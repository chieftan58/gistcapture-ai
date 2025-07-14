"""Centralized filename generation utilities for audio files"""

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import Episode


def sanitize_podcast_name(name: str, max_length: int = 20) -> str:
    """Sanitize podcast name for filename use"""
    # Remove special characters, keep only alphanumeric and basic punctuation
    sanitized = re.sub(r'[^\w\s-]', '', name)
    # Replace spaces with nothing to shorten
    sanitized = re.sub(r'\s+', '', sanitized)
    # Truncate to max length
    return sanitized[:max_length]


def extract_episode_number(title: str) -> str:
    """Extract episode number from title"""
    # Look for patterns like #123, Episode 123, Ep 123, etc.
    patterns = [
        r'#(\d+)',
        r'episode\s+(\d+)',
        r'ep\.?\s*(\d+)',
        r'\b(\d+)\b'  # Any standalone number (last resort)
    ]
    
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return f"ep{match.group(1)}"
    
    return "ep000"  # Default if no number found


def generate_content_hash(episode: Episode) -> str:
    """Generate consistent hash from episode content"""
    # Use podcast, title, and published date (date only, not time) for consistent hashing
    if episode.published:
        published_str = episode.published.strftime('%Y-%m-%d')  # Date only, ignore time
    else:
        published_str = "unknown"
    hash_input = f"{episode.podcast}|{episode.title}|{published_str}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:6]


def generate_audio_filename(episode: Episode, mode: str = 'test') -> str:
    """
    Generate standardized audio filename
    
    Format: YYYYMMDD_PodcastName_ep123_hash6_mode.mp3
    Example: 20250114_TimFerriss_ep818_a7b2c3_test.mp3
    
    Args:
        episode: Episode object with podcast, title, published date
        mode: 'test' or 'full' transcription mode
        
    Returns:
        Filename string (without path)
    """
    # Date component (8 chars)
    if episode.published:
        date_str = episode.published.strftime('%Y%m%d')
    else:
        date_str = datetime.now().strftime('%Y%m%d')
    
    # Podcast component (max 20 chars, alphanumeric only)
    podcast_clean = sanitize_podcast_name(episode.podcast)
    
    # Episode number component
    ep_number = extract_episode_number(episode.title)
    
    # Hash component (6 chars for uniqueness)
    content_hash = generate_content_hash(episode)
    
    # Mode component
    mode_clean = mode.lower()
    
    # Combine all components
    filename = f"{date_str}_{podcast_clean}_{ep_number}_{content_hash}_{mode_clean}.mp3"
    
    return filename


def generate_temp_filename(base_name: str, suffix: str = ".mp3") -> str:
    """
    Generate short temporary filename for trimming operations
    
    Args:
        base_name: Base identifier (e.g., correlation_id, file path)
        suffix: File extension
        
    Returns:
        Short filename for /tmp use
    """
    # Use first 8 chars of hash for temp files
    temp_hash = hashlib.md5(base_name.encode()).hexdigest()[:8]
    return f"trim_{temp_hash}{suffix}"


def parse_audio_filename(filename: str) -> Optional[dict]:
    """
    Parse standardized audio filename back to components
    
    Args:
        filename: Audio filename (with or without extension)
        
    Returns:
        Dict with parsed components or None if not parseable
    """
    # Remove extension
    name_without_ext = Path(filename).stem
    
    # Expected pattern: YYYYMMDD_PodcastName_ep123_hash6_mode
    pattern = r'^(\d{8})_([^_]+)_(ep\d+)_([a-f0-9]{6})_([^_]+)$'
    match = re.match(pattern, name_without_ext)
    
    if match:
        return {
            'date': match.group(1),
            'podcast': match.group(2),
            'episode_number': match.group(3),
            'content_hash': match.group(4),
            'mode': match.group(5)
        }
    
    return None


def is_standardized_filename(filename: str) -> bool:
    """Check if filename follows our standardized format"""
    return parse_audio_filename(filename) is not None


# For backwards compatibility and debugging
def legacy_filename_to_new(old_filename: str, episode: Episode, mode: str) -> str:
    """
    Convert old-style filename to new standardized format
    Useful for migration or debugging
    """
    return generate_audio_filename(episode, mode)