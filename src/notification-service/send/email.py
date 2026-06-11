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
    # UX2: name the file in the email; .get default for pre-Sprint-4 messages.
    original_filename = message.get("original_filename") or "your file"

    # Backward compatibility: messages published before per-user routing existed
    # have no `username`. Skip (ACK) rather than crash or loop forever on them.
    if not receiver_address:
        log.info("No username on message, skipping email", correlation_id=correlation_id, mp3_fid=mp3_fid)
        return None

    sender_address = os.environ.get("GMAIL_ADDRESS")
    sender_password = os.environ.get("GMAIL_PASSWORD")
    # UX2: public URL of the VidCast web app for the "go to your conversions" link.
    # Defaults to a dev placeholder; set VIDCAST_URL to the real ALB hostname in the
    # prod overlay. Documented in docs/OBSERVABILITY.md.
    vidcast_url = os.environ.get("VIDCAST_URL", "http://localhost:30006").rstrip("/")
    # Friendly greeting name from the email local-part (matches the JWT display_name
    # derivation; the message doesn't carry display_name).
    display_name = receiver_address.split("@")[0]

    msg = EmailMessage()
    # UX2: subject names the file; body adds a reference (correlation_id) for
    # support and links to the authenticated conversions page — note it no longer
    # prints the mp3 file id (the download key), tightening A8.
    msg.set_content(
        f"Hi {display_name},\n\n"
        "Your video has been converted to audio and is ready for download.\n\n"
        f"File: {original_filename}\n"
        f"Reference: {correlation_id}\n\n"
        "Download your audio by logging in to VidCast and visiting your\n"
        f"conversions page:\n{vidcast_url}/my-files\n\n"
        "Keep this reference number if you need to contact support about this\n"
        f"conversion: {correlation_id}\n\n"
        "— The VidCast Platform"
    )
    msg["Subject"] = f"Your audio is ready: {original_filename}"
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
