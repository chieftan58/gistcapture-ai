#!/usr/bin/env python3
"""
Fix downloads using yt-dlp for YouTube extraction
"""

import asyncio
import subprocess
import json
from pathlib import Path

async def find_youtube_episode(podcast_name: str, episode_title: str):
    """Find YouTube URL using yt-dlp search"""
    
    # Build search queries based on podcast
    queries = []
    
    if podcast_name == "American Optimist":
        # Extract episode number
        import re
        ep_match = re.search(r'Ep\s*(\d+)', episode_title)
        if ep_match:
            ep_num = ep_match.group(1)
            queries = [
                f"Joe Lonsdale American Optimist {ep_num}",
                f"Joe Lonsdale {episode_title}",
                f"American Optimist podcast {episode_title}"
            ]
    elif podcast_name == "Dwarkesh Podcast":
        queries = [
            f"Dwarkesh Patel {episode_title}",
            f"Dwarkesh Podcast {episode_title}"
        ]
    elif podcast_name == "All-In":
        queries = [
            f"All-In Podcast {episode_title}",
            f"All In Pod {episode_title}"
        ]
    else:
        queries = [f"{podcast_name} {episode_title}"]
    
    # Try each query
    for query in queries:
        print(f"\nSearching YouTube: {query}")
        
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",  # Search for 1 result
            "--get-url",  # Get direct audio URL
            "-f", "bestaudio",  # Best audio format
            "--no-playlist",
            "-q"  # Quiet
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                audio_url = result.stdout.strip()
                print(f"✅ Found audio URL: {audio_url[:80]}...")
                
                # Also get video URL for reference
                video_cmd = cmd.copy()
                video_cmd.remove("--get-url")
                video_cmd.extend(["--get-id", "--get-title"])
                
                video_result = subprocess.run(video_cmd, capture_output=True, text=True, timeout=10)
                if video_result.returncode == 0:
                    lines = video_result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        video_id = lines[0]
                        title = lines[1]
                        print(f"   Video: https://youtube.com/watch?v={video_id}")
                        print(f"   Title: {title}")
                
                return audio_url
        except subprocess.TimeoutExpired:
            print("   Timeout")
        except Exception as e:
            print(f"   Error: {e}")
    
    return None

async def main():
    """Test YouTube extraction for problematic podcasts"""
    
    test_cases = [
        ("American Optimist", "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance"),
        ("Dwarkesh Podcast", "Why I don't think AGI is right around the corner"),
        ("All-In", "Big Beautiful Bill, Elon/Trump, Dollar Down Big, Harvard's Money Problems, Figma IPO"),
    ]
    
    print("Testing YouTube extraction with yt-dlp")
    print("="*60)
    
    for podcast, title in test_cases:
        print(f"\n{podcast}: {title}")
        print("-"*60)
        
        audio_url = await find_youtube_episode(podcast, title)
        
        if audio_url:
            print("✅ SUCCESS - Found audio URL")
            
            # Test download
            print("\nTesting download...")
            download_cmd = [
                "yt-dlp",
                audio_url,
                "-o", f"test_{podcast}.%(ext)s",
                "-f", "bestaudio",
                "--extract-audio",
                "--audio-format", "mp3",
                "--no-playlist",
                "--progress"
            ]
            
            try:
                subprocess.run(download_cmd, timeout=60)
                
                # Check file
                files = list(Path(".").glob(f"test_{podcast}.*"))
                if files:
                    file_size = files[0].stat().st_size / (1024*1024)
                    print(f"✅ Downloaded: {files[0].name} ({file_size:.1f} MB)")
                    files[0].unlink()  # Clean up
            except Exception as e:
                print(f"Download error: {e}")
        else:
            print("❌ FAILED - No YouTube version found")

if __name__ == "__main__":
    asyncio.run(main())