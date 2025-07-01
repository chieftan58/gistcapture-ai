"""Data models for Renaissance Weekly"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TranscriptSource(Enum):
    """Source of transcript"""
    RSS_FEED = "rss_feed"
    SCRAPED = "scraped"
    GENERATED = "generated"
    API = "api"
    CACHED = "cached"


@dataclass
class Episode:
    """Podcast episode data model"""
    podcast: str
    title: str
    published: datetime
    audio_url: Optional[str] = None
    transcript_url: Optional[str] = None
    description: Optional[str] = None
    link: Optional[str] = None
    duration: str = "Unknown"
    guid: Optional[str] = None
    apple_podcast_id: Optional[str] = None
    
    def __post_init__(self):
        """Ensure datetime objects are timezone-naive"""
        if self.published and self.published.tzinfo:
            self.published = self.published.replace(tzinfo=None)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'podcast': self.podcast,
            'title': self.title,
            'published': self.published.isoformat() if self.published else None,
            'audio_url': self.audio_url,
            'transcript_url': self.transcript_url,
            'description': self.description,
            'link': self.link,
            'duration': self.duration,
            'guid': self.guid,
            'apple_podcast_id': self.apple_podcast_id
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Episode':
        """Create from dictionary"""
        if isinstance(data.get('published'), str):
            data['published'] = datetime.fromisoformat(data['published'])
        return cls(**data)