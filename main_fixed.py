# main.py - Renaissance Weekly Podcast Intelligence System (Production Version)
import os
import json
import hashlib
import asyncio
import aiohttp
import aiofiles
import tempfile
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin
import openai
from openai import OpenAI
from pydub import AudioSegment
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
import time
import re
import threading
from typing import List, Dict, Optional, Tuple
import requests
from bs4 import BeautifulSoup
import html
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from dataclasses import dataclass
from enum import Enum
import sqlite3
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
load_dotenv()

# Initialize clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
sendgrid_client = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))

# Configuration
TRANSCRIPT_DIR = Path("transcripts")
AUDIO_DIR = Path("audio")
SUMMARY_DIR = Path("summaries")
CACHE_DIR = Path("cache")
TEMP_DIR = Path("temp")
DB_PATH = Path("podcast_data.db")

# Create directories
for dir in [TRANSCRIPT_DIR, AUDIO_DIR, SUMMARY_DIR, CACHE_DIR, TEMP_DIR]:
    dir.mkdir(exist_ok=True)

# Email configuration
EMAIL_FROM = "insights@gistcapture.ai"
EMAIL_TO = os.getenv("EMAIL_TO", "caddington05@gmail.com")

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('renaissance_weekly.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Testing mode
TESTING_MODE = os.getenv("TESTING_MODE", "true").lower() == "true"
MAX_TRANSCRIPTION_MINUTES = 20 if TESTING_MODE else float('inf')


class TranscriptSource(Enum):
    OFFICIAL = "official"          # From podcast website
    API = "api"                    # From transcript API
    COMMUNITY = "community"        # From community sources
    GENERATED = "generated"        # We transcribed it
    CACHED = "cached"             # From our cache


@dataclass
class Episode:
    podcast: str
    title: str
    published: datetime
    audio_url: Optional[str] = None
    transcript_url: Optional[str] = None
    transcript_source: Optional[TranscriptSource] = None
    description: str = ""
    link: str = ""
    duration: str = "Unknown"
    guid: str = ""  # Unique identifier
    
    def __post_init__(self):
        if not self.guid:
            # Create unique ID from podcast + title + date
            self.guid = hashlib.md5(
                f"{self.podcast}:{self.title}:{self.published}".encode()
            ).hexdigest()


class PodcastDatabase:
    """SQLite database for tracking podcasts and episodes"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Podcast feeds table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS podcast_feeds (
                podcast_name TEXT PRIMARY KEY,
                working_feeds TEXT,  -- JSON array of working feed URLs
                transcript_sources TEXT,  -- JSON object of transcript sources
                last_checked TIMESTAMP,
                last_success TIMESTAMP
            )
        """)
        
        # Episodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                guid TEXT PRIMARY KEY,
                podcast_name TEXT,
                title TEXT,
                published TIMESTAMP,
                audio_url TEXT,
                transcript_url TEXT,
                transcript_source TEXT,
                transcript_text TEXT,
                summary TEXT,
                processed BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (podcast_name) REFERENCES podcast_feeds(podcast_name)
            )
        """)
        
        # Feed health monitoring
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feed_health (
                url TEXT PRIMARY KEY,
                podcast_name TEXT,
                status TEXT,  -- 'working', 'failing', 'dead'
                last_success TIMESTAMP,
                last_failure TIMESTAMP,
                failure_count INTEGER DEFAULT 0,
                error_message TEXT
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_cached_transcript(self, episode: Episode) -> Optional[str]:
        """Get cached transcript if available"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT transcript_text FROM episodes WHERE guid = ?",
            (episode.guid,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result and result[0] else None
    
    def save_episode(self, episode: Episode, transcript: Optional[str] = None):
        """Save episode to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO episodes 
            (guid, podcast_name, title, published, audio_url, transcript_url, 
             transcript_source, transcript_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode.guid,
            episode.podcast,
            episode.title,
            episode.published,
            episode.audio_url,
            episode.transcript_url,
            episode.transcript_source.value if episode.transcript_source else None,
            transcript
        ))
        
        conn.commit()
        conn.close()


class TranscriptFinder:
    """Find existing transcripts before resorting to audio transcription"""
    
    def __init__(self, db: PodcastDatabase):
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Renaissance Weekly/2.0 (Transcript Finder)'
        })
    
    async def find_transcript(self, episode: Episode) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """Try to find an existing transcript"""
        logger.info(f"🔍 Searching for transcript: {episode.title}")
        
        # 1. Check cache first
        cached = self.db.get_cached_transcript(episode)
        if cached:
            logger.info("✅ Found cached transcript")
            return cached, TranscriptSource.CACHED
        
        # 2. Try official sources
        transcript = await self._try_official_transcript(episode)
        if transcript:
            return transcript, TranscriptSource.OFFICIAL
        
        # 3. Try transcript APIs
        transcript = await self._try_transcript_apis(episode)
        if transcript:
            return transcript, TranscriptSource.API
        
        # 4. Try community sources
        transcript = await self._try_community_sources(episode)
        if transcript:
            return transcript, TranscriptSource.COMMUNITY
        
        logger.info("❌ No existing transcript found")
        return None, None
    
    async def _try_official_transcript(self, episode: Episode) -> Optional[str]:
        """Check official podcast websites for transcripts"""
        
        # Podcast-specific transcript patterns
        transcript_patterns = {
            "Tim Ferriss": self._get_tim_ferriss_transcript,
            "Huberman Lab": self._get_huberman_transcript,
            "Lex Fridman": self._get_lex_fridman_transcript,
            "The Drive": self._get_peter_attia_transcript,
            "Modern Wisdom": self._get_modern_wisdom_transcript,
            "Knowledge Project": self._get_knowledge_project_transcript,
        }
        
        if episode.podcast in transcript_patterns:
            try:
                return await transcript_patterns[episode.podcast](episode)
            except Exception as e:
                logger.error(f"Error getting official transcript: {e}")
        
        # Generic transcript finder for episode page
        if episode.link:
            return await self._find_transcript_on_page(episode.link)
        
        return None
    
    async def _get_tim_ferriss_transcript(self, episode: Episode) -> Optional[str]:
        """Tim Ferriss provides full transcripts on his website"""
        try:
            # Tim's transcripts are usually at the episode URL
            if not episode.link:
                return None
            
            response = self.session.get(episode.link, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for transcript section
            transcript_div = soup.find('div', class_='podcast-transcript')
            if not transcript_div:
                # Try another common pattern
                transcript_div = soup.find('div', id='transcript')
            
            if transcript_div:
                # Clean up the transcript
                transcript = transcript_div.get_text(separator='\n', strip=True)
                if len(transcript) > 1000:  # Sanity check
                    logger.info("✅ Found Tim Ferriss transcript")
                    return transcript
        except Exception as e:
            logger.error(f"Error fetching Tim Ferriss transcript: {e}")
        
        return None
    
    async def _get_huberman_transcript(self, episode: Episode) -> Optional[str]:
        """Huberman Lab provides transcripts"""
        try:
            if episode.link and 'hubermanlab.com' in episode.link:
                response = self.session.get(episode.link, timeout=15)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Huberman uses specific markup
                transcript_section = soup.find('section', {'aria-label': 'Transcript'})
                if not transcript_section:
                    transcript_section = soup.find('div', class_='transcript-content')
                
                if transcript_section:
                    transcript = transcript_section.get_text(separator='\n', strip=True)
                    if len(transcript) > 1000:
                        logger.info("✅ Found Huberman Lab transcript")
                        return transcript
        except Exception as e:
            logger.error(f"Error fetching Huberman transcript: {e}")
        
        return None
    
    async def _get_lex_fridman_transcript(self, episode: Episode) -> Optional[str]:
        """Lex Fridman provides transcripts on his website"""
        try:
            # Lex's site structure
            if episode.link and 'lexfridman.com' in episode.link:
                response = self.session.get(episode.link, timeout=15)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Look for transcript
                transcript_div = soup.find('div', class_='transcript')
                if transcript_div:
                    transcript = transcript_div.get_text(separator='\n', strip=True)
                    if len(transcript) > 1000:
                        logger.info("✅ Found Lex Fridman transcript")
                        return transcript
        except Exception as e:
            logger.error(f"Error fetching Lex Fridman transcript: {e}")
        
        return None
    
    async def _get_peter_attia_transcript(self, episode: Episode) -> Optional[str]:
        """Peter Attia's The Drive provides show notes with key quotes"""
        # Note: Full transcripts might be member-only
        # We can get show notes which are often quite detailed
        try:
            if episode.link and 'peterattiamd.com' in episode.link:
                response = self.session.get(episode.link, timeout=15)
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Get detailed show notes
                show_notes = soup.find('div', class_='show-notes-content')
                if show_notes:
                    notes = show_notes.get_text(separator='\n', strip=True)
                    if len(notes) > 2000:  # Show notes are substantial
                        logger.info("✅ Found Peter Attia show notes")
                        return f"[Show Notes]\n{notes}"
        except Exception as e:
            logger.error(f"Error fetching Peter Attia content: {e}")
        
        return None
    
    async def _get_modern_wisdom_transcript(self, episode: Episode) -> Optional[str]:
        """Modern Wisdom sometimes provides transcripts"""
        # Similar pattern - check website
        return await self._find_transcript_on_page(episode.link)
    
    async def _get_knowledge_project_transcript(self, episode: Episode) -> Optional[str]:
        """Knowledge Project provides detailed show notes"""
        if episode.link and 'fs.blog' in episode.link:
            return await self._find_transcript_on_page(episode.link)
        return None
    
    async def _find_transcript_on_page(self, url: str) -> Optional[str]:
        """Generic transcript finder for any podcast page"""
        if not url:
            return None
        
        try:
            response = self.session.get(url, timeout=15)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Common transcript indicators
            transcript_indicators = [
                ('div', {'class': re.compile(r'transcript|Transcript')}),
                ('div', {'id': re.compile(r'transcript|Transcript')}),
                ('section', {'class': re.compile(r'transcript|Transcript')}),
                ('article', {'class': re.compile(r'transcript|Transcript')}),
                ('div', {'data-transcript': True}),
            ]
            
            for tag, attrs in transcript_indicators:
                element = soup.find(tag, attrs)
                if element:
                    text = element.get_text(separator='\n', strip=True)
                    if len(text) > 1000:  # Minimum length check
                        logger.info(f"✅ Found transcript on page: {url}")
                        return text
            
            # Check for "Read Transcript" or similar links
            transcript_link = soup.find('a', text=re.compile(r'transcript|Transcript', re.I))
            if transcript_link and transcript_link.get('href'):
                transcript_url = urljoin(url, transcript_link['href'])
                return await self._fetch_transcript_from_url(transcript_url)
        
        except Exception as e:
            logger.error(f"Error finding transcript on page: {e}")
        
        return None
    
    async def _fetch_transcript_from_url(self, url: str) -> Optional[str]:
        """Fetch transcript from a direct URL"""
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                # Could be PDF, TXT, or HTML
                content_type = response.headers.get('content-type', '').lower()
                
                if 'text' in content_type or 'html' in content_type:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    text = soup.get_text(separator='\n', strip=True)
                    if len(text) > 1000:
                        return text
                    
        except Exception as e:
            logger.error(f"Error fetching transcript from URL: {e}")
        
        return None
    
    async def _try_transcript_apis(self, episode: Episode) -> Optional[str]:
        """Try transcript API services"""
        
        # 1. Taddy API (if you have access)
        if os.getenv("TADDY_API_KEY"):
            transcript = await self._try_taddy_api(episode)
            if transcript:
                return transcript
        
        # 2. Rev.ai (many podcasts use Rev)
        # This would require either API access or scraping
        
        # 3. Descript (some podcasts use this)
        # Would need to implement based on their API
        
        return None
    
    async def _try_taddy_api(self, episode: Episode) -> Optional[str]:
        """Taddy provides transcripts for many podcasts"""
        # Implementation would depend on Taddy API access
        # This is a placeholder
        return None
    
    async def _try_community_sources(self, episode: Episode) -> Optional[str]:
        """Check community transcript sources"""
        
        # 1. GitHub repositories with transcripts
        github_sources = [
            "https://github.com/leerob/lex-fridman-transcripts",
            # Add more known transcript repos
        ]
        
        # 2. Fan sites with transcripts
        # Many popular podcasts have fan-maintained transcript sites
        
        # 3. Reddit posts with transcripts
        # Some communities post transcripts
        
        return None


class PodcastIndexClient:
    """Client for PodcastIndex.org - free and comprehensive"""
    
    def __init__(self):
        self.api_key = os.getenv("PODCASTINDEX_API_KEY")
        self.api_secret = os.getenv("PODCASTINDEX_API_SECRET")
        self.base_url = "https://api.podcastindex.org/api/1.0"
    
    def _get_headers(self):
        """Generate auth headers for PodcastIndex"""
        if not self.api_key or not self.api_secret:
            return None
            
        import hashlib
        import time
        
        api_header_time = str(int(time.time()))
        hash_input = self.api_key + self.api_secret + api_header_time
        sha1_hash = hashlib.sha1(hash_input.encode()).hexdigest()
        
        return {
            "X-Auth-Key": self.api_key,
            "X-Auth-Date": api_header_time,
            "Authorization": sha1_hash,
            "User-Agent": "Renaissance Weekly"
        }
    
    async def search_podcast(self, podcast_name: str) -> Optional[Dict]:
        """Search for podcast by name"""
        headers = self._get_headers()
        if not headers:
            return None
            
        try:
            url = f"{self.base_url}/search/byterm"
            params = {"q": podcast_name, "val": "podcast"}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("feeds"):
                            return data["feeds"][0]  # Return first match
        except Exception as e:
            logger.error(f"PodcastIndex search error: {e}")
        
        return None
    
    async def get_episodes(self, feed_id: int, max_results: int = 20) -> List[Dict]:
        """Get recent episodes for a podcast"""
        headers = self._get_headers()
        if not headers:
            return []
            
        try:
            url = f"{self.base_url}/episodes/byfeedid"
            params = {"id": feed_id, "max": max_results}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("items", [])
        except Exception as e:
            logger.error(f"PodcastIndex episodes error: {e}")
        
        return []


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
        """Fetch episodes using multiple methods until success"""
        podcast_name = podcast_config["name"]
        logger.info(f"📡 Fetching episodes for {podcast_name}")
        
        episodes = []
        
        # Method 1: Try RSS feeds
        if "rss_feeds" in podcast_config:
            episodes = await self._try_rss_feeds(podcast_name, podcast_config["rss_feeds"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via RSS")
                return episodes
        
        # Method 2: Try PodcastIndex
        episodes = await self._try_podcast_index(podcast_name, days_back)
        if episodes:
            logger.info(f"✅ Found {len(episodes)} episodes via PodcastIndex")
            return episodes
        
        # Method 3: Try Apple Podcasts
        if "apple_id" in podcast_config:
            episodes = await self._try_apple_podcasts(podcast_name, podcast_config["apple_id"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via Apple Podcasts")
                return episodes
        
        # Method 4: Try web scraping
        if "website" in podcast_config:
            episodes = await self._try_web_scraping(podcast_name, podcast_config["website"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via web scraping")
                return episodes
        
        # Method 5: Try direct API if available
        if "api_endpoint" in podcast_config:
            episodes = await self._try_direct_api(podcast_name, podcast_config["api_endpoint"], days_back)
            if episodes:
                logger.info(f"✅ Found {len(episodes)} episodes via API")
                return episodes
        
        logger.error(f"❌ Could not fetch episodes for {podcast_name} from any source")
        return []
    
    async def _try_rss_feeds(self, podcast_name: str, feed_urls: List[str], days_back: int) -> List[Episode]:
        """Try multiple RSS feed URLs"""
        cutoff = datetime.now() - timedelta(days=days_back)
        
        for url in feed_urls:
            try:
                logger.info(f"  Trying RSS: {url}")
                feed = feedparser.parse(url, agent='Renaissance Weekly/2.0')
                
                if not feed.entries:
                    continue
                
                episodes = []
                for entry in feed.entries[:20]:
                    # Parse date
                    pub_date = self._parse_date(entry)
                    if not pub_date or pub_date < cutoff:
                        continue
                    
                    # Get audio URL
                    audio_url = self._extract_audio_url(entry)
                    if not audio_url:
                        continue
                    
                    # Check for transcript URL in feed
                    transcript_url = self._extract_transcript_url(entry)
                    
                    episode = Episode(
                        podcast=podcast_name,
                        title=entry.get('title', 'Unknown'),
                        published=pub_date,
                        audio_url=audio_url,
                        transcript_url=transcript_url,
                        description=self._extract_description(entry),
                        link=entry.get('link', ''),
                        duration=self._extract_duration(entry),
                        guid=entry.get('guid', entry.get('id', ''))
                    )
                    
                    episodes.append(episode)
                
                if episodes:
                    return episodes
                    
            except Exception as e:
                logger.error(f"  RSS error: {e}")
                continue
        
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
                duration=self._seconds_to_duration(ep_data.get("duration", 0)),
                guid=ep_data.get("guid", str(ep_data.get("id", "")))
            )
            
            episodes.append(episode)
        
        return episodes
    
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
    
    async def _try_web_scraping(self, podcast_name: str, website: str, days_back: int) -> List[Episode]:
        """Scrape podcast website for episodes"""
        # Implement specific scrapers for different podcast websites
        scrapers = {
            "markethuddle.substack.com": self._scrape_substack,
            "tim.blog": self._scrape_tim_ferriss,
            "hubermanlab.com": self._scrape_huberman,
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
                    
                    episode = Episode(
                        podcast=podcast_name,
                        title=title_elem.text.strip(),
                        published=pub_date,
                        audio_url=audio_url,
                        link=post_url,
                        description=post.find('div', class_='post-preview-description').text.strip() if post.find('div', class_='post-preview-description') else ""
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
                    from dateutil import parser
                    date = parser.parse(getattr(entry, field))
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
    
    def _extract_description(self, entry) -> str:
        """Extract description from feed entry"""
        for field in ['description', 'summary', 'content']:
            if hasattr(entry, field):
                value = getattr(entry, field)
                if isinstance(value, list) and value:
                    return value[0].get('value', '')
                elif isinstance(value, str):
                    return value
        return ""
    
    def _extract_duration(self, entry) -> str:
        """Extract duration from feed entry"""
        if hasattr(entry, 'itunes_duration'):
            return entry.itunes_duration
        elif hasattr(entry, 'duration'):
            return entry.duration
        return "Unknown"
    
    def _seconds_to_duration(self, seconds: int) -> str:
        """Convert seconds to duration string"""
        if seconds <= 0:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


class RenaissanceWeekly:
    """Main application class"""
    
    def __init__(self):
        self.validate_env_vars()
        self.db = PodcastDatabase(DB_PATH)
        self.transcript_finder = TranscriptFinder(self.db)
        self.episode_fetcher = ReliableEpisodeFetcher(self.db)
        self.selected_episodes = []
    
    def validate_env_vars(self):
        """Validate required environment variables"""
        required = ["OPENAI_API_KEY", "SENDGRID_API_KEY"]
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        if not EMAIL_TO or EMAIL_TO == "caddington05@gmail.com":
            logger.info("📧 Using default email: caddington05@gmail.com")
            logger.info("💡 To change, set EMAIL_TO in your .env file")
    
    async def process_episode(self, episode: Episode) -> Optional[str]:
        """Process a single episode - find transcript or transcribe, then summarize"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🎧 Processing: {episode.title}")
        logger.info(f"📅 Published: {episode.published.strftime('%Y-%m-%d')}")
        logger.info(f"🎙️  Podcast: {episode.podcast}")
        logger.info(f"{'='*60}")
        
        # Step 1: Try to find existing transcript
        transcript_text, transcript_source = await self.transcript_finder.find_transcript(episode)
        
        # Step 2: If no transcript found, transcribe from audio
        if not transcript_text:
            logger.info("📥 No transcript found - downloading audio for transcription...")
            transcript_file = await self.transcribe_from_audio(episode)
            
            if transcript_file and transcript_file.exists():
                with open(transcript_file, 'r', encoding='utf-8') as f:
                    transcript_text = f.read()
                transcript_source = TranscriptSource.GENERATED
            else:
                logger.error("❌ Failed to transcribe audio")
                return None
        
        # Save transcript to database
        self.db.save_episode(episode, transcript_text)
        
        # Step 3: Generate summary
        logger.info("📝 Generating executive summary...")
        summary = await self.generate_summary(episode, transcript_text, transcript_source)
        
        if summary:
            logger.info("✅ Episode processed successfully!")
        else:
            logger.error("❌ Failed to generate summary")
        
        return summary
    
    async def transcribe_from_audio(self, episode: Episode) -> Optional[Path]:
        """Download and transcribe audio"""
        if not episode.audio_url:
            logger.error("❌ No audio URL available")
            return None
        
        try:
            # Create unique filename
            slug = self.slugify(episode.title)
            hash_val = hashlib.md5(episode.audio_url.encode()).hexdigest()[:6]
            transcript_file = TRANSCRIPT_DIR / f"{slug[:50]}_{hash_val}.txt"
            
            # Check if already transcribed
            if transcript_file.exists():
                logger.info("✅ Found existing transcription")
                return transcript_file
            
            # Download audio
            logger.info("⬇️  Downloading audio...")
            audio_path = await self.download_audio(episode.audio_url)
            
            if not audio_path:
                return None
            
            # Transcribe with Whisper
            logger.info("🎯 Transcribing with Whisper...")
            transcript = await self.transcribe_with_whisper(audio_path)
            
            # Save transcript
            if transcript:
                with open(transcript_file, 'w', encoding='utf-8') as f:
                    f.write(transcript)
                logger.info(f"✅ Transcript saved: {transcript_file}")
                
                # Clean up audio file
                try:
                    os.remove(audio_path)
                except:
                    pass
                
                return transcript_file
            
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return None
    
    async def download_audio(self, audio_url: str) -> Optional[Path]:
        """Download audio file"""
        try:
            import aiofiles
            from aiohttp import ClientSession
            
            # Create temp file
            temp_file = AUDIO_DIR / f"temp_{hashlib.md5(audio_url.encode()).hexdigest()[:8]}.mp3"
            
            async with ClientSession() as session:
                async with session.get(audio_url) as response:
                    if response.status == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        
                        async with aiofiles.open(temp_file, 'wb') as f:
                            downloaded = 0
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                
                                if total_size > 0:
                                    progress = (downloaded / total_size) * 100
                                    print(f"\r  Progress: {progress:.1f}%", end='', flush=True)
                        
                        print()  # New line after progress
                        logger.info(f"✅ Downloaded: {downloaded/1_000_000:.1f}MB")
                        return temp_file
                    else:
                        logger.error(f"❌ Download failed: HTTP {response.status}")
                        
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
        
        return None
    
    async def transcribe_with_whisper(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper"""
        try:
            # Load and process audio
            from pydub import AudioSegment
            
            audio = AudioSegment.from_file(audio_path)
            duration_min = len(audio) / 60000
            
            logger.info(f"⏱️  Duration: {duration_min:.1f} minutes")
            
            # Apply testing limit if enabled
            if TESTING_MODE and duration_min > MAX_TRANSCRIPTION_MINUTES:
                logger.info(f"🧪 TESTING MODE: Limiting to {MAX_TRANSCRIPTION_MINUTES} minutes")
                audio = audio[:MAX_TRANSCRIPTION_MINUTES * 60 * 1000]
            
            # Create chunks for Whisper (25MB limit)
            chunks = self._create_audio_chunks(audio)
            logger.info(f"📦 Created {len(chunks)} chunks for transcription")
            
            transcripts = []
            
            for i, chunk_path in enumerate(chunks):
                logger.info(f"🎙️  Transcribing chunk {i+1}/{len(chunks)}...")
                
                with open(chunk_path, 'rb') as audio_file:
                    transcript = openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="text"
                    )
                
                transcripts.append(transcript.strip())
                
                # Clean up chunk
                try:
                    os.remove(chunk_path)
                except:
                    pass
                
                # Small delay between API calls
                if i < len(chunks) - 1:
                    await asyncio.sleep(1)
            
            # Merge transcripts
            full_transcript = " ".join(transcripts)
            logger.info(f"✅ Transcription complete: {len(full_transcript)} characters")
            
            return full_transcript
            
        except Exception as e:
            logger.error(f"❌ Whisper error: {e}")
            return None
    
    def _create_audio_chunks(self, audio: AudioSegment, max_size_mb: int = 20) -> List[Path]:
        """Split audio into chunks for Whisper API"""
        chunks = []
        chunk_duration_ms = 20 * 60 * 1000  # 20 minutes
        
        for i in range(0, len(audio), chunk_duration_ms):
            chunk = audio[i:i + chunk_duration_ms]
            
            # Export chunk
            chunk_path = TEMP_DIR / f"chunk_{i//chunk_duration_ms}.mp3"
            chunk.export(chunk_path, format="mp3", bitrate="64k")
            
            # Check size
            if os.path.getsize(chunk_path) > max_size_mb * 1024 * 1024:
                # Re-export with lower quality
                os.remove(chunk_path)
                chunk.export(chunk_path, format="mp3", bitrate="32k")
            
            chunks.append(chunk_path)
        
        return chunks
    
    async def generate_summary(self, episode: Episode, transcript: str, source: TranscriptSource) -> Optional[str]:
        """Generate executive summary using GPT-4o"""
        try:
            # Check for cached summary
            summary_file = SUMMARY_DIR / f"{episode.guid}_summary.md"
            if summary_file.exists():
                logger.info("✅ Found cached summary")
                with open(summary_file, 'r', encoding='utf-8') as f:
                    return f.read()
            
            # Your existing summary generation logic
            prompt = f"""EPISODE: {episode.title}
PODCAST: {episode.podcast}
TRANSCRIPT SOURCE: {source.value}

TRANSCRIPT:
{transcript[:100000]}  # Limit for API

[Your existing executive summary prompt...]
"""
            
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are the lead writer for Renaissance Weekly..."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content
            
            # Add metadata
            summary += f"\n\n---\n\n"
            summary += f"**Episode**: {episode.title}\n"
            summary += f"**Podcast**: {episode.podcast}\n"
            summary += f"**Published**: {episode.published.strftime('%Y-%m-%d')}\n"
            summary += f"**Transcript Source**: {source.value}\n"
            if episode.link:
                summary += f"**Link**: [{episode.title}]({episode.link})\n"
            
            # Cache summary
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Summary generation error: {e}")
            return None
    
    def slugify(self, text: str) -> str:
        """Convert text to filename-safe string"""
        return "".join(c if c.isalnum() or c in " ._-" else "_" for c in text)
    
    async def run(self, days_back: int = 7):
        """Main execution function"""
        logger.info("🚀 Starting Renaissance Weekly System...")
        logger.info(f"📧 Email delivery: {EMAIL_FROM} → {EMAIL_TO}")
        logger.info(f"📅 Looking back {days_back} days")
        
        if TESTING_MODE:
            logger.info(f"🧪 TESTING MODE: Limited to {MAX_TRANSCRIPTION_MINUTES} min transcriptions")
        
        # Fetch episodes from all configured podcasts
        all_episodes = []
        
        for podcast_config in PODCAST_CONFIGS:
            episodes = await self.episode_fetcher.fetch_episodes(podcast_config, days_back)
            all_episodes.extend(episodes)
        
        if not all_episodes:
            logger.error("❌ No recent episodes found")
            return
        
        logger.info(f"✅ Found {len(all_episodes)} total episodes")
        
        # Episode selection UI (your existing code)
        selected_episodes = self.run_selection_server(all_episodes)
        
        if not selected_episodes:
            logger.warning("❌ No episodes selected")
            return
        
        logger.info(f"🎯 Processing {len(selected_episodes)} selected episodes...")
        
        # Process episodes concurrently
        summaries = []
        
        async def process_with_semaphore(episode, semaphore):
            async with semaphore:
                return await self.process_episode(episode)
        
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
        
        tasks = [
            process_with_semaphore(Episode(**ep), semaphore)
            for ep in selected_episodes
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Episode {i+1} failed: {result}")
            elif result:
                summaries.append(result)
        
        logger.info(f"✅ Successfully processed {len(summaries)}/{len(selected_episodes)} episodes")
        
        # Send email digest
        if summaries:
            if self.send_summary_email(summaries, selected_episodes):
                logger.info("📧 Renaissance Weekly digest sent!")
            else:
                logger.error("❌ Failed to send email")
    
    # Include all your existing UI and email methods here...
    def run_selection_server(self, episodes: List[Dict]):
        """Run a temporary web server for episode selection"""
        selected_episodes = []
        server_running = True
        parent_instance = self
        
        class SelectionHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = parent_instance.create_selection_html(episodes)
                    self.wfile.write(html.encode())
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/select':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    for idx in data['selected']:
                        selected_episodes.append(episodes[idx])
                    
                    self.send_response(200)
                    self.end_headers()
                    
                    nonlocal server_running
                    server_running = False
            
            def log_message(self, format, *args):
                pass  # Suppress logs
        
        # Find available port
        port = 8888
        for attempt in range(5):
            try:
                server = HTTPServer(('localhost', port), SelectionHandler)
                break
            except OSError:
                port += 1
                if attempt == 4:
                    logger.error("Could not start web server")
                    return self._fallback_text_selection(episodes)
        
        # Open browser
        url = f'http://localhost:{port}'
        logger.info(f"🌐 Opening episode selection at {url}")
        
        try:
            webbrowser.open(url)
        except:
            logger.warning(f"Please open: {url}")
        
        # Run server
        logger.info("⏳ Waiting for episode selection...")
        
        try:
            while server_running:
                server.handle_request()
        except KeyboardInterrupt:
            logger.warning("Selection cancelled")
            selected_episodes = []
        finally:
            server.server_close()
        
        return selected_episodes
    
    def create_selection_html(self, episodes: List[Dict]) -> str:
        """Create an HTML page for episode selection"""
        html = """<!DOCTYPE html>
<html>
<head>
    <title>Renaissance Weekly - Episode Selection</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 { color: #333; margin-bottom: 10px; }
        .subtitle { color: #666; margin-bottom: 30px; font-size: 18px; }
        .podcast-group {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .podcast-title {
            font-size: 20px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }
        .episode {
            padding: 15px;
            margin-bottom: 10px;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        .episode:hover { background-color: #f8f9fa; border-color: #4a90e2; }
        .episode.selected { background-color: #e3f2fd; border-color: #2196f3; }
        .episode-header { display: flex; align-items: flex-start; gap: 15px; }
        input[type="checkbox"] { width: 20px; height: 20px; margin-top: 2px; cursor: pointer; }
        .episode-content { flex: 1; }
        .episode-title { font-weight: 500; color: #333; margin-bottom: 5px; font-size: 16px; }
        .episode-meta { font-size: 14px; color: #666; margin-bottom: 8px; }
        .episode-description { font-size: 15px; color: #555; line-height: 1.5; }
        .transcript-badge {
            display: inline-block;
            padding: 2px 8px;
            background: #4CAF50;
            color: white;
            font-size: 12px;
            border-radius: 4px;
            margin-left: 10px;
        }
        .controls {
            position: sticky;
            top: 20px;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .button {
            padding: 12px 24px;
            margin: 5px;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .button-primary { background-color: #4a90e2; color: white; }
        .button-primary:hover { background-color: #357abd; }
        .button-secondary { background-color: #6c757d; color: white; }
        .button-secondary:hover { background-color: #545b62; }
        .selection-count { font-size: 16px; color: #666; margin-left: 20px; }
        .loading {
            display: none;
            text-align: center;
            padding: 40px;
            font-size: 18px;
            color: #666;
        }
    </style>
</head>
<body>
    <h1>🎙️ Renaissance Weekly</h1>
    <p class="subtitle">Select episodes to process for this week's digest</p>
    
    <div class="controls">
        <button class="button button-primary" onclick="processSelected()">Process Selected Episodes</button>
        <button class="button button-secondary" onclick="selectAll()">Select All</button>
        <button class="button button-secondary" onclick="selectNone()">Clear All</button>
        <span class="selection-count">0 episodes selected</span>
    </div>
    
    <div class="loading" id="loading">
        Processing your selection... This window will close automatically.
    </div>
    
    <div id="episodes">
"""
        
        # Group episodes by podcast
        by_podcast = {}
        for i, ep in enumerate(episodes):
            podcast = ep.podcast if isinstance(ep, Episode) else ep.get('podcast', 'Unknown')
            if podcast not in by_podcast:
                by_podcast[podcast] = []
            by_podcast[podcast].append((i, ep))
        
        # Create HTML for each podcast group
        for podcast, podcast_episodes in by_podcast.items():
            html += f'<div class="podcast-group">\n'
            html += f'<div class="podcast-title">{podcast}</div>\n'
            
            for idx, ep in podcast_episodes:
                if isinstance(ep, Episode):
                    title = ep.title
                    published = ep.published.strftime('%Y-%m-%d')
                    duration = ep.duration
                    has_transcript = ep.transcript_url is not None
                else:
                    title = ep.get('title', 'Unknown')
                    published = ep.get('published', 'Unknown')
                    duration = ep.get('duration', 'Unknown')
                    has_transcript = ep.get('transcript_url') is not None
                
                transcript_badge = '<span class="transcript-badge">TRANSCRIPT</span>' if has_transcript else ''
                
                html += f'''<div class="episode" id="episode-{idx}">
    <div class="episode-header">
        <input type="checkbox" id="cb-{idx}" value="{idx}" onchange="updateSelection()">
        <div class="episode-content">
            <div class="episode-title">{html.escape(title)}{transcript_badge}</div>
            <div class="episode-meta">📅 {published} | ⏱️ {duration}</div>
            <div class="episode-description">Click to select this episode for processing</div>
        </div>
    </div>
</div>\n'''
            
            html += '</div>\n'
        
        html += """
    </div>
    
    <script>
        function updateSelection() {
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            let count = 0;
            checkboxes.forEach(cb => {
                const episode = document.getElementById('episode-' + cb.value);
                if (cb.checked) {
                    count++;
                    episode.classList.add('selected');
                } else {
                    episode.classList.remove('selected');
                }
            });
            document.querySelector('.selection-count').textContent = count + ' episodes selected';
        }
        
        function selectAll() {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            updateSelection();
        }
        
        function selectNone() {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            updateSelection();
        }
        
        function processSelected() {
            const selected = [];
            document.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                selected.push(parseInt(cb.value));
            });
            
            if (selected.length === 0) {
                alert('Please select at least one episode to process.');
                return;
            }
            
            document.getElementById('loading').style.display = 'block';
            document.getElementById('episodes').style.display = 'none';
            document.querySelector('.controls').style.display = 'none';
            
            fetch('/select', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({selected: selected})
            }).then(() => {
                setTimeout(() => window.close(), 1000);
            });
        }
    </script>
</body>
</html>
"""
        
        return html
    
    def _fallback_text_selection(self, episodes: List[Dict]) -> List[Dict]:
        """Text-based fallback selection method"""
        print("\n" + "="*80)
        print("📻 RECENT PODCAST EPISODES (Text Selection)")
        print("="*80)
        
        episode_map = {}
        for i, ep in enumerate(episodes):
            if isinstance(ep, Episode):
                print(f"\n[{i+1}] {ep.podcast}: {ep.title}")
                print(f"    📅 {ep.published.strftime('%Y-%m-%d')} | ⏱️  {ep.duration}")
                if ep.transcript_url:
                    print(f"    ✅ Transcript available")
            else:
                print(f"\n[{i+1}] {ep['podcast']}: {ep['title']}")
                print(f"    📅 {ep['published']} | ⏱️  {ep['duration']}")
            episode_map[i+1] = ep
        
        print("\n" + "="*80)
        print("Enter episode numbers separated by commas (e.g., 1,3,5)")
        print("Or type 'all' for all episodes, 'none' to exit")
        
        while True:
            selection = input("\n🎯 Your selection: ").strip().lower()
            
            if selection == 'none':
                return []
            
            if selection == 'all':
                return episodes
            
            try:
                if not selection:
                    print("❌ Please enter episode numbers or 'all'/'none'")
                    continue
                
                selected_indices = [int(x.strip()) for x in selection.split(',') if x.strip()]
                
                invalid = [i for i in selected_indices if i not in episode_map]
                if invalid:
                    print(f"❌ Invalid episode numbers: {invalid}")
                    continue
                
                selected_episodes = [episode_map[i] for i in selected_indices]
                
                print(f"\n✅ Selected {len(selected_episodes)} episode(s)")
                return selected_episodes
                
            except ValueError:
                print("❌ Invalid input. Please enter numbers separated by commas.")
    
    def send_summary_email(self, summaries: List[str], episodes: List[Dict]) -> bool:
        """Send Renaissance Weekly digest"""
        try:
            logger.info("📧 Preparing Renaissance Weekly digest...")
            
            # Create email content
            html_content = self.create_substack_style_email(summaries)
            plain_content = self._create_plain_text_version(summaries)
            
            # Create subject
            subject = f"Renaissance Weekly: {len(summaries)} Essential Conversations"
            
            # Create message
            message = Mail(
                from_email=(EMAIL_FROM, "Renaissance Weekly"),
                to_emails=EMAIL_TO,
                subject=subject,
                plain_text_content=plain_content,
                html_content=html_content
            )
            
            # Send email
            response = sendgrid_client.send(message)
            
            if response.status_code == 202:
                logger.info("✅ Email sent successfully!")
                return True
            else:
                logger.error(f"Email failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Email error: {e}")
            return False
    
    def create_substack_style_email(self, summaries: List[str]) -> str:
        """Create clean HTML email"""
        episodes_html = ""
        
        for i, summary in enumerate(summaries):
            if i > 0:
                episodes_html += '<tr><td style="padding: 60px 0 40px 0;"><div style="text-align: center; font-size: 20px; color: #E0E0E0; letter-spacing: 8px;">• • •</div></td></tr>'
            
            # Convert markdown to HTML
            html_content = self._convert_markdown_to_html(summary)
            episodes_html += f'<tr><td>{html_content}</td></tr>'
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 18px; line-height: 1.6; color: #333; background-color: #FFF;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #FFF;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width: 600px;">
                    <tr>
                        <td style="padding: 0 0 40px 0; text-align: center;">
                            <h1 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 48px; font-weight: normal; letter-spacing: -1px; color: #000;">Renaissance Weekly</h1>
                            <p style="margin: 0 0 20px 0; font-size: 18px; color: #666; font-style: italic;">The smartest podcasts, distilled.</p>
                            <p style="margin: 0; font-size: 14px; color: #999; text-transform: uppercase; letter-spacing: 1px;">{datetime.now().strftime('%B %d, %Y')}</p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 0 0 50px 0;">
                            <p style="margin: 0; font-size: 20px; line-height: 1.7; color: #333; font-weight: 300;">In a world of infinite content, attention is the scarcest resource. This week's edition brings you the essential insights from conversations that matter.</p>
                        </td>
                    </tr>
                    {episodes_html}
                    <tr>
                        <td style="padding: 80px 0 40px 0; text-align: center; border-top: 1px solid #E0E0E0;">
                            <p style="margin: 0 0 15px 0; font-size: 24px; font-family: Georgia, serif; color: #000;">Renaissance Weekly</p>
                            <p style="margin: 0 0 20px 0; font-size: 16px; color: #666; font-style: italic;">"For those who remain curious."</p>
                            <p style="margin: 0; font-size: 14px; color: #999;">
                                <a href="https://gistcapture.ai" style="color: #666; text-decoration: none;">gistcapture.ai</a>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    
        def _convert_markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to HTML"""
        html = markdown
        
        # Headers
        html = re.sub(r'^### (.*?)$', r'<h3 style="margin: 25px 0 15px 0; font-size: 20px; color: #333;">\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.*?)$', r'<h2 style="margin: 30px 0 20px 0; font-size: 24px; color: #000;">\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.*?)$', r'<h1 style="margin: 40px 0 30px 0; font-size: 32px; color: #000;">\1</h1>', html, flags=re.MULTILINE)
        
        # Bold and italic
        html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', html)
        
        # Links
        html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2" style="color: #0066CC;">\1</a>', html)
        
        # Paragraphs
        paragraphs = html.split('\n\n')
        html = ''.join([f'<p style="margin: 0 0 20px 0;">{p}</p>' for p in paragraphs if p.strip()])
        
        return html

    def _create_plain_text_version(self, summaries: List[str]) -> str:
        """Create plain text version"""
        plain = "RENAISSANCE WEEKLY\n"
        plain += "The smartest podcasts, distilled.\n"
        plain += f"{datetime.now().strftime('%B %d, %Y')}\n\n"
        plain += "="*60 + "\n\n"
        
        for summary in summaries:
            # Remove markdown
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', summary)
            text = re.sub(r'\*([^*]+)\*', r'\1', text)
            text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1 (\2)', text)
            text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
            
            plain += text + "\n\n" + "="*60 + "\n\n"
        
        plain += "Renaissance Weekly\n"
        plain += "For those who remain curious.\n"
        plain += "https://gistcapture.ai"
        
        return plain


# Podcast configurations with multiple sources
PODCAST_CONFIGS = [
    {
        "name": "Market Huddle",
        "rss_feeds": [
            "https://markethuddle.substack.com/feed",
            "https://api.substack.com/feed/podcast/140759.rss",
            "https://feeds.simplecast.com/PftbA45m"
        ],
        "apple_id": "1552799888",
        "website": "https://markethuddle.substack.com"
    },
    {
        "name": "Tim Ferriss",
        "rss_feeds": [
            "https://rss.art19.com/tim-ferriss-show",
            "https://tim.blog/feed/podcast/",
            "https://feeds.megaphone.fm/TIM"
        ],
        "apple_id": "863897795",
        "website": "https://tim.blog",
        "has_transcripts": True  # Tim provides transcripts
    },
    {
        "name": "Huberman Lab",
        "rss_feeds": [
            "https://feeds.megaphone.fm/hubermanlab",
            "https://feeds.megaphone.fm/ADL9840290619"
        ],
        "apple_id": "1545953110",
        "website": "https://hubermanlab.com",
        "has_transcripts": True
    },
    {
        "name": "All-In",
        "rss_feeds": [
            "https://feeds.megaphone.fm/all-in-with-chamath-jason-sacks-friedberg",
            "https://anchor.fm/s/2b337d28/podcast/rss"
        ],
        "apple_id": "1502871393",
        "website": "https://www.allinpodcast.co"
    },
    # Add all your other podcasts here...
]


def main():
    """Entry point"""
    try:
        # Set up async event loop
        if os.name == 'nt':  # Windows
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # Run the app
        app = RenaissanceWeekly()
        
        # Get days_back from command line
        import sys
        days_back = 7
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            days_back = int(sys.argv[1])
        
        # Run async main
        asyncio.run(app.run(days_back))
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()