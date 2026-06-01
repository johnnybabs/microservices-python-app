FROM python:3.10-slim-bookworm

# ffmpeg removed: the notification service only consumes the mp3 queue and sends
# email via SMTP. It never invokes ffmpeg/moviepy, so the ~100MB media toolchain
# was dead weight inherited by copy-paste from the converter Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests build-essential libpq-dev python3-dev && pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app

# Run as a non-root uid (matches the Kubernetes securityContext runAsUser: 1000).
# The consumer writes the /tmp/healthy heartbeat to /tmp, which is world-writable
# (mode 1777) and backed by a writable emptyDir in k8s.
USER 1000

CMD ["python", "consumer.py"]