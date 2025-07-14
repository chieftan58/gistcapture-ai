"""Centralized yt-dlp configuration and helper functions"""

import asyncio
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from ..utils.logging import get_logger

logger = get_logger(__name__)


class YtDlpConfig:
    """Centralized configuration for yt-dlp usage across the codebase"""
    
    # Standard yt-dlp options
    DEFAULT_OPTIONS = {
        'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
        'extract_audio': True,
        'audio_format': 'mp3',
        'audio_quality': '192K',
        'quiet': True,
        'no_warnings': True,
        'no_playlist': True,
        'retries': 3,
        'fragment_retries': 3,
        'concurrent_fragment_downloads': 1,
    }
    
    # Cookie file location
    COOKIE_FILE = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt'
    
    # Supported browsers for cookie extraction
    BROWSERS = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
    
    # Default timeout for downloads
    DEFAULT_TIMEOUT = 300  # 5 minutes
    
    @classmethod
    def get_cookie_options(cls) -> Dict:
        """Get the best available cookie options"""
        # Try cookie file first
        if cls.COOKIE_FILE.exists():
            logger.info(f"📂 Found cookie file: {cls.COOKIE_FILE}")
            return {'cookiefile': str(cls.COOKIE_FILE)}
        
        # Try browser cookies
        for browser in cls.BROWSERS:
            if cls.test_browser_cookies(browser):
                logger.info(f"🌐 Using {browser} browser cookies")
                return {'cookiesfrombrowser': (browser,)}
        
        logger.warning("⚠️ No cookies available for YouTube")
        return {}
    
    @classmethod
    def test_browser_cookies(cls, browser: str) -> bool:
        """Test if browser cookies work"""
        try:
            cmd = ['python', '-m', 'yt_dlp', '--cookies-from-browser', browser, 
                   '--simulate', '--quiet', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ']
            process = asyncio.run(asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            ))
            stdout, stderr = asyncio.run(process.communicate())
            return process.returncode == 0
        except:
            return False
    
    @classmethod
    def get_command_args(cls, url: str, output_path: Path, use_cookies: bool = True) -> List[str]:
        """Get standardized command arguments for subprocess calls"""
        cmd = [
            'python', '-m', 'yt_dlp',
            '-f', cls.DEFAULT_OPTIONS['format'],
            '--extract-audio',
            '--audio-format', cls.DEFAULT_OPTIONS['audio_format'],
            '--audio-quality', cls.DEFAULT_OPTIONS['audio_quality'],
            '--no-playlist',
            '--quiet',
            '--no-warnings',
            '-o', str(output_path)
        ]
        
        if use_cookies:
            # Try cookie file first
            if cls.COOKIE_FILE.exists():
                cmd.extend(['--cookies', str(cls.COOKIE_FILE)])
            else:
                # Try to find working browser
                for browser in cls.BROWSERS:
                    if cls.test_browser_cookies(browser):
                        cmd.extend(['--cookies-from-browser', browser])
                        break
        
        cmd.append(url)
        return cmd
    
    @classmethod
    async def run_ytdlp_async(cls, cmd: List[str], timeout: int = None) -> Tuple[int, str, str]:
        """Run yt-dlp command asynchronously with timeout"""
        timeout = timeout or cls.DEFAULT_TIMEOUT
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return process.returncode, stdout.decode(), stderr.decode()
            
        except asyncio.TimeoutError:
            logger.error(f"yt-dlp timeout after {timeout}s")
            if 'process' in locals():
                process.terminate()
                await process.wait()
            raise