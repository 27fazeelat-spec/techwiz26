"""Plain-text email, sent one of two ways (both configured through environment variables):

1. Brevo's HTTPS API, when BREVO_API_KEY is set. Works on hosts that block outgoing SMTP (Railway's trial and
   hobby plans do). MAIL_FROM must be a sender address verified in Brevo; MAIL_FROM_NAME is optional.
2. SMTP with STARTTLS, when MAIL_SERVER, MAIL_USERNAME and MAIL_PASSWORD are set (MAIL_PORT defaults to 587).

Without either nothing is sent and the caller offers a ready-made draft instead (see the console's approve page).
Tests never send email.
"""
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def _testing():
    from flask import current_app, has_app_context
    return has_app_context() and current_app.testing


def method():
    if _testing():
        return None
    if os.environ.get("BREVO_API_KEY") and _sender():
        return "brevo"
    if os.environ.get("MAIL_SERVER") and os.environ.get("MAIL_USERNAME") and os.environ.get("MAIL_PASSWORD"):
        return "smtp"
    return None


def configured():
    return method() is not None


def _sender():
    return os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")


def send(to, subject, body):
    """Return (sent, error). The error names the cause so the console can say what went wrong."""
    how = method()
    if how is None:
        return False, "Email is not set up on this server."
    try:
        if how == "brevo":
            return _send_brevo(to, subject, body)
        return _send_smtp(to, subject, body)
    except Exception as exc:                                       # never lose the demo login over an email error
        return False, f"The email could not be sent ({exc.__class__.__name__}: {exc})."


def _send_brevo(to, subject, body):
    payload = {"sender": {"email": _sender(), "name": os.environ.get("MAIL_FROM_NAME", "SkillSprint")},
               "to": [{"email": to}], "subject": subject, "textContent": body}
    request = urllib.request.Request(BREVO_URL, data=json.dumps(payload).encode(), method="POST",
                                     headers={"api-key": os.environ["BREVO_API_KEY"], "Content-Type": "application/json",
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
            if 200 <= response.status < 300:
                return True, None
            return False, f"The email service answered {response.status}."
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        return False, f"The email service refused the message ({exc.code}: {detail})."


def _send_smtp(to, subject, body):
    msg = EmailMessage()
    msg["From"] = _sender()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["MAIL_SERVER"], int(os.environ.get("MAIL_PORT", "587")), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
            smtp.send_message(msg)
        return True, None
    except smtplib.SMTPException as exc:                           # reached the server, which said no
        return False, f"The email server refused the message ({exc.__class__.__name__}: {exc})."
    except OSError as exc:                                         # never reached the server
        hint = " This host may block outgoing email (SMTP); set BREVO_API_KEY to send through Brevo instead."
        return False, f"The email could not be sent ({exc.__class__.__name__}: {exc}).{hint}"
