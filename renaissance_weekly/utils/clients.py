"""API clients initialization"""

import os
from openai import OpenAI
from sendgrid import SendGridAPIClient
from dotenv import load_dotenv
from .helpers import RateLimiter
from .logging import get_logger

load_dotenv()
logger = get_logger(__name__)

# Global rate limiter for OpenAI API (50 requests per minute with 10% buffer = 45 effective)
openai_rate_limiter = RateLimiter(max_requests_per_minute=50, buffer_percentage=0.1)

# Initialize clients with improved settings
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=300.0,  # 5 minute timeout for long transcriptions
    max_retries=0   # We handle retries ourselves for better control
)

# Log rate limiter initialization
logger.info("OpenAI client initialized with global rate limiter (45 req/min effective)")

sendgrid_client = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))