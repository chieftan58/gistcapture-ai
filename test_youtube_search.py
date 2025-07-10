#\!/usr/bin/env python3
"""Test YouTube search for American Optimist episode"""

import asyncio
import aiohttp
from urllib.parse import quote_plus

async def search_youtube():
    """Search YouTube for the Marc Andreessen episode"""
    
    queries = [
        "Joe Lonsdale Marc Andreessen AI Robotics",
        "American Optimist Ep 118 Marc Andreessen",
        "Joe Lonsdale American Optimist Marc Andreessen 2025",
        "Marc Andreessen America Industrial Renaissance Joe Lonsdale"
    ]
    
    async with aiohttp.ClientSession() as session:
        for query in queries:
            print(f"\nSearching YouTube for: {query}")
            
            # Try YouTube search
            search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            
            try:
                async with session.get(search_url, headers=headers) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Quick check for video IDs
                        import re
                        video_ids = re.findall(r"\"videoId\":\"([a-zA-Z0-9_-]{11})\"", html)[:5]
                        
                        if video_ids:
                            print(f"Found {len(video_ids)} videos")
                            
                            # Extract titles if possible
                            title_matches = re.findall(r"\"title\":{\"runs\":\[{\"text\":\"([^\"]+)\"}\]", html)[:5]
                            
                            for i, (vid_id, title) in enumerate(zip(video_ids, title_matches), 1):
                                print(f"  {i}. {title[:60]}...")
                                print(f"     https://www.youtube.com/watch?v={vid_id}")
                                
                                # Check if this looks like our episode
                                if ("Marc Andreessen" in title or "marc andreessen" in title.lower()) and \
                                   ("Joe Lonsdale" in title or "American Optimist" in title):
                                    print(f"     ✅ This looks like a match\!")
                        else:
                            print("  No videos found")
                    else:
                        print(f"  Error: {response.status}")
                        
            except Exception as e:
                print(f"  Search error: {e}")
    
    # Also check Joe Lonsdale YouTube channel directly
    print("\n\nChecking Joe Lonsdale YouTube channel:")
    print("Channel URL: https://www.youtube.com/@joelonsdale")
    print("Channel ID: UCBZjspOTvT5nyDWcHAfaVZQ")
    
    # Test with yt-dlp
    import subprocess
    try:
        print("\nTrying yt-dlp search:")
        cmd = [
            "yt-dlp",
            "--get-title",
            "--get-id", 
            "--playlist-items", "1-5",
            "ytsearch5:Joe Lonsdale Marc Andreessen AI Robotics 2025"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.strip().split("\\n")
            for i in range(0, len(lines), 2):
                if i+1 < len(lines):
                    title = lines[i]
                    video_id = lines[i+1]
                    print(f"\n{i//2 + 1}. {title}")
                    print(f"   https://www.youtube.com/watch?v={video_id}")
        else:
            print("yt-dlp search failed")
            
    except FileNotFoundError:
        print("yt-dlp not installed")

if __name__ == "__main__":
    asyncio.run(search_youtube())
