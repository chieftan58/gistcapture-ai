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
from .utils.logging import get_logger
from .utils.helpers import exponential_backoff_with_jitter
from .config import TEMP_DIR

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
        
    def add_attempt(self, attempt: DownloadAttempt):
        """Add a download attempt"""
        self.attempts.append(attempt)
        
    def to_dict(self) -> dict:
        """Convert to dictionary for UI display"""
        return {
            'episode': f"{self.episode.podcast}: {self.episode.title}",
            'status': self.status,
            'attemptCount': len(self.attempts),
            'attempts': [att.to_dict() for att in self.attempts],
            'lastError': self.last_error,
            'currentStrategy': self.attempts[-1].strategy if self.attempts else None,
            'history': [att.to_dict() for att in self.attempts]
        }


class DownloadManager:
    """Manage concurrent episode downloads with retry strategies"""
    
    def __init__(self, concurrency: int = 10, progress_callback: Optional[Callable] = None):
        self.concurrency = concurrency
        self.progress_callback = progress_callback
        self.transcriber = AudioTranscriber()
        self.audio_finder = AudioSourceFinder()
        self.download_status: Dict[str, EpisodeDownloadStatus] = {}
        self._download_semaphore = asyncio.Semaphore(concurrency)
        self._manual_url_queue: Dict[str, str] = {}
        self._browser_download_queue: List[str] = []
        self._cancelled = False
        
        # Download statistics
        self.stats = {
            'total': 0,
            'downloaded': 0,
            'retrying': 0,
            'failed': 0,
            'startTime': None
        }
        
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
        
    async def download_episodes(self, episodes: List[Episode], podcast_configs: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
        """Download multiple episodes concurrently"""
        self.stats['total'] = len(episodes)
        self.stats['startTime'] = time.time()
        
        # Store the event loop for cross-thread operations
        self._event_loop = asyncio.get_running_loop()
        
        # Store podcast configs for audio finder
        if podcast_configs:
            self.podcast_configs = podcast_configs
        
        # Initialize status for each episode
        for episode in episodes:
            ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
            self.download_status[ep_id] = EpisodeDownloadStatus(episode)
        
        # Use audio finder as context manager to ensure proper cleanup
        async with self.audio_finder:
            # Create download tasks
            tasks = [self._download_episode(episode) for episode in episodes]
            
            # Run downloads concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
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
        
        async with self._download_semaphore:
            if self._cancelled:
                return None
                
            # First check if file already exists
            from .config import AUDIO_DIR
            from .utils.helpers import slugify, calculate_file_hash, validate_audio_file_smart
            
            # Ensure audio directory exists
            AUDIO_DIR.mkdir(exist_ok=True)
            
            date_str = episode.published.strftime('%Y%m%d')
            safe_podcast = slugify(episode.podcast)[:30]
            safe_title = slugify(episode.title)[:50]
            # Get current mode from parent app or use test as default
            current_mode = getattr(self, 'transcription_mode', 'test')
            mode_suffix = '_test' if current_mode == 'test' else '_full'
            audio_file = AUDIO_DIR / f"{date_str}_{safe_podcast}_{safe_title}{mode_suffix}.mp3"
            
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
            
            # Check for manual URL
            if ep_id in self._manual_url_queue:
                url = self._manual_url_queue.pop(ep_id)
                audio_path = await self._try_download(episode, url, 'manual_url', status)
                if audio_path:
                    return audio_path
                    
            # Check for browser download request
            if ep_id in self._browser_download_queue:
                self._browser_download_queue.remove(ep_id)
                audio_path = await self._try_browser_download(episode, status)
                if audio_path:
                    return audio_path
                    
            # Universal YouTube handling for all problematic podcasts
            if UniversalYouTubeHandler.should_handle(episode.podcast):
                logger.info(f"🎥 Universal YouTube handling for {episode.podcast}: {episode.title[:50]}...")
                
                # Use the universal handler to enhance the episode
                enhanced_episode = UniversalYouTubeHandler.enhance_episode(episode)
                
                # Try downloading with enhanced URL
                audio_path = await asyncio.wait_for(
                    self._try_download(
                        enhanced_episode,
                        enhanced_episode.audio_url,
                        f'{episode.podcast.lower().replace(" ", "_")}_youtube',
                        status
                    ),
                    timeout=300  # 5 minute timeout per attempt
                )
                if audio_path:
                    return audio_path
                
                # Try manual URLs if available
                manual_urls = UniversalYouTubeHandler.get_manual_urls(episode.podcast)
                for i, (key, url) in enumerate(manual_urls.items()):
                    if key.lower() in episode.title.lower():
                        try:
                            audio_path = await asyncio.wait_for(
                                self._try_download(
                                    episode,
                                    url,
                                    f'{episode.podcast.lower().replace(" ", "_")}_manual_{i+1}',
                                    status
                                ),
                                timeout=300
                            )
                            if audio_path:
                                return audio_path
                        except asyncio.TimeoutError:
                            logger.warning(f"Download timeout for {episode.title[:50]}...")
                            continue
                
                # If all else fails, provide download instructions
                status.last_error = UniversalYouTubeHandler.get_download_instructions(episode)
                
                # Log detailed instructions once per podcast
                instructions_key = f'_youtube_instructions_{episode.podcast.replace(" ", "_")}'
                if not hasattr(self, instructions_key):
                    from .fetchers.youtube_cookie_helper import YouTubeCookieHelper
                    logger.info(YouTubeCookieHelper.get_cookie_instructions())
                    setattr(self, instructions_key, True)
                
                logger.info(f"{episode.podcast} download failed - YouTube auth required: {episode.title[:50]}...")
                
                # Mark as failed before returning
                status.status = 'failed'
                self._report_progress()
                return None
            
            # Regular download handling for non-YouTube podcasts
                    
            # Try multiple audio sources with timeout
            try:
                # Get podcast config for this episode
                podcast_config = None
                if hasattr(self, 'podcast_configs') and episode.podcast in self.podcast_configs:
                    podcast_config = self.podcast_configs[episode.podcast]
                    # Set apple_podcast_id on episode if not already set
                    if not episode.apple_podcast_id and 'apple_id' in podcast_config:
                        episode.apple_podcast_id = podcast_config['apple_id']
                        logger.info(f"Set apple_podcast_id={episode.apple_podcast_id} for {episode.podcast}")
                
                # Add timeout to audio source finding
                sources = await asyncio.wait_for(
                    self.audio_finder.find_all_audio_sources(episode, podcast_config),
                    timeout=120  # 2 minutes to find sources
                )
                logger.info(f"Found {len(sources)} audio sources for {episode.title[:50]}...")
                
                for i, source_url in enumerate(sources):
                    if self._cancelled:
                        break
                    
                    try:
                        audio_path = await asyncio.wait_for(
                            self._try_download(
                                episode, 
                                source_url, 
                                f'multi_source_{i+1}',
                                status
                            ),
                            timeout=300  # 5 minutes per download
                        )
                        if audio_path:
                            return audio_path
                    except asyncio.TimeoutError:
                        logger.warning(f"Source {i+1} timeout for {episode.title[:50]}...")
                        continue
                        
                # Try original URL as last resort
                if episode.audio_url and not self._cancelled:
                    try:
                        audio_path = await asyncio.wait_for(
                            self._try_download(
                                episode, 
                                episode.audio_url, 
                                'original_rss',
                                status
                            ),
                            timeout=300
                        )
                        if audio_path:
                            return audio_path
                    except asyncio.TimeoutError:
                        logger.warning(f"Original RSS timeout for {episode.title[:50]}...")
                        
                # Final fallback: Try yt-dlp YouTube download
                if not self._cancelled:
                    logger.info(f"🎥 All sources failed, trying yt-dlp YouTube fallback for {episode.title[:50]}...")
                    try:
                        audio_path = await asyncio.wait_for(
                            self._try_ytdlp_fallback(episode, status),
                            timeout=600  # 10 minutes for YouTube fallback
                        )
                        if audio_path:
                            return audio_path
                    except asyncio.TimeoutError:
                        logger.warning(f"YouTube fallback timeout for {episode.title[:50]}...")
                        
            except Exception as e:
                logger.error(f"Error finding audio sources for {episode.title}: {e}")
                status.last_error = str(e)
                
            # Mark as failed if no successful download
            status.status = 'failed'
            status.last_error = status.last_error or "All download strategies failed"
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
            temp_file = Path(TEMP_DIR) / f"browser_download_{episode.title[:20]}_{int(time.time())}.mp3"
            
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
            temp_file = Path(TEMP_DIR) / f"ytdlp_download_{episode.title[:20]}_{int(time.time())}.mp3"
            
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
            self.stats['downloaded'] = self.stats.get('downloaded', 0) + 1
            self.stats['retrying'] = max(0, self.stats.get('retrying', 0) - 1)
        else:
            logger.error(f"❌ Manual URL download failed for {episode.title}")
            status.status = 'failed'
            status.last_error = "Manual URL download failed"
            self.stats['failed'] = self.stats.get('failed', 0) + 1
            self.stats['retrying'] = max(0, self.stats.get('retrying', 0) - 1)
            
        self._report_progress()