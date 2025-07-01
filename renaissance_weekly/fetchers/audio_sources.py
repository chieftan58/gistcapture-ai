"""
Multiple audio source discovery for maximum reliability.
Finds alternative audio URLs when primary sources fail.
"""

import re
import asyncio
from typing import List, Optional, Dict
from urllib.parse import urlparse, parse_qs
import aiohttp
from bs4 import BeautifulSoup

from ..utils.logging import get_logger
from ..models import Episode

logger = get_logger(__name__)


class AudioSourceFinder:
    """Find multiple audio sources for podcast episodes"""
    
    def __init__(self):
        self.session = None
        self._session_created = False
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if not self._session_created or self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            )
            self._session_created = True
        return self.session
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            self._session_created = False
    
    async def find_all_audio_sources(self, episode: Episode) -> List[str]:
        """
        Find all possible audio sources for an episode.
        Returns list of audio URLs in order of preference.
        """
        sources = []
        
        # 1. Primary audio URL from RSS
        if episode.audio_url:
            sources.append(episode.audio_url)
        
        # 2. Check episode webpage for alternative players
        if episode.link:
            web_sources = await self._find_audio_from_webpage(episode.link)
            sources.extend(web_sources)
        
        # 3. Platform-specific searches
        platform_sources = await self._find_platform_specific_sources(episode)
        sources.extend(platform_sources)
        
        # 4. Search for mirrors/CDN alternatives
        cdn_sources = await self._find_cdn_alternatives(episode.audio_url) if episode.audio_url else []
        sources.extend(cdn_sources)
        
        # 5. YouTube audio extraction
        youtube_url = await self._find_youtube_version(episode)
        if youtube_url:
            sources.append(youtube_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_sources = []
        for source in sources:
            if source not in seen:
                seen.add(source)
                unique_sources.append(source)
        
        logger.info(f"Found {len(unique_sources)} audio sources for: {episode.title[:50]}...")
        return unique_sources
    
    async def _find_audio_from_webpage(self, url: str) -> List[str]:
        """Extract audio URLs from episode webpage"""
        audio_urls = []
        
        try:
            session = await self._get_session()
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return audio_urls
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Look for audio tags
                for audio in soup.find_all('audio'):
                    src = audio.get('src')
                    if src:
                        audio_urls.append(src)
                    
                    # Check source tags within audio
                    for source in audio.find_all('source'):
                        src = source.get('src')
                        if src:
                            audio_urls.append(src)
                
                # Look for iframe embeds (often contain players)
                for iframe in soup.find_all('iframe'):
                    src = iframe.get('src', '')
                    if any(platform in src for platform in ['spotify', 'soundcloud', 'anchor']):
                        # Extract episode ID and construct direct URL if possible
                        platform_url = await self._extract_from_embed(src)
                        if platform_url:
                            audio_urls.append(platform_url)
                
                # Look for data attributes that might contain audio URLs
                for elem in soup.find_all(attrs={'data-audio-url': True}):
                    audio_urls.append(elem['data-audio-url'])
                
                for elem in soup.find_all(attrs={'data-src': True}):
                    if any(ext in elem['data-src'] for ext in ['.mp3', '.m4a', '.ogg']):
                        audio_urls.append(elem['data-src'])
                
                # Search for audio URLs in JavaScript
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        # Common patterns for audio URLs in JS
                        patterns = [
                            r'"audioUrl":\s*"([^"]+)"',
                            r'"audio":\s*"([^"]+)"',
                            r'"mp3":\s*"([^"]+)"',
                            r'"url":\s*"([^"]+\.mp3[^"]*)"',
                            r'audioSrc\s*=\s*["\']([^"\']+)["\']',
                        ]
                        for pattern in patterns:
                            matches = re.findall(pattern, script.string)
                            audio_urls.extend(matches)
                
        except Exception as e:
            logger.debug(f"Error finding audio from webpage: {e}")
        
        return [url for url in audio_urls if url and not url.startswith('data:')]
    
    async def _find_platform_specific_sources(self, episode: Episode) -> List[str]:
        """Find platform-specific alternative sources"""
        sources = []
        
        # Spotify
        spotify_url = await self._find_spotify_url(episode)
        if spotify_url:
            sources.append(spotify_url)
        
        # Apple Podcasts
        apple_url = await self._find_apple_podcasts_url(episode)
        if apple_url:
            sources.append(apple_url)
        
        # Google Podcasts (if still available)
        google_url = await self._find_google_podcasts_url(episode)
        if google_url:
            sources.append(google_url)
        
        return sources
    
    async def _find_cdn_alternatives(self, original_url: str) -> List[str]:
        """Find CDN alternatives for the same audio file"""
        alternatives = []
        
        if not original_url:
            return alternatives
        
        parsed = urlparse(original_url)
        
        # Common CDN patterns
        cdn_patterns = {
            'cloudfront.net': ['d1.cloudfront.net', 'd2.cloudfront.net', 'd3.cloudfront.net'],
            'amazonaws.com': ['s3.amazonaws.com', 's3-us-west-2.amazonaws.com'],
            'akamaized.net': ['media.akamaized.net', 'audio.akamaized.net'],
        }
        
        for domain, alternates in cdn_patterns.items():
            if domain in parsed.netloc:
                for alt in alternates:
                    alt_url = original_url.replace(parsed.netloc, alt)
                    alternatives.append(alt_url)
        
        return alternatives
    
    async def _find_youtube_version(self, episode: Episode) -> Optional[str]:
        """Find YouTube version of the episode"""
        try:
            # Search YouTube for the episode
            search_query = f"{episode.podcast} {episode.title}"
            # Clean up the query
            search_query = re.sub(r'[#\-–—:]', ' ', search_query)
            search_query = re.sub(r'\s+', ' ', search_query).strip()[:100]
            
            # Note: This would use YouTube search API or web scraping
            # For now, return None as placeholder
            # In production, this would return the YouTube URL if found
            
        except Exception as e:
            logger.debug(f"Error finding YouTube version: {e}")
        
        return None
    
    async def _find_spotify_url(self, episode: Episode) -> Optional[str]:
        """Find Spotify URL for episode"""
        # This would search Spotify's API or web
        # Placeholder for now
        return None
    
    async def _find_apple_podcasts_url(self, episode: Episode) -> Optional[str]:
        """Find Apple Podcasts URL for episode"""
        # This would use Apple Podcasts API
        # Placeholder for now
        return None
    
    async def _find_google_podcasts_url(self, episode: Episode) -> Optional[str]:
        """Find Google Podcasts URL for episode"""
        # This would search Google Podcasts
        # Placeholder for now
        return None
    
    async def _extract_from_embed(self, embed_url: str) -> Optional[str]:
        """Extract direct audio URL from embed players"""
        # This would extract direct URLs from various embed players
        # Placeholder for now
        return None