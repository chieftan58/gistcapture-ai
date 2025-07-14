"""Specialized audio downloader with platform-specific strategies and validation"""

import re
import requests
import os
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Callable
from pathlib import Path
import time
import subprocess
import asyncio
from datetime import datetime, timedelta

from ..utils.logging import get_logger
from ..monitoring import monitor

logger = get_logger(__name__)


class PlatformAudioDownloader:
    """Platform-specific audio download strategies with validation"""
    
    def __init__(self):
        self.session = requests.Session()
        
        # Add retry adapter for better reliability
        from requests.adapters import HTTPAdapter
        from requests.packages.urllib3.util.retry import Retry
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Rotate user agents to avoid detection
        self.user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'AppleCoreMedia/1.0.0.20G165 (iPhone; U; CPU OS 16_6 like Mac OS X; en_us)',
            'Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
            'Overcast/2024.1 (+http://overcast.fm/; iOS podcast app)',
        ]
        self.current_ua_index = 0
        self._set_default_headers()
    
    def download_audio(self, url: str, output_path: Path, podcast_name: str = "") -> bool:
        """Download audio with platform-specific strategy and validation"""
        logger.info(f"🎵 Downloading audio from: {url[:80]}...")
        logger.info("📊 Using progress-based timeout: 60s stall timeout, 30min max timeout")
        domain = urlparse(url).netloc.lower()
        
        # Add small delay to avoid rate limiting
        time.sleep(0.5)
        
        # Platform-specific strategies
        strategies = {
            'youtube.com': self._download_youtube,
            'youtu.be': self._download_youtube,
            'api.substack.com': self._download_substack,
            'substack.com': self._download_substack,
            'traffic.libsyn.com': self._download_libsyn,
            'content.libsyn.com': self._download_libsyn,
            'anchor.fm': self._download_anchor,
            'feeds.simplecast.com': self._download_simplecast,
            'feeds.megaphone.fm': self._download_megaphone,
            'rss.art19.com': self._download_art19,
            'dts.podtrac.com': self._download_generic,  # Common redirect service
            'pdst.fm': self._download_generic,  # Podcast distribution
        }
        
        # Try platform-specific strategy
        for pattern, strategy in strategies.items():
            if pattern in domain:
                logger.info(f"📡 Using {strategy.__name__} strategy for {pattern}")
                if strategy(url, output_path):
                    # Validate the downloaded file
                    if self._validate_audio_file(output_path):
                        logger.info(f"✅ Successfully downloaded: {output_path.stat().st_size / 1_000_000:.1f}MB")
                        monitor.record_success('audio_download', podcast_name or 'Unknown')
                        return True
                    else:
                        logger.warning(f"Downloaded file failed validation, removing: {output_path}")
                        monitor.record_failure('audio_download', podcast_name or 'Unknown', url[:80],
                                             'ValidationFailed', 'Downloaded file failed validation')
                        if output_path.exists():
                            output_path.unlink()
        
        # Fallback to generic download
        logger.info("📡 Using generic download strategy")
        if self._download_generic(url, output_path):
            if self._validate_audio_file(output_path):
                logger.info(f"✅ Successfully downloaded: {output_path.stat().st_size / 1_000_000:.1f}MB")
                monitor.record_success('audio_download', podcast_name or 'Unknown')
                return True
            else:
                logger.warning(f"Downloaded file failed validation, removing: {output_path}")
                monitor.record_failure('audio_download', podcast_name or 'Unknown', url[:80],
                                     'ValidationFailed', 'Downloaded file failed validation')
                if output_path.exists():
                    output_path.unlink()
        
        # Ultimate fallback: yt-dlp
        logger.info("🎥 Trying yt-dlp as final fallback...")
        if self._download_with_ytdlp(url, str(output_path)):
            if self._validate_audio_file(output_path):
                logger.info(f"✅ yt-dlp download successful: {output_path.stat().st_size / 1_000_000:.1f}MB")
                monitor.record_success('audio_download', podcast_name or 'Unknown')
                return True
        
        logger.error(f"❌ All download strategies failed for: {url[:80]}...")
        monitor.record_failure('audio_download', podcast_name or 'Unknown', url[:80],
                             'AllStrategiesFailed', 'All download strategies failed')
        return False
    
    def _validate_audio_file(self, file_path: Path) -> bool:
        """Validate that the downloaded file is actually an audio file"""
        if not file_path.exists():
            return False
        
        # Check file size
        file_size = file_path.stat().st_size
        if file_size < 1000:  # Less than 1KB is suspicious
            logger.warning(f"File too small: {file_size} bytes")
            return False
        
        # Check file header for audio signatures
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)
                
                # Check for common audio file signatures
                audio_signatures = [
                    b'ID3',           # MP3 with ID3 tag
                    b'\xFF\xFB',      # MP3
                    b'\xFF\xF3',      # MP3
                    b'\xFF\xF2',      # MP3
                    b'ftyp',          # MP4/M4A (at offset 4)
                    b'OggS',          # Ogg Vorbis
                    b'RIFF',          # WAV
                    b'fLaC',          # FLAC
                ]
                
                # Check if file starts with any audio signature
                for sig in audio_signatures:
                    if header.startswith(sig):
                        logger.debug(f"Valid audio signature found: {sig}")
                        return True
                
                # Check for MP4/M4A at offset 4
                if len(header) >= 8 and header[4:8] == b'ftyp':
                    logger.debug("Valid MP4/M4A file detected")
                    return True
                
                # Check if it's HTML (common error response)
                if header.startswith(b'<!DOCTYPE') or header.startswith(b'<html'):
                    logger.error("Downloaded file appears to be HTML, not audio")
                    return False
                
                # Try to validate with ffprobe if available
                return self._validate_with_ffprobe(file_path)
                
        except Exception as e:
            logger.error(f"Error validating file: {e}")
            return False
    
    def _validate_with_ffprobe(self, file_path: Path) -> bool:
        """Use ffprobe to validate the audio file"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=format_name,duration',
                '-of', 'json',
                str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                import json
                try:
                    data = json.loads(result.stdout)
                    if 'format' in data and 'format_name' in data['format']:
                        format_name = data['format']['format_name']
                        logger.debug(f"FFprobe detected format: {format_name}")
                        # Check if it's an audio format
                        audio_formats = ['mp3', 'mp4', 'm4a', 'aac', 'ogg', 'wav', 'flac', 'opus']
                        return any(fmt in format_name.lower() for fmt in audio_formats)
                except:
                    pass
            
            return False
            
        except Exception as e:
            logger.debug(f"FFprobe validation failed: {e}")
            # If ffprobe is not available, we can't do this validation
            return True  # Assume it's valid if we can't check
    
    def _set_default_headers(self):
        """Set default headers with current user agent"""
        self.session.headers.update({
            'User-Agent': self.user_agents[self.current_ua_index],
            'Accept': 'audio/mpeg, audio/*, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
    
    def _rotate_user_agent(self):
        """Rotate to next user agent"""
        self.current_ua_index = (self.current_ua_index + 1) % len(self.user_agents)
        self._set_default_headers()
        logger.debug(f"Rotated to user agent: {self.user_agents[self.current_ua_index][:50]}...")
    
    def _download_substack(self, url: str, output_path: Path) -> bool:
        """Download from Substack with better error handling"""
        try:
            # Try multiple approaches for Substack
            approaches = [
                # Approach 1: Direct download with browser-like headers
                {
                    'headers': {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,video/*;q=0.6,*/*;q=0.5',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'identity;q=1, *;q=0',
                        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                        'Sec-Ch-Ua-Mobile': '?0',
                        'Sec-Ch-Ua-Platform': '"macOS"',
                        'Sec-Fetch-Dest': 'audio',
                        'Sec-Fetch-Mode': 'no-cors',
                        'Sec-Fetch-Site': 'cross-site',
                        'Range': 'bytes=0-',
                        'Referer': 'https://substack.com/',
                    },
                    'cookies': {
                        'substack.sid': 'anonymous',
                        'substack.lli': '1'
                    }
                },
                # Approach 2: Podcast app user agent
                {
                    'headers': {
                        'User-Agent': 'AppleCoreMedia/1.0.0.20G75 (iPhone; iOS 16.0; Scale/3.00)',
                        'Accept': '*/*',
                        'Accept-Encoding': 'identity',
                        'Connection': 'keep-alive',
                    }
                },
                # Approach 3: Direct with minimal headers
                {
                    'headers': {
                        'User-Agent': 'Podcast/1.0',
                        'Accept': 'audio/*',
                    }
                }
            ]
            
            for i, approach in enumerate(approaches):
                logger.debug(f"Trying Substack approach {i+1}")
                
                # Create new session for each approach
                session = requests.Session()
                session.headers.update(approach['headers'])
                
                if 'cookies' in approach:
                    session.cookies.update(approach['cookies'])
                
                try:
                    # Follow redirects manually to handle them better
                    response = session.get(url, stream=True, allow_redirects=False, timeout=30)
                    
                    # Handle redirects
                    redirect_count = 0
                    while response.status_code in [301, 302, 303, 307, 308] and redirect_count < 5:
                        redirect_url = response.headers.get('Location')
                        if not redirect_url:
                            break
                        
                        # Make redirect URL absolute if needed
                        if not redirect_url.startswith('http'):
                            redirect_url = f"https://api.substack.com{redirect_url}"
                        
                        logger.debug(f"Following redirect to: {redirect_url[:50]}...")
                        response = session.get(redirect_url, stream=True, allow_redirects=False, timeout=30)
                        redirect_count += 1
                    
                    if response.status_code == 200:
                        # Check content type
                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'audio' in content_type or 'octet-stream' in content_type:
                            # Use progress-based download
                            if self._download_with_progress(response, output_path):
                                return True
                        else:
                            logger.warning(f"Unexpected content type: {content_type}")
                    
                    elif response.status_code == 403:
                        logger.debug(f"Approach {i+1} got 403 Forbidden")
                        continue
                    else:
                        logger.debug(f"Approach {i+1} got status {response.status_code}")
                        
                except Exception as e:
                    logger.debug(f"Approach {i+1} failed: {e}")
                    continue
                finally:
                    session.close()
            
            # If all approaches failed, try with curl as last resort
            return self._download_with_curl(url, output_path)
            
        except Exception as e:
            logger.error(f"Substack download error: {e}")
            return False
    
    def _download_with_curl(self, url: str, output_path: Path) -> bool:
        """Use curl as a fallback download method"""
        try:
            # Check if curl is available
            try:
                subprocess.run(['curl', '--version'], capture_output=True, check=True)
            except:
                logger.debug("Curl not available")
                return False
            
            # Create a temporary cookie file
            import tempfile
            cookie_file = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
            cookie_file.close()
            
            cmd = [
                'curl',
                '-L',  # Follow redirects
                '-o', str(output_path),
                '-c', cookie_file.name,  # Save cookies
                '-b', cookie_file.name,  # Send cookies
                '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                '-H', 'Accept: audio/mpeg, audio/*, */*',
                '-H', 'Accept-Language: en-US,en;q=0.9',
                '-H', 'Accept-Encoding: gzip, deflate, br',
                '-H', 'DNT: 1',
                '-H', 'Connection: keep-alive',
                '-H', 'Upgrade-Insecure-Requests: 1',
                '--compressed',
                '--retry', '3',
                '--retry-delay', '2',
                '--max-time', '1800',  # 30 minutes for very long episodes
                '--progress-bar',
                url
            ]
            
            logger.debug(f"Running curl command...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Clean up cookie file
            try:
                os.unlink(cookie_file.name)
            except:
                pass
            
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
                return True
            else:
                logger.debug(f"Curl failed with return code: {result.returncode}")
                return False
                
        except Exception as e:
            logger.debug(f"Curl download failed: {e}")
            return False
    
    def _download_libsyn(self, url: str, output_path: Path) -> bool:
        """Download from Libsyn"""
        try:
            # Libsyn often redirects, follow redirects
            headers = {
                'User-Agent': 'iTunes/12.12',
                'Accept': '*/*'
            }
            
            # Use shorter initial timeout for connection, but no read timeout
            response = self.session.get(url, headers=headers, stream=True, allow_redirects=True, timeout=(30, None))
            
            if response.status_code == 200:
                # Check content type
                content_type = response.headers.get('Content-Type', '').lower()
                if 'audio' in content_type or 'octet-stream' in content_type:
                    # Use progress-based download
                    return self._download_with_progress(response, output_path)
                
            return False
            
        except Exception as e:
            logger.error(f"Libsyn download error: {e}")
            return False
    
    def _download_anchor(self, url: str, output_path: Path) -> bool:
        """Download from Anchor.fm (Spotify)"""
        try:
            headers = {
                'User-Agent': 'Spotify/8.8.0 iOS/16.0 (iPhone12,1)',
                'Accept': 'audio/*',
                'Accept-Encoding': 'identity',
            }
            
            # Use shorter initial timeout for connection, but no read timeout
            response = self.session.get(url, headers=headers, stream=True, timeout=(30, None), allow_redirects=True)
            
            if response.status_code == 200:
                # Use progress-based download
                return self._download_with_progress(response, output_path)
                
            return False
            
        except Exception as e:
            logger.error(f"Anchor download error: {e}")
            return False
    
    def _download_youtube(self, url: str, output_path: Path) -> bool:
        """Download audio from YouTube using yt-dlp Python module"""
        try:
            import yt_dlp
        except ImportError:
            logger.error("yt-dlp module not found. Please install with: pip install yt-dlp")
            return False
            
        try:
            logger.info("🎥 Using yt-dlp Python module for YouTube download")
            
            # Configure yt-dlp options
            ydl_opts = {
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
            
            # Check for manual cookie file first
            manual_cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_manual_do_not_overwrite.txt'
            if manual_cookie_file.exists():
                logger.info("🔒 Using protected manual cookie file for YouTube download")
                ydl_opts['cookiefile'] = str(manual_cookie_file)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Check if file was created
                for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                    potential_path = output_path.with_suffix(suffix)
                    if potential_path.exists():
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
                        
                        logger.info("✅ YouTube download successful with manual cookies")
                        return True
            
            # Try with browser cookies first
            browsers = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
            
            for browser in browsers:
                try:
                    ydl_opts_with_cookies = ydl_opts.copy()
                    ydl_opts_with_cookies['cookiesfrombrowser'] = (browser,)
                    
                    logger.debug(f"Trying yt-dlp with {browser} cookies")
                    
                    with yt_dlp.YoutubeDL(ydl_opts_with_cookies) as ydl:
                        ydl.download([url])
                    
                    # Check if file was created
                    for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                        potential_path = output_path.with_suffix(suffix)
                        if potential_path.exists():
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
                            
                            logger.info(f"✅ yt-dlp download successful with {browser} cookies")
                            return True
                            
                except Exception as e:
                    logger.debug(f"yt-dlp with {browser} cookies failed: {e}")
                    continue
            
            # Try without cookies as fallback
            logger.debug("Trying yt-dlp without browser cookies")
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # Check if file was created
                for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                    potential_path = output_path.with_suffix(suffix)
                    if potential_path.exists():
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
                        
                        logger.info("✅ yt-dlp download successful without cookies")
                        return True
                        
            except Exception as e:
                logger.error(f"yt-dlp without cookies failed: {e}")
                
            return False
            
        except Exception as e:
            logger.error(f"YouTube download error: {e}")
            return False
    
    def _download_simplecast(self, url: str, output_path: Path) -> bool:
        """Download from Simplecast"""
        return self._download_generic(url, output_path)
    
    def _download_megaphone(self, url: str, output_path: Path) -> bool:
        """Download from Megaphone"""
        try:
            # Megaphone tracks downloads, so be polite
            headers = {
                'User-Agent': 'AppleCoreMedia/1.0.0.20G75',
                'Accept': 'audio/*',
                'Range': 'bytes=0-'  # Sometimes helps with large files
            }
            
            # Use shorter initial timeout for connection, but no read timeout
            response = self.session.get(url, headers=headers, stream=True, timeout=(30, None), allow_redirects=True)
            
            if response.status_code in [200, 206]:  # 206 for partial content
                # Use progress-based download
                return self._download_with_progress(response, output_path)
                
            return False
            
        except Exception as e:
            logger.error(f"Megaphone download error: {e}")
            return False
    
    def _download_art19(self, url: str, output_path: Path) -> bool:
        """Download from Art19 with enhanced headers"""
        try:
            # Art19 requires specific headers to avoid 403
            approaches = [
                # Approach 1: Apple Podcasts app
                {
                    'User-Agent': 'Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
                    'Accept': '*/*',
                    'Accept-Encoding': 'br, gzip, deflate',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Cache-Control': 'no-cache',
                },
                # Approach 2: Overcast
                {
                    'User-Agent': 'Overcast/2024.1 (+http://overcast.fm/; iOS podcast app)',
                    'Accept': 'audio/mpeg, audio/*',
                    'X-Playback-Session-Id': 'F6D8F9E0-1234-4D5E-B098-' + str(int(time.time())),
                },
                # Approach 3: Browser with audio context
                {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,*/*;q=0.5',
                    'Sec-Fetch-Dest': 'audio',
                    'Sec-Fetch-Mode': 'no-cors',
                    'Sec-Fetch-Site': 'cross-site',
                    'Range': 'bytes=0-',
                }
            ]
            
            for i, headers in enumerate(approaches):
                try:
                    logger.debug(f"Art19 attempt {i+1} with {headers.get('User-Agent', '')[:30]}...")
                    # Use shorter initial timeout for connection, but no read timeout
                    response = self.session.get(url, headers=headers, stream=True, timeout=(30, None), allow_redirects=True)
                    
                    if response.status_code == 200:
                        # Use progress-based download
                        return self._download_with_progress(response, output_path)
                    elif response.status_code == 403:
                        logger.warning(f"Art19 approach {i+1} got 403, trying next...")
                        time.sleep(1)  # Brief pause between attempts
                    else:
                        logger.warning(f"Art19 approach {i+1} got status {response.status_code}")
                except Exception as e:
                    logger.debug(f"Art19 approach {i+1} failed: {e}")
                    
            return False
            
        except Exception as e:
            logger.error(f"Art19 download error: {e}")
            return False
    
    def _download_with_progress(self, response: requests.Response, output_path: Path, 
                                 stall_timeout: int = 60, max_timeout: int = 1800,
                                 min_speed_bps: int = 1024) -> bool:
        """
        Download with progress-based timeout management.
        
        Args:
            response: Active response object with stream=True
            output_path: Where to save the file
            stall_timeout: Seconds without progress before timeout (default: 60)
            max_timeout: Maximum total seconds allowed (default: 30 minutes)
            min_speed_bps: Minimum bytes/second to count as progress (default: 1KB/s)
            
        Returns:
            True if download succeeded, False otherwise
        """
        try:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            # Progress tracking
            last_progress_time = datetime.now()
            last_downloaded = 0
            start_time = datetime.now()
            
            # Chunk tracking for speed calculation
            chunk_start_time = datetime.now()
            chunk_downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=32768):  # 32KB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        chunk_downloaded += len(chunk)
                        
                        # Calculate time since last progress
                        now = datetime.now()
                        time_since_progress = (now - last_progress_time).total_seconds()
                        total_time = (now - start_time).total_seconds()
                        
                        # Check for stall (no progress for stall_timeout seconds)
                        if time_since_progress > stall_timeout:
                            logger.error(f"⏱️ Download stalled: No progress for {stall_timeout}s")
                            return False
                        
                        # Check for max timeout
                        if total_time > max_timeout:
                            logger.error(f"⏱️ Download exceeded max timeout of {max_timeout}s")
                            return False
                        
                        # Update progress tracking every second
                        chunk_time = (now - chunk_start_time).total_seconds()
                        if chunk_time >= 1.0:
                            # Calculate speed
                            speed_bps = chunk_downloaded / chunk_time if chunk_time > 0 else 0
                            
                            # Check if we're making meaningful progress
                            if speed_bps >= min_speed_bps:
                                last_progress_time = now
                                last_downloaded = downloaded
                            
                            # Log progress every 50MB to reduce overhead
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                if downloaded % (1024 * 1024 * 50) < chunk_downloaded:
                                    speed_mbps = speed_bps / (1024 * 1024)
                                    eta_seconds = (total_size - downloaded) / speed_bps if speed_bps > 0 else 0
                                    eta_str = str(timedelta(seconds=int(eta_seconds)))
                                    logger.info(f"📊 Progress: {progress:.1f}% ({downloaded / 1_000_000:.1f}MB/{total_size / 1_000_000:.1f}MB) "
                                              f"Speed: {speed_mbps:.2f}MB/s ETA: {eta_str}")
                            else:
                                # No content-length, just show downloaded amount every 50MB
                                if downloaded % (1024 * 1024 * 50) < chunk_downloaded:
                                    speed_mbps = speed_bps / (1024 * 1024)
                                    logger.info(f"📊 Downloaded: {downloaded / 1_000_000:.1f}MB Speed: {speed_mbps:.2f}MB/s")
                            
                            # Reset chunk tracking
                            chunk_start_time = now
                            chunk_downloaded = 0
                
                # Final validation
                if downloaded < 1000:
                    logger.warning(f"Downloaded file too small: {downloaded} bytes")
                    if output_path.exists():
                        output_path.unlink()
                    return False
                
                # Log final stats
                total_time = (datetime.now() - start_time).total_seconds()
                avg_speed_mbps = (downloaded / total_time / (1024 * 1024)) if total_time > 0 else 0
                logger.info(f"✅ Download complete: {downloaded / 1_000_000:.1f}MB in {int(total_time)}s "
                          f"(avg {avg_speed_mbps:.2f}MB/s)")
                
                return True
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            if output_path.exists():
                output_path.unlink()
            return False
    
    def _download_generic(self, url: str, output_path: Path) -> bool:
        """Generic download with multiple header attempts"""
        user_agents = [
            ('Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0', 'audio/*, */*'),
            ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'audio/webm,audio/*;q=0.9,*/*;q=0.5'),
            ('Spotify/8.8.0 iOS/16.6 (iPhone13)', 'audio/mpeg, audio/*'),
            ('CastBox/8.32.1-230915 (Linux;Android 13)', 'audio/*'),
            ('PocketCasts/1.0 (Pocket Casts Feed Parser; +http://pocketcasts.com/)', '*/*'),
            ('AppleCoreMedia/1.0.0.20G165 (iPhone; U; CPU OS 16_6 like Mac OS X; en_us)', '*/*'),
        ]
        
        for ua, accept in user_agents:
            try:
                headers = {
                    'User-Agent': ua, 
                    'Accept': accept,
                    'Accept-Encoding': 'identity',  # Avoid compressed responses
                }
                # Use shorter initial timeout for connection, but no read timeout
                response = self.session.get(url, headers=headers, stream=True, timeout=(30, None), allow_redirects=True)
                
                if response.status_code == 200:
                    # Check content type
                    content_type = response.headers.get('Content-Type', '').lower()
                    content_length = response.headers.get('Content-Length', '0')
                    
                    # Skip if it looks like an error page
                    if 'html' in content_type:
                        logger.warning(f"Got HTML response instead of audio from {url[:50]}...")
                        continue
                    
                    # Skip if content is too small
                    if content_length and int(content_length) < 1000:
                        logger.warning(f"Content too small: {content_length} bytes")
                        continue
                    
                    # Use progress-based download
                    if self._download_with_progress(response, output_path):
                        return True
                    else:
                        continue
                    
            except Exception as e:
                logger.debug(f"Generic download with UA '{ua}' failed: {e}")
                continue
        
        return False
    
    def _download_with_ytdlp(self, url: str, output_path: str) -> bool:
        """Download using yt-dlp as ultimate fallback."""
        try:
            import yt_dlp
        except ImportError:
            logger.warning("yt-dlp not installed. Install with: pip install yt-dlp")
            return False
            
        # Try different browsers for cookie extraction
        browsers = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
        
        for browser in browsers:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_path,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'retries': 3,
                'fragment_retries': 3,
                'ignoreerrors': False,
                'cookiesfrombrowser': (browser,),  # Try to use browser cookies
                'headers': {
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache',
                    'DNT': '1',
                    'Upgrade-Insecure-Requests': '1',
                    'Referer': 'https://substack.com/',
                },
                'http_chunk_size': 10485760,  # 10MB chunks
                'concurrent_fragment_downloads': 5,
                'extractor_args': {'generic': ['impersonate']},  # Try to bypass Cloudflare
                'nocheckcertificate': True,  # Sometimes helps with SSL issues
            }
        
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info(f"Attempting yt-dlp download with {browser} cookies for: {url}")
                    ydl.download([url])
                    
                if self._validate_audio_file(Path(output_path)):
                    logger.info(f"✅ yt-dlp download successful with {browser} cookies")
                    return True
                else:
                    logger.debug(f"yt-dlp download with {browser} failed validation")
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    continue
                    
            except Exception as e:
                logger.debug(f"yt-dlp with {browser} cookies failed: {e}")
                if os.path.exists(output_path):
                    os.remove(output_path)
                # Try next browser
                continue
        
        # If all browsers fail, try without cookies
        logger.info("Trying yt-dlp without browser cookies...")
        ydl_opts_no_cookies = ydl_opts.copy()
        ydl_opts_no_cookies.pop('cookiesfrombrowser', None)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts_no_cookies) as ydl:
                ydl.download([url])
                
            if self._validate_audio_file(Path(output_path)):
                logger.info("✅ yt-dlp download successful without cookies")
                return True
        except Exception as e:
            logger.error(f"yt-dlp final attempt failed: {e}")
            
        return False


async def download_audio_with_ytdlp(url: str, output_path: Path) -> bool:
    """Async wrapper for YouTube download using yt-dlp Python module"""
    try:
        import yt_dlp
    except ImportError:
        logger.error("yt-dlp module not found. Please install with: pip install yt-dlp")
        return False
        
    try:
        logger.info(f"🎥 Downloading from YouTube/yt-dlp: {url[:80]}...")
        
        # Configure yt-dlp options
        ydl_opts = {
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
        
        # Try manual cookie file first (protected from yt-dlp overwriting)
        manual_cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_manual_do_not_overwrite.txt'
        cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt'
        
        # Prioritize manual cookie file
        if manual_cookie_file.exists():
            cookie_file = manual_cookie_file
            logger.info("🔒 Using protected manual cookie file")
        
        if cookie_file.exists():
            try:
                logger.info(f"📂 Trying YouTube download with cookie file: {cookie_file}")
                ydl_opts_with_cookies = ydl_opts.copy()
                ydl_opts_with_cookies['cookiefile'] = str(cookie_file)
                
                # Run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _download_with_ytdlp_sync, url, ydl_opts_with_cookies)
                
                if result:
                    # Check if file was created and rename if needed
                    for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                        potential_path = output_path.with_suffix(suffix)
                        if potential_path.exists():
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
                            
                            logger.info(f"✅ YouTube download successful with cookie file")
                            return True
                            
            except Exception as e:
                logger.warning(f"Cookie file attempt failed: {e}")
        
        # Try browser cookies
        browsers = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
        
        for browser in browsers:
            try:
                logger.debug(f"Trying YouTube download with {browser} cookies")
                ydl_opts_with_cookies = ydl_opts.copy()
                ydl_opts_with_cookies['cookiesfrombrowser'] = (browser,)
                
                # Run in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _download_with_ytdlp_sync, url, ydl_opts_with_cookies)
                
                if result:
                    # Check if file was created and rename if needed
                    for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                        potential_path = output_path.with_suffix(suffix)
                        if potential_path.exists():
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
                            
                            logger.info(f"✅ YouTube download successful with {browser} cookies")
                            return True
                            
            except Exception as e:
                logger.debug(f"Failed with {browser} cookies: {e}")
                continue
        
        # Try without cookies
        logger.info("Trying yt-dlp without browser cookies...")
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _download_with_ytdlp_sync, url, ydl_opts)
            
            if result:
                # Check if file was created and rename if needed
                for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                    potential_path = output_path.with_suffix(suffix)
                    if potential_path.exists():
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
                        
                        logger.info("✅ YouTube download successful without cookies")
                        return True
                        
        except Exception as e:
            error_msg = str(e)
            if "Sign in to confirm" in error_msg or "bot" in error_msg.lower():
                logger.error("\n" + "="*60)
                logger.error("❌ YouTube requires authentication")
                logger.error("="*60)
                logger.error("\nSOLUTION 1: Use browser directly")
                logger.error("1. Open Firefox/Chrome and ensure you're logged into YouTube")
                logger.error("2. The system will use your browser cookies automatically")
                logger.error("\nSOLUTION 2: Manual download")
                logger.error("1. Download manually: yt-dlp -x --audio-format mp3 \"<youtube_url>\"")
                logger.error("2. Click 'Manual URL' in UI and provide the local file path")
                logger.error("="*60 + "\n")
            else:
                logger.error(f"yt-dlp error: {error_msg[:200]}")
        
        return False
            
    except Exception as e:
        logger.error(f"YouTube download error: {e}")
        return False


def _download_with_ytdlp_sync(url: str, ydl_opts: dict) -> bool:
    """Synchronous yt-dlp download helper for use in executor"""
    try:
        import yt_dlp
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        return True
        
    except Exception as e:
        logger.debug(f"yt-dlp sync download failed: {e}")
        return False