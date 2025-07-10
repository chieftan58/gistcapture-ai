#!/usr/bin/env python3
"""Working solution for American Optimist downloads"""

import asyncio
import aiohttp
import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def get_episodes_from_apple():
    """Get episode metadata from Apple Podcasts"""
    apple_id = "1573141757"
    url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcastEpisode&limit=10"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()
            data = json.loads(text)
    
    episodes = []
    for item in data.get('results', [])[1:]:  # Skip podcast info
        episodes.append({
            'title': item.get('trackName', ''),
            'date': item.get('releaseDate', ''),
            'description': item.get('description', ''),
            'apple_url': item.get('episodeUrl', ''),  # This will be Substack/403
            'guid': item.get('trackId', '')
        })
    
    return episodes

async def find_youtube_url(episode_title):
    """Find YouTube URL for episode"""
    # Clean up title for search
    import re
    
    # Extract episode number if present
    ep_match = re.search(r'Ep\.?\s*(\d+)', episode_title, re.IGNORECASE)
    ep_num = ep_match.group(1) if ep_match else None
    
    # Build search query
    if ep_num:
        query = f'"American Optimist" "Joe Lonsdale" "Ep {ep_num}"'
    else:
        # Extract guest name if present
        guest_match = re.search(r':\s*([^:]+?)(?:\s+on\s+|\s*$)', episode_title)
        guest = guest_match.group(1).strip() if guest_match else ""
        query = f'"American Optimist" "Joe Lonsdale" "{guest}"' if guest else f'"American Optimist" "{episode_title[:50]}"'
    
    print(f"  Searching YouTube: {query}")
    
    # Use yt-dlp to search
    cmd = [
        sys.executable, '-m', 'yt_dlp',  # Use Python module instead of command
        f'ytsearch3:{query}',
        '--get-title',
        '--get-id', 
        '--get-duration',
        '--no-playlist',
        '--quiet',
        '--no-warnings'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.stdout:
            lines = result.stdout.strip().split('\n')
            # Process results in groups of 3 (title, id, duration)
            for i in range(0, len(lines), 3):
                if i+2 < len(lines):
                    title = lines[i]
                    video_id = lines[i+1]
                    duration = lines[i+2]
                    
                    # Check if this looks like a full episode (not a clip)
                    duration_parts = duration.split(':')
                    if len(duration_parts) >= 2:
                        minutes = int(duration_parts[0]) * 60 + int(duration_parts[1])
                        if minutes > 30:  # Full episodes are usually > 30 minutes
                            youtube_url = f"https://youtube.com/watch?v={video_id}"
                            print(f"  Found: {title}")
                            print(f"  URL: {youtube_url}")
                            print(f"  Duration: {duration}")
                            return youtube_url
            
        print(f"  No suitable YouTube videos found")
        return None
        
    except Exception as e:
        print(f"  YouTube search error: {e}")
        return None

async def download_from_youtube(youtube_url, output_path):
    """Download audio from YouTube URL"""
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '-f', 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
        '--extract-audio',
        '--audio-format', 'mp3',
        '--audio-quality', '192K',
        '-o', str(output_path),
        youtube_url,
        '--quiet',
        '--no-warnings',
        '--progress'
    ]
    
    try:
        print(f"  Downloading from YouTube...")
        result = subprocess.run(cmd, timeout=300)
        
        # Check if file exists (yt-dlp adds .mp3 extension)
        if output_path.with_suffix('.mp3').exists():
            return output_path.with_suffix('.mp3')
        elif output_path.exists():
            return output_path
        else:
            print(f"  Download failed - no file created")
            return None
            
    except subprocess.TimeoutExpired:
        print(f"  Download timed out")
        return None
    except Exception as e:
        print(f"  Download error: {e}")
        return None

async def process_american_optimist():
    """Complete solution for American Optimist"""
    print("American Optimist Download Solution")
    print("=" * 80)
    
    # Step 1: Get episodes from Apple
    print("\n1. Getting episodes from Apple Podcasts...")
    episodes = await get_episodes_from_apple()
    print(f"   Found {len(episodes)} episodes")
    
    # Step 2: Process first episode as test
    if episodes:
        episode = episodes[0]
        print(f"\n2. Processing: {episode['title']}")
        print(f"   Date: {episode['date']}")
        
        # Step 3: Find on YouTube
        print("\n3. Finding on YouTube...")
        youtube_url = await find_youtube_url(episode['title'])
        
        if youtube_url:
            # Step 4: Download
            print("\n4. Downloading audio...")
            output_path = Path(f"/tmp/american_optimist_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            audio_file = await download_from_youtube(youtube_url, output_path)
            
            if audio_file and audio_file.exists():
                size_mb = audio_file.stat().st_size / 1_000_000
                print(f"\n✅ SUCCESS!")
                print(f"   Downloaded to: {audio_file}")
                print(f"   Size: {size_mb:.1f} MB")
                
                # Clean up
                audio_file.unlink()
                
                return True
            else:
                print(f"\n❌ Download failed")
                return False
        else:
            print(f"\n❌ Could not find on YouTube")
            return False
    else:
        print("\n❌ No episodes found from Apple")
        return False

async def create_episode_objects():
    """Create Episode objects that work with the system"""
    from renaissance_weekly.models import Episode
    from datetime import datetime, timezone
    
    print("\n\n5. Creating Episode objects for the system...")
    
    episodes = await get_episodes_from_apple()
    episode_objects = []
    
    for ep in episodes[:3]:  # Just first 3
        # Find YouTube URL
        youtube_url = await find_youtube_url(ep['title'])
        
        # Parse date
        date_str = ep['date']
        if date_str:
            published = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        else:
            published = datetime.now(timezone.utc)
        
        # Create Episode object with YouTube URL as audio_url
        episode_obj = Episode(
            podcast="American Optimist",
            title=ep['title'],
            published=published,
            duration="60:00",  # Estimate
            audio_url=youtube_url or "",  # Use YouTube URL!
            transcript_url=None,
            description=ep['description'],
            guid=str(ep['guid'])
        )
        
        episode_objects.append(episode_obj)
        print(f"\n   Created: {episode_obj.title}")
        print(f"   Audio URL: {episode_obj.audio_url}")
    
    return episode_objects

if __name__ == "__main__":
    # Test the complete solution
    success = asyncio.run(process_american_optimist())
    
    if success:
        # Show how to create Episode objects
        episodes = asyncio.run(create_episode_objects())
        
        print("\n\nSOLUTION SUMMARY:")
        print("=" * 80)
        print("1. Get metadata from Apple Podcasts (titles, dates, descriptions)")
        print("2. Search YouTube for each episode using intelligent queries")
        print("3. Use YouTube URLs as audio_url in Episode objects")
        print("4. Let the download manager handle YouTube downloads with yt-dlp")
        print("\nThis bypasses Substack/Cloudflare completely!")