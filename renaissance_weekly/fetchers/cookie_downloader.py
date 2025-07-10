"""
Cookie-based downloader for Cloudflare-protected podcasts
"""

import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Optional

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class CookieDownloader:
    """Download using browser cookies to bypass Cloudflare"""
    
    def __init__(self, cookie_dir: Path = None):
        self.cookie_dir = cookie_dir or Path("cookies")
        self.cookie_dir.mkdir(exist_ok=True)
        
    def get_cookie_file(self, podcast_name: str) -> Optional[Path]:
        """Get cookie file for a specific podcast"""
        # Standardize filename
        filename = podcast_name.lower().replace(" ", "_") + "_cookies.txt"
        cookie_file = self.cookie_dir / filename
        
        if cookie_file.exists():
            logger.info(f"Found cookie file: {cookie_file}")
            return cookie_file
        
        # Check for generic cookies
        generic_file = self.cookie_dir / "cookies.txt"
        if generic_file.exists():
            logger.info(f"Using generic cookie file: {generic_file}")
            return generic_file
            
        return None
    
    async def download_with_cookies(self, episode: Episode, output_path: Path, 
                                  cookie_file: Optional[Path] = None) -> bool:
        """Download episode using cookies"""
        
        # Get appropriate cookie file
        if not cookie_file:
            cookie_file = self.get_cookie_file(episode.podcast)
            
        if not cookie_file:
            logger.warning(f"No cookie file found for {episode.podcast}")
            return False
        
        logger.info(f"Attempting cookie-based download for: {episode.title}")
        
        # Build yt-dlp command
        cmd = [
            'python', '-m', 'yt_dlp',
            '--cookies', str(cookie_file),
            '-o', str(output_path),
            '--no-playlist',
            '--quiet',
            '--no-warnings',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            episode.audio_url
        ]
        
        try:
            # Run download
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=120)
            
            # Check if successful
            if result.returncode == 0 and output_path.exists():
                size_mb = output_path.stat().st_size / 1_000_000
                logger.info(f"✅ Cookie download successful! Size: {size_mb:.1f} MB")
                return True
            else:
                logger.error(f"Cookie download failed: {stderr.decode()}")
                return False
                
        except asyncio.TimeoutExpired:
            logger.error("Cookie download timed out")
            return False
        except Exception as e:
            logger.error(f"Cookie download error: {e}")
            return False
    
    @staticmethod
    def create_cookie_instructions(podcast_name: str) -> str:
        """Create instructions for obtaining cookies"""
        
        instructions = f"""
COOKIE EXPORT INSTRUCTIONS FOR {podcast_name}
{'=' * 60}

The {podcast_name} podcast is protected by Cloudflare and requires browser cookies
to download. Follow these steps:

1. INSTALL BROWSER EXTENSION:
   - Firefox: Install "cookies.txt" extension
   - Chrome: Install "Get cookies.txt" extension

2. VISIT THE PODCAST WEBSITE:
   - For American Optimist: https://americanoptimist.substack.com/
   - Make sure you can play an episode

3. EXPORT COOKIES:
   - Click the cookie extension icon
   - Choose "Export" or "Download"
   - Save as: cookies/{podcast_name.lower().replace(' ', '_')}_cookies.txt

4. PLACE IN CORRECT LOCATION:
   - Save to: {Path.cwd()}/cookies/
   - Filename: {podcast_name.lower().replace(' ', '_')}_cookies.txt

5. RETRY DOWNLOAD:
   - The system will automatically use the cookies
   - Or manually run: yt-dlp --cookies [cookie_file] [episode_url]

ALTERNATIVE: Browser Automation
- Run with --use-browser flag to automate cookie capture
- Requires solving captcha on first run
"""
        return instructions
    
    @staticmethod 
    async def try_browser_cookies(episode: Episode, output_path: Path) -> bool:
        """Try using cookies from installed browsers"""
        
        browsers = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
        
        for browser in browsers:
            logger.info(f"Trying {browser} cookies...")
            
            cmd = [
                'python', '-m', 'yt_dlp',
                '--cookies-from-browser', browser,
                '-o', str(output_path),
                '--quiet',
                '--no-warnings',
                episode.audio_url
            ]
            
            try:
                result = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await result.communicate()
                
                if result.returncode == 0 and output_path.exists():
                    logger.info(f"✅ Downloaded using {browser} cookies!")
                    return True
                    
            except Exception as e:
                logger.debug(f"{browser} cookies failed: {e}")
                continue
        
        return False