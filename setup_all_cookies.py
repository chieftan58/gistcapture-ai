#!/usr/bin/env python3
"""Set up cookies for YouTube, Spotify, and Apple Podcasts"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from renaissance_weekly.utils.cookie_manager import cookie_manager

def main():
    print("🍪 Renaissance Weekly Cookie Setup")
    print("=" * 60)
    
    # Show current status
    status = cookie_manager.list_cookies()
    
    print("\nCurrent Cookie Status:")
    print("-" * 30)
    
    for platform, files in status.items():
        print(f"\n{platform.upper()}:")
        if files['protected']:
            print(f"  ✅ Protected manual file exists")
            size = files['protected'].stat().st_size
            print(f"     Size: {size} bytes")
        else:
            print(f"  ❌ No protected manual file")
        
        if files['regular']:
            print(f"  📄 Regular file exists")
            size = files['regular'].stat().st_size
            print(f"     Size: {size} bytes")
    
    print("\n" + "=" * 60)
    print("\nINSTRUCTIONS FOR EACH PLATFORM:")
    
    print("\n1. YOUTUBE (Required for American Optimist & Dwarkesh):")
    print("   - Go to YouTube.com and ensure you're logged in")
    print("   - Use 'cookies.txt' browser extension to export")
    print("   - Save as: ~/.config/renaissance-weekly/cookies/youtube_cookies.txt")
    
    print("\n2. SPOTIFY (Optional fallback):")
    print("   - Go to Spotify.com and ensure you're logged in")
    print("   - Export cookies with the extension")
    print("   - Save as: ~/.config/renaissance-weekly/cookies/spotify_cookies.txt")
    
    print("\n3. APPLE PODCASTS (Optional fallback):")
    print("   - Go to podcasts.apple.com and ensure you're logged in")
    print("   - Export cookies with the extension")
    print("   - Save as: ~/.config/renaissance-weekly/cookies/apple_cookies.txt")
    
    print("\n" + "=" * 60)
    
    # Check for unprotected files and offer to protect them
    found_new = False
    for platform in ['youtube', 'spotify', 'apple']:
        regular = cookie_manager.regular_cookies[platform]
        protected = cookie_manager.protected_cookies[platform]
        
        if regular.exists() and not protected.exists():
            found_new = True
            print(f"\n📌 Found unprotected {platform} cookies!")
            response = input(f"   Protect them from being overwritten? (y/n): ")
            if response.lower() == 'y':
                if cookie_manager.protect_cookie_file(platform, regular):
                    print(f"   ✅ {platform} cookies are now protected!")
    
    if not found_new:
        print("\nNo new cookie files found to protect.")
        print("\nAfter you export cookie files, run this script again to protect them.")
    
    print("\n" + "=" * 60)
    print("\nThe system will automatically use protected cookies when available.")
    print("Protected files won't be overwritten by yt-dlp or other tools.")
    
    # Test YouTube if cookies exist
    youtube_cookie = cookie_manager.get_cookie_file('youtube')
    if youtube_cookie:
        print("\n" + "=" * 60)
        response = input("\nTest YouTube access? (y/n): ")
        if response.lower() == 'y':
            test_youtube_access(youtube_cookie)

def test_youtube_access(cookie_file):
    """Quick test of YouTube access"""
    import subprocess
    
    print("\nTesting YouTube access...")
    test_url = "https://www.youtube.com/watch?v=pRoKi4VL_5s"
    
    try:
        cmd = ['python', '-m', 'yt_dlp', '--cookies', str(cookie_file), '--get-title', test_url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            print(f"✅ SUCCESS: YouTube access working!")
            print(f"   Title: {result.stdout.strip()}")
        else:
            print("❌ FAILED: YouTube access not working")
            if "Sign in" in result.stderr:
                print("   Cookies may be expired or invalid")
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    main()