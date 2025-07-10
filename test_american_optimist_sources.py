#!/usr/bin/env python3
"""Test what audio sources we can find for American Optimist"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.models import Episode
from renaissance_weekly.fetchers.audio_sources import AudioSourceFinder
from renaissance_weekly.fetchers.youtube_enhanced import YouTubeEnhancedFetcher
from renaissance_weekly.transcripts.audio_downloader import PlatformAudioDownloader
import yaml

async def test_sources():
    """Test finding audio sources for American Optimist"""
    
    # Load podcast config
    with open('podcasts.yaml', 'r') as f:
        podcasts = yaml.safe_load(f)
    
    # Find American Optimist config
    ao_config = None
    for podcast in podcasts['podcasts']:
        if podcast['name'] == 'American Optimist':
            ao_config = podcast
            break
    
    print(f"American Optimist config:")
    print(f"  RSS Feed: {ao_config.get('rss_feed')}")
    print(f"  Apple ID: {ao_config.get('apple_id')}")
    print(f"  Retry Strategy: {ao_config.get('retry_strategy')}")
    print()
    
    # Create test episode
    episode = Episode(
        podcast="American Optimist",
        title="Ep 118: Marc Andreessen on AI, Robotics & America's Future",
        published=datetime(2025, 1, 3, tzinfo=timezone.utc),
        duration=3600,
        audio_url="https://api.substack.com/feed/podcast/167438211/c0bcea42c2f887030be97d4c8d58c088",
        transcript_url=None,
        description="Marc Andreessen joins Joe Lonsdale to discuss AI and robotics",
        apple_podcast_id=ao_config.get('apple_id')
    )
    
    print(f"Test Episode: {episode.title}")
    print(f"RSS Audio URL: {episode.audio_url}")
    print()
    
    # Test 1: Find all audio sources
    print("=== Testing AudioSourceFinder ===")
    async with AudioSourceFinder() as finder:
        sources = await finder.find_all_audio_sources(episode, ao_config)
        print(f"Found {len(sources)} audio sources:")
        for i, source in enumerate(sources, 1):
            print(f"  {i}. {source[:100]}...")
    print()
    
    # Test 2: YouTube search
    print("=== Testing YouTube Enhanced Fetcher ===")
    async with YouTubeEnhancedFetcher() as yt_fetcher:
        youtube_url = await yt_fetcher.find_episode_on_youtube(episode)
        if youtube_url:
            print(f"Found YouTube URL: {youtube_url}")
        else:
            print("No YouTube URL found")
    print()
    
    # Test 3: Test downloading from each source
    print("=== Testing Downloads ===")
    downloader = PlatformAudioDownloader()
    
    # Test RSS URL
    print("1. Testing RSS URL download:")
    test_file = Path("/tmp/test_rss.mp3")
    if test_file.exists():
        test_file.unlink()
    
    success = downloader.download_audio(episode.audio_url, test_file, "American Optimist")
    print(f"   RSS download: {'SUCCESS' if success else 'FAILED'}")
    if success:
        print(f"   File size: {test_file.stat().st_size / 1024 / 1024:.1f} MB")
        test_file.unlink()
    print()
    
    # Test Apple Podcasts lookup
    print("2. Testing Apple Podcasts API:")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        url = "https://itunes.apple.com/lookup"
        params = {
            'id': ao_config.get('apple_id'),
            'entity': 'podcastEpisode',
            'limit': 5
        }
        
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                episodes = data.get('results', [])[1:]  # Skip first (podcast info)
                print(f"   Found {len(episodes)} recent episodes")
                for ep in episodes[:3]:
                    print(f"   - {ep.get('trackName', 'No title')}")
                    print(f"     Audio URL: {ep.get('episodeUrl', 'NO URL')[:80]}...")
            else:
                print(f"   API Error: {response.status}")

if __name__ == "__main__":
    asyncio.run(test_sources())