#!/usr/bin/env python3
"""
Simple test for the 4 problematic podcasts
"""

import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

# The 4 problematic podcasts
PROBLEM_PODCASTS = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]

async def test_single_podcast(podcast_name: str):
    """Test a single podcast"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing: {podcast_name}")
    logger.info(f"{'='*60}")
    
    # Find podcast config
    podcast_config = None
    for config in PODCAST_CONFIGS:
        if config['name'] == podcast_name:
            podcast_config = config
            break
    
    if not podcast_config:
        logger.error(f"Config not found for {podcast_name}")
        return False
    
    # Show retry strategy
    retry_strategy = podcast_config.get('retry_strategy', {})
    if retry_strategy:
        logger.info(f"Retry Strategy:")
        logger.info(f"  Primary: {retry_strategy.get('primary', 'default')}")
        logger.info(f"  Fallback: {retry_strategy.get('fallback', 'none')}")
        logger.info(f"  Skip RSS: {retry_strategy.get('skip_rss', False)}")
        logger.info(f"  Force Apple: {retry_strategy.get('force_apple', False)}")
    
    # Fetch episodes
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    logger.info(f"\n1. Fetching episodes...")
    episodes = await fetcher.fetch_episodes(podcast_config, days_back=7)
    
    if not episodes:
        logger.warning(f"No episodes found for {podcast_name}")
        return False
    
    logger.info(f"Found {len(episodes)} episodes")
    episode = episodes[0]
    logger.info(f"First episode: {episode.title}")
    logger.info(f"Audio URL: {episode.audio_url[:80] if episode.audio_url else 'None'}...")
    
    # Test download with DownloadManager
    logger.info(f"\n2. Testing download...")
    download_manager = DownloadManager(concurrency=1)
    
    # Create podcast configs dict
    podcast_configs = {podcast_name: podcast_config}
    
    # Download the episode
    result = await download_manager.download_episodes([episode], podcast_configs)
    
    success = result['downloaded'] > 0
    
    if success:
        logger.info(f"✅ SUCCESS: Downloaded {episode.title}")
        # Show which strategy worked
        ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        if ep_id in result['episodeDetails']:
            details = result['episodeDetails'][ep_id]
            for attempt in details['attempts']:
                if attempt['success']:
                    logger.info(f"   Strategy: {attempt['strategy']}")
                    logger.info(f"   URL: {attempt['url'][:80]}...")
                    break
    else:
        logger.error(f"❌ FAILED: Could not download {episode.title}")
        # Show what was tried
        ep_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        if ep_id in result['episodeDetails']:
            details = result['episodeDetails'][ep_id]
            logger.error(f"   Attempts:")
            for attempt in details['attempts']:
                logger.error(f"     - {attempt['strategy']}: {attempt.get('error', 'Unknown error')}")
    
    return success

async def main():
    """Test all 4 problematic podcasts"""
    logger.info("Testing 4 Problematic Podcasts")
    logger.info("="*60)
    
    results = {}
    
    for podcast in PROBLEM_PODCASTS:
        try:
            success = await test_single_podcast(podcast)
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
        status = "✅ SUCCESS" if success else "❌ FAILED"
        logger.info(f"{podcast}: {status}")
    
    success_count = sum(1 for s in results.values() if s)
    logger.info(f"\nTotal: {success_count}/4 successful")
    
    # Recommendations
    if success_count < 4:
        logger.info(f"\n{'='*60}")
        logger.info("RECOMMENDATIONS")
        logger.info(f"{'='*60}")
        
        if not results.get("All-In"):
            logger.info("All-In:")
            logger.info("  - Issue: Megaphone CDN may be blocking or rate limiting")
            logger.info("  - Fix: Ensure Apple Podcasts is tried first (already configured)")
            logger.info("  - Alternative: Add custom headers for Megaphone")
        
        if not results.get("American Optimist"):
            logger.info("American Optimist:")
            logger.info("  - Issue: Substack RSS with Cloudflare protection")
            logger.info("  - Fix: YouTube search should work (Joe Lonsdale's channel)")
            logger.info("  - Check: Ensure skip_rss is being honored")
        
        if not results.get("Dwarkesh Podcast"):
            logger.info("Dwarkesh Podcast:")
            logger.info("  - Issue: Substack RSS with Cloudflare protection")
            logger.info("  - Fix: YouTube should be primary source")
            logger.info("  - Check: May need better YouTube query matching")
        
        if not results.get("The Drive"):
            logger.info("The Drive:")
            logger.info("  - Issue: Libsyn may require authentication")
            logger.info("  - Fix: Apple Podcasts should work as primary")
            logger.info("  - Alternative: Try extended timeout")

if __name__ == "__main__":
    # Set environment to avoid rate limiting
    os.environ['TESTING_MODE'] = 'true'
    asyncio.run(main())