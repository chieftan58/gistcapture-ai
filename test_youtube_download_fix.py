#!/usr/bin/env python3
"""Test the YouTube download fixes for American Optimist, Dwarkesh, and The Drive"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from renaissance_weekly.models import Episode
from renaissance_weekly.download_manager import DownloadManager

async def test_youtube_downloads():
    """Test downloading problematic podcasts"""
    
    # Create test episodes
    test_episodes = [
        Episode(
            podcast="American Optimist",
            title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
            published=datetime(2025, 7, 3, tzinfo=timezone.utc),
            duration="1:30:00",
            audio_url="https://api.substack.com/feed/podcast/1231981/test.mp3",
            transcript_url=None,
            description="Test episode",
            guid="ao-test-118"
        ),
        Episode(
            podcast="Dwarkesh Podcast",
            title="Sarah C. M. Paine - WW2, Taiwan, Ukraine, & Maritime vs Continental Powers",
            published=datetime(2025, 7, 5, tzinfo=timezone.utc),
            duration="2:00:00",
            audio_url="https://api.substack.com/feed/podcast/dwarkesh/test.mp3",
            transcript_url=None,
            description="Test episode",
            guid="dp-test-001"
        ),
        Episode(
            podcast="The Drive",
            title="Rhonda Patrick, Ph.D.: longevity, optimal health, and aging insights",
            published=datetime(2025, 7, 4, tzinfo=timezone.utc),
            duration="2:30:00",
            audio_url="https://peterattia.com/podcast/test.mp3",
            transcript_url=None,
            description="Test episode",
            guid="td-test-001"
        )
    ]
    
    print("=" * 80)
    print("Testing YouTube Downloads for Problematic Podcasts")
    print("=" * 80)
    
    # Create download manager
    dm = DownloadManager()
    
    # Test each episode
    for episode in test_episodes:
        print(f"\n🎯 Testing {episode.podcast}: {episode.title[:50]}...")
        print("-" * 80)
        
        # Create a simple status object
        from renaissance_weekly.download_manager import EpisodeDownloadStatus
        status = EpisodeDownloadStatus(episode)
        
        # Try downloading
        audio_path = await dm._download_episode(episode, status)
        
        if audio_path:
            print(f"✅ SUCCESS! Downloaded to: {audio_path}")
            print(f"   File size: {audio_path.stat().st_size / 1_000_000:.1f} MB")
            # Clean up test file
            audio_path.unlink()
        else:
            print(f"❌ FAILED!")
            print(f"   Last error: {status.last_error}")
            print(f"   Attempts made: {len(status.attempts)}")
            for i, attempt in enumerate(status.attempts):
                print(f"   Attempt {i+1}: {attempt.strategy} - {attempt.error or 'Success'}")
    
    print("\n" + "=" * 80)
    print("Test Complete")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_youtube_downloads())