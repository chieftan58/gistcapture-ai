"""Centralized cookie management for all platforms"""

from pathlib import Path
from typing import Optional, Dict, List, Tuple
import shutil
import time
from datetime import datetime, timedelta
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
                # Check if cookies are still valid
                is_valid, days_remaining = self.check_cookie_validity(protected_file)
                if is_valid:
                    if days_remaining is not None and days_remaining < 7:
                        logger.warning(f"⚠️ {platform} cookies expire in {days_remaining} days!")
                    logger.info(f"🔒 Using protected manual {platform} cookie file")
                    return protected_file
                else:
                    logger.error(f"❌ Protected {platform} cookies have expired!")
        
        # Fall back to regular cookie file
        if platform in self.regular_cookies:
            regular_file = self.regular_cookies[platform]
            if regular_file.exists():
                # Check if cookies are still valid
                is_valid, days_remaining = self.check_cookie_validity(regular_file)
                if is_valid:
                    if days_remaining is not None and days_remaining < 7:
                        logger.warning(f"⚠️ {platform} cookies expire in {days_remaining} days!")
                    logger.info(f"📄 Using regular {platform} cookie file")
                    return regular_file
                else:
                    logger.error(f"❌ Regular {platform} cookies have expired!")
        
        logger.debug(f"No valid cookie file found for {platform}")
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
    
    def check_cookie_validity(self, cookie_file: Path) -> Tuple[bool, Optional[int]]:
        """
        Check if cookies in file are still valid
        
        Returns:
            Tuple of (is_valid, days_remaining)
            - is_valid: True if at least some cookies are still valid
            - days_remaining: Days until earliest expiration (None if no expiration found)
        """
        try:
            with open(cookie_file, 'r') as f:
                content = f.read()
            
            # Parse Netscape HTTP Cookie format
            # Format: domain flag path secure expiry name value
            current_time = int(time.time())
            earliest_expiry = None
            has_session_cookies = False
            
            for line in content.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 5:
                    try:
                        expiry = int(parts[4])
                        if expiry == 0:
                            # Session cookie (expires when browser closes)
                            has_session_cookies = True
                        elif expiry > current_time:
                            # Future expiration
                            if earliest_expiry is None or expiry < earliest_expiry:
                                earliest_expiry = expiry
                        # If expiry < current_time, cookie has expired
                    except (ValueError, IndexError):
                        # Invalid format, skip this line
                        continue
            
            # Check results
            if earliest_expiry is None and not has_session_cookies:
                # No valid cookies found
                return False, None
            
            if earliest_expiry:
                days_remaining = (earliest_expiry - current_time) // 86400  # Convert to days
                if days_remaining < 0:
                    return False, 0
                return True, days_remaining
            else:
                # Only session cookies (considered valid until proven otherwise)
                return True, None
                
        except Exception as e:
            logger.warning(f"Could not parse cookie file {cookie_file}: {e}")
            # If we can't parse, assume cookies are valid (backward compatibility)
            return True, None
    
    def get_cookie_status(self, platform: str) -> Dict[str, any]:
        """Get detailed status of cookies for a platform"""
        platform = platform.lower()
        status = {
            'platform': platform,
            'has_cookies': False,
            'is_valid': False,
            'is_expired': False,
            'days_remaining': None,
            'warning': None,
            'file_type': None  # 'protected' or 'regular'
        }
        
        # Check protected file first
        if platform in self.protected_cookies:
            protected_file = self.protected_cookies[platform]
            if protected_file.exists():
                is_valid, days_remaining = self.check_cookie_validity(protected_file)
                status['has_cookies'] = True
                status['is_valid'] = is_valid
                status['is_expired'] = not is_valid
                status['days_remaining'] = days_remaining
                status['file_type'] = 'protected'
                
                if not is_valid:
                    status['warning'] = f'{platform.capitalize()} cookies have expired! Please update them.'
                elif days_remaining is not None and days_remaining < 7:
                    status['warning'] = f'{platform.capitalize()} cookies expire in {days_remaining} days.'
                
                return status
        
        # Check regular file
        if platform in self.regular_cookies:
            regular_file = self.regular_cookies[platform]
            if regular_file.exists():
                is_valid, days_remaining = self.check_cookie_validity(regular_file)
                status['has_cookies'] = True
                status['is_valid'] = is_valid
                status['is_expired'] = not is_valid
                status['days_remaining'] = days_remaining
                status['file_type'] = 'regular'
                
                if not is_valid:
                    status['warning'] = f'{platform.capitalize()} cookies have expired! Please update them.'
                elif days_remaining is not None and days_remaining < 7:
                    status['warning'] = f'{platform.capitalize()} cookies expire in {days_remaining} days.'
                
                return status
        
        # No cookies found
        status['warning'] = f'No {platform} cookies found.'
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