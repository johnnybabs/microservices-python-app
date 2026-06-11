import datetime
import gridfs
import json
import os
import time
import uuid

import pika
import requests
from bson.objectid import ObjectId
from flask import Flask, g, jsonify, request, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_pymongo import PyMongo
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)

from auth import validate
from auth_svc import access
from storage import util
from metrics import IN_FLIGHT, REQUEST_COUNT, REQUEST_LATENCY, UPLOADS
from jsonlog import get_logger

server = Flask(__name__)
CORS(server)

# I8/P3 structured logging.
log = get_logger("gateway")

# A10 rate limiting. flask-limiter backed by the EXISTING in-cluster Redis so the
# counters are shared across gunicorn's worker processes (an in-memory store would
# count per-worker → N× the intended limit). Port is fixed at the redis Service's
# 6379: we deliberately do NOT read a REDIS_PORT env var because the in-namespace
# `redis` Service injects REDIS_PORT=tcp://<ip>:6379 via Docker service links (the
# gateway Deployment, unlike the consumers, does not set enableServiceLinks:false),
# which would corrupt the URI.
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")


def _client_ip():
    # The gateway is behind the frontend's nginx (and the ALB), so request.remote_addr
    # is the proxy, not the user. Key the limit on the real client from the first
    # X-Forwarded-For hop, falling back to the socket peer. Keying on the proxy IP
    # instead would collapse /login into ONE global bucket (a lockout DoS). Caveat:
    # XFF is client-spoofable (nginx appends rather than replaces) — documented in
    # docs/OBSERVABILITY.md as a known limitation of app-layer IP limiting here.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address()


limiter = Limiter(
    _client_ip,
    app=server,
    storage_uri=f"redis://{REDIS_HOST}:6379",
    strategy="fixed-window",
    default_limits=[],  # no global limit — only /login and /upload are decorated
    # Degrade to a per-process in-memory limiter if Redis is unreachable (e.g. the
    # gateway→redis NetworkPolicy egress rule has not been applied yet) rather than
    # failing the request. See docs/OBSERVABILITY.md.
    in_memory_fallback_enabled=True,
)

# B4 SLO instrumentation. We record every request EXCEPT the scrape itself and the
# liveness check, so /metrics polling and probes don't pollute the availability SLI.
_UNMETERED = {"metrics", "healthz"}


@server.before_request
def _metrics_before():
    # I8/P3: a fresh correlation id per request, attached to every log line and
    # threaded into the RabbitMQ message so one upload is greppable end to end.
    g.correlation_id = str(uuid.uuid4())
    if request.endpoint in _UNMETERED:
        return
    g._start = time.perf_counter()
    IN_FLIGHT.inc()


@server.after_request
def _metrics_after(response):
    if request.endpoint in _UNMETERED:
        return response
    # endpoint may be None for unmatched routes (404) — bucket those as "unknown".
    endpoint = request.endpoint or "unknown"
    REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
    start = g.pop("_start", None)
    if start is not None:
        REQUEST_LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - start)
    IN_FLIGHT.dec()
    return response


@server.route("/metrics", methods=["GET"])
def metrics():
    # Aggregate the per-worker sample files into one exposition payload.
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return generate_latest(registry), 200, {"Content-Type": CONTENT_TYPE_LATEST}

mongo_video = PyMongo(server, uri=os.environ.get('MONGODB_VIDEOS_URI'))

mongo_mp3 = PyMongo(server, uri=os.environ.get('MONGODB_MP3S_URI'))

fs_videos = gridfs.GridFS(mongo_video.db)
fs_mp3s = gridfs.GridFS(mongo_mp3.db)

# A1 transactional outbox. The `outbox` collection lives in the same database as
# the video GridFS (mongo_video.db), so the GridFS write and the outbox insert go
# through the same MongoDB client. OUTBOX_ENABLED defaults to false → the gateway
# publishes directly to RabbitMQ exactly as before; set it to "true" to route
# uploads through the outbox (the outbox-relay then publishes them). See
# storage/util.py and OUTBOX_EXPLAINED.md.
outbox = mongo_video.db.outbox
OUTBOX_ENABLED = os.environ.get("OUTBOX_ENABLED", "false").strip().lower() == "true"

rabbitmq_credentials = pika.PlainCredentials(
    os.environ.get("RABBITMQ_DEFAULT_USER", "guest"),
    os.environ.get("RABBITMQ_DEFAULT_PASS", "guest"),
)
connection = pika.BlockingConnection(
    pika.ConnectionParameters(host="rabbitmq", credentials=rabbitmq_credentials, heartbeat=0)
)
channel = connection.channel()

@server.route("/healthz", methods=["GET"])
def healthz():
    checks = {}
    status_code = 200
    try:
        mongo_video.db.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = str(e)
        status_code = 503
    try:
        conn = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=os.environ.get("RABBITMQ_HOST", "rabbitmq"),
                credentials=rabbitmq_credentials,
                heartbeat=0,
            )
        )
        conn.close()
        checks["rabbitmq"] = "ok"
    except Exception as e:
        checks["rabbitmq"] = str(e)
        status_code = 503
    return jsonify({"status": "ok" if status_code == 200 else "degraded", "checks": checks}), status_code

@server.route("/login", methods=["POST"])
@limiter.limit("10 per minute")  # A10: brute-force protection on credential checks
def login():
    token, err = access.login(request)

    if not err:
        return token
    log.warning("Login rejected", correlation_id=g.correlation_id)
    return err

@server.route("/register", methods=["POST"])
def register():
    token, err = access.register(request)

    if not err:
        return token, 201
    else:
        return err

@server.route("/upload", methods=["POST"])
@limiter.limit("20 per hour")  # A10: conservative per-client upload quota
def upload():
    access, err = validate.token(request)

    if err:
        return err

    access = json.loads(access)

    # AUTHORIZATION: uploading is a core action available to ANY authenticated
    # user, not just admins. We previously gated on access["admin"], which only
    # worked because every JWT claimed admin=true. With real RBAC, admin is
    # reserved for privileged views (Dashboard/Architecture/Users); a valid token
    # is all that's required to upload.
    if not access:
        return "not authorized", 401

    if len(request.files) > 1 or len(request.files) < 1:
        return "exactly 1 file required", 400

    for _, f in request.files.items():
        err = util.upload(
            f, fs_videos, channel, access, outbox, OUTBOX_ENABLED,
            correlation_id=g.correlation_id,
        )

        if err:
            return err

    # SLO 3 numerator denominator source: count one accepted video per upload that
    # reached the queue/outbox without error (we returned above on failure).
    UPLOADS.inc()
    log.info("Upload accepted", correlation_id=g.correlation_id, user=access["username"])
    return "success!", 200

@server.route("/download", methods=["GET"])
def download():
    access, err = validate.token(request)

    if err:
        return err

    access = json.loads(access)

    # AUTHORIZATION: downloading is available to any authenticated user (same
    # rationale as /upload). Per-user ownership scoping of downloads is layered on
    # in Fix 2 via GridFS owner_email metadata; here we only require a valid token.
    if not access:
        return "not authorized", 401

    fid_string = request.args.get("fid")

    if not fid_string:
        return "fid is required", 400

    try:
        out = fs_mp3s.get(ObjectId(fid_string))
        # A12 download audit: who downloaded which file, when, and how big.
        log.info(
            "File downloaded",
            correlation_id=g.correlation_id,
            fid=fid_string,
            user=access.get("username", "unknown"),
            file_size_bytes=getattr(out, "length", None),
        )
        return send_file(out, download_name=f"{fid_string}.mp3")
    except Exception as err:
        log.error(
            "Download failed",
            correlation_id=g.correlation_id,
            fid=fid_string,
            error=str(err),
        )
        return "internal server error", 500


@server.route("/my-files", methods=["GET"])
def my_files():
    """List the converted mp3s owned by the current user, newest first.

    Ownership is the metadata.owner_email tag written on the GridFS object at
    conversion time (converter) — set from the uploader's JWT username. Files
    uploaded before per-user ownership existed have no tag and simply don't
    appear here (correct: they predate the concept; no backfill needed).
    """
    access, err = validate.token(request)
    if err:
        return err
    access = json.loads(access)
    if not access:
        return "not authorized", 401

    owner = access["username"]
    files = []
    for f in fs_mp3s.find({"metadata.owner_email": owner}).sort("uploadDate", -1):
        files.append({
            "fid": str(f._id),
            "filename": f.filename,
            "size": f.length,
            "created": f.upload_date.isoformat() if f.upload_date else None,
        })
    return jsonify({"files": files}), 200


@server.route("/notifications/unseen-count", methods=["GET"])
def unseen_count():
    """Count this user's completed mp3s created since `since` (ISO-8601).

    The frontend polls this for the Download bubble badge and passes the
    timestamp of the user's last visit to the Download page as `since`, so the
    badge reflects only conversions completed since they last looked.
    """
    access, err = validate.token(request)
    if err:
        return err
    access = json.loads(access)
    if not access:
        return "not authorized", 401

    since = request.args.get("since", "1970-01-01T00:00:00")
    try:
        since_dt = datetime.datetime.fromisoformat(since)
    except ValueError:
        since_dt = datetime.datetime(1970, 1, 1)

    # count_documents on the GridFS files collection — PyMongo 4 removed
    # Cursor.count(), and counting server-side avoids streaming file docs.
    count = mongo_mp3.db["fs.files"].count_documents({
        "metadata.owner_email": access["username"],
        "uploadDate": {"$gt": since_dt},
    })
    return jsonify({"count": count}), 200


def _require_admin(request):
    """Validate the JWT and require the admin role. Returns (claims, None) on
    success or (None, (body, status)) to return directly. This is where admin
    authorization is enforced — the auth-service /users endpoints trust it."""
    raw, err = validate.token(request)
    if err:
        return None, err
    claims = json.loads(raw)
    if not claims or not claims.get("admin"):
        return None, ("admin only", 403)
    return claims, None


def _conversion_counts():
    """Map of owner_email -> number of converted mp3s, from a Mongo aggregation."""
    pipeline = [{"$group": {"_id": "$metadata.owner_email", "count": {"$sum": 1}}}]
    return {
        doc["_id"]: doc["count"]
        for doc in mongo_mp3.db["fs.files"].aggregate(pipeline)
        if doc["_id"]
    }


@server.route("/admin/users", methods=["GET"])
def admin_users():
    claims, err = _require_admin(request)
    if err:
        return err

    auth_addr = os.environ.get("AUTH_SVC_ADDRESS")
    try:
        resp = requests.get(f"http://{auth_addr}/users", timeout=5)
    except Exception as e:
        return f"auth service unreachable: {e}", 502
    if resp.status_code != 200:
        return resp.text, resp.status_code

    users = resp.json()
    counts = _conversion_counts()
    for u in users:
        u["conversions"] = counts.get(u["email"], 0)
    return jsonify(users), 200


@server.route("/admin/users/<email>", methods=["PATCH"])
def admin_update_user(email):
    claims, err = _require_admin(request)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    role = data.get("role")
    if role not in ("user", "admin"):
        return "role must be 'user' or 'admin'", 400

    caller = claims.get("username")
    auth_addr = os.environ.get("AUTH_SVC_ADDRESS")

    # Guardrail 1: an admin cannot change their own role (no accidental self-lockout).
    if email == caller:
        return "cannot change your own role", 403

    # Guardrail 2: refuse a demotion that would leave zero admins (cluster lockout).
    if role == "user":
        try:
            resp = requests.get(f"http://{auth_addr}/users", timeout=5)
            resp.raise_for_status()
            admin_emails = {u["email"] for u in resp.json() if u.get("role") == "admin"}
        except Exception as e:
            return f"auth service unreachable: {e}", 502
        if admin_emails == {email}:
            return "cannot demote the last remaining admin", 409

    try:
        resp = requests.patch(
            f"http://{auth_addr}/users/{email}", json={"role": role}, timeout=5
        )
    except Exception as e:
        return f"auth service unreachable: {e}", 502

    # Audit trail (captured in gateway pod logs): who changed whom, to what role.
    log.info(
        "Admin role change",
        correlation_id=g.correlation_id,
        admin=caller,
        target=email,
        new_role=role,
        result=resp.status_code,
    )
    return resp.text, resp.status_code


if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8080)
