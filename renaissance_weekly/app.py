"""Main application class for Renaissance Weekly - FIXED"""

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
    """Main application class with improved error handling and reliability"""
    
    def __init__(self):
        try:
            validate_env_vars()
            self.db = PodcastDatabase()
            self.transcript_finder = TranscriptFinder(self.db)
            self.episode_fetcher = ReliableEpisodeFetcher(self.db)
            self.transcriber = AudioTranscriber()
            self.summarizer = Summarizer()
            self.selector = EpisodeSelector()
            self.email_digest = EmailDigest()
            logger.info("✅ Renaissance Weekly initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Renaissance Weekly: {e}")
            raise
    
    async def run(self, days_back: int = 7):
        """Main execution function with improved error handling"""
        logger.info("🚀 Starting Renaissance Weekly System...")
        logger.info(f"📧 Email delivery: {EMAIL_FROM} → {EMAIL_TO}")
        
        if TESTING_MODE:
            logger.info(f"🧪 TESTING MODE: Limited to {MAX_TRANSCRIPTION_MINUTES} min transcriptions")
        
        try:
            # Stage 1: Select podcasts
            logger.info("\n📻 STAGE 1: Podcast Selection")
            selected_podcasts, configuration = self.selector.run_podcast_selection(days_back)
            
            if not selected_podcasts:
                logger.warning("❌ No podcasts selected - exiting")
                return
            
            logger.info(f"✅ Selected {len(selected_podcasts)} podcasts")
            logger.info(f"📅 Looking back {configuration['lookback_days']} days")
            logger.info(f"🔧 Transcription mode: {configuration['transcription_mode']}")
            
            # Small delay to ensure clean transition
            await asyncio.sleep(1)
            
            # Create fetch callback for the loading screen
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
                    logger.error(f"Error in fetch callback: {e}", exc_info=True)
                    raise
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            
            # Stage 2: Fetch and select episodes
            logger.info("\n📺 STAGE 2: Episode Fetching & Selection")
            selected_episodes = self.selector.show_loading_screen_and_fetch(
                selected_podcasts, 
                configuration, 
                fetch_episodes_callback
            )
            
            logger.info(f"📋 Received {len(selected_episodes) if selected_episodes else 0} episodes from selector")
            
            if not selected_episodes:
                logger.warning("❌ No episodes selected for processing - exiting")
                return
            
            logger.info(f"✅ Selected {len(selected_episodes)} episodes for processing")
            
            # Validate episodes
            logger.info(f"🔍 Validating {len(selected_episodes)} episodes...")
            valid_episodes = self._validate_episodes(selected_episodes)
            if not valid_episodes:
                logger.error("❌ No valid episodes to process after validation")
                return
            
            logger.info(f"✅ {len(valid_episodes)} episodes passed validation")
            
            # Small delay to ensure clean server shutdown
            await asyncio.sleep(1.5)
            
            # Log first few episodes for debugging
            logger.info("📋 Episodes to process:")
            for i, ep in enumerate(valid_episodes[:3]):
                logger.info(f"  {i+1}. {ep.podcast}: {ep.title}")
                logger.info(f"     Audio URL: {ep.audio_url[:80] if ep.audio_url else 'None'}...")
            if len(valid_episodes) > 3:
                logger.info(f"  ... and {len(valid_episodes) - 3} more")
            
            # Stage 3: Process episodes
            logger.info("\n🎯 STAGE 3: Processing Episodes")
            logger.info(f"🚀 Starting to process {len(valid_episodes)} episodes...")
            logger.info("⏰ This may take several minutes depending on episode length...")
            
            try:
                summaries = await self._process_episodes(valid_episodes)
            except Exception as e:
                logger.error(f"❌ Error during episode processing: {e}", exc_info=True)
                summaries = []
            
            logger.info(f"\n📊 Processing Results:")
            logger.info(f"   Episodes selected: {len(valid_episodes)}")
            logger.info(f"   Summaries generated: {len(summaries)}")
            logger.info(f"   Success rate: {len(summaries)/len(valid_episodes)*100:.1f}%")
            
            # Stage 4: Send email digest
            if summaries:
                logger.info("\n📧 STAGE 4: Email Delivery")
                if self.email_digest.send_digest(summaries):
                    logger.info("✅ Renaissance Weekly digest sent successfully!")
                else:
                    logger.error("❌ Failed to send email digest")
            else:
                logger.warning("❌ No summaries generated - nothing to send")
            
            logger.info("\n✨ Renaissance Weekly pipeline completed!")
                
        except KeyboardInterrupt:
            logger.info("\n⚠️ Operation cancelled by user")
        except Exception as e:
            logger.error(f"\n❌ Unexpected error in main run: {e}", exc_info=True)
    
    def _validate_episodes(self, selected_episodes: List) -> List[Episode]:
        """Validate and convert episodes to Episode objects"""
        valid_episodes = []
        
        logger.info(f"🔍 Validating {len(selected_episodes)} episodes...")
        
        for i, ep in enumerate(selected_episodes):
            try:
                if isinstance(ep, Episode):
                    valid_episodes.append(ep)
                    logger.debug(f"  Episode {i+1}: Valid Episode object - {ep.title}")
                elif isinstance(ep, dict):
                    # Convert dict to Episode
                    logger.debug(f"  Episode {i+1}: Converting dict to Episode")
                    
                    # Ensure published date is a datetime object
                    published = ep.get('published')
                    if isinstance(published, str):
                        from dateutil import parser
                        published = parser.parse(published)
                    elif not isinstance(published, datetime):
                        published = datetime.now()
                    
                    episode_obj = Episode(
                        podcast=ep.get('podcast', 'Unknown'),
                        title=ep.get('title', 'Unknown'),
                        published=published,
                        audio_url=ep.get('audio_url'),
                        transcript_url=ep.get('transcript_url'),
                        description=ep.get('description'),
                        link=ep.get('link'),
                        duration=ep.get('duration', 'Unknown'),
                        guid=ep.get('guid')
                    )
                    valid_episodes.append(episode_obj)
                    logger.debug(f"  Episode {i+1}: Converted to Episode - {episode_obj.title}")
                else:
                    logger.warning(f"  Episode {i+1}: Unknown type {type(ep)} - skipping")
            except Exception as e:
                logger.error(f"  Episode {i+1}: Validation error - {e}", exc_info=True)
        
        logger.info(f"✅ Validation complete: {len(valid_episodes)}/{len(selected_episodes)} episodes valid")
        return valid_episodes
    
    async def _fetch_selected_episodes(self, podcast_names: List[str], days_back: int, 
                                      progress_callback: Callable) -> List[Episode]:
        """Fetch episodes for selected podcasts with progress updates"""
        all_episodes = []
        
        logger.info(f"📡 Starting to fetch episodes from {len(podcast_names)} podcasts...")
        
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
                logger.info(f"📻 Fetching episodes for {podcast_name}...")
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                
                if episodes:
                    all_episodes.extend(episodes)
                    logger.info(f"  ✅ {podcast_name}: Found {len(episodes)} episodes")
                    
                    # Save to database
                    for episode in episodes:
                        try:
                            self.db.save_episode(episode)
                        except Exception as e:
                            logger.debug(f"  Failed to cache episode: {e}")
                else:
                    logger.warning(f"  ⚠️ {podcast_name}: No episodes found")
                    
            except Exception as e:
                logger.error(f"  ❌ {podcast_name}: Failed to fetch episodes - {e}")
        
        logger.info(f"📊 Total episodes fetched: {len(all_episodes)}")
        return all_episodes
    
    async def _process_episodes(self, selected_episodes: List[Episode]) -> List[Dict]:
        """Process selected episodes concurrently with better error handling"""
        summaries = []
        
        logger.info(f"🔄 Starting concurrent processing of {len(selected_episodes)} episodes...")
        logger.info(f"⚙️  Max concurrent tasks: 3")
        
        # Ensure we have episodes to process
        if not selected_episodes:
            logger.error("❌ No episodes provided to process")
            return []
        
        async def process_with_semaphore(episode: Episode, semaphore: asyncio.Semaphore, index: int):
            """Process single episode with semaphore for concurrency control"""
            async with semaphore:
                try:
                    logger.info(f"\n🎯 [{index+1}/{len(selected_episodes)}] Starting: {episode.title[:50]}...")
                    
                    summary = await self.process_episode(episode)
                    
                    if summary:
                        logger.info(f"✅ [{index+1}/{len(selected_episodes)}] Success: {episode.title[:50]}...")
                        return {"episode": episode, "summary": summary}
                    else:
                        logger.warning(f"⚠️ [{index+1}/{len(selected_episodes)}] No summary: {episode.title[:50]}...")
                        return None
                        
                except Exception as e:
                    logger.error(f"❌ [{index+1}/{len(selected_episodes)}] Failed: {episode.title[:50]}... - {e}")
                    return None
        
        # Limit concurrent processing to avoid overwhelming resources
        semaphore = asyncio.Semaphore(3)
        
        # Create all tasks
        logger.info("📋 Creating processing tasks...")
        tasks = [
            process_with_semaphore(ep, semaphore, i)
            for i, ep in enumerate(selected_episodes)
        ]
        
        # Execute tasks and gather results
        logger.info("⚡ Executing tasks concurrently...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        logger.info("📊 Processing results...")
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Episode {i+1} processing failed with exception: {result}")
            elif isinstance(result, dict) and result:
                summaries.append(result)
            elif result is None:
                logger.debug(f"Episode {i+1} returned None")
        
        logger.info(f"✅ Processing complete: {len(summaries)}/{len(selected_episodes)} episodes succeeded")
        return summaries
    
    async def process_episode(self, episode: Episode) -> Optional[str]:
        """Process a single episode with comprehensive logging"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🎧 PROCESSING EPISODE:")
        logger.info(f"   Title: {episode.title}")
        logger.info(f"   Podcast: {episode.podcast}")
        logger.info(f"   Published: {episode.published.strftime('%Y-%m-%d')}")
        logger.info(f"   Duration: {episode.duration}")
        logger.info(f"   Audio URL: {'Yes' if episode.audio_url else 'No'}")
        logger.info(f"   Transcript URL: {'Yes' if episode.transcript_url else 'No'}")
        logger.info(f"{'='*60}")
        
        try:
            # Step 1: Try to find existing transcript
            logger.info("\n📄 Step 1: Checking for existing transcript...")
            transcript_text, transcript_source = await self.transcript_finder.find_transcript(episode)
            
            # Step 2: If no transcript found, transcribe from audio
            if not transcript_text:
                logger.info("\n🎵 Step 2: No transcript found - transcribing from audio...")
                
                # Check if we have audio URL
                if not episode.audio_url:
                    logger.error("❌ No audio URL available for this episode")
                    return None
                
                logger.info(f"🔗 Audio URL: {episode.audio_url[:80]}...")
                transcript_text = await self.transcriber.transcribe_episode(episode)
                
                if transcript_text:
                    transcript_source = TranscriptSource.GENERATED
                    logger.info("✅ Audio transcribed successfully")
                    logger.info(f"📏 Transcript length: {len(transcript_text)} characters")
                else:
                    logger.error("❌ Failed to transcribe audio")
                    return None
            else:
                logger.info(f"✅ Found existing transcript (source: {transcript_source.value})")
                logger.info(f"📏 Transcript length: {len(transcript_text)} characters")
            
            # Save transcript to database
            try:
                self.db.save_episode(episode, transcript_text, transcript_source)
                logger.info("💾 Transcript saved to database")
            except Exception as e:
                logger.warning(f"Failed to save transcript to database: {e}")
            
            # Step 3: Generate summary
            logger.info("\n📝 Step 3: Generating executive summary...")
            summary = await self.summarizer.generate_summary(episode, transcript_text, transcript_source)
            
            if summary:
                logger.info("✅ Summary generated successfully!")
                logger.info(f"📏 Summary length: {len(summary)} characters")
                # Save summary to database
                try:
                    self.db.save_episode(episode, transcript_text, transcript_source, summary)
                    logger.info("💾 Summary saved to database")
                except Exception as e:
                    logger.warning(f"Failed to save summary to database: {e}")
            else:
                logger.error("❌ Failed to generate summary")
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Error processing episode: {e}", exc_info=True)
            return None
        finally:
            logger.info(f"{'='*60}\n")
    
    async def check_single_podcast(self, podcast_name: str, days_back: int = 7):
        """Debug function to check a single podcast"""
        logger.info(f"\n🔍 DEBUG MODE: Checking single podcast '{podcast_name}'")
        
        # Find the podcast config
        podcast_config = None
        for config in PODCAST_CONFIGS:
            if config["name"].lower() == podcast_name.lower():
                podcast_config = config
                break
        
        if not podcast_config:
            logger.error(f"❌ Podcast '{podcast_name}' not found in configuration")
            logger.info("\n📋 Available podcasts:")
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
            logger.info(f"\n📻 Checking {podcast_name}...")
            
            try:
                # Fetch episodes using our methods
                episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
                
                # Verify against Apple if configured
                if VERIFY_APPLE_PODCASTS and podcast_config.get("apple_id"):
                    verification = await self.episode_fetcher.verify_against_apple_podcasts(
                        podcast_config, episodes, days_back
                    )
                    
                    # Optionally fetch missing episodes
                    if FETCH_MISSING_EPISODES and verification.get("missing_count", 0) > 0:
                        logger.info(f"  🔄 Fetching {verification['missing_count']} missing episodes from Apple...")
                        missing_episodes = await self.episode_fetcher.fetch_missing_from_apple(
                            podcast_config, episodes, verification
                        )
                        if missing_episodes:
                            episodes.extend(missing_episodes)
                            logger.info(f"  ✅ Added {len(missing_episodes)} missing episodes")
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
            json.dump({
                "verification_date": datetime.now().isoformat(),
                "days_back": days_back,
                "summary": {
                    "total_podcasts": len(PODCAST_CONFIGS),
                    "episodes_found": total_found,
                    "episodes_missing": total_missing
                },
                "details": report_data
            }, f, indent=2, default=str)
        logger.info(f"\n💾 Detailed report saved to: {report_file}")
    
    def _display_verification_report(self, report_data: List[Dict], total_found: int, total_missing: int):
        """Display verification report in a clean format"""
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
                    
                    if verification.get("apple_feed_url"):
                        logger.info(f"   Apple Feed: {verification['apple_feed_url']}")
            elif verification["status"] == "skipped":
                logger.info(f"\n⏭️  {podcast}")
                logger.info(f"   Found: {found} episodes")
                logger.info(f"   Verification: {verification['reason']}")
            else:
                logger.warning(f"\n❌ {podcast}")
                logger.warning(f"   Verification failed: {verification.get('reason', 'Unknown error')}")
                logger.info(f"   Found: {found} episodes (unverified)")
        
        logger.info("\n" + "="*80)
        logger.info(f"📈 TOTALS:")
        logger.info(f"   Episodes found: {total_found}")
        logger.info(f"   Episodes missing: {total_missing}")
        
        if total_found + total_missing > 0:
            success_rate = (total_found / (total_found + total_missing) * 100)
            logger.info(f"   Success rate: {success_rate:.1f}%")
        
        logger.info("="*80)
    
    async def cleanup(self):
        """Clean up resources"""
        try:
            # Clean up transcript finder session
            if hasattr(self.transcript_finder, 'cleanup'):
                await self.transcript_finder.cleanup()
            
            # Clean up any temporary files
            from .config import TEMP_DIR
            if TEMP_DIR.exists():
                for file in TEMP_DIR.glob("*"):
                    try:
                        file.unlink()
                    except:
                        pass
            
            logger.info("🧹 Cleanup completed")
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")