#!/usr/bin/env python3
"""Test episode with transcript but no summary - should trigger direct cache check"""

import sys
sys.path.append('.')

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.models import Episode
from datetime import datetime
import asyncio

print("=" * 80)
print("TESTING PARTIAL CACHE (Transcript but no Summary)")
print("=" * 80)

async def test():
    app = RenaissanceWeekly()
    app.current_transcription_mode = 'full'
    
    # Create episode that has transcript but no summary
    episode = Episode(
        podcast="All-In Podcast",
        title="E165: Nvidia's trillion-dollar problem, Apple's EU battle & more",
        published=datetime.now(),  # Date doesn't matter for our test
        audio_url="https://example.com/test.mp3",
        duration="1h"
    )
    
    print(f"\nProcessing episode with transcript but no summary:")
    print(f"  {episode.podcast}: {episode.title}")
    print(f"\nThis should trigger:")
    print(f"  1. 🔍 DIRECT CACHE CHECK")
    print(f"  2. 📝 PARTIAL CACHE HIT")
    print(f"\n" + "-" * 80 + "\n")
    
    # Only process enough to see if cache check works
    try:
        # We'll interrupt after seeing cache behavior
        result = await asyncio.wait_for(
            app.process_episode(episode), 
            timeout=5.0  # 5 seconds should be enough to see cache behavior
        )
    except asyncio.TimeoutError:
        print("\n(Timeout - this is expected for testing cache behavior)")
    except Exception as e:
        print(f"\nError (may be expected): {e}")

# Run test
try:
    asyncio.run(test())
except:
    pass

print("\n" + "=" * 80)
print("Check the logs above for:")
print("  🔍 DIRECT CACHE CHECK - Looking for existing data...")
print("  📝 PARTIAL CACHE HIT - Have transcript, need to generate summaries")
print("=" * 80)