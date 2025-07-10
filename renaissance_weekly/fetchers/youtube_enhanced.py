"""Enhanced YouTube fetching for podcast episodes with intelligent search strategies"""

import re
import os
import asyncio
import aiohttp
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import json

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class YouTubeEnhancedFetcher:
    """Enhanced YouTube fetcher with smarter search strategies for podcasts"""
    
    # Podcast-specific YouTube channel mappings
    CHANNEL_MAPPINGS = {
        "American Optimist": {
            "channel_id": "UCBZjspOTvT5nyDWcHAfaVZQ",  # Joe Lonsdale's channel
            "channel_name": "Joe Lonsdale",
            "search_variants": ["Joe Lonsdale American Optimist", "American Optimist Podcast"]
        },
        "Dwarkesh Podcast": {
            "channel_id": "UCCaEbmz8gvyJHXFR42uSbXQ",  # Dwarkesh Patel's channel
            "channel_name": "Dwarkesh Patel",
            "search_variants": ["Dwarkesh Patel", "Dwarkesh Podcast"]
        },
        "Tim Ferriss": {
            "channel_id": "UCznv7Vf9nBdJYvBagFdAHWw",  # Tim Ferriss channel
            "channel_name": "Tim Ferriss",
            "search_variants": ["Tim Ferriss Show", "Tim Ferriss Podcast"]
        },
        "The Drive": {
            "channel_id": "UC1W8ShdwtUKhJgPVYoOlzRg",  # Peter Attia's channel
            "channel_name": "Peter Attia MD",
            "search_variants": ["The Drive Peter Attia", "Peter Attia The Drive", "The Drive Podcast"]
        }
    }
    
    def __init__(self):
        self.session = None
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY')
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def find_episode_on_youtube(self, episode: Episode) -> Optional[str]:
        """
        Find episode on YouTube using multiple search strategies.
        Returns YouTube URL if found.
        """
        logger.info(f"🎥 Searching YouTube for: {episode.podcast} - {episode.title}")
        
        # Strategy 1: Use channel-specific search if available
        if episode.podcast in self.CHANNEL_MAPPINGS:
            url = await self._search_specific_channel(episode)
            if url:
                return url
        
        # Strategy 2: Try date-based search
        url = await self._search_by_date(episode)
        if url:
            return url
        
        # Strategy 3: Try guest name extraction
        url = await self._search_by_guest(episode)
        if url:
            return url
        
        # Strategy 4: Generic search with multiple query variations
        url = await self._search_generic(episode)
        if url:
            return url
        
        logger.warning(f"❌ Could not find {episode.title} on YouTube")
        return None
    
    async def _search_specific_channel(self, episode: Episode) -> Optional[str]:
        """Search within a specific YouTube channel"""
        channel_info = self.CHANNEL_MAPPINGS.get(episode.podcast)
        if not channel_info:
            return None
        
        logger.info(f"🔍 Searching {channel_info['channel_name']} channel on YouTube")
        
        # Extract key terms from episode title
        title_terms = self._extract_search_terms(episode.title)
        
        # Special handling for American Optimist
        if episode.podcast == "American Optimist":
            # Extract episode number if present
            ep_match = re.search(r'Ep\.?\s*(\d+)', episode.title, re.IGNORECASE)
            ep_number = ep_match.group(1) if ep_match else None
            
            queries = []
            if ep_number:
                # Prioritize episode number searches
                queries.extend([
                    f"American Optimist Ep {ep_number} full episode",
                    f"Joe Lonsdale American Optimist Episode {ep_number}",
                    f"American Optimist {ep_number} {channel_info['channel_name']}"
                ])
            
            # Add guest-based searches
            guest_match = re.search(r':\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', episode.title)
            if guest_match:
                guest_name = guest_match.group(1)
                queries.extend([
                    f"American Optimist {guest_name} full episode",
                    f"Joe Lonsdale {guest_name} interview"
                ])
            
            # Add fallback with shorter title
            queries.append(f"{title_terms[:30]} American Optimist")
        else:
            # Original logic for other podcasts
            queries = [
                f"{title_terms} channel:{channel_info['channel_id']}",
                f"{title_terms} {channel_info['channel_name']}",
                f"{episode.title[:50]} {channel_info['channel_name']}"
            ]
        
        for query in queries:
            logger.info(f"Trying query: {query}")
            result = await self._perform_youtube_search(query, episode)
            if result:
                return result
        
        return None
    
    async def _search_by_date(self, episode: Episode) -> Optional[str]:
        """Search using episode publication date"""
        # Search for videos published around the episode date
        date_str = episode.published.strftime("%Y-%m-%d")
        
        queries = [
            f"{episode.podcast} {date_str}",
            f"{episode.podcast} uploaded:{date_str}"
        ]
        
        for query in queries:
            result = await self._perform_youtube_search(query, episode, use_date_filter=True)
            if result:
                return result
        
        return None
    
    async def _search_by_guest(self, episode: Episode) -> Optional[str]:
        """Extract guest name and search"""
        # Common patterns for guest names in titles
        patterns = [
            r"(?:with|w/|featuring|feat\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:",
            r"Guest:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
        ]
        
        guest_name = None
        for pattern in patterns:
            match = re.search(pattern, episode.title)
            if match:
                guest_name = match.group(1)
                break
        
        if guest_name:
            logger.info(f"👤 Extracted guest name: {guest_name}")
            queries = [
                f"{episode.podcast} {guest_name}",
                f"{guest_name} {episode.podcast}"
            ]
            
            for query in queries:
                result = await self._perform_youtube_search(query, episode)
                if result:
                    return result
        
        return None
    
    async def _search_generic(self, episode: Episode) -> Optional[str]:
        """Generic search with multiple query variations"""
        # Build various search queries
        queries = []
        
        # Clean episode title
        clean_title = re.sub(r'^#?\d+\s*[-–—|:]?\s*', '', episode.title)
        clean_title = re.sub(r'^Episode\s+\d+\s*[-–—|:]?\s*', '', clean_title, flags=re.IGNORECASE)
        
        # Query variations
        queries.extend([
            f"{episode.podcast} {clean_title[:50]}",
            f"{episode.podcast} podcast {clean_title[:30]}",
            clean_title[:60]  # Just the title for unique episodes
        ])
        
        for query in queries:
            logger.info(f"Trying query: {query}")
            result = await self._perform_youtube_search(query, episode)
            if result:
                return result
        
        return None
    
    async def _perform_youtube_search(self, query: str, episode: Episode, 
                                    use_date_filter: bool = False) -> Optional[str]:
        """Perform actual YouTube search"""
        try:
            if self.youtube_api_key:
                return await self._search_with_api(query, episode, use_date_filter)
            else:
                return await self._search_with_scraping(query, episode)
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
            return None
    
    async def _search_with_api(self, query: str, episode: Episode, 
                               use_date_filter: bool = False) -> Optional[str]:
        """Search using YouTube Data API v3"""
        try:
            search_url = "https://www.googleapis.com/youtube/v3/search"
            
            params = {
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'maxResults': 10,
                'key': self.youtube_api_key
            }
            
            # Add date filter if requested
            if use_date_filter:
                # Search within 7 days of episode publication
                published_after = (episode.published - timedelta(days=3)).isoformat()
                published_before = (episode.published + timedelta(days=4)).isoformat()
                params['publishedAfter'] = published_after
                params['publishedBefore'] = published_before
            
            async with self.session.get(search_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Find best match
                    for item in data.get('items', []):
                        video_title = item['snippet']['title'].lower()
                        channel_title = item['snippet']['channelTitle'].lower()
                        
                        # Check if this looks like our episode
                        if self._is_likely_match(episode, video_title, channel_title):
                            video_id = item['id']['videoId']
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            logger.info(f"✅ Found on YouTube: {video_url}")
                            return video_url
                
        except Exception as e:
            logger.error(f"YouTube API error: {e}")
        
        return None
    
    async def _search_with_scraping(self, query: str, episode: Episode) -> Optional[str]:
        """Fallback: Search YouTube by scraping search results"""
        try:
            search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with self.session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # Extract video IDs from search results
                    video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                    
                    # Also look for video titles
                    title_matches = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}\]', html)
                    
                    # Check first few results
                    for i, video_id in enumerate(video_ids[:10]):
                        if i < len(title_matches):
                            video_title = title_matches[i].lower()
                            if self._is_likely_match(episode, video_title, ""):
                                video_url = f"https://www.youtube.com/watch?v={video_id}"
                                logger.info(f"✅ Found on YouTube (scraping): {video_url}")
                                return video_url
                
        except Exception as e:
            logger.error(f"YouTube scraping error: {e}")
        
        return None
    
    def _is_likely_match(self, episode: Episode, video_title: str, channel_title: str) -> bool:
        """Check if a YouTube video is likely our episode"""
        video_title_lower = video_title.lower()
        episode_title_lower = episode.title.lower()
        podcast_name_lower = episode.podcast.lower()
        
        # Special handling for American Optimist
        if episode.podcast == "American Optimist":
            # Check for Joe Lonsdale's channel
            if "joe lonsdale" in channel_title.lower():
                # Look for episode number match
                ep_match = re.search(r'Ep\.?\s*(\d+)', episode.title, re.IGNORECASE)
                if ep_match:
                    ep_number = ep_match.group(1)
                    if f"ep {ep_number}" in video_title_lower or f"episode {ep_number}" in video_title_lower:
                        return True
                
                # Look for guest name match
                guest_match = re.search(r':\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', episode.title)
                if guest_match:
                    guest_name = guest_match.group(1).lower()
                    if guest_name in video_title_lower:
                        # Avoid clips by checking for "full" indicators
                        if any(term in video_title_lower for term in ["full episode", "interview", "conversation"]):
                            return True
                        # Accept if video title has similar structure
                        if "american optimist" in video_title_lower:
                            return True
            return False
        
        # Original logic for other podcasts
        # Check for podcast name in video or channel title
        if podcast_name_lower not in video_title_lower and podcast_name_lower not in channel_title:
            # Check for known channel mappings
            if episode.podcast in self.CHANNEL_MAPPINGS:
                channel_info = self.CHANNEL_MAPPINGS[episode.podcast]
                if channel_info['channel_name'].lower() not in channel_title:
                    return False
            else:
                return False
        
        # Extract key terms from episode title
        key_terms = self._extract_key_terms(episode.title)
        
        # Check if enough key terms match
        matches = sum(1 for term in key_terms if term.lower() in video_title_lower)
        
        # Require at least 50% of key terms to match
        if len(key_terms) > 0 and matches >= len(key_terms) * 0.5:
            return True
        
        # Check for guest name match
        guest_match = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", episode.title)
        if guest_match:
            guest_name = guest_match.group(1).lower()
            if len(guest_name) > 5 and guest_name in video_title_lower:
                return True
        
        return False
    
    def _extract_search_terms(self, title: str) -> str:
        """Extract clean search terms from episode title"""
        # Remove episode numbers and common prefixes
        clean = re.sub(r'^#?\d+\s*[-–—|:]?\s*', '', title)
        clean = re.sub(r'^Episode\s+\d+\s*[-–—|:]?\s*', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'^Ep\.?\s*\d+\s*[-–—|:]?\s*', '', clean, flags=re.IGNORECASE)
        
        # Limit length
        return clean[:100]
    
    def _extract_key_terms(self, title: str) -> List[str]:
        """Extract key terms from title for matching"""
        # Remove common words and extract significant terms
        clean_title = self._extract_search_terms(title)
        
        # Split into words and filter
        words = clean_title.split()
        stop_words = {'the', 'a', 'an', 'of', 'with', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'is', 'are', 'was', 'were'}
        
        key_terms = []
        for word in words:
            if len(word) > 3 and word.lower() not in stop_words:
                key_terms.append(word)
        
        return key_terms[:8]  # Limit to first 8 key terms