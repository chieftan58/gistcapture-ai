"""Centralized cookie management for all platforms"""

from pathlib import Path
from typing import Optional, Dict
import shutil
from ..utils.logging import get_logger

logger = get_logger(__name__)


class CookieManager:
    """Manage cookies for YouTube, Spotify, and Apple Podcasts"""
    
    def __init__(self):
        self.cookie_dir = Path.home() / '.config' / 'renaissance-weekly' / 'cookies'
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        
        # Protected cookie files that won't be overwritten
        self.protected_cookies = {
            'youtube': self.cookie_dir / 'youtube_manual_do_not_overwrite.txt',
            'spotify': self.cookie_dir / 'spotify_manual_do_not_overwrite.txt',
            'apple': self.cookie_dir / 'apple_manual_do_not_overwrite.txt'
        }
        
        # Regular cookie files (may be overwritten by tools)
        self.regular_cookies = {
            'youtube': self.cookie_dir / 'youtube_cookies.txt',
            'spotify': self.cookie_dir / 'spotify_cookies.txt',
            'apple': self.cookie_dir / 'apple_cookies.txt'
        }
    
    def get_cookie_file(self, platform: str) -> Optional[Path]:
        """Get the best available cookie file for a platform"""
        platform = platform.lower()
        
        # First check for protected manual cookie file
        if platform in self.protected_cookies:
            protected_file = self.protected_cookies[platform]
            if protected_file.exists():
                logger.info(f"🔒 Using protected manual {platform} cookie file")
                return protected_file
        
        # Fall back to regular cookie file
        if platform in self.regular_cookies:
            regular_file = self.regular_cookies[platform]
            if regular_file.exists():
                logger.info(f"📄 Using regular {platform} cookie file")
                return regular_file
        
        logger.debug(f"No cookie file found for {platform}")
        return None
    
    def protect_cookie_file(self, platform: str, source_file: Path) -> bool:
        """Copy a cookie file to the protected location"""
        platform = platform.lower()
        
        if platform not in self.protected_cookies:
            logger.error(f"Unknown platform: {platform}")
            return False
        
        if not source_file.exists():
            logger.error(f"Source file does not exist: {source_file}")
            return False
        
        try:
            protected_file = self.protected_cookies[platform]
            shutil.copy2(source_file, protected_file)
            
            # Make it read-only to prevent overwriting
            protected_file.chmod(0o444)
            
            logger.info(f"✅ Protected {platform} cookie file created at: {protected_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to protect cookie file: {e}")
            return False
    
    def list_cookies(self) -> Dict[str, Dict[str, Optional[Path]]]:
        """List all available cookie files"""
        status = {}
        
        for platform in ['youtube', 'spotify', 'apple']:
            status[platform] = {
                'protected': self.protected_cookies[platform] if self.protected_cookies[platform].exists() else None,
                'regular': self.regular_cookies[platform] if self.regular_cookies[platform].exists() else None
            }
        
        return status
    
    def setup_all_cookies(self):
        """Interactive setup for all cookie files"""
        print("\nCookie Setup for Renaissance Weekly")
        print("=" * 50)
        print("\nThis will help you set up cookies for:")
        print("1. YouTube (for American Optimist, Dwarkesh, etc.)")
        print("2. Spotify (backup for some podcasts)")
        print("3. Apple Podcasts (additional fallback)")
        print("\nProtected files won't be overwritten by tools.")
        print("\nCurrent status:")
        
        status = self.list_cookies()
        for platform, files in status.items():
            print(f"\n{platform.upper()}:")
            if files['protected']:
                print(f"  ✅ Protected: {files['protected'].name}")
            else:
                print(f"  ❌ Protected: Not found")
            
            if files['regular']:
                print(f"  📄 Regular: {files['regular'].name}")
            else:
                print(f"  ❌ Regular: Not found")
        
        print("\n" + "-" * 50)
        print("\nTo set up cookies:")
        print("1. Export cookies from your browser using 'cookies.txt' extension")
        print("2. Save them in: ~/.config/renaissance-weekly/cookies/")
        print("3. Name them: youtube_cookies.txt, spotify_cookies.txt, apple_cookies.txt")
        print("4. Run this script again to protect them")
        
        # Offer to protect existing files
        for platform in ['youtube', 'spotify', 'apple']:
            regular_file = self.regular_cookies[platform]
            protected_file = self.protected_cookies[platform]
            
            if regular_file.exists() and not protected_file.exists():
                response = input(f"\nProtect existing {platform} cookies? (y/n): ")
                if response.lower() == 'y':
                    self.protect_cookie_file(platform, regular_file)


# Global instance
cookie_manager = CookieManager()