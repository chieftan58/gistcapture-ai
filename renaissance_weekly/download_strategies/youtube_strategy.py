"""YouTube download strategy - bypasses most protections"""

import asyncio
import subprocess
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
        
        # Try downloading with yt-dlp Python module
        try:
            import yt_dlp
        except ImportError:
            return False, "yt-dlp module not found. Please install with: pip install yt-dlp"
            
        cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt'
        
        # Configure yt-dlp options
        base_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
            'outtmpl': str(output_path.with_suffix('.%(ext)s')),
            'extractaudio': True,
            'audioformat': 'mp3',
            'audioquality': '192K',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
        }
        
        approaches = [
            # First try with cookie file
            {
                'name': 'cookie_file',
                'opts': {**base_opts, 'cookiefile': str(cookie_file)} if cookie_file.exists() else None
            },
            
            # Try with browser cookies
            {'name': 'firefox', 'opts': {**base_opts, 'cookiesfrombrowser': ('firefox',)}},
            {'name': 'chrome', 'opts': {**base_opts, 'cookiesfrombrowser': ('chrome',)}},
            {'name': 'chromium', 'opts': {**base_opts, 'cookiesfrombrowser': ('chromium',)}},
            {'name': 'edge', 'opts': {**base_opts, 'cookiesfrombrowser': ('edge',)}},
            {'name': 'safari', 'opts': {**base_opts, 'cookiesfrombrowser': ('safari',)}},
            
            # Try without cookies
            {'name': 'no_cookies', 'opts': base_opts},
        ]
        
        last_error = None
        for i, approach in enumerate(approaches):
            if approach['opts'] is None:
                continue
                
            try:
                logger.info(f"🎬 Attempt {i+1}: {approach['name']}")
                
                # Run yt-dlp in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, 
                    self._download_with_ytdlp_sync, 
                    youtube_url, 
                    approach['opts']
                )
                
                if result:
                    # Check if file was created and rename if needed
                    for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                        potential_path = output_path.with_suffix(suffix)
                        if potential_path.exists():
                            file_size = potential_path.stat().st_size
                            if file_size > 1000:  # At least 1KB
                                if suffix != '.mp3':
                                    # Convert to mp3 if needed
                                    try:
                                        convert_cmd = ['ffmpeg', '-i', str(potential_path), '-acodec', 'mp3', 
                                                     '-ab', '192k', str(output_path), '-y']
                                        subprocess.run(convert_cmd, capture_output=True, check=True)
                                        potential_path.unlink()  # Remove original file
                                    except:
                                        # If conversion fails, just rename
                                        potential_path.rename(output_path)
                                else:
                                    if potential_path != output_path:
                                        potential_path.rename(output_path)
                                
                                logger.info(f"✅ YouTube download successful with {approach['name']} ({file_size / 1024 / 1024:.1f} MB)")
                                return True, None
                            else:
                                potential_path.unlink()  # Remove empty file
                                logger.warning(f"❌ Downloaded file too small: {file_size} bytes")
                        
            except Exception as e:
                last_error = str(e)
                logger.warning(f"❌ Approach {i+1} ({approach['name']}) exception: {last_error}")
                continue
        
        # All approaches failed
        error_msg = "YouTube download failed - may need authentication"
        if last_error:
            if "Sign in" in last_error or "bot" in last_error.lower():
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
    
    def _download_with_ytdlp_sync(self, url: str, ydl_opts: dict) -> bool:
        """Synchronous yt-dlp download helper for use in executor"""
        try:
            import yt_dlp
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            return True
            
        except Exception as e:
            logger.debug(f"yt-dlp sync download failed: {e}")
            return False