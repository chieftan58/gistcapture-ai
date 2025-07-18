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
        
        Respects retry_strategy configuration:
        - primary: First source to try (apple_podcasts, youtube_search, etc.)
        - fallback: Secondary source if primary fails
        - skip_rss: Skip RSS feed URL entirely
        - force_apple: Always prioritize Apple Podcasts
        """
        sources = []
        
        # Check retry strategy configuration
        retry_strategy = podcast_config.get('retry_strategy', {}) if podcast_config else {}
        primary = retry_strategy.get('primary')
        fallback = retry_strategy.get('fallback')
        skip_rss = retry_strategy.get('skip_rss', False)
        force_apple = retry_strategy.get('force_apple', False)
        
        # Platform-specific handling
        if episode.audio_url:
            # Check if we can fix platform-specific URLs
            from .platform_handlers import MegaphoneHandler, LibsynHandler
            
            if 'megaphone.fm' in episode.audio_url:
                fixed_url = await MegaphoneHandler.get_audio_url(episode.audio_url)
                if fixed_url:
                    sources.append(fixed_url)
                    logger.info("✅ Fixed Megaphone URL")
            elif 'libsyn.com' in episode.audio_url:
                fixed_url = await LibsynHandler.get_audio_url(episode.audio_url)
                if fixed_url:
                    sources.append(fixed_url)
                    logger.info("✅ Fixed Libsyn URL")
        
        # If force_apple or primary is apple_podcasts, try Apple first
        if force_apple or primary == 'apple_podcasts':
            logger.info(f"🍎 Prioritizing Apple Podcasts for {episode.podcast}")
            apple_sources = await self._find_apple_podcast_sources(episode, podcast_config)
            sources.extend(apple_sources)
        
        # If primary is youtube_search, try YouTube first
        if primary == 'youtube_search':
            logger.info(f"🎥 Prioritizing YouTube for {episode.podcast}")
            youtube_url = await self._find_youtube_version(episode, podcast_config)
            if youtube_url:
                sources.append(youtube_url)
                logger.info(f"✅ Found YouTube version")
        
        # Platform-specific searches (unless already done above)
        if not (force_apple or primary == 'apple_podcasts'):
            logger.info(f"🔍 Searching platform APIs for: {episode.title[:50]}...")
            platform_sources = await self._find_platform_specific_sources(episode, podcast_config)
            sources.extend(platform_sources)
        
        # Handle fallback strategy
        if fallback == 'youtube_search' and primary != 'youtube_search':
            logger.info(f"🎥 YouTube as fallback for {episode.podcast}")
            youtube_url = await self._find_youtube_version(episode, podcast_config)
            if youtube_url:
                sources.append(youtube_url)
        elif fallback == 'cdn_alternatives' and episode.audio_url:
            logger.info("🔍 CDN alternatives as fallback")
            cdn_sources = await self._find_cdn_alternatives(episode.audio_url)
            sources.extend(cdn_sources)
        elif fallback == 'browser_automation':
            logger.info("🌐 Browser automation marked as fallback")
            # Browser automation will be handled by download manager
        
        # Standard fallback sources (unless primary already tried)
        
        # Check episode webpage for alternative players
        if episode.link:
            logger.info("🔍 Checking episode webpage for audio sources...")
            web_sources = await self._find_audio_from_webpage(episode.link)
            sources.extend(web_sources)
        
        # YouTube (if not already tried)
        if primary != 'youtube_search' and fallback != 'youtube_search':
            logger.info("🔍 Searching for YouTube version...")
            youtube_url = await self._find_youtube_version(episode, podcast_config)
            if youtube_url:
                sources.append(youtube_url)
        
        # RSS audio URL - ONLY if skip_rss is False
        if episode.audio_url and not skip_rss:
            logger.info("📡 Adding RSS feed URL as last resort...")
            sources.append(episode.audio_url)
        elif skip_rss:
            logger.info(f"⏭️ Skipping RSS feed URL for {episode.podcast} per configuration")
        
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
    
    def _build_youtube_queries(self, episode: Episode) -> List[str]:
        """Build optimized YouTube search queries"""
        queries = []
        
        # Extract key information
        podcast_name = episode.podcast
        title = episode.title
        
        # Special handling for American Optimist
        if podcast_name == "American Optimist":
            # American Optimist often posts on Joe Lonsdale's YouTube channel
            # Format: "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance"
            ep_match = re.search(r'Ep\s*(\d+):\s*(.+)', title)
            if ep_match:
                ep_num = ep_match.group(1)
                ep_title = ep_match.group(2)
                # Extract guest name if present
                guest_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', ep_title)
                if guest_match:
                    guest_name = guest_match.group(1)
                    # Search with Joe Lonsdale + guest name
                    queries.append(f'Joe Lonsdale {guest_name}')
                    queries.append(f'Joe Lonsdale Ep {ep_num} {guest_name}')
                else:
                    queries.append(f'Joe Lonsdale {ep_title[:30]}')
                queries.append(f'Joe Lonsdale American Optimist {ep_num}')
            else:
                queries.append(f'Joe Lonsdale "{title}"')
            return queries[:3]
        
        # Remove common patterns that make search less effective
        # Remove episode numbers
        title_clean = re.sub(r'^#?\d+\s*[-–—|:]?\s*', '', title)
        title_clean = re.sub(r'^Episode\s+\d+\s*[-–—|:]?\s*', '', title_clean, flags=re.IGNORECASE)
        title_clean = re.sub(r'^Ep\.?\s*\d+\s*[-–—|:]?\s*', '', title_clean, flags=re.IGNORECASE)
        
        # Extract guest name if present (pattern: "Guest Name: Topic")
        guest_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:\s*(.+)$', title_clean)
        if guest_match:
            guest_name = guest_match.group(1)
            topic = guest_match.group(2)
            
            # Query 1: Podcast + Guest name (most specific)
            queries.append(f"{podcast_name} {guest_name}")
            
            # Query 2: Podcast + Topic keywords
            topic_keywords = ' '.join(topic.split()[:5])  # First 5 words
            queries.append(f"{podcast_name} {topic_keywords}")
            
            # Query 3: Guest + Podcast (reversed)
            queries.append(f"{guest_name} {podcast_name}")
        else:
            # No clear guest pattern
            # Query 1: Podcast + First few words of title
            title_words = title_clean.split()[:6]
            queries.append(f"{podcast_name} {' '.join(title_words)}")
            
            # Query 2: Just significant keywords
            # Remove common words
            stop_words = {'the', 'a', 'an', 'of', 'with', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
            keywords = [w for w in title_words if w.lower() not in stop_words][:4]
            if keywords:
                queries.append(f"{podcast_name} {' '.join(keywords)}")
        
        # Query 3: Episode number if present (as fallback)
        episode_num_match = re.search(r'#?(\d+)', title)
        if episode_num_match and len(queries) < 3:
            queries.append(f"{podcast_name} episode {episode_num_match.group(1)}")
        
        # Clean up all queries
        cleaned_queries = []
        for query in queries:
            # Remove special characters
            query = re.sub(r'[#\-–—:]', ' ', query)
            query = re.sub(r'\s+', ' ', query).strip()
            # Limit length
            query = query[:80]  # Shorter queries work better
            if query and query not in cleaned_queries:
                cleaned_queries.append(query)
        
        return cleaned_queries[:3]  # Return top 3 queries
    
    async def _find_apple_podcast_sources(self, episode: Episode, podcast_config: Optional[Dict] = None) -> List[str]:
        """Find Apple Podcast sources specifically (wrapper for clarity)"""
        sources = []
        apple_url = await self._find_apple_podcasts_url(episode, podcast_config)
        if apple_url:
            sources.append(apple_url)
            logger.info(f"🍎 Found Apple Podcasts audio URL")
        return sources
    
    async def _find_youtube_version(self, episode: Episode, podcast_config: Optional[Dict] = None) -> Optional[str]:
        """Find YouTube version of the episode"""
        try:
            import os
            
            # Build optimized search queries
            queries = self._build_youtube_queries(episode)
            
            # Check if YouTube API key is available
            youtube_api_key = os.getenv('YOUTUBE_API_KEY')
            
            # Try each query until we find a match
            for search_query in queries:
                logger.debug(f"🔍 YouTube search: {search_query}")
                
                if youtube_api_key:
                    result = await self._search_youtube_api(search_query, episode, youtube_api_key)
                else:
                    result = await self._search_youtube_web(search_query, episode)
                
                if result:
                    return result
            
        except Exception as e:
            logger.debug(f"Error finding YouTube version: {e}")
        
        return None
    
    async def _search_youtube_api(self, query: str, episode: Episode, api_key: str) -> Optional[str]:
        """Search YouTube using official API"""
        try:
            session = await self._get_session()
            
            # YouTube Data API v3 search endpoint
            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                'part': 'snippet',
                'q': query,
                'type': 'video',
                'maxResults': 10,
                'order': 'relevance',
                'videoDuration': 'long',  # Prefer longer videos (podcasts)
                'key': api_key
            }
            
            async with session.get(search_url, params=params) as response:
                if response.status != 200:
                    logger.warning(f"YouTube API error: {response.status}")
                    # Try yt-dlp fallback
                    return await self._search_youtube_ytdlp(query, episode)
                
                data = await response.json()
                
                if 'items' not in data or not data['items']:
                    return None
                
                # Try to find best match
                episode_date = episode.published
                episode_title_lower = episode.title.lower()
                
                for item in data['items']:
                    snippet = item.get('snippet', {})
                    video_id = item.get('id', {}).get('videoId')
                    
                    if not video_id:
                        continue
                    
                    # Check title similarity
                    video_title = snippet.get('title', '').lower()
                    channel_title = snippet.get('channelTitle', '').lower()
                    
                    # Score based on title match
                    title_match_score = 0
                    if episode.podcast.lower() in channel_title:
                        title_match_score += 2
                    
                    # Check for key words from episode title
                    title_words = set(episode_title_lower.split())
                    video_words = set(video_title.split())
                    common_words = title_words & video_words
                    
                    if len(common_words) >= min(3, len(title_words) * 0.5):
                        title_match_score += len(common_words)
                    
                    # Check publish date proximity
                    if 'publishedAt' in snippet:
                        import datetime
                        video_date = datetime.datetime.fromisoformat(
                            snippet['publishedAt'].replace('Z', '+00:00')
                        ).replace(tzinfo=None)
                        
                        days_diff = abs((video_date - episode_date).days)
                        if days_diff <= 7:  # Within a week
                            title_match_score += 3
                    
                    # If good match, return YouTube URL
                    if title_match_score >= 4:
                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                        logger.info(f"✅ Found YouTube version: {youtube_url}")
                        return youtube_url
                
        except Exception as e:
            logger.error(f"YouTube API search error: {e}")
        
        return None
    
    async def _search_youtube_ytdlp(self, query: str, episode: Episode) -> Optional[str]:
        """Search YouTube using yt-dlp when API fails"""
        try:
            from .youtube_ytdlp_api import YtDlpSearcher
            
            logger.info(f"Using yt-dlp for YouTube search: {query}")
            
            # Search for videos
            videos = await YtDlpSearcher.search_youtube(query, limit=5)
            
            if not videos:
                return None
            
            # Find best match
            best_match = YtDlpSearcher.match_episode(
                query, 
                videos, 
                episode.published if hasattr(episode, 'published') else None
            )
            
            if best_match:
                return best_match['url']
                
        except Exception as e:
            logger.error(f"yt-dlp search error: {e}")
        
        return None
    
    async def _search_youtube_web(self, query: str, episode: Episode) -> Optional[str]:
        """Search YouTube via web scraping (fallback)"""
        try:
            session = await self._get_session()
            
            # Use YouTube search URL
            search_url = "https://www.youtube.com/results"
            params = {'search_query': query}
            
            async with session.get(search_url, params=params) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                
                # Look for video IDs in the response
                # YouTube embeds video IDs in various places
                import json
                
                # Try to find ytInitialData
                match = re.search(r'var ytInitialData = ({.*?});', html)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        
                        # Navigate through the data structure to find videos
                        contents = (data.get('contents', {})
                                      .get('twoColumnSearchResultsRenderer', {})
                                      .get('primaryContents', {})
                                      .get('sectionListRenderer', {})
                                      .get('contents', []))
                        
                        for section in contents:
                            items = (section.get('itemSectionRenderer', {})
                                          .get('contents', []))
                            
                            for item in items[:5]:  # Check first 5 results
                                video = item.get('videoRenderer', {})
                                if not video:
                                    continue
                                
                                video_id = video.get('videoId')
                                if not video_id:
                                    continue
                                
                                # Check title
                                title_runs = video.get('title', {}).get('runs', [])
                                if title_runs:
                                    video_title = ' '.join(run.get('text', '') for run in title_runs).lower()
                                    
                                    # Simple matching
                                    if (episode.podcast.lower() in video_title or 
                                        any(word in video_title for word in episode.title.lower().split()[:3])):
                                        
                                        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
                                        logger.info(f"✅ Found YouTube version via web: {youtube_url}")
                                        return youtube_url
                    
                    except json.JSONDecodeError:
                        pass
                
                # Fallback: regex search for video IDs
                video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                if video_ids:
                    # Return the first one as a guess
                    youtube_url = f"https://www.youtube.com/watch?v={video_ids[0]}"
                    logger.info(f"✅ Found potential YouTube version: {youtube_url}")
                    return youtube_url
                    
        except Exception as e:
            logger.debug(f"YouTube web search error: {e}")
        
        return None
    
    async def _find_spotify_url(self, episode: Episode) -> Optional[str]:
        """Find Spotify URL for episode using Web API"""
        try:
            import os
            import base64
            
            # Check for Spotify API credentials
            client_id = os.getenv('SPOTIFY_CLIENT_ID')
            client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
            
            if not client_id or not client_secret:
                # Try web scraping approach
                return await self._search_spotify_web(episode)
            
            # Get access token
            token = await self._get_spotify_token(client_id, client_secret)
            if not token:
                return None
                
            session = await self._get_session()
            
            # Search for the episode
            search_query = f"{episode.podcast} {episode.title}"
            search_query = re.sub(r'[#\-–—:]', ' ', search_query)
            search_query = re.sub(r'\s+', ' ', search_query).strip()[:100]
            
            search_url = "https://api.spotify.com/v1/search"
            params = {
                'q': search_query,
                'type': 'episode',
                'limit': 10
            }
            headers = {
                'Authorization': f'Bearer {token}'
            }
            
            async with session.get(search_url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Spotify API error: {response.status}")
                    return None
                    
                data = await response.json()
                
                if not data.get('episodes', {}).get('items'):
                    return None
                
                # Find best match
                episode_title_lower = episode.title.lower()
                
                for item in data['episodes']['items']:
                    # Check title match
                    spotify_title = item.get('name', '').lower()
                    show_name = item.get('show', {}).get('name', '').lower()
                    
                    # Score matching
                    if (episode.podcast.lower() in show_name and
                        (episode_title_lower in spotify_title or
                         self._title_similarity(episode_title_lower, spotify_title) > 0.7)):
                        
                        # Get audio preview or episode URL
                        audio_preview = item.get('audio_preview_url')
                        episode_uri = item.get('uri')
                        
                        if audio_preview:
                            logger.info(f"✅ Found Spotify audio preview: {audio_preview}")
                            return audio_preview
                        elif episode_uri:
                            # Convert URI to web URL
                            episode_id = episode_uri.split(':')[-1]
                            web_url = f"https://open.spotify.com/episode/{episode_id}"
                            logger.info(f"✅ Found Spotify episode: {web_url}")
                            # Note: This returns the web URL, not direct audio
                            # Would need additional processing to get audio
                            return None
                
        except Exception as e:
            logger.error(f"Spotify API error: {e}")
            
        return None
    
    async def _get_spotify_token(self, client_id: str, client_secret: str) -> Optional[str]:
        """Get Spotify access token"""
        try:
            session = await self._get_session()
            
            # Encode credentials
            credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            
            token_url = "https://accounts.spotify.com/api/token"
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'grant_type': 'client_credentials'
            }
            
            async with session.post(token_url, headers=headers, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    return token_data.get('access_token')
                    
        except Exception as e:
            logger.error(f"Spotify token error: {e}")
            
        return None
    
    async def _search_spotify_web(self, episode: Episode) -> Optional[str]:
        """Search Spotify via web (fallback)"""
        # Note: Spotify web search is complex due to dynamic content
        # This is a placeholder for now
        logger.debug("Spotify web search not implemented")
        return None
    
    def _title_similarity(self, title1: str, title2: str) -> float:
        """Calculate title similarity score"""
        # Simple word overlap similarity
        words1 = set(title1.lower().split())
        words2 = set(title2.lower().split())
        
        if not words1 or not words2:
            return 0.0
            
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)
    
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