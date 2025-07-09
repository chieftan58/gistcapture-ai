"""Main application class for Renaissance Weekly - FIXED with enhanced robustness"""

import asyncio
import json
import threading
import uuid
import traceback
import time
from pathlib import Path
from typing import List, Optional, Dict, Callable, Any
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from .config import (
    TESTING_MODE, MAX_TRANSCRIPTION_MINUTES, EMAIL_TO, EMAIL_FROM,
    PODCAST_CONFIGS, VERIFY_APPLE_PODCASTS, FETCH_MISSING_EPISODES
)
from .database import PodcastDatabase
from .models import Episode, TranscriptSource
from .fetchers.episode_fetcher import ReliableEpisodeFetcher
from .transcripts.finder import TranscriptFinder
from .transcripts.transcriber import AudioTranscriber
from .processing.summarizer import Summarizer
from .ui.selection import EpisodeSelector
from .email.digest import EmailDigest
from .utils.logging import get_logger
from .monitoring import monitor
from .utils.helpers import (
    validate_env_vars, get_available_memory, get_cpu_count,
    ProgressTracker, exponential_backoff_with_jitter, slugify
)
from .utils.clients import openai_rate_limiter

logger = get_logger(__name__)


class ResourceAwareConcurrencyManager:
    """Manage concurrency based on available system resources"""
    
    def __init__(self, correlation_id: str):
        self.correlation_id = correlation_id
        self.base_concurrency = 3
        self.max_concurrency = 10
        self.min_memory_per_task = 500  # MB for test mode
        self.min_memory_per_task_full = 1500  # MB for full mode (larger audio files)
        self.cpu_multiplier = 1.5
        self.is_full_mode = False
        
    def get_optimal_concurrency(self, openai_limit: int = 3) -> int:
        """Calculate optimal concurrency based on system resources with OpenAI limit"""
        try:
            # Get available resources
            available_memory = get_available_memory()
            cpu_count = get_cpu_count()
            
            # Calculate memory-based limit based on mode
            memory_per_task = self.min_memory_per_task_full if self.is_full_mode else self.min_memory_per_task
            memory_limit = int(available_memory / memory_per_task)
            
            # Calculate CPU-based limit
            cpu_limit = int(cpu_count * self.cpu_multiplier)
            
            # Take the minimum of all limits including OpenAI
            optimal = min(
                max(self.base_concurrency, memory_limit),
                cpu_limit,
                self.max_concurrency,
                openai_limit  # Hard limit for OpenAI operations
            )
            
            logger.info(
                f"[{self.correlation_id}] Resource-aware concurrency: {optimal} "
                f"(Memory: {available_memory:.0f}MB allows {memory_limit}, "
                f"CPU: {cpu_count} cores allows {cpu_limit}, "
                f"OpenAI limit: {openai_limit})"
            )
            
            return optimal
            
        except Exception as e:
            logger.warning(f"[{self.correlation_id}] Could not determine optimal concurrency: {e}")
            return min(self.base_concurrency, openai_limit)


class ExceptionAggregator:
    """Aggregate exceptions from concurrent tasks"""
    
    def __init__(self, correlation_id: str):
        self.correlation_id = correlation_id
        self.exceptions = []
        self._lock = asyncio.Lock()
    
    async def add_exception(self, task_name: str, exception: Exception):
        """Add an exception with context"""
        async with self._lock:
            self.exceptions.append({
                'task': task_name,
                'exception': exception,
                'traceback': traceback.format_exc(),
                'timestamp': datetime.now()
            })
    
    def get_summary(self) -> Dict[str, Any]:
        """Get exception summary"""
        if not self.exceptions:
            return {'has_errors': False}
        
        # Group by exception type
        by_type = defaultdict(list)
        for exc_data in self.exceptions:
            exc_type = type(exc_data['exception']).__name__
            by_type[exc_type].append(exc_data)
        
        return {
            'has_errors': True,
            'total_errors': len(self.exceptions),
            'error_types': dict(by_type),
            'first_error': self.exceptions[0] if self.exceptions else None,
            'last_error': self.exceptions[-1] if self.exceptions else None
        }
    
    def log_summary(self):
        """Log exception summary"""
        summary = self.get_summary()
        if summary['has_errors']:
            logger.error(f"[{self.correlation_id}] Exception Summary:")
            logger.error(f"  Total errors: {summary['total_errors']}")
            
            for exc_type, errors in summary['error_types'].items():
                logger.error(f"  {exc_type}: {len(errors)} occurrences")
                
                # Log first occurrence of each type
                first_error = errors[0]
                logger.error(f"    First occurred in: {first_error['task']}")
                logger.error(f"    Message: {str(first_error['exception'])[:200]}")


class RenaissanceWeekly:
    """Main application class with improved error handling and reliability"""
    
    def __init__(self):
        self.correlation_id = str(uuid.uuid4())[:8]
        
        try:
            validate_env_vars()
            self.db = PodcastDatabase()
            self.episode_fetcher = ReliableEpisodeFetcher(self.db)
            self.transcript_finder = TranscriptFinder(self.db)
            self.transcriber = AudioTranscriber()
            self.summarizer = Summarizer()
            self.selector = EpisodeSelector(db=self.db)
            self.email_digest = EmailDigest()
            
            # Resource management
            self.concurrency_manager = ResourceAwareConcurrencyManager(self.correlation_id)
            self.exception_aggregator = ExceptionAggregator(self.correlation_id)
            
            # Default transcription mode (will be updated from UI selection)
            self.current_transcription_mode = 'test'
            
            # Cancellation support
            self._processing_cancelled = False
            self._processing_status = None
            self._status_lock = threading.Lock()  # Thread-safe status updates
            self._active_tasks = []  # Track active tasks for cancellation
            
            # Initialize global rate limiter info
            logger.info(f"[{self.correlation_id}] 🔧 OpenAI rate limiter configured: 45 requests/minute (with 10% buffer)")
            
            # Log current API usage
            usage = openai_rate_limiter.get_current_usage()
            logger.info(
                f"[{self.correlation_id}] 📊 Initial OpenAI API usage: "
                f"{usage['current_requests']}/{usage['max_requests']} requests"
            )
            
            logger.info(f"[{self.correlation_id}] ✅ Renaissance Weekly initialized successfully")
            
        except Exception as e:
            logger.error(f"[{self.correlation_id}] ❌ Failed to initialize Renaissance Weekly: {e}")
            raise
    
    async def pre_flight_check(self, podcast_names: List[str], days_back: int = 7) -> Dict:
        """Pre-flight check to identify which podcasts have new episodes"""
        logger.info(f"[{self.correlation_id}] 🔍 Running pre-flight check for {len(podcast_names)} podcasts...")
        
        results = {
            'podcasts_with_episodes': [],
            'podcasts_without_episodes': [],
            'total_episodes_available': 0,
            'estimated_processing_time': 0,
            'should_proceed': True,
            'warnings': []
        }
        
        # Quick RSS check for each podcast
        for podcast_name in podcast_names:
            try:
                # Get podcast config
                podcast_config = next((p for p in PODCAST_CONFIGS if p['name'] == podcast_name), None)
                if not podcast_config:
                    continue
                
                # Check last episode date from database
                last_episode_dates = self.db.get_last_episode_dates([podcast_name])
                last_date = last_episode_dates.get(podcast_name)
                
                if last_date:
                    days_since_last = (datetime.now(timezone.utc) - last_date).days
                    if days_since_last > days_back:
                        results['podcasts_without_episodes'].append({
                            'name': podcast_name,
                            'last_episode_date': last_date,
                            'days_since': days_since_last
                        })
                        logger.info(f"[{self.correlation_id}] ⏭️ {podcast_name}: No new episodes (last: {days_since_last} days ago)")
                    else:
                        results['podcasts_with_episodes'].append(podcast_name)
                        results['total_episodes_available'] += 1  # Estimate 1 per podcast
                else:
                    # New podcast or no history
                    results['podcasts_with_episodes'].append(podcast_name)
                    
            except Exception as e:
                logger.warning(f"[{self.correlation_id}] Error checking {podcast_name}: {e}")
        
        # Calculate estimates
        results['estimated_processing_time'] = results['total_episodes_available'] * 5  # 5 min per episode avg
        
        # Determine if we should proceed
        if results['total_episodes_available'] < 15:
            results['should_proceed'] = False
            results['warnings'].append(f"Only {results['total_episodes_available']} episodes available (minimum: 15)")
        
        # Check for problem podcasts
        problem_podcasts = ['American Optimist', 'Dwarkesh Podcast']
        problem_count = sum(1 for p in problem_podcasts if p in results['podcasts_without_episodes'])
        if problem_count >= 2:
            results['warnings'].append("Multiple Substack podcasts have no new episodes - may be Cloudflare issues")
        
        logger.info(f"[{self.correlation_id}] ✅ Pre-flight complete: {len(results['podcasts_with_episodes'])} podcasts have new content")
        
        return results
    
    async def run(self, days_back: int = 7):
        """Main execution function with simplified flow and progress tracking"""
        start_time = time.time()
        logger.info(f"[{self.correlation_id}] 🚀 Starting Renaissance Weekly System...")
        logger.info(f"[{self.correlation_id}] 📧 Email delivery: {EMAIL_FROM} → {EMAIL_TO}")
        
        if TESTING_MODE:
            logger.info(f"[{self.correlation_id}] 🧪 TESTING MODE: Limited to {MAX_TRANSCRIPTION_MINUTES} min transcriptions")
        
        # Pipeline progress tracker
        pipeline_progress = ProgressTracker(3, self.correlation_id)  # 3 stages
        
        try:
            # Create fetch callback for the UI
            def fetch_episodes_callback(podcast_names: List[str], days: int, progress_callback: Callable):
                """Callback to fetch episodes in a separate thread"""
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self._fetch_selected_episodes(podcast_names, days, progress_callback)
                    )
                    return result
                except Exception as e:
                    logger.error(f"[{self.correlation_id}] Error in fetch callback: {e}", exc_info=True)
                    raise
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            
            # Stage 1: Episode Selection
            await pipeline_progress.start_item("Episode Selection")
            logger.info(f"\n[{self.correlation_id}] 📺 STAGE 1: Episode Selection")
            
            selected_episodes, configuration = self.selector.run_complete_selection(
                days_back,
                fetch_episodes_callback
            )
            
            if not selected_episodes:
                logger.warning(f"[{self.correlation_id}] ❌ No episodes selected - exiting")
                await pipeline_progress.complete_item(False)
                return
            
            logger.info(f"[{self.correlation_id}] ✅ Selected {len(selected_episodes)} episodes for processing")
            logger.info(f"[{self.correlation_id}] 📅 Lookback period: {configuration['lookback_days']} days")
            logger.info(f"[{self.correlation_id}] 🔧 Transcription mode: {configuration['transcription_mode']}")
            
            # Check if email was already approved (UI completed full flow)
            if configuration.get('email_approved') and configuration.get('final_summaries'):
                logger.info(f"[{self.correlation_id}] 📧 Email already approved - sending digest directly")
                summaries = configuration['final_summaries']
                
                # Send email digest
                await pipeline_progress.start_item("Email Delivery")
                if self.email_digest.send_digest(summaries):
                    logger.info(f"[{self.correlation_id}] ✅ Renaissance Weekly digest sent successfully!")
                    await pipeline_progress.complete_item(True)
                else:
                    logger.error(f"[{self.correlation_id}] ❌ Failed to send email digest")
                    await pipeline_progress.complete_item(False)
                
                # Skip processing stages
                total_time = time.time() - start_time
                logger.info(f"\n[{self.correlation_id}] ✨ Email sent in {total_time:.1f} seconds")
                return
            
            # Cost estimation and warning for full mode
            if configuration['transcription_mode'] == 'full':
                estimated_cost = self._estimate_processing_cost(selected_episodes)
                logger.warning(f"[{self.correlation_id}] 💰 COST WARNING: Full episode transcription")
                logger.warning(f"[{self.correlation_id}] 💵 Estimated cost: ${estimated_cost['total']:.2f}")
                logger.warning(f"[{self.correlation_id}]    - Transcription: ${estimated_cost['transcription']:.2f}")
                logger.warning(f"[{self.correlation_id}]    - Summarization: ${estimated_cost['summarization']:.2f}")
                logger.warning(f"[{self.correlation_id}] ⏱️  Estimated time: {estimated_cost['time_minutes']:.0f} minutes")
                
                # In production, could add a confirmation step here
                await asyncio.sleep(3)  # Give user time to see the warning
            
            # Store configuration for use during processing
            self.current_transcription_mode = configuration.get('transcription_mode', 'test')
            self.concurrency_manager.is_full_mode = (self.current_transcription_mode == 'full')
            
            await pipeline_progress.complete_item(True)
            
            # Sort selected episodes to maintain order
            selected_episodes = self._sort_episodes_for_processing(selected_episodes)
            
            # Log selected episodes
            logger.info(f"[{self.correlation_id}] 📋 Episodes to process:")
            for i, ep in enumerate(selected_episodes[:5]):
                logger.info(f"[{self.correlation_id}]   {i+1}. {ep.podcast}: {ep.title}")
                if hasattr(ep, 'audio_url'):
                    logger.info(f"[{self.correlation_id}]      Audio: {'Yes' if ep.audio_url else 'No'}")
            if len(selected_episodes) > 5:
                logger.info(f"[{self.correlation_id}]   ... and {len(selected_episodes) - 5} more")
            
            # Stage 2: Process episodes
            await pipeline_progress.start_item("Episode Processing")
            logger.info(f"\n[{self.correlation_id}] 🎯 STAGE 2: Processing Episodes")
            logger.info(f"[{self.correlation_id}] ⏰ This may take several minutes depending on episode length...")
            
            summaries = await self._process_episodes_with_resource_management(selected_episodes)
            
            logger.info(f"\n[{self.correlation_id}] 📊 Processing Results:")
            logger.info(f"[{self.correlation_id}]    Episodes selected: {len(selected_episodes)}")
            logger.info(f"[{self.correlation_id}]    Summaries generated: {len(summaries)}")
            if selected_episodes:
                logger.info(f"[{self.correlation_id}]    Success rate: {len(summaries)/len(selected_episodes)*100:.1f}%")
            
            # Log exception summary if any
            self.exception_aggregator.log_summary()
            
            # Log final API usage
            final_usage = openai_rate_limiter.get_current_usage()
            logger.info(
                f"[{self.correlation_id}] 📊 Final OpenAI API usage: "
                f"{final_usage['current_requests']}/{final_usage['max_requests']} requests "
                f"({final_usage['utilization']:.1f}% utilization)"
            )
            
            await pipeline_progress.complete_item(len(summaries) > 0)
            
            # Stage 3: Send email digest
            if summaries:
                await pipeline_progress.start_item("Email Delivery")
                logger.info(f"\n[{self.correlation_id}] 📧 STAGE 3: Email Delivery")
                
                # Sort summaries to match the episode order
                summaries = self._sort_summaries_for_email(summaries)
                
                if self.email_digest.send_digest(summaries):
                    logger.info(f"[{self.correlation_id}] ✅ Renaissance Weekly digest sent successfully!")
                    await pipeline_progress.complete_item(True)
                else:
                    logger.error(f"[{self.correlation_id}] ❌ Failed to send email digest")
                    await pipeline_progress.complete_item(False)
            else:
                logger.warning(f"[{self.correlation_id}] ❌ No summaries generated - nothing to send")
            
            # Final summary
            total_time = time.time() - start_time
            summary = pipeline_progress.get_summary()
            
            logger.info(f"\n[{self.correlation_id}] ✨ Renaissance Weekly pipeline completed!")
            logger.info(f"[{self.correlation_id}] ⏱️  Total time: {total_time/60:.1f} minutes")
            logger.info(f"[{self.correlation_id}] 📈 Pipeline success rate: {summary['success_rate']:.0f}%")
            
            # Log any critical issues
            exc_summary = self.exception_aggregator.get_summary()
            if exc_summary['has_errors']:
                logger.warning(
                    f"[{self.correlation_id}] ⚠️  Pipeline completed with {exc_summary['total_errors']} errors. "
                    f"Check logs for details."
                )
                
        except KeyboardInterrupt:
            logger.info(f"\n[{self.correlation_id}] ⚠️ Operation cancelled by user")
        except Exception as e:
            logger.error(f"\n[{self.correlation_id}] ❌ Unexpected error in main run: {e}", exc_info=True)
            await self.exception_aggregator.add_exception("main_run", e)
        finally:
            # Ensure cleanup happens
            await self.cleanup()
    
    def _sort_episodes_for_processing(self, episodes: List[Episode]) -> List[Episode]:
        """Sort episodes: by podcast name (alphabetically), then by date (newest first)"""
        return sorted(episodes, key=lambda ep: (
            ep.podcast.lower(),  # Primary: podcast name alphabetically
            -ep.published.timestamp()  # Secondary: date descending (newest first)
        ))
    
    def _sort_summaries_for_email(self, summaries: List[Dict]) -> List[Dict]:
        """Sort summaries to maintain the same order as episodes"""
        return sorted(summaries, key=lambda s: (
            s['episode'].podcast.lower(),  # Primary: podcast name alphabetically
            -s['episode'].published.timestamp()  # Secondary: date descending
        ))
    
    async def _fetch_selected_episodes(self, podcast_names: List[str], days_back: int, 
                                      progress_callback: Callable) -> List[Episode]:
        """Fetch episodes for selected podcasts with progress updates"""
        all_episodes = []
        podcasts_with_no_recent_episodes = []
        
        logger.info(f"[{self.correlation_id}] 📡 Starting to fetch episodes from {len(podcast_names)} podcasts...")
        logger.info(f"[{self.correlation_id}] 📅 Looking back {days_back} days")
        
        # Progress tracker for fetching
        fetch_progress = ProgressTracker(len(podcast_names), self.correlation_id)
        
        # Sort podcast names alphabetically for consistent order
        sorted_podcast_names = sorted(podcast_names, key=lambda x: x.lower())
        
        for i, podcast_name in enumerate(sorted_podcast_names):
            progress_callback(podcast_name, i, len(sorted_podcast_names))
            
            # Find the podcast config
            podcast_config = next(
                (config for config in PODCAST_CONFIGS if config["name"] == podcast_name), 
                None
            )
            
            if not podcast_config:
                logger.warning(f"[{self.correlation_id}] ⚠️ No configuration found for {podcast_name}")
                await fetch_progress.complete_item(False)
                continue
            
            try:
                await fetch_progress.start_item(podcast_name)
                logger.info(f"[{self.correlation_id}] 📻 Fetching episodes for {podcast_name}...")
                
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                
                if episodes:
                    all_episodes.extend(episodes)
                    logger.info(f"[{self.correlation_id}]   ✅ {podcast_name}: Found {len(episodes)} episodes")
                    
                    # Save to database
                    for episode in episodes:
                        try:
                            self.db.save_episode(episode)
                        except Exception as e:
                            logger.debug(f"[{self.correlation_id}]   Failed to cache episode: {e}")
                    
                    await fetch_progress.complete_item(True)
                else:
                    logger.info(f"[{self.correlation_id}]   📅 {podcast_name}: No episodes in the last {days_back} days")
                    podcasts_with_no_recent_episodes.append(podcast_name)
                    await fetch_progress.complete_item(True)
                    
            except Exception as e:
                logger.error(f"[{self.correlation_id}]   ❌ {podcast_name}: Failed to fetch episodes - {e}")
                await self.exception_aggregator.add_exception(f"fetch_{podcast_name}", e)
                await fetch_progress.complete_item(False)
        
        # Log fetch summary
        fetch_summary = fetch_progress.get_summary()
        actual_failures = fetch_summary['failed']
        podcasts_checked = fetch_summary['total_items']
        
        if actual_failures > 0:
            logger.info(
                f"[{self.correlation_id}] 📊 Fetch complete: {podcasts_checked - actual_failures}/{podcasts_checked} successful, "
                f"{actual_failures} failed, {len(all_episodes)} total episodes"
            )
        else:
            logger.info(
                f"[{self.correlation_id}] 📊 Fetch complete: All {podcasts_checked} podcasts checked successfully, "
                f"{len(all_episodes)} total episodes"
            )
        
        # Get last episode dates for podcasts with no recent episodes
        last_episode_dates = {}
        if podcasts_with_no_recent_episodes:
            logger.info(f"[{self.correlation_id}] 📅 Getting last episode dates for {len(podcasts_with_no_recent_episodes)} podcasts...")
            last_episode_dates = self.db.get_last_episode_dates(podcasts_with_no_recent_episodes)
            
            # Log the results
            for podcast_name in podcasts_with_no_recent_episodes:
                last_date = last_episode_dates.get(podcast_name)
                if last_date:
                    days_ago = (datetime.now(timezone.utc) - last_date).days
                    logger.info(f"[{self.correlation_id}]   📅 {podcast_name}: Last episode was {days_ago} days ago ({last_date.strftime('%Y-%m-%d')})")
                else:
                    logger.info(f"[{self.correlation_id}]   📅 {podcast_name}: No episodes found in database")
        
        # Store the last episode dates in the selector for UI access
        if hasattr(self, 'selector') and self.selector:
            self.selector._last_episode_dates = last_episode_dates
        
        return all_episodes
    
    async def _process_episodes_with_resource_management(self, selected_episodes: List[Episode]) -> List[Dict]:
        """Process episodes with dynamic concurrency based on system resources and OpenAI limits"""
        summaries = []
        
        # Initialize processing status for UI
        self._processing_status = {
            'total': len(selected_episodes),
            'completed': 0,
            'failed': 0,
            'currently_processing': set(),  # Track multiple episodes being processed
            'errors': []
        }
        
        # Get optimal concurrency with separate limits for different services
        whisper_concurrency_limit = 3  # Whisper API: 3 requests per minute
        gpt4_concurrency_limit = 20  # GPT-4 API: Much higher limit (check your tier)
        # Allow more concurrent tasks for transcript fetching and other non-API operations
        general_concurrency = self.concurrency_manager.get_optimal_concurrency(10)  # Up to 10 concurrent tasks
        
        logger.info(f"[{self.correlation_id}] 🔄 Starting concurrent processing of {len(selected_episodes)} episodes...")
        logger.info(f"[{self.correlation_id}] ⚙️  Max concurrent tasks: {general_concurrency}")
        logger.info(f"[{self.correlation_id}] 🎙️  Whisper API limit: {whisper_concurrency_limit} concurrent")
        logger.info(f"[{self.correlation_id}] 🤖  GPT-4 API limit: {gpt4_concurrency_limit} concurrent")
        
        # Progress tracker for processing
        process_progress = ProgressTracker(len(selected_episodes), self.correlation_id)
        
        # Create semaphores for different types of operations
        # General semaphore for overall concurrency (transcript fetch, processing, etc.)
        general_semaphore = asyncio.Semaphore(general_concurrency)
        # Separate semaphores for different OpenAI services
        self._whisper_semaphore = asyncio.Semaphore(whisper_concurrency_limit)
        self._gpt4_semaphore = asyncio.Semaphore(gpt4_concurrency_limit)
        
        # Create tasks with enhanced error handling
        tasks = []
        for i, episode in enumerate(selected_episodes):
            task = asyncio.create_task(
                self._process_episode_with_monitoring(
                    episode, general_semaphore, process_progress, i
                )
            )
            tasks.append(task)
        
        # Store active tasks for cancellation support
        self._active_tasks = tasks
        
        # DIAGNOSTIC: Log task creation
        logger.info(f"[{self.correlation_id}] 📋 Created {len(tasks)} tasks for processing")
        
        # Monitor resource usage periodically
        monitor_task = asyncio.create_task(self._monitor_resources(general_concurrency))
        
        try:
            # Execute all tasks
            logger.info(f"[{self.correlation_id}] 🚀 Starting asyncio.gather for {len(tasks)} tasks...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(f"[{self.correlation_id}] ✅ asyncio.gather completed with {len(results)} results")
            
            # Process results maintaining order
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    episode = selected_episodes[i]
                    logger.error(
                        f"[{self.correlation_id}] Episode {i+1} ({episode.title[:50]}...) "
                        f"failed with exception: {result}"
                    )
                    await self.exception_aggregator.add_exception(
                        f"process_episode_{i}_{episode.title[:30]}", 
                        result
                    )
                elif isinstance(result, dict) and result:
                    summaries.append(result)
                elif result is None:
                    logger.debug(f"[{self.correlation_id}] Episode {i+1} returned None")
            
        finally:
            # Cancel monitoring
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            # Clear active tasks list
            self._active_tasks = []
        
        # Log processing summary
        process_summary = process_progress.get_summary()
        
        # Verify all episodes are accounted for
        total_processed = process_summary['completed'] + process_summary['failed']
        if total_processed < process_summary['total_items']:
            logger.warning(
                f"[{self.correlation_id}] ⚠️ Not all episodes were processed! "
                f"Expected: {process_summary['total_items']}, Processed: {total_processed}"
            )
            # Log which episodes might be missing
            if len(results) < len(selected_episodes):
                logger.error(
                    f"[{self.correlation_id}] 🚨 Results mismatch: {len(results)} results for {len(selected_episodes)} episodes"
                )
        
        logger.info(
            f"[{self.correlation_id}] ✅ Processing complete: "
            f"{process_summary['completed']}/{process_summary['total_items']} episodes succeeded "
            f"({process_summary['success_rate']:.0f}% success rate) "
            f"in {process_summary['duration_seconds']/60:.1f} minutes"
        )
        
        return summaries
    
    async def _process_episodes_with_progress(self, selected_episodes: List[Episode], progress_callback: Callable) -> List[Dict]:
        """Process episodes with progress callback for UI updates"""
        summaries = []
        
        # Store the callback
        self._progress_callback = progress_callback
        
        try:
            # Process using existing method
            summaries = await self._process_episodes_with_resource_management(selected_episodes)
        finally:
            self._progress_callback = None
            
        return summaries
    
    async def _process_episode_with_monitoring(self, episode: Episode, semaphore: asyncio.Semaphore, 
                                             progress: ProgressTracker, index: int) -> Optional[Dict]:
        """Process single episode with monitoring and error handling"""
        async with semaphore:
            # Check for cancellation before starting
            if self._processing_cancelled:
                logger.info(f"[{self.correlation_id}] Processing cancelled, skipping episode {index+1}")
                return None
                
            episode_id = f"{episode.podcast}:{episode.title[:30]}"
            episode_timeout = 600  # 10 minutes per episode
            
            try:
                await progress.start_item(episode_id)
                
                # Update processing status if available (thread-safe)
                if self._processing_status:
                    with self._status_lock:
                        self._processing_status['currently_processing'].add(f"{episode.podcast}:{episode.title}")
                
                # Call progress callback if available
                if hasattr(self, '_progress_callback') and self._progress_callback:
                    self._progress_callback(episode, 'processing')
                
                # Add retry logic with exponential backoff
                max_retries = 3
                last_exception = None
                
                for attempt in range(max_retries):
                    try:
                        # Check for cancellation in retry loop
                        if self._processing_cancelled:
                            logger.info(f"[{self.correlation_id}] Processing cancelled during episode {index+1}")
                            return None
                            
                        # Add timeout to prevent stuck episodes
                        logger.debug(f"[{self.correlation_id}] Processing episode {index+1}: {episode_id}")
                        summary = await asyncio.wait_for(
                            self.process_episode(episode),
                            timeout=episode_timeout
                        )
                        
                        if summary:
                            await progress.complete_item(True)
                            # Update processing status (thread-safe)
                            if self._processing_status:
                                with self._status_lock:
                                    self._processing_status['completed'] += 1
                                    self._processing_status['currently_processing'].discard(f"{episode.podcast}:{episode.title}")
                            
                            # Call progress callback if available
                            if hasattr(self, '_progress_callback') and self._progress_callback:
                                self._progress_callback(episode, 'completed')
                            logger.debug(f"[{self.correlation_id}] Episode {index+1} completed successfully")
                            return {"episode": episode, "summary": summary}
                        else:
                            await progress.complete_item(False)
                            # Update processing status (thread-safe)
                            if self._processing_status:
                                with self._status_lock:
                                    self._processing_status['failed'] += 1
                                    self._processing_status['currently_processing'].discard(f"{episode.podcast}:{episode.title}")
                            
                            # Call progress callback if available
                            if hasattr(self, '_progress_callback') and self._progress_callback:
                                self._progress_callback(episode, 'failed')
                            logger.debug(f"[{self.correlation_id}] Episode {index+1} completed with no summary")
                            return None
                            
                    except asyncio.TimeoutError:
                        logger.error(
                            f"[{self.correlation_id}] Episode {index+1} ({episode_id}) timed out after {episode_timeout}s"
                        )
                        last_exception = asyncio.TimeoutError(f"Episode processing timed out after {episode_timeout}s")
                        if attempt < max_retries - 1:
                            logger.warning(f"[{self.correlation_id}] Retrying episode {index+1}...")
                            continue
                        else:
                            raise last_exception
                    except Exception as e:
                        last_exception = e
                        if attempt < max_retries - 1:
                            delay = exponential_backoff_with_jitter(attempt)
                            logger.warning(
                                f"[{self.correlation_id}] Episode processing attempt {attempt + 1} failed: {e}. "
                                f"Retrying in {delay:.1f}s..."
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise
                
            except Exception as e:
                logger.error(
                    f"[{self.correlation_id}] Failed to process {episode_id} after {max_retries} attempts: {e}"
                )
                await self.exception_aggregator.add_exception(episode_id, e)
                await progress.complete_item(False)
                
                # Update processing status with error (thread-safe)
                if self._processing_status:
                    with self._status_lock:
                        self._processing_status['failed'] += 1
                        self._processing_status['currently_processing'].discard(f"{episode.podcast}:{episode.title}")
                
                # Call progress callback if available
                if hasattr(self, '_progress_callback') and self._progress_callback:
                    self._progress_callback(episode, 'failed', e)
                    if self._processing_status:
                        with self._status_lock:
                            self._processing_status['errors'].append({
                                'episode': f"{episode.podcast}: {episode.title}",
                                'message': str(e)[:200]  # Limit error message length
                            })
                
                return None
    
    async def _monitor_resources(self, initial_concurrency: int):
        """Monitor system resources and log warnings if needed"""
        check_interval = 30  # seconds
        low_memory_threshold = 500 if self.concurrency_manager.is_full_mode else 200  # MB
        
        while True:
            try:
                await asyncio.sleep(check_interval)
                
                available_memory = get_available_memory()
                total_memory = get_available_memory() + get_used_memory() if 'get_used_memory' in globals() else available_memory * 2
                memory_usage_pct = ((total_memory - available_memory) / total_memory) * 100
                
                # Log detailed memory info
                logger.info(
                    f"[{self.correlation_id}] 💾 Memory: {available_memory:.0f}MB free "
                    f"({memory_usage_pct:.1f}% used) | Mode: {self.current_transcription_mode}"
                )
                
                if available_memory < low_memory_threshold:
                    logger.warning(
                        f"[{self.correlation_id}] ⚠️  Low memory warning: {available_memory:.0f}MB available "
                        f"(threshold: {low_memory_threshold}MB). "
                        f"Consider reducing concurrency from {initial_concurrency}."
                    )
                
                # Log API rate limiter status
                api_usage = openai_rate_limiter.get_current_usage()
                if api_usage['utilization'] > 80:
                    logger.warning(
                        f"[{self.correlation_id}] ⚠️  High API usage: {api_usage['utilization']:.1f}% "
                        f"({api_usage['current_requests']}/{api_usage['max_requests']} requests)"
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[{self.correlation_id}] Resource monitoring error: {e}")
    
    async def process_episode(self, episode: Episode) -> Optional[str]:
        """Process a single episode with comprehensive logging"""
        episode_id = str(uuid.uuid4())[:8]
        logger.info(f"\n[{episode_id}] {'='*60}")
        logger.info(f"[{episode_id}] 🎧 PROCESSING EPISODE:")
        logger.info(f"[{episode_id}]    Title: {episode.title}")
        logger.info(f"[{episode_id}]    Podcast: {episode.podcast}")
        logger.info(f"[{episode_id}]    Published: {episode.published.strftime('%Y-%m-%d')}")
        logger.info(f"[{episode_id}]    Duration: {episode.duration}")
        logger.info(f"[{episode_id}]    Audio URL: {'Yes' if episode.audio_url else 'No'}")
        logger.info(f"[{episode_id}]    Transcript URL: {'Yes' if episode.transcript_url else 'No'}")
        logger.info(f"[{episode_id}] {'='*60}")
        
        try:
            # Step 1: Try to find existing transcript
            logger.info(f"\n[{episode_id}] 📄 Step 1: Checking for existing transcript...")
            transcript_text, transcript_source = await self.transcript_finder.find_transcript(episode)
            
            # If transcript found, validate it immediately
            if transcript_text:
                # Validate the transcript content
                if self.summarizer._validate_transcript_content(transcript_text, transcript_source):
                    logger.info(f"[{episode_id}] ✅ Found valid transcript (source: {transcript_source.value})")
                    logger.info(f"[{episode_id}] 📏 Transcript length: {len(transcript_text)} characters")
                    monitor.record_success('transcript_fetch', episode.podcast)
                else:
                    logger.warning(f"[{episode_id}] ⚠️ Found transcript but validation failed - falling back to audio")
                    monitor.record_failure('transcript_fetch', episode.podcast, episode.title, 
                                         'ValidationFailed', 'Transcript found but contains only metadata')
                    # Reset transcript to trigger audio fallback
                    transcript_text = None
                    transcript_source = None
            
            # Step 2: If no valid transcript found, transcribe from audio
            if not transcript_text:
                # Only record as NotFound if we didn't already record as ValidationFailed
                if transcript_source is None:
                    monitor.record_failure('transcript_fetch', episode.podcast, episode.title, 
                                         'NotFound', 'No transcript found from any source')
                logger.info(f"\n[{episode_id}] 🎵 Step 2: No valid transcript found - transcribing from audio...")
                
                # Check if we have audio URL
                if not episode.audio_url:
                    logger.error(f"[{episode_id}] ❌ No audio URL available for this episode")
                    return None
                
                logger.info(f"[{episode_id}] 🔗 Audio URL: {episode.audio_url[:80]}...")
                transcript_text = await self.transcriber.transcribe_episode(episode, self.current_transcription_mode)
                
                if transcript_text:
                    transcript_source = TranscriptSource.GENERATED
                    logger.info(f"[{episode_id}] ✅ Audio transcribed successfully")
                    logger.info(f"[{episode_id}] 📏 Transcript length: {len(transcript_text)} characters")
                    monitor.record_success('audio_transcription', episode.podcast)
                else:
                    logger.error(f"[{episode_id}] ❌ Failed to transcribe audio")
                    monitor.record_failure('audio_transcription', episode.podcast, episode.title,
                                         'TranscriptionFailed', 'Failed to transcribe audio')
                    return None
            
            # Save transcript to database
            try:
                self.db.save_episode(episode, transcript_text, transcript_source)
                logger.info(f"[{episode_id}] 💾 Transcript saved to database")
            except Exception as e:
                logger.warning(f"[{episode_id}] Failed to save transcript to database: {e}")
            
            # Step 3: Generate summary
            logger.info(f"\n[{episode_id}] 📝 Step 3: Generating executive summary...")
            summary = await self.summarizer.generate_summary(episode, transcript_text, transcript_source)
            
            if summary:
                logger.info(f"[{episode_id}] ✅ Summary generated successfully!")
                logger.info(f"[{episode_id}] 📏 Summary length: {len(summary)} characters")
                monitor.record_success('summarization', episode.podcast)
                # Save summary to database
                try:
                    self.db.save_episode(episode, transcript_text, transcript_source, summary)
                    logger.info(f"[{episode_id}] 💾 Summary saved to database")
                except Exception as e:
                    logger.warning(f"[{episode_id}] Failed to save summary to database: {e}")
            else:
                logger.error(f"[{episode_id}] ❌ Failed to generate summary")
                monitor.record_failure('summarization', episode.podcast, episode.title,
                                     'SummarizationFailed', 'Failed to generate summary')
            
            return summary
            
        except Exception as e:
            logger.error(f"[{episode_id}] ❌ Error processing episode: {e}", exc_info=True)
            monitor.record_failure('episode_processing', episode.podcast, episode.title,
                                 type(e).__name__, str(e))
            raise
        finally:
            logger.info(f"[{episode_id}] {'='*60}\n")
    
    def _estimate_processing_cost(self, episodes: List[Episode]) -> dict:
        """Estimate the cost of processing episodes"""
        # Average podcast episode duration
        avg_duration_minutes = 90  # Conservative estimate
        
        # Cost rates (as of 2024)
        whisper_cost_per_minute = 0.006
        gpt4_cost_per_1k_tokens = 0.01  # Input tokens
        gpt4_output_cost_per_1k_tokens = 0.03
        
        # Estimate tokens for summarization (roughly 4 tokens per 3 words)
        avg_transcript_words = avg_duration_minutes * 150  # ~150 words per minute speaking
        avg_tokens = (avg_transcript_words * 4) / 3
        avg_summary_tokens = 1000  # Output tokens
        
        total_minutes = len(episodes) * avg_duration_minutes
        transcription_cost = total_minutes * whisper_cost_per_minute
        
        # GPT-4 costs
        input_cost = len(episodes) * (avg_tokens / 1000) * gpt4_cost_per_1k_tokens
        output_cost = len(episodes) * (avg_summary_tokens / 1000) * gpt4_output_cost_per_1k_tokens
        summarization_cost = input_cost + output_cost
        
        # Time estimation (including rate limits)
        transcription_time = len(episodes) * 5  # ~5 minutes per episode with chunking
        processing_time = transcription_time + (len(episodes) * 1)  # +1 minute per episode for other tasks
        
        return {
            'transcription': transcription_cost,
            'summarization': summarization_cost,
            'total': transcription_cost + summarization_cost,
            'time_minutes': processing_time,
            'episodes': len(episodes),
            'total_audio_minutes': total_minutes
        }
    
    async def check_single_podcast(self, podcast_name: str, days_back: int = 7):
        """Debug function to check a single podcast"""
        logger.info(f"\n[{self.correlation_id}] 🔍 DEBUG MODE: Checking single podcast '{podcast_name}'")
        
        # Find the podcast config
        podcast_config = None
        for config in PODCAST_CONFIGS:
            if config["name"].lower() == podcast_name.lower():
                podcast_config = config
                break
        
        if not podcast_config:
            logger.error(f"[{self.correlation_id}] ❌ Podcast '{podcast_name}' not found in configuration")
            logger.info(f"\n[{self.correlation_id}] 📋 Available podcasts:")
            for config in sorted(PODCAST_CONFIGS, key=lambda x: x['name'].lower()):
                logger.info(f"[{self.correlation_id}]   - {config['name']}")
            return
        
        await self.episode_fetcher.debug_single_podcast(podcast_config, days_back)
    
    async def run_verification_report(self, days_back: int = 7):
        """Run a verification report comparing all sources against Apple Podcasts"""
        logger.info(f"[{self.correlation_id}] 🔍 Running Apple Podcasts Verification Report...")
        logger.info(f"[{self.correlation_id}] 📅 Checking episodes from the last {days_back} days\n")
        
        report_data = []
        total_found = 0
        total_missing = 0
        
        # Progress tracker for verification
        verify_progress = ProgressTracker(len(PODCAST_CONFIGS), self.correlation_id)
        
        # Sort podcasts alphabetically
        sorted_configs = sorted(PODCAST_CONFIGS, key=lambda x: x['name'].lower())
        
        for podcast_config in sorted_configs:
            podcast_name = podcast_config["name"]
            
            try:
                await verify_progress.start_item(podcast_name)
                logger.info(f"\n[{self.correlation_id}] 📻 Checking {podcast_name}...")
                
                # Fetch episodes using our methods
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                
                # Verify against Apple if configured
                if VERIFY_APPLE_PODCASTS and podcast_config.get("apple_id"):
                    verification = await self.episode_fetcher.verify_against_apple_podcasts(
                        podcast_config, episodes, days_back
                    )
                    
                    # Optionally fetch missing episodes
                    if FETCH_MISSING_EPISODES and verification.get("missing_count", 0) > 0:
                        logger.info(
                            f"[{self.correlation_id}]   🔄 Fetching {verification['missing_count']} "
                            f"missing episodes from Apple..."
                        )
                        missing_episodes = await self.episode_fetcher.fetch_missing_from_apple(
                            podcast_config, episodes, verification
                        )
                        if missing_episodes:
                            episodes.extend(missing_episodes)
                            logger.info(
                                f"[{self.correlation_id}]   ✅ Added {len(missing_episodes)} missing episodes"
                            )
                else:
                    verification = {"status": "skipped", "reason": "Apple verification disabled or no Apple ID"}
                
                report_entry = {
                    "podcast": podcast_name,
                    "found_episodes": len(episodes),
                    "verification": verification
                }
                
                if verification["status"] == "success":
                    report_entry["apple_episodes"] = verification["apple_episode_count"]
                    report_entry["missing_episodes"] = verification["missing_count"]
                    total_found += len(episodes)
                    total_missing += verification.get("missing_count", 0)
                
                report_data.append(report_entry)
                await verify_progress.complete_item(True)
                
            except Exception as e:
                logger.error(f"[{self.correlation_id}] Error checking {podcast_name}: {e}")
                report_data.append({
                    "podcast": podcast_name,
                    "error": str(e)
                })
                await verify_progress.complete_item(False)
        
        # Generate and display report
        self._display_verification_report(report_data, total_found, total_missing)
        
        # Save detailed report
        report_file = Path("verification_report.json")
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump({
                "verification_date": datetime.now().isoformat(),
                "days_back": days_back,
                "correlation_id": self.correlation_id,
                "summary": {
                    "total_podcasts": len(PODCAST_CONFIGS),
                    "episodes_found": total_found,
                    "episodes_missing": total_missing
                },
                "details": report_data,
                "exceptions": self.exception_aggregator.get_summary(),
                "api_usage": openai_rate_limiter.get_current_usage()
            }, f, indent=2, default=str)
        logger.info(f"\n[{self.correlation_id}] 💾 Detailed report saved to: {report_file}")
        
        # Log verification summary
        verify_summary = verify_progress.get_summary()
        logger.info(
            f"\n[{self.correlation_id}] 📊 Verification complete: "
            f"{verify_summary['completed']}/{verify_summary['total_items']} podcasts verified successfully"
        )
    
    def _display_verification_report(self, report_data: List[Dict], total_found: int, total_missing: int):
        """Display verification report in a clean format"""
        logger.info(f"\n[{self.correlation_id}] " + "="*80)
        logger.info(f"[{self.correlation_id}] 📊 VERIFICATION REPORT SUMMARY")
        logger.info(f"[{self.correlation_id}] " + "="*80)
        
        for entry in report_data:
            podcast = entry["podcast"]
            
            if "error" in entry:
                logger.error(f"\n[{self.correlation_id}] ❌ {podcast}")
                logger.error(f"[{self.correlation_id}]    Error: {entry['error']}")
                continue
            
            found = entry["found_episodes"]
            verification = entry["verification"]
            
            if verification["status"] == "success":
                apple_count = verification["apple_episode_count"]
                missing = verification["missing_count"]
                
                status = "✅" if missing == 0 else "⚠️"
                logger.info(f"\n[{self.correlation_id}] {status} {podcast}")
                logger.info(f"[{self.correlation_id}]    Found: {found} episodes")
                logger.info(f"[{self.correlation_id}]    Apple: {apple_count} episodes")
                
                if missing > 0:
                    logger.warning(f"[{self.correlation_id}]    Missing: {missing} episodes")
                    for i, ep in enumerate(verification["missing_episodes"][:3]):
                        logger.warning(
                            f"[{self.correlation_id}]       - {ep['title']} "
                            f"({ep['date'].strftime('%Y-%m-%d')})"
                        )
                    if missing > 3:
                        logger.warning(f"[{self.correlation_id}]       ... and {missing - 3} more")
                    
                    if verification.get("apple_feed_url"):
                        logger.info(f"[{self.correlation_id}]    Apple Feed: {verification['apple_feed_url']}")
            elif verification["status"] == "skipped":
                logger.info(f"\n[{self.correlation_id}] ⏭️  {podcast}")
                logger.info(f"[{self.correlation_id}]    Found: {found} episodes")
                logger.info(f"[{self.correlation_id}]    Verification: {verification['reason']}")
            else:
                logger.warning(f"\n[{self.correlation_id}] ❌ {podcast}")
                logger.warning(
                    f"[{self.correlation_id}]    Verification failed: "
                    f"{verification.get('reason', 'Unknown error')}"
                )
                logger.info(f"[{self.correlation_id}]    Found: {found} episodes (unverified)")
        
        logger.info(f"\n[{self.correlation_id}] " + "="*80)
        logger.info(f"[{self.correlation_id}] 📈 TOTALS:")
        logger.info(f"[{self.correlation_id}]    Episodes found: {total_found}")
        logger.info(f"[{self.correlation_id}]    Episodes missing: {total_missing}")
        
        if total_found + total_missing > 0:
            success_rate = (total_found / (total_found + total_missing) * 100)
            logger.info(f"[{self.correlation_id}]    Success rate: {success_rate:.1f}%")
        
        logger.info(f"[{self.correlation_id}] " + "="*80)
    
    async def test_fetch_only(self, days_back: int = 7):
        """Test episode fetching without processing"""
        logger.info(f"[{self.correlation_id}] 🧪 TEST MODE: Fetching episodes only")
        
        # Select podcasts
        selector = EpisodeSelector(db=self.db)
        
        # Create a simple fetch callback
        async def fetch_episodes_test(podcast_names, days, progress_callback):
            since_date = datetime.now() - timedelta(days=days)
            return await self._fetch_selected_episodes(
                podcast_names, 
                days,
                progress_callback
            )
        
        def fetch_callback(podcast_names, days, progress_callback):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    fetch_episodes_test(podcast_names, days, progress_callback)
                )
                return result
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        
        selected_episodes, config = selector.run_complete_selection(days_back, fetch_callback)
        
        if not selected_episodes:
            logger.info("No episodes selected")
            return
        
        logger.info(f"[{self.correlation_id}] ✅ Selected {len(selected_episodes)} episodes")
        for episode in selected_episodes[:10]:  # Show first 10
            logger.info(f"  - {episode.podcast}: {episode.title}")
    
    async def test_summarize_only(self, transcript_file: str):
        """Test summarization with a provided transcript file"""
        logger.info(f"[{self.correlation_id}] 🧪 TEST MODE: Summarizing transcript from {transcript_file}")
        
        # Read transcript
        transcript_path = Path(transcript_file)
        if not transcript_path.exists():
            logger.error(f"Transcript file not found: {transcript_file}")
            return
        
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript = f.read()
        
        # Create dummy episode
        episode = Episode(
            guid="test-episode",
            title="Test Episode",
            podcast="Test Podcast",
            published=datetime.now(),
            link="https://example.com",
            audio_url="https://example.com/audio.mp3",
            duration="1:00:00"
        )
        
        # Generate summary
        summary = await self.summarizer.generate_summary(episode, transcript, TranscriptSource.CACHED)
        
        if summary:
            logger.info(f"[{self.correlation_id}] ✅ Summary generated ({len(summary)} chars)")
            print("\n" + "="*80)
            print(summary)
            print("="*80 + "\n")
        else:
            logger.error(f"[{self.correlation_id}] ❌ Failed to generate summary")
    
    async def test_email_only(self):
        """Test email generation with cached data"""
        logger.info(f"[{self.correlation_id}] 🧪 TEST MODE: Generating email from cached data")
        
        # Get recent episodes with summaries from database
        recent_episodes = self.db.get_episodes_with_summaries(days_back=7)
        
        if not recent_episodes:
            logger.error("No episodes with summaries found in cache")
            return
        
        logger.info(f"[{self.correlation_id}] Found {len(recent_episodes)} episodes with summaries")
        
        # Generate and send digest
        await self._generate_and_send_digest(recent_episodes[:5])  # Limit to 5 for test
    
    async def retry_failed_episodes(self, failed_episode_info: List[Dict], use_alternative_sources: bool = True) -> Dict:
        """Retry failed episodes with alternative download sources"""
        logger.info(f"[{self.correlation_id}] 🔄 Starting retry for {len(failed_episode_info)} failed episodes")
        
        results = {
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        # Extract episode info from failed episodes
        episodes_to_retry = []
        for error_info in failed_episode_info:
            episode_name = error_info.get('episode', '')
            error_msg = error_info.get('message', '')
            
            # Parse podcast and title from episode name
            if ': ' in episode_name:
                podcast, title = episode_name.split(': ', 1)
                
                # Try to find the episode in the database
                episode_data = self.db.get_episode(podcast, title, datetime.now())
                if episode_data:
                    # Reconstruct Episode object
                    episode = Episode(
                        podcast=episode_data['podcast'],
                        title=episode_data['title'],
                        published=datetime.fromisoformat(episode_data['published']),
                        audio_url=episode_data.get('audio_url'),
                        link=episode_data.get('link'),
                        description=episode_data.get('description'),
                        duration=episode_data.get('duration'),
                        guid=episode_data.get('guid')
                    )
                    
                    # Store retry strategy based on error and podcast config
                    retry_strategy = self._determine_retry_strategy(error_msg, podcast)
                    episodes_to_retry.append({
                        'episode': episode,
                        'error': error_msg,
                        'strategy': retry_strategy
                    })
                    
                    # Update database with retry attempt
                    if episode_data.get('id'):
                        self.db.update_episode_status(
                            episode_data['id'], 
                            'retrying',
                            failure_reason=error_msg,
                            retry_strategy=retry_strategy
                        )
        
        # Process retries with specific strategies
        if episodes_to_retry:
            retry_summaries = await self._process_episodes_with_retry_strategies(episodes_to_retry)
            
            for summary in retry_summaries:
                if summary:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
            
            # Add remaining failures to errors
            if results['failed'] > 0:
                for retry_info in episodes_to_retry[results['successful']:]:
                    results['errors'].append({
                        'episode': f"{retry_info['episode'].podcast}: {retry_info['episode'].title}",
                        'message': retry_info['error']
                    })
        
        logger.info(f"[{self.correlation_id}] ✅ Retry complete: {results['successful']} succeeded, {results['failed']} failed")
        return results
    
    def _determine_retry_strategy(self, error_msg: str, podcast_name: str = None) -> str:
        """Determine the best retry strategy based on error type and podcast configuration"""
        # Check if podcast has specific retry strategy configured
        if podcast_name:
            from .config import PODCAST_CONFIGS
            podcast_config = next((p for p in PODCAST_CONFIGS if p['name'] == podcast_name), None)
            if podcast_config and 'retry_strategy' in podcast_config:
                return podcast_config['retry_strategy'].get('primary', 'standard_retry')
        
        # Fall back to error-based strategy
        if '403' in error_msg or 'Cloudflare' in error_msg:
            return 'youtube_search'
        elif 'timeout' in error_msg or 'Timeout' in error_msg:
            return 'cdn_extended_timeout'
        elif 'transcript' in error_msg or 'Transcription' in error_msg:
            return 'force_audio_transcription'
        elif 'audio' in error_msg.lower() or 'download' in error_msg.lower():
            return 'alternative_audio_sources'
        else:
            return 'standard_retry'
    
    async def _process_episodes_with_retry_strategies(self, retry_infos: List[Dict]) -> List[Dict]:
        """Process episodes with specific retry strategies"""
        summaries = []
        
        for retry_info in retry_infos:
            episode = retry_info['episode']
            strategy = retry_info['strategy']
            
            logger.info(f"[{self.correlation_id}] 🔄 Retrying {episode.podcast}: {episode.title} with strategy: {strategy}")
            
            try:
                # Apply strategy-specific modifications
                if strategy == 'youtube_search':
                    # Force YouTube as primary audio source
                    from .fetchers.audio_sources import AudioSourceFinder
                    async with AudioSourceFinder() as finder:
                        sources = await finder.find_all_audio_sources(episode)
                        # Find YouTube URL in sources
                        youtube_url = next((s for s in sources if 'youtube.com' in s or 'youtu.be' in s), None)
                        if youtube_url:
                            episode.audio_url = youtube_url
                            logger.info(f"[{self.correlation_id}] 🎥 Using YouTube URL: {youtube_url}")
                
                elif strategy == 'cdn_extended_timeout':
                    # Temporarily increase timeouts
                    # This would need to be passed through to the downloader
                    logger.info(f"[{self.correlation_id}] ⏱️ Using extended timeout (120s)")
                
                elif strategy == 'force_audio_transcription':
                    # Skip transcript search, go straight to audio
                    logger.info(f"[{self.correlation_id}] 🎵 Forcing audio transcription")
                    # Set a flag to skip transcript search
                    episode._force_audio_transcription = True
                
                # Process the episode with modifications
                summary = await self.process_episode(episode)
                if summary:
                    summaries.append({"episode": episode, "summary": summary})
                    
            except Exception as e:
                logger.error(f"[{self.correlation_id}] ❌ Retry failed for {episode.podcast}: {e}")
                continue
        
        return summaries
    
    async def run_dry_run(self, days_back: int = 7):
        """Run full pipeline without making API calls"""
        logger.info(f"[{self.correlation_id}] 🧪 DRY RUN MODE: No API calls will be made")
        
        # Set environment to disable API calls
        import os
        os.environ['DRY_RUN'] = 'true'
        
        try:
            # Run normal pipeline - components should check DRY_RUN env var
            await self.run(days_back)
        finally:
            # Reset environment
            os.environ.pop('DRY_RUN', None)
    
    async def save_test_dataset(self, name: str):
        """Save current cache as test dataset"""
        logger.info(f"[{self.correlation_id}] 💾 Saving test dataset: {name}")
        
        from .utils.test_cache import TestDataCache
        cache = TestDataCache()
        
        if cache.save_dataset(name):
            logger.info(f"[{self.correlation_id}] ✅ Dataset saved successfully")
            
            # List all datasets
            datasets = cache.list_datasets()
            logger.info(f"[{self.correlation_id}] Available datasets:")
            for dataset in datasets:
                logger.info(f"  - {dataset['name']} (created: {dataset['created'][:10]})")
    
    async def load_test_dataset(self, name: str):
        """Load test dataset into cache"""
        logger.info(f"[{self.correlation_id}] 📂 Loading test dataset: {name}")
        
        from .utils.test_cache import TestDataCache
        cache = TestDataCache()
        
        if cache.load_dataset(name):
            logger.info(f"[{self.correlation_id}] ✅ Dataset loaded successfully")
            
            # Show what was loaded
            recent_episodes = self.db.get_recent_episodes(days_back=30)
            logger.info(f"[{self.correlation_id}] Loaded {len(recent_episodes)} episodes")
    
    async def regenerate_summaries(self, days_back: int = 7):
        """Force regenerate summaries for recent episodes"""
        logger.info(f"[{self.correlation_id}] 🔄 Regenerating summaries for last {days_back} days")
        
        # Get episodes with transcripts
        since_date = datetime.now() - timedelta(days=days_back)
        episodes = self.db.get_recent_episodes(days_back)
        episodes_with_transcripts = []
        
        for ep_dict in episodes:
            if ep_dict.get('transcript'):
                episode = Episode(
                    guid=ep_dict['guid'],
                    title=ep_dict['title'],
                    podcast=ep_dict['podcast'],
                    published=datetime.fromisoformat(ep_dict['published']),
                    link=ep_dict.get('link', ''),
                    audio_url=ep_dict.get('audio_url', ''),
                    duration=ep_dict.get('duration', '')
                )
                episodes_with_transcripts.append({
                    'episode': episode,
                    'transcript': ep_dict['transcript'],
                    'source': TranscriptSource(ep_dict.get('transcript_source', 'UNKNOWN'))
                })
        
        logger.info(f"[{self.correlation_id}] Found {len(episodes_with_transcripts)} episodes with transcripts")
        
        # Delete existing summaries
        from .config import SUMMARY_DIR
        deleted_count = 0
        for ep_data in episodes_with_transcripts:
            episode = ep_data['episode']
            date_str = episode.published.strftime('%Y%m%d')
            safe_podcast = slugify(episode.podcast)[:30]
            safe_title = slugify(episode.title)[:50]
            summary_file = SUMMARY_DIR / f"{date_str}_{safe_podcast}_{safe_title}_summary.md"
            
            if summary_file.exists():
                summary_file.unlink()
                deleted_count += 1
                logger.info(f"  Deleted cached summary: {summary_file.name}")
        
        logger.info(f"[{self.correlation_id}] Deleted {deleted_count} cached summaries")
        
        # Regenerate summaries
        summaries = []
        for i, ep_data in enumerate(episodes_with_transcripts, 1):
            episode = ep_data['episode']
            logger.info(f"[{self.correlation_id}] [{i}/{len(episodes_with_transcripts)}] Regenerating: {episode.podcast} - {episode.title}")
            
            summary = await self.summarizer.generate_summary(
                episode,
                ep_data['transcript'],
                ep_data['source']
            )
            
            if summary:
                summaries.append({
                    'episode': episode,
                    'summary': summary
                })
                # Update database
                self.db.save_summary(episode, summary)
            else:
                logger.warning(f"[{self.correlation_id}] Failed to regenerate summary")
        
        logger.info(f"[{self.correlation_id}] ✅ Regenerated {len(summaries)} summaries")
        
        # Optionally send email with regenerated summaries
        if summaries and EMAIL_TO:
            logger.info(f"[{self.correlation_id}] 📧 Sending digest with regenerated summaries...")
            await self._generate_and_send_digest(summaries)
    
    def cancel_processing(self):
        """Cancel ongoing processing"""
        logger.info(f"[{self.correlation_id}] 🛑 Cancelling processing...")
        self._processing_cancelled = True
        
        # Cancel all active tasks
        if self._active_tasks:
            logger.info(f"[{self.correlation_id}] 🛑 Cancelling {len(self._active_tasks)} active tasks...")
            for task in self._active_tasks:
                if not task.done():
                    task.cancel()
            self._active_tasks = []
    
    def get_processing_status(self):
        """Get current processing status for UI"""
        if self._processing_status:
            return self._processing_status.copy()
        return {
            'total': 0,
            'completed': 0,
            'failed': 0,
            'current': None,
            'errors': []
        }
    
    def generate_email_preview(self):
        """Generate preview of email content"""
        # This would use the actual email template
        # For now, return a simple preview
        completed = self._processing_status.get('completed', 0) if self._processing_status else 0
        
        return f"""Subject: Renaissance Weekly - Your AI Podcast Digest

Your weekly podcast digest is ready with {completed} episodes successfully processed.

This email will include executive summaries of all processed episodes...
"""
    
    async def cleanup(self):
        """Clean up resources properly"""
        try:
            logger.info(f"[{self.correlation_id}] 🧹 Starting cleanup...")
            
            # Clean up episode fetcher
            if hasattr(self.episode_fetcher, 'cleanup'):
                await self.episode_fetcher.cleanup()
                logger.debug(f"[{self.correlation_id}] ✓ Episode fetcher cleaned up")
            
            # Clean up transcript finder
            if hasattr(self.transcript_finder, 'cleanup'):
                await self.transcript_finder.cleanup()
                logger.debug(f"[{self.correlation_id}] ✓ Transcript finder cleaned up")
            
            # Clean up transcriber
            if hasattr(self.transcriber, 'cleanup'):
                await self.transcriber.cleanup()
                logger.debug(f"[{self.correlation_id}] ✓ Transcriber cleaned up")
            
            # Clean up any temporary files
            from .config import TEMP_DIR
            if TEMP_DIR.exists():
                temp_files_cleaned = 0
                for file in TEMP_DIR.glob("*"):
                    try:
                        file.unlink()
                        temp_files_cleaned += 1
                    except:
                        pass
                
                if temp_files_cleaned > 0:
                    logger.debug(f"[{self.correlation_id}] ✓ Cleaned up {temp_files_cleaned} temp files")
            
            # Log final API usage stats
            final_usage = openai_rate_limiter.get_current_usage()
            logger.info(
                f"[{self.correlation_id}] 📊 Final API usage: "
                f"{final_usage['current_requests']}/{final_usage['max_requests']} requests used"
            )
            
            logger.info(f"[{self.correlation_id}] 🧹 Cleanup completed")
            
        except Exception as e:
            logger.warning(f"[{self.correlation_id}] Cleanup error: {e}")