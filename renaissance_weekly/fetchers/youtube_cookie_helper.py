"""YouTube Cookie Helper - Provides guidance for YouTube authentication"""

import os
from pathlib import Path
from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class YouTubeCookieHelper:
    """Helper for YouTube authentication and cookie management"""
    
    COOKIE_LOCATIONS = [
        Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt',
        Path.home() / '.config' / 'yt-dlp' / 'cookies.txt',
        Path.home() / 'youtube_cookies.txt',
        Path('/tmp/youtube_cookies.txt'),
    ]
    
    @classmethod
    def find_cookie_file(cls) -> Optional[Path]:
        """Find YouTube cookie file in common locations"""
        for location in cls.COOKIE_LOCATIONS:
            if location.exists():
                logger.info(f"✅ Found YouTube cookies at: {location}")
                return location
        return None
    
    @classmethod
    def get_cookie_instructions(cls) -> str:
        """Get detailed instructions for cookie export"""
        return """
YOUTUBE AUTHENTICATION REQUIRED
==============================

YouTube is blocking automated downloads. You need to export browser cookies.

QUICK SOLUTION:
--------------
1. Install browser extension:
   - Firefox: "cookies.txt" by Lennon Hill
   - Chrome: "Get cookies.txt LOCALLY"

2. Visit https://www.youtube.com and sign in

3. Click extension icon and save cookies

4. Place file at: ~/.config/renaissance-weekly/cookies/youtube_cookies.txt

ALTERNATIVE: Use Manual URL in UI
---------------------------------
In the download UI, click "Manual URL" for failed episodes and paste these:

Episode 118 (Marc Andreessen): https://www.youtube.com/watch?v=pRoKi4VL_5s
Episode 117 (Dave Rubin): https://www.youtube.com/watch?v=w1FRqBOxS8g
Episode 115 (Scott Wu): https://www.youtube.com/watch?v=YwmQzWGyrRQ
Episode 114 (Flying Cars): https://www.youtube.com/watch?v=TVg_DK8-kMw

Then download manually from YouTube and provide the MP3 file location.
"""
    
    @classmethod
    def check_youtube_auth(cls) -> bool:
        """Check if YouTube authentication is available"""
        cookie_file = cls.find_cookie_file()
        if cookie_file:
            return True
        
        # Check if browser cookies are available
        import subprocess
        browsers = ['firefox', 'chrome', 'chromium', 'edge']
        
        for browser in browsers:
            try:
                # Test if browser cookies work
                cmd = ['python', '-m', 'yt_dlp', '--cookies-from-browser', browser, '--simulate', '--quiet', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ']
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode == 0:
                    logger.info(f"✅ Can use {browser} browser cookies for YouTube")
                    return True
            except:
                pass
        
        logger.warning("❌ No YouTube authentication available")
        logger.info(cls.get_cookie_instructions())
        return False