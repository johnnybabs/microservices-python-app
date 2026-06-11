import datetime
import json
import time

import pika

from jsonlog import get_logger

log = get_logger("gateway")


def upload(f, fs, channel, access, outbox=None, outbox_enabled=False, correlation_id="none"):
    try:
        # Tag the stored video with its owner (the uploader's JWT email) and a
        # filename. owner_email is what /my-files and the unseen-count badge
        # query on; the converter copies the same tag onto the resulting mp3.
        fid = fs.put(
            f,
            filename=getattr(f, "filename", None),
            metadata={"owner_email": access["username"]},
        )
    except Exception as err:
        log.error("GridFS store failed", correlation_id=correlation_id, error=str(err))
        return "internal server error, fs level", 500

    # correlation_id rides in the message body so the converter and notification
    # service log the same id — one upload is greppable across all services (I8/P3).
    message = {
        "video_fid": str(fid),
        "mp3_fid": None,
        "username": access["username"],
        "correlation_id": correlation_id,
    }

    # A1 transactional outbox. When OUTBOX_ENABLED is true the gateway does NOT
    # publish to RabbitMQ here — it records the event in the MongoDB `outbox`
    # collection, and the single-replica outbox-relay publishes it asynchronously
    # on its next poll. This guarantees the event survives a broker outage at
    # upload time: the row is durable in Mongo even if RabbitMQ is down, and gets
    # published once the broker recovers. The compensating fs.delete is KEPT as a
    # belt-and-braces fallback (per PHASE_UP_PLAN §7.5) — if the outbox write
    # itself fails, we roll back the orphaned GridFS object, exactly as the
    # direct-publish path does on a broker failure. It is removed only in a clean
    # follow-up once the outbox is proven in a live soak.
    #
    # Consistency note (honest): on the in-cluster mongo:4.0.8 standalone there is
    # no multi-document transaction (that needs a replica set), so the GridFS put
    # and the outbox insert are two sequential writes, not one atomic unit. The
    # ordering (GridFS first, then outbox) plus the compensating delete bounds the
    # failure window to "process crash between the two writes" — which orphans a
    # video with no event, the same window the direct-publish path already has.
    # True atomicity is a documented benefit of managed Mongo (Atlas replica set);
    # see MANAGED_SERVICES.md §3.
    if outbox_enabled and outbox is not None:
        try:
            outbox.insert_one(
                {
                    "event_type": "video.uploaded",
                    "routing_key": "video",
                    "payload": message,
                    "created_at": datetime.datetime.utcnow(),
                    "published_at": None,
                }
            )
        except Exception as err:
            log.error("Outbox write failed", correlation_id=correlation_id, error=str(err))
            fs.delete(fid)
            return f"internal server error, outbox write failed, {err}", 500
        log.info("Upload queued via outbox", correlation_id=correlation_id, video_fid=str(fid))
        return None

    # Legacy direct-publish path (OUTBOX_ENABLED=false, the default). Preserved
    # verbatim so behaviour is identical to today when the flag is off.
    try:
        channel.basic_publish(
            exchange="",
            routing_key="video",
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE,
                # B4 SLO 2 clock start: stamp the publish time so the converter can
                # record publish→mp3-write latency. The outbox-relay sets the same
                # property on its publish path, keeping the SLI consistent.
                timestamp=int(time.time()),
            ),
        )
        log.info("Upload published", correlation_id=correlation_id, video_fid=str(fid))
    except Exception as err:
        log.error("RabbitMQ publish failed", correlation_id=correlation_id, error=str(err))
        fs.delete(fid)
        return f"internal server error rabbitmq issue, {err}", 500
