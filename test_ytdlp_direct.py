#!/usr/bin/env python3
"""
Test yt-dlp directly
"""

import yt_dlp

# Test search
query = "Joe Lonsdale American Optimist 118"
print(f"Searching for: {query}")

ydl_opts = {
    'quiet': False,
    'extract_flat': True,
    'default_search': 'ytsearch',
    'playlist_items': '1-3'
}

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch3:{query}", download=False)
        
        if result and 'entries' in result:
            print(f"\nFound {len(result['entries'])} results:")
            for i, entry in enumerate(result['entries']):
                if entry:
                    print(f"\n{i+1}. {entry.get('title')}")
                    print(f"   Channel: {entry.get('channel', 'Unknown')}")
                    print(f"   URL: https://www.youtube.com/watch?v={entry.get('id')}")
        else:
            print("No results found")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()