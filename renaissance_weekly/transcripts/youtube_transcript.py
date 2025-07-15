"""YouTube transcript finder for podcasts that publish on YouTube"""

import re
from typing import Optional, List, Dict
from urllib.parse import parse_qs, urlparse
import asyncio

from ..utils.logging import get_logger

logger = get_logger(__name__)


class YouTubeTranscriptFinder:
    """Find and extract transcripts from YouTube videos"""
    
    def __init__(self):
        self.youtube_patterns = [
            r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
            r'youtu\.be/([a-zA-Z0-9_-]+)',
            r'youtube\.com/embed/([a-zA-Z0-9_-]+)',
        ]
    
    async def find_youtube_transcript(self, episode_title: str, podcast_name: str, 
                                    episode_link: Optional[str] = None) -> Optional[str]:
        """
        Find YouTube transcript for a podcast episode.
        
        Args:
            episode_title: Title of the episode
            podcast_name: Name of the podcast
            episode_link: Optional link to episode page that might contain YouTube embed
            
        Returns:
            Transcript text if found, None otherwise
        """
        video_id = None
        
        # First, check if episode link contains YouTube video
        if episode_link:
            video_id = await self._extract_youtube_id_from_page(episode_link)
        
        # If not found, search YouTube for the episode
        if not video_id:
            video_id = await self._search_youtube_for_episode(podcast_name, episode_title)
        
        # If we found a video ID, get the transcript
        if video_id:
            return await self._get_youtube_transcript(video_id)
        
        return None
    
    async def _extract_youtube_id_from_page(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from a webpage"""
        try:
            import aiohttp
            from bs4 import BeautifulSoup
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    
                    html = await response.text()
                    
                    # Check for YouTube ID in the HTML
                    for pattern in self.youtube_patterns:
                        match = re.search(pattern, html)
                        if match:
                            return match.group(1)
                    
                    # Also check for YouTube embeds in iframes
                    soup = BeautifulSoup(html, 'html.parser')
                    iframes = soup.find_all('iframe', src=True)
                    
                    for iframe in iframes:
                        src = iframe['src']
                        if 'youtube.com' in src or 'youtu.be' in src:
                            for pattern in self.youtube_patterns:
                                match = re.search(pattern, src)
                                if match:
                                    return match.group(1)
                    
        except Exception as e:
            logger.debug(f"Failed to extract YouTube ID from page: {e}")
        
        return None
    
    async def _search_youtube_for_episode(self, podcast_name: str, episode_title: str) -> Optional[str]:
        """Search YouTube for a podcast episode and return video ID"""
        try:
            # Use YouTube Data API if available
            import os
            youtube_api_key = os.getenv('YOUTUBE_API_KEY')
            
            if youtube_api_key:
                return await self._search_youtube_api(podcast_name, episode_title, youtube_api_key)
            else:
                # Fallback to web scraping
                return await self._search_youtube_web(podcast_name, episode_title)
                
        except Exception as e:
            logger.debug(f"YouTube search failed: {e}")
            return None
    
    async def _search_youtube_api(self, podcast_name: str, episode_title: str, api_key: str) -> Optional[str]:
        """Search using YouTube Data API"""
        try:
            import aiohttp
            
            # Clean up episode title - remove episode numbers, special characters
            clean_title = re.sub(r'^#?\d+:?\s*', '', episode_title)  # Remove episode numbers
            clean_title = re.sub(r'\s+', ' ', clean_title).strip()
            
            search_query = f"{podcast_name} {clean_title}"
            
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                'part': 'snippet',
                'q': search_query,
                'type': 'video',
                'maxResults': 5,
                'key': api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Look for best match
                        for item in data.get('items', []):
                            snippet = item['snippet']
                            title = snippet['title'].lower()
                            channel = snippet['channelTitle'].lower()
                            
                            # Check if this looks like the right episode
                            if (podcast_name.lower() in channel or 
                                podcast_name.lower() in title) and \
                               any(word in title for word in clean_title.lower().split()[:5]):
                                return item['id']['videoId']
                    
        except Exception as e:
            logger.debug(f"YouTube API search failed: {e}")
        
        return None
    
    async def _search_youtube_web(self, podcast_name: str, episode_title: str) -> Optional[str]:
        """Search YouTube by web scraping (fallback method)"""
        session = None
        try:
            import aiohttp
            from urllib.parse import quote
            
            # Clean up search query
            clean_title = re.sub(r'^#?\d+:?\s*', '', episode_title)[:50]
            search_query = quote(f"{podcast_name} {clean_title}")
            
            url = f"https://www.youtube.com/results?search_query={search_query}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Extract video IDs from search results
                        pattern = r'"videoId":"([a-zA-Z0-9_-]+)"'
                        matches = re.findall(pattern, html)
                        
                        if matches:
                            # Return first match (most relevant)
                            return matches[0]
                            
        except Exception as e:
            logger.debug(f"YouTube web search failed: {e}")
        
        return None
    
    async def _get_youtube_transcript(self, video_id: str) -> Optional[str]:
        """Get transcript for a YouTube video"""
        try:
            # Try youtube-transcript-api first
            from youtube_transcript_api import YouTubeTranscriptApi
            
            logger.info(f"🎬 Fetching YouTube transcript for video: {video_id}")
            
            # Try to get transcript in different languages
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Prefer manually created transcripts
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
            except:
                # Fallback to auto-generated
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                except:
                    # Try any available transcript
                    transcript = transcript_list.find_transcript(['en'])
            
            # Fetch the actual transcript
            transcript_data = transcript.fetch()
            
            # Format transcript text
            text_parts = []
            for entry in transcript_data:
                text = entry['text'].replace('\n', ' ').strip()
                if text:
                    text_parts.append(text)
            
            full_text = ' '.join(text_parts)
            
            # Clean up the transcript
            full_text = re.sub(r'\s+', ' ', full_text)  # Multiple spaces to single
            full_text = re.sub(r'\[.*?\]', '', full_text)  # Remove [Music] etc
            
            if len(full_text) > 1000:  # Minimum length check
                logger.info(f"✅ Found YouTube transcript ({len(full_text)} characters)")
                return full_text
            
        except ImportError:
            logger.warning("youtube-transcript-api not installed. Install with: pip install youtube-transcript-api")
        except Exception as e:
            logger.debug(f"Failed to get YouTube transcript: {e}")
        
        return None
    
    async def find_podcast_youtube_channel(self, podcast_name: str) -> Optional[str]:
        """Find the YouTube channel ID for a podcast"""
        try:
            import os
            youtube_api_key = os.getenv('YOUTUBE_API_KEY')
            
            if not youtube_api_key:
                return None
            
            import aiohttp
            
            url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                'part': 'snippet',
                'q': podcast_name,
                'type': 'channel',
                'maxResults': 3,
                'key': youtube_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        for item in data.get('items', []):
                            channel_title = item['snippet']['title'].lower()
                            if podcast_name.lower() in channel_title:
                                return item['snippet']['channelId']
                                
        except Exception as e:
            logger.debug(f"Failed to find YouTube channel: {e}")
        
        return None