"""Utility helper functions"""

import os
import re
from typing import List
from .logging import get_logger


def validate_env_vars():
    """Validate required environment variables"""
    required = ["OPENAI_API_KEY", "SENDGRID_API_KEY"]
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    email_to = os.getenv("EMAIL_TO", "caddington05@gmail.com")
    if not email_to or email_to == "caddington05@gmail.com":
        logger = get_logger(__name__)
        logger.info("📧 Using default email: caddington05@gmail.com")
        logger.info("💡 To change, set EMAIL_TO in your .env file")


def slugify(text: str) -> str:
    """Convert text to filename-safe string"""
    # Remove or replace invalid filename characters
    invalid_chars = '<>:"/\\|?*'
    safe_text = text
    for char in invalid_chars:
        safe_text = safe_text.replace(char, '_')
    
    # Replace multiple underscores with single
    safe_text = re.sub(r'_+', '_', safe_text)
    
    # Limit length and clean up
    safe_text = safe_text[:100].strip('_')
    
    return safe_text


def format_duration(duration_str: str) -> str:
    """Format duration string into human-readable format"""
    if not duration_str or duration_str == "Unknown":
        return "Unknown"
    
    # Handle HH:MM:SS format
    if ':' in str(duration_str):
        parts = str(duration_str).split(':')
        try:
            if len(parts) == 3:  # HH:MM:SS
                hours = int(parts[0])
                minutes = int(parts[1])
            elif len(parts) == 2:  # MM:SS
                hours = 0
                minutes = int(parts[0])
            else:
                return str(duration_str)
            
            if hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
        except:
            return str(duration_str)
    
    # If already has text like "hour" or "minute", return as is
    if any(word in str(duration_str).lower() for word in ['hour', 'minute', 'second']):
        return str(duration_str)
    
    try:
        # Assume it's seconds if it's just a number
        if str(duration_str).isdigit():
            seconds = int(duration_str)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            
            if hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
                
    except:
        pass
    
    return str(duration_str)


def seconds_to_duration(seconds: int) -> str:
    """Convert seconds to duration string"""
    if seconds <= 0:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"