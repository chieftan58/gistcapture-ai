"""YouTube download strategy - bypasses most protections"""

import asyncio
from pathlib import Path
from typing import Optional, Tuple, Dict
from . import DownloadStrategy
from ..utils.logging import get_logger

logger = get_logger(__name__)


class YouTubeStrategy(DownloadStrategy):
    """Download from YouTube - bypasses Cloudflare and most protections"""
    
    # Known YouTube URLs for specific episodes
    EPISODE_MAPPINGS = {
        # American Optimist
        "American Optimist|Marc Andreessen": "https://www.youtube.com/watch?v=pRoKi4VL_5s",
        "American Optimist|Dave Rubin": "https://www.youtube.com/watch?v=w1FRqBOxS8g", 
        "American Optimist|Scott Wu": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",
        "American Optimist|Flying Cars": "https://www.youtube.com/watch?v=TVg_DK8-kMw",
        
        # Dwarkesh Podcast
        "Dwarkesh Podcast|Stephen Kotkin": "https://www.youtube.com/watch?v=YMfd3EoHfPI",
        "Dwarkesh Podcast|Stalin": "https://www.youtube.com/watch?v=YMfd3EoHfPI",
        
        # Add more mappings as discovered
    }
    
    # YouTube channels for podcasts
    YOUTUBE_CHANNELS = {
        "American Optimist": "americanoptimist",
        "Dwarkesh Podcast": "DwarkeshPatel",
        "The Drive": "peterattiamd",
        "The Tim Ferriss Show": "TimFerriss",
        "Lex Fridman": "lexfridman",
        "Huberman Lab": "hubermanlab",
    }
    
    @property
    def name(self) -> str:
        return "youtube"
    
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Priority for Cloudflare-protected podcasts and YouTube URLs"""
        # Always try YouTube for known problematic podcasts
        if podcast_name in ["American Optimist", "Dwarkesh Podcast"]:
            return True
        
        # Handle YouTube URLs
        return "youtube.com" in url or "youtu.be" in url
    
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """Download from YouTube using yt-dlp"""
        podcast = episode_info.get('podcast', '')
        title = episode_info.get('title', '')
        
        # First try to find YouTube URL
        youtube_url = await self._find_youtube_url(podcast, title, url)
        if not youtube_url:
            return False, "No YouTube URL found for this episode"
        
        logger.info(f"🎥 Found YouTube URL: {youtube_url}")
        
        # Try downloading with different approaches
        approaches = [
            # First try with browser cookies
            ['yt-dlp', '--cookies-from-browser', 'firefox', '-x', '--audio-format', 'mp3', 
             '--quiet', '--progress', '-o', str(output_path), youtube_url],
            
            # Try Chrome cookies
            ['yt-dlp', '--cookies-from-browser', 'chrome', '-x', '--audio-format', 'mp3',
             '--quiet', '--progress', '-o', str(output_path), youtube_url],
            
            # Try without cookies
            ['yt-dlp', '-x', '--audio-format', 'mp3', '--quiet', '--progress',
             '-o', str(output_path), youtube_url],
        ]
        
        last_stderr = None
        for i, cmd in enumerate(approaches):
            try:
                logger.debug(f"Attempt {i+1}: {' '.join(cmd[:5])}...")
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                last_stderr = stderr  # Store for error reporting
                
                if process.returncode == 0 and output_path.exists():
                    file_size = output_path.stat().st_size
                    if file_size > 1000:  # At least 1KB
                        logger.info(f"✅ YouTube download successful ({file_size / 1024 / 1024:.1f} MB)")
                        return True, None
                    else:
                        output_path.unlink()  # Remove empty file
                        
            except Exception as e:
                logger.debug(f"Approach {i+1} failed: {e}")
                continue
        
        # All approaches failed
        error_msg = "YouTube download failed - may need authentication"
        if last_stderr:
            error_details = last_stderr.decode().strip()
            if "Sign in" in error_details:
                error_msg = "YouTube requires sign-in - please login to YouTube in Firefox/Chrome"
        
        return False, error_msg
    
    async def _find_youtube_url(self, podcast: str, title: str, original_url: str) -> Optional[str]:
        """Find YouTube URL for the episode"""
        # If already a YouTube URL, return it
        if "youtube.com" in original_url or "youtu.be" in original_url:
            return original_url
        
        # Check known mappings
        mapping_key = f"{podcast}|{title}"
        for key, url in self.EPISODE_MAPPINGS.items():
            # Flexible matching
            if any(word.lower() in key.lower() for word in title.split()[:3]):
                logger.info(f"✅ Found known YouTube mapping: {key}")
                return url
        
        # Build search query
        channel = self.YOUTUBE_CHANNELS.get(podcast, "")
        if channel:
            search_terms = f"{channel} {title}"
        else:
            search_terms = f"{podcast} {title} full episode"
        
        logger.info(f"🔍 Would search YouTube for: {search_terms}")
        
        # TODO: Implement actual YouTube search
        # For now, return None - in production, this would search YouTube
        return None