"""Enhanced Substack podcast handling with multiple fallback strategies"""

import os
import re
import asyncio
import aiohttp
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import json

from ..models import Episode
from ..utils.logging import get_logger
from ..fetchers.audio_sources import AudioSourceFinder

logger = get_logger(__name__)


class SubstackEnhancedFetcher:
    """Enhanced fetcher for Substack-protected podcasts with multiple fallback strategies"""
    
    def __init__(self):
        self.session = None
        self.audio_finder = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        self.audio_finder = AudioSourceFinder()
        await self.audio_finder.__aenter__()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        if self.audio_finder:
            await self.audio_finder.__aexit__(exc_type, exc_val, exc_tb)
    
    async def get_episode_content(self, episode: Episode) -> Tuple[Optional[str], Optional[str]]:
        """
        Get episode content using multiple strategies.
        Returns (transcript, audio_url) tuple.
        """
        logger.info(f"🎯 Using enhanced strategy for Substack podcast: {episode.podcast}")
        
        # Strategy 1: Try alternative platforms first (YouTube, Spotify, Apple)
        alt_content = await self._try_alternative_platforms(episode)
        if alt_content:
            return alt_content
        
        # Strategy 2: Try to find the episode on other podcast apps
        podcast_app_content = await self._try_podcast_apps(episode)
        if podcast_app_content:
            return podcast_app_content
        
        # Strategy 3: Try web search for transcript
        web_transcript = await self._search_web_transcript(episode)
        if web_transcript:
            return (web_transcript, None)
        
        # Strategy 4: Try browser automation with enhanced techniques
        browser_content = await self._try_browser_automation(episode)
        if browser_content:
            return browser_content
        
        logger.warning(f"❌ All enhanced strategies failed for {episode.podcast}")
        return (None, None)
    
    async def _try_alternative_platforms(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Try to find episode on alternative platforms"""
        
        # Check YouTube first (often has auto-generated transcripts)
        youtube_result = await self._check_youtube(episode)
        if youtube_result:
            return youtube_result
        
        # Check Apple Podcasts (reliable audio source)
        apple_result = await self._check_apple_podcasts(episode)
        if apple_result:
            return apple_result
        
        # Check Spotify (may have descriptions/chapters)
        spotify_result = await self._check_spotify(episode)
        if spotify_result:
            return spotify_result
        
        return None
    
    async def _check_youtube(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Check if episode is on YouTube"""
        try:
            # Use the enhanced YouTube search
            youtube_url = await self.audio_finder._find_youtube_version(episode)
            if youtube_url:
                logger.info(f"✅ Found episode on YouTube: {youtube_url}")
                
                # Try to get YouTube transcript
                from youtube_transcript_api import YouTubeTranscriptApi
                video_id_match = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', youtube_url)
                if video_id_match:
                    video_id = video_id_match.group(1)
                    try:
                        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                        transcript = ' '.join([entry['text'] for entry in transcript_list])
                        logger.info(f"✅ Got YouTube transcript: {len(transcript)} chars")
                        return (transcript, youtube_url)
                    except Exception as e:
                        logger.debug(f"YouTube transcript not available: {e}")
                
                # Return URL even without transcript (can be transcribed)
                return (None, youtube_url)
                
        except Exception as e:
            logger.debug(f"YouTube check failed: {e}")
        
        return None
    
    async def _check_apple_podcasts(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Check if episode is on Apple Podcasts"""
        try:
            # Build search query
            query = f"{episode.podcast} {episode.title[:50]}"
            
            # Search Apple Podcasts (using iTunes Search API)
            search_url = "https://itunes.apple.com/search"
            params = {
                'term': query,
                'media': 'podcast',
                'entity': 'podcastEpisode',
                'limit': 10
            }
            
            async with self.session.get(search_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])
                    
                    # Find best match
                    for result in results:
                        if self._is_episode_match(episode, result):
                            audio_url = result.get('episodeUrl')
                            if audio_url:
                                logger.info(f"✅ Found on Apple Podcasts: {audio_url}")
                                # Apple doesn't provide transcripts, but we have audio
                                return (None, audio_url)
                                
        except Exception as e:
            logger.debug(f"Apple Podcasts check failed: {e}")
        
        return None
    
    async def _check_spotify(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Check if episode is on Spotify using existing integration"""
        try:
            from .spotify_transcript import SpotifyTranscriptFetcher
            
            async with SpotifyTranscriptFetcher() as spotify:
                content = await spotify.get_transcript(episode)
                if content:
                    logger.info(f"✅ Found Spotify content: {len(content)} chars")
                    # Spotify doesn't provide direct audio URLs, but content is useful
                    return (content, None)
                    
        except Exception as e:
            logger.debug(f"Spotify check failed: {e}")
        
        return None
    
    async def _try_podcast_apps(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Try to find episode on podcast aggregator apps"""
        
        # Try Overcast
        overcast_result = await self._check_overcast(episode)
        if overcast_result:
            return overcast_result
        
        # Try Pocket Casts
        pocketcasts_result = await self._check_pocketcasts(episode)
        if pocketcasts_result:
            return pocketcasts_result
        
        return None
    
    async def _check_overcast(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Check Overcast for episode"""
        try:
            # Overcast has a web interface we can scrape
            search_query = f"{episode.podcast} {episode.title[:30]}"
            search_url = f"https://overcast.fm/search?q={search_query}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
            
            async with self.session.get(search_url, headers=headers) as response:
                if response.status == 200:
                    # Parse and find episode
                    # This is a simplified version - real implementation would parse HTML
                    logger.debug("Overcast search not fully implemented")
                    
        except Exception as e:
            logger.debug(f"Overcast check failed: {e}")
        
        return None
    
    async def _check_pocketcasts(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Check Pocket Casts for episode"""
        # Similar to Overcast - would need HTML parsing
        return None
    
    async def _search_web_transcript(self, episode: Episode) -> Optional[str]:
        """Search the web for transcript using search engines"""
        try:
            # Try searching for transcript directly
            queries = [
                f'"{episode.title}" transcript site:{episode.podcast.lower().replace(" ", "")}.com',
                f'"{episode.title}" "full transcript"',
                f'{episode.podcast} "{episode.title}" transcript'
            ]
            
            for query in queries:
                # In a real implementation, this would use a search API
                # or web scraping of search results
                logger.debug(f"Web search: {query}")
                
        except Exception as e:
            logger.debug(f"Web search failed: {e}")
        
        return None
    
    async def _try_browser_automation(self, episode: Episode) -> Optional[Tuple[str, str]]:
        """Enhanced browser automation specifically for Substack"""
        try:
            # Import browser downloader
            from ..fetchers.browser_downloader import BrowserDownloader
            
            # Force browser download for Substack URLs
            if episode.link and 'substack.com' in episode.link:
                logger.info("🌐 Attempting enhanced browser automation for Substack")
                
                downloader = BrowserDownloader()
                # Use a custom approach for Substack
                audio_file = await self._enhanced_substack_download(episode, downloader)
                if audio_file:
                    return (None, audio_file)
                    
        except Exception as e:
            logger.error(f"Browser automation failed: {e}")
        
        return None
    
    async def _enhanced_substack_download(self, episode: Episode, downloader) -> Optional[str]:
        """Enhanced Substack download with better Cloudflare bypass"""
        # This would implement:
        # 1. Use persistent browser context with real profile
        # 2. Add human-like delays and mouse movements
        # 3. Handle Cloudflare challenges
        # 4. Extract audio URL from player
        logger.debug("Enhanced Substack download not fully implemented")
        return None
    
    def _is_episode_match(self, episode: Episode, result: Dict) -> bool:
        """Check if search result matches the episode"""
        # Simple matching logic
        result_title = result.get('trackName', '').lower()
        result_podcast = result.get('collectionName', '').lower()
        
        episode_title_words = set(episode.title.lower().split()[:5])
        result_title_words = set(result_title.split())
        
        # Check podcast name match
        if episode.podcast.lower() not in result_podcast:
            return False
        
        # Check title overlap
        common_words = episode_title_words & result_title_words
        if len(common_words) >= 3:
            return True
        
        return False


# Specific implementations for each problematic podcast
class AmericanOptimistEnhanced:
    """Enhanced handler for American Optimist podcast"""
    
    @staticmethod
    async def get_content(episode: Episode) -> Tuple[Optional[str], Optional[str]]:
        async with SubstackEnhancedFetcher() as fetcher:
            # American Optimist specific: Check if Joe Lonsdale posts on other platforms
            # He often cross-posts to Twitter/X, LinkedIn, etc.
            content = await fetcher.get_episode_content(episode)
            
            if not content[0] and not content[1]:
                # Try specific American Optimist strategies
                logger.info("Trying American Optimist specific strategies...")
                # Could check Joe Lonsdale's Twitter, LinkedIn, etc.
                
            return content


class DwarkeshPodcastEnhanced:
    """Enhanced handler for Dwarkesh Podcast"""
    
    @staticmethod
    async def get_content(episode: Episode) -> Tuple[Optional[str], Optional[str]]:
        async with SubstackEnhancedFetcher() as fetcher:
            # Dwarkesh specific: Often posts on YouTube first
            content = await fetcher.get_episode_content(episode)
            
            if not content[0] and not content[1]:
                # Try Dwarkesh-specific strategies
                logger.info("Trying Dwarkesh Podcast specific strategies...")
                # Dwarkesh often has long-form YouTube videos
                
            return content