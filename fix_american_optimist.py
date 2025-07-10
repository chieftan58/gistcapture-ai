#!/usr/bin/env python3
"""
Fix for American Optimist downloads
This script patches the episode fetcher to use Apple Podcasts data directly
and creates episodes with alternative download strategies
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.fetchers.episode_fetcher import ReliableEpisodeFetcher
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.config import load_podcast_configs

async def test_fix():
    """Test the American Optimist fix"""
    print("Testing American Optimist Fix")
    print("=" * 80)
    
    # Get config
    configs = load_podcast_configs()
    ao_config = next(c for c in configs if c['name'] == 'American Optimist')
    
    # Modify config to force Apple-only fetching
    ao_config['force_apple'] = True
    ao_config['retry_strategy']['skip_youtube'] = True  # Add flag to skip YouTube
    
    print(f"1. Config: {ao_config['name']}")
    print(f"   Apple ID: {ao_config['apple_id']}")
    print(f"   Skip YouTube: {ao_config['retry_strategy'].get('skip_youtube', False)}")
    
    # Initialize fetcher
    db = PodcastDatabase()
    fetcher = ReliableEpisodeFetcher(db)
    
    # Patch the fetcher to handle American Optimist specially
    original_fetch = fetcher.fetch_episodes
    
    async def patched_fetch(podcast_config, days_back=7):
        """Patched fetch that handles American Optimist specially"""
        if podcast_config['name'] == 'American Optimist':
            print("\n2. Using special American Optimist handler...")
            
            # Force Apple-only strategy
            fetcher.primary_strategy = 'apple_podcasts'
            
            # Get episodes from Apple
            episodes = await fetcher._fetch_from_apple_podcasts(podcast_config, days_back)
            
            if episodes:
                print(f"\n3. Found {len(episodes)} episodes from Apple:")
                for i, ep in enumerate(episodes[:5]):
                    print(f"   {i+1}. {ep.title}")
                    print(f"      Published: {ep.published}")
                    print(f"      Original URL: {ep.audio_url[:60]}...")
                    
                    # Replace Substack URLs with search instructions
                    if 'substack.com' in ep.audio_url:
                        # Create search query for later use
                        import re
                        ep_match = re.search(r'Ep\.?\s*(\d+)', ep.title)
                        if ep_match:
                            ep_num = ep_match.group(1)
                            # This will be handled by download manager
                            ep.audio_url = f"search:American Optimist Episode {ep_num}"
                            print(f"      Enhanced URL: {ep.audio_url}")
                
                return episodes
            else:
                print("   ❌ No episodes from Apple!")
                return []
        else:
            # Use original method for other podcasts
            return await original_fetch(podcast_config, days_back)
    
    # Apply patch
    fetcher.fetch_episodes = patched_fetch
    
    # Test fetch
    print("\n4. Fetching episodes...")
    episodes = await fetcher.fetch_episodes(ao_config, days_back=7)
    
    print(f"\n5. Results:")
    print(f"   Total episodes: {len(episodes)}")
    if episodes:
        print(f"   First episode: {episodes[0].title}")
        print(f"   Audio URL: {episodes[0].audio_url}")
    
    return episodes

if __name__ == "__main__":
    episodes = asyncio.run(test_fix())