#!/usr/bin/env python3
"""
Debug audio source finding for the 4 problematic podcasts
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.models import Episode
from renaissance_weekly.fetchers.audio_sources import AudioSourceFinder
from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.utils.logging import get_logger
from datetime import datetime

logger = get_logger(__name__)

async def test_audio_finder():
    """Test audio source finder with retry strategies"""
    
    # Create test episodes for each problematic podcast
    test_episodes = [
        Episode(
            podcast="All-In",
            title="Test Episode",
            published=datetime.now(),
            duration=60,
            audio_url="https://feeds.megaphone.fm/all-in-test.mp3",
            transcript_url=None,
            description="Test"
        ),
        Episode(
            podcast="American Optimist",
            title="Ep 118: Test Episode",
            published=datetime.now(),
            duration=60,
            audio_url="https://api.substack.com/feed/test.mp3",
            transcript_url=None,
            description="Test"
        ),
        Episode(
            podcast="Dwarkesh Podcast",
            title="Test Episode",
            published=datetime.now(),
            duration=60,
            audio_url="https://api.substack.com/feed/test.mp3",
            transcript_url=None,
            description="Test"
        ),
        Episode(
            podcast="The Drive",
            title="Test Episode",
            published=datetime.now(),
            duration=60,
            audio_url="https://peterattiadrive.libsyn.com/test.mp3",
            transcript_url=None,
            description="Test"
        )
    ]
    
    # Get podcast configs
    podcast_configs = {}
    for config in PODCAST_CONFIGS:
        podcast_configs[config['name']] = config
    
    # Test each episode
    async with AudioSourceFinder() as finder:
        for episode in test_episodes:
            logger.info(f"\n{'='*60}")
            logger.info(f"Testing: {episode.podcast}")
            logger.info(f"{'='*60}")
            
            podcast_config = podcast_configs.get(episode.podcast)
            if not podcast_config:
                logger.error(f"No config for {episode.podcast}")
                continue
            
            # Show retry strategy
            retry_strategy = podcast_config.get('retry_strategy', {})
            logger.info(f"Retry Strategy: {retry_strategy}")
            
            # Find all audio sources
            try:
                sources = await finder.find_all_audio_sources(episode, podcast_config)
                
                logger.info(f"\nFound {len(sources)} sources:")
                for i, source in enumerate(sources):
                    logger.info(f"  {i+1}. {source[:80]}...")
                    
                if not sources:
                    logger.warning("No sources found!")
            except Exception as e:
                logger.error(f"Error finding sources: {e}")
                import traceback
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_audio_finder())