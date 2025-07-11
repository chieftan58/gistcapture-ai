"""Download strategies for bulletproof episode downloads"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict

class DownloadStrategy(ABC):
    """Base class for download strategies"""
    
    @abstractmethod
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """
        Download audio file
        Returns: (success, error_message)
        """
        pass
    
    @abstractmethod
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Check if this strategy can handle the given URL/podcast"""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging"""
        pass