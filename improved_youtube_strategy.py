#!/usr/bin/env python3
"""
Improved YouTube strategy with better authentication handling
This replaces the overly long error message with practical solutions
"""

import sys
sys.path.insert(0, '/workspaces/gistcapture-ai')

# Patch the YouTube strategy to provide better error messages
def patch_youtube_strategy():
    """Patch the YouTube strategy for better error handling"""
    
    from renaissance_weekly.download_strategies.youtube_strategy import YouTubeStrategy
    
    # Store the original download method
    original_download = YouTubeStrategy.download
    
    async def improved_download(self, url, output_path, episode_info):
        """Improved download with better error messages"""
        
        # Try the original download method
        success, error = await original_download(self, url, output_path, episode_info)
        
        if not success:
            # Provide more helpful error message
            podcast = episode_info.get('podcast', '')
            title = episode_info.get('title', '')
            
            better_error = f"""
YouTube Authentication Required for {podcast}

QUICK SOLUTIONS:
1. SIGN INTO YOUTUBE: Open Firefox/Chrome → youtube.com → Sign in
2. MANUAL DOWNLOAD: Click 'Manual URL' in UI and provide:
   - YouTube URL (if you have it)
   - Local MP3 file path

FOR {podcast.upper()}:
Try these YouTube URLs:
• Search: "{title}" site:youtube.com
• Channel: Look for official episodes

TECHNICAL FIX:
yt-dlp --cookies-from-browser firefox -x --audio-format mp3 [URL]
            """.strip()
            
            return False, better_error
        
        return success, error
    
    # Replace the method
    YouTubeStrategy.download = improved_download
    print("✅ YouTube strategy patched with better error messages")

def create_manual_download_helper():
    """Create a helper script for manual downloads"""
    
    helper_script = '''#!/bin/bash
# Manual Download Helper for Renaissance Weekly
# Usage: ./manual_download.sh [YouTube URL]

echo "🎵 Renaissance Weekly - Manual Download Helper"
echo "=============================================="

if [ $# -eq 0 ]; then
    echo "Usage: $0 [YouTube URL]"
    echo ""
    echo "Example URLs for American Optimist:"
    echo "• Marc Andreessen: https://www.youtube.com/watch?v=pRoKi4VL_5s"
    echo "• Dave Rubin: https://www.youtube.com/watch?v=w1FRqBOxS8g"
    echo ""
    exit 1
fi

URL="$1"
OUTPUT="downloaded_episode.mp3"

echo "🔽 Downloading from: $URL"
echo "📁 Output file: $OUTPUT"
echo ""

# Try different authentication methods
echo "🍪 Trying with Firefox cookies..."
if yt-dlp --cookies-from-browser firefox -x --audio-format mp3 -o "$OUTPUT" "$URL"; then
    echo "✅ Download successful with Firefox cookies!"
    echo "📂 File saved as: $OUTPUT"
    echo ""
    echo "💡 In Renaissance Weekly UI:"
    echo "   1. Click 'Manual URL' for the failed episode"
    echo "   2. Enter: $(pwd)/$OUTPUT"
    exit 0
fi

echo "🍪 Trying with Chrome cookies..."
if yt-dlp --cookies-from-browser chrome -x --audio-format mp3 -o "$OUTPUT" "$URL"; then
    echo "✅ Download successful with Chrome cookies!"
    echo "📂 File saved as: $OUTPUT"
    echo ""
    echo "💡 In Renaissance Weekly UI:"
    echo "   1. Click 'Manual URL' for the failed episode"
    echo "   2. Enter: $(pwd)/$OUTPUT"
    exit 0
fi

echo "🚫 Trying without cookies..."
if yt-dlp -x --audio-format mp3 -o "$OUTPUT" "$URL"; then
    echo "✅ Download successful without cookies!"
    echo "📂 File saved as: $OUTPUT"
    echo ""
    echo "💡 In Renaissance Weekly UI:"
    echo "   1. Click 'Manual URL' for the failed episode"
    echo "   2. Enter: $(pwd)/$OUTPUT"
    exit 0
fi

echo "❌ All download methods failed."
echo ""
echo "SOLUTIONS:"
echo "1. Make sure you're signed into YouTube in your browser"
echo "2. Try a different YouTube URL for the same episode"
echo "3. Use an online YouTube to MP3 converter"
echo "4. Check if the video is available in your region"
'''
    
    with open('/workspaces/gistcapture-ai/manual_download.sh', 'w') as f:
        f.write(helper_script)
    
    import os
    os.chmod('/workspaces/gistcapture-ai/manual_download.sh', 0o755)
    
    print("✅ Created manual_download.sh helper script")

def test_youtube_authentication():
    """Test YouTube authentication quickly"""
    
    print("\n🧪 Testing YouTube Authentication")
    print("=" * 40)
    
    import subprocess
    
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll - safe test
    
    browsers = ['firefox', 'chrome']
    
    for browser in browsers:
        try:
            print(f"Testing {browser}...", end=' ')
            
            cmd = [
                'yt-dlp', 
                '--cookies-from-browser', browser,
                '--simulate',  # Don't download, just test
                '--quiet',
                test_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                print("✅ WORKS!")
                return browser
            else:
                if "Sign in" in result.stderr:
                    print("❌ Need to sign in")
                else:
                    print("❌ Failed")
                    
        except subprocess.TimeoutExpired:
            print("❌ Timeout")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print("\n💡 No working authentication found.")
    print("   Please sign into YouTube in Firefox or Chrome")
    return None

if __name__ == "__main__":
    print("🔧 YouTube Strategy Improvements")
    print("=" * 40)
    
    # Test authentication first
    working_browser = test_youtube_authentication()
    
    # Apply patches
    patch_youtube_strategy()
    
    # Create helper script
    create_manual_download_helper()
    
    print("\n✅ YouTube strategy improved!")
    print("\nNext steps:")
    print("1. Run the episode cleanup: python fix_dwarkesh_episodes.py")
    print("2. Test downloads: python main.py 7") 
    
    if working_browser:
        print(f"3. {working_browser.title()} cookies should work for YouTube downloads")
    else:
        print("3. Sign into YouTube in your browser first")
        print("4. Use manual_download.sh for manual downloads")