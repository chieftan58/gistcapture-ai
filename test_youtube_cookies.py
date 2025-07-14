#!/usr/bin/env python3
"""Test YouTube cookie authentication"""

import subprocess
import sys
from pathlib import Path

def test_youtube_access():
    """Test if YouTube cookies are working"""
    
    # Test URLs
    test_urls = {
        "American Optimist (Marc Andreessen)": "https://www.youtube.com/watch?v=pRoKi4VL_5s",
        "Dwarkesh (Stephen Kotkin)": "https://www.youtube.com/watch?v=YMfd3EoHfPI"
    }
    
    # Check for manual cookie file
    manual_cookie = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_manual_do_not_overwrite.txt'
    regular_cookie = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt'
    
    print("YouTube Cookie Test")
    print("==================\n")
    
    if manual_cookie.exists():
        print(f"✅ Manual cookie file found: {manual_cookie}")
        print(f"   Size: {manual_cookie.stat().st_size} bytes")
        print(f"   Protected: {'Yes' if oct(manual_cookie.stat().st_mode)[-3:] == '444' else 'No'}")
    else:
        print(f"❌ Manual cookie file not found: {manual_cookie}")
    
    if regular_cookie.exists():
        print(f"\n📄 Regular cookie file found: {regular_cookie}")
        print(f"   Size: {regular_cookie.stat().st_size} bytes")
    
    print("\nTesting YouTube access...")
    print("-" * 50)
    
    for name, url in test_urls.items():
        print(f"\nTesting: {name}")
        print(f"URL: {url}")
        
        # Test with yt-dlp
        try:
            if manual_cookie.exists():
                cmd = ['python', '-m', 'yt_dlp', '--cookies', str(manual_cookie), '--get-title', url]
            else:
                cmd = ['python', '-m', 'yt_dlp', '--get-title', url]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"✅ SUCCESS: {result.stdout.strip()}")
            else:
                error = result.stderr.strip()
                if "Sign in" in error or "bot" in error:
                    print("❌ FAILED: YouTube requires authentication")
                else:
                    print(f"❌ FAILED: {error[:100]}...")
                    
        except subprocess.TimeoutExpired:
            print("❌ FAILED: Timeout - likely authentication issue")
        except Exception as e:
            print(f"❌ ERROR: {e}")
    
    print("\n" + "-" * 50)
    print("\nRecommendations:")
    if not manual_cookie.exists():
        print("1. Export fresh YouTube cookies from your browser")
        print("2. Save as: ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt")
        print("3. Run: chmod 444 <cookie_file> to protect it")
    elif any("FAILED" in line for line in str(locals())):
        print("1. Your cookies may have expired - export fresh ones")
        print("2. Make sure you're logged into YouTube when exporting")
        print("3. Use 'cookies.txt' extension for Netscape format")

if __name__ == "__main__":
    test_youtube_access()