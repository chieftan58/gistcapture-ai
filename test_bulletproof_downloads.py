#!/usr/bin/env python3
"""
Test bulletproof download implementation
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

async def test_downloads():
    """Test downloading the 4 problematic podcasts"""
    
    # The 4 problematic podcasts
    test_podcasts = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]
    
    # Get configs for these podcasts
    podcast_configs_map = {}
    for config in PODCAST_CONFIGS:
        if config['name'] in test_podcasts:
            podcast_configs_map[config['name']] = config
    
    # Fetch episodes
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    all_episodes = []
    for podcast_name in test_podcasts:
        config = podcast_configs_map[podcast_name]
        logger.info(f"\nFetching episodes for {podcast_name}...")
        episodes = await fetcher.fetch_episodes(config, days_back=7)
        
        if episodes:
            # Take only the first episode for testing
            episode = episodes[0]
            all_episodes.append(episode)
            logger.info(f"✅ Found episode: {episode.title}")
        else:
            logger.warning(f"❌ No episodes found for {podcast_name}")
    
    if not all_episodes:
        logger.error("No episodes to download!")
        return
    
    # Test downloads with bulletproof strategy
    logger.info(f"\n{'='*60}")
    logger.info("TESTING BULLETPROOF DOWNLOADS")
    logger.info(f"{'='*60}")
    
    # Progress callback
    def progress_callback(status):
        logger.info(f"Progress: {status['downloaded']}/{status['total']} downloaded, {status['failed']} failed")
    
    # Create download manager
    manager = DownloadManager(concurrency=4, progress_callback=progress_callback)
    
    # Download episodes
    result = await manager.download_episodes(all_episodes, podcast_configs_map)
    
    # Show results
    logger.info(f"\n{'='*60}")
    logger.info("DOWNLOAD RESULTS")
    logger.info(f"{'='*60}")
    
    for ep_id, status in result['episodeDetails'].items():
        podcast, title, _ = ep_id.split('|')
        logger.info(f"\n{podcast}: {title[:50]}...")
        logger.info(f"  Status: {status['status']}")
        logger.info(f"  Attempts: {status['attemptCount']}")
        
        if status['status'] == 'success':
            logger.info("  ✅ SUCCESS!")
        else:
            logger.info(f"  ❌ FAILED: {status['lastError']}")
            
        # Show attempts
        for attempt in status['attempts']:
            logger.info(f"    - {attempt['strategy']}: {'✅' if attempt['success'] else '❌'} {attempt['error'] or 'Success'}")
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total: {result['total']}")
    logger.info(f"Downloaded: {result['downloaded']}")
    logger.info(f"Failed: {result['failed']}")
    
    success_rate = (result['downloaded'] / result['total'] * 100) if result['total'] > 0 else 0
    logger.info(f"Success Rate: {success_rate:.1f}%")

if __name__ == "__main__":
    asyncio.run(test_downloads())