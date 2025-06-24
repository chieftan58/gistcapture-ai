"""Episode fetching with multiple fallback sources"""

import re
import requests
import feedparser
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from ..models import Episode
from ..database import PodcastDatabase
from ..config import PODCAST_CONFIGS
from ..utils.logging import get_logger
from ..utils.helpers import seconds_to_duration
from .podcast_index import PodcastIndexClient

logger = get_logger(__name__)


class ReliableEpisodeFetcher:
    """Fetches episodes with multiple fallback sources"""
    
    def __init__(self, db: PodcastDatabase):
        self.db = db
        self.podcast_index = PodcastIndexClient()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    async def fetch_episodes(self, podcast_config: Dict, days_back: int = 7) -> List[Episode]:
        """Bulletproof episode fetching - ensures we find ALL episodes"""
        podcast_name = podcast_config["name"]
        logger.info(f"📡 Fetching episodes for {podcast_name}")
        
        episodes = []
        
        # If force_apple is set, go straight to Apple
        if podcast_config.get("force_apple") and "apple_id" in podcast_config:
            logger.info(f"   Force using Apple Podcasts for {podcast_name}")
            episodes = await self._try_apple_podcasts(podcast_name, podcast_config["apple_id"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via Apple Podcasts")
                return episodes
        
        # Method 1: Try RSS feeds
        if "rss_feeds" in podcast_config and not podcast_config.get("force_apple"):
            episodes = await self._try_rss_feeds(podcast_name, podcast_config["rss_feeds"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via RSS")
                return episodes
        
        # Method 2: Try Apple Podcasts as fallback
        if "apple_id" in podcast_config:
            episodes = await self._try_apple_podcasts(podcast_name, podcast_config["apple_id"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via Apple Podcasts")
                return episodes
        
        # Method 3: Try PodcastIndex
        episodes = await self._try_podcast_index(podcast_name, days_back)
        if episodes:
            logger.info(f"✅ Found {len(episodes)} episodes via PodcastIndex")
            return episodes
        
        # Method 4: Try web scraping
        if "website" in podcast_config:
            episodes = await self._try_web_scraping(podcast_name, podcast_config["website"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via web scraping")
                return episodes
        
        # Method 5: Try iTunes Search API as last resort
        episodes = await self._try_itunes_search(podcast_name, days_back)
        if episodes:
            logger.info(f"✅ Found {len(episodes)} episodes via iTunes Search")
            return episodes
        
        logger.error(f"❌ Could not fetch episodes for {podcast_name} from any source")
        return []
    
    async def _try_rss_feeds(self, podcast_name: str, feed_urls: List[str], days_back: int) -> List[Episode]:
        """Try multiple RSS feed URLs with better error handling and timeouts"""
        cutoff = datetime.now() - timedelta(days=days_back)
        
        for url in feed_urls:
            try:
                logger.info(f"  Trying RSS: {url}")
                
                # Use requests with shorter timeout for better control
                try:
                    response = self.session.get(url, timeout=10, allow_redirects=True)
                    if response.status_code != 200:
                        logger.warning(f"  HTTP {response.status_code} for {url}")
                        continue
                    feed_content = response.content
                except requests.Timeout:
                    logger.warning(f"  Timeout for {url}")
                    continue
                except Exception as e:
                    logger.warning(f"  Request error: {e}")
                    continue
                
                # Parse the feed content
                feed = feedparser.parse(feed_content)
                
                # Check if feed is valid
                if feed.bozo and feed.bozo_exception:
                    logger.warning(f"  Feed parse warning: {feed.bozo_exception}")
                
                if not feed.entries:
                    logger.warning(f"  No entries found in feed")
                    continue
                
                episodes = []
                for entry in feed.entries[:20]:
                    try:
                        # Parse date
                        pub_date = self._parse_date(entry)
                        if not pub_date:
                            logger.debug(f"  Skipping entry without date: {entry.get('title', 'Unknown')}")
                            continue
                        
                        if pub_date < cutoff:
                            continue
                        
                        # Get audio URL
                        audio_url = self._extract_audio_url(entry)
                        if not audio_url:
                            logger.debug(f"  Skipping entry without audio: {entry.get('title', 'Unknown')}")
                            continue
                        
                        # Check for transcript URL in feed
                        transcript_url = self._extract_transcript_url(entry)
                        
                        # Extract full description
                        description = self._extract_full_description(entry)
                        
                        # Extract and format duration
                        duration = self._extract_duration(entry)
                        
                        episode = Episode(
                            podcast=podcast_name,
                            title=entry.get('title', 'Unknown'),
                            published=pub_date,
                            audio_url=audio_url,
                            transcript_url=transcript_url,
                            description=description,
                            link=entry.get('link', ''),
                            duration=duration,
                            guid=entry.get('guid', entry.get('id', ''))
                        )
                        
                        episodes.append(episode)
                    except Exception as e:
                        logger.warning(f"  Error processing entry: {e}")
                        continue
                
                if episodes:
                    return episodes
                    
            except Exception as e:
                logger.error(f"  RSS error for {url}: {e}")
                continue
        
        return []
    
    async def _try_apple_podcasts(self, podcast_name: str, apple_id: str, days_back: int) -> List[Episode]:
        """Use Apple Podcasts lookup to get RSS feed"""
        try:
            lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
            response = self.session.get(lookup_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    feed_url = data["results"][0].get("feedUrl")
                    if feed_url:
                        return await self._try_rss_feeds(podcast_name, [feed_url], days_back)
        except Exception as e:
            logger.error(f"Apple Podcasts error: {e}")
        
        return []
    
    async def _try_podcast_index(self, podcast_name: str, days_back: int) -> List[Episode]:
        """Try PodcastIndex.org API"""
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
            pub_date = datetime.fromtimestamp(ep_data.get("datePublished", 0))
            if pub_date < cutoff:
                continue
            
            episode = Episode(
                podcast=podcast_name,
                title=ep_data.get("title", "Unknown"),
                published=pub_date,
                audio_url=ep_data.get("enclosureUrl"),
                transcript_url=ep_data.get("transcriptUrl"),  # Some episodes have this
                description=ep_data.get("description", ""),
                link=ep_data.get("link", ""),
                duration=seconds_to_duration(ep_data.get("duration", 0)),
                guid=ep_data.get("guid", str(ep_data.get("id", "")))
            )
            
            episodes.append(episode)
        
        return episodes
    
    async def _try_itunes_search(self, podcast_name: str, days_back: int) -> List[Episode]:
        """Use iTunes Search API to find podcast and get episodes"""
        try:
            # Search for podcast
            search_url = "https://itunes.apple.com/search"
            params = {
                "term": podcast_name,
                "media": "podcast",
                "entity": "podcast",
                "limit": 5
            }
            
            response = self.session.get(search_url, params=params, timeout=10)
            if response.status_code != 200:
                return []
            
            data = response.json()
            if not data.get("results"):
                return []
            
            # Try each result until we find episodes
            for result in data["results"]:
                feed_url = result.get("feedUrl")
                if feed_url:
                    episodes = await self._try_rss_feeds(podcast_name, [feed_url], days_back)
                    if episodes:
                        return episodes
                    
        except Exception as e:
            logger.error(f"iTunes Search error: {e}")
        
        return []
    
    async def _try_web_scraping(self, podcast_name: str, website: str, days_back: int) -> List[Episode]:
        """Scrape podcast website for episodes"""
        # Implement specific scrapers for different podcast websites
        scrapers = {
            "markethuddle.substack.com": self._scrape_substack,
            # Add more scrapers as needed
        }
        
        for domain, scraper in scrapers.items():
            if domain in website:
                return await scraper(podcast_name, website, days_back)
        
        return []
    
    async def _scrape_substack(self, podcast_name: str, website: str, days_back: int) -> List[Episode]:
        """Scrape Substack podcast pages"""
        try:
            # Get archive page
            archive_url = f"{website.rstrip('/')}/archive"
            response = self.session.get(archive_url, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            episodes = []
            cutoff = datetime.now() - timedelta(days=days_back)
            
            # Find podcast posts
            for post in soup.find_all('div', class_='post-preview'):
                # Check if it's a podcast
                if not post.find('div', class_='podcast-preview'):
                    continue
                
                title_elem = post.find('a', class_='post-preview-title')
                if not title_elem:
                    continue
                
                # Get post details
                post_url = title_elem['href']
                if not post_url.startswith('http'):
                    post_url = urljoin(website, post_url)
                
                # Get full post to find audio
                post_resp = self.session.get(post_url, timeout=10)
                post_soup = BeautifulSoup(post_resp.content, 'html.parser')
                
                # Find audio player
                audio_elem = post_soup.find('audio')
                if not audio_elem or not audio_elem.get('src'):
                    continue
                
                audio_url = audio_elem['src']
                
                # Parse date
                date_elem = post.find('time')
                if date_elem and date_elem.get('datetime'):
                    pub_date = datetime.fromisoformat(date_elem['datetime'].replace('Z', '+00:00'))
                    if pub_date.tzinfo:
                        pub_date = pub_date.replace(tzinfo=None)
                    
                    if pub_date < cutoff:
                        continue
                    
                    # Get full description from the post page
                    desc_elem = post_soup.find('div', class_='available-content')
                    if desc_elem:
                        description = desc_elem.get_text(separator=' ', strip=True)
                    else:
                        description = post.find('div', class_='post-preview-description').text.strip() if post.find('div', class_='post-preview-description') else ""
                    
                    episode = Episode(
                        podcast=podcast_name,
                        title=title_elem.text.strip(),
                        published=pub_date,
                        audio_url=audio_url,
                        link=post_url,
                        description=description
                    )
                    
                    episodes.append(episode)
            
            return episodes
            
        except Exception as e:
            logger.error(f"Substack scraping error: {e}")
            return []
    
    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse date from feed entry"""
        # Try parsed date fields
        for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    return datetime(*getattr(entry, field)[:6])
                except:
                    continue
        
        # Try string dates
        for field in ['published', 'updated', 'pubDate']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    date = date_parser.parse(getattr(entry, field))
                    if date.tzinfo:
                        date = date.replace(tzinfo=None)
                    return date
                except:
                    continue
        
        return None
    
    def _extract_audio_url(self, entry) -> Optional[str]:
        """Extract audio URL from feed entry"""
        # Check enclosures
        if hasattr(entry, 'enclosures'):
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('audio/'):
                    return enclosure.get('href') or enclosure.get('url')
                elif enclosure.get('href', '').lower().endswith(('.mp3', '.m4a', '.mp4')):
                    return enclosure.get('href')
        
        # Check links
        if hasattr(entry, 'links'):
            for link in entry.links:
                if link.get('type', '').startswith('audio/'):
                    return link.get('href')
                elif link.get('rel') == 'enclosure':
                    return link.get('href')
        
        return None
    
    def _extract_transcript_url(self, entry) -> Optional[str]:
        """Check if feed includes transcript URL"""
        # Some podcasts include transcript links in their feeds
        if hasattr(entry, 'links'):
            for link in entry.links:
                if 'transcript' in link.get('rel', '').lower():
                    return link.get('href')
                elif 'transcript' in link.get('title', '').lower():
                    return link.get('href')
        
        return None
    
    def _extract_full_description(self, entry) -> str:
        """Extract full description from feed entry without truncation"""
        description = ""
        
        # Try different fields that might contain the description
        for field in ['content', 'summary', 'description']:
            if hasattr(entry, field):
                value = getattr(entry, field)
                if isinstance(value, list) and value:
                    # Some feeds have content as a list of dicts
                    raw_desc = value[0].get('value', '')
                elif isinstance(value, str):
                    raw_desc = value
                else:
                    continue
                
                # Clean HTML from description
                soup = BeautifulSoup(raw_desc, 'html.parser')
                clean_desc = soup.get_text(separator=' ', strip=True)
                
                # Take the longest description we find
                if len(clean_desc) > len(description):
                    description = clean_desc
        
        # If no description found, return a default message
        if not description:
            description = "No description available for this episode."
        
        return description
    
    def _extract_duration(self, entry) -> str:
        """Extract duration from feed entry"""
        duration_str = None
        
        # Try different duration fields
        if hasattr(entry, 'itunes_duration'):
            duration_str = entry.itunes_duration
        elif hasattr(entry, 'duration'):
            duration_str = entry.duration
            
        if duration_str:
            return self._format_duration(duration_str)
        
        return "Unknown"
    
    def _format_duration(self, duration_str: str) -> str:
        """Format duration string into human-readable format"""
        from ..utils.helpers import format_duration
        return format_duration(duration_str)
    
    async def verify_against_apple_podcasts(self, podcast_config: Dict, found_episodes: List[Episode], days_back: int) -> Dict:
        """Verify found episodes against Apple Podcasts to check for missing episodes"""
        if "apple_id" not in podcast_config:
            return {"status": "skipped", "reason": "No Apple ID configured"}
        
        try:
            apple_id = podcast_config["apple_id"]
            podcast_name = podcast_config["name"]
            
            # First get the RSS feed URL from Apple
            lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
            response = self.session.get(lookup_url, timeout=10)
            
            if response.status_code != 200:
                return {"status": "error", "reason": f"Apple API returned {response.status_code}"}
            
            data = response.json()
            if not data.get("results"):
                return {"status": "error", "reason": "No podcast found on Apple"}
            
            apple_feed_url = data["results"][0].get("feedUrl")
            if not apple_feed_url:
                return {"status": "error", "reason": "No feed URL in Apple data"}
            
            # Parse Apple's feed
            apple_feed = feedparser.parse(apple_feed_url, agent='Mozilla/5.0')
            
            if not apple_feed.entries:
                return {"status": "error", "reason": "No episodes in Apple feed"}
            
            # Get episodes from Apple feed within date range
            cutoff = datetime.now() - timedelta(days=days_back)
            apple_episodes = []
            
            for entry in apple_feed.entries[:20]:  # Check recent 20 episodes
                pub_date = self._parse_date(entry)
                if pub_date and pub_date >= cutoff:
                    title = entry.get('title', 'Unknown')
                    apple_episodes.append({
                        'title': title,
                        'date': pub_date,
                        'guid': entry.get('guid', entry.get('id', '')),
                        'has_audio': bool(self._extract_audio_url(entry))
                    })
            
            # Compare with found episodes
            found_titles = {ep.title.lower().strip() for ep in found_episodes}
            found_guids = {ep.guid for ep in found_episodes}
            
            missing_episodes = []
            for apple_ep in apple_episodes:
                # Check by title (normalized) and GUID
                title_normalized = apple_ep['title'].lower().strip()
                if title_normalized not in found_titles and apple_ep['guid'] not in found_guids:
                    missing_episodes.append(apple_ep)
            
            result = {
                "status": "success",
                "apple_episode_count": len(apple_episodes),
                "found_episode_count": len([ep for ep in found_episodes if ep.published >= cutoff]),
                "missing_count": len(missing_episodes),
                "missing_episodes": missing_episodes,
                "apple_feed_url": apple_feed_url
            }
            
            if missing_episodes:
                logger.warning(f"⚠️  {podcast_name}: Found {len(missing_episodes)} episodes on Apple Podcasts that we missed:")
                for ep in missing_episodes[:3]:  # Show first 3
                    logger.warning(f"   - {ep['title']} ({ep['date'].strftime('%Y-%m-%d')})")
                if len(missing_episodes) > 3:
                    logger.warning(f"   ... and {len(missing_episodes) - 3} more")
            
            return result
            
        except Exception as e:
            logger.error(f"Apple verification error for {podcast_config['name']}: {e}")
            return {"status": "error", "reason": str(e)}
    
    async def fetch_missing_from_apple(self, podcast_config: Dict, existing_episodes: List[Episode], verification_result: Dict) -> List[Episode]:
        """Fetch missing episodes identified by Apple verification"""
        if verification_result["status"] != "success" or verification_result["missing_count"] == 0:
            return []
        
        podcast_name = podcast_config["name"]
        apple_feed_url = verification_result["apple_feed_url"]
        
        logger.info(f"🔄 Attempting to fetch {verification_result['missing_count']} missing episodes from Apple feed")
        
        # Fetch from Apple's feed URL
        additional_episodes = await self._try_rss_feeds(podcast_name, [apple_feed_url], 30)  # Look back further
        
        if not additional_episodes:
            return []
        
        # Filter to only the missing ones
        existing_titles = {ep.title.lower().strip() for ep in existing_episodes}
        existing_guids = {ep.guid for ep in existing_episodes}
        
        new_episodes = []
        for ep in additional_episodes:
            if ep.title.lower().strip() not in existing_titles and ep.guid not in existing_guids:
                new_episodes.append(ep)
        
        if new_episodes:
            logger.info(f"✅ Successfully fetched {len(new_episodes)} missing episodes from Apple feed")
        
        return new_episodes
    
    async def debug_single_podcast(self, podcast_config: Dict, days_back: int = 7):
        """Debug function to check a single podcast in detail"""
        logger.info(f"\n🔍 Checking {podcast_config['name']}")
        logger.info("="*60)
        
        # Try each RSS feed
        if "rss_feeds" in podcast_config:
            logger.info("\n📡 Testing RSS feeds:")
            for feed_url in podcast_config["rss_feeds"]:
                logger.info(f"\n  Feed: {feed_url}")
                try:
                    episodes = await self._try_rss_feeds(
                        podcast_config["name"], [feed_url], days_back
                    )
                    if episodes:
                        logger.info(f"  ✅ Success! Found {len(episodes)} episodes")
                        for ep in episodes[:2]:
                            logger.info(f"     - {ep.title} ({ep.published.strftime('%Y-%m-%d')})")
                    else:
                        logger.warning("  ❌ No episodes found")
                except Exception as e:
                    logger.error(f"  ❌ Error: {e}")
        
        # Check Apple Podcasts
        if "apple_id" in podcast_config:
            logger.info(f"\n🍎 Apple Podcasts ID: {podcast_config['apple_id']}")
            episodes = await self._try_apple_podcasts(
                podcast_config["name"], podcast_config["apple_id"], days_back
            )
            if episodes:
                logger.info(f"✅ Apple feed works! Found {len(episodes)} episodes")
            else:
                logger.warning("❌ Could not fetch from Apple")
        
        # Run full fetch
        logger.info("\n🚀 Running full episode fetch...")
        all_episodes = await self.fetch_episodes(podcast_config, days_back)
        
        if all_episodes:
            logger.info(f"\n✅ Total episodes found: {len(all_episodes)}")
            for ep in all_episodes:
                logger.info(f"  - {ep.title}")
                logger.info(f"    Published: {ep.published.strftime('%Y-%m-%d %H:%M')}")
                logger.info(f"    Duration: {ep.duration}")
                logger.info(f"    Has transcript: {'Yes' if ep.transcript_url else 'No'}")
                if len(ep.description) > 150:
                    logger.info(f"    Description: {ep.description[:150]}...")
                else:
                    logger.info(f"    Description: {ep.description}")
                logger.info("")
        else:
            logger.error("❌ No episodes found!")
        
        # Verify against Apple
        if "apple_id" in podcast_config:
            logger.info("\n📱 Verifying against Apple Podcasts...")
            verification = await self.verify_against_apple_podcasts(
                podcast_config, all_episodes, days_back
            )
            
            if verification["status"] == "success":
                logger.info(f"Apple episodes: {verification['apple_episode_count']}")
                logger.info(f"Found episodes: {verification['found_episode_count']}")
                logger.info(f"Missing episodes: {verification['missing_count']}")
                
                if verification["missing_count"] > 0:
                    logger.warning("\nMissing episodes:")
                    for ep in verification["missing_episodes"]:
                        logger.warning(f"  - {ep['title']} ({ep['date'].strftime('%Y-%m-%d')})")
            else:
                logger.error(f"Verification failed: {verification['reason']}")