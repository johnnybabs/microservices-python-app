import datetime
import gridfs
import json
import os

import pika
from bson.objectid import ObjectId
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_pymongo import PyMongo

from auth import validate
from auth_svc import access
from storage import util

server = Flask(__name__)
CORS(server)

mongo_video = PyMongo(server, uri=os.environ.get('MONGODB_VIDEOS_URI'))

mongo_mp3 = PyMongo(server, uri=os.environ.get('MONGODB_MP3S_URI'))

fs_videos = gridfs.GridFS(mongo_video.db)
fs_mp3s = gridfs.GridFS(mongo_mp3.db)

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
def login():
    token, err = access.login(request)

    if not err:
        return token
    else:
        return err

@server.route("/register", methods=["POST"])
def register():
    token, err = access.register(request)

    if not err:
        return token, 201
    else:
        return err

@server.route("/upload", methods=["POST"])
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
        err = util.upload(f, fs_videos, channel, access)

        if err:
            return err

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
        return send_file(out, download_name=f"{fid_string}.mp3")
    except Exception as err:
        print(err)
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


if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8080)
