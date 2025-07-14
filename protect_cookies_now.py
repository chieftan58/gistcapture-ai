#!/usr/bin/env python3
"""Protect all cookie files immediately"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from renaissance_weekly.utils.cookie_manager import cookie_manager

def main():
    print("🍪 Protecting Cookie Files")
    print("=" * 60)
    
    # Protect all existing cookie files
    platforms_protected = []
    
    for platform in ['youtube', 'spotify', 'apple']:
        regular_file = cookie_manager.regular_cookies[platform]
        protected_file = cookie_manager.protected_cookies[platform]
        
        if regular_file.exists():
            if protected_file.exists():
                print(f"\n{platform.upper()}: Already protected ✅")
            else:
                print(f"\n{platform.upper()}: Protecting cookie file...")
                if cookie_manager.protect_cookie_file(platform, regular_file):
                    platforms_protected.append(platform)
                    print(f"  ✅ Protected as: {protected_file.name}")
                    print(f"  📁 Full path: {protected_file}")
                else:
                    print(f"  ❌ Failed to protect {platform} cookies")
        else:
            print(f"\n{platform.upper()}: No cookie file found ❌")
    
    # Show final status
    print("\n" + "=" * 60)
    print("\nFINAL STATUS:")
    print("-" * 30)
    
    status = cookie_manager.list_cookies()
    for platform, files in status.items():
        print(f"\n{platform.upper()}:")
        if files['protected']:
            size = files['protected'].stat().st_size
            print(f"  ✅ Protected file: {size} bytes")
            print(f"     {files['protected']}")
        else:
            print(f"  ❌ No protected file")
    
    print("\n" + "=" * 60)
    print("\n✅ Cookie protection complete!")
    print("\nThe system will now use these protected files:")
    print("- youtube_manual_do_not_overwrite.txt")
    print("- spotify_manual_do_not_overwrite.txt") 
    print("- apple_manual_do_not_overwrite.txt")
    print("\nThese files cannot be overwritten by yt-dlp or other tools.")
    
    if platforms_protected:
        print(f"\n🎉 Successfully protected {len(platforms_protected)} cookie file(s)!")

if __name__ == "__main__":
    main()