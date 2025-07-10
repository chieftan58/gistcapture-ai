#!/usr/bin/env python3
"""
Deep investigation into American Optimist download options
Let's explore EVERY possible source
"""

import asyncio
import aiohttp
import json
import re
from urllib.parse import quote
import subprocess

async def investigate():
    print("AMERICAN OPTIMIST DEEP INVESTIGATION")
    print("=" * 80)
    
    # First, let's get the episode data from Apple
    apple_id = "1573141757"
    episode_title = "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance"
    
    print("\n1. APPLE PODCASTS INVESTIGATION")
    print("-" * 40)
    
    # Check Apple Podcasts web player
    apple_web_url = f"https://podcasts.apple.com/us/podcast/american-optimist/id{apple_id}"
    print(f"Apple Podcasts page: {apple_web_url}")
    
    # Get specific episode data
    async with aiohttp.ClientSession() as session:
        # Get episode details
        episode_api = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcastEpisode&limit=1"
        async with session.get(episode_api) as resp:
            text = await resp.text()
            data = json.loads(text)
            if len(data['results']) > 1:
                episode = data['results'][1]  # First episode (skip podcast info)
                print(f"\nEpisode from Apple API:")
                print(f"  Title: {episode['trackName']}")
                print(f"  Episode URL: {episode.get('episodeUrl', 'None')}")
                print(f"  Track ID: {episode.get('trackId')}")
                print(f"  Collection ID: {episode.get('collectionId')}")
                print(f"  Preview URL: {episode.get('previewUrl', 'None')}")
                print(f"  Episode File Extension: {episode.get('episodeFileExtension', 'None')}")
                
                # Check for any other URL fields
                for key, value in episode.items():
                    if 'url' in key.lower() and value:
                        print(f"  {key}: {value}")
    
    print("\n2. SPOTIFY INVESTIGATION")
    print("-" * 40)
    
    # Search Spotify (would need auth for full API)
    spotify_search = f"https://open.spotify.com/search/{quote('American Optimist Joe Lonsdale')}"
    print(f"Spotify search: {spotify_search}")
    
    # Check if American Optimist is on Spotify
    # Note: Full implementation would use Spotify API
    
    print("\n3. PODCAST INDEX INVESTIGATION")
    print("-" * 40)
    
    # Podcast Index is a free, open podcast directory
    # Check if they have alternative URLs
    pi_search = f"https://podcastindex.org/search?q={quote('American Optimist')}"
    print(f"Podcast Index search: {pi_search}")
    
    print("\n4. WEB PLAYER INVESTIGATION")
    print("-" * 40)
    
    # When you play on Apple Podcasts website, it must stream from somewhere
    # Let's check what happens when we load the episode page
    
    # This would need browser automation to capture network traffic
    print("Apple Podcasts web player likely uses a CDN that we can capture")
    print("Possible approaches:")
    print("  - Use browser DevTools to capture network requests")
    print("  - Use mitmproxy to intercept HTTPS traffic")
    print("  - Use Playwright to automate and capture requests")
    
    print("\n5. ALTERNATIVE PLATFORMS")
    print("-" * 40)
    
    platforms = [
        "Google Podcasts (podcasts.google.com)",
        "Stitcher",
        "Overcast", 
        "Pocket Casts",
        "Castro",
        "Podbean",
        "iHeartRadio",
        "TuneIn"
    ]
    
    for platform in platforms:
        print(f"  - Check {platform}")
    
    print("\n6. SUBSTACK API INVESTIGATION")
    print("-" * 40)
    
    # Substack might have API endpoints that bypass Cloudflare
    print("Possible Substack endpoints to try:")
    endpoints = [
        "https://americanoptimist.substack.com/api/v1/podcasts/1231981",
        "https://americanoptimist.substack.com/api/v1/podcast_episodes",
        "https://api.substack.com/feed/podcast/1231981.json",
        "https://americanoptimist.substack.com/feed.json"
    ]
    
    for endpoint in endpoints:
        print(f"  - {endpoint}")
    
    print("\n7. DIRECT CDN DISCOVERY")
    print("-" * 40)
    
    # Apple Podcasts must serve audio from somewhere
    # Common podcast CDNs that Apple might use:
    cdns = [
        "podcasts.apple.com/cdn",
        "audiocdn.apple.com",
        "is1-ssl.mzstatic.com",  # Apple's CDN
        "is2-ssl.mzstatic.com",
        "is3-ssl.mzstatic.com",
        "is4-ssl.mzstatic.com",
        "is5-ssl.mzstatic.com"
    ]
    
    print("Apple likely serves audio from one of these domains")
    for cdn in cdns:
        print(f"  - {cdn}")
    
    print("\n8. YOUTUBE COOKIE SOLUTION")
    print("-" * 40)
    
    print("yt-dlp with browser cookies might work:")
    browsers = ['firefox', 'chrome', 'safari', 'edge']
    for browser in browsers:
        cmd = f"yt-dlp --cookies-from-browser {browser} [URL]"
        print(f"  - {cmd}")
    
    print("\n9. RSS FEED AT DIFFERENT TIMES")
    print("-" * 40)
    
    print("RSS feeds sometimes have different URLs at different times:")
    print("  - Try accessing RSS feed with different User-Agents")
    print("  - Try accessing from different IP addresses")
    print("  - Check if RSS has enclosure URLs that change")
    
    print("\n10. ARCHIVE.ORG")
    print("-" * 40)
    
    archive_search = f"https://archive.org/search.php?query={quote('American Optimist Joe Lonsdale')}"
    print(f"Archive.org search: {archive_search}")

async def test_apple_cdn_theory():
    """Test if we can find Apple's actual CDN"""
    print("\n\nTESTING APPLE CDN THEORY")
    print("=" * 80)
    
    # Apple episode URL pattern investigation
    # Based on other Apple Podcasts, the pattern might be:
    # https://[number]-ssl.mzstatic.com/path/to/episode.mp3
    
    episode_id = "1000715621905"  # Episode 118's track ID
    
    # Try various Apple CDN patterns
    patterns = [
        f"https://is1-ssl.mzstatic.com/us/r1000/0/Music/v4/podcast/{episode_id}.mp3",
        f"https://is2-ssl.mzstatic.com/podcast/episode/{episode_id}.mp3",
        f"https://audio-ssl.itunes.apple.com/podcast/{episode_id}.mp3",
        f"https://podcasts.apple.com/stream/{episode_id}",
        f"https://play.podtrac.com/american-optimist/{episode_id}.mp3"
    ]
    
    print("Testing potential Apple CDN URLs:")
    async with aiohttp.ClientSession() as session:
        for url in patterns:
            try:
                async with session.head(url, timeout=5) as resp:
                    print(f"  {url[:50]}... -> {resp.status}")
            except:
                print(f"  {url[:50]}... -> Failed")

async def check_yt_dlp_extractors():
    """Check what extractors yt-dlp has"""
    print("\n\nYT-DLP EXTRACTOR CHECK")
    print("=" * 80)
    
    # Check if yt-dlp has Apple Podcasts or Substack extractors
    try:
        result = subprocess.run(
            ['python', '-m', 'yt_dlp', '--list-extractors'],
            capture_output=True,
            text=True
        )
        
        extractors = result.stdout.lower()
        relevant = ['apple', 'podcast', 'substack', 'spotify']
        
        print("Relevant extractors:")
        for term in relevant:
            if term in extractors:
                lines = [l for l in result.stdout.split('\n') if term in l.lower()]
                for line in lines:
                    print(f"  - {line}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(investigate())
    asyncio.run(test_apple_cdn_theory())
    asyncio.run(check_yt_dlp_extractors())