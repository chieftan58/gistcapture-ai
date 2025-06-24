"""API clients initialization"""

import os
from openai import OpenAI
from sendgrid import SendGridAPIClient
from dotenv import load_dotenv

load_dotenv()

# Initialize clients with improved settings
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=300.0,  # 5 minute timeout for long transcriptions
    max_retries=2   # Retry failed requests
)

sendgrid_client = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))