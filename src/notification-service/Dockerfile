FROM python:3.10-slim-bookworm

# ffmpeg removed: the notification service only consumes the mp3 queue and sends
# email via SMTP. It never invokes ffmpeg/moviepy, so the ~100MB media toolchain
# was dead weight inherited by copy-paste from the converter Dockerfile.
RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests build-essential libpq-dev python3-dev && pip install --no-cache-dir --upgrade pip

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir --requirement /app/requirements.txt
COPY . /app

CMD ["python", "consumer.py"]