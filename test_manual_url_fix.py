#!/usr/bin/env python3
"""Test script to verify manual URL functionality fixes"""

import asyncio
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.models import Episode
from datetime import datetime

async def test_manual_url():
    """Test manual URL retry functionality"""
    print("Testing Manual URL Functionality Fixes")
    print("=" * 50)
    
    # Create a test episode
    test_episode = Episode(
        podcast="American Optimist",
        title="Ep 117: Dave Rubin on Free Speech",
        published=datetime.now(),
        duration="60:00",
        audio_url="https://failing-url.example.com/test.mp3",
        transcript_url=None,
        description="Test episode"
    )
    
    # Create download manager
    dm = DownloadManager(concurrency=1)
    
    print("1. Creating download task for test episode...")
    
    # Start download (will fail)
    download_task = asyncio.create_task(dm.download_episodes([test_episode]))
    
    # Wait a moment for it to fail
    await asyncio.sleep(2)
    
    print("2. Episode should have failed. Testing manual URL retry...")
    
    # Get episode ID
    ep_id = f"{test_episode.podcast}|{test_episode.title}|{test_episode.published}"
    
    # Add manual URL (using a YouTube URL that would work with yt-dlp)
    manual_url = "https://www.youtube.com/watch?v=w1FRqBOxS8g"
    print(f"3. Adding manual URL: {manual_url}")
    
    # Test the add_manual_url method
    dm.add_manual_url(ep_id, manual_url)
    
    # Wait for retry to process
    print("4. Waiting for retry to process...")
    await asyncio.sleep(5)
    
    # Check status
    status = dm.get_status()
    print(f"\n5. Final Status:")
    print(f"   Total: {status['total']}")
    print(f"   Downloaded: {status['downloaded']}")
    print(f"   Failed: {status['failed']}")
    print(f"   Retrying: {status['retrying']}")
    
    # Get episode details
    if ep_id in status['episodeDetails']:
        ep_status = status['episodeDetails'][ep_id]
        print(f"\n6. Episode Status: {ep_status['status']}")
        print(f"   Attempts: {ep_status['attemptCount']}")
        if ep_status['attempts']:
            print("   Last attempt:")
            last_attempt = ep_status['attempts'][-1]
            print(f"     Strategy: {last_attempt['strategy']}")
            print(f"     Success: {last_attempt['success']}")
            print(f"     Error: {last_attempt.get('error', 'None')}")
    
    # Cancel remaining tasks
    download_task.cancel()
    try:
        await download_task
    except asyncio.CancelledError:
        pass
    
    print("\n✅ Manual URL test completed!")
    print("If you see 'retrying' status and manual_url_retry strategy, the fix is working!")

if __name__ == "__main__":
    print("Manual URL Fix Test Script")
    print("This tests the fixes for UI not updating when manual URL is provided")
    print()
    
    # Run the test
    asyncio.run(test_manual_url())