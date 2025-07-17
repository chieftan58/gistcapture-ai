#!/usr/bin/env python3
"""
Fix for American Optimist downloads - enhanced YouTube strategy with better anti-detection
"""

import os
import sys
import yt_dlp
from pathlib import Path

def download_with_enhanced_options(url: str, output_path: str):
    """Download with enhanced anti-detection options"""
    
    cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_manual_do_not_overwrite.txt'
    
    ydl_opts = {
        'format': 'bestaudio/best',  # More flexible format selection
        'outtmpl': output_path.replace('.mp3', '.%(ext)s'),  # Let yt-dlp choose extension
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,
        'quiet': False,
        'no_warnings': False,
        'ignoreerrors': False,
        'cookiefile': str(cookie_file) if cookie_file.exists() else None,
        # Enhanced anti-detection options
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        'sleep_interval_requests': 1,
        'extractor_args': {
            'youtube': {
                'player_client': ['web'],  # Use only web client since android doesn't support cookies
                'skip': ['dash']
            }
        }
    }
    
    print(f"🎥 Attempting download with enhanced options...")
    print(f"📁 Cookie file: {cookie_file} ({'exists' if cookie_file.exists() else 'missing'})")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            print(f"✅ Successfully downloaded: {info.get('title', 'Unknown')}")
            return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        
        # Try alternative approach with browser cookies
        print("\n🔄 Trying with browser cookies...")
        for browser in ['firefox', 'chrome', 'chromium', 'edge']:
            try:
                ydl_opts['cookiesfrombrowser'] = (browser,)
                del ydl_opts['cookiefile']
                
                print(f"  Trying {browser}...")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    print(f"✅ Successfully downloaded with {browser} cookies!")
                    return True
            except:
                continue
        
        return False

def test_boris_sofman_episode():
    """Test downloading the Boris Sofman episode"""
    url = "https://www.youtube.com/watch?v=l2sdZ1IyZx8"
    output = "american_optimist_boris_sofman.mp3"
    
    print("🚀 Testing American Optimist - Boris Sofman episode download")
    print(f"📎 URL: {url}")
    print(f"💾 Output: {output}")
    print("-" * 60)
    
    if download_with_enhanced_options(url, output):
        if os.path.exists(output):
            size_mb = os.path.getsize(output) / 1024 / 1024
            print(f"\n✅ Download successful!")
            print(f"📁 File: {output}")
            print(f"📏 Size: {size_mb:.1f} MB")
            print("\n💡 The episode URL mapping has been fixed in youtube_strategy.py")
            print("   Future downloads should work automatically!")
        else:
            print("\n⚠️ Download reported success but file not found")
    else:
        print("\n❌ All download attempts failed")
        print("\n📋 Next steps:")
        print("1. Export fresh YouTube cookies from your browser")
        print("2. Make sure you're signed into YouTube")
        print("3. Use the cookies.txt browser extension")
        print("4. Save to ~/.config/renaissance-weekly/cookies/youtube_cookies.txt")
        print("5. Run: python protect_cookies_now.py")

if __name__ == "__main__":
    test_boris_sofman_episode()