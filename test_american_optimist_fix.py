#!/usr/bin/env python3
"""Test script to verify American Optimist YouTube search and download fixes"""

import asyncio
from datetime import datetime, timezone
from renaissance_weekly.models import Episode
from renaissance_weekly.fetchers.youtube_enhanced import YouTubeEnhancedFetcher
from renaissance_weekly.transcripts.audio_downloader import PlatformAudioDownloader
from pathlib import Path


async def test_american_optimist_youtube_search():
    """Test the enhanced YouTube search for American Optimist"""
    
    # Create a test episode - the Marc Andreessen one
    episode = Episode(
        podcast="American Optimist",
        title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
        published=datetime(2025, 7, 3, tzinfo=timezone.utc),
        duration=0,
        audio_url="https://api.substack.com/feed/podcast/1231981/someid.mp3",  # This would normally fail
        transcript_url=None,
        description="Marc Andreessen joins Joe Lonsdale to discuss AI and robotics",
        guid="american-optimist-ep-118"
    )
    
    print(f"Testing YouTube search for: {episode.title}")
    print("=" * 80)
    
    # Check API key availability
    import os
    if os.getenv('YOUTUBE_API_KEY'):
        print("✅ YouTube API key is available (from Codespaces secrets)")
    else:
        print("⚠️  No YouTube API key found")
    
    # Test YouTube search
    async with YouTubeEnhancedFetcher() as yt_fetcher:
        youtube_url = await yt_fetcher.find_episode_on_youtube(episode)
        
        if youtube_url:
            print(f"✅ SUCCESS! Found YouTube URL: {youtube_url}")
            
            # Test if we can download from this URL
            print("\nTesting download capability...")
            downloader = PlatformAudioDownloader()
            test_output = Path("/tmp/american_optimist_test.mp3")
            
            if downloader.download_audio(youtube_url, test_output, "American Optimist"):
                print(f"✅ Download successful! File size: {test_output.stat().st_size / 1_000_000:.1f} MB")
                # Clean up test file
                test_output.unlink()
            else:
                print("❌ Download failed")
        else:
            print("❌ YouTube search failed - no URL found")
            print("\nTrying alternative search queries...")
            
            # Show what queries would be tried
            queries = [
                "American Optimist Ep 118 full episode",
                "Joe Lonsdale American Optimist Episode 118",
                "American Optimist Marc Andreessen full episode",
                "Joe Lonsdale Marc Andreessen interview"
            ]
            
            print("\nSearch queries that would be attempted:")
            for q in queries:
                print(f"  - {q}")


async def test_browser_fallback():
    """Test browser automation fallback"""
    print("\n\nTesting Browser Automation Fallback")
    print("=" * 80)
    
    try:
        from renaissance_weekly.transcripts.browser_downloader import BrowserDownloader, PLAYWRIGHT_AVAILABLE
        
        if PLAYWRIGHT_AVAILABLE:
            print("✅ Playwright is installed and available")
            print("   Browser automation would be used as fallback if YouTube fails")
        else:
            print("⚠️  Playwright not installed")
            print("   Run: playwright install chromium")
            print("   This is needed for Cloudflare bypass fallback")
    except ImportError as e:
        print(f"❌ Could not import BrowserDownloader: {e}")


if __name__ == "__main__":
    print("American Optimist Fix Test")
    print("=" * 80)
    print("This test verifies the YouTube-first, browser-fallback approach\n")
    
    # Run tests
    asyncio.run(test_american_optimist_youtube_search())
    asyncio.run(test_browser_fallback())
    
    print("\n\nSummary:")
    print("- YouTube search has been enhanced with episode number and guest name extraction")
    print("- Search queries are now shorter and more focused on finding full episodes")
    print("- Browser automation is available as fallback for Cloudflare-protected URLs")
    print("- American Optimist episodes should now have much higher success rate")