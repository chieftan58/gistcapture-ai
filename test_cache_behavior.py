#!/usr/bin/env python3
"""Test the new cache behavior in process_episode"""

import sys
sys.path.append('.')

import asyncio
from datetime import datetime
from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.models import Episode

print("=" * 80)
print("TESTING DIRECT CACHE CHECK IN PROCESS_EPISODE")
print("=" * 80)

async def test_cache():
    # Initialize app
    app = RenaissanceWeekly()
    app.current_transcription_mode = 'full'
    # Set correlation_id for logging
    app.correlation_id = "cache-test"
    
    # Create an episode that we know exists in the database
    # From our verification script, we know this exists:
    # American Optimist: Ep 118: Marc Andreessen... (full mode, 47k transcript)
    episode = Episode(
        podcast="American Optimist",
        title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
        published=datetime.fromisoformat("2025-07-03T16:56:02"),
        audio_url="https://example.com/test.mp3",
        guid="1000715621905"
    )
    
    print(f"\nTesting with episode:")
    print(f"  Podcast: {episode.podcast}")
    print(f"  Title: {episode.title[:60]}...")
    print(f"  GUID: {episode.guid}")
    print(f"  Mode: {app.current_transcription_mode}")
    print(f"\nProcessing episode...\n")
    
    # Process the episode - should hit cache
    try:
        result = await app.process_episode(episode)
        if result:
            if isinstance(result, dict):
                print(f"\n✅ SUCCESS! Got result with:")
                print(f"   Full summary: {len(result.get('full_summary', '')) if result.get('full_summary') else 0} chars")
                print(f"   Paragraph: {len(result.get('paragraph_summary', '')) if result.get('paragraph_summary') else 0} chars")
            else:
                print(f"\n✅ SUCCESS! Got summary: {len(result)} chars")
        else:
            print("\n❌ FAILED: Got None result")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Now test with an episode that doesn't exist
    print("\n" + "=" * 80)
    print("Testing with non-existent episode...\n")
    
    fake_episode = Episode(
        podcast="Test Podcast",
        title="This Episode Does Not Exist in Database",
        published=datetime.now(),
        audio_url="https://example.com/fake.mp3",
        guid="fake-guid-12345"
    )
    
    print(f"  Podcast: {fake_episode.podcast}")
    print(f"  Title: {fake_episode.title}")
    print(f"\nThis should show CACHE MISS in logs...\n")
    
    # Just check the cache behavior, don't actually process
    # We'll look at the logs to see if it shows "CACHE MISS"
    
    print("\nCheck the logs above for:")
    print("1. 🔍 DIRECT CACHE CHECK messages")
    print("2. 📊 CACHE RESULT showing transcript/summary lengths")
    print("3. 🎉 CACHE HIT or ❌ CACHE MISS messages")
    print("\nIf you see 'CACHE HIT' for the first episode, the fix is working!")

# Run the test
if __name__ == "__main__":
    asyncio.run(test_cache())