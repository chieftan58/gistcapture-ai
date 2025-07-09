#!/usr/bin/env python3
"""
Trace the full download process for one problematic podcast
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.fetchers.audio_sources import AudioSourceFinder
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger

# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

logger = get_logger(__name__)

async def trace_american_optimist():
    """Trace American Optimist download process"""
    
    # Get config
    podcast_config = None
    for config in PODCAST_CONFIGS:
        if config['name'] == "American Optimist":
            podcast_config = config
            break
    
    logger.info("="*60)
    logger.info("AMERICAN OPTIMIST CONFIG:")
    logger.info(f"  Apple ID: {podcast_config.get('apple_id')}")
    logger.info(f"  Retry Strategy: {podcast_config.get('retry_strategy')}")
    logger.info("="*60)
    
    # 1. Fetch episode
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    logger.info("\n1. FETCHING EPISODES...")
    episodes = await fetcher.fetch_episodes(podcast_config, days_back=7)
    
    if not episodes:
        logger.error("No episodes found!")
        return
    
    episode = episodes[0]
    logger.info(f"Found episode: {episode.title}")
    logger.info(f"Audio URL: {episode.audio_url}")
    
    # 2. Find audio sources
    logger.info("\n2. FINDING AUDIO SOURCES...")
    async with AudioSourceFinder() as finder:
        sources = await finder.find_all_audio_sources(episode, podcast_config)
        
        logger.info(f"Found {len(sources)} sources:")
        for i, source in enumerate(sources):
            logger.info(f"  {i+1}. {source[:100]}...")
    
    # 3. Try download
    logger.info("\n3. ATTEMPTING DOWNLOAD...")
    download_manager = DownloadManager(concurrency=1)
    
    # This is the key - pass the config!
    podcast_configs = {"American Optimist": podcast_config}
    
    result = await download_manager.download_episodes([episode], podcast_configs)
    
    logger.info("\n4. RESULT:")
    logger.info(f"Downloaded: {result['downloaded']}")
    logger.info(f"Failed: {result['failed']}")
    
    # Show details
    ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
    if ep_id in result['episodeDetails']:
        details = result['episodeDetails'][ep_id]
        logger.info("\nAttempts:")
        for attempt in details['attempts']:
            logger.info(f"  Strategy: {attempt['strategy']}")
            logger.info(f"  URL: {attempt['url'][:80]}...")
            logger.info(f"  Success: {attempt['success']}")
            if not attempt['success']:
                logger.info(f"  Error: {attempt.get('error', 'Unknown')}")

if __name__ == "__main__":
    asyncio.run(trace_american_optimist())