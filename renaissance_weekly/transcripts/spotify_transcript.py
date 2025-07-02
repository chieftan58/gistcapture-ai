"""Spotify transcript fetcher using their episode API"""

import os
import re
import json
import base64
import asyncio
import aiohttp
from typing import Optional, Dict, Tuple
from difflib import SequenceMatcher

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SpotifyTranscriptFetcher:
    """Fetch transcripts from Spotify's API when available"""
    
    def __init__(self):
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        self._token = None
        self._token_expires = 0
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_transcript(self, episode: Episode) -> Optional[str]:
        """Get transcript from Spotify if available"""
        if not self.client_id or not self.client_secret:
            logger.debug("Spotify credentials not configured")
            return None
        
        try:
            # Get access token
            token = await self._get_access_token()
            if not token:
                return None
            
            # Search for the episode
            episode_data = await self._search_episode(episode, token)
            if not episode_data:
                return None
            
            episode_id = episode_data['id']
            logger.info(f"🎵 Found Spotify episode: {episode_data.get('name', 'Unknown')}")
            
            # Check if transcript is available
            # Note: Spotify API doesn't directly expose transcripts, but some shows have them
            # We need to check the episode's available markets and features
            transcript = await self._fetch_transcript(episode_id, token)
            
            if transcript:
                logger.info(f"✅ Retrieved Spotify transcript: {len(transcript)} characters")
                return transcript
            else:
                # Try to get chapter descriptions as fallback
                chapters = await self._fetch_chapters(episode_id, token)
                if chapters:
                    logger.info(f"📝 Using Spotify chapter descriptions as partial transcript")
                    return chapters
                    
        except Exception as e:
            logger.error(f"Spotify transcript error: {e}")
        
        return None
    
    async def _get_access_token(self) -> Optional[str]:
        """Get or refresh Spotify access token"""
        import time
        
        # Check if we have a valid token
        if self._token and time.time() < self._token_expires:
            return self._token
        
        try:
            # Encode credentials
            credentials = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'grant_type': 'client_credentials'}
            
            async with self.session.post(
                'https://accounts.spotify.com/api/token',
                headers=headers,
                data=data
            ) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self._token = token_data['access_token']
                    # Set expiry time (subtract 60 seconds for safety)
                    self._token_expires = time.time() + token_data['expires_in'] - 60
                    return self._token
                else:
                    logger.error(f"Spotify auth failed: {response.status}")
                    
        except Exception as e:
            logger.error(f"Spotify token error: {e}")
        
        return None
    
    async def _search_episode(self, episode: Episode, token: str) -> Optional[Dict]:
        """Search for episode on Spotify"""
        try:
            # Clean up the title for better search
            title = re.sub(r'[^\w\s-]', '', episode.title)
            title = re.sub(r'\s+', ' ', title).strip()
            
            # Try different search queries
            queries = [
                f"{episode.podcast} {title}",
                f'show:"{episode.podcast}" {title}',
                title  # Just the title as last resort
            ]
            
            headers = {'Authorization': f'Bearer {token}'}
            
            for query in queries:
                params = {
                    'q': query[:100],  # Spotify has query length limit
                    'type': 'episode',
                    'limit': 10,
                    'market': 'US'
                }
                
                async with self.session.get(
                    'https://api.spotify.com/v1/search',
                    headers=headers,
                    params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        episodes = data.get('episodes', {}).get('items', [])
                        
                        # Find best match
                        best_match = self._find_best_match(episode, episodes)
                        if best_match:
                            return best_match
                    elif response.status == 429:
                        # Rate limited
                        retry_after = int(response.headers.get('Retry-After', 60))
                        logger.warning(f"Spotify rate limited, retry after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
        
        return None
    
    def _find_best_match(self, target: Episode, candidates: list) -> Optional[Dict]:
        """Find best matching episode from search results"""
        if not candidates:
            return None
        
        best_score = 0
        best_match = None
        
        target_title = target.title.lower()
        
        for candidate in candidates:
            title = candidate.get('name', '').lower()
            show_name = candidate.get('show', {}).get('name', '').lower()
            
            # Calculate title similarity
            title_score = SequenceMatcher(None, target_title, title).ratio()
            
            # Bonus for matching podcast name
            if target.podcast.lower() in show_name:
                title_score += 0.2
            
            if title_score > best_score:
                best_score = title_score
                best_match = candidate
        
        # Require at least 70% similarity
        if best_score >= 0.7:
            return best_match
        
        return None
    
    async def _fetch_transcript(self, episode_id: str, token: str) -> Optional[str]:
        """Fetch transcript for a specific episode"""
        try:
            headers = {'Authorization': f'Bearer {token}'}
            
            # Spotify doesn't have a direct transcript endpoint
            # But we can check if the episode has certain features
            async with self.session.get(
                f'https://api.spotify.com/v1/episodes/{episode_id}',
                headers=headers,
                params={'market': 'US'}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check if episode has transcript in description
                    description = data.get('description', '') or data.get('html_description', '')
                    
                    # Some podcasts put transcript links in description
                    if 'transcript' in description.lower():
                        # Extract and follow transcript links if present
                        logger.debug("Transcript mentioned in description but extraction not implemented")
                    
                    # Return None for now as Spotify doesn't expose transcripts directly
                    return None
                    
        except Exception as e:
            logger.error(f"Spotify transcript fetch error: {e}")
        
        return None
    
    async def _fetch_chapters(self, episode_id: str, token: str) -> Optional[str]:
        """Fetch chapter information as fallback content"""
        try:
            headers = {'Authorization': f'Bearer {token}'}
            
            # Get full episode details
            async with self.session.get(
                f'https://api.spotify.com/v1/episodes/{episode_id}',
                headers=headers,
                params={'market': 'US'}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Build a structured summary from available data
                    content_parts = []
                    
                    # Episode description
                    if data.get('description'):
                        content_parts.append(f"Episode Description:\n{data['description']}\n")
                    
                    # Show description
                    show = data.get('show', {})
                    if show.get('description'):
                        content_parts.append(f"About the Podcast:\n{show['description']}\n")
                    
                    if content_parts:
                        return '\n'.join(content_parts)
                        
        except Exception as e:
            logger.error(f"Spotify chapters fetch error: {e}")
        
        return None


async def get_spotify_transcript(episode: Episode) -> Optional[str]:
    """Convenience function to get Spotify transcript"""
    async with SpotifyTranscriptFetcher() as fetcher:
        return await fetcher.get_transcript(episode)