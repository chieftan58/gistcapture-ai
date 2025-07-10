#!/usr/bin/env python3
"""Fix cookie format and test YouTube downloads"""

import asyncio
from pathlib import Path

def convert_to_netscape_format():
    """Convert cookie file to proper Netscape format"""
    input_file = Path("/home/codespace/.config/renaissance-weekly/cookies/youtube_cookies.txt")
    output_file = Path("/home/codespace/.config/renaissance-weekly/cookies/youtube_cookies_netscape.txt")
    
    print("Converting cookies to Netscape format...")
    
    with open(input_file, 'r') as f:
        lines = f.readlines()
    
    # Write Netscape format
    with open(output_file, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")
        
        for line in lines:
            if line.strip() and not line.startswith('#'):
                parts = line.strip().split('\t')
                if len(parts) >= 7:
                    name = parts[0]
                    value = parts[1] 
                    domain = parts[2]
                    path = parts[3]
                    expires = parts[4]
                    
                    # Convert to Netscape format: domain, flag, path, secure, expiration, name, value
                    secure = "TRUE" if "✓" in line else "FALSE"
                    flag = "TRUE" if domain.startswith('.') else "FALSE"
                    
                    # Convert timestamp to epoch if needed
                    if 'T' in expires and 'Z' in expires:
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                            expires = str(int(dt.timestamp()))
                        except:
                            expires = "0"
                    
                    netscape_line = f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
                    f.write(netscape_line)
    
    print(f"✅ Converted cookies to: {output_file}")
    return output_file

async def test_youtube_download():
    """Test YouTube download with proper cookies"""
    from renaissance_weekly.transcripts.audio_downloader import download_audio_with_ytdlp
    
    # Test with American Optimist Episode 118
    youtube_url = "https://www.youtube.com/watch?v=pRoKi4VL_5s"
    output_path = Path("/tmp/test_ep118_fixed.mp3")
    
    print(f"\nTesting YouTube download...")
    print(f"URL: {youtube_url}")
    print(f"Output: {output_path}")
    
    success = await download_audio_with_ytdlp(youtube_url, output_path)
    
    if success and output_path.exists():
        print(f"✅ SUCCESS! Downloaded {output_path.stat().st_size / 1_000_000:.1f} MB")
        output_path.unlink()  # Clean up
        return True
    else:
        print("❌ Download still failing")
        return False

def check_hanging_issue():
    """Check for potential hanging issues"""
    print("\nChecking for hanging issues...")
    
    # Check if there are stuck download state files
    temp_dir = Path("/workspaces/gistcapture-ai/temp")
    if temp_dir.exists():
        state_files = list(temp_dir.glob("download_state_*.json"))
        if state_files:
            print(f"Found {len(state_files)} download state files:")
            for f in state_files:
                print(f"  - {f}")
            
            # Clean them up
            for f in state_files:
                f.unlink()
            print("✅ Cleaned up state files")
    
    # Check for any leftover audio files
    audio_dir = Path("/workspaces/gistcapture-ai/audio")
    if audio_dir.exists():
        audio_files = list(audio_dir.glob("*.mp3"))
        print(f"Found {len(audio_files)} audio files in cache")

if __name__ == "__main__":
    print("FIXING COOKIES AND HANGING ISSUES")
    print("=" * 50)
    
    # Step 1: Fix cookie format
    netscape_file = convert_to_netscape_format()
    
    # Step 2: Update the cookie helper to use the new file
    from renaissance_weekly.fetchers.youtube_cookie_helper import YouTubeCookieHelper
    YouTubeCookieHelper.COOKIE_LOCATIONS.insert(0, netscape_file)
    
    # Step 3: Test download
    result = asyncio.run(test_youtube_download())
    
    # Step 4: Check for hanging issues
    check_hanging_issue()
    
    if result:
        print("\n✅ FIXED! YouTube downloads working")
        print("Now we can extend this to other podcasts")
    else:
        print("\n❌ Still having issues - may need manual approach")