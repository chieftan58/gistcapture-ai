"""Validate cached summaries against transcript quality"""

from typing import Tuple, Optional
import hashlib

from ..utils.logging import get_logger

logger = get_logger(__name__)


class CacheValidator:
    """Check if cached summaries need regeneration due to transcript updates"""
    
    def __init__(self):
        # Known errors that invalidate summaries
        self.invalidating_errors = [
            "Heath Raboy", "Heath Rabois", "Keith Raboy",
            "David Sachs", "David Sax",
            "Open AI", "Space X",
            "Founder's Fund", "Founders' Fund"
        ]
    
    def should_regenerate_summaries(self, transcript: str, summary: str, paragraph_summary: str) -> Tuple[bool, str]:
        """
        Check if summaries should be regenerated
        
        Returns:
            Tuple of (should_regenerate, reason)
        """
        if not summary or not paragraph_summary:
            return True, "Missing summaries"
        
        # Check if summaries contain errors that aren't in transcript
        for error in self.invalidating_errors:
            if error in summary or error in paragraph_summary:
                if error not in transcript:
                    logger.info(f"🚨 Found fixed error '{error}' in cached summary but not in transcript")
                    return True, f"Summary contains outdated error: {error}"
        
        # Check transcript hash (future implementation)
        # This would detect any transcript changes
        
        return False, "Cache is valid"
    
    def get_transcript_hash(self, transcript: str) -> str:
        """Generate hash of transcript for change detection"""
        return hashlib.md5(transcript.encode()).hexdigest()
    
    def summaries_need_update(self, episode_data: dict) -> bool:
        """
        Quick check if episode summaries are stale
        """
        transcript = episode_data.get('transcript', '')
        summary = episode_data.get('summary', '')
        paragraph = episode_data.get('paragraph_summary', '')
        
        should_regen, reason = self.should_regenerate_summaries(transcript, summary, paragraph)
        
        if should_regen:
            logger.info(f"📝 Summaries need regeneration: {reason}")
        
        return should_regen


# Singleton instance
cache_validator = CacheValidator()