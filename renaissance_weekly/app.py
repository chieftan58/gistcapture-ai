"""Main application class for Renaissance Weekly"""

import asyncio
import json
import threading
from pathlib import Path
from typing import List, Optional, Dict, Callable
from datetime import datetime, timedelta

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
from .utils.helpers import validate_env_vars

logger = get_logger(__name__)


class RenaissanceWeekly:
    """Main application class with improved error handling and two-stage selection"""
    
    def __init__(self):
        validate_env_vars()
        self.db = PodcastDatabase()
        self.transcript_finder = TranscriptFinder(self.db)
        self.episode_fetcher = ReliableEpisodeFetcher(self.db)
        self.transcriber = AudioTranscriber()
        self.summarizer = Summarizer()
        self.selector = EpisodeSelector()
        self.email_digest = EmailDigest()
    
    async def run(self, days_back: int = 7):
        """Main execution function with two-stage selection"""
        logger.info("🚀 Starting Renaissance Weekly System...")
        logger.info(f"📧 Email delivery: {EMAIL_FROM} → {EMAIL_TO}")
        
        if TESTING_MODE:
            logger.info(f"🧪 TESTING MODE: Limited to {MAX_TRANSCRIPTION_MINUTES} min transcriptions")
        
        try:
            # Stage 1: Select podcasts
            selected_podcasts, configuration = self.selector.run_podcast_selection(days_back)
            
            if not selected_podcasts:
                logger.warning("❌ No podcasts selected")
                return
            
            logger.info(f"✅ Selected {len(selected_podcasts)} podcasts")
            logger.info(f"📅 Looking back {configuration['lookback_days']} days")
            
            # Create fetch callback for the loading screen
            # This will be called from a separate thread, so we need to handle async properly
            def fetch_episodes_callback(podcast_names: List[str], days: int, progress_callback: Callable):
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Run the async fetch method
                    result = loop.run_until_complete(
                        self._fetch_selected_episodes(podcast_names, days, progress_callback)
                    )
                    return result
                except Exception as e:
                    logger.error(f"Error in fetch callback: {e}", exc_info=True)
                    raise
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            
            # Stage 2: Show loading screen and fetch episodes, then select episodes
            selected_episodes = self.selector.show_loading_screen_and_fetch(
                selected_podcasts, 
                configuration, 
                fetch_episodes_callback
            )
            
            logger.info(f"✅ Episode selection complete: {len(selected_episodes) if selected_episodes else 0} episodes selected")
            
            if not selected_episodes:
                logger.warning("❌ No episodes selected for processing")
                return
            
            logger.info(f"🎯 Starting to process {len(selected_episodes)} episodes...")
            
            # Debug: Log the episodes we're about to process
            for i, ep in enumerate(selected_episodes[:3]):
                if isinstance(ep, Episode):
                    logger.debug(f"  Episode {i+1}: {ep.title} - {ep.podcast}")
                else:
                    logger.debug(f"  Episode {i+1}: {type(ep)} - {ep}")
            
            # Process episodes - ensure they are Episode objects
            processed_episodes = []
            for ep in selected_episodes:
                if isinstance(ep, Episode):
                    processed_episodes.append(ep)
                    logger.debug(f"  Added Episode object: {ep.title}")
                elif isinstance(ep, dict):
                    try:
                        episode_obj = Episode(**ep)
                        processed_episodes.append(episode_obj)
                        logger.debug(f"  Converted dict to Episode: {episode_obj.title}")
                    except Exception as e:
                        logger.error(f"  Failed to convert dict to Episode: {e}")
                        logger.error(f"  Dict content: {ep}")
                else:
                    logger.warning(f"  Unknown episode type: {type(ep)}")
            
            if not processed_episodes:
                logger.error("❌ No valid episodes to process after conversion")
                return
            
            logger.info(f"📋 {len(processed_episodes)} valid episodes ready for processing")
            
            # Process episodes
            summaries = await self._process_episodes(processed_episodes)
            
            logger.info(f"✅ Successfully processed {len(summaries)}/{len(processed_episodes)} episodes")
            
            # Send email digest
            if summaries:
                logger.info("📧 Preparing email digest...")
                if self.email_digest.send_digest(summaries):
                    logger.info("📧 Renaissance Weekly digest sent!")
                else:
                    logger.error("❌ Failed to send email")
            else:
                logger.warning("❌ No summaries generated - nothing to send")
                
        except KeyboardInterrupt:
            logger.info("⚠️ Operation cancelled by user")
        except Exception as e:
            logger.error(f"❌ Unexpected error in main run: {e}", exc_info=True)
    
    async def _fetch_selected_episodes(self, podcast_names: List[str], days_back: int, 
                                      progress_callback: Callable) -> List[Episode]:
        """Fetch episodes for selected podcasts with progress updates"""
        all_episodes = []
        
        for i, podcast_name in enumerate(podcast_names):
            progress_callback(podcast_name, i, len(podcast_names))
            
            # Find the podcast config
            podcast_config = next(
                (config for config in PODCAST_CONFIGS if config["name"] == podcast_name), 
                None
            )
            
            if not podcast_config:
                logger.warning(f"⚠️ No configuration found for {podcast_name}")
                continue
            
            try:
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                all_episodes.extend(episodes)
                logger.info(f"  ✅ {podcast_name}: {len(episodes)} episodes")
            except Exception as e:
                logger.error(f"  ❌ {podcast_name}: Failed to fetch episodes - {e}")
        
        return all_episodes
    
    async def _process_episodes(self, selected_episodes: List[Episode]) -> List[Dict]:
        """Process selected episodes concurrently with better error handling"""
        summaries = []
        
        logger.info(f"🔄 Starting concurrent processing of {len(selected_episodes)} episodes...")
        
        async def process_with_semaphore(episode, semaphore, index):
            async with semaphore:
                try:
                    logger.info(f"🎯 [{index+1}/{len(selected_episodes)}] Starting: {episode.title}")
                    
                    # Ensure episode is an Episode object
                    if not isinstance(episode, Episode):
                        logger.error(f"Invalid episode type: {type(episode)}")
                        return None
                    
                    summary = await self.process_episode(episode)
                    if summary:
                        logger.info(f"✅ [{index+1}/{len(selected_episodes)}] Completed: {episode.title}")
                        return {"episode": episode, "summary": summary}
                    else:
                        logger.warning(f"⚠️ [{index+1}/{len(selected_episodes)}] No summary generated: {episode.title}")
                    return None
                except Exception as e:
                    logger.error(f"❌ [{index+1}/{len(selected_episodes)}] Failed to process '{episode.title}': {e}", exc_info=True)
                    return None
        
        # Limit concurrent processing to avoid overwhelming resources
        semaphore = asyncio.Semaphore(3)
        
        tasks = [
            process_with_semaphore(ep, semaphore, i)
            for i, ep in enumerate(selected_episodes)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Episode {i+1} processing failed with exception: {result}")
            elif isinstance(result, dict) and result:
                summaries.append(result)
        
        logger.info(f"📊 Processing complete: {len(summaries)} summaries generated")
        return summaries
    
    async def process_episode(self, episode: Episode) -> Optional[str]:
        """Process a single episode with improved error handling"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🎧 Processing: {episode.title}")
        logger.info(f"📅 Published: {episode.published.strftime('%Y-%m-%d')}")
        logger.info(f"🎙️  Podcast: {episode.podcast}")
        logger.info(f"{'='*60}")
        
        try:
            # Step 1: Try to find existing transcript
            logger.info("🔍 Checking for existing transcript...")
            transcript_text, transcript_source = await self.transcript_finder.find_transcript(episode)
            
            # Step 2: If no transcript found, transcribe from audio
            if not transcript_text:
                logger.info("📥 No transcript found - downloading audio for transcription...")
                
                # Check if we have audio URL
                if not episode.audio_url:
                    logger.error("❌ No audio URL available for this episode")
                    return None
                
                logger.info(f"🎵 Audio URL: {episode.audio_url[:100]}...")
                transcript_text = await self.transcriber.transcribe_episode(episode)
                
                if transcript_text:
                    transcript_source = TranscriptSource.GENERATED
                    logger.info("✅ Audio transcribed successfully")
                else:
                    logger.error("❌ Failed to transcribe audio")
                    return None
            else:
                logger.info(f"✅ Found existing transcript (source: {transcript_source.value})")
            
            # Save transcript to database
            self.db.save_episode(episode, transcript_text, transcript_source)
            
            # Step 3: Generate summary
            logger.info("📝 Generating executive summary...")
            summary = await self.summarizer.generate_summary(episode, transcript_text, transcript_source)
            
            if summary:
                logger.info("✅ Episode processed successfully!")
                # Save summary to database
                self.db.save_episode(episode, transcript_text, transcript_source, summary)
            else:
                logger.error("❌ Failed to generate summary")
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error processing episode: {e}", exc_info=True)
            return None
    
    # ... rest of the methods remain the same ...
    
    async def check_single_podcast(self, podcast_name: str, days_back: int = 7):
        """Debug function to check a single podcast"""
        # Find the podcast config
        podcast_config = None
        for config in PODCAST_CONFIGS:
            if config["name"].lower() == podcast_name.lower():
                podcast_config = config
                break
        
        if not podcast_config:
            logger.error(f"❌ Podcast '{podcast_name}' not found in configuration")
            logger.info("\nAvailable podcasts:")
            for config in PODCAST_CONFIGS:
                logger.info(f"  - {config['name']}")
            return
        
        await self.episode_fetcher.debug_single_podcast(podcast_config, days_back)
    
    async def run_verification_report(self, days_back: int = 7):
        """Run a verification report comparing all sources against Apple Podcasts"""
        logger.info("🔍 Running Apple Podcasts Verification Report...")
        logger.info(f"📅 Checking episodes from the last {days_back} days\n")
        
        report_data = []
        total_found = 0
        total_missing = 0
        
        for podcast_config in PODCAST_CONFIGS:
            podcast_name = podcast_config["name"]
            logger.info(f"Checking {podcast_name}...")
            
            try:
                # Fetch episodes using our methods
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                
                # Verify against Apple
                verification = await self.episode_fetcher.verify_against_apple_podcasts(
                    podcast_config, episodes, days_back
                )
                
                report_entry = {
                    "podcast": podcast_name,
                    "found_episodes": len(episodes),
                    "verification": verification
                }
                
                if verification["status"] == "success":
                    report_entry["apple_episodes"] = verification["apple_episode_count"]
                    report_entry["missing_episodes"] = verification["missing_count"]
                    total_found += len(episodes)
                    total_missing += verification["missing_count"]
                
                report_data.append(report_entry)
                
            except Exception as e:
                logger.error(f"Error checking {podcast_name}: {e}")
                report_data.append({
                    "podcast": podcast_name,
                    "error": str(e)
                })
        
        # Generate and display report
        self._display_verification_report(report_data, total_found, total_missing)
        
        # Save detailed report
        report_file = Path("verification_report.json")
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, default=str)
        logger.info(f"\n💾 Detailed report saved to: {report_file}")
    
    def _display_verification_report(self, report_data: List[Dict], total_found: int, total_missing: int):
        """Display verification report"""
        logger.info("\n" + "="*80)
        logger.info("📊 VERIFICATION REPORT SUMMARY")
        logger.info("="*80)
        
        for entry in report_data:
            podcast = entry["podcast"]
            
            if "error" in entry:
                logger.error(f"\n❌ {podcast}")
                logger.error(f"   Error: {entry['error']}")
                continue
            
            found = entry["found_episodes"]
            verification = entry["verification"]
            
            if verification["status"] == "success":
                apple_count = verification["apple_episode_count"]
                missing = verification["missing_count"]
                
                status = "✅" if missing == 0 else "⚠️"
                logger.info(f"\n{status} {podcast}")
                logger.info(f"   Found: {found} episodes")
                logger.info(f"   Apple: {apple_count} episodes")
                
                if missing > 0:
                    logger.warning(f"   Missing: {missing} episodes")
                    for i, ep in enumerate(verification["missing_episodes"][:3]):
                        logger.warning(f"      - {ep['title']} ({ep['date'].strftime('%Y-%m-%d')})")
                    if missing > 3:
                        logger.warning(f"      ... and {missing - 3} more")
                    
                    logger.info(f"   Apple Feed: {verification['apple_feed_url']}")
            else:
                logger.warning(f"\n❌ {podcast}")
                logger.warning(f"   Verification failed: {verification['reason']}")
                logger.info(f"   Found: {found} episodes (unverified)")
        
        logger.info("\n" + "="*80)
        logger.info(f"📈 TOTALS:")
        logger.info(f"   Episodes found: {total_found}")
        logger.info(f"   Episodes missing: {total_missing}")
        
        if total_found + total_missing > 0:
            success_rate = (total_found / (total_found + total_missing) * 100)
            logger.info(f"   Success rate: {success_rate:.1f}%")
        else:
            logger.info(f"   Success rate: N/A")
        
        logger.info("="*80)