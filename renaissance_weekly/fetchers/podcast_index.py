"""PodcastIndex.org API client"""

import os
import time
import hashlib
import aiohttp
from typing import Optional, Dict, List
from ..utils.logging import get_logger

logger = get_logger(__name__)


class PodcastIndexClient:
    """Client for PodcastIndex.org - free and comprehensive"""
    
    def __init__(self):
        self.api_key = os.getenv("PODCASTINDEX_API_KEY")
        self.api_secret = os.getenv("PODCASTINDEX_API_SECRET")
        self.base_url = "https://api.podcastindex.org/api/1.0"
    
    def _get_headers(self):
        """Generate auth headers for PodcastIndex"""
        if not self.api_key or not self.api_secret:
            return None
            
        api_header_time = str(int(time.time()))
        hash_input = self.api_key + self.api_secret + api_header_time
        sha1_hash = hashlib.sha1(hash_input.encode()).hexdigest()
        
        return {
            "X-Auth-Key": self.api_key,
            "X-Auth-Date": api_header_time,
            "Authorization": sha1_hash,
            "User-Agent": "Renaissance Weekly"
        }
    
    async def search_podcast(self, podcast_name: str) -> Optional[Dict]:
        """Search for podcast by name"""
        headers = self._get_headers()
        if not headers:
            return None
            
        try:
            url = f"{self.base_url}/search/byterm"
            params = {"q": podcast_name, "val": "podcast"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("feeds"):
                            return data["feeds"][0]  # Return first match
        except Exception as e:
            logger.error(f"PodcastIndex search error: {e}")
        
        return None
    
    async def get_episodes(self, feed_id: int, max_results: int = 20) -> List[Dict]:
        """Get recent episodes for a podcast"""
        headers = self._get_headers()
        if not headers:
            return []
            
        try:
            url = f"{self.base_url}/episodes/byfeedid"
            params = {"id": feed_id, "max": max_results}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("items", [])
        except Exception as e:
            logger.error(f"PodcastIndex episodes error: {e}")
        
        return []