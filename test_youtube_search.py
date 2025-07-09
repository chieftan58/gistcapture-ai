#\!/usr/bin/env python3
"""
Test YouTube search functionality
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.fetchers.youtube_ytdlp_api import YtDlpSearcher
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

async def test_youtube_search():
    """Test YouTube search for podcasts"""
    
    test_queries = [
        "All In Podcast E197",
        "Joe Lonsdale American Optimist",
        "Dwarkesh Patel podcast",
        "The Drive Peter Attia"
    ]
    
    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Searching: {query}")
        print(f"{'='*60}")
        
        videos = await YtDlpSearcher.search_youtube(query, limit=3)
        
        if videos:
            print(f"Found {len(videos)} videos:")
            for i, video in enumerate(videos):
                print(f"\n{i+1}. {video['title']}")
                print(f"   Channel: {video['channel']}")
                print(f"   URL: {video['url']}")
                print(f"   Duration: {video['duration']}s")
                
                # Try to get audio URL
                print("   Getting audio URL...")
                audio_url = await YtDlpSearcher.get_audio_url(video['url'])
                if audio_url:
                    print(f"   ✅ Audio URL: {audio_url[:80]}...")
                else:
                    print("   ❌ Could not get audio URL")
        else:
            print("No videos found\!")

if __name__ == "__main__":
    asyncio.run(test_youtube_search())
EOF < /dev/null
