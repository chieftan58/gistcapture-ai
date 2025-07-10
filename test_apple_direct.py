#!/usr/bin/env python3
"""Test Apple Podcasts direct download for American Optimist"""

import asyncio
import aiohttp
import json
from datetime import datetime

async def test_apple_podcasts():
    """Test Apple Podcasts API and downloads"""
    
    apple_id = "1573141757"  # American Optimist
    
    async with aiohttp.ClientSession() as session:
        # Get recent episodes
        url = "https://itunes.apple.com/lookup"
        params = {
            'id': apple_id,
            'entity': 'podcastEpisode',
            'limit': 10
        }
        
        print(f"Fetching from Apple Podcasts API...")
        print(f"URL: {url}")
        print(f"Params: {params}")
        print()
        
        async with session.get(url, params=params) as response:
            if response.status == 200:
                text = await response.text()
                # Apple API sometimes returns JSONP
                if text.startswith('/*') and text.endswith('*/'):
                    text = text[2:-2].strip()
                data = json.loads(text)
                
                print(f"Podcast: {data['results'][0].get('collectionName', 'Unknown')}")
                print(f"Episodes found: {len(data['results']) - 1}")
                print()
                
                # Episodes start from index 1
                episodes = data['results'][1:]
                
                # Find Marc Andreessen episode
                marc_episode = None
                for ep in episodes:
                    title = ep.get('trackName', '')
                    if 'Marc Andreessen' in title or 'Ep 118' in title:
                        marc_episode = ep
                        break
                
                if marc_episode:
                    print("Found Marc Andreessen episode:")
                    print(f"  Title: {marc_episode.get('trackName')}")
                    print(f"  Release Date: {marc_episode.get('releaseDate')}")
                    print(f"  Audio URL: {marc_episode.get('episodeUrl', 'NO URL')}")
                    print()
                    
                    # Try to download
                    audio_url = marc_episode.get('episodeUrl')
                    if audio_url:
                        print(f"Testing download from Apple URL...")
                        headers = {
                            'User-Agent': 'AppleCoreMedia/1.0.0.20G165 (iPhone; U; CPU OS 16_6 like Mac OS X; en_us)',
                            'Accept': '*/*',
                            'Accept-Encoding': 'identity',
                            'Connection': 'keep-alive',
                        }
                        
                        async with session.get(audio_url, headers=headers) as audio_response:
                            print(f"  Status: {audio_response.status}")
                            print(f"  Content-Type: {audio_response.headers.get('Content-Type')}")
                            print(f"  Content-Length: {audio_response.headers.get('Content-Length')}")
                            
                            if audio_response.status == 200:
                                # Just read first 1KB to verify it's audio
                                chunk = await audio_response.content.read(1024)
                                if chunk.startswith(b'ID3') or chunk[4:8] == b'ftyp':
                                    print(f"  ✅ Valid audio file!")
                                else:
                                    print(f"  ❌ Not an audio file")
                                    print(f"  First bytes: {chunk[:20]}")
                else:
                    print("Marc Andreessen episode not found in recent episodes")
                    
                print("\nAll recent episodes:")
                for i, ep in enumerate(episodes[:5], 1):
                    print(f"{i}. {ep.get('trackName', 'No title')}")
                    print(f"   Released: {ep.get('releaseDate', 'Unknown')}")
                    print(f"   URL available: {'Yes' if ep.get('episodeUrl') else 'No'}")
                    
            else:
                print(f"API Error: {response.status}")
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(test_apple_podcasts())