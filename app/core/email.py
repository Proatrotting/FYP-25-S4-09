import smtplib
from email.message import EmailMessage
import os

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

if not SMTP_EMAIL or not SMTP_PASSWORD:
    raise RuntimeError("SMTP credentials not configured")


def send_email(to: str, subject: str, body: str):
    msg = EmailMessage()
    msg["From"] = SMTP_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
