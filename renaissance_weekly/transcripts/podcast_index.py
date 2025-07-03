"""Podcast Index API integration for finding podcast episodes and transcripts"""

import hashlib
import time
from typing import Optional, Dict, List
import aiohttp
from datetime import datetime
import os

from ..utils.logging import get_logger

logger = get_logger(__name__)


class PodcastIndexAPI:
    """
    Interface to the Podcast Index API for finding episodes and transcripts.
    
    Podcast Index is a free, open podcast directory that aggregates data
    from multiple sources including transcript URLs.
    
    API documentation: https://podcastindex-org.github.io/docs-api/
    """
    
    def __init__(self):
        self.base_url = "https://api.podcastindex.org/api/1.0"
        self.api_key = os.getenv('PODCASTINDEX_API_KEY', '')
        self.api_secret = os.getenv('PODCASTINDEX_API_SECRET', '')
        
        if not self.api_key or not self.api_secret:
            logger.warning("Podcast Index API credentials not found. Set PODCASTINDEX_API_KEY and PODCASTINDEX_API_SECRET in .env")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for Podcast Index API"""
        if not self.api_key or not self.api_secret:
            return {}
        
        # Current time in seconds
        api_header_time = str(int(time.time()))
        
        # Create hash for authentication
        data_to_hash = self.api_key + self.api_secret + api_header_time
        sha_hash = hashlib.sha1(data_to_hash.encode()).hexdigest()
        
        return {
            "X-Auth-Key": self.api_key,
            "X-Auth-Date": api_header_time,
            "Authorization": sha_hash,
            "User-Agent": "Renaissance Weekly Podcast Intelligence"
        }
    
    async def search_podcast(self, podcast_name: str) -> Optional[Dict]:
        """Search for a podcast by name and return its details"""
        if not self.api_key:
            return None
            
        try:
            headers = self._get_auth_headers()
            params = {
                "q": podcast_name,
                "max": 5
            }
            
            timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/search/byterm"
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        feeds = data.get('feeds', [])
                        
                        # Find best match
                        for feed in feeds:
                            if podcast_name.lower() in feed.get('title', '').lower():
                                logger.info(f"Found podcast on Podcast Index: {feed.get('title')}")
                                return feed
                        
                        # Return first result if no exact match
                        if feeds:
                            return feeds[0]
                    else:
                        logger.debug(f"Podcast Index search failed: {response.status}")
                        
        except Exception as e:
            logger.debug(f"Error searching Podcast Index: {e}")
        
        return None
    
    async def get_episodes_with_transcripts(self, podcast_id: int, days_back: int = 30) -> List[Dict]:
        """Get recent episodes from a podcast that have transcripts"""
        if not self.api_key:
            return []
            
        try:
            headers = self._get_auth_headers()
            params = {
                "id": podcast_id,
                "max": 100,  # Get more episodes to find ones with transcripts
                "fulltext": "true"  # Include full episode data
            }
            
            timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/episodes/byfeedid"
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        episodes = data.get('items', [])
                        
                        # Filter episodes with transcripts
                        episodes_with_transcripts = []
                        cutoff_time = time.time() - (days_back * 24 * 60 * 60)
                        
                        for episode in episodes:
                            # Check if episode is recent enough
                            if episode.get('datePublished', 0) < cutoff_time:
                                continue
                            
                            # Check for transcript
                            if episode.get('transcriptUrl'):
                                episodes_with_transcripts.append(episode)
                                logger.info(f"Found transcript URL via Podcast Index: {episode.get('title')}")
                        
                        return episodes_with_transcripts
                    
        except Exception as e:
            logger.debug(f"Error getting episodes from Podcast Index: {e}")
        
        return []
    
    async def find_episode_transcript(self, episode_title: str, podcast_name: str) -> Optional[str]:
        """
        Find transcript URL for a specific episode.
        
        Args:
            episode_title: Title of the episode
            podcast_name: Name of the podcast
            
        Returns:
            Transcript URL if found, None otherwise
        """
        if not self.api_key:
            return None
        
        # First, find the podcast
        podcast = await self.search_podcast(podcast_name)
        if not podcast:
            return None
        
        podcast_id = podcast.get('id')
        if not podcast_id:
            return None
        
        try:
            # Search for the specific episode
            headers = self._get_auth_headers()
            
            # Clean episode title for search
            import re
            clean_title = re.sub(r'^#?\d+:?\s*', '', episode_title)  # Remove episode numbers
            
            params = {
                "id": podcast_id,
                "q": clean_title[:50],  # Limit search query length
                "max": 10
            }
            
            timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/search/byterm"
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = data.get('items', [])
                        
                        # Look for episode with transcript
                        for item in items:
                            if item.get('transcriptUrl'):
                                # Verify it's the right episode by checking title similarity
                                item_title = item.get('title', '').lower()
                                if any(word in item_title for word in clean_title.lower().split()[:5]):
                                    logger.info(f"✅ Found transcript URL via Podcast Index: {item.get('transcriptUrl')}")
                                    return item.get('transcriptUrl')
                        
        except Exception as e:
            logger.debug(f"Error finding episode transcript: {e}")
        
        return None
    
    async def get_podcast_metadata(self, podcast_name: str) -> Optional[Dict]:
        """Get comprehensive metadata about a podcast"""
        podcast = await self.search_podcast(podcast_name)
        if not podcast:
            return None
        
        return {
            'id': podcast.get('id'),
            'title': podcast.get('title'),
            'url': podcast.get('url'),
            'description': podcast.get('description'),
            'author': podcast.get('author'),
            'language': podcast.get('language'),
            'categories': podcast.get('categories', {}),
            'itunesId': podcast.get('itunesId'),
            'image': podcast.get('image'),
            'newestItemPubdate': podcast.get('newestItemPubdate'),
            'episodeCount': podcast.get('episodeCount'),
            'explicit': podcast.get('explicit'),
            'link': podcast.get('link'),
        }
    
    async def check_live_status(self, podcast_id: int) -> bool:
        """Check if a podcast is currently live streaming"""
        if not self.api_key:
            return False
            
        try:
            headers = self._get_auth_headers()
            
            timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.base_url}/podcasts/live"
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        live_feeds = data.get('feeds', [])
                        
                        for feed in live_feeds:
                            if feed.get('id') == podcast_id:
                                return True
                                
        except Exception as e:
            logger.debug(f"Error checking live status: {e}")
        
        return False