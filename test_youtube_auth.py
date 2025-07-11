#!/usr/bin/env python3
"""Test YouTube authentication with different browsers"""

import subprocess
import sys

def test_browser_cookies():
    """Test which browsers have working YouTube cookies"""
    
    test_url = "https://www.youtube.com/watch?v=pRoKi4VL_5s"  # American Optimist Ep 118
    browsers = ['firefox', 'chrome', 'chromium', 'edge', 'safari']
    
    print("Testing YouTube authentication with available browsers...\n")
    
    working_browsers = []
    
    for browser in browsers:
        print(f"Testing {browser}...", end=' ')
        try:
            cmd = [
                'yt-dlp',
                '--cookies-from-browser', browser,
                '--simulate',  # Don't download, just test
                '--quiet',
                test_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print("✅ WORKS!")
                working_browsers.append(browser)
            else:
                if "browser" in result.stderr.lower() and "not found" in result.stderr.lower():
                    print("❌ Browser not found")
                elif "Sign in" in result.stderr:
                    print("❌ Not logged into YouTube") 
                else:
                    print("❌ Failed")
                    
        except subprocess.TimeoutExpired:
            print("❌ Timeout")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print("\n" + "="*60)
    if working_browsers:
        print(f"✅ Working browsers: {', '.join(working_browsers)}")
        print("\nThe system will automatically use these browsers for YouTube downloads.")
        print("Make sure you stay logged into YouTube in one of these browsers.")
    else:
        print("❌ No browsers with working YouTube authentication found.")
        print("\nTo fix this:")
        print("1. Open Firefox or Chrome")
        print("2. Go to youtube.com and sign in")
        print("3. Make sure you can play videos")
        print("4. Run this test again")
        
        print("\nAlternatively, you can manually download episodes:")
        print("yt-dlp -x --audio-format mp3 -o 'episode.mp3' <youtube_url>")
        print("Then use 'Manual URL' in the UI with the local file path")
    print("="*60)

if __name__ == "__main__":
    test_browser_cookies()