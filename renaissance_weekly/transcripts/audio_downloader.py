"""Specialized audio downloader with platform-specific strategies and validation"""

import re
import requests
import os
from urllib.parse import urlparse
from typing import Optional, Dict, Any
from pathlib import Path
import time
import subprocess

from ..utils.logging import get_logger

logger = get_logger(__name__)


class PlatformAudioDownloader:
    """Platform-specific audio download strategies with validation"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download_audio(self, url: str, output_path: Path, podcast_name: str = "") -> bool:
        """Download audio with platform-specific strategy and validation"""
        logger.info(f"🎵 Downloading audio from: {url[:80]}...")
        domain = urlparse(url).netloc.lower()
        
        # Platform-specific strategies
        strategies = {
            'api.substack.com': self._download_substack,
            'substack.com': self._download_substack,
            'traffic.libsyn.com': self._download_libsyn,
            'content.libsyn.com': self._download_libsyn,
            'anchor.fm': self._download_anchor,
            'feeds.simplecast.com': self._download_simplecast,
            'feeds.megaphone.fm': self._download_megaphone,
            'rss.art19.com': self._download_art19,
        }
        
        # Try platform-specific strategy
        for pattern, strategy in strategies.items():
            if pattern in domain:
                logger.info(f"📡 Using {strategy.__name__} strategy for {pattern}")
                if strategy(url, output_path):
                    # Validate the downloaded file
                    if self._validate_audio_file(output_path):
                        logger.info(f"✅ Successfully downloaded: {output_path.stat().st_size / 1_000_000:.1f}MB")
                        return True
                    else:
                        logger.warning(f"Downloaded file failed validation, removing: {output_path}")
                        if output_path.exists():
                            output_path.unlink()
        
        # Fallback to generic download
        logger.info("📡 Using generic download strategy")
        if self._download_generic(url, output_path):
            if self._validate_audio_file(output_path):
                logger.info(f"✅ Successfully downloaded: {output_path.stat().st_size / 1_000_000:.1f}MB")
                return True
            else:
                logger.warning(f"Downloaded file failed validation, removing: {output_path}")
                if output_path.exists():
                    output_path.unlink()
        
        logger.error(f"❌ All download strategies failed for: {url[:80]}...")
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
    
    def _download_substack(self, url: str, output_path: Path) -> bool:
        """Download from Substack with better error handling"""
        try:
            # Try multiple approaches for Substack
            approaches = [
                # Approach 1: Direct download with cookies
                {
                    'headers': {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                        'Accept': 'audio/mpeg, audio/*, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1',
                        'Cache-Control': 'max-age=0',
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
                            # Download with progress
                            total_size = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            
                            with open(output_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        
                                        if total_size > 0 and downloaded % (1024 * 1024 * 10) == 0:  # Every 10MB
                                            progress = (downloaded / total_size) * 100
                                            logger.debug(f"  Progress: {progress:.1f}% ({downloaded / 1_000_000:.1f}MB)")
                            
                            # Validate the file
                            if output_path.exists() and output_path.stat().st_size > 1000:
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
                '--max-time', '300',
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
            
            response = self.session.get(url, headers=headers, stream=True, allow_redirects=True, timeout=60)
            
            if response.status_code == 200:
                # Check content type
                content_type = response.headers.get('Content-Type', '').lower()
                if 'audio' in content_type or 'octet-stream' in content_type:
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    return True
                
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
            
            response = self.session.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Anchor download error: {e}")
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
            
            response = self.session.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code in [200, 206]:  # 206 for partial content
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Megaphone download error: {e}")
            return False
    
    def _download_art19(self, url: str, output_path: Path) -> bool:
        """Download from Art19"""
        try:
            # Art19 likes podcast app user agents
            headers = {
                'User-Agent': 'Overcast/3.0 (+http://overcast.fm/)',
                'Accept': 'audio/mpeg'
            }
            
            response = self.session.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Art19 download error: {e}")
            return False
    
    def _download_generic(self, url: str, output_path: Path) -> bool:
        """Generic download with multiple header attempts"""
        user_agents = [
            ('Podcasts/1.0', 'audio/*'),
            ('Mozilla/5.0 (compatible; GooglePodcasts)', '*/*'),
            ('CastBox/8.0 (fm.castbox.audiobook.radio.podcast)', 'audio/*'),
            ('Podbean/7.0 (http://podbean.com)', '*/*'),
            ('Overcast/3.0 (+http://overcast.fm/)', 'audio/mpeg'),
            ('AppleCoreMedia/1.0.0.20G75', '*/*'),
        ]
        
        for ua, accept in user_agents:
            try:
                headers = {
                    'User-Agent': ua, 
                    'Accept': accept,
                    'Accept-Encoding': 'identity',  # Avoid compressed responses
                }
                response = self.session.get(url, headers=headers, stream=True, timeout=60)
                
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
                    
                    # Download with progress
                    total_size = int(content_length) if content_length else 0
                    downloaded = 0
                    
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                
                                if total_size > 0 and downloaded % (1024 * 1024 * 10) == 0:  # Every 10MB
                                    progress = (downloaded / total_size) * 100
                                    logger.debug(f"  Progress: {progress:.1f}% ({downloaded / 1_000_000:.1f}MB)")
                        
                        # Validate size
                        if downloaded < 1000:
                            logger.warning(f"Downloaded file too small: {downloaded} bytes")
                            if output_path.exists():
                                output_path.unlink()
                            continue
                    
                    return True
                    
            except Exception as e:
                logger.debug(f"Generic download with UA '{ua}' failed: {e}")
                continue
        
        return False