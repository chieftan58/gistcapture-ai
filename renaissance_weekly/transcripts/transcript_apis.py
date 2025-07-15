"""
Official transcript aggregator API integrations.
Provides access to high-quality transcripts from services like Descript, Otter.ai, etc.
"""

import os
import asyncio
import aiohttp
from typing import Optional, Dict, List
import hashlib
import hmac
import time
import json
from urllib.parse import urlencode

from ..utils.logging import get_logger
from ..models import Episode
from .spotify_transcript import SpotifyTranscriptFetcher

logger = get_logger(__name__)


class TranscriptAPIClient:
    """Base class for transcript API clients"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session = None
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for transcript. To be implemented by subclasses."""
        raise NotImplementedError


class PodcastIndexClient(TranscriptAPIClient):
    """
    Podcast Index API client for finding transcripts.
    Free API that aggregates podcast data including transcripts.
    """
    
    def __init__(self):
        self.api_key = os.getenv('PODCASTINDEX_API_KEY')
        self.api_secret = os.getenv('PODCASTINDEX_API_SECRET')
        self.base_url = "https://api.podcastindex.org/api/1.0"
        super().__init__(self.api_key)
        
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for Podcast Index API"""
        if not self.api_key or not self.api_secret:
            return {}
            
        # Current time in seconds
        api_time = str(int(time.time()))
        
        # Create auth hash
        data = self.api_key + self.api_secret + api_time
        api_hash = hashlib.sha1(data.encode()).hexdigest()
        
        return {
            'X-Auth-Key': self.api_key,
            'X-Auth-Date': api_time,
            'Authorization': api_hash,
            'User-Agent': 'Renaissance Weekly/1.0'
        }
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for episode transcript using Podcast Index API"""
        if not self.api_key or not self.api_secret:
            return None
            
        try:
            session = await self._get_session()
            headers = self._get_auth_headers()
            
            # Search by podcast + episode title
            search_params = {
                'q': f"{episode.podcast} {episode.title}",
                'max': 5
            }
            
            search_url = f"{self.base_url}/search/byterm?" + urlencode(search_params)
            
            async with session.get(search_url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Podcast Index API error: {response.status}")
                    return None
                    
                data = await response.json()
                
                if data.get('status') != 'true' or not data.get('feeds'):
                    return None
                
                # Look for matching podcast
                for feed in data['feeds']:
                    if episode.podcast.lower() in feed.get('title', '').lower():
                        feed_id = feed.get('id')
                        if feed_id:
                            # Get episodes for this feed
                            return await self._get_episode_transcript(feed_id, episode, headers)
                            
        except Exception as e:
            logger.error(f"Podcast Index search error: {e}")
            
        return None
        
    async def _get_episode_transcript(self, feed_id: int, episode: Episode, headers: Dict) -> Optional[str]:
        """Get transcript for specific episode"""
        try:
            session = await self._get_session()
            
            # Get recent episodes
            episodes_url = f"{self.base_url}/episodes/byfeedid?id={feed_id}&max=50"
            
            async with session.get(episodes_url, headers=headers) as response:
                if response.status != 200:
                    return None
                    
                data = await response.json()
                
                if not data.get('items'):
                    return None
                
                # Find matching episode
                episode_title_lower = episode.title.lower()
                for item in data['items']:
                    item_title = item.get('title', '').lower()
                    
                    # Check title match
                    if (episode_title_lower in item_title or 
                        item_title in episode_title_lower or
                        self._fuzzy_match(episode_title_lower, item_title)):
                        
                        # Check for transcript
                        transcript_url = item.get('transcriptUrl')
                        if transcript_url:
                            return await self._fetch_transcript(transcript_url)
                            
        except Exception as e:
            logger.error(f"Podcast Index episode fetch error: {e}")
            
        return None
        
    async def _fetch_transcript(self, transcript_url: str) -> Optional[str]:
        """Fetch transcript from URL"""
        try:
            session = await self._get_session()
            
            async with session.get(transcript_url) as response:
                if response.status == 200:
                    content = await response.text()
                    
                    # Handle different transcript formats
                    if transcript_url.endswith('.json'):
                        # Parse JSON transcript format
                        data = json.loads(content)
                        if isinstance(data, dict) and 'transcript' in data:
                            return data['transcript']
                        elif isinstance(data, list):
                            # Join segments
                            return ' '.join(item.get('text', '') for item in data)
                    elif transcript_url.endswith('.srt') or transcript_url.endswith('.vtt'):
                        # Parse subtitle format
                        return self._parse_subtitle_format(content)
                    else:
                        # Assume plain text
                        return content
                        
        except Exception as e:
            logger.error(f"Transcript fetch error: {e}")
            
        return None
        
    def _parse_subtitle_format(self, content: str) -> str:
        """Parse SRT/VTT subtitle format to plain text"""
        lines = content.split('\n')
        transcript_lines = []
        
        for line in lines:
            line = line.strip()
            # Skip timecodes and sequence numbers
            if (not line or 
                line.isdigit() or 
                '-->' in line or
                line.startswith('WEBVTT')):
                continue
            transcript_lines.append(line)
            
        return ' '.join(transcript_lines)
        
    def _fuzzy_match(self, str1: str, str2: str) -> bool:
        """Simple fuzzy matching for episode titles"""
        # Remove common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'ep', 'episode'}
        
        words1 = set(word for word in str1.split() if word not in stop_words and len(word) > 2)
        words2 = set(word for word in str2.split() if word not in stop_words and len(word) > 2)
        
        # Check if significant overlap
        common = words1 & words2
        if not words1 or not words2:
            return False
            
        overlap_ratio = len(common) / min(len(words1), len(words2))
        return overlap_ratio >= 0.6


class DescriptClient(TranscriptAPIClient):
    """
    Descript API client for finding transcripts.
    Note: This is a placeholder - Descript API requires partnership.
    """
    
    def __init__(self):
        self.api_key = os.getenv('DESCRIPT_API_KEY')
        self.base_url = "https://api.descript.com/v2"
        super().__init__(self.api_key)
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for episode transcript using Descript API"""
        if not self.api_key:
            return None
            
        # Note: Actual implementation would require Descript API documentation
        # This is a placeholder showing the structure
        logger.debug("Descript API not yet implemented")
        return None


class OtterAIClient(TranscriptAPIClient):
    """
    Otter.ai API client for finding transcripts.
    Note: This is a placeholder - Otter.ai API requires enterprise plan.
    """
    
    def __init__(self):
        self.api_key = os.getenv('OTTER_AI_API_KEY')
        self.base_url = "https://api.otter.ai/v1"
        super().__init__(self.api_key)
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for episode transcript using Otter.ai API"""
        if not self.api_key:
            return None
            
        # Note: Actual implementation would require Otter.ai API documentation
        # This is a placeholder showing the structure
        logger.debug("Otter.ai API not yet implemented")
        return None


class SpeechmaticsClient(TranscriptAPIClient):
    """
    Speechmatics API client for finding transcripts.
    Professional transcription service with search capabilities.
    """
    
    def __init__(self):
        self.api_key = os.getenv('SPEECHMATICS_API_KEY')
        self.base_url = "https://api.speechmatics.com/v1"
        super().__init__(self.api_key)
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for episode transcript using Speechmatics API"""
        if not self.api_key:
            return None
            
        # Note: Implementation would require Speechmatics API documentation
        logger.debug("Speechmatics API not yet implemented")
        return None


class SpotifyClient(TranscriptAPIClient):
    """
    Spotify transcript/content client.
    Uses Spotify API to fetch episode information and available content.
    """
    
    def __init__(self):
        super().__init__()
        self.fetcher = SpotifyTranscriptFetcher()
        
    async def __aenter__(self):
        await self.fetcher.__aenter__()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.fetcher.__aexit__(exc_type, exc_val, exc_tb)
        
    async def search_transcript(self, episode: Episode) -> Optional[str]:
        """Search for transcript or content via Spotify API"""
        try:
            # Use the Spotify transcript fetcher
            content = await self.fetcher.get_transcript(episode)
            if content:
                logger.info(f"✅ Found Spotify content for: {episode.title}")
                return content
        except Exception as e:
            logger.error(f"Spotify client error: {e}")
        
        return None


class TranscriptAPIAggregator:
    """
    Aggregates multiple transcript API sources.
    Tries each API in order until a transcript is found.
    """
    
    def __init__(self):
        # Don't instantiate clients here - create them in find_transcript
        self.client_classes = [
            PodcastIndexClient,
            SpotifyClient,  # Add Spotify before less reliable sources
            DescriptClient,
            OtterAIClient,
            SpeechmaticsClient,
        ]
        
    async def find_transcript(self, episode: Episode) -> Optional[str]:
        """Try all available transcript APIs"""
        for client_class in self.client_classes:
            try:
                # Create client instance within async context
                client = client_class()
                async with client:
                    logger.info(f"🔍 Trying {client.__class__.__name__} for transcript...")
                    transcript = await client.search_transcript(episode)
                    
                    if transcript and len(transcript) > 1000:  # Minimum length check
                        logger.info(f"✅ Found transcript via {client.__class__.__name__}")
                        return transcript
                        
            except Exception as e:
                logger.error(f"Error with {client_class.__name__}: {e}")
                continue
                
        return None
    
    async def cleanup(self):
        """Cleanup method for compatibility - no longer needed"""
        # Clients are now created and cleaned up within find_transcript
        pass