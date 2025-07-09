#!/usr/bin/env python3
"""
Comprehensive test with all improvements
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.fetchers.audio_sources import AudioSourceFinder
from renaissance_weekly.fetchers.youtube_ytdlp_api import YtDlpSearcher
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

async def test_podcast_comprehensive(podcast_name: str):
    """Comprehensive test for a podcast"""
    logger.info(f"\n{'='*60}")
    logger.info(f"COMPREHENSIVE TEST: {podcast_name}")
    logger.info(f"{'='*60}")
    
    # Get config
    podcast_config = None
    for config in PODCAST_CONFIGS:
        if config['name'] == podcast_name:
            podcast_config = config
            break
    
    if not podcast_config:
        logger.error(f"No config for {podcast_name}")
        return False
    
    # 1. Fetch episodes
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    logger.info("\n1. FETCHING EPISODES...")
    episodes = await fetcher.fetch_episodes(podcast_config, days_back=7)
    
    if not episodes:
        logger.warning("No episodes found")
        return False
    
    episode = episodes[0]
    logger.info(f"Episode: {episode.title}")
    logger.info(f"Original URL: {episode.audio_url}")
    
    # 2. Test audio source finder
    logger.info("\n2. FINDING AUDIO SOURCES...")
    async with AudioSourceFinder() as finder:
        sources = await finder.find_all_audio_sources(episode, podcast_config)
        logger.info(f"Found {len(sources)} sources")
        for i, source in enumerate(sources):
            logger.info(f"  {i+1}. {source[:80]}...")
    
    # 3. Test YouTube search directly
    logger.info("\n3. TESTING YOUTUBE SEARCH...")
    queries = finder._build_youtube_queries(episode)
    logger.info(f"Queries: {queries}")
    
    for query in queries[:2]:
        logger.info(f"\nSearching: {query}")
        videos = await YtDlpSearcher.search_youtube(query, limit=3)
        for video in videos:
            logger.info(f"  - {video['title']}")
            logger.info(f"    Channel: {video['channel']}")
    
    # 4. Test specific solutions
    if podcast_name == "All-In":
        logger.info("\n4. TESTING MEGAPHONE FIX...")
        from renaissance_weekly.fetchers.platform_handlers import MegaphoneHandler
        fixed_url = await MegaphoneHandler.get_audio_url(episode.audio_url)
        if fixed_url:
            logger.info(f"✅ Fixed URL: {fixed_url[:80]}...")
        else:
            logger.info("❌ Could not fix Megaphone URL")
    
    elif podcast_name == "The Drive":
        logger.info("\n4. TESTING LIBSYN FIX...")
        from renaissance_weekly.fetchers.platform_handlers import LibsynHandler
        fixed_url = await LibsynHandler.get_audio_url(episode.audio_url)
        if fixed_url:
            logger.info(f"✅ Fixed URL: {fixed_url[:80]}...")
        else:
            logger.info("❌ Could not fix Libsyn URL")
    
    return len(sources) > 0

async def main():
    """Test all 4 problematic podcasts"""
    podcasts = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]
    
    results = {}
    for podcast in podcasts:
        try:
            success = await test_podcast_comprehensive(podcast)
            results[podcast] = success
        except Exception as e:
            logger.error(f"Error testing {podcast}: {e}")
            import traceback
            traceback.print_exc()
            results[podcast] = False
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    
    for podcast, success in results.items():
        status = "✅ Has sources" if success else "❌ No sources"
        logger.info(f"{podcast}: {status}")

if __name__ == "__main__":
    asyncio.run(main())