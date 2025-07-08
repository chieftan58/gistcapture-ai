"""Episode fetching with multiple fallback sources and bulletproof recovery"""

import re
import requests
import feedparser
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urljoin, quote, urlparse
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import json
import time
import hashlib
import uuid
from functools import lru_cache
import concurrent.futures
import threading

from ..models import Episode
from ..database import PodcastDatabase
from ..config import PODCAST_CONFIGS
from ..utils.logging import get_logger
from ..utils.helpers import seconds_to_duration, CircuitBreaker, ProgressTracker
from .podcast_index import PodcastIndexClient

logger = get_logger(__name__)


class FeedCache:
    """Cache for feed URLs with TTL"""
    
    def __init__(self, ttl_seconds: int = 3600):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[List[str]]:
        """Get cached feed URLs if not expired"""
        if key in self.cache:
            urls, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return urls
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, urls: List[str]):
        """Cache feed URLs with timestamp"""
        self.cache[key] = (urls, time.time())
    
    def clear_expired(self):
        """Remove expired entries"""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if current_time - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]


class ReliableEpisodeFetcher:
    """Bulletproof episode fetching with aggressive fallback strategies"""
    
    def __init__(self, db: PodcastDatabase):
        self.db = db
        self.podcast_index = PodcastIndexClient()
        self._http_session = None  # Shared requests session
        self._aiohttp_session = None  # Shared aiohttp session
        self._session_initialized = False
        self._correlation_id = str(uuid.uuid4())[:8]
        
        # Cache for feed URLs discovered through various methods
        self.discovered_feeds_cache = {}
        
        # Feed URL cache with TTL
        self.feed_cache = FeedCache(ttl_seconds=3600)  # 1 hour TTL
        
        # Circuit breakers for failing feeds
        self.circuit_breakers = {}  # URL -> CircuitBreaker
        
        # Track failed URLs to avoid retrying too often
        self.failed_urls = {}  # URL -> (failure_count, last_failure_time)
        self.max_failures = 3
        self.failure_cooldown = 300  # 5 minutes
    
    def _get_http_session(self) -> requests.Session:
        """Get or create shared HTTP session with proper headers"""
        if not self._http_session:
            self._http_session = requests.Session()
            self._http_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            # Connection pooling settings
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10,
                pool_maxsize=20,
                max_retries=requests.adapters.Retry(
                    total=3,
                    backoff_factor=0.3,
                    status_forcelist=[500, 502, 503, 504]
                )
            )
            self._http_session.mount('http://', adapter)
            self._http_session.mount('https://', adapter)
            
        return self._http_session
    
    async def _get_aiohttp_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session"""
        if self._aiohttp_session is None or self._aiohttp_session.closed:
            timeout = aiohttp.ClientTimeout(
                total=60,
                connect=10,
                sock_read=30
            )
            connector = aiohttp.TCPConnector(
                limit=30,
                limit_per_host=5,
                force_close=True,
                enable_cleanup_closed=True
            )
            self._aiohttp_session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            )
        return self._aiohttp_session
    
    async def cleanup(self):
        """Cleanup resources"""
        # Close HTTP session
        if self._http_session:
            self._http_session.close()
            self._http_session = None
        
        # Close aiohttp session
        if self._aiohttp_session and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()
            self._aiohttp_session = None
        
        # Clear caches
        self.circuit_breakers.clear()
        self.failed_urls.clear()
        self.feed_cache.cache.clear()
        
        logger.info(f"[{self._correlation_id}] Episode fetcher cleaned up")
    
    def _get_circuit_breaker(self, url: str) -> CircuitBreaker:
        """Get or create circuit breaker for URL"""
        if url not in self.circuit_breakers:
            self.circuit_breakers[url] = CircuitBreaker(
                failure_threshold=3,
                recovery_timeout=300,  # 5 minutes
                correlation_id=self._correlation_id
            )
        return self.circuit_breakers[url]
    
    def _should_skip_url(self, url: str) -> bool:
        """Check if URL should be skipped due to recent failures"""
        if url in self.failed_urls:
            failure_count, last_failure = self.failed_urls[url]
            
            # Check if in cooldown period
            if time.time() - last_failure < self.failure_cooldown:
                if failure_count >= self.max_failures:
                    logger.debug(f"[{self._correlation_id}] Skipping URL due to failures: {url[:50]}...")
                    return True
        
        return False
    
    def _record_url_failure(self, url: str):
        """Record URL failure for tracking"""
        if url in self.failed_urls:
            count, _ = self.failed_urls[url]
            self.failed_urls[url] = (count + 1, time.time())
        else:
            self.failed_urls[url] = (1, time.time())
    
    def _record_url_success(self, url: str):
        """Clear URL from failure tracking on success"""
        if url in self.failed_urls:
            del self.failed_urls[url]
    
    @lru_cache(maxsize=128)
    def _get_feed_url_hash(self, url: str) -> str:
        """Get hash of feed URL for caching"""
        return hashlib.md5(url.encode()).hexdigest()
    
    async def fetch_episodes(self, podcast_config: Dict, days_back: int = 7) -> List[Episode]:
        """Bulletproof episode fetching - ensures we find ALL episodes"""
        podcast_name = podcast_config["name"]
        correlation_id = f"{self._correlation_id}-{podcast_name[:10]}"
        logger.info(f"[{correlation_id}] 📡 Fetching episodes for {podcast_name}")
        
        # Store apple_id for episode creation
        self._current_apple_id = podcast_config.get("apple_id")
        
        # Clean up expired cache entries
        self.feed_cache.clear_expired()
        
        # Check feed cache first
        cache_key = f"{podcast_name}:{days_back}"
        cached_feed_urls = self.feed_cache.get(cache_key)
        
        # Collect all episodes from all sources
        all_episodes = {}  # Use dict to deduplicate by guid/title
        methods_tried = []
        
        # Method 1: Try configured RSS feeds (with cache)
        if "rss_feeds" in podcast_config and podcast_config["rss_feeds"]:
            methods_tried.append("RSS feeds")
            
            # Use cached feeds if available
            feed_urls = cached_feed_urls if cached_feed_urls else podcast_config["rss_feeds"]
            
            episodes = await self._try_all_rss_sources(
                podcast_name, podcast_config, days_back, correlation_id, feed_urls
            )
            for ep in episodes:
                all_episodes[self._episode_key(ep)] = ep
        
        # Method 2: Try Apple Podcasts (always try this)
        if "apple_id" in podcast_config and podcast_config["apple_id"]:
            methods_tried.append("Apple Podcasts")
            episodes = await self._comprehensive_apple_search(
                podcast_name, podcast_config["apple_id"], days_back, correlation_id
            )
            for ep in episodes:
                all_episodes[self._episode_key(ep)] = ep
        
        # Method 3: Use search_term for better discovery
        search_term = podcast_config.get("search_term", podcast_name)
        if search_term and len(all_episodes) == 0:  # Only if we haven't found episodes yet
            methods_tried.append("Enhanced search")
            logger.info(f"[{correlation_id}]   🔍 Using search term: {search_term}")
            # Search Apple with the search term
            episodes = await self._search_apple_by_term(search_term, days_back, correlation_id)
            for ep in episodes:
                all_episodes[self._episode_key(ep)] = ep
        
        # Method 4: Search for podcast across multiple platforms
        # DISABLED: This is returning episodes from wrong podcasts with similar names
        # TODO: Add validation to ensure episodes are from the correct podcast
        # if len(all_episodes) < 3:  # If we have very few episodes
        #     methods_tried.append("Multi-platform search")
        #     episodes = await self._multi_platform_search(podcast_name, days_back, correlation_id)
        #     for ep in episodes:
        #         all_episodes[self._episode_key(ep)] = ep
        
        # Method 5: Try PodcastIndex
        # DISABLED: This is returning episodes from wrong podcasts with similar names
        # TODO: Add validation to ensure the podcast returned matches the expected podcast
        # if len(all_episodes) < 5:  # Still need more episodes
        #     methods_tried.append("PodcastIndex")
        #     episodes = await self._try_podcast_index(podcast_name, days_back, correlation_id)
        #     for ep in episodes:
        #         all_episodes[self._episode_key(ep)] = ep
        
        # Method 6: Try web scraping (only if website is provided)
        if podcast_config.get("website") and len(all_episodes) < 5:
            methods_tried.append("Web scraping")
            episodes = await self._try_web_scraping(
                podcast_name, podcast_config["website"], days_back, correlation_id
            )
            for ep in episodes:
                all_episodes[self._episode_key(ep)] = ep
        
        # Method 7: Google search for RSS feeds (last resort)
        if len(all_episodes) == 0:
            methods_tried.append("Google RSS search")
            episodes = await self._google_rss_search(podcast_name, days_back, correlation_id)
            for ep in episodes:
                all_episodes[self._episode_key(ep)] = ep
        
        # Convert back to list
        final_episodes = list(all_episodes.values())
        
        # Cache successful feed URLs
        if final_episodes and podcast_name in self.discovered_feeds_cache:
            self.feed_cache.set(cache_key, self.discovered_feeds_cache[podcast_name])
        
        if final_episodes:
            logger.info(f"[{correlation_id}] ✅ Found {len(final_episodes)} unique episodes via: {', '.join(methods_tried)}")
        else:
            # Check if we successfully accessed feeds but found no episodes in the date range
            if methods_tried and 'RSS feeds' in methods_tried:
                logger.info(f"[{correlation_id}] 📅 No episodes found for {podcast_name} in the last {days_back} days")
                logger.info(f"[{correlation_id}]    Successfully checked: {', '.join(methods_tried)}")
            else:
                logger.error(f"[{correlation_id}] ❌ Could not fetch episodes for {podcast_name} from any source")
                logger.error(f"[{correlation_id}]    Methods tried: {', '.join(methods_tried)}")
                
                # Last resort: Manual intervention suggestion
                logger.warning(f"[{correlation_id}] 💡 Manual intervention needed for {podcast_name}")
                logger.warning(f"[{correlation_id}]    Consider checking the Apple ID or adding more identifiers to podcasts.yaml")
        
        return final_episodes
    
    def _episode_key(self, episode: Episode) -> str:
        """Create a unique key for episode deduplication"""
        # Always use title + date for consistent deduplication
        # This prevents the same episode with different GUIDs from being duplicated
        
        # Remove common episode number prefixes
        title = episode.title.lower()
        # Remove patterns like "#123 -", "Episode 123:", "Ep. 123 |", etc.
        title = re.sub(r'^(#?\d+\s*[-–—|:]?\s*|episode\s+\d+\s*[-–—|:]?\s*|ep\.?\s*\d+\s*[-–—|:]?\s*)', '', title, flags=re.IGNORECASE)
        
        # Remove guest name prefixes (e.g., "Katherine Boyle: How Tech..." -> "How Tech...")
        # Pattern: "Name Name: " at the beginning
        title = re.sub(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*:\s*', '', title, flags=re.MULTILINE)
        
        # Also check if the title contains a colon and the part after it matches another episode
        # This handles cases where the full title is "Guest: Topic" but RSS might just have "Topic"
        if ':' in title:
            # Get the part after the colon as a potential match
            after_colon = title.split(':', 1)[1].strip()
            # We'll use the shorter version for matching
            if len(after_colon) > 10:  # Only if it's substantial
                title = after_colon
        
        # Clean remaining non-alphanumeric characters
        title_clean = re.sub(r'[^\w\s]', '', title)
        date_str = episode.published.strftime('%Y%m%d')
        return f"{title_clean}_{date_str}"
    
    async def _try_all_rss_sources(self, podcast_name: str, podcast_config: Dict, 
                                  days_back: int, correlation_id: str, 
                                  initial_feed_urls: List[str]) -> List[Episode]:
        """Try all possible RSS sources including discovered ones"""
        all_episodes = []
        tried_urls = set()
        
        # Start with provided feeds
        feed_urls = list(initial_feed_urls)
        
        # Add any cached discovered feeds
        if podcast_name in self.discovered_feeds_cache:
            feed_urls.extend(self.discovered_feeds_cache[podcast_name])
        
        # Try to discover more feeds
        if "apple_id" in podcast_config:
            apple_feed = await self._get_apple_feed_url(podcast_config["apple_id"], correlation_id)
            if apple_feed:
                feed_urls.append(apple_feed)
        
        # Deduplicate
        feed_urls = list(set(feed_urls))
        
        # Progress tracking
        progress = ProgressTracker(len(feed_urls), correlation_id)
        
        for url in feed_urls:
            if url in tried_urls:
                continue
            tried_urls.add(url)
            
            # Skip if URL has failed recently
            if self._should_skip_url(url):
                continue
            
            # Get circuit breaker for this URL
            circuit_breaker = self._get_circuit_breaker(url)
            
            try:
                await progress.start_item(f"RSS: {url[:50]}...")
                
                # Try to fetch through circuit breaker
                async def fetch_rss():
                    return await self._try_rss_with_fallbacks(
                        podcast_name, url, days_back, correlation_id
                    )
                
                episodes = await circuit_breaker.call(fetch_rss)
                all_episodes.extend(episodes)
                
                if episodes:
                    self._record_url_success(url)
                    await progress.complete_item(True)
                else:
                    await progress.complete_item(False)
                    
            except Exception as e:
                logger.debug(f"[{correlation_id}] RSS fetch failed for {url[:50]}...: {e}")
                self._record_url_failure(url)
                await progress.complete_item(False)
        
        # Log progress summary
        summary = progress.get_summary()
        if summary['completed'] > 0:
            logger.info(
                f"[{correlation_id}] RSS fetch complete: "
                f"{summary['completed']}/{summary['total_items']} successful "
                f"({summary['success_rate']:.0f}% success rate)"
            )
        
        return all_episodes
    
    async def _try_rss_with_fallbacks(self, podcast_name: str, feed_url: str, 
                                     days_back: int, correlation_id: str) -> List[Episode]:
        """Try RSS feed with multiple fallback strategies"""
        logger.info(f"[{correlation_id}]   Trying RSS: {feed_url}")
        
        # Try different user agents
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'iTunes/12.12 (Windows; Microsoft Windows 10 x64)',
            'Podcasts/1.0',
            'curl/7.68.0',
            'Renaissance Weekly Bot/1.0'
        ]
        
        session = self._get_http_session()
        
        for ua in user_agents:
            try:
                headers = {'User-Agent': ua}
                
                # Universal streaming approach with size limit
                response = session.get(feed_url, timeout=20, headers=headers, allow_redirects=True, stream=True)
                
                if response.status_code == 200:
                    # Smart RSS parsing - only download what we need
                    content = b''
                    # Most RSS feeds have recent episodes first, so we only need a small portion
                    # 500KB is enough to get 10-15 recent episodes from most feeds
                    initial_size = 500 * 1024  # 500KB initial chunk
                    max_size = 2 * 1024 * 1024  # 2MB absolute max (even for huge feeds)
                    
                    # Track if we have enough complete episodes
                    item_count = 0
                    complete_items = 0
                    
                    for chunk in response.iter_content(chunk_size=8192):
                        content += chunk
                        
                        # Count opening and closing item tags
                        chunk_str = chunk.decode('utf-8', errors='ignore')
                        item_count += chunk_str.count('<item>')
                        complete_items += chunk_str.count('</item>')
                        
                        # Stop if we have at least 5 complete episodes
                        if complete_items >= 5 and len(content) >= initial_size:
                            logger.info(f"[{correlation_id}]     Got {complete_items} complete episodes in {len(content)/1024:.0f}KB")
                            break
                            
                        # Absolute limit to prevent downloading huge feeds
                        if len(content) >= max_size:
                            logger.info(f"[{correlation_id}]     Reached max size limit ({max_size/(1024*1024):.1f}MB) with {complete_items} complete episodes")
                            break
                    
                    response.close()
                    
                    # Ensure XML is properly closed if we stopped mid-stream
                    if content and complete_items < item_count:
                        # Find the last complete </item> tag
                        last_item_end = content.rfind(b'</item>')
                        if last_item_end > 0:
                            # Truncate to last complete item and close the XML
                            content = content[:last_item_end + 7]  # +7 for '</item>'
                            # Add closing tags if needed
                            if b'</channel>' not in content:
                                content += b'\n</channel>'
                            if b'</rss>' not in content:
                                content += b'\n</rss>'
                    
                    # Parse whatever we got
                    if content:
                        episodes = self._parse_rss_feed(content, podcast_name, days_back, correlation_id)
                        if episodes:
                            # Cache this feed URL as successful
                            if podcast_name not in self.discovered_feeds_cache:
                                self.discovered_feeds_cache[podcast_name] = []
                            if feed_url not in self.discovered_feeds_cache[podcast_name]:
                                self.discovered_feeds_cache[podcast_name].append(feed_url)
                            return episodes
                    elif response.status_code == 403:
                        logger.debug(f"[{correlation_id}]     403 with UA: {ua[:30]}...")
                        continue
                    else:
                        logger.warning(f"[{correlation_id}]     HTTP {response.status_code}")
                        break
                    
            except requests.Timeout:
                logger.warning(f"[{correlation_id}]     Timeout with UA: {ua[:30]}...")
                continue
            except Exception as e:
                logger.warning(f"[{correlation_id}]     Error with UA {ua[:30]}...: {e}")
                continue
        
        return []
    
    def _parse_feed_with_timeout(self, content: bytes, correlation_id: str, timeout: int = 20):
        """Parse feedparser content with timeout protection"""
        import feedparser
        
        # Use ThreadPoolExecutor to enforce timeout on feedparser.parse()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(feedparser.parse, content)
            try:
                # Wait for parsing to complete with timeout
                feed = future.result(timeout=timeout)
                return feed
            except concurrent.futures.TimeoutError:
                logger.error(f"[{correlation_id}]     Feedparser timed out after {timeout}s - skipping this feed")
                # Cancel the future if possible
                future.cancel()
                # Return empty feed structure
                return type('obj', (object,), {'entries': []})()
            except Exception as e:
                logger.error(f"[{correlation_id}]     Feedparser error: {e}")
                return type('obj', (object,), {'entries': []})()
    
    def _parse_rss_feed(self, content: bytes, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Parse RSS feed content into episodes with more robust parsing"""
        try:
            # Parse RSS feed with timeout protection
            feed = self._parse_feed_with_timeout(content, correlation_id)
            
            if not feed or not hasattr(feed, 'entries') or not feed.entries:
                logger.warning(f"[{correlation_id}]     No entries in feed")
                return []
            
            episodes = []
            cutoff = datetime.now() - timedelta(days=days_back)
            
            logger.debug(f"[{correlation_id}]     Feed has {len(feed.entries)} entries, checking last {days_back} days")
            
            # Check more entries in case dates are out of order
            for i, entry in enumerate(feed.entries[:100]):  # Increased from 50
                try:
                    # Log first few entries for debugging
                    if i < 3:
                        logger.debug(f"[{correlation_id}]     Entry {i}: {entry.get('title', 'No title')[:50]}")
                    
                    pub_date = self._parse_date(entry)
                    if not pub_date:
                        if i < 3:
                            logger.debug(f"[{correlation_id}]       No valid date found")
                        continue
                    
                    if i < 3:
                        logger.debug(f"[{correlation_id}]       Published: {pub_date.strftime('%Y-%m-%d')}")
                    
                    # Don't stop on old episodes - some feeds aren't chronological
                    if pub_date < cutoff:
                        continue
                    
                    audio_url = self._extract_audio_url(entry)
                    if not audio_url:
                        logger.debug(f"[{correlation_id}]       No audio URL for: {entry.get('title', 'Unknown')[:50]}")
                        continue
                    
                    episode = Episode(
                        podcast=podcast_name,
                        title=entry.get('title', 'Unknown'),
                        published=pub_date,
                        audio_url=audio_url,
                        transcript_url=self._extract_transcript_url(entry),
                        description=self._extract_full_description(entry),
                        link=entry.get('link', ''),
                        duration=self._extract_duration(entry),
                        guid=entry.get('guid', entry.get('id', '')),
                        apple_podcast_id=getattr(self, '_current_apple_id', None)
                    )
                    episodes.append(episode)
                    logger.debug(f"[{correlation_id}]     ✓ Added episode: {episode.title[:50]} ({episode.published.strftime('%Y-%m-%d')})")
                    
                except Exception as e:
                    logger.debug(f"[{correlation_id}]     Error parsing entry {i}: {e}")
                    continue
            
            logger.info(f"[{correlation_id}]     Found {len(episodes)} episodes from this feed")
            return episodes
            
        except Exception as e:
            logger.error(f"[{correlation_id}]     Feed parse error: {e}")
            return []
    
    async def _comprehensive_apple_search(self, podcast_name: str, apple_id: str, 
                                         days_back: int, correlation_id: str) -> List[Episode]:
        """Comprehensive Apple Podcasts search with multiple strategies"""
        episodes = []
        session = self._get_http_session()
        
        logger.info(f"[{correlation_id}]   🍎 Searching Apple Podcasts (ID: {apple_id})")
        
        # Strategy 1: Direct lookup API
        try:
            lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
            logger.debug(f"[{correlation_id}]     Trying Apple lookup: {lookup_url}")
            response = session.get(lookup_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                logger.debug(f"[{correlation_id}]     Apple lookup response: {data.get('resultCount', 0)} results")
                
                if data.get("results"):
                    podcast_info = data["results"][0]
                    feed_url = podcast_info.get("feedUrl")
                    logger.info(f"[{correlation_id}]     Found feed URL: {feed_url}")
                    
                    if feed_url:
                        episodes.extend(
                            await self._try_rss_with_fallbacks(
                                podcast_name, feed_url, days_back, correlation_id
                            )
                        )
                        
                        # Cache this feed URL
                        if podcast_name not in self.discovered_feeds_cache:
                            self.discovered_feeds_cache[podcast_name] = []
                        self.discovered_feeds_cache[podcast_name].append(feed_url)
                    else:
                        logger.warning(f"[{correlation_id}]     No feed URL in Apple data")
                else:
                    logger.warning(f"[{correlation_id}]     No results for Apple ID {apple_id}")
            else:
                logger.warning(f"[{correlation_id}]     Apple lookup failed with status {response.status_code}")
                
        except Exception as e:
            logger.error(f"[{correlation_id}]     Apple lookup error: {e}")
        
        # Strategy 2: Search API if no episodes found
        if not episodes:
            try:
                logger.info(f"[{correlation_id}]     Trying Apple search API...")
                search_url = "https://itunes.apple.com/search"
                
                # Try searching by podcast name
                params = {
                    "term": podcast_name,
                    "media": "podcast",
                    "entity": "podcast",
                    "limit": 10
                }
                
                response = session.get(search_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"[{correlation_id}]     Search found {data.get('resultCount', 0)} podcasts")
                    
                    for result in data.get("results", []):
                        # Check if this matches our apple ID or podcast name
                        result_id = str(result.get("trackId", result.get("collectionId", "")))
                        result_name = result.get("trackName", "").lower()
                        
                        if result_id == apple_id or podcast_name.lower() in result_name:
                            feed_url = result.get("feedUrl")
                            if feed_url:
                                logger.info(f"[{correlation_id}]     Found matching podcast with feed: {feed_url}")
                                episodes.extend(
                                    await self._try_rss_with_fallbacks(
                                        podcast_name, feed_url, days_back, correlation_id
                                    )
                                )
                                
                                # Cache the feed
                                if podcast_name not in self.discovered_feeds_cache:
                                    self.discovered_feeds_cache[podcast_name] = []
                                self.discovered_feeds_cache[podcast_name].append(feed_url)
                                break
            except Exception as e:
                logger.error(f"[{correlation_id}]     Apple search error: {e}")
        
        # Strategy 3: Try alternative Apple endpoints
        if not episodes:
            try:
                # Try the lookup with different parameters
                alt_lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcastEpisode&limit=50"
                logger.info(f"[{correlation_id}]     Trying alternative Apple lookup for episodes...")
                response = session.get(alt_lookup_url, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    logger.debug(f"[{correlation_id}]     Alternative lookup found {data.get('resultCount', 0)} items")
                    
                    # This might return episodes directly
                    cutoff = datetime.now() - timedelta(days=days_back)
                    
                    for item in data.get("results", []):
                        if item.get("wrapperType") == "podcastEpisode":
                            try:
                                pub_date = datetime.fromisoformat(item.get("releaseDate", "").replace("Z", "+00:00"))
                                if pub_date.tzinfo:
                                    pub_date = pub_date.replace(tzinfo=None)
                                
                                if pub_date >= cutoff:
                                    episode = Episode(
                                        podcast=podcast_name,
                                        title=item.get("trackName", "Unknown"),
                                        published=pub_date,
                                        audio_url=item.get("episodeUrl", item.get("previewUrl")),
                                        description=item.get("description", ""),
                                        duration=self._format_duration(str(item.get("trackTimeMillis", 0) // 1000)),
                                        guid=str(item.get("trackId", "")),
                                        apple_podcast_id=apple_id
                                    )
                                    episodes.append(episode)
                            except Exception as e:
                                logger.debug(f"[{correlation_id}]     Error parsing episode: {e}")
                                continue
                                
            except Exception as e:
                logger.error(f"[{correlation_id}]     Alternative Apple lookup error: {e}")
        
        if episodes:
            logger.info(f"[{correlation_id}]   ✅ Found {len(episodes)} episodes from Apple Podcasts")
        else:
            logger.warning(f"[{correlation_id}]   ⚠️ No episodes found from Apple Podcasts ID {apple_id}")
        
        return episodes
    
    async def _multi_platform_search(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search multiple podcast platforms for episodes"""
        episodes = []
        
        # Platform-specific search strategies
        platforms = [
            ("Spotify", self._search_spotify),
            ("Google Podcasts", self._search_google_podcasts),
            ("Podcast Addict", self._search_podcast_addict),
            ("Listen Notes", self._search_listen_notes),
        ]
        
        for platform_name, search_func in platforms:
            try:
                logger.debug(f"[{correlation_id}]   Searching {platform_name}...")
                platform_episodes = await search_func(podcast_name, days_back, correlation_id)
                episodes.extend(platform_episodes)
            except Exception as e:
                logger.debug(f"[{correlation_id}]   {platform_name} search failed: {e}")
        
        return episodes
    
    async def _search_spotify(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search Spotify for podcast (placeholder for future implementation)"""
        # Spotify requires OAuth, so this is a placeholder
        # Could be implemented with Spotify Web API in the future
        return []
    
    async def _search_google_podcasts(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search Google for podcast RSS feeds"""
        try:
            session = self._get_http_session()
            
            # Google search for RSS feeds
            query = f'"{podcast_name}" podcast RSS feed filetype:xml OR filetype:rss'
            search_url = f"https://www.google.com/search?q={quote(query)}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = session.get(search_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract URLs that might be RSS feeds
                feed_urls = []
                for link in soup.find_all('a'):
                    href = link.get('href', '')
                    if any(indicator in href.lower() for indicator in ['rss', 'feed', 'xml', 'podcast']):
                        # Extract actual URL from Google redirect
                        if '/url?q=' in href:
                            actual_url = href.split('/url?q=')[1].split('&')[0]
                            feed_urls.append(actual_url)
                
                # Try each discovered feed
                episodes = []
                for feed_url in feed_urls[:5]:  # Limit to first 5
                    eps = await self._try_rss_with_fallbacks(podcast_name, feed_url, days_back, correlation_id)
                    episodes.extend(eps)
                
                return episodes
                
        except Exception as e:
            logger.debug(f"[{correlation_id}] Google search error: {e}")
        
        return []
    
    async def _search_podcast_addict(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search Podcast Addict database (placeholder)"""
        # Would require API access or web scraping
        return []
    
    async def _search_listen_notes(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search Listen Notes API (requires API key)"""
        # Listen Notes has a good API but requires registration
        # This is a placeholder for future implementation
        return []
    
    async def _google_rss_search(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Use Google to find RSS feeds for the podcast"""
        episodes = []
        session = self._get_http_session()
        
        # Various search queries to try
        queries = [
            f'"{podcast_name}" RSS feed site:feeds.megaphone.fm',
            f'"{podcast_name}" RSS feed site:libsyn.com',
            f'"{podcast_name}" RSS feed site:anchor.fm',
            f'"{podcast_name}" RSS feed site:feeds.simplecast.com',
            f'"{podcast_name}" RSS feed site:rss.art19.com',
            f'"{podcast_name}" podcast feed URL',
        ]
        
        for query in queries:
            try:
                await asyncio.sleep(1)  # Be polite to Google
                
                search_url = f"https://www.google.com/search?q={quote(query)}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
                }
                
                response = session.get(search_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    # Extract potential RSS URLs from search results
                    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+\.(?:rss|xml)', response.text)
                    
                    for url in set(urls[:3]):  # Try first 3 unique URLs
                        eps = await self._try_rss_with_fallbacks(podcast_name, url, days_back, correlation_id)
                        episodes.extend(eps)
                        
                        if eps:  # Cache successful feed
                            if podcast_name not in self.discovered_feeds_cache:
                                self.discovered_feeds_cache[podcast_name] = []
                            self.discovered_feeds_cache[podcast_name].append(url)
                            
            except Exception as e:
                logger.debug(f"[{correlation_id}] Google RSS search error: {e}")
        
        return episodes
    
    async def _search_apple_by_term(self, search_term: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Search Apple Podcasts using a search term"""
        try:
            session = self._get_http_session()
            logger.info(f"[{correlation_id}]     Searching Apple with term: {search_term}")
            search_url = "https://itunes.apple.com/search"
            params = {
                "term": search_term,
                "media": "podcast",
                "entity": "podcast",
                "limit": 5
            }
            
            response = session.get(search_url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # Try the first matching podcast
                for result in data.get("results", []):
                    feed_url = result.get("feedUrl")
                    if feed_url:
                        logger.info(f"[{correlation_id}]     Found podcast: {result.get('trackName')} with feed: {feed_url}")
                        episodes = await self._try_rss_with_fallbacks(
                            result.get('trackName', search_term), 
                            feed_url, 
                            days_back,
                            correlation_id
                        )
                        if episodes:
                            return episodes
                            
        except Exception as e:
            logger.debug(f"[{correlation_id}] Search by term error: {e}")
        
        return []
    
    async def _get_apple_feed_url(self, apple_id: str, correlation_id: str) -> Optional[str]:
        """Get RSS feed URL from Apple Podcasts ID"""
        try:
            session = self._get_http_session()
            lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
            response = session.get(lookup_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    return data["results"][0].get("feedUrl")
        except Exception as e:
            logger.debug(f"[{correlation_id}] Apple feed lookup error: {e}")
        
        return None
    
    async def _try_podcast_index(self, podcast_name: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Try PodcastIndex.org API with better error handling"""
        try:
            # Search for podcast
            podcast_info = await self.podcast_index.search_podcast(podcast_name)
            if not podcast_info:
                return []
            
            # Get episodes
            feed_id = podcast_info.get("id")
            if not feed_id:
                return []
                
            episodes_data = await self.podcast_index.get_episodes(feed_id)
            
            episodes = []
            cutoff = datetime.now() - timedelta(days=days_back)
            
            for ep_data in episodes_data:
                try:
                    pub_date = datetime.fromtimestamp(ep_data.get("datePublished", 0))
                    if pub_date < cutoff:
                        continue
                    
                    episode = Episode(
                        podcast=podcast_name,
                        title=ep_data.get("title", "Unknown"),
                        published=pub_date,
                        audio_url=ep_data.get("enclosureUrl"),
                        transcript_url=ep_data.get("transcriptUrl"),
                        description=ep_data.get("description", ""),
                        link=ep_data.get("link", ""),
                        duration=seconds_to_duration(ep_data.get("duration", 0)),
                        guid=ep_data.get("guid", str(ep_data.get("id", ""))),
                        apple_podcast_id=getattr(self, '_current_apple_id', None)
                    )
                    episodes.append(episode)
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Error parsing PodcastIndex episode: {e}")
                    continue
            
            return episodes
            
        except Exception as e:
            logger.debug(f"[{correlation_id}] PodcastIndex error: {e}")
            return []
    
    async def _try_web_scraping(self, podcast_name: str, website: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Enhanced web scraping with multiple strategies"""
        if not website:
            return []
        
        session = await self._get_aiohttp_session()
        
        # Try multiple URL patterns
        url_patterns = [
            website,
            f"{website.rstrip('/')}/podcast",
            f"{website.rstrip('/')}/episodes",
            f"{website.rstrip('/')}/archive",
            f"{website.rstrip('/')}/feed",
            f"{website.rstrip('/')}/rss",
        ]
        
        for url in url_patterns:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for RSS feed links in the page
                        feed_links = soup.find_all('link', {'type': ['application/rss+xml', 'application/atom+xml']})
                        for link in feed_links:
                            feed_url = link.get('href')
                            if feed_url:
                                if not feed_url.startswith('http'):
                                    feed_url = urljoin(url, feed_url)
                                
                                episodes = await self._try_rss_with_fallbacks(
                                    podcast_name, feed_url, days_back, correlation_id
                                )
                                if episodes:
                                    return episodes
                        
                        # Try specific scraping strategies based on platform
                        if 'substack.com' in website:
                            return await self._scrape_substack(podcast_name, website, days_back, correlation_id)
                        elif 'transistor.fm' in website:
                            return await self._scrape_transistor(podcast_name, website, days_back, correlation_id)
                        # Add more platform-specific scrapers as needed
                    
            except Exception as e:
                logger.debug(f"[{correlation_id}] Web scraping error for {url}: {e}")
        
        return []
    
    async def _scrape_substack(self, podcast_name: str, website: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Enhanced Substack scraping"""
        try:
            session = await self._get_aiohttp_session()
            
            # Try multiple Substack URL patterns
            urls_to_try = [
                f"{website.rstrip('/')}/archive?sort=new&search=podcast",
                f"{website.rstrip('/')}/podcast",
                f"{website.rstrip('/')}/archive",
                f"{website.rstrip('/')}/api/v1/podcasts",
            ]
            
            episodes = []
            cutoff = datetime.now() - timedelta(days=days_back)
            
            for url in urls_to_try:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                        if response.status != 200:
                            continue
                        
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for podcast episodes
                        for article in soup.find_all(['article', 'div'], class_=['post', 'post-preview', 'portable-archive-list-item']):
                            # Check if it's a podcast post
                            audio_indicators = article.find_all(['audio', 'div'], class_=['audio-player', 'podcast-player', 'enclosure'])
                            if not audio_indicators:
                                continue
                            
                            # Extract episode data
                            title_elem = article.find(['h1', 'h2', 'h3', 'a'], class_=['post-title', 'portable-archive-list-item-title'])
                            if not title_elem:
                                continue
                            
                            title = title_elem.get_text(strip=True)
                            
                            # Get link
                            link = title_elem.get('href') if title_elem.name == 'a' else article.find('a')['href']
                            if not link.startswith('http'):
                                link = urljoin(website, link)
                            
                            # Get date
                            date_elem = article.find(['time', 'div'], class_=['post-date', 'pencraft'])
                            if date_elem:
                                pub_date = self._parse_flexible_date(date_elem.get_text(strip=True))
                                if pub_date and pub_date >= cutoff:
                                    # Get the full post to find audio URL
                                    async with session.get(link, timeout=aiohttp.ClientTimeout(total=10)) as post_response:
                                        if post_response.status == 200:
                                            post_html = await post_response.text()
                                            post_soup = BeautifulSoup(post_html, 'html.parser')
                                            
                                            # Find audio URL
                                            audio_elem = post_soup.find('audio')
                                            if audio_elem and audio_elem.get('src'):
                                                audio_url = audio_elem['src']
                                                
                                                episode = Episode(
                                                    podcast=podcast_name,
                                                    title=title,
                                                    published=pub_date,
                                                    audio_url=audio_url,
                                                    link=link,
                                                    description=self._extract_description_from_page(post_soup),
                                                    apple_podcast_id=getattr(self, '_current_apple_id', None)
                                                )
                                                episodes.append(episode)
                    
                except Exception as e:
                    logger.debug(f"[{correlation_id}] Substack scraping error for {url}: {e}")
                    continue
            
            return episodes
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Substack scraping error: {e}")
            return []
    
    async def _scrape_transistor(self, podcast_name: str, website: str, days_back: int, correlation_id: str) -> List[Episode]:
        """Scrape Transistor.fm hosted podcasts"""
        try:
            # Transistor has a predictable RSS feed pattern
            if 'transistor.fm' in website:
                # Extract show ID from URL
                show_id_match = re.search(r'transistor\.fm/s/([a-z0-9-]+)', website)
                if show_id_match:
                    show_id = show_id_match.group(1)
                    feed_url = f"https://feeds.transistor.fm/{show_id}"
                    
                    episodes = await self._try_rss_with_fallbacks(
                        podcast_name, feed_url, days_back, correlation_id
                    )
                    if episodes:
                        return episodes
            
            # Fallback to generic scraping
            session = await self._get_aiohttp_session()
            async with session.get(website, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for RSS feed link
                    feed_link = soup.find('link', {'type': 'application/rss+xml'})
                    if feed_link and feed_link.get('href'):
                        feed_url = feed_link['href']
                        if not feed_url.startswith('http'):
                            feed_url = urljoin(website, feed_url)
                        
                        return await self._try_rss_with_fallbacks(
                            podcast_name, feed_url, days_back, correlation_id
                        )
            
        except Exception as e:
            logger.debug(f"[{correlation_id}] Transistor scraping error: {e}")
        
        return []
    
    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse date from feed entry with multiple fallbacks"""
        # Try parsed date fields
        for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    return datetime(*getattr(entry, field)[:6])
                except:
                    continue
        
        # Try string dates
        for field in ['published', 'updated', 'pubDate', 'pubdate', 'date']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    return self._parse_flexible_date(getattr(entry, field))
                except:
                    continue
        
        return None
    
    def _parse_flexible_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string with multiple format attempts"""
        if not date_str:
            return None
        
        # Clean the date string
        date_str = date_str.strip()
        
        # Try dateutil parser first (handles most formats)
        try:
            parsed = date_parser.parse(date_str, fuzzy=True)
            if parsed.tzinfo:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except:
            pass
        
        # Try specific formats
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%a, %d %b %Y %H:%M:%S',
            '%d %b %Y',
            '%B %d, %Y',
            '%b %d, %Y',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except:
                continue
        
        # Last resort: try to extract date components
        try:
            # Look for year, month, day patterns
            year_match = re.search(r'20\d{2}', date_str)
            month_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', date_str, re.I)
            day_match = re.search(r'\b([1-9]|[12][0-9]|3[01])\b', date_str)
            
            if year_match and month_match and day_match:
                month_map = {
                    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                }
                year = int(year_match.group())
                month = month_map.get(month_match.group().lower()[:3], 1)
                day = int(day_match.group())
                
                return datetime(year, month, day)
        except:
            pass
        
        return None
    
    def _extract_audio_url(self, entry) -> Optional[str]:
        """Extract audio URL with multiple strategies"""
        # Check enclosures
        if hasattr(entry, 'enclosures'):
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('audio/'):
                    return enclosure.get('href') or enclosure.get('url')
                elif enclosure.get('href', '').lower().endswith(('.mp3', '.m4a', '.mp4', '.aac', '.ogg')):
                    return enclosure.get('href')
        
        # Check links
        if hasattr(entry, 'links'):
            for link in entry.links:
                if link.get('type', '').startswith('audio/'):
                    return link.get('href')
                elif link.get('rel') == 'enclosure':
                    href = link.get('href')
                    if href and any(ext in href.lower() for ext in ['.mp3', '.m4a', '.mp4', '.aac']):
                        return href
        
        # Check media content
        if hasattr(entry, 'media_content'):
            for media in entry.media_content:
                if media.get('type', '').startswith('audio/'):
                    return media.get('url')
        
        # Check iTunes extensions
        if hasattr(entry, 'itunes_enclosure'):
            return entry.itunes_enclosure
        
        return None
    
    def _extract_transcript_url(self, entry) -> Optional[str]:
        """Check if feed includes transcript URL"""
        # Check podcast namespace
        if hasattr(entry, 'podcast_transcript'):
            return entry.podcast_transcript.get('url')
        
        # Check links
        if hasattr(entry, 'links'):
            for link in entry.links:
                if 'transcript' in link.get('rel', '').lower():
                    return link.get('href')
                elif 'transcript' in link.get('title', '').lower():
                    return link.get('href')
                elif link.get('type') == 'text/plain' and 'transcript' in link.get('href', '').lower():
                    return link.get('href')
        
        return None
    
    def _extract_full_description(self, entry) -> str:
        """Extract full description from feed entry"""
        description = ""
        
        # Try different fields
        for field in ['content', 'summary_detail', 'summary', 'description', 'itunes_summary']:
            if hasattr(entry, field):
                value = getattr(entry, field)
                if isinstance(value, list) and value:
                    raw_desc = value[0].get('value', '')
                elif isinstance(value, dict):
                    raw_desc = value.get('value', '')
                elif isinstance(value, str):
                    raw_desc = value
                else:
                    continue
                
                # Clean HTML
                soup = BeautifulSoup(raw_desc, 'html.parser')
                clean_desc = soup.get_text(separator=' ', strip=True)
                
                if len(clean_desc) > len(description):
                    description = clean_desc
        
        return description or "No description available."
    
    def _extract_description_from_page(self, soup: BeautifulSoup) -> str:
        """Extract description from a web page"""
        # Try multiple selectors
        selectors = [
            'div.available-content',
            'div.post-content',
            'div.entry-content',
            'article',
            'main',
            'div[itemprop="description"]',
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator=' ', strip=True)
                if len(text) > 100:  # Minimum length for valid description
                    return text[:2000]  # Cap at 2000 chars
        
        return "No description available."
    
    def _extract_duration(self, entry) -> str:
        """Extract duration from feed entry"""
        # Try iTunes duration
        if hasattr(entry, 'itunes_duration'):
            return self._format_duration(entry.itunes_duration)
        
        # Try regular duration field
        if hasattr(entry, 'duration'):
            return self._format_duration(entry.duration)
        
        # Try media duration
        if hasattr(entry, 'media_content'):
            for media in entry.media_content:
                if media.get('duration'):
                    return self._format_duration(media['duration'])
        
        return "Unknown"
    
    def _format_duration(self, duration_str: str) -> str:
        """Format duration string"""
        from ..utils.helpers import format_duration
        return format_duration(duration_str)
    
    async def verify_against_apple_podcasts(self, podcast_config: Dict, found_episodes: List[Episode], days_back: int) -> Dict:
        """Verify found episodes against Apple Podcasts"""
        if "apple_id" not in podcast_config:
            return {"status": "skipped", "reason": "No Apple ID configured"}
        
        correlation_id = f"{self._correlation_id}-verify"
        
        try:
            # Get all episodes from Apple
            apple_episodes = await self._comprehensive_apple_search(
                podcast_config["name"], 
                podcast_config["apple_id"], 
                days_back,
                correlation_id
            )
            
            # Compare
            found_keys = {self._episode_key(ep) for ep in found_episodes}
            apple_keys = {self._episode_key(ep) for ep in apple_episodes}
            
            missing_keys = apple_keys - found_keys
            missing_episodes = [ep for ep in apple_episodes if self._episode_key(ep) in missing_keys]
            
            result = {
                "status": "success",
                "apple_episode_count": len(apple_episodes),
                "found_episode_count": len(found_episodes),
                "missing_count": len(missing_episodes),
                "missing_episodes": [
                    {
                        'title': ep.title,
                        'date': ep.published,
                        'guid': ep.guid
                    }
                    for ep in missing_episodes
                ],
                "apple_feed_url": await self._get_apple_feed_url(podcast_config["apple_id"], correlation_id)
            }
            
            return result
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Apple verification error: {e}")
            return {"status": "error", "reason": str(e)}
    
    async def fetch_missing_from_apple(self, podcast_config: Dict, existing_episodes: List[Episode], verification_result: Dict) -> List[Episode]:
        """Fetch missing episodes from Apple"""
        if verification_result["status"] != "success" or verification_result["missing_count"] == 0:
            return []
        
        correlation_id = f"{self._correlation_id}-missing"
        
        # We should already have these from comprehensive search
        apple_episodes = await self._comprehensive_apple_search(
            podcast_config["name"],
            podcast_config["apple_id"],
            30,  # Look back further
            correlation_id
        )
        
        # Filter to only missing ones
        existing_keys = {self._episode_key(ep) for ep in existing_episodes}
        new_episodes = [ep for ep in apple_episodes if self._episode_key(ep) not in existing_keys]
        
        return new_episodes
    
    async def debug_single_podcast(self, podcast_config: Dict, days_back: int = 7):
        """Debug function to check a single podcast in detail"""
        correlation_id = f"{self._correlation_id}-debug"
        logger.info(f"\n🔍 [{correlation_id}] DEBUGGING: {podcast_config['name']}")
        logger.info("="*80)
        
        # Run the full fetch with detailed logging
        logger.info(f"\n🚀 [{correlation_id}] Running bulletproof episode fetch...")
        all_episodes = await self.fetch_episodes(podcast_config, days_back)
        
        logger.info(f"\n📊 [{correlation_id}] RESULTS:")
        logger.info(f"Total episodes found: {len(all_episodes)}")
        
        if all_episodes:
            logger.info(f"\n📝 [{correlation_id}] Episode Details:")
            for i, ep in enumerate(all_episodes, 1):
                logger.info(f"\n{i}. {ep.title}")
                logger.info(f"   Published: {ep.published.strftime('%Y-%m-%d %H:%M')}")
                logger.info(f"   Duration: {ep.duration}")
                logger.info(f"   Has audio: {'Yes' if ep.audio_url else 'No'}")
                logger.info(f"   Has transcript: {'Yes' if ep.transcript_url else 'No'}")
                logger.info(f"   GUID: {ep.guid[:20]}..." if ep.guid else "   GUID: None")
        
        # Show discovered feeds
        if podcast_config['name'] in self.discovered_feeds_cache:
            logger.info(f"\n🔗 [{correlation_id}] Discovered RSS feeds:")
            for feed in self.discovered_feeds_cache[podcast_config['name']]:
                logger.info(f"   - {feed}")
        
        # Show circuit breaker states
        logger.info(f"\n⚡ [{correlation_id}] Circuit Breaker States:")
        for url, breaker in self.circuit_breakers.items():
            if podcast_config['name'] in url or any(feed in url for feed in podcast_config.get('rss_feeds', [])):
                logger.info(f"   - {url[:50]}... State: {breaker.state}, Failures: {breaker.failure_count}")
        
        logger.info("\n" + "="*80)