#!/usr/bin/env python3
"""Search for American Optimist episodes on alternative hosting platforms"""

import asyncio
import aiohttp
from urllib.parse import quote
import re

async def search_alternative_hosts():
    print("SEARCHING FOR AMERICAN OPTIMIST ON ALTERNATIVE HOSTS")
    print("=" * 80)
    
    episode_title = "Marc Andreessen AI Robotics America Industrial Renaissance"
    
    async with aiohttp.ClientSession() as session:
        # 1. Search on Podcast databases/aggregators
        print("\n1. PODCAST AGGREGATORS")
        print("-" * 40)
        
        # Listen Notes API (podcast search engine)
        print("Listen Notes - Major podcast search engine")
        listen_notes_url = f"https://www.listennotes.com/search/?q={quote('American Optimist Marc Andreessen')}"
        print(f"Search: {listen_notes_url}")
        
        # Podchaser
        print("\nPodchaser - Podcast database")
        podchaser_url = f"https://www.podchaser.com/search?q={quote('American Optimist')}"
        print(f"Search: {podchaser_url}")
        
        # 2. Check if hosted on other platforms
        print("\n2. ALTERNATIVE HOSTING PLATFORMS")
        print("-" * 40)
        
        platforms = {
            "Transistor.fm": "https://api.transistor.fm/v1/episodes.json",
            "Buzzsprout": "https://www.buzzsprout.com/api/",
            "Libsyn": "https://api.libsyn.com/",
            "Simplecast": "https://api.simplecast.com/",
            "Anchor.fm": "https://anchor.fm/api/",
            "Blubrry": "https://api.blubrry.com/",
            "Captivate": "https://api.captivate.fm/"
        }
        
        for platform, api in platforms.items():
            print(f"{platform}: Check if American Optimist uses this")
        
        # 3. Search for mirrors or reposts
        print("\n3. CHECKING FOR MIRRORS/REPOSTS")
        print("-" * 40)
        
        # Sometimes podcasts are reposted on other channels
        search_queries = [
            "American Optimist Marc Andreessen full episode",
            "Joe Lonsdale Marc Andreessen interview 2025",
            "American Optimist episode 118"
        ]
        
        print("Search queries for potential mirrors:")
        for query in search_queries:
            print(f"  - {query}")
        
        # 4. Check RSS aggregators that might cache the audio
        print("\n4. RSS AGGREGATORS THAT CACHE AUDIO")
        print("-" * 40)
        
        aggregators = [
            "Feedly",
            "Inoreader", 
            "The Old Reader",
            "Feedbin",
            "NewsBlur"
        ]
        
        print("These services might cache/proxy the audio:")
        for agg in aggregators:
            print(f"  - {agg}")
        
        # 5. Try web scraping the Substack page differently
        print("\n5. SUBSTACK BYPASS ATTEMPTS")
        print("-" * 40)
        
        print("Trying different Substack endpoints...")
        
        # Get episode ID from the URL
        # https://api.substack.com/feed/podcast/167438211/c0bcea42c2f887030be97d4c8d58c088.mp3
        episode_id = "167438211"
        
        substack_attempts = [
            f"https://americanoptimist.substack.com/api/v1/podcast_episode/{episode_id}",
            f"https://americanoptimist.substack.com/api/v1/audio/{episode_id}/stream",
            f"https://api.substack.com/api/v1/podcast_episode/{episode_id}/download",
            f"https://cdn.substack.com/audio/podcast/{episode_id}.mp3",
            f"https://substackcdn.com/audio/{episode_id}.mp3"
        ]
        
        for url in substack_attempts:
            try:
                async with session.head(url, timeout=5) as resp:
                    print(f"{url} -> {resp.status}")
                    if resp.status == 200:
                        print("  ✅ This might work!")
            except:
                print(f"{url} -> Failed")
        
        # 6. Check if Joe Lonsdale has other distribution channels
        print("\n6. JOE LONSDALE'S OTHER CHANNELS")
        print("-" * 40)
        
        print("Check these potential sources:")
        print("  - Joe Lonsdale's personal website")
        print("  - 8VC website (his venture capital firm)")
        print("  - University of Texas (where he teaches)")
        print("  - His Twitter/X account for episode links")
        print("  - LinkedIn posts")
        
        # 7. Try URL manipulation on the Substack URL
        print("\n7. URL MANIPULATION ATTEMPTS")
        print("-" * 40)
        
        original = "https://api.substack.com/feed/podcast/167438211/c0bcea42c2f887030be97d4c8d58c088.mp3"
        
        variations = [
            original.replace("api.", "cdn."),
            original.replace("api.", "media."),
            original.replace("/feed/", "/audio/"),
            original.replace("https://", "https://media."),
            original + "?download=1",
            original + "?direct=1"
        ]
        
        print("Trying URL variations...")
        for var in variations:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; Podcast/2.0)',
                    'Accept': 'audio/*',
                    'Referer': 'https://americanoptimist.substack.com/'
                }
                async with session.head(var, headers=headers, timeout=3) as resp:
                    print(f"{var[:60]}... -> {resp.status}")
            except:
                print(f"{var[:60]}... -> Failed")

if __name__ == "__main__":
    asyncio.run(search_alternative_hosts())