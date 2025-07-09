#!/usr/bin/env python3
"""
Test YouTube access with yt-dlp
"""

import yt_dlp
import sys

def test_youtube_access():
    """Test if we can access YouTube"""
    
    browsers = ['chrome', 'firefox', 'safari', 'edge', None]
    
    for browser in browsers:
        print(f"\nTrying with {browser if browser else 'no'} cookies...")
        
        ydl_opts = {
            'quiet': False,
            'extract_flat': True,
        }
        
        if browser:
            try:
                ydl_opts['cookiesfrombrowser'] = (browser,)
            except Exception as e:
                print(f"  Could not load {browser} cookies: {e}")
                continue
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Try to search for a simple query
                result = ydl.extract_info("ytsearch3:test video", download=False)
                
                if result and 'entries' in result:
                    print(f"  ✅ SUCCESS with {browser if browser else 'no'} cookies!")
                    print(f"  Found {len(result['entries'])} videos")
                    for i, entry in enumerate(result['entries'][:2]):
                        if entry:
                            print(f"    {i+1}. {entry.get('title', 'Unknown')}")
                    return True
                    
        except Exception as e:
            print(f"  ❌ Failed: {str(e)[:100]}...")
    
    return False

if __name__ == "__main__":
    print("Testing YouTube access with yt-dlp...")
    print("=" * 60)
    
    if test_youtube_access():
        print("\n✅ YouTube access is working!")
    else:
        print("\n❌ Cannot access YouTube - all methods failed")
        print("\nPossible solutions:")
        print("1. Log into YouTube in a browser")
        print("2. Install browser: apt-get install chromium-browser")
        print("3. Use a VPN if YouTube is blocked")
        print("4. Wait a few hours if rate limited")