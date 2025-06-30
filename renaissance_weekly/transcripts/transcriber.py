"""Audio transcription using OpenAI Whisper API with robust downloading"""

import os
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from typing import Optional, Tuple
import subprocess
import time
import re
import shutil
from urllib.parse import urlparse, parse_qs

from ..models import Episode
from ..config import AUDIO_DIR, TEMP_DIR, TESTING_MODE, MAX_TRANSCRIPTION_MINUTES
from ..utils.logging import get_logger
from ..utils.helpers import slugify
from ..utils.clients import openai_client

logger = get_logger(__name__)


class AudioTranscriber:
    """Transcribe podcast audio using OpenAI Whisper with robust downloading"""
    
    def __init__(self):
        self.max_retries = 3
        self.retry_delay = 5
        self.chunk_size = 8192
        # Enhanced headers for different download scenarios
        self.headers_presets = [
            {
                # Chrome on Mac - most compatible
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'audio/mpeg,audio/*;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'audio',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
                'Referer': 'https://www.google.com/'
            },
            {
                # Safari on Mac
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            },
            {
                # Podcast app
                'User-Agent': 'Podcasts/1.0.0 (+http://www.apple.com/itunes/)',
                'Accept': 'audio/*',
                'Range': 'bytes=0-'
            },
            {
                # Curl fallback
                'User-Agent': 'curl/7.68.0',
                'Accept': '*/*'
            }
        ]
    
    async def transcribe_episode(self, episode: Episode) -> Optional[str]:
        """Download and transcribe episode audio with robust error handling"""
        if not episode.audio_url:
            logger.error("No audio URL provided")
            return None
        
        try:
            # Download audio file with enhanced error handling
            audio_file = await self._download_audio_with_fallbacks(episode)
            if not audio_file:
                return None
            
            # Validate the audio file
            if not await self._validate_audio_file(audio_file):
                logger.error("Downloaded file is not valid audio")
                if audio_file.exists():
                    audio_file.unlink()
                return None
            
            # Transcribe with Whisper
            transcript = await self._transcribe_with_whisper(audio_file)
            
            # Cleanup
            if audio_file.exists():
                audio_file.unlink()
                logger.info("🧹 Cleaned up audio file")
            
            return transcript
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
    
    async def _download_audio_with_fallbacks(self, episode: Episode) -> Optional[Path]:
        """Download audio with multiple fallback strategies"""
        logger.info("📥 Downloading audio file...")
        
        # Create safe filename
        date_str = episode.published.strftime('%Y%m%d')
        safe_podcast = slugify(episode.podcast)[:30]
        safe_title = slugify(episode.title)[:50]
        audio_file = AUDIO_DIR / f"{date_str}_{safe_podcast}_{safe_title}.mp3"
        
        # Check if already exists
        if audio_file.exists() and audio_file.stat().st_size > 1000000:  # > 1MB
            logger.info("✅ Using cached audio file")
            return audio_file
        
        audio_url = episode.audio_url
        logger.info(f"⬇️ Downloading from: {audio_url[:80]}...")
        
        # Special handling for Substack URLs
        if 'substack.com' in audio_url:
            success = await self._download_substack_audio(audio_url, audio_file, episode)
            if success and audio_file.exists() and audio_file.stat().st_size > 1000000:
                return audio_file
        
        # Try each header preset for non-Substack URLs
        for i, headers in enumerate(self.headers_presets):
            try:
                logger.debug(f"Attempt {i+1} with {headers['User-Agent'][:30]}...")
                
                # Add referer based on domain
                domain = urlparse(audio_url).netloc
                if domain:
                    headers = headers.copy()
                    headers['Referer'] = f'https://{domain}/'
                
                # Try async download first
                success = await self._download_with_aiohttp(audio_url, audio_file, headers)
                if success and audio_file.exists() and audio_file.stat().st_size > 1000000:
                    return audio_file
                
                # If async fails, try requests
                if not success:
                    success = await self._download_with_requests(audio_url, audio_file, headers)
                    if success and audio_file.exists() and audio_file.stat().st_size > 1000000:
                        return audio_file
                
            except Exception as e:
                logger.debug(f"Download attempt {i+1} failed: {e}")
                if audio_file.exists():
                    audio_file.unlink()
                continue
        
        # Last resort: try curl/wget with special options
        logger.warning("All HTTP attempts failed, trying system tools...")
        success = await self._download_with_system_tool(audio_url, audio_file)
        if success and audio_file.exists() and audio_file.stat().st_size > 1000000:
            return audio_file
        
        logger.error("All download attempts failed")
        return None
    
    async def _download_substack_audio(self, url: str, output_file: Path, episode: Episode) -> bool:
        """Special handling for Substack audio downloads"""
        logger.info("🔧 Using Substack-specific download method...")
        
        # Extract the actual MP3 URL from Substack's redirect URL
        # Substack URLs often have the format: /feed/podcast/{id}/{hash}
        parsed = urlparse(url)
        
        # Try to get the direct MP3 URL
        try:
            # Method 1: Check if it's already a direct MP3 URL
            if url.endswith('.mp3') or 'audio' in url:
                return await self._download_direct_url(url, output_file)
            
            # Method 2: Try to construct direct URL from Substack pattern
            if '/feed/podcast/' in url:
                # Extract episode ID from URL
                match = re.search(r'/feed/podcast/(\d+)/', url)
                if match:
                    episode_id = match.group(1)
                    
                    # Try common Substack audio URL patterns
                    direct_urls = [
                        f"https://api.substack.com/api/v1/audio/upload/{episode_id}/src",
                        f"https://substackcdn.com/audio/{episode_id}.mp3",
                        f"https://api.substack.com/feed/podcast/{episode_id}/audio.mp3"
                    ]
                    
                    for direct_url in direct_urls:
                        logger.debug(f"Trying direct Substack URL: {direct_url}")
                        if await self._download_direct_url(direct_url, output_file):
                            return True
            
            # Method 3: Use episode link to find audio URL
            if hasattr(episode, 'link') and episode.link:
                audio_url = await self._find_substack_audio_url(episode.link)
                if audio_url:
                    return await self._download_direct_url(audio_url, output_file)
            
            # Method 4: Try with special Substack headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': 'audio/mpeg,audio/*;q=0.9,*/*;q=0.8',
                'Referer': 'https://substack.com/',
                'Origin': 'https://substack.com',
                'Sec-Fetch-Dest': 'audio',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            return await self._download_with_aiohttp(url, output_file, headers)
            
        except Exception as e:
            logger.error(f"Substack download error: {e}")
            return False
    
    async def _find_substack_audio_url(self, episode_url: str) -> Optional[str]:
        """Find audio URL from Substack episode page"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(episode_url) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Look for audio URL in the page
                        patterns = [
                            r'<audio[^>]+src="([^"]+)"',
                            r'"audio_url":"([^"]+)"',
                            r'data-audio-url="([^"]+)"',
                            r'"url":"(https://[^"]+\.mp3)"'
                        ]
                        
                        for pattern in patterns:
                            match = re.search(pattern, html)
                            if match:
                                audio_url = match.group(1)
                                if audio_url.startswith('//'):
                                    audio_url = 'https:' + audio_url
                                elif audio_url.startswith('/'):
                                    audio_url = f"https://substack.com{audio_url}"
                                logger.info(f"Found audio URL in page: {audio_url}")
                                return audio_url
        except Exception as e:
            logger.debug(f"Failed to find audio URL in page: {e}")
        
        return None
    
    async def _download_direct_url(self, url: str, output_file: Path) -> bool:
        """Download from a direct URL with multiple attempts"""
        headers_list = [
            {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'identity',  # Avoid compression issues
                'Range': 'bytes=0-'  # Support partial content
            },
            {
                'User-Agent': 'Podcasts/1.0',
                'Accept': 'audio/*'
            },
            {}  # No headers
        ]
        
        for headers in headers_list:
            if await self._download_with_aiohttp(url, output_file, headers):
                return True
            if await self._download_with_requests(url, output_file, headers):
                return True
        
        return False
    
    async def _download_with_aiohttp(self, url: str, output_file: Path, headers: dict) -> bool:
        """Download using aiohttp with progress tracking"""
        try:
            timeout = aiohttp.ClientTimeout(total=300, connect=30)
            connector = aiohttp.TCPConnector(force_close=True)
            
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.get(url, headers=headers, allow_redirects=True, ssl=False) as response:
                    # Check status
                    if response.status == 403:
                        logger.error(f"Download failed: HTTP 403")
                        return False
                    elif response.status not in [200, 206]:  # 206 is partial content
                        logger.error(f"Download failed: HTTP {response.status}")
                        return False
                    
                    # Get file size
                    total_size = int(response.headers.get('Content-Length', 0))
                    if total_size > 0:
                        logger.info(f"📦 Download size: {total_size / 1024 / 1024:.1f} MB")
                    
                    # Download with progress
                    async with aiofiles.open(output_file, 'wb') as file:
                        downloaded = 0
                        last_progress = 0
                        
                        async for chunk in response.content.iter_chunked(self.chunk_size):
                            await file.write(chunk)
                            downloaded += len(chunk)
                            
                            # Show progress
                            if total_size > 0:
                                progress = int((downloaded / total_size) * 100)
                                if progress >= last_progress + 10:
                                    logger.info(f"   Progress: {progress}%")
                                    last_progress = progress
                    
                    logger.info(f"✅ Download complete: {output_file.name}")
                    logger.info(f"📊 Audio file size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
                    return True
                    
        except asyncio.TimeoutError:
            logger.error("Download timeout")
            return False
        except Exception as e:
            logger.debug(f"aiohttp download error: {e}")
            return False
    
    async def _download_with_requests(self, url: str, output_file: Path, headers: dict) -> bool:
        """Fallback download using requests library"""
        import requests
        
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            def download():
                session = requests.Session()
                session.headers.update(headers)
                
                # Add SSL verification bypass for problematic certificates
                session.verify = False
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                
                response = session.get(url, stream=True, timeout=60, allow_redirects=True)
                if response.status_code == 403:
                    logger.error(f"Download failed: HTTP 403")
                    return False
                elif response.status_code not in [200, 206]:
                    logger.error(f"Download failed: HTTP {response.status_code}")
                    return False
                
                total_size = int(response.headers.get('Content-Length', 0))
                if total_size > 0:
                    logger.info(f"📦 Download size: {total_size / 1024 / 1024:.1f} MB")
                
                with open(output_file, 'wb') as f:
                    downloaded = 0
                    last_progress = 0
                    
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                progress = int((downloaded / total_size) * 100)
                                if progress >= last_progress + 10:
                                    logger.info(f"   Progress: {progress}%")
                                    last_progress = progress
                
                logger.info(f"✅ Download complete: {output_file.name}")
                return True
            
            return await loop.run_in_executor(None, download)
            
        except Exception as e:
            logger.debug(f"requests download error: {e}")
            return False
    
    async def _download_with_system_tool(self, url: str, output_file: Path) -> bool:
        """Last resort: use curl or wget with enhanced options"""
        try:
            # Try yt-dlp first (best for media downloads)
            if shutil.which('yt-dlp'):
                logger.info("🎯 Trying yt-dlp (most reliable for protected audio)...")
                cmd = [
                    'yt-dlp',
                    '--no-check-certificate',
                    '-f', 'bestaudio[ext=mp3]/bestaudio/best',
                    '--extract-audio',
                    '--audio-format', 'mp3',
                    '--audio-quality', '128K',
                    '--output', str(output_file),
                    '--quiet',
                    '--no-warnings',
                    '--no-playlist',
                    '--user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    url
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and output_file.exists():
                    logger.info("✅ Downloaded with yt-dlp")
                    return True
                else:
                    logger.debug(f"yt-dlp failed: {stderr.decode()}")
            else:
                logger.warning("⚠️ yt-dlp not found - this is the most reliable download method")
                logger.warning("   Install with: pip install yt-dlp or ./install_deps.sh")
            
            # Try curl with more options
            cmd = [
                'curl', '-L', '-f', '-s', '-S',
                '--compressed',
                '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                '-H', 'Accept: audio/mpeg,audio/*;q=0.9,*/*;q=0.8',
                '-H', 'Accept-Language: en-US,en;q=0.9',
                '-H', 'Cache-Control: no-cache',
                '--connect-timeout', '30',
                '--max-time', '300',
                '--retry', '3',
                '--retry-delay', '5',
                '-k',  # Allow insecure connections
                '-o', str(output_file),
                url
            ]
            
            # Add referer if it's a known domain
            domain = urlparse(url).netloc
            if domain:
                cmd.extend(['-H', f'Referer: https://{domain}/'])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and output_file.exists():
                logger.info("✅ Downloaded with curl")
                return True
            else:
                logger.debug(f"curl failed: {stderr.decode()}")
                
                # Try wget as last resort
                if output_file.exists():
                    output_file.unlink()
                
                cmd = [
                    'wget', '-q', '-O', str(output_file),
                    '--user-agent=Mozilla/5.0',
                    '--header=Accept: audio/*',
                    '--header=Accept-Language: en-US,en;q=0.9',
                    '--timeout=30',
                    '--tries=3',
                    '--no-check-certificate',
                    url
                ]
                
                if domain:
                    cmd.append(f'--header=Referer: https://{domain}/')
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and output_file.exists():
                    logger.info("✅ Downloaded with wget")
                    return True
                else:
                    logger.debug(f"wget failed: {stderr.decode()}")
                    
        except Exception as e:
            logger.debug(f"System tool download error: {e}")
        
        return False
    
    async def _validate_audio_file(self, audio_file: Path) -> bool:
        """Validate that the downloaded file is actually audio"""
        try:
            # Check file size
            file_size = audio_file.stat().st_size
            if file_size < 10000:  # Less than 10KB is suspicious
                logger.error(f"File too small: {file_size} bytes")
                return False
            
            # Check file header for audio signatures
            with open(audio_file, 'rb') as f:
                header = f.read(16)
            
            # Common audio file signatures
            audio_signatures = [
                b'ID3',       # MP3 with ID3 tag
                b'\xff\xfb',  # MP3
                b'\xff\xf3',  # MP3
                b'\xff\xf2',  # MP3
                b'RIFF',      # WAV
                b'ftyp',      # MP4/M4A
                b'OggS',      # OGG
            ]
            
            if not any(header.startswith(sig) for sig in audio_signatures):
                # Check if it's HTML (common error response)
                if header.lower().startswith(b'<!doctype') or header.lower().startswith(b'<html'):
                    logger.error("Downloaded file is HTML, not audio")
                    
                    # Log the content for debugging
                    with open(audio_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(1000)
                        logger.debug(f"HTML content: {content[:200]}...")
                    
                    return False
                
                # Try to probe with ffprobe
                return await self._probe_with_ffmpeg(audio_file)
            
            return True
            
        except Exception as e:
            logger.error(f"File validation error: {e}")
            return False
    
    async def _probe_with_ffmpeg(self, audio_file: Path) -> bool:
        """Use ffprobe to validate audio file"""
        try:
            import shutil
            if not shutil.which('ffprobe'):
                logger.debug("ffprobe not available, assuming file is valid")
                return True
            
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 
                   'format=format_name,duration', '-of', 'json', str(audio_file)]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                import json
                probe_data = json.loads(stdout.decode())
                if 'format' in probe_data and probe_data['format'].get('format_name'):
                    logger.info(f"✅ Valid audio format: {probe_data['format']['format_name']}")
                    return True
            
            logger.error(f"ffprobe validation failed: {stderr.decode()}")
            return False
            
        except Exception as e:
            logger.debug(f"ffprobe error: {e}")
            # If ffprobe isn't available or fails, assume file is valid
            return True
    
    async def _transcribe_with_whisper(self, audio_file: Path) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper API"""
        logger.info("🎤 Starting transcription with Whisper...")
        
        # Handle test mode truncation
        if TESTING_MODE:
            logger.info(f"🧪 TEST MODE: Limiting to {MAX_TRANSCRIPTION_MINUTES} minutes")
            trimmed_file = await self._trim_audio(audio_file, MAX_TRANSCRIPTION_MINUTES * 60)
            if trimmed_file:
                audio_file = trimmed_file
        
        # Ensure file is under 25MB (Whisper limit)
        file_size = audio_file.stat().st_size
        if file_size > 25 * 1024 * 1024:
            logger.warning(f"File too large ({file_size / 1024 / 1024:.1f} MB), compressing...")
            compressed_file = await self._compress_audio(audio_file)
            if compressed_file:
                audio_file = compressed_file
            else:
                logger.error("Failed to compress audio file")
                return None
        
        # Try transcription with retries
        for attempt in range(self.max_retries):
            try:
                logger.info(f"🎯 Calling Whisper API (attempt {attempt + 1}/{self.max_retries})...")
                
                with open(audio_file, 'rb') as f:
                    # Run in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    
                    def api_call():
                        return openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=f,
                            response_format="text",
                            language="en"  # Assuming English, adjust if needed
                        )
                    
                    transcript = await loop.run_in_executor(None, api_call)
                
                if transcript and len(transcript.strip()) > 100:
                    logger.info(f"✅ Transcription complete: {len(transcript)} characters")
                    return transcript.strip()
                else:
                    logger.error("Transcription returned empty result")
                    
            except Exception as e:
                logger.error(f"Whisper API error: {e}")
                if "format is not supported" in str(e):
                    # Try to convert the audio file
                    converted_file = await self._convert_audio_format(audio_file)
                    if converted_file:
                        audio_file = converted_file
                        continue
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("All transcription attempts failed")
        
        return None
    
    async def _trim_audio(self, audio_file: Path, max_seconds: int) -> Optional[Path]:
        """Trim audio file to specified duration"""
        try:
            logger.info(f"✂️ Trimming audio to {max_seconds} seconds...")
            
            # Create output file
            trimmed_file = TEMP_DIR / f"trimmed_{audio_file.name}"
            
            # Check if ffmpeg is available
            import shutil
            if shutil.which('ffmpeg'):
                # Use ffmpeg to trim
                cmd = [
                    'ffmpeg', '-i', str(audio_file),
                    '-t', str(max_seconds),
                    '-c', 'copy',  # Copy codec to avoid re-encoding
                    '-y',  # Overwrite output
                    str(trimmed_file)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and trimmed_file.exists():
                    logger.info("✅ Audio trimmed successfully")
                    return trimmed_file
                else:
                    logger.error(f"ffmpeg trim failed: {stderr.decode()}")
            
            # Fallback: use pydub
            return await self._trim_with_pydub(audio_file, max_seconds)
                
        except Exception as e:
            logger.error(f"Audio trim error: {e}")
            # Fallback: use pydub
            return await self._trim_with_pydub(audio_file, max_seconds)
    
    async def _trim_with_pydub(self, audio_file: Path, max_seconds: int) -> Optional[Path]:
        """Fallback: trim audio using pydub"""
        try:
            from pydub import AudioSegment
            
            logger.info("Using pydub for trimming...")
            
            # Load audio
            audio = AudioSegment.from_file(str(audio_file))
            
            # Trim to max duration
            trimmed = audio[:max_seconds * 1000]  # pydub uses milliseconds
            
            # Export
            trimmed_file = TEMP_DIR / f"trimmed_{audio_file.name}"
            trimmed.export(str(trimmed_file), format="mp3")
            
            logger.info("✅ Audio trimmed successfully")
            return trimmed_file
            
        except Exception as e:
            logger.error(f"Pydub trim error: {e}")
            # If trimming fails, return original file
            return audio_file
    
    async def _compress_audio(self, audio_file: Path) -> Optional[Path]:
        """Compress audio file to reduce size"""
        try:
            compressed_file = TEMP_DIR / f"compressed_{audio_file.name}"
            
            import shutil
            if shutil.which('ffmpeg'):
                # Use ffmpeg to compress
                cmd = [
                    'ffmpeg', '-i', str(audio_file),
                    '-b:a', '64k',  # 64kbps bitrate
                    '-ar', '16000',  # 16kHz sample rate (sufficient for speech)
                    '-ac', '1',  # Mono
                    '-y',
                    str(compressed_file)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                await process.communicate()
                
                if process.returncode == 0 and compressed_file.exists():
                    new_size = compressed_file.stat().st_size
                    logger.info(f"✅ Compressed to {new_size / 1024 / 1024:.1f} MB")
                    return compressed_file
            else:
                # Try pydub compression
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(audio_file))
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(str(compressed_file), format="mp3", bitrate="64k")
                logger.info(f"✅ Compressed with pydub")
                return compressed_file
                
        except Exception as e:
            logger.error(f"Compression error: {e}")
        
        return None
    
    async def _convert_audio_format(self, audio_file: Path) -> Optional[Path]:
        """Convert audio to a format Whisper can handle"""
        try:
            logger.info("🔄 Converting audio format...")
            
            converted_file = TEMP_DIR / f"converted_{audio_file.stem}.mp3"
            
            import shutil
            if shutil.which('ffmpeg'):
                # Use ffmpeg to convert
                cmd = [
                    'ffmpeg', '-i', str(audio_file),
                    '-acodec', 'libmp3lame',
                    '-b:a', '128k',
                    '-ar', '44100',
                    '-y',
                    str(converted_file)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and converted_file.exists():
                    logger.info("✅ Audio converted successfully")
                    return converted_file
                else:
                    logger.error(f"ffmpeg conversion failed: {stderr.decode()}")
            else:
                # Try pydub conversion
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(audio_file))
                audio.export(str(converted_file), format="mp3", bitrate="128k")
                logger.info("✅ Audio converted with pydub")
                return converted_file
                
        except Exception as e:
            logger.error(f"Audio conversion error: {e}")
        
        return None