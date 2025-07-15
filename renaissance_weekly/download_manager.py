"""Download Manager for concurrent episode downloads with retry strategies"""

import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
import logging

from .models import Episode
from .transcripts.transcriber import AudioTranscriber
from .fetchers.audio_sources import AudioSourceFinder
from .fetchers.american_optimist_handler import AmericanOptimistHandler
from .fetchers.universal_youtube_handler import UniversalYouTubeHandler
from .download_strategies.smart_router import SmartDownloadRouter
from .utils.logging import get_logger
from .utils.helpers import exponential_backoff_with_jitter
from .utils.filename_utils import generate_audio_filename, generate_temp_filename
from .config import TEMP_DIR, MAX_TRANSCRIPTION_MINUTES

logger = get_logger(__name__)


class DownloadAttempt:
    """Track individual download attempt"""
    def __init__(self, url: str, strategy: str):
        self.url = url
        self.strategy = strategy
        self.start_time = time.time()
        self.end_time = None
        self.error = None
        self.success = False
    
    def complete(self, success: bool, error: Optional[str] = None):
        """Mark attempt as complete"""
        self.end_time = time.time()
        self.success = success
        self.error = error
        
    @property
    def duration(self) -> float:
        """Get duration in seconds"""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
        
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'url': self.url,
            'strategy': self.strategy,
            'timestamp': datetime.fromtimestamp(self.start_time).isoformat(),
            'duration': f"{self.duration:.1f}s",
            'success': self.success,
            'error': self.error
        }


class EpisodeDownloadStatus:
    """Track download status for a single episode"""
    def __init__(self, episode: Episode):
        self.episode = episode
        self.episode_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        self.status = 'pending'  # pending, downloading, retrying, success, failed
        self.attempts: List[DownloadAttempt] = []
        self.audio_path: Optional[Path] = None
        self.last_error: Optional[str] = None
        self.file_size: Optional[int] = None
        self.downloaded_duration: Optional[float] = None  # in minutes
        self.audio_format: Optional[str] = None
        self.download_source: Optional[str] = None
        
    def add_attempt(self, attempt: DownloadAttempt):
        """Add a download attempt"""
        self.attempts.append(attempt)
        
    def extract_audio_info(self):
        """Extract audio file information after successful download"""
        if not self.audio_path or not self.audio_path.exists():
            return
            
        try:
            # Get file size
            self.file_size = self.audio_path.stat().st_size
            
            # Get audio format from file extension
            self.audio_format = self.audio_path.suffix.lower().lstrip('.')
            
            # Extract duration using mutagen (memory efficient - doesn't load entire file)
            try:
                from mutagen import File
                audio_file = File(str(self.audio_path))
                if audio_file and audio_file.info:
                    self.downloaded_duration = audio_file.info.length / 60  # Convert seconds to minutes
                else:
                    # Fallback: Try ffprobe if mutagen fails
                    import subprocess
                    import json
                    cmd = [
                        'ffprobe', '-v', 'quiet', '-print_format', 'json',
                        '-show_streams', str(self.audio_path)
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                        for stream in data.get('streams', []):
                            if stream.get('codec_type') == 'audio' and 'duration' in stream:
                                self.downloaded_duration = float(stream['duration']) / 60
                                break
            except Exception as e:
                logger.debug(f"Could not extract duration from {self.audio_path}: {e}")
                
            # Set download source from last successful attempt
            if self.attempts:
                for attempt in reversed(self.attempts):
                    if attempt.success:
                        self.download_source = attempt.strategy
                        break
                        
        except Exception as e:
            logger.debug(f"Error extracting audio info from {self.audio_path}: {e}")
    
    def _parse_duration_string(self, duration_str: str) -> Optional[float]:
        """Parse duration string from episode metadata to minutes"""
        if not duration_str or duration_str.lower().strip() in ['unknown', 'none', '']:
            return None
            
        # Handle various duration formats
        # Examples: "1:30:45", "90:15", "45", "1h 30m", "90 minutes"
        duration_str = str(duration_str).strip().lower()
        
        # Try HH:MM:SS or MM:SS format
        if ':' in duration_str:
            parts = duration_str.split(':')
            try:
                if len(parts) == 3:  # HH:MM:SS
                    hours, minutes, seconds = map(int, parts)
                    return hours * 60 + minutes + seconds / 60
                elif len(parts) == 2:  # MM:SS
                    minutes, seconds = map(int, parts)
                    return minutes + seconds / 60
            except ValueError:
                pass
                
        # Try "Xh Ym" format
        if 'h' in duration_str and 'm' in duration_str:
            try:
                import re
                match = re.search(r'(\d+)h\s*(\d+)m', duration_str)
                if match:
                    hours, minutes = map(int, match.groups())
                    return hours * 60 + minutes
            except:
                pass
                
        # Try "X minutes" format
        if 'minute' in duration_str:
            try:
                import re
                match = re.search(r'(\d+)', duration_str)
                if match:
                    return int(match.group(1))
            except:
                pass
                
        # Try just a number (assume minutes)
        try:
            return float(duration_str)
        except ValueError:
            pass
            
        return None
        
    def to_dict(self) -> dict:
        """Convert to dictionary for UI display"""
        # Parse expected duration from episode metadata
        expected_duration = None
        raw_duration = getattr(self.episode, 'duration', None)
        if raw_duration:
            expected_duration = self._parse_duration_string(raw_duration)
            
        return {
            'episode': f"{self.episode.podcast}: {self.episode.title}",
            'title': self.episode.title,
            'status': self.status,
            'attemptCount': len(self.attempts),
            'attempts': [att.to_dict() for att in self.attempts],
            'lastError': self.last_error,
            'currentStrategy': self.attempts[-1].strategy if self.attempts else None,
            'history': [att.to_dict() for att in self.attempts],
            # New file information
            'fileSize': self.file_size,
            'downloadedDuration': self.downloaded_duration,
            'audioFormat': self.audio_format,
            'downloadSource': self.download_source,
            'expectedDuration': expected_duration,
            'metadata': {
                'duration': raw_duration,  # Use raw_duration instead of getattr
                'originalDuration': raw_duration,  # Add extra field for debugging
                'parsedDuration': expected_duration  # Add parsed version for debugging
            }
        }


class DownloadManager:
    """Manage concurrent episode downloads with retry strategies"""
    
    def __init__(self, concurrency: int = 10, progress_callback: Optional[Callable] = None, transcription_mode: str = 'test'):
        self.concurrency = concurrency
        self.progress_callback = progress_callback
        self.transcriber = AudioTranscriber()
        self.audio_finder = AudioSourceFinder()
        self.download_status: Dict[str, EpisodeDownloadStatus] = {}
        self._download_semaphore = asyncio.Semaphore(concurrency)
        # Add separate semaphore for YouTube downloads to limit memory usage
        self._youtube_semaphore = asyncio.Semaphore(2)  # Max 2 concurrent YouTube downloads
        self._manual_url_queue: Dict[str, str] = {}
        self._browser_download_queue: List[str] = []
        self._cancelled = False
        self.transcription_mode = transcription_mode  # Set mode from constructor
        
        # Set transcriber mode to match
        self.transcriber._current_mode = self.transcription_mode
        logger.info(f"DownloadManager initialized with mode: {self.transcription_mode}")
        
        # Initialize smart router for bulletproof downloads
        self.smart_router = SmartDownloadRouter()
        
        # Download statistics
        self.stats = {
            'total': 0,
            'downloaded': 0,
            'retrying': 0,
            'failed': 0,
            'startTime': None
        }
    
    def set_transcription_mode(self, mode: str):
        """Set transcription mode and sync with transcriber"""
        self.transcription_mode = mode
        self.transcriber._current_mode = mode
        logger.info(f"Set transcription mode to: {mode}")
        
    def add_manual_url(self, episode_id: str, url: str):
        """Add manual URL for an episode and retry download"""
        self._manual_url_queue[episode_id] = url
        logger.info(f"Added manual URL for {episode_id}: {url}")
        
        # If episode exists and is failed, trigger immediate retry
        if episode_id in self.download_status:
            status = self.download_status[episode_id]
            if status.status == 'failed':
                # Mark as retrying
                status.status = 'retrying'
                self.stats['retrying'] = self.stats.get('retrying', 0) + 1
                self.stats['failed'] = max(0, self.stats.get('failed', 0) - 1)
                self._report_progress()
                
                # Create task to retry download with manual URL
                # Use run_coroutine_threadsafe for cross-thread scheduling
                try:
                    # Try to get the running loop
                    loop = asyncio.get_running_loop()
                    # We're already in the loop, create task directly
                    asyncio.create_task(self._retry_with_manual_url(episode_id, url))
                except RuntimeError:
                    # Not in async context, check if we have a stored loop reference
                    if hasattr(self, '_event_loop') and self._event_loop:
                        # Schedule in the download loop using threadsafe method
                        asyncio.run_coroutine_threadsafe(
                            self._retry_with_manual_url(episode_id, url),
                            self._event_loop
                        )
                    else:
                        logger.error(f"Cannot retry {episode_id} - no event loop available")
        
    def request_browser_download(self, episode_id: str):
        """Request browser-based download for an episode"""
        self._browser_download_queue.append(episode_id)
        logger.info(f"Requested browser download for {episode_id}")
        
    def cancel(self):
        """Cancel all downloads"""
        self._cancelled = True
        logger.info("Download manager cancelled")
    
    def _check_memory(self) -> tuple[bool, str]:
        """Check available memory before starting downloads"""
        try:
            import psutil
            
            # Get memory info
            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024**3)
            total_gb = memory.total / (1024**3)
            percent_used = memory.percent
            
            logger.info(f"💾 Memory status: {available_gb:.1f}GB available of {total_gb:.1f}GB total ({percent_used:.1f}% used)")
            
            # Warn if less than 1GB available
            if available_gb < 1.0:
                return False, f"Low memory: only {available_gb:.1f}GB available"
            
            # Warn if over 85% memory usage
            if percent_used > 85:
                return False, f"High memory usage: {percent_used:.1f}%"
            
            return True, "Memory OK"
            
        except ImportError:
            logger.warning("psutil not available for memory monitoring")
            return True, "psutil not available"
        except Exception as e:
            logger.warning(f"Memory check failed: {e}")
            return True, "Memory check failed"
    
    async def _monitor_memory_usage(self):
        """Monitor memory usage during downloads and log warnings"""
        try:
            import psutil
            
            warning_threshold = 80  # Warn at 80% memory usage
            critical_threshold = 90  # Critical at 90% memory usage
            last_warning_percent = 0
            
            while True:
                try:
                    memory = psutil.virtual_memory()
                    percent_used = memory.percent
                    available_gb = memory.available / (1024**3)
                    
                    # Log critical memory usage
                    if percent_used > critical_threshold and percent_used > last_warning_percent + 5:
                        logger.error(f"🚨 CRITICAL MEMORY: {percent_used:.1f}% used, only {available_gb:.1f}GB available!")
                        last_warning_percent = percent_used
                    # Log high memory usage
                    elif percent_used > warning_threshold and percent_used > last_warning_percent + 5:
                        logger.warning(f"⚠️ HIGH MEMORY: {percent_used:.1f}% used, {available_gb:.1f}GB available")
                        last_warning_percent = percent_used
                    
                    # Check every 10 seconds
                    await asyncio.sleep(10)
                    
                except Exception as e:
                    logger.debug(f"Memory monitoring error: {e}")
                    await asyncio.sleep(10)
                    
        except asyncio.CancelledError:
            logger.debug("Memory monitoring stopped")
            raise
        except ImportError:
            logger.debug("psutil not available for memory monitoring")
            return
        
    async def download_episodes(self, episodes: List[Episode], podcast_configs: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
        """Download multiple episodes concurrently"""
        self.stats['total'] = len(episodes)
        self.stats['startTime'] = time.time()
        
        # Memory check before starting downloads
        memory_ok, memory_msg = self._check_memory()
        if not memory_ok:
            logger.error(f"⚠️ Memory check failed: {memory_msg}")
            # Continue anyway but with reduced concurrency
            if self.concurrency > 2:
                logger.warning(f"Reducing concurrency from {self.concurrency} to 2 due to low memory")
                self._download_semaphore = asyncio.Semaphore(2)
                self.concurrency = 2
            # Also reduce YouTube concurrency
            if hasattr(self, '_youtube_semaphore'):
                self._youtube_semaphore = asyncio.Semaphore(1)
                logger.warning("Reduced YouTube concurrency to 1 due to low memory")
        
        # Store the event loop for cross-thread operations
        self._event_loop = asyncio.get_running_loop()
        
        # Store podcast configs for audio finder
        if podcast_configs:
            self.podcast_configs = podcast_configs
        
        # Initialize status for each episode
        for episode in episodes:
            ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
            self.download_status[ep_id] = EpisodeDownloadStatus(episode)
        
        # Report initial progress to show all episodes in UI
        self._report_progress()
        
        # Use audio finder as context manager to ensure proper cleanup
        async with self.audio_finder:
            # Create download tasks
            tasks = [self._download_episode(episode) for episode in episodes]
            
            # Start memory monitoring task
            memory_monitor_task = asyncio.create_task(self._monitor_memory_usage())
            
            # Run downloads concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Cancel memory monitoring
            memory_monitor_task.cancel()
            try:
                await memory_monitor_task
            except asyncio.CancelledError:
                pass
        
        # Update final statistics
        for ep_id, status in self.download_status.items():
            if status.status == 'success':
                self.stats['downloaded'] += 1
            elif status.status == 'failed':
                self.stats['failed'] += 1
        
        # Send final progress report to UI
        self._report_progress()
                
        return self.get_status()
        
    async def _download_episode(self, episode: Episode) -> Optional[Path]:
        """Download single episode with retry strategies"""
        ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        status = self.download_status[ep_id]
        
        # Update status to show episode is now downloading
        status.status = 'downloading'
        self._report_progress()
        
        async with self._download_semaphore:
            if self._cancelled:
                return None
                
            # First check if file already exists
            from .config import AUDIO_DIR
            from .utils.helpers import calculate_file_hash, validate_audio_file_smart
            
            # Ensure audio directory exists
            AUDIO_DIR.mkdir(exist_ok=True)
            
            # Get current mode from parent app or use test as default
            current_mode = getattr(self, 'transcription_mode', 'test')
            
            # Generate standardized filename
            filename = generate_audio_filename(episode, current_mode)
            audio_file = AUDIO_DIR / filename
            
            # Check if already exists and is valid
            if audio_file.exists():
                correlation_id = f"download_{ep_id[:8]}"
                if validate_audio_file_smart(audio_file, correlation_id, episode.audio_url):
                    file_hash = calculate_file_hash(audio_file)
                    logger.info(f"✅ Using existing audio file for {episode.title}")
                    logger.info(f"   Path: {audio_file}")
                    logger.info(f"   Size: {audio_file.stat().st_size / 1024 / 1024:.1f} MB")
                    logger.info(f"   Hash: {file_hash[:8]}...")
                    
                    # Mark as successful immediately
                    status.status = 'success'
                    status.audio_path = audio_file
                    
                    # Extract audio file information
                    status.extract_audio_info()
                    
                    # Add a successful attempt record to show it was cached
                    cached_attempt = DownloadAttempt(str(audio_file), 'cached_file')
                    cached_attempt.complete(True, None)
                    status.add_attempt(cached_attempt)
                    
                    # Don't increment stats or report progress for cached files
                    # This will be done in the final statistics update
                    return audio_file
                else:
                    logger.warning(f"Existing file invalid for {episode.title}, re-downloading")
                    audio_file.unlink()
                
            # Update status
            status.status = 'downloading'
            self._report_progress()
            
            # Check for manual URL first
            if ep_id in self._manual_url_queue:
                url = self._manual_url_queue.pop(ep_id)
                logger.info(f"🔧 Using manual URL: {url[:80]}...")
                
                # For local files, just copy them
                if url.startswith('/') or url.startswith('~') or url.startswith('file://'):
                    try:
                        import shutil
                        from pathlib import Path
                        
                        source_path = Path(url.replace('file://', '')).expanduser()
                        if source_path.exists():
                            shutil.copy2(source_path, audio_file)
                            logger.info(f"✅ Copied local file: {source_path}")
                            
                            # Trim if in test mode
                            if current_mode == 'test':
                                logger.info(f"[{ep_id}] 🧪 TEST MODE: Trimming manual file to {MAX_TRANSCRIPTION_MINUTES} minutes")
                                trimmed_file = await self._trim_downloaded_audio(audio_file, ep_id)
                                if trimmed_file:
                                    logger.info(f"[{ep_id}] ✂️ Audio trimmed from {audio_file.stat().st_size / 1024 / 1024:.1f}MB to {trimmed_file.stat().st_size / 1024 / 1024:.1f}MB")
                                    # Replace the original file with the trimmed version
                                    audio_file.unlink()  # Remove original
                                    trimmed_file.rename(audio_file)  # Move trimmed to original location
                                else:
                                    logger.warning(f"[{ep_id}] Failed to trim audio, keeping full file")
                            
                            status.status = 'success'
                            status.audio_path = audio_file
                            
                            # Extract audio file information
                            status.extract_audio_info()
                            
                            self.stats['downloaded'] += 1
                            self._report_progress()
                            return audio_file
                    except Exception as e:
                        logger.error(f"Failed to copy local file: {e}")
                
                # For URLs, use smart router
                episode_info = {
                    'podcast': episode.podcast,
                    'title': episode.title,
                    'audio_url': url,
                    'published': episode.published
                }
                
                # Check if URL is YouTube for semaphore management
                is_youtube_url = "youtube.com" in url or "youtu.be" in url
                
                if is_youtube_url:
                    async with self._youtube_semaphore:
                        logger.info(f"🎥 Using YouTube semaphore for manual URL")
                        success = await self.smart_router.download_with_fallback(episode_info, audio_file)
                else:
                    success = await self.smart_router.download_with_fallback(episode_info, audio_file)
                if success:
                    # Trim if in test mode
                    if current_mode == 'test':
                        logger.info(f"[{ep_id}] 🧪 TEST MODE: Trimming manual download to {MAX_TRANSCRIPTION_MINUTES} minutes")
                        trimmed_file = await self._trim_downloaded_audio(audio_file, ep_id)
                        if trimmed_file:
                            logger.info(f"[{ep_id}] ✂️ Audio trimmed from {audio_file.stat().st_size / 1024 / 1024:.1f}MB to {trimmed_file.stat().st_size / 1024 / 1024:.1f}MB")
                            # Replace the original file with the trimmed version
                            audio_file.unlink()  # Remove original
                            import shutil
                            shutil.move(str(trimmed_file), str(audio_file))  # Move trimmed to original location
                        else:
                            logger.warning(f"[{ep_id}] Failed to trim audio, keeping full file")
                    
                    status.status = 'success'
                    status.audio_path = audio_file
                    
                    # Extract audio file information
                    status.extract_audio_info()
                    
                    self.stats['downloaded'] += 1
                    self._report_progress()
                    return audio_file
                    
            # Use smart router for all downloads (replaces all complex logic above)
            episode_info = {
                'podcast': episode.podcast,
                'title': episode.title,
                'audio_url': episode.audio_url,
                'published': episode.published
            }
            
            # Record download attempt start
            attempt = DownloadAttempt(episode.audio_url, 'smart_router')
            status.add_attempt(attempt)
            
            try:
                # Check if this will likely use YouTube (for memory management)
                is_youtube_likely = (
                    episode.podcast in ["American Optimist", "Dwarkesh Podcast"] or
                    "youtube.com" in episode.audio_url or
                    "youtu.be" in episode.audio_url
                )
                
                # Use YouTube semaphore if likely to use YouTube
                if is_youtube_likely:
                    async with self._youtube_semaphore:
                        logger.info(f"🎥 Using YouTube semaphore for {episode.podcast}")
                        success = await asyncio.wait_for(
                            self.smart_router.download_with_fallback(episode_info, audio_file),
                            timeout=1800  # 30 minutes total for all strategies
                        )
                else:
                    # Regular download without YouTube semaphore
                    success = await asyncio.wait_for(
                        self.smart_router.download_with_fallback(episode_info, audio_file),
                        timeout=1800  # 30 minutes total for all strategies (for very long episodes)
                    )
                
                if success:
                    # If we're in test mode, trim the audio file immediately after download
                    if current_mode == 'test':
                        logger.info(f"[{ep_id}] 🧪 TEST MODE: Trimming downloaded audio to {MAX_TRANSCRIPTION_MINUTES} minutes")
                        trimmed_file = await self._trim_downloaded_audio(audio_file, ep_id)
                        if trimmed_file:
                            logger.info(f"[{ep_id}] ✂️ Audio trimmed from {audio_file.stat().st_size / 1024 / 1024:.1f}MB to {trimmed_file.stat().st_size / 1024 / 1024:.1f}MB")
                            # Replace the original file with the trimmed version
                            audio_file.unlink()  # Remove original
                            import shutil
                            shutil.move(str(trimmed_file), str(audio_file))  # Move trimmed to original location
                        else:
                            logger.warning(f"[{ep_id}] Failed to trim audio, keeping full file")
                    
                    attempt.complete(True)
                    status.status = 'success'
                    status.audio_path = audio_file
                    
                    # Extract audio file information
                    status.extract_audio_info()
                    
                    self.stats['downloaded'] += 1
                    self._report_progress()
                    logger.info(f"✅ Smart router succeeded for {episode.title}")
                    return audio_file
                else:
                    attempt.complete(False, "All strategies failed")
                    status.status = 'failed'
                    status.last_error = "All download strategies failed"
                    
            except asyncio.TimeoutError:
                attempt.complete(False, "Download timeout")
                status.status = 'failed'
                status.last_error = "Download timeout (30 minutes exceeded)"
                logger.warning(f"⏰ Smart router timeout for {episode.title}")
                
            except Exception as e:
                attempt.complete(False, str(e))
                status.status = 'failed'
                status.last_error = str(e)
                logger.error(f"❌ Smart router error for {episode.title}: {e}")
            
            # Update stats and progress
            self.stats['failed'] += 1
            self._report_progress()
            return None
            
    async def _try_download(self, episode: Episode, url: str, strategy: str, 
                          status: EpisodeDownloadStatus) -> Optional[Path]:
        """Try downloading from a specific URL"""
        attempt = DownloadAttempt(url, strategy)
        status.add_attempt(attempt)
        
        try:
            logger.info(f"Trying {strategy} for {episode.title}: {url}")
            
            # Create a modified episode with the specific URL
            episode_copy = Episode(
                podcast=episode.podcast,
                title=episode.title,
                published=episode.published,
                duration=episode.duration,
                audio_url=url,  # Use the specific URL
                transcript_url=episode.transcript_url,
                description=episode.description,
                link=episode.link if hasattr(episode, 'link') else None,
                guid=episode.guid if hasattr(episode, 'guid') else None,
                apple_podcast_id=episode.apple_podcast_id if hasattr(episode, 'apple_podcast_id') else None
            )
            
            # Set the transcriber's mode before downloading
            self.transcriber._current_mode = current_mode
            
            # Use the transcriber's simple download method
            audio_path = await self.transcriber.download_audio_simple(
                episode_copy, 
                url,
                f"download-{strategy}-{episode.title[:20]}"
            )
            
            if audio_path and audio_path.exists():
                attempt.complete(True)
                status.status = 'success'
                status.audio_path = audio_path
                
                # Extract audio file information
                status.extract_audio_info()
                
                self._report_progress()
                logger.info(f"Successfully downloaded {episode.title} using {strategy}")
                return audio_path
            else:
                attempt.complete(False, "Download returned no file")
                return None
                
        except Exception as e:
            error_msg = str(e)
            attempt.complete(False, error_msg)
            status.last_error = error_msg
            logger.warning(f"Failed {strategy} for {episode.title}: {error_msg}")
            return None
            
    async def _try_browser_download(self, episode: Episode, 
                                  status: EpisodeDownloadStatus) -> Optional[Path]:
        """Try browser-based download using Playwright"""
        if not episode.audio_url:
            return None
            
        attempt = DownloadAttempt(episode.audio_url, 'browser_automation')
        status.add_attempt(attempt)
        
        try:
            logger.info(f"🌐 Attempting browser-based download for {episode.title}")
            
            # Import browser downloader
            try:
                from .transcripts.browser_downloader import BrowserDownloader, PLAYWRIGHT_AVAILABLE
                
                if not PLAYWRIGHT_AVAILABLE:
                    error_msg = "Playwright not installed. Run: playwright install chromium"
                    attempt.complete(False, error_msg)
                    status.last_error = error_msg
                    logger.warning(error_msg)
                    return None
                    
            except ImportError as e:
                error_msg = f"Failed to import browser downloader: {e}"
                attempt.complete(False, error_msg)
                status.last_error = error_msg
                logger.error(error_msg)
                return None
            
            # Create temporary file path
            temp_filename = generate_temp_filename(f"browser_{episode.podcast}_{int(time.time())}")
            temp_file = Path(TEMP_DIR) / temp_filename
            
            # Use browser downloader
            async with BrowserDownloader() as downloader:
                success = await downloader.download_with_browser(
                    episode.audio_url,
                    str(temp_file),
                    timeout=120
                )
                
                if success and temp_file.exists():
                    attempt.complete(True)
                    status.status = 'success'
                    status.audio_path = temp_file
                    
                    # Extract audio file information
                    status.extract_audio_info()
                    
                    logger.info(f"✅ Browser download successful for {episode.title}")
                    return temp_file
                else:
                    error_msg = "Browser download failed or file not created"
                    attempt.complete(False, error_msg)
                    status.last_error = error_msg
                    return None
                    
        except Exception as e:
            error_msg = f"Browser download error: {str(e)}"
            attempt.complete(False, error_msg)
            status.last_error = error_msg
            logger.error(f"Browser download failed for {episode.title}: {e}")
            return None
            
    async def _try_ytdlp_fallback(self, episode: Episode, 
                                  status: EpisodeDownloadStatus) -> Optional[Path]:
        """Try downloading from YouTube using yt-dlp as final fallback"""
        attempt = DownloadAttempt("youtube_search", 'ytdlp_fallback')
        status.add_attempt(attempt)
        
        try:
            logger.info(f"🎥 Attempting yt-dlp YouTube fallback for {episode.title}")
            
            # Import YtDlpDownloader
            try:
                from .fetchers.fallback_downloader import YtDlpDownloader
            except ImportError as e:
                error_msg = f"Failed to import YtDlpDownloader: {e}"
                attempt.complete(False, error_msg)
                status.last_error = error_msg
                logger.error(error_msg)
                return None
            
            # Create temporary file path
            temp_filename = generate_temp_filename(f"ytdlp_{episode.podcast}_{int(time.time())}")
            temp_file = Path(TEMP_DIR) / temp_filename
            
            # Try to find and download from YouTube
            success = await YtDlpDownloader.find_and_download_youtube(
                episode.title,
                episode.podcast,
                temp_file
            )
            
            if success and temp_file.exists():
                attempt.complete(True)
                status.status = 'success'
                status.audio_path = temp_file
                
                # Extract audio file information
                status.extract_audio_info()
                
                logger.info(f"✅ yt-dlp YouTube download successful for {episode.title}")
                return temp_file
            else:
                error_msg = "yt-dlp YouTube download failed or file not created"
                attempt.complete(False, error_msg)
                status.last_error = error_msg
                return None
                
        except Exception as e:
            error_msg = f"yt-dlp YouTube download error: {str(e)}"
            attempt.complete(False, error_msg)
            status.last_error = error_msg
            logger.error(f"yt-dlp YouTube download failed for {episode.title}: {e}")
            return None
            
    def _report_progress(self):
        """Report progress to callback if available"""
        if self.progress_callback:
            try:
                self.progress_callback(self.get_status())
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
                
    def get_status(self) -> Dict[str, Any]:
        """Get current download status"""
        # Count statuses
        downloaded = sum(1 for s in self.download_status.values() if s.status == 'success')
        failed = sum(1 for s in self.download_status.values() if s.status == 'failed')
        retrying = sum(1 for s in self.download_status.values() if s.status == 'retrying')
        
        return {
            'total': self.stats['total'],
            'downloaded': downloaded,
            'failed': failed,
            'retrying': retrying,
            'episodeDetails': {
                ep_id: status.to_dict() 
                for ep_id, status in self.download_status.items()
            },
            'startTime': self.stats['startTime']
        }
        
    def retry_failed(self, episode_ids: List[str]):
        """Mark episodes for retry"""
        for ep_id in episode_ids:
            if ep_id in self.download_status:
                status = self.download_status[ep_id]
                if status.status == 'failed':
                    status.status = 'retrying'
                    logger.info(f"Marked {ep_id} for retry")
                    
    def get_debug_info(self, episode_id: str) -> Dict[str, Any]:
        """Get detailed debug information for an episode"""
        if episode_id not in self.download_status:
            return {'error': 'Episode not found'}
            
        status = self.download_status[episode_id]
        episode = status.episode
        
        return {
            'episode': {
                'title': episode.title,
                'podcast': episode.podcast,
                'published': str(episode.published),
                'audio_url': episode.audio_url,
                'transcript_url': episode.transcript_url,
                'description': episode.description[:200] if episode.description else None
            },
            'download_attempts': [att.to_dict() for att in status.attempts],
            'available_strategies': [
                'RSS feed URL',
                'YouTube search',
                'Apple Podcasts API',
                'Spotify API',
                'CDN direct access',
                'Browser automation',
                'yt-dlp YouTube fallback'
            ],
            'current_status': status.status,
            'last_error': status.last_error
        }
        
    def save_state(self, filepath: Path):
        """Save download state to file for resume capability"""
        state = {
            'stats': self.stats,
            'episodes': {
                ep_id: {
                    'episode_data': {
                        'title': status.episode.title,
                        'podcast': status.episode.podcast,
                        'published': str(status.episode.published),
                        'audio_url': status.episode.audio_url,
                        'transcript_url': status.episode.transcript_url,
                        'description': status.episode.description
                    },
                    'status': status.status,
                    'attempts': [att.to_dict() for att in status.attempts],
                    'audio_path': str(status.audio_path) if status.audio_path else None,
                    'last_error': status.last_error
                }
                for ep_id, status in self.download_status.items()
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Create directory if it doesn't exist
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"Saved download state to {filepath}")
            
    def load_state(self, filepath: Path, episodes: List[Episode]) -> bool:
        """Load download state from file and match with provided episodes
        
        Args:
            filepath: Path to state file
            episodes: List of Episode objects to match against saved state
            
        Returns:
            True if state was loaded successfully, False otherwise
        """
        if not filepath.exists():
            return False
            
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
                
            self.stats = state.get('stats', self.stats)
            
            # Match episodes with saved state
            episode_map = {}
            for episode in episodes:
                ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
                episode_map[ep_id] = episode
                
            # Reconstruct download status
            loaded_count = 0
            for ep_id, saved_status in state.get('episodes', {}).items():
                if ep_id in episode_map:
                    episode = episode_map[ep_id]
                    status = EpisodeDownloadStatus(episode)
                    
                    # Restore status
                    status.status = saved_status['status']
                    status.last_error = saved_status.get('last_error')
                    if saved_status.get('audio_path'):
                        status.audio_path = Path(saved_status['audio_path'])
                        
                    # Restore attempts
                    for att_data in saved_status.get('attempts', []):
                        attempt = DownloadAttempt(att_data['url'], att_data['strategy'])
                        attempt.success = att_data['success']
                        attempt.error = att_data.get('error')
                        status.attempts.append(attempt)
                        
                    self.download_status[ep_id] = status
                    loaded_count += 1
                    
            logger.info(f"Loaded download state from {filepath}: {loaded_count} episodes restored")
            return loaded_count > 0
            
        except Exception as e:
            logger.error(f"Failed to load download state: {e}")
            return False
            
    async def _retry_with_manual_url(self, episode_id: str, url: str):
        """Retry download with manually provided URL"""
        if episode_id not in self.download_status:
            logger.error(f"Episode {episode_id} not found in download status")
            return
            
        status = self.download_status[episode_id]
        episode = status.episode
        
        logger.info(f"Retrying download for {episode.title} with manual URL: {url}")
        
        # Try the manual URL
        audio_path = await self._try_download(episode, url, 'manual_url_retry', status)
        
        if audio_path:
            logger.info(f"✅ Manual URL download successful for {episode.title}")
            status.status = 'success'
            status.audio_path = audio_path
            
            # Extract audio file information
            status.extract_audio_info()
            
            self.stats['downloaded'] = self.stats.get('downloaded', 0) + 1
            self.stats['retrying'] = max(0, self.stats.get('retrying', 0) - 1)
        else:
            logger.error(f"❌ Manual URL download failed for {episode.title}")
            status.status = 'failed'
            status.last_error = "Manual URL download failed"
            self.stats['failed'] = self.stats.get('failed', 0) + 1
            self.stats['retrying'] = max(0, self.stats.get('retrying', 0) - 1)
            
        self._report_progress()
    
    async def _trim_downloaded_audio(self, audio_file: Path, correlation_id: str) -> Optional[Path]:
        """Trim downloaded audio file to MAX_TRANSCRIPTION_MINUTES for test mode"""
        try:
            import tempfile
            import subprocess
            import shutil
            
            # Calculate max duration in seconds
            max_seconds = MAX_TRANSCRIPTION_MINUTES * 60
            
            # Create temporary trimmed file
            temp_dir = Path(tempfile.gettempdir())
            # Use standardized short filename for temp files
            temp_filename = generate_temp_filename(f"{correlation_id}_{audio_file.name}")
            trimmed_file = temp_dir / temp_filename
            
            # Check if ffmpeg is available (preferred method)
            if shutil.which('ffmpeg'):
                logger.info(f"[{correlation_id}] Using ffmpeg to trim audio to {max_seconds} seconds")
                
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
                    logger.info(f"[{correlation_id}] ✂️ Audio trimmed successfully with ffmpeg")
                    return trimmed_file
                else:
                    logger.error(f"[{correlation_id}] ffmpeg trim failed: {stderr.decode()}")
                    # Fall back to pydub
            else:
                logger.warning(f"[{correlation_id}] ffmpeg not found, using pydub fallback")
            
            # Fallback: use pydub
            try:
                from pydub import AudioSegment
                
                # Check file size first to avoid OOM
                file_size_mb = audio_file.stat().st_size / (1024 * 1024)
                if file_size_mb > 200:  # 200MB threshold
                    logger.error(f"[{correlation_id}] File too large for pydub ({file_size_mb:.1f}MB), skipping trim")
                    return None
                
                logger.info(f"[{correlation_id}] Using pydub to trim audio to {max_seconds} seconds")
                
                # Load audio file
                audio = AudioSegment.from_file(str(audio_file))
                
                # Calculate trimming duration in milliseconds
                max_duration_ms = max_seconds * 1000
                
                # If audio is already shorter, return None (no trimming needed)
                if len(audio) <= max_duration_ms:
                    logger.info(f"[{correlation_id}] Audio already short enough ({len(audio)/1000:.1f}s), no trimming needed")
                    return None
                
                # Trim the audio
                trimmed_audio = audio[:max_duration_ms]
                
                # Export trimmed audio
                trimmed_audio.export(str(trimmed_file), format="mp3")
                
                logger.info(f"[{correlation_id}] ✂️ Audio trimmed from {len(audio)/1000:.1f}s to {len(trimmed_audio)/1000:.1f}s")
                
                # Clean up
                del audio
                del trimmed_audio
                import gc
                gc.collect()
                
                return trimmed_file
                
            except Exception as e:
                logger.error(f"[{correlation_id}] pydub trim failed: {e}")
                return None
                
        except Exception as e:
            logger.error(f"[{correlation_id}] Audio trim error: {e}")
            return None
    
    async def cleanup(self):
        """Clean up resources"""
        try:
            # Close audio finder session
            if self.audio_finder:
                await self.audio_finder.__aexit__(None, None, None)
            
            # Close transcriber if it has cleanup
            if hasattr(self.transcriber, 'cleanup'):
                await self.transcriber.cleanup()
            
            # Close smart router if it has cleanup
            if hasattr(self.smart_router, 'cleanup'):
                await self.smart_router.cleanup()
                
            logger.info("DownloadManager cleanup completed")
        except Exception as e:
            logger.error(f"Error during DownloadManager cleanup: {e}")