#!/usr/bin/env python3
"""
Fix for the 4 problematic podcasts to ensure bulletproof downloads
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.models import Episode
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger
from datetime import datetime, timedelta

logger = get_logger(__name__)

# The 4 problematic podcasts
PROBLEM_PODCASTS = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]

async def test_podcast_download(podcast_name: str, days_back: int = 7):
    """Test downloading episodes for a specific podcast"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing {podcast_name}")
    logger.info(f"{'='*60}")
    
    # Find podcast config
    podcast_config = None
    for config in PODCAST_CONFIGS:
        if config['name'] == podcast_name:
            podcast_config = config
            break
    
    if not podcast_config:
        logger.error(f"Podcast {podcast_name} not found in configs")
        return False
    
    # Show retry strategy
    retry_strategy = podcast_config.get('retry_strategy', {})
    logger.info(f"Retry strategy: {retry_strategy}")
    
    # Fetch episodes
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    logger.info(f"\n1. Fetching episodes...")
    episodes = await fetcher.fetch_episodes(podcast_config, days_back)
    
    if not episodes:
        logger.warning(f"No episodes found for {podcast_name} in the last {days_back} days")
        return False
    
    logger.info(f"Found {len(episodes)} episodes")
    
    # Try downloading first episode
    episode = episodes[0]
    logger.info(f"\n2. Testing download for: {episode.title}")
    logger.info(f"   Audio URL: {episode.audio_url[:80] if episode.audio_url else 'None'}...")
    
    # Use download manager
    download_manager = DownloadManager(concurrency=1)
    
    # Pass podcast configs properly
    podcast_configs = {podcast_name: podcast_config}
    
    result = await download_manager.download_episodes([episode], podcast_configs)
    
    if result['downloaded'] > 0:
        logger.info(f"✅ Successfully downloaded episode!")
        logger.info(f"   Download details: {result['episodeDetails']}")
        return True
    else:
        logger.error(f"❌ Failed to download episode")
        logger.error(f"   Error details: {result['episodeDetails']}")
        return False

async def main():
    """Test all problematic podcasts"""
    logger.info("Testing problematic podcasts with enhanced retry strategies")
    logger.info("="*60)
    
    results = {}
    
    for podcast_name in PROBLEM_PODCASTS:
        try:
            success = await test_podcast_download(podcast_name, days_back=7)
            results[podcast_name] = success
        except Exception as e:
            logger.error(f"Error testing {podcast_name}: {e}")
            results[podcast_name] = False
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    
    for podcast, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        logger.info(f"{podcast}: {status}")
    
    success_count = sum(1 for s in results.values() if s)
    logger.info(f"\nTotal: {success_count}/{len(results)} successful")
    
    # Specific recommendations
    logger.info(f"\n{'='*60}")
    logger.info("RECOMMENDATIONS")
    logger.info(f"{'='*60}")
    
    if not results.get("All-In"):
        logger.info("All-In: Check if Megaphone CDN is having issues. Apple Podcasts should work.")
    
    if not results.get("American Optimist"):
        logger.info("American Optimist: Ensure Apple Podcasts API is being used (not Substack RSS)")
    
    if not results.get("Dwarkesh Podcast"):
        logger.info("Dwarkesh Podcast: Check YouTube availability. Episodes may be YouTube-only.")
    
    if not results.get("The Drive"):
        logger.info("The Drive: Libsyn may require authentication. Use Apple Podcasts.")

if __name__ == "__main__":
    asyncio.run(main())