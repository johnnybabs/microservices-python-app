FROM python:3.10-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests build-essential libpq-dev python3-dev ffmpeg && pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app

# Run as a non-root uid (matches the Kubernetes securityContext runAsUser: 1000).
# The consumer writes ffmpeg temp files and the /tmp/healthy heartbeat to /tmp,
# which is world-writable (mode 1777) and backed by a writable emptyDir in k8s.
USER 1000

CMD ["python", "consumer.py"]