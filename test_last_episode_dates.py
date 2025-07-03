#!/usr/bin/env python3
"""Test script to verify last episode dates functionality"""

import asyncio
from datetime import datetime, timedelta
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.models import Episode

async def test_last_episode_dates():
    db = PodcastDatabase()
    
    # Create some test episodes
    test_podcasts = ["Test Podcast 1", "Test Podcast 2", "Test Podcast 3"]
    
    # Add episodes with different dates
    episodes = [
        Episode(
            guid="test-1-old",
            title="Old Episode",
            podcast="Test Podcast 1",
            published=datetime.now() - timedelta(days=30),
            link="https://example.com",
            audio_url="https://example.com/audio.mp3",
            duration="1:00:00"
        ),
        Episode(
            guid="test-2-recent",
            title="Recent Episode",
            podcast="Test Podcast 2",
            published=datetime.now() - timedelta(days=15),
            link="https://example.com",
            audio_url="https://example.com/audio.mp3",
            duration="1:00:00"
        ),
        # Test Podcast 3 has no episodes
    ]
    
    # Save episodes to database
    for episode in episodes:
        db.save_episode(episode)
    
    # Test the get_last_episode_dates method
    last_dates = db.get_last_episode_dates(test_podcasts)
    
    print("Last episode dates:")
    for podcast, date in last_dates.items():
        if date:
            days_ago = (datetime.now(date.tzinfo) - date).days
            print(f"  {podcast}: {days_ago} days ago ({date.strftime('%Y-%m-%d')})")
        else:
            print(f"  {podcast}: No episodes found")

if __name__ == "__main__":
    asyncio.run(test_last_episode_dates())