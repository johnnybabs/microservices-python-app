FROM python:3.10-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests build-essential libpq-dev python3-dev && pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app

EXPOSE 8080

# Run as a non-root uid (matches the Kubernetes securityContext runAsUser: 1000).
# Port 8080 is >1024 so no privileged binding is required; /app is world-readable.
USER 1000

CMD ["python", "server.py"]