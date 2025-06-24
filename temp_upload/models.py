"""Data models for Renaissance Weekly"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
import hashlib


class TranscriptSource(Enum):
    """Sources for podcast transcripts"""
    OFFICIAL = "official"          # From podcast website
    API = "api"                    # From transcript API
    COMMUNITY = "community"        # From community sources
    GENERATED = "generated"        # We transcribed it
    CACHED = "cached"             # From our cache


@dataclass
class Episode:
    """Podcast episode data model"""
    podcast: str
    title: str
    published: datetime
    audio_url: Optional[str] = None
    transcript_url: Optional[str] = None
    transcript_source: Optional[TranscriptSource] = None
    description: str = ""
    link: str = ""
    duration: str = "Unknown"
    guid: str = ""  # Unique identifier
    
    def __post_init__(self):
        if not self.guid:
            # Create unique ID from podcast + title + date
            self.guid = hashlib.md5(
                f"{self.podcast}:{self.title}:{self.published}".encode()
            ).hexdigest()