"""Direct download strategy - uses existing audio downloader"""

from pathlib import Path
from typing import Optional, Tuple, Dict
from . import DownloadStrategy
from ..transcripts.audio_downloader import PlatformAudioDownloader
from ..utils.logging import get_logger

logger = get_logger(__name__)


class DirectDownloadStrategy(DownloadStrategy):
    """Direct download using platform-specific strategies"""
    
    def __init__(self):
        self.downloader = PlatformAudioDownloader()
    
    @property
    def name(self) -> str:
        return "direct"
    
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Can handle most URLs except known problematic ones"""
        # Skip for known Cloudflare-protected sites
        if "substack.com" in url:
            return False
        
        # Skip for podcasts known to have issues
        if podcast_name in ["American Optimist", "Dwarkesh Podcast"]:
            return False
            
        return True
    
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """Download using existing platform-aware downloader"""
        podcast = episode_info.get('podcast', '')
        
        try:
            logger.info(f"📡 Direct download from: {url[:80]}...")
            
            # Use the existing downloader which has platform-specific logic
            success = self.downloader.download_audio(url, output_path, podcast)
            
            if success:
                file_size = output_path.stat().st_size
                logger.info(f"✅ Direct download successful ({file_size / 1024 / 1024:.1f} MB)")
                return True, None
            else:
                return False, "Direct download failed"
                
        except Exception as e:
            error_msg = f"Direct download error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg