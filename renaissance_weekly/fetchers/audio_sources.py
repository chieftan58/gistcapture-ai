"""
Multiple audio source discovery for maximum reliability.
Finds alternative audio URLs when primary sources fail.
"""

import re
import asyncio
from typing import List, Optional, Dict, Any
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
    
    async def find_all_audio_sources(self, episode: Episode, podcast_config: Optional[Dict] = None) -> List[str]:
        """
        Find all possible audio sources for an episode.
        Returns list of audio URLs in order of preference.
        
        NEW PRIORITY ORDER:
        1. Platform APIs (most reliable)
        2. Direct CDN URLs (bypass redirects)
        3. Episode webpage sources
        4. YouTube versions
        5. RSS feed URL (least reliable due to redirects/protection)
        """
        sources = []
        
        # 1. Platform-specific searches (HIGHEST PRIORITY)
        logger.info(f"🔍 Searching platform APIs for: {episode.title[:50]}...")
        platform_sources = await self._find_platform_specific_sources(episode, podcast_config)
        sources.extend(platform_sources)
        
        # 2. Search for direct CDN URLs (bypass redirects)
        if episode.audio_url:
            logger.info("🔍 Looking for direct CDN URLs...")
            cdn_sources = await self._find_cdn_alternatives(episode.audio_url)
            sources.extend(cdn_sources)
        
        # 3. Check episode webpage for alternative players
        if episode.link:
            logger.info("🔍 Checking episode webpage for audio sources...")
            web_sources = await self._find_audio_from_webpage(episode.link)
            sources.extend(web_sources)
        
        # 4. YouTube audio extraction
        logger.info("🔍 Searching for YouTube version...")
        youtube_url = await self._find_youtube_version(episode)
        if youtube_url:
            sources.append(youtube_url)
        
        # 5. RSS audio URL (LOWEST PRIORITY - often has redirects/protection)
        if episode.audio_url:
            logger.info("📡 Adding RSS feed URL as last resort...")
            sources.append(episode.audio_url)
        
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
    
    async def _find_platform_specific_sources(self, episode: Episode, podcast_config: Optional[Dict] = None) -> List[str]:
        """Find platform-specific alternative sources"""
        sources = []
        
        # Apple Podcasts (FIRST - we have IDs for this)
        apple_url = await self._find_apple_podcasts_url(episode, podcast_config)
        if apple_url:
            sources.append(apple_url)
        
        # Spotify
        spotify_url = await self._find_spotify_url(episode)
        if spotify_url:
            sources.append(spotify_url)
        
        # Google Podcasts (if still available)
        google_url = await self._find_google_podcasts_url(episode)
        if google_url:
            sources.append(google_url)
        
        return sources
    
    async def _find_cdn_alternatives(self, original_url: str) -> List[str]:
        """Find CDN alternatives and resolve redirect chains"""
        alternatives = []
        
        if not original_url:
            return alternatives
        
        try:
            # Use RedirectResolver to find direct CDN URLs
            from ..transcripts.redirect_resolver import RedirectResolver
            
            async with RedirectResolver() as resolver:
                # Get all CDN alternatives including resolved redirects
                cdn_alternatives = await resolver.find_all_cdn_alternatives(original_url)
                alternatives.extend(cdn_alternatives)
                
                # Also try the simpler pattern-based approach
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
                            if alt_url not in alternatives:
                                alternatives.append(alt_url)
                
        except Exception as e:
            logger.debug(f"Error finding CDN alternatives: {e}")
            # Fall back to simple approach
            return alternatives[:5]  # Limit to 5 alternatives
        
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
    
    async def _find_apple_podcasts_url(self, episode: Episode, podcast_config: Optional[Dict] = None) -> Optional[str]:
        """Find Apple Podcasts URL for episode using iTunes Search API"""
        try:
            # Get apple_id from episode or podcast_config
            apple_id = episode.apple_podcast_id
            if not apple_id and podcast_config and 'apple_id' in podcast_config:
                apple_id = podcast_config['apple_id']
            
            if not apple_id:
                return None
                
            # Use iTunes Search API to find episodes
            session = await self._get_session()
            
            # Search for recent episodes of this podcast
            search_url = "https://itunes.apple.com/lookup"
            params = {
                'id': apple_id,
                'entity': 'podcastEpisode',
                'limit': 50  # Get recent episodes
            }
            
            async with session.get(search_url, params=params) as response:
                if response.status != 200:
                    return None
                    
                data = await response.json()
                
                if 'results' not in data or len(data['results']) < 2:
                    return None
                
                # First result is podcast info, episodes start from index 1
                episodes = data['results'][1:]
                
                # Try to match episode by title
                episode_title_lower = episode.title.lower()
                for ep in episodes:
                    if 'trackName' in ep and 'episodeUrl' in ep:
                        # Fuzzy title matching
                        ep_title_lower = ep['trackName'].lower()
                        
                        # Check for exact match or close match
                        if (episode_title_lower == ep_title_lower or 
                            episode_title_lower in ep_title_lower or
                            ep_title_lower in episode_title_lower):
                            
                            audio_url = ep.get('episodeUrl')
                            if audio_url:
                                logger.info(f"✅ Found Apple Podcasts audio URL: {audio_url[:80]}...")
                                return audio_url
                
                # Try matching by date if title match fails
                if hasattr(episode, 'published') and episode.published:
                    target_date = episode.published.date()
                    for ep in episodes:
                        if 'releaseDate' in ep and 'episodeUrl' in ep:
                            import datetime
                            release_date = datetime.datetime.fromisoformat(
                                ep['releaseDate'].replace('Z', '+00:00')
                            ).date()
                            
                            # Allow 1 day difference for timezone issues
                            if abs((release_date - target_date).days) <= 1:
                                audio_url = ep.get('episodeUrl')
                                if audio_url:
                                    logger.info(f"✅ Found Apple Podcasts audio URL by date: {audio_url[:80]}...")
                                    return audio_url
                
        except Exception as e:
            logger.debug(f"Error finding Apple Podcasts URL: {e}")
        
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