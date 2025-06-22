# email_sender.py

import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv

load_dotenv()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_TO = os.getenv("EMAIL_TO")

def send_email(subject: str, body: str):
    if not SENDGRID_API_KEY or not EMAIL_FROM or not EMAIL_TO:
        raise ValueError("Missing SendGrid environment variables.")

    message = Mail(
        from_email=EMAIL_FROM,
        to_emails=EMAIL_TO,
        subject=subject,
        plain_text_content=body
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"📬 Email sent! Status Code: {response.status_code}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
