"""Audio transcription using AssemblyAI (primary) or OpenAI Whisper (fallback) with robust downloading"""

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
import uuid
import tempfile
import gc

from ..models import Episode
from ..config import AUDIO_DIR, TEMP_DIR, TESTING_MODE, MAX_TRANSCRIPTION_MINUTES
from ..utils.logging import get_logger
from ..fetchers.audio_sources import AudioSourceFinder
from ..utils.filename_utils import generate_audio_filename, generate_temp_filename
from ..utils.helpers import (
    slugify, validate_audio_file_comprehensive, validate_audio_file_smart, 
    exponential_backoff_with_jitter, retry_with_backoff, ProgressTracker, 
    calculate_file_hash, CircuitBreaker
)
from ..utils.clients import openai_client, openai_rate_limiter, whisper_rate_limiter
from ..robustness_config import should_use_feature

logger = get_logger(__name__)


class AudioTranscriber:
    """Transcribe podcast audio using AssemblyAI (primary) or OpenAI Whisper (fallback)"""
    
    def __init__(self):
        self.max_retries = 5  # Increased from 3
        self.retry_delay = 1.0
        self.chunk_size = 8192
        self.validation_interval = 1024 * 1024  # Validate every 1MB during download
        self.session = None
        self._session_lock = asyncio.Lock()
        self.temp_files = set()  # Track temp files for cleanup
        self._current_mode = 'test'  # Default mode, updated per episode
        
        # Check for ffmpeg availability (critical for memory-efficient trimming)
        import shutil
        self.ffmpeg_available = shutil.which('ffmpeg') is not None
        if self.ffmpeg_available:
            logger.info("✅ ffmpeg available for memory-efficient audio trimming")
        else:
            logger.warning("⚠️  ffmpeg NOT found! Audio trimming will use more memory. Install with: sudo apt-get install ffmpeg")
        
        # Initialize AssemblyAI transcriber if API key is available
        self.assemblyai_transcriber = None
        if os.getenv('ASSEMBLYAI_API_KEY'):
            try:
                from .assemblyai_transcriber import AssemblyAITranscriber
                self.assemblyai_transcriber = AssemblyAITranscriber()
                logger.info("✅ AssemblyAI transcriber initialized (32x concurrency)")
            except Exception as e:
                logger.warning(f"Failed to initialize AssemblyAI: {e}")
                
        # Circuit breaker for OpenAI API with special rate limit handling
        self.openai_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            rate_limit_threshold=3,
            rate_limit_recovery=300.0,  # 5 minutes for rate limits
            correlation_id="openai-whisper"
        )
        
        # Enhanced headers for different download scenarios
        self.headers_presets = [
            {
                # Apple Podcasts (most reliable for podcast content)
                'User-Agent': 'Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'br, gzip, deflate',
                'Connection': 'keep-alive',
                'X-Apple-Store-Front': '143441-1,32'
            },
            {
                # Chrome with audio context - good for web-based podcasts
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,video/*;q=0.6,*/*;q=0.5',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'identity;q=1, *;q=0',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'audio',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
                'Range': 'bytes=0-'
            },
            {
                # Overcast - popular podcast app
                'User-Agent': 'Overcast/2024.1 (+http://overcast.fm/; iOS podcast app)',
                'Accept': 'audio/mpeg, audio/*',
                'Accept-Encoding': 'gzip, deflate',
                'X-Playback-Session-Id': str(uuid.uuid4()),
                'Connection': 'keep-alive'
            },
            {
                # Spotify podcast user agent
                'User-Agent': 'Spotify/8.8.0 iOS/16.6 (iPhone13)',
                'Accept': 'audio/mpeg, audio/*;q=0.9, */*;q=0.8',
                'Accept-Language': 'en',
                'Accept-Encoding': 'gzip',
            },
            {
                # Generic mobile browser fallback
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }
        ]
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with proper configuration"""
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(
                    total=600,    # 10 minutes total
                    connect=30,   # 30s connect timeout
                    sock_read=60  # 60s read timeout
                )
                connector = aiohttp.TCPConnector(
                    limit=10,
                    limit_per_host=2,
                    force_close=True,
                    enable_cleanup_closed=True
                )
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector
                )
            return self.session
    
    async def cleanup(self):
        """Cleanup resources and temporary files"""
        try:
            # Close session
            if self.session and not self.session.closed:
                await self.session.close()
                self.session = None
            
            # Clean up temp files
            for temp_file in self.temp_files:
                try:
                    if Path(temp_file).exists():
                        Path(temp_file).unlink()
                        logger.debug(f"Cleaned up temp file: {temp_file}")
                except Exception as e:
                    logger.debug(f"Failed to clean up {temp_file}: {e}")
            
            self.temp_files.clear()
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    async def transcribe_episode(self, episode: Episode, transcription_mode: str = None) -> Optional[str]:
        """Download and transcribe episode audio with robust error handling"""
        correlation_id = str(uuid.uuid4())[:8]
        logger.info(f"[{correlation_id}] Starting transcription for: {episode.title}")
        
        # Use provided mode or fall back to environment setting
        self._current_mode = transcription_mode if transcription_mode else ('test' if TESTING_MODE else 'full')
        
        audio_file = None
        temp_files_to_clean = []
        
        try:
            # Download audio file with enhanced error handling
            audio_file = await self._download_audio_with_fallbacks(episode, correlation_id)
            if not audio_file:
                return None
            
            temp_files_to_clean.append(audio_file)
            
            # Comprehensive validation with smart mode
            if not validate_audio_file_smart(audio_file, correlation_id, episode.audio_url):
                logger.error(f"[{correlation_id}] Downloaded file failed comprehensive validation")
                return None
            
            # Additional validation with ffprobe if available
            if not await self._validate_with_ffprobe(audio_file, correlation_id):
                logger.warning(f"[{correlation_id}] FFprobe validation failed, but continuing")
            
            # Try AssemblyAI first if available
            transcript = None
            if self.assemblyai_transcriber:
                try:
                    logger.info(f"[{correlation_id}] 🚀 Using AssemblyAI for transcription (32x concurrency)")
                    transcript = await self.assemblyai_transcriber.transcribe_episode(
                        episode, audio_file, self._current_mode
                    )
                    if transcript:
                        logger.info(f"[{correlation_id}] ✅ AssemblyAI transcription successful")
                except Exception as e:
                    logger.warning(f"[{correlation_id}] AssemblyAI failed, falling back to Whisper: {e}")
            
            # Fall back to Whisper if AssemblyAI failed or unavailable
            if not transcript:
                logger.info(f"[{correlation_id}] Using OpenAI Whisper for transcription")
                transcript = await self._transcribe_with_whisper(audio_file, correlation_id)
            
            # Stream processing: delete audio file immediately after successful transcription
            if transcript and self._current_mode == 'full':
                try:
                    if audio_file.exists():
                        audio_file.unlink()
                        self.temp_files.discard(str(audio_file))
                        temp_files_to_clean.remove(audio_file)
                        logger.info(f"[{correlation_id}] 🗑️  Deleted audio file immediately to save disk space")
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Could not delete audio file immediately: {e}")
            
            # Force garbage collection after processing large audio files
            gc.collect()
            
            return transcript
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Transcription error: {e}", exc_info=True)
            return None
            
        finally:
            # Cleanup in finally block
            for file_path in temp_files_to_clean:
                try:
                    if file_path and file_path.exists():
                        file_path.unlink()
                        logger.debug(f"[{correlation_id}] Cleaned up: {file_path.name}")
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Cleanup error: {e}")
            
            # Remove from tracked temp files
            for file_path in temp_files_to_clean:
                self.temp_files.discard(str(file_path))
    
    async def download_audio_simple(self, episode: Episode, url: str, correlation_id: str) -> Optional[Path]:
        """Simple audio download without retry logic - for use with DownloadManager"""
        logger.info(f"[{correlation_id}] 📥 Downloading audio from: {url[:80]}...")
        
        # Create safe filename
        # Generate standardized filename
        mode = 'test' if self._current_mode == 'test' else 'full'
        filename = generate_audio_filename(episode, mode)
        audio_file = AUDIO_DIR / filename
        
        # Check if already exists and is valid
        if audio_file.exists():
            if validate_audio_file_smart(audio_file, correlation_id, url):
                file_hash = calculate_file_hash(audio_file)
                logger.info(f"[{correlation_id}] ✅ Using cached audio file (hash: {file_hash[:8]}...)")
                return audio_file
            else:
                logger.warning(f"[{correlation_id}] Cached file invalid, re-downloading")
                audio_file.unlink()
        
        # Track this file for cleanup on failure
        should_cleanup = True
        self.temp_files.add(str(audio_file))
        
        try:
            # Check if this is a YouTube URL or yt-dlp search
            if 'youtube.com' in url or 'youtu.be' in url or url.startswith('ytsearch'):
                logger.info(f"[{correlation_id}] 🎥 Detected YouTube URL, using yt-dlp")
                try:
                    # Use yt-dlp for YouTube downloads
                    from .audio_downloader import download_audio_with_ytdlp
                    success = await download_audio_with_ytdlp(url, audio_file)
                    if success and audio_file.exists():
                        if validate_audio_file_smart(audio_file, correlation_id, url):
                            logger.info(f"[{correlation_id}] ✅ YouTube download successful")
                            should_cleanup = False  # Success, don't cleanup
                            return audio_file
                        else:
                            logger.warning(f"[{correlation_id}] YouTube download failed validation")
                            if audio_file.exists():
                                audio_file.unlink()
                except Exception as e:
                    logger.error(f"[{correlation_id}] YouTube download error: {e}")
                    if audio_file.exists():
                        audio_file.unlink()
                return None
            
            # Try downloading with best headers for non-YouTube URLs
            headers = self.headers_presets[0]  # Use best headers
            
            # Try aiohttp download
            try:
                success = await self._download_with_aiohttp_validated(
                    url, audio_file, headers, correlation_id
                )
                if success and audio_file.exists():
                    if validate_audio_file_smart(audio_file, correlation_id, url):
                        logger.info(f"[{correlation_id}] ✅ Download successful")
                        should_cleanup = False  # Success, don't cleanup
                        return audio_file
                    else:
                        logger.warning(f"[{correlation_id}] Downloaded file failed validation")
                        if audio_file.exists():
                            audio_file.unlink()
            except Exception as e:
                logger.warning(f"[{correlation_id}] Download failed: {e}")
                if audio_file.exists():
                    audio_file.unlink()
            
            return None
        finally:
            # Cleanup on failure
            if should_cleanup:
                self.temp_files.discard(str(audio_file))
                if audio_file.exists():
                    try:
                        audio_file.unlink()
                    except Exception:
                        pass
    
    async def _download_audio_with_fallbacks(self, episode: Episode, correlation_id: str) -> Optional[Path]:
        """Download audio with multiple fallback strategies and exponential backoff"""
        logger.info(f"[{correlation_id}] 📥 Downloading audio file...")
        
        # Create safe filename
        # Generate standardized filename
        mode = 'test' if self._current_mode == 'test' else 'full'
        filename = generate_audio_filename(episode, mode)
        audio_file = AUDIO_DIR / filename
        
        # Check if already exists and is valid
        if audio_file.exists():
            if validate_audio_file_smart(audio_file, correlation_id, episode.audio_url):
                file_hash = calculate_file_hash(audio_file)
                logger.info(f"[{correlation_id}] ✅ Using cached audio file (hash: {file_hash[:8]}...)")
                return audio_file
            else:
                logger.warning(f"[{correlation_id}] Cached file invalid, re-downloading")
                audio_file.unlink()
        
        # Find all available audio sources
        if should_use_feature('use_multiple_audio_sources'):
            logger.info(f"[{correlation_id}] 🔍 Searching for audio sources...")
            audio_source_finder = AudioSourceFinder()
            async with audio_source_finder:
                audio_sources = await audio_source_finder.find_all_audio_sources(episode)
            
            if not audio_sources:
                logger.error(f"[{correlation_id}] No audio sources found")
                return None
            
            logger.info(f"[{correlation_id}] Found {len(audio_sources)} audio source(s)")
        else:
            # Use original single audio URL
            if not episode.audio_url:
                logger.error(f"[{correlation_id}] No audio URL provided")
                return None
            audio_sources = [episode.audio_url]
            logger.info(f"[{correlation_id}] Using single audio source from RSS")
        
        # Track this file for cleanup
        self.temp_files.add(str(audio_file))
        
        # Try each audio source in order
        for source_idx, audio_url in enumerate(audio_sources):
            logger.info(f"[{correlation_id}] Trying source {source_idx + 1}/{len(audio_sources)}: {audio_url[:80]}...")
            
            # First, try to resolve redirects to get direct CDN URL
            try:
                from .redirect_resolver import RedirectResolver
                async with RedirectResolver() as resolver:
                    resolved_url, redirect_chain = await resolver.resolve_redirect_chain(audio_url)
                    if resolved_url != audio_url:
                        logger.info(f"[{correlation_id}] Resolved to direct CDN URL: {resolved_url[:80]}...")
                        # Try the resolved URL first
                        audio_sources.insert(source_idx + 1, resolved_url)
            except Exception as e:
                logger.debug(f"[{correlation_id}] Redirect resolution failed: {e}")
            
            # Use PlatformAudioDownloader for initial attempt
            try:
                from .audio_downloader import PlatformAudioDownloader
                platform_downloader = PlatformAudioDownloader()
                
                # Try platform-specific download first
                success = await asyncio.get_event_loop().run_in_executor(
                    None, 
                    platform_downloader.download_audio,
                    audio_url,
                    audio_file,
                    episode.podcast
                )
                
                if success and audio_file.exists() and validate_audio_file_smart(audio_file, correlation_id, audio_url):
                    logger.info(f"[{correlation_id}] ✅ Platform-specific download successful from source {source_idx + 1}")
                    return audio_file
                else:
                    logger.debug(f"[{correlation_id}] Platform-specific download failed, trying generic methods...")
            except Exception as e:
                logger.debug(f"[{correlation_id}] Platform downloader error: {e}")
        
            # Try each header preset with exponential backoff
            for attempt, headers in enumerate(self.headers_presets):
                try:
                    # Add exponential backoff delay (except for first attempt)
                    if attempt > 0:
                        delay = exponential_backoff_with_jitter(attempt - 1, base_delay=2.0, max_delay=30.0)
                        logger.info(f"[{correlation_id}] Waiting {delay:.1f}s before attempt {attempt + 1}")
                        await asyncio.sleep(delay)
                    
                    logger.debug(f"[{correlation_id}] Attempt {attempt + 1} with {headers['User-Agent'][:30]}...")
                    
                    # Add referer based on domain
                    domain = urlparse(audio_url).netloc
                    if domain:
                        headers = headers.copy()
                        headers['Referer'] = f'https://{domain}/'
                    
                    # Try async download with validation
                    success = await self._download_with_aiohttp_validated(
                        audio_url, audio_file, headers, correlation_id
                    )
                    if success:
                        return audio_file
                    
                    # If async fails, try requests with validation
                    if not success:
                        success = await self._download_with_requests_validated(
                            audio_url, audio_file, headers, correlation_id
                        )
                        if success:
                            return audio_file
                    
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Download attempt {attempt + 1} failed: {e}")
                    if audio_file.exists():
                        audio_file.unlink()
                    continue
            
            # Try browser automation for Cloudflare-protected content
            if 'substack.com' in audio_url or 'cloudflare' in str(e).lower() if 'e' in locals() else False:
                logger.warning(f"[{correlation_id}] Attempting browser-based download for protected content...")
                try:
                    from .browser_downloader import download_with_browser_sync
                    success = await asyncio.get_event_loop().run_in_executor(
                        None,
                        download_with_browser_sync,
                        audio_url,
                        str(audio_file),
                        120
                    )
                    if success and validate_audio_file_smart(audio_file, correlation_id, audio_url):
                        logger.info(f"[{correlation_id}] ✅ Browser download successful")
                        return audio_file
                except Exception as browser_error:
                    logger.error(f"[{correlation_id}] Browser download failed: {browser_error}")
            
            # Last resort: try system tools with special options
            logger.warning(f"[{correlation_id}] All HTTP attempts failed for source {source_idx + 1}, trying system tools...")
            success = await self._download_with_system_tool(audio_url, audio_file, correlation_id)
            if success and validate_audio_file_smart(audio_file, correlation_id, audio_url):
                return audio_file
        
        logger.error(f"[{correlation_id}] All download attempts failed")
        return None
    
    async def _download_with_aiohttp_validated(self, url: str, output_file: Path, headers: dict, correlation_id: str) -> bool:
        """Download using aiohttp with chunked validation"""
        temp_file = None
        
        try:
            # Use temporary file during download
            temp_file = output_file.with_suffix('.tmp')
            self.temp_files.add(str(temp_file))
            
            session = await self._get_session()
            
            async with session.get(url, headers=headers, allow_redirects=True, ssl=False) as response:
                # Check status
                if response.status == 403:
                    logger.error(f"[{correlation_id}] Download failed: HTTP 403")
                    return False
                elif response.status not in [200, 206]:  # 206 is partial content
                    logger.error(f"[{correlation_id}] Download failed: HTTP {response.status}")
                    return False
                
                # Check content type
                content_type = response.headers.get('Content-Type', '').lower()
                if 'text/html' in content_type:
                    logger.error(f"[{correlation_id}] Received HTML instead of audio")
                    return False
                
                # Get file size
                total_size = int(response.headers.get('Content-Length', 0))
                if total_size > 0:
                    logger.info(f"[{correlation_id}] 📦 Download size: {total_size / 1024 / 1024:.1f} MB")
                
                # Download with progress and validation
                async with aiofiles.open(temp_file, 'wb') as file:
                    downloaded = 0
                    last_progress = 0
                    validation_errors = 0
                    first_chunk_validated = False
                    
                    async for chunk in response.content.iter_chunked(self.chunk_size):
                        await file.write(chunk)
                        downloaded += len(chunk)
                        
                        # Validate first chunk
                        if not first_chunk_validated and downloaded >= 16:
                            await file.flush()
                            if not await self._validate_first_chunk(temp_file, correlation_id):
                                logger.error(f"[{correlation_id}] First chunk validation failed")
                                return False
                            first_chunk_validated = True
                        
                        # Periodic validation every 1MB
                        if downloaded % self.validation_interval == 0:
                            await file.flush()
                            # Quick size check
                            if temp_file.stat().st_size != downloaded:
                                validation_errors += 1
                                logger.warning(f"[{correlation_id}] Size mismatch at {downloaded} bytes")
                                if validation_errors > 3:
                                    logger.error(f"[{correlation_id}] Too many validation errors")
                                    return False
                        
                        # Show progress
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            if progress >= last_progress + 10:
                                logger.info(f"[{correlation_id}]    Progress: {progress}%")
                                last_progress = progress
                
                # Final validation
                if not await self._validate_download_complete(temp_file, downloaded, total_size, correlation_id):
                    return False
                
                # Move to final location
                shutil.move(str(temp_file), str(output_file))
                self.temp_files.discard(str(temp_file))
                
                logger.info(f"[{correlation_id}] ✅ Download complete: {output_file.name}")
                logger.info(f"[{correlation_id}] 📊 Audio file size: {output_file.stat().st_size / 1024 / 1024:.1f} MB")
                return True
                
        except asyncio.TimeoutError:
            logger.error(f"[{correlation_id}] Download timeout")
            return False
        except Exception as e:
            logger.debug(f"[{correlation_id}] aiohttp download error: {e}")
            return False
        finally:
            # Clean up temp file if exists
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    self.temp_files.discard(str(temp_file))
                except:
                    pass
    
    async def _download_with_requests_validated(self, url: str, output_file: Path, headers: dict, correlation_id: str) -> bool:
        """Fallback download using requests library with validation"""
        import requests
        
        temp_file = None
        
        try:
            # Use temporary file during download
            temp_file = output_file.with_suffix('.tmp')
            self.temp_files.add(str(temp_file))
            
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
                    logger.error(f"[{correlation_id}] Download failed: HTTP 403")
                    return False
                elif response.status_code not in [200, 206]:
                    logger.error(f"[{correlation_id}] Download failed: HTTP {response.status_code}")
                    return False
                
                # Check content type
                content_type = response.headers.get('Content-Type', '').lower()
                if 'text/html' in content_type:
                    logger.error(f"[{correlation_id}] Received HTML instead of audio")
                    return False
                
                total_size = int(response.headers.get('Content-Length', 0))
                if total_size > 0:
                    logger.info(f"[{correlation_id}] 📦 Download size: {total_size / 1024 / 1024:.1f} MB")
                
                with open(temp_file, 'wb') as f:
                    downloaded = 0
                    last_progress = 0
                    first_chunk_validated = False
                    
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Validate first chunk
                            if not first_chunk_validated and downloaded >= 16:
                                f.flush()
                                # Run async validation in sync context
                                if not self._validate_first_chunk_sync(temp_file, correlation_id):
                                    logger.error(f"[{correlation_id}] First chunk validation failed")
                                    return False
                                first_chunk_validated = True
                            
                            if total_size > 0:
                                progress = int((downloaded / total_size) * 100)
                                if progress >= last_progress + 10:
                                    logger.info(f"[{correlation_id}]    Progress: {progress}%")
                                    last_progress = progress
                
                # Final validation
                if downloaded < 100 * 1024:  # Less than 100KB
                    logger.error(f"[{correlation_id}] Downloaded file too small: {downloaded} bytes")
                    return False
                
                # Move to final location
                shutil.move(str(temp_file), str(output_file))
                
                logger.info(f"[{correlation_id}] ✅ Download complete: {output_file.name}")
                return True
            
            result = await loop.run_in_executor(None, download)
            if result:
                self.temp_files.discard(str(temp_file))
            return result
            
        except Exception as e:
            logger.debug(f"[{correlation_id}] requests download error: {e}")
            return False
        finally:
            # Clean up temp file if exists
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    self.temp_files.discard(str(temp_file))
                except:
                    pass
    
    async def _validate_first_chunk(self, file_path: Path, correlation_id: str) -> bool:
        """Validate the first chunk of downloaded file"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)
                
                # Check for HTML
                if header.lower().startswith(b'<!doctype') or header.lower().startswith(b'<html'):
                    logger.error(f"[{correlation_id}] File starts with HTML")
                    return False
                
                # Check for audio signatures
                audio_signatures = [
                    b'ID3', b'\xFF\xFB', b'\xFF\xF3', b'\xFF\xF2',
                    b'OggS', b'RIFF', b'fLaC'
                ]
                
                # Check at offset 4 for MP4
                if len(header) >= 8 and header[4:8] == b'ftyp':
                    return True
                
                # Check standard signatures
                for sig in audio_signatures:
                    if header.startswith(sig):
                        return True
                
                logger.warning(f"[{correlation_id}] No audio signature found in first chunk")
                return False
                
        except Exception as e:
            logger.error(f"[{correlation_id}] First chunk validation error: {e}")
            return False
    
    def _validate_first_chunk_sync(self, file_path: Path, correlation_id: str) -> bool:
        """Synchronous version of first chunk validation"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)
                
                if header.lower().startswith(b'<!doctype') or header.lower().startswith(b'<html'):
                    return False
                
                audio_signatures = [
                    b'ID3', b'\xFF\xFB', b'\xFF\xF3', b'\xFF\xF2',
                    b'OggS', b'RIFF', b'fLaC'
                ]
                
                if len(header) >= 8 and header[4:8] == b'ftyp':
                    return True
                
                for sig in audio_signatures:
                    if header.startswith(sig):
                        return True
                
                return False
                
        except:
            return False
    
    async def _validate_download_complete(self, file_path: Path, downloaded: int, expected_size: int, correlation_id: str) -> bool:
        """Validate completed download"""
        actual_size = file_path.stat().st_size
        
        # Check size
        if actual_size != downloaded:
            logger.error(f"[{correlation_id}] Size mismatch: expected {downloaded}, got {actual_size}")
            return False
        
        if expected_size > 0 and abs(actual_size - expected_size) > 1024:  # Allow 1KB difference
            logger.warning(f"[{correlation_id}] Size differs from Content-Length: {actual_size} vs {expected_size}")
            # Don't fail, some servers report wrong Content-Length
        
        # Minimum size check
        if actual_size < 100 * 1024:  # 100KB minimum
            logger.error(f"[{correlation_id}] File too small: {actual_size} bytes")
            return False
        
        return True
    
    async def _download_substack_audio(self, url: str, output_file: Path, episode: Episode, correlation_id: str) -> bool:
        """Special handling for Substack audio downloads"""
        logger.info(f"[{correlation_id}] 🔧 Using Substack-specific download method...")
        
        # Extract the actual MP3 URL from Substack's redirect URL
        parsed = urlparse(url)
        
        # Try to get the direct MP3 URL
        try:
            # Method 1: Check if it's already a direct MP3 URL
            if url.endswith('.mp3') or 'audio' in url:
                return await self._download_direct_url(url, output_file, correlation_id)
            
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
                        logger.debug(f"[{correlation_id}] Trying direct Substack URL: {direct_url}")
                        if await self._download_direct_url(direct_url, output_file, correlation_id):
                            return True
            
            # Method 3: Use episode link to find audio URL
            if hasattr(episode, 'link') and episode.link:
                audio_url = await self._find_substack_audio_url(episode.link, correlation_id)
                if audio_url:
                    return await self._download_direct_url(audio_url, output_file, correlation_id)
            
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
            
            return await self._download_with_aiohttp_validated(url, output_file, headers, correlation_id)
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Substack download error: {e}")
            return False
    
    async def _find_substack_audio_url(self, episode_url: str, correlation_id: str) -> Optional[str]:
        """Find audio URL from Substack episode page"""
        try:
            session = await self._get_session()
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
                            logger.info(f"[{correlation_id}] Found audio URL in page: {audio_url}")
                            return audio_url
        except Exception as e:
            logger.debug(f"[{correlation_id}] Failed to find audio URL in page: {e}")
        
        return None
    
    async def _download_direct_url(self, url: str, output_file: Path, correlation_id: str) -> bool:
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
            if await self._download_with_aiohttp_validated(url, output_file, headers, correlation_id):
                return True
            
            # Small delay between attempts
            await asyncio.sleep(1)
            
            if await self._download_with_requests_validated(url, output_file, headers, correlation_id):
                return True
        
        return False
    
    async def _download_with_system_tool(self, url: str, output_file: Path, correlation_id: str) -> bool:
        """Last resort: use curl or wget with enhanced options"""
        temp_file = None
        
        try:
            # Use temporary file
            temp_file = output_file.with_suffix('.tmp')
            self.temp_files.add(str(temp_file))
            
            # Try yt-dlp first (best for media downloads)
            if shutil.which('yt-dlp'):
                logger.info(f"[{correlation_id}] 🎯 Trying yt-dlp (most reliable for protected audio)...")
                cmd = [
                    'yt-dlp',
                    '--no-check-certificate',
                    '-f', 'bestaudio[ext=mp3]/bestaudio/best',
                    '--extract-audio',
                    '--audio-format', 'mp3',
                    '--audio-quality', '128K',
                    '--output', str(temp_file),
                    '--quiet',
                    '--no-warnings',
                    '--no-playlist',
                    '--add-header', 'User-Agent:Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
                    '--add-header', 'Accept:*/*',
                    '--add-header', 'Accept-Language:en-US,en;q=0.9',
                ]
                
                # Add browser cookie extraction if enabled
                if should_use_feature('enable_browser_cookie_extraction'):
                    cmd.extend(['--cookies-from-browser', 'chrome'])
                    logger.debug(f"[{correlation_id}] Using browser cookies for yt-dlp")
                
                cmd.append(url)
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and temp_file.exists():
                    # yt-dlp might create file with different extension
                    # Look for any audio file with the base name
                    base_name = temp_file.stem
                    parent_dir = temp_file.parent
                    
                    for ext in ['.mp3', '.m4a', '.opus', '.ogg', '.wav']:
                        possible_file = parent_dir / f"{base_name}{ext}"
                        if possible_file.exists():
                            shutil.move(str(possible_file), str(output_file))
                            logger.info(f"[{correlation_id}] ✅ Downloaded with yt-dlp")
                            self.temp_files.discard(str(temp_file))
                            return True
                else:
                    logger.debug(f"[{correlation_id}] yt-dlp failed: {stderr.decode()}")
            else:
                logger.warning(f"[{correlation_id}] ⚠️ yt-dlp not found - install with: pip install yt-dlp")
            
            # Try curl with podcast app headers
            cmd = [
                'curl', '-L', '-f', '-s', '-S',
                '--compressed',
                '--max-time', '300',
                '--retry', '3',
                '--retry-delay', '5',
                '-H', 'User-Agent: Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
                '-H', 'Accept: */*',
                '-H', 'Accept-Language: en-US,en;q=0.9',
                '-H', 'Accept-Encoding: br, gzip, deflate',
                '-H', 'Connection: keep-alive',
                '-H', 'X-Apple-Store-Front: 143441-1,32',
                '-H', 'Cache-Control: no-cache',
                '--connect-timeout', '30',
                '--max-time', '600',  # 10 minutes
                '--retry', '5',
                '--retry-delay', '5',
                '--retry-max-time', '120',
                '-k',  # Allow insecure connections
                '-o', str(temp_file),
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
            
            if process.returncode == 0 and temp_file.exists() and temp_file.stat().st_size > 100 * 1024:
                shutil.move(str(temp_file), str(output_file))
                logger.info(f"[{correlation_id}] ✅ Downloaded with curl")
                self.temp_files.discard(str(temp_file))
                return True
            else:
                logger.debug(f"[{correlation_id}] curl failed: {stderr.decode()}")
                
                # Try wget as last resort
                if temp_file.exists():
                    temp_file.unlink()
                
                cmd = [
                    'wget', '-q', '-O', str(temp_file),
                    '--user-agent=Mozilla/5.0',
                    '--header=Accept: audio/*',
                    '--header=Accept-Language: en-US,en;q=0.9',
                    '--timeout=30',
                    '--tries=5',
                    '--retry-connrefused',
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
                
                if process.returncode == 0 and temp_file.exists() and temp_file.stat().st_size > 100 * 1024:
                    shutil.move(str(temp_file), str(output_file))
                    logger.info(f"[{correlation_id}] ✅ Downloaded with wget")
                    self.temp_files.discard(str(temp_file))
                    return True
                else:
                    logger.debug(f"[{correlation_id}] wget failed: {stderr.decode()}")
                    
        except Exception as e:
            logger.debug(f"[{correlation_id}] System tool download error: {e}")
        finally:
            # Clean up temp file
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    self.temp_files.discard(str(temp_file))
                except:
                    pass
        
        return False
    
    async def _validate_with_ffprobe(self, audio_file: Path, correlation_id: str) -> bool:
        """Use ffprobe to validate audio file and get metadata"""
        try:
            import shutil
            if not shutil.which('ffprobe'):
                logger.debug(f"[{correlation_id}] ffprobe not available")
                return True  # Don't fail if ffprobe not available
            
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 
                   'format=format_name,duration,bit_rate', '-of', 'json', str(audio_file)]
            
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
                    format_info = probe_data['format']
                    logger.info(
                        f"[{correlation_id}] ✅ Valid audio - "
                        f"Format: {format_info.get('format_name')} | "
                        f"Duration: {float(format_info.get('duration', 0))/60:.1f}m | "
                        f"Bitrate: {int(format_info.get('bit_rate', 0))/1000:.0f}kbps"
                    )
                    return True
            
            logger.error(f"[{correlation_id}] ffprobe validation failed: {stderr.decode()}")
            return False
            
        except Exception as e:
            logger.debug(f"[{correlation_id}] ffprobe error: {e}")
            return True  # Don't fail on ffprobe errors
    
    async def _transcribe_with_whisper(self, audio_file: Path, correlation_id: str) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper API with enhanced error handling and rate limiting"""
        logger.info(f"[{correlation_id}] 🎤 Starting transcription with Whisper...")
        
        # Track files for cleanup
        files_to_clean = []
        
        try:
            # Handle test mode truncation (only if audio is not already trimmed)
            # Only trim if explicitly in test mode, regardless of global TESTING_MODE
            if self._current_mode == 'test':
                # First check if the audio is already short enough (might be pre-trimmed by download manager)
                try:
                    from pydub import AudioSegment
                    temp_audio = AudioSegment.from_file(str(audio_file))
                    current_duration_seconds = len(temp_audio) / 1000
                    max_duration_seconds = MAX_TRANSCRIPTION_MINUTES * 60
                    
                    if current_duration_seconds > max_duration_seconds:
                        logger.info(f"[{correlation_id}] 🧪 TEST MODE: Audio {current_duration_seconds:.1f}s > {max_duration_seconds}s, limiting to {MAX_TRANSCRIPTION_MINUTES} minutes")
                        trimmed_file = await self._trim_audio(audio_file, MAX_TRANSCRIPTION_MINUTES * 60, correlation_id)
                        if trimmed_file:
                            audio_file = trimmed_file
                            files_to_clean.append(trimmed_file)
                    else:
                        logger.info(f"[{correlation_id}] 🧪 TEST MODE: Audio already short enough ({current_duration_seconds:.1f}s), no trimming needed")
                    
                    # Clean up temp audio
                    del temp_audio
                    import gc
                    gc.collect()
                    
                except Exception as e:
                    logger.warning(f"[{correlation_id}] Failed to check audio duration, proceeding with trim: {e}")
                    # Fall back to the original behavior
                    logger.info(f"[{correlation_id}] 🧪 TEST MODE: Limiting to {MAX_TRANSCRIPTION_MINUTES} minutes")
                    trimmed_file = await self._trim_audio(audio_file, MAX_TRANSCRIPTION_MINUTES * 60, correlation_id)
                    if trimmed_file:
                        audio_file = trimmed_file
                        files_to_clean.append(trimmed_file)
            
            # Check if we need to use chunking for large files
            file_size = audio_file.stat().st_size
            if file_size > 25 * 1024 * 1024 and self._current_mode == 'full':
                # For full episodes, use chunking instead of compression
                logger.info(f"[{correlation_id}] 📚 File too large ({file_size / 1024 / 1024:.1f} MB), using chunked transcription...")
                return await self._transcribe_with_chunks(audio_file, correlation_id)
            elif file_size > 25 * 1024 * 1024:
                # In test mode, compress as before
                logger.warning(f"[{correlation_id}] File too large ({file_size / 1024 / 1024:.1f} MB), compressing...")
                compressed_file = await self._compress_audio(audio_file, correlation_id)
                if compressed_file:
                    audio_file = compressed_file
                    files_to_clean.append(compressed_file)
                else:
                    logger.error(f"[{correlation_id}] Failed to compress audio file")
                    return None
            
            # Check for dry-run mode
            if os.getenv('DRY_RUN') == 'true':
                logger.info(f"[{correlation_id}] 🧪 DRY RUN: Skipping OpenAI transcription API call")
                return "This is a dry-run transcript. In normal operation, this would contain the actual transcript from the audio file."
            
            # Wait for rate limiter before making API call
            wait_time = await whisper_rate_limiter.acquire(correlation_id)
            if wait_time > 0:
                logger.info(f"[{correlation_id}] Whisper rate limiting: waiting {wait_time:.1f}s before API call")
                await asyncio.sleep(wait_time)
            
            # Log current rate limiter usage
            usage = whisper_rate_limiter.get_current_usage()
            logger.info(f"[{correlation_id}] Whisper API rate limit usage: {usage['current_requests']}/{usage['max_requests']} ({usage['utilization']:.1f}%)")
            
            # Define the transcription function for retry and circuit breaker
            async def transcribe():
                with open(audio_file, 'rb') as f:
                    # Run in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    
                    def api_call():
                        try:
                            return openai_client.audio.transcriptions.create(
                                model="whisper-1",
                                file=f,
                                response_format="text",
                                language="en"  # Assuming English, adjust if needed
                            )
                        except Exception as e:
                            # Wrap the exception to preserve response information
                            if hasattr(e, 'response'):
                                raise e
                            else:
                                # Create a wrapper exception that includes the error message
                                class APIError(Exception):
                                    def __init__(self, message):
                                        super().__init__(message)
                                        self.response = None
                                
                                raise APIError(str(e))
                    
                    return await loop.run_in_executor(None, api_call)
            
            # Try transcription with circuit breaker and enhanced retry logic
            try:
                async def circuit_breaker_call():
                    return await retry_with_backoff(
                        transcribe,
                        max_attempts=5,  # Increased for rate limits
                        base_delay=2.0,
                        max_delay=300.0,  # 5 minutes max
                        exceptions=(Exception,),
                        correlation_id=correlation_id,
                        handle_rate_limit=True  # Enable special rate limit handling
                    )
                
                transcript = await self.openai_circuit_breaker.call(circuit_breaker_call)
                
                if transcript and len(transcript.strip()) > 100:
                    logger.info(f"[{correlation_id}] ✅ Transcription complete: {len(transcript)} characters")
                    return transcript.strip()
                else:
                    logger.error(f"[{correlation_id}] Transcription returned empty or too short result")
                    return None
                    
            except Exception as e:
                error_msg = str(e)
                
                # Handle specific Whisper errors
                if "format is not supported" in error_msg:
                    logger.warning(f"[{correlation_id}] Audio format not supported, converting...")
                    converted_file = await self._convert_audio_format(audio_file, correlation_id)
                    if converted_file:
                        files_to_clean.append(converted_file)
                        # Retry with converted file
                        audio_file = converted_file
                        return await self._transcribe_with_whisper(audio_file, correlation_id)
                
                elif "file size" in error_msg.lower():
                    logger.error(f"[{correlation_id}] File size issue after compression")
                
                elif "invalid" in error_msg.lower():
                    logger.error(f"[{correlation_id}] Invalid audio file")
                
                elif "circuit breaker is open" in error_msg.lower():
                    logger.error(f"[{correlation_id}] Circuit breaker is open - too many failures")
                
                logger.error(f"[{correlation_id}] Whisper API error: {error_msg}")
                raise
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Transcription failed: {e}", exc_info=True)
            return None
            
        finally:
            # Clean up temporary files
            for file_path in files_to_clean:
                try:
                    if file_path.exists():
                        file_path.unlink()
                        logger.debug(f"[{correlation_id}] Cleaned up: {file_path.name}")
                        self.temp_files.discard(str(file_path))
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Failed to clean up {file_path}: {e}")
    
    async def _trim_audio(self, audio_file: Path, max_seconds: int, correlation_id: str) -> Optional[Path]:
        """Trim audio file to specified duration"""
        try:
            logger.info(f"[{correlation_id}] ✂️ Trimming audio to {max_seconds} seconds...")
            
            # Create output file with shorter name to avoid "File name too long" errors
            temp_filename = generate_temp_filename(f"trim_{correlation_id}_{audio_file.name}")
            trimmed_file = TEMP_DIR / temp_filename
            self.temp_files.add(str(trimmed_file))
            
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
                    logger.info(f"[{correlation_id}] ✅ Audio trimmed successfully with ffmpeg")
                    return trimmed_file
                else:
                    logger.error(f"[{correlation_id}] ffmpeg trim failed (code {process.returncode}): {stderr.decode()}")
                    logger.info(f"[{correlation_id}] Attempting pydub fallback...")
            else:
                logger.warning(f"[{correlation_id}] ffmpeg not found, using pydub fallback")
            
            # Fallback: use pydub (with size check to prevent OOM)
            return await self._trim_with_pydub(audio_file, max_seconds, correlation_id)
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Audio trim error: {e}")
            # If trimming fails, return original file
            return audio_file
    
    async def _trim_with_pydub(self, audio_file: Path, max_seconds: int, correlation_id: str) -> Optional[Path]:
        """Fallback: trim audio using pydub"""
        try:
            # Check file size first to avoid OOM
            file_size_mb = audio_file.stat().st_size / (1024 * 1024)
            if file_size_mb > 100:  # 100MB threshold
                logger.warning(f"[{correlation_id}] File too large for pydub ({file_size_mb:.1f}MB), skipping pydub trim")
                # Return original file rather than risk OOM
                return audio_file
            
            from pydub import AudioSegment
            
            logger.info(f"[{correlation_id}] Using pydub for trimming ({file_size_mb:.1f}MB file)...")
            
            # Load audio - this is where OOM can happen with large files
            audio = AudioSegment.from_file(str(audio_file))
            
            # Trim to max duration
            trimmed = audio[:max_seconds * 1000]  # pydub uses milliseconds
            
            # Export - use shorter filename to avoid "File name too long" errors
            temp_filename = generate_temp_filename(f"trim_pydub_{correlation_id}")
            trimmed_file = TEMP_DIR / temp_filename
            self.temp_files.add(str(trimmed_file))
            trimmed.export(str(trimmed_file), format="mp3")
            
            # Clean up the large audio object
            del audio
            del trimmed
            gc.collect()  # Force garbage collection after pydub operations
            
            logger.info(f"[{correlation_id}] ✅ Audio trimmed successfully with pydub")
            return trimmed_file
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Pydub trim error: {e}")
            # If trimming fails, return original file
            return audio_file
    
    async def _compress_audio(self, audio_file: Path, correlation_id: str) -> Optional[Path]:
        """Compress audio file to reduce size"""
        try:
            compressed_file = TEMP_DIR / f"compressed_{audio_file.name}"
            self.temp_files.add(str(compressed_file))
            
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
                    logger.info(f"[{correlation_id}] ✅ Compressed to {new_size / 1024 / 1024:.1f} MB")
                    return compressed_file
            else:
                # Try pydub compression
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(audio_file))
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(str(compressed_file), format="mp3", bitrate="64k")
                logger.info(f"[{correlation_id}] ✅ Compressed with pydub")
                return compressed_file
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Compression error: {e}")
        
        return None
    
    async def _convert_audio_format(self, audio_file: Path, correlation_id: str) -> Optional[Path]:
        """Convert audio to a format Whisper can handle"""
        try:
            logger.info(f"[{correlation_id}] 🔄 Converting audio format...")
            
            temp_filename = generate_temp_filename(f"convert_{audio_file.stem}")
            converted_file = TEMP_DIR / temp_filename
            self.temp_files.add(str(converted_file))
            
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
                    logger.info(f"[{correlation_id}] ✅ Audio converted successfully")
                    return converted_file
                else:
                    logger.error(f"[{correlation_id}] ffmpeg conversion failed: {stderr.decode()}")
            else:
                # Try pydub conversion
                from pydub import AudioSegment
                audio = AudioSegment.from_file(str(audio_file))
                audio.export(str(converted_file), format="mp3", bitrate="128k")
                logger.info(f"[{correlation_id}] ✅ Audio converted with pydub")
                return converted_file
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Audio conversion error: {e}")
        
        return None
    
    async def _transcribe_with_chunks(self, audio_file: Path, correlation_id: str) -> Optional[str]:
        """Transcribe large audio files by splitting into chunks under 25MB"""
        try:
            logger.info(f"[{correlation_id}] 🔪 Starting chunked transcription...")
            
            # Calculate chunk duration based on file size and bitrate
            file_size_mb = audio_file.stat().st_size / (1024 * 1024)
            
            # Get audio duration using ffprobe
            duration_seconds = await self._get_audio_duration(audio_file, correlation_id)
            if not duration_seconds:
                logger.error(f"[{correlation_id}] Failed to get audio duration")
                return None
            
            # Calculate optimal chunk size (aim for ~20MB chunks with some buffer)
            target_chunk_mb = 20
            num_chunks = max(2, int(file_size_mb / target_chunk_mb) + 1)
            chunk_duration = duration_seconds / num_chunks
            
            logger.info(f"[{correlation_id}] Splitting {duration_seconds/60:.1f} min audio into {num_chunks} chunks of ~{chunk_duration/60:.1f} min each")
            
            # Split audio into chunks
            chunks = []
            for i in range(num_chunks):
                start_time = i * chunk_duration
                chunk_file = await self._extract_audio_chunk(audio_file, start_time, chunk_duration, i, correlation_id)
                if chunk_file:
                    chunks.append(chunk_file)
                else:
                    logger.error(f"[{correlation_id}] Failed to create chunk {i+1}/{num_chunks}")
            
            if not chunks:
                logger.error(f"[{correlation_id}] No chunks created successfully")
                return None
            
            # Transcribe each chunk
            transcripts = []
            for i, chunk_file in enumerate(chunks):
                try:
                    logger.info(f"[{correlation_id}] 📝 Transcribing chunk {i+1}/{len(chunks)}...")
                    
                    # Use the regular transcription method for each chunk
                    transcript = await self._transcribe_single_file(chunk_file, correlation_id)
                    
                    if transcript:
                        transcripts.append(transcript)
                        logger.info(f"[{correlation_id}] ✅ Chunk {i+1} transcribed: {len(transcript)} characters")
                    else:
                        logger.error(f"[{correlation_id}] ❌ Failed to transcribe chunk {i+1}")
                    
                finally:
                    # Clean up chunk file immediately after transcription
                    try:
                        chunk_file.unlink()
                        self.temp_files.discard(str(chunk_file))
                    except Exception as e:
                        logger.debug(f"[{correlation_id}] Error cleaning up chunk: {e}")
            
            # Combine all transcripts
            if transcripts:
                full_transcript = " ".join(transcripts)
                logger.info(f"[{correlation_id}] ✅ Combined {len(transcripts)} chunks into {len(full_transcript)} characters")
                return full_transcript
            else:
                logger.error(f"[{correlation_id}] No chunks were successfully transcribed")
                return None
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Chunked transcription error: {e}", exc_info=True)
            return None
    
    async def _get_audio_duration(self, audio_file: Path, correlation_id: str) -> Optional[float]:
        """Get audio duration in seconds using ffprobe"""
        try:
            import shutil
            if not shutil.which('ffprobe'):
                # Fallback: estimate based on file size (assume 128kbps)
                file_size_bits = audio_file.stat().st_size * 8
                estimated_seconds = file_size_bits / (128 * 1000)
                logger.warning(f"[{correlation_id}] ffprobe not available, estimating duration: {estimated_seconds/60:.1f} min")
                return estimated_seconds
            
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                   '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_file)]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                duration = float(stdout.decode().strip())
                return duration
            else:
                logger.error(f"[{correlation_id}] ffprobe error: {stderr.decode()}")
                return None
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Duration detection error: {e}")
            return None
    
    async def _extract_audio_chunk(self, audio_file: Path, start_time: float, duration: float, chunk_index: int, correlation_id: str) -> Optional[Path]:
        """Extract a chunk of audio using ffmpeg"""
        try:
            temp_filename = generate_temp_filename(f"chunk_{chunk_index}_{audio_file.stem}")
            chunk_file = TEMP_DIR / temp_filename
            self.temp_files.add(str(chunk_file))
            
            import shutil
            if shutil.which('ffmpeg'):
                cmd = [
                    'ffmpeg', '-i', str(audio_file),
                    '-ss', str(start_time),
                    '-t', str(duration),
                    '-acodec', 'libmp3lame',
                    '-b:a', '128k',  # Consistent bitrate for predictable file sizes
                    '-y',
                    str(chunk_file)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0 and chunk_file.exists():
                    chunk_size_mb = chunk_file.stat().st_size / (1024 * 1024)
                    logger.info(f"[{correlation_id}] ✅ Created chunk {chunk_index+1}: {chunk_size_mb:.1f} MB")
                    return chunk_file
                else:
                    logger.error(f"[{correlation_id}] ffmpeg chunk extraction failed: {stderr.decode()}")
            else:
                # Fallback to pydub
                from pydub import AudioSegment
                logger.info(f"[{correlation_id}] Using pydub for chunk extraction...")
                
                audio = AudioSegment.from_file(str(audio_file))
                start_ms = int(start_time * 1000)
                end_ms = int((start_time + duration) * 1000)
                chunk = audio[start_ms:end_ms]
                
                chunk.export(str(chunk_file), format="mp3", bitrate="128k")
                chunk_size_mb = chunk_file.stat().st_size / (1024 * 1024)
                logger.info(f"[{correlation_id}] ✅ Created chunk {chunk_index+1} with pydub: {chunk_size_mb:.1f} MB")
                return chunk_file
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Chunk extraction error: {e}")
            return None
    
    async def _transcribe_single_file(self, audio_file: Path, correlation_id: str) -> Optional[str]:
        """Transcribe a single audio file (used for chunks)"""
        try:
            # Check for dry-run mode
            if os.getenv('DRY_RUN') == 'true':
                return "Dry-run chunk transcript"
            
            # Wait for rate limiter
            wait_time = await whisper_rate_limiter.acquire(correlation_id)
            if wait_time > 0:
                logger.info(f"[{correlation_id}] Whisper rate limiting: waiting {wait_time:.1f}s before API call")
                await asyncio.sleep(wait_time)
            
            # Define the transcription function
            async def transcribe():
                with open(audio_file, 'rb') as f:
                    loop = asyncio.get_event_loop()
                    
                    def api_call():
                        try:
                            return openai_client.audio.transcriptions.create(
                                model="whisper-1",
                                file=f,
                                response_format="text",
                                language="en"
                            )
                        except Exception as e:
                            if hasattr(e, 'response'):
                                raise e
                            else:
                                class APIError(Exception):
                                    def __init__(self, message):
                                        super().__init__(message)
                                        self.response = None
                                raise APIError(str(e))
                    
                    return await loop.run_in_executor(None, api_call)
            
            # Try transcription with retry
            transcript = await retry_with_backoff(
                transcribe,
                max_attempts=5,
                base_delay=2.0,
                max_delay=300.0,
                exceptions=(Exception,),
                correlation_id=correlation_id,
                handle_rate_limit=True
            )
            
            return transcript
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Single file transcription error: {e}")
            return None