#!/usr/bin/env python3
"""
Test Apple Podcasts API directly
"""

import asyncio
import aiohttp
import json

async def test_apple_api():
    """Test Apple Podcasts API for American Optimist"""
    
    apple_id = "1573141757"  # American Optimist
    
    async with aiohttp.ClientSession() as session:
        # Search for recent episodes
        search_url = "https://itunes.apple.com/lookup"
        params = {
            'id': apple_id,
            'entity': 'podcastEpisode',
            'limit': 10
        }
        
        print(f"Fetching from: {search_url}")
        print(f"Params: {params}")
        
        async with session.get(search_url, params=params) as response:
            print(f"Status: {response.status}")
            
            if response.status == 200:
                text = await response.text()
                # Apple API returns JSONP sometimes, extract JSON
                if text.startswith('/*') and text.endswith('*/'):
                    # Remove comment wrapper
                    text = text[2:-2].strip()
                data = json.loads(text)
                
                print(f"\nResults count: {data.get('resultCount', 0)}")
                
                if 'results' in data and len(data['results']) > 0:
                    # First result is podcast info
                    podcast_info = data['results'][0]
                    print(f"\nPodcast: {podcast_info.get('collectionName', 'Unknown')}")
                    
                    # Episodes start from index 1
                    episodes = data['results'][1:]
                    print(f"Episodes found: {len(episodes)}")
                    
                    for i, ep in enumerate(episodes[:3]):
                        print(f"\nEpisode {i+1}:")
                        print(f"  Title: {ep.get('trackName', 'No title')}")
                        print(f"  Release: {ep.get('releaseDate', 'No date')}")
                        print(f"  Audio URL: {ep.get('episodeUrl', 'NO AUDIO URL')}")
                        print(f"  Episode type: {ep.get('episodeContentType', 'Unknown')}")
                        
                        # Check what fields are available
                        if i == 0:
                            print(f"\n  Available fields: {list(ep.keys())}")
                else:
                    print("No results found!")
            else:
                print(f"Error: {await response.text()}")

if __name__ == "__main__":
    asyncio.run(test_apple_api())