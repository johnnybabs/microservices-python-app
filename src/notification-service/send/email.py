import json
import os
import smtplib
from email.message import EmailMessage

from jsonlog import get_logger

log = get_logger("notification")


def notification(message):
    """Send the "your audio is ready" email to the user who uploaded the video.

    Returns None on success OR on a deliberate skip (the caller ACKs and moves
    on); returns a truthy error string only for a *retryable* failure (the caller
    NACKs). It never raises — an unhandled exception here crashes the consumer
    pod, which is exactly the CrashLoopBackOff this hardening removes.

    Recipient routing: the message carries `username` (the uploader's email, put
    there by the gateway from the validated JWT and forwarded through the
    converter). This is the standard SaaS "notify the user who triggered the
    action" pattern — the address never comes from a hardcoded value.
    """
    try:
        message = json.loads(message)
    except (ValueError, TypeError) as err:
        # Unparseable body — it will never succeed on retry, so drop it (ACK).
        log.warning("Dropping unparseable message", correlation_id="legacy", error=str(err))
        return None

    mp3_fid = message.get("mp3_fid")
    receiver_address = message.get("username")
    correlation_id = message.get("correlation_id", "legacy")

    # Backward compatibility: messages published before per-user routing existed
    # have no `username`. Skip (ACK) rather than crash or loop forever on them.
    if not receiver_address:
        log.info("No username on message, skipping email", correlation_id=correlation_id, mp3_fid=mp3_fid)
        return None

    sender_address = os.environ.get("GMAIL_ADDRESS")
    sender_password = os.environ.get("GMAIL_PASSWORD")

    msg = EmailMessage()
    msg.set_content(
        "Your VidCast audio is ready.\n\n"
        f"File ID: {mp3_fid}\n\n"
        "Download it from the VidCast app using this file ID."
    )
    msg["Subject"] = "Your VidCast audio is ready"
    msg["From"] = sender_address
    msg["To"] = receiver_address

    try:
        session = smtplib.SMTP("smtp.gmail.com", 587)
        session.starttls()
        session.login(sender_address, sender_password)
        session.send_message(msg, sender_address, receiver_address)
        session.quit()
    except Exception as err:
        # Retryable (transient network, or a bad credential that may be fixed by
        # rotating the secret). Returning an error makes the consumer NACK so the
        # message is requeued. NOTE: a *permanently* bad credential will requeue
        # in a loop — in production we'd bound that with a dead-letter queue and a
        # max-retry policy. Deliberately out of scope here (no new infra).
        log.error("Email send failed", correlation_id=correlation_id, mp3_fid=mp3_fid, error=str(err))
        return f"email send failed: {err}"

    log.info("Mail sent", correlation_id=correlation_id, mp3_fid=mp3_fid, recipient=receiver_address)
    return None
