"""Smart retry handler for failed episodes with different strategies"""

import asyncio
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from ..models import Episode
from ..database import PodcastDatabase
from ..utils.logging import get_logger
from ..fetchers.youtube_enhanced import YouTubeEnhancedFetcher
from ..transcripts.browser_downloader import BrowserDownloader
from ..fetchers.audio_sources import AudioSourceFinder
from ..transcripts.finder import TranscriptFinder
from ..transcripts.transcriber import AudioTranscriber
from ..processing.summarizer import Summarizer

logger = get_logger(__name__)


class RetryHandler:
    """Handle retries for failed episodes with smart strategy selection"""
    
    def __init__(self, db: PodcastDatabase):
        self.db = db
        self.transcript_finder = TranscriptFinder(db)
        self.transcriber = AudioTranscriber()
        self.summarizer = Summarizer()
        
    async def get_retry_strategy(self, episode: Episode, failure_reason: str) -> Dict[str, str]:
        """Determine the best retry strategy based on failure reason"""
        strategy = {
            'episode_id': episode.guid,
            'podcast': episode.podcast,
            'title': episode.title,
            'failure_reason': failure_reason,
            'retry_methods': []
        }
        
        podcast_lower = episode.podcast.lower()
        
        # Cloudflare/403 errors - Use alternative platforms
        if '403' in failure_reason or 'cloudflare' in failure_reason.lower():
            if 'american optimist' in podcast_lower or 'dwarkesh' in podcast_lower:
                strategy['retry_methods'] = [
                    'youtube_search',
                    'apple_podcasts_api',
                    'browser_automation'
                ]
                strategy['recommendation'] = "YouTube search recommended for Substack podcasts"
            else:
                strategy['retry_methods'] = [
                    'apple_podcasts_api',
                    'youtube_search',
                    'cdn_alternatives'
                ]
                strategy['recommendation'] = "Try alternative audio sources"
                
        # Timeout errors - Try with extended timeout
        elif 'timeout' in failure_reason.lower():
            strategy['retry_methods'] = [
                'extended_timeout',
                'direct_cdn',
                'youtube_search'
            ]
            strategy['recommendation'] = "Extend timeout and try direct CDN"
            
        # Transcription failures - Force audio transcription
        elif 'transcription' in failure_reason.lower():
            strategy['retry_methods'] = [
                'force_audio_transcription',
                'alternative_transcription_service',
                'youtube_transcript'
            ]
            strategy['recommendation'] = "Force audio transcription with fallback services"
            
        # Audio download failures - Try alternative sources
        elif 'audio' in failure_reason.lower() or 'download' in failure_reason.lower():
            strategy['retry_methods'] = [
                'youtube_search',
                'apple_podcasts_api',
                'browser_automation',
                'manual_url'
            ]
            strategy['recommendation'] = "Search for alternative audio sources"
            
        else:
            # Generic retry
            strategy['retry_methods'] = [
                'youtube_search',
                'apple_podcasts_api',
                'extended_timeout'
            ]
            strategy['recommendation'] = "Try standard fallback methods"
            
        return strategy
    
    async def retry_episode(self, episode: Episode, strategy: Dict[str, str]) -> Tuple[bool, Optional[str]]:
        """Retry processing an episode with the given strategy"""
        logger.info(f"🔄 Retrying {episode.podcast}: {episode.title}")
        logger.info(f"   Strategy: {strategy['recommendation']}")
        
        for method in strategy['retry_methods']:
            logger.info(f"   Trying method: {method}")
            
            try:
                if method == 'youtube_search':
                    success, summary = await self._retry_with_youtube(episode)
                elif method == 'apple_podcasts_api':
                    success, summary = await self._retry_with_apple(episode)
                elif method == 'browser_automation':
                    success, summary = await self._retry_with_browser(episode)
                elif method == 'extended_timeout':
                    success, summary = await self._retry_with_extended_timeout(episode)
                elif method == 'force_audio_transcription':
                    success, summary = await self._retry_force_audio(episode)
                elif method == 'youtube_transcript':
                    success, summary = await self._retry_youtube_transcript(episode)
                else:
                    continue
                    
                if success and summary:
                    logger.info(f"   ✅ Success with method: {method}")
                    # Update database with success
                    self.db.update_episode_status(
                        episode.guid,
                        'completed',
                        retry_strategy=method
                    )
                    return True, summary
                    
            except Exception as e:
                logger.error(f"   ❌ Method {method} failed: {e}")
                continue
        
        # All methods failed
        logger.error(f"   ❌ All retry methods failed for {episode.title}")
        return False, None
    
    async def _retry_with_youtube(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Retry using YouTube as source"""
        try:
            async with YouTubeEnhancedFetcher() as yt_fetcher:
                youtube_url = await yt_fetcher.find_episode_on_youtube(episode)
                if youtube_url:
                    # Try to get transcript first
                    transcript = await self.transcript_finder.youtube_finder.get_youtube_transcript(youtube_url)
                    if transcript:
                        summary = await self.summarizer.generate_summary(episode, transcript)
                        if summary:
                            return True, summary
                    
                    # Fall back to audio transcription
                    episode.audio_url = youtube_url
                    transcript = await self.transcriber.transcribe_episode(episode, 'full')
                    if transcript:
                        summary = await self.summarizer.generate_summary(episode, transcript)
                        if summary:
                            return True, summary
                            
        except Exception as e:
            logger.error(f"YouTube retry failed: {e}")
            
        return False, None
    
    async def _retry_with_apple(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Retry using Apple Podcasts API"""
        try:
            # Use audio source finder to get Apple URL
            audio_finder = AudioSourceFinder()
            async with audio_finder:
                apple_url = await audio_finder._find_apple_podcasts_url(episode)
                if apple_url:
                    episode.audio_url = apple_url
                    transcript = await self.transcriber.transcribe_episode(episode, 'full')
                    if transcript:
                        summary = await self.summarizer.generate_summary(episode, transcript)
                        if summary:
                            return True, summary
                            
        except Exception as e:
            logger.error(f"Apple Podcasts retry failed: {e}")
            
        return False, None
    
    async def _retry_with_browser(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Retry using browser automation for Cloudflare sites"""
        try:
            if not episode.audio_url:
                logger.error("No audio URL available for browser download")
                return False, None
                
            # Use browser downloader to get the audio file
            async with BrowserDownloader() as downloader:
                # Try Substack-specific handler if it's a Substack URL
                if 'substack.com' in episode.audio_url:
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                        success = await downloader.handle_substack(episode.audio_url, tmp_file.name)
                        if success:
                            # Transcribe the downloaded file
                            episode.audio_url = f"file://{tmp_file.name}"
                            transcript = await self.transcriber.transcribe_episode(episode, 'full')
                            if transcript:
                                summary = await self.summarizer.generate_summary(episode, transcript)
                                if summary:
                                    return True, summary
                else:
                    # Use general browser download
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                        success = await downloader.download_with_browser(episode.audio_url, tmp_file.name)
                        if success:
                            episode.audio_url = f"file://{tmp_file.name}"
                            transcript = await self.transcriber.transcribe_episode(episode, 'full')
                            if transcript:
                                summary = await self.summarizer.generate_summary(episode, transcript)
                                if summary:
                                    return True, summary
                        
        except Exception as e:
            logger.error(f"Browser automation retry failed: {e}")
            
        return False, None
    
    async def _retry_with_extended_timeout(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Retry with extended timeout settings"""
        try:
            # This would need to be implemented in the transcriber
            # For now, just retry with normal settings
            transcript = await self.transcriber.transcribe_episode(episode, 'full')
            if transcript:
                summary = await self.summarizer.generate_summary(episode, transcript)
                if summary:
                    return True, summary
                    
        except Exception as e:
            logger.error(f"Extended timeout retry failed: {e}")
            
        return False, None
    
    async def _retry_force_audio(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Force audio transcription even if we think we have a transcript"""
        try:
            # Skip transcript search and go straight to audio
            if episode.audio_url:
                transcript = await self.transcriber.transcribe_episode(episode, 'full')
                if transcript:
                    summary = await self.summarizer.generate_summary(episode, transcript)
                    if summary:
                        return True, summary
                        
        except Exception as e:
            logger.error(f"Force audio retry failed: {e}")
            
        return False, None
    
    async def _retry_youtube_transcript(self, episode: Episode) -> Tuple[bool, Optional[str]]:
        """Try to get YouTube transcript"""
        try:
            async with YouTubeEnhancedFetcher() as yt_fetcher:
                youtube_url = await yt_fetcher.find_episode_on_youtube(episode)
                if youtube_url:
                    transcript = await self.transcript_finder.youtube_finder.get_youtube_transcript(youtube_url)
                    if transcript:
                        summary = await self.summarizer.generate_summary(episode, transcript)
                        if summary:
                            return True, summary
                            
        except Exception as e:
            logger.error(f"YouTube transcript retry failed: {e}")
            
        return False, None
    
    async def batch_retry_episodes(self, failed_episodes: List[Episode]) -> Dict[str, any]:
        """Retry multiple failed episodes in parallel"""
        results = {
            'total': len(failed_episodes),
            'successful': 0,
            'failed': 0,
            'results': []
        }
        
        # Get retry strategies for all episodes
        strategies = []
        for episode in failed_episodes:
            # Get failure reason from database
            failure_info = self.db.get_episode_failure_info(episode.guid)
            failure_reason = failure_info.get('failure_reason', 'Unknown')
            
            strategy = await self.get_retry_strategy(episode, failure_reason)
            strategies.append((episode, strategy))
        
        # Process in batches to avoid overwhelming resources
        batch_size = 5
        for i in range(0, len(strategies), batch_size):
            batch = strategies[i:i + batch_size]
            
            tasks = []
            for episode, strategy in batch:
                task = self.retry_episode(episode, strategy)
                tasks.append(task)
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for (episode, strategy), result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Retry failed with exception for {episode.title}: {result}")
                    results['failed'] += 1
                    results['results'].append({
                        'episode': episode.title,
                        'success': False,
                        'error': str(result)
                    })
                else:
                    success, summary = result
                    if success:
                        results['successful'] += 1
                        results['results'].append({
                            'episode': episode.title,
                            'success': True,
                            'summary_length': len(summary) if summary else 0
                        })
                    else:
                        results['failed'] += 1
                        results['results'].append({
                            'episode': episode.title,
                            'success': False,
                            'error': 'All retry methods failed'
                        })
        
        return results