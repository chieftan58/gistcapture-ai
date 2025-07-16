#!/usr/bin/env python3
"""Test episode processing with cache"""

import sys
sys.path.append('.')

import logging
# Set up logging to see all messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.models import Episode
from datetime import datetime
import asyncio

print("=" * 80)
print("TESTING EPISODE PROCESSING WITH CACHE")
print("=" * 80)

async def test():
    app = RenaissanceWeekly()
    app.current_transcription_mode = 'full'
    
    # Create episode that exists in DB with full data
    episode = Episode(
        podcast="American Optimist",
        title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
        published=datetime.fromisoformat("2025-07-03T16:56:02"),
        audio_url="https://example.com/test.mp3",
        guid="1000715621905",
        duration="1h 30m"
    )
    
    print(f"\nProcessing episode that should be cached:")
    print(f"  {episode.podcast}: {episode.title[:60]}...")
    print(f"\nWatch for these log messages:")
    print(f"  1. 🔍 DIRECT CACHE CHECK")
    print(f"  2. 🎉 CACHE HIT")
    print(f"\n" + "-" * 80 + "\n")
    
    result = await app.process_episode(episode)
    
    print(f"\n" + "-" * 80)
    if result:
        if isinstance(result, dict):
            print(f"\n✅ Result returned (should be from cache):")
            print(f"  Full summary: {len(result.get('full_summary', ''))} chars")
            print(f"  Paragraph: {len(result.get('paragraph_summary', ''))} chars")
        else:
            print(f"\n✅ Got summary: {len(result)} chars")
    else:
        print(f"\n❌ No result returned")

# Run test
asyncio.run(test())

print("\n" + "=" * 80)
print("If you saw '🎉 CACHE HIT' in the logs above, the cache is working!")
print("If not, the episode was processed from scratch.")
print("=" * 80)