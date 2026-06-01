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

connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq", heartbeat=0))
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
            pika.ConnectionParameters(host=os.environ.get("RABBITMQ_HOST", "rabbitmq"), heartbeat=0)
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

@server.route("/upload", methods=["POST"])
def upload():
    access, err = validate.token(request)

    if err:
        return err

    access = json.loads(access)

    if access["admin"]:
        if len(request.files) > 1 or len(request.files) < 1:
            return "exactly 1 file required", 400

        for _, f in request.files.items():
            err = util.upload(f, fs_videos, channel, access)

            if err:
                return err

        return "success!", 200
    else:
        return "not authorized", 401

@server.route("/download", methods=["GET"])
def download():
    access, err = validate.token(request)

    if err:
        return err

    access = json.loads(access)

    if access["admin"]:
        fid_string = request.args.get("fid")

        if not fid_string:
            return "fid is required", 400

        try:
            out = fs_mp3s.get(ObjectId(fid_string))
            return send_file(out, download_name=f"{fid_string}.mp3")
        except Exception as err:
            print(err)
            return "internal server error", 500

    return "not authorized", 401


if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8080)
