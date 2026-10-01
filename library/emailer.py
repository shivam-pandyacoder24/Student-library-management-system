"""Sending OTP emails through Brevo (HTTPS API), SMTP (e.g. Gmail), or demo mode."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

import requests
from flask import current_app, render_template

log = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class EmailError(Exception):
    """Raised when an email could not be delivered to the provider."""


def provider():
    cfg = current_app.config
    if cfg.get("TESTING_OUTBOX"):
        return "outbox"
    if cfg["BREVO_API_KEY"]:
        return "brevo"
    if cfg["SMTP_HOST"] and cfg["SMTP_USERNAME"] and cfg["SMTP_PASSWORD"]:
        return "smtp"
    return "demo"


def is_demo_mode():
    return provider() == "demo"


def send_otp_email(to_email, name, code, purpose):
    cfg = current_app.config
    subject = f"{code} is your {cfg['LIBRARY_NAME']} verification code"
    context = dict(
        name=name,
        code=code,
        purpose=purpose,
        minutes=cfg["OTP_TTL_MINUTES"],
        library_name=cfg["LIBRARY_NAME"],
    )
    html = render_template("email/otp.html", **context)
    text = render_template("email/otp.txt", **context)
    send_email(to_email, subject, html, text)


def send_email(to_email, subject, html, text):
    kind = provider()
    cfg = current_app.config

    if kind == "outbox":  # used by the test-suite
        current_app.extensions.setdefault("outbox", []).append(
            {"to": to_email, "subject": subject, "text": text}
        )
        return

    if kind == "demo":
        log.warning("Email is not configured; demo mode. To %s: %s", to_email, subject)
        print(f"[demo email] to={to_email} subject={subject}", flush=True)
        return

    sender_email = cfg["MAIL_FROM_EMAIL"]
    if not sender_email:
        raise EmailError("MAIL_FROM_EMAIL is not set on the server.")

    if kind == "brevo":
        try:
            resp = requests.post(
                BREVO_URL,
                headers={
                    "api-key": cfg["BREVO_API_KEY"],
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json={
                    "sender": {"name": cfg["MAIL_FROM_NAME"], "email": sender_email},
                    "to": [{"email": to_email}],
                    "subject": subject,
                    "htmlContent": html,
                    "textContent": text,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise EmailError(f"Could not reach the email service ({exc.__class__.__name__}).") from exc
        if resp.status_code >= 300:
            log.error("Brevo error %s: %s", resp.status_code, resp.text[:300])
            raise EmailError(f"The email service rejected the message (HTTP {resp.status_code}).")
        return

    # SMTP
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{cfg['MAIL_FROM_NAME']} <{sender_email}>"
    msg["To"] = to_email
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        context = ssl.create_default_context()
        if cfg["SMTP_USE_SSL"]:
            with smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], context=context, timeout=20) as smtp:
                smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as smtp:
                smtp.starttls(context=context)
                smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("SMTP send failed: %r", exc)
        raise EmailError(f"Could not send the email ({exc.__class__.__name__}).") from exc
