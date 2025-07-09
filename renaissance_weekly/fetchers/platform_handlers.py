"""
Platform-specific handlers for problematic podcast hosts
"""

import aiohttp
from typing import Optional
from ..utils.logging import get_logger

logger = get_logger(__name__)

class MegaphoneHandler:
    """Handle Megaphone CDN downloads (All-In podcast)"""
    
    @staticmethod
    async def get_audio_url(episode_url: str) -> Optional[str]:
        """Get working audio URL from Megaphone"""
        if 'megaphone.fm' not in episode_url:
            return None
        
        # Megaphone requires specific headers
        headers = {
            'User-Agent': 'AppleCoreMedia/1.0.0.0 (iPhone; U; CPU OS 14_0 like Mac OS X)',
            'Accept': 'audio/mpeg, audio/mp4, audio/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'identity',  # No compression
            'Range': 'bytes=0-1',  # Test with range request
            'Connection': 'keep-alive'
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # First, try a HEAD request to check if it's accessible
                async with session.head(episode_url, headers=headers, allow_redirects=True) as response:
                    if response.status in [200, 206, 302, 301]:
                        # If redirect, get final URL
                        final_url = str(response.url)
                        
                        # Check content type
                        content_type = response.headers.get('Content-Type', '')
                        if 'audio' in content_type or response.status in [301, 302]:
                            logger.info(f"Megaphone URL accessible: {final_url[:80]}...")
                            return final_url
                        
                # If HEAD fails, try GET with range
                headers['Range'] = 'bytes=0-1024'  # Get first 1KB
                async with session.get(episode_url, headers=headers, allow_redirects=True) as response:
                    if response.status in [200, 206]:
                        content_type = response.headers.get('Content-Type', '')
                        if 'audio' in content_type:
                            return str(response.url)
                            
        except Exception as e:
            logger.debug(f"Megaphone handler error: {e}")
        
        return None


class LibsynHandler:
    """Handle Libsyn downloads (The Drive podcast)"""
    
    @staticmethod
    async def get_audio_url(episode_url: str) -> Optional[str]:
        """Get working audio URL from Libsyn"""
        if 'libsyn.com' not in episode_url:
            return None
        
        # Libsyn sometimes needs referrer
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'audio/*,*/*',
            'Referer': 'https://peterattiadrive.com/',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(episode_url, headers=headers, allow_redirects=True) as response:
                    if response.status == 200:
                        return str(response.url)
                    elif response.status == 403:
                        # Try with different user agent
                        headers['User-Agent'] = 'Podcasts/1.0'
                        async with session.head(episode_url, headers=headers, allow_redirects=True) as retry:
                            if retry.status == 200:
                                return str(retry.url)
                                
        except Exception as e:
            logger.debug(f"Libsyn handler error: {e}")
        
        return None