"""Main application class for Renaissance Weekly"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional, Dict
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
    """Main application class"""
    
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
        """Main execution function"""
        logger.info("🚀 Starting Renaissance Weekly System...")
        logger.info(f"📧 Email delivery: {EMAIL_FROM} → {EMAIL_TO}")
        logger.info(f"📅 Looking back {days_back} days")
        
        if TESTING_MODE:
            logger.info(f"🧪 TESTING MODE: Limited to {MAX_TRANSCRIPTION_MINUTES} min transcriptions")
        
        # Fetch episodes
        all_episodes = await self._fetch_all_episodes(days_back)
        
        if not all_episodes:
            logger.error("❌ No recent episodes found")
            return
        
        logger.info(f"✅ Found {len(all_episodes)} total episodes")
        
        # Episode selection
        selected_episodes = self.selector.run_selection_server(all_episodes)
        
        if not selected_episodes:
            logger.warning("❌ No episodes selected")
            return
        
        logger.info(f"🎯 Processing {len(selected_episodes)} selected episodes...")
        
        # Process episodes
        summaries = await self._process_episodes(selected_episodes)
        
        logger.info(f"✅ Successfully processed {len(summaries)}/{len(selected_episodes)} episodes")
        
        # Send email digest
        if summaries:
            if self.email_digest.send_digest(summaries):
                logger.info("📧 Renaissance Weekly digest sent!")
            else:
                logger.error("❌ Failed to send email")
        else:
            logger.warning("❌ No summaries generated - nothing to send")
    
    async def _fetch_all_episodes(self, days_back: int) -> List[Episode]:
        """Fetch episodes from all configured podcasts"""
        all_episodes = []
        verification_results = {}
        podcast_episodes_map = {}
        
        for podcast_config in PODCAST_CONFIGS:
            episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
            podcast_episodes_map[podcast_config["name"]] = episodes
            all_episodes.extend(episodes)
            
            # Verify against Apple Podcasts
            if VERIFY_APPLE_PODCASTS:
                verification = await self.episode_fetcher.verify_against_apple_podcasts(
                    podcast_config, episodes, days_back
                )
                verification_results[podcast_config["name"]] = verification
        
        # Fetch missing episodes
        if FETCH_MISSING_EPISODES and verification_results:
            all_episodes.extend(
                await self._fetch_missing_episodes(
                    podcast_episodes_map, verification_results
                )
            )
        
        # Display verification summary
        self._display_verification_summary(verification_results)
        
        return all_episodes
    
    async def _fetch_missing_episodes(
        self, 
        podcast_episodes_map: Dict[str, List[Episode]], 
        verification_results: Dict[str, Dict]
    ) -> List[Episode]:
        """Fetch missing episodes identified by verification"""
        logger.info("\n🔄 Attempting to fetch missing episodes...")
        additional_episodes = []
        
        for podcast_config in PODCAST_CONFIGS:
            podcast_name = podcast_config["name"]
            if podcast_name in verification_results:
                result = verification_results[podcast_name]
                if result["status"] == "success" and result["missing_count"] > 0:
                    existing = podcast_episodes_map[podcast_name]
                    additional = await self.episode_fetcher.fetch_missing_from_apple(
                        podcast_config, existing, result
                    )
                    if additional:
                        additional_episodes.extend(additional)
                        logger.info(f"   Added {len(additional)} episodes for {podcast_name}")
        
        return additional_episodes
    
    def _display_verification_summary(self, verification_results: Dict[str, Dict]):
        """Display Apple Podcasts verification summary"""
        if not verification_results:
            return
        
        logger.info("\n📱 Apple Podcasts Verification Summary:")
        total_missing = 0
        
        for podcast_name, result in verification_results.items():
            if result["status"] == "success" and result["missing_count"] > 0:
                logger.warning(f"   {podcast_name}: Missing {result['missing_count']} episodes")
                total_missing += result["missing_count"]
            elif result["status"] == "error":
                logger.debug(f"   {podcast_name}: Verification failed - {result['reason']}")
        
        if total_missing > 0:
            logger.warning(f"\n⚠️  Total missing episodes across all podcasts: {total_missing}")
            if not FETCH_MISSING_EPISODES:
                logger.info("💡 Set FETCH_MISSING_EPISODES=true to automatically fetch missing episodes")
    
    async def _process_episodes(self, selected_episodes: List[Episode]) -> List[Dict]:
        """Process selected episodes concurrently"""
        summaries = []
        
        async def process_with_semaphore(episode, semaphore):
            async with semaphore:
                summary = await self.process_episode(episode)
                return {"episode": episode, "summary": summary}
        
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
        
        tasks = [
            process_with_semaphore(
                Episode(**ep) if isinstance(ep, dict) else ep, 
                semaphore
            )
            for ep in selected_episodes
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Episode processing failed: {result}")
            elif isinstance(result, dict) and result["summary"]:
                summaries.append(result)
        
        return summaries
    
    async def process_episode(self, episode: Episode) -> Optional[str]:
        """Process a single episode - find transcript or transcribe, then summarize"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🎧 Processing: {episode.title}")
        logger.info(f"📅 Published: {episode.published.strftime('%Y-%m-%d')}")
        logger.info(f"🎙️  Podcast: {episode.podcast}")
        logger.info(f"{'='*60}")
        
        # Step 1: Try to find existing transcript
        transcript_text, transcript_source = await self.transcript_finder.find_transcript(episode)
        
        # Step 2: If no transcript found, transcribe from audio
        if not transcript_text:
            logger.info("📥 No transcript found - downloading audio for transcription...")
            transcript_text = await self.transcriber.transcribe_episode(episode)
            
            if transcript_text:
                transcript_source = TranscriptSource.GENERATED
            else:
                logger.error("❌ Failed to transcribe audio")
                return None
        
        # Save transcript to database
        self.db.save_episode(episode, transcript_text)
        
        # Step 3: Generate summary
        logger.info("📝 Generating executive summary...")
        summary = await self.summarizer.generate_summary(episode, transcript_text, transcript_source)
        
        if summary:
            logger.info("✅ Episode processed successfully!")
        else:
            logger.error("❌ Failed to generate summary")
        
        return summary
    
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