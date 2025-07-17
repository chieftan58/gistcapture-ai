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
        
        # Simplified: Use only one set of cookie files
        self.cookie_files = {
            'youtube': self.cookie_dir / 'youtube_cookies.txt',
            'spotify': self.cookie_dir / 'spotify_cookies.txt',
            'apple': self.cookie_dir / 'apple_cookies.txt'
        }
    
    def get_cookie_file(self, platform: str) -> Optional[Path]:
        """Get the cookie file for a platform"""
        platform = platform.lower()
        
        if platform in self.cookie_files:
            cookie_file = self.cookie_files[platform]
            if cookie_file.exists():
                # Check if cookies are still valid
                is_valid, days_remaining = self.check_cookie_validity(cookie_file)
                if is_valid:
                    if days_remaining is not None and days_remaining < 7:
                        logger.warning(f"⚠️ {platform} cookies expire in {days_remaining} days!")
                    logger.info(f"🍪 Using {platform} cookie file")
                    return cookie_file
                else:
                    logger.error(f"❌ {platform} cookies have expired! Please run: python update_cookies.py")
        
        logger.debug(f"No valid cookie file found for {platform}")
        return None
    
    def update_cookie_file(self, platform: str, source_file: Path) -> bool:
        """Update the cookie file for a platform"""
        platform = platform.lower()
        
        if platform not in self.cookie_files:
            logger.error(f"Unknown platform: {platform}")
            return False
        
        if not source_file.exists():
            logger.error(f"Source file does not exist: {source_file}")
            return False
        
        try:
            cookie_file = self.cookie_files[platform]
            shutil.copy2(source_file, cookie_file)
            
            logger.info(f"✅ Updated {platform} cookie file at: {cookie_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update cookie file: {e}")
            return False
    
    def list_cookies(self) -> Dict[str, Optional[Path]]:
        """List all available cookie files"""
        status = {}
        
        for platform in ['youtube', 'spotify', 'apple']:
            cookie_file = self.cookie_files[platform]
            status[platform] = cookie_file if cookie_file.exists() else None
        
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
            'warning': None
        }
        
        if platform in self.cookie_files:
            cookie_file = self.cookie_files[platform]
            if cookie_file.exists():
                is_valid, days_remaining = self.check_cookie_validity(cookie_file)
                status['has_cookies'] = True
                status['is_valid'] = is_valid
                status['is_expired'] = not is_valid
                status['days_remaining'] = days_remaining
                
                if not is_valid:
                    status['warning'] = f'{platform.capitalize()} cookies have expired! Please run: python update_cookies.py'
                elif days_remaining is not None and days_remaining < 7:
                    status['warning'] = f'{platform.capitalize()} cookies expire in {days_remaining} days.'
                
                return status
        
        # No cookies found
        status['warning'] = f'No {platform} cookies found. Please run: python update_cookies.py'
        return status
    
    def setup_all_cookies(self):
        """Interactive setup for all cookie files"""
        print("\nCookie Setup for Renaissance Weekly")
        print("=" * 50)
        print("\nThis will help you set up cookies for:")
        print("1. YouTube (for American Optimist, Dwarkesh, etc.)")
        print("2. Spotify (backup for some podcasts)")
        print("3. Apple Podcasts (additional fallback)")
        print("\nCurrent status:")
        
        status = self.list_cookies()
        for platform, cookie_file in status.items():
            print(f"\n{platform.upper()}:")
            if cookie_file:
                print(f"  ✅ Cookie file: {cookie_file.name}")
                is_valid, days_remaining = self.check_cookie_validity(cookie_file)
                if is_valid:
                    if days_remaining:
                        print(f"     Valid (expires in {days_remaining} days)")
                    else:
                        print(f"     Valid (no expiry found)")
                else:
                    print(f"     ❌ Expired")
            else:
                print(f"  ❌ Not found")
        
        print("\n" + "-" * 50)
        print("\nTo update cookies:")
        print("1. Run: python update_cookies.py")
        print("2. Follow the interactive prompts")
        print("3. The script will validate and test your cookies")


    def get_youtube_auth_error_info(self, error_msg: str) -> Optional[Dict[str, str]]:
        """Check if error is YouTube authentication related"""
        auth_error_patterns = [
            ("Sign in to confirm you're not a bot", "YouTube requires authentication"),
            ("This video is unavailable", "Video unavailable (may need auth)"),
            ("Please sign in", "YouTube sign-in required"),
            ("bot detection", "YouTube bot detection triggered"),
            ("403", "Access forbidden (authentication may be required)")
        ]
        
        for pattern, description in auth_error_patterns:
            if pattern.lower() in error_msg.lower():
                return {
                    'error_type': 'youtube_auth',
                    'description': description,
                    'cookie_status': self.get_cookie_status('youtube')
                }
        
        return None


# Global instance
cookie_manager = CookieManager()