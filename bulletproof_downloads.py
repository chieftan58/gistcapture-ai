#!/usr/bin/env python3
"""
Bulletproof download strategies for problematic podcasts
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

# Enhanced configurations for bulletproof downloads
BULLETPROOF_CONFIGS = {
    "All-In": {
        "retry_strategy": {
            "primary": "apple_podcasts",
            "fallback": "youtube_search",
            "youtube_channel": "UCESLZhusAkFfsNsApnjF_Cg",
            "extended_timeout": True
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "audio/mpeg,audio/*;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache"
        }
    },
    "American Optimist": {
        "retry_strategy": {
            "primary": "youtube_search",
            "fallback": "apple_podcasts",
            "skip_rss": True,
            "force_apple": True,
            "youtube_queries": [
                'Joe Lonsdale American Optimist',
                'American Optimist podcast Joe Lonsdale',
                'Joe Lonsdale interview'
            ]
        }
    },
    "Dwarkesh Podcast": {
        "retry_strategy": {
            "primary": "youtube_search",
            "fallback": "apple_podcasts",
            "skip_rss": True,
            "youtube_channel": "UCCaEbmz8gvyJHXFR42uSbXQ",
            "youtube_queries": [
                'Dwarkesh Patel',
                'Dwarkesh Podcast',
                'Dwarkesh interview'
            ]
        }
    },
    "The Drive": {
        "retry_strategy": {
            "primary": "apple_podcasts",
            "fallback": "cdn_alternatives",
            "extended_timeout": True,
            "force_apple": True
        },
        "headers": {
            "User-Agent": "Apple Podcasts/1.0",
            "Accept": "*/*"
        }
    }
}

async def test_bulletproof_download(podcast_name: str, days_back: int = 7):
    """Test bulletproof download strategy for a podcast"""
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing bulletproof download for {podcast_name}")
    logger.info(f"{'='*60}")
    
    # Find base podcast config
    base_config = None
    for config in PODCAST_CONFIGS:
        if config['name'] == podcast_name:
            base_config = config.copy()
            break
    
    if not base_config:
        logger.error(f"Podcast {podcast_name} not found")
        return False
    
    # Apply bulletproof enhancements
    if podcast_name in BULLETPROOF_CONFIGS:
        enhancements = BULLETPROOF_CONFIGS[podcast_name]
        base_config.update(enhancements)
        logger.info(f"Applied bulletproof enhancements: {enhancements}")
    
    # Fetch episodes
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    logger.info(f"\n1. Fetching episodes...")
    episodes = await fetcher.fetch_episodes(base_config, days_back)
    
    if not episodes:
        logger.warning(f"No episodes found in the last {days_back} days")
        return False
    
    logger.info(f"Found {len(episodes)} episodes")
    
    # Test download with enhanced config
    episode = episodes[0]
    logger.info(f"\n2. Testing download for: {episode.title}")
    
    # Create download manager with enhanced settings
    download_manager = DownloadManager(
        concurrency=1,
        progress_callback=lambda status: logger.info(f"Progress: {status}")
    )
    
    # Pass enhanced config
    podcast_configs = {podcast_name: base_config}
    
    result = await download_manager.download_episodes([episode], podcast_configs)
    
    if result['downloaded'] > 0:
        logger.info(f"✅ Successfully downloaded!")
        
        # Show successful strategy
        episode_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        if episode_id in result['episodeDetails']:
            details = result['episodeDetails'][episode_id]
            successful_attempt = next((a for a in details['attempts'] if a['success']), None)
            if successful_attempt:
                logger.info(f"   Strategy used: {successful_attempt['strategy']}")
                logger.info(f"   URL: {successful_attempt['url'][:80]}...")
        
        return True
    else:
        logger.error(f"❌ Failed to download")
        
        # Show attempted strategies
        episode_id = f"{episode.podcast}|{episode.title}|{episode.published}"
        if episode_id in result['episodeDetails']:
            details = result['episodeDetails'][episode_id]
            logger.error(f"   Attempted strategies:")
            for attempt in details['attempts']:
                logger.error(f"     - {attempt['strategy']}: {attempt.get('error', 'Unknown error')}")
        
        return False

async def test_all_problematic():
    """Test all problematic podcasts with bulletproof strategies"""
    problematic = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]
    
    results = {}
    for podcast in problematic:
        try:
            success = await test_bulletproof_download(podcast)
            results[podcast] = success
        except Exception as e:
            logger.error(f"Error testing {podcast}: {e}")
            results[podcast] = False
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("BULLETPROOF DOWNLOAD RESULTS")
    logger.info(f"{'='*60}")
    
    for podcast, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        logger.info(f"{podcast}: {status}")
    
    success_count = sum(1 for s in results.values() if s)
    logger.info(f"\nTotal: {success_count}/{len(results)} successful")
    
    # Specific recommendations for failures
    if not all(results.values()):
        logger.info(f"\n{'='*60}")
        logger.info("NEXT STEPS FOR FAILURES")
        logger.info(f"{'='*60}")
        
        if not results.get("All-In"):
            logger.info("All-In: Consider implementing Megaphone-specific headers or use browser automation")
        
        if not results.get("American Optimist"):
            logger.info("American Optimist: Enhance YouTube search with better guest name extraction")
        
        if not results.get("Dwarkesh Podcast"):
            logger.info("Dwarkesh Podcast: Check if episodes are YouTube-exclusive")
        
        if not results.get("The Drive"):
            logger.info("The Drive: May need authenticated Libsyn API access")

if __name__ == "__main__":
    asyncio.run(test_all_problematic())