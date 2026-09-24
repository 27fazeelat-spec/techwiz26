"""Plain-text email over SMTP, only when the server is configured through environment variables:

    MAIL_SERVER, MAIL_PORT (default 587), MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM (default MAIL_USERNAME)

Without them nothing is sent and the caller offers a ready-made draft instead (see the console's approve page).
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


def configured():
    return bool(os.environ.get("MAIL_SERVER") and os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_PASSWORD"))


def send(to, subject, body):
    """Return (sent, error). Uses STARTTLS with certificate verification."""
    if not configured():
        return False, "Email is not set up on this server."
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ["MAIL_USERNAME"]
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["MAIL_SERVER"], int(os.environ.get("MAIL_PORT", "587")), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True, None
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"The email could not be sent ({exc.__class__.__name__})."
