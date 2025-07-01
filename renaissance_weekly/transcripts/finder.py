"""Find existing transcripts from various sources"""

import re
import aiohttp
import asyncio
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from ..models import Episode, TranscriptSource
from ..database import PodcastDatabase
from ..utils.logging import get_logger
from .youtube_transcript import YouTubeTranscriptFinder
from .podcast_index import PodcastIndexAPI
from .transcript_sources import ComprehensiveTranscriptFinder

logger = get_logger(__name__)


class TranscriptFinder:
    """Find existing transcripts from RSS feeds, websites, or APIs"""
    
    def __init__(self, db: PodcastDatabase):
        self.db = db
        self.session = None
        self._session_created = False
        self.youtube_finder = YouTubeTranscriptFinder()
        self.podcast_index = PodcastIndexAPI()
        self.comprehensive_finder = ComprehensiveTranscriptFinder()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if not self._session_created or self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            )
            self._session_created = True
        return self.session
    
    async def cleanup(self):
        """Cleanup aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self._session_created = False
    
    async def find_transcript(self, episode: Episode) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """Find transcript from various sources"""
        logger.info("🔍 Searching for existing transcript...")
        
        # Check database cache first
        cached_transcript, cached_source = self.db.get_transcript(episode)
        if cached_transcript:
            logger.info(f"✅ Found cached transcript (source: {cached_source.value})")
            return cached_transcript, cached_source
        
        # Try to find transcript from various sources
        # 1. Check if RSS feed included transcript URL
        if episode.transcript_url:
            transcript = await self._fetch_from_url(episode.transcript_url)
            if transcript:
                logger.info("✅ Found transcript from RSS feed URL")
                return transcript, TranscriptSource.RSS_FEED
        
        # 2. Use comprehensive transcript finder for all sources
        transcript, source = await self.comprehensive_finder.find_transcript(episode)
        if transcript:
            logger.info(f"✅ Found transcript via comprehensive search (source: {source.value})")
            return transcript, source
        
        # 3. Try to scrape from episode page (fallback to original method)
        if episode.link:
            transcript = await self._scrape_from_page(episode.link)
            if transcript:
                logger.info("✅ Found transcript from episode page")
                return transcript, TranscriptSource.SCRAPED
        
        # 4. Try Podcast Index API
        podcast_index_url = await self.podcast_index.find_episode_transcript(
            episode.title, episode.podcast
        )
        if podcast_index_url:
            transcript = await self._fetch_from_url(podcast_index_url)
            if transcript:
                logger.info("✅ Found transcript from Podcast Index")
                return transcript, TranscriptSource.RSS_FEED
        
        # 5. Try podcast-specific methods
        transcript = await self._try_podcast_specific_methods(episode)
        if transcript:
            logger.info("✅ Found transcript using podcast-specific method")
            return transcript, TranscriptSource.SCRAPED
        
        # 6. Try YouTube transcript
        transcript = await self.youtube_finder.find_youtube_transcript(
            episode.title, episode.podcast, episode.link
        )
        if transcript:
            logger.info("✅ Found transcript from YouTube")
            return transcript, TranscriptSource.SCRAPED
        
        logger.info("❌ No transcript found from any source")
        return None, None
    
    async def _fetch_from_url(self, url: str) -> Optional[str]:
        """Fetch transcript from direct URL"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    # Clean up the content
                    if content.strip().startswith('<'):
                        # It's HTML, extract text
                        soup = BeautifulSoup(content, 'html.parser')
                        return soup.get_text(separator='\n', strip=True)
                    return content
        except Exception as e:
            logger.debug(f"Failed to fetch transcript from URL: {e}")
        return None
    
    async def _scrape_from_page(self, url: str) -> Optional[str]:
        """Scrape transcript from episode page"""
        logger.info(f"🌐 Trying to scrape from episode page: {url}")
        
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Common transcript containers
                selectors = [
                    'div.transcript',
                    'div#transcript',
                    'div.episode-transcript',
                    'div.podcast-transcript',
                    'article.transcript',
                    'section.transcript',
                    'div[class*="transcript"]',
                    'div[id*="transcript"]',
                    # Simplecast specific
                    'div.prose',
                    'div.episode-content',
                    # Libsyn specific
                    'div.libsyn-item-body',
                    # Generic content containers
                    'div.content',
                    'article.content',
                    'main',
                ]
                
                for selector in selectors:
                    elements = soup.select(selector)
                    for element in elements:
                        text = element.get_text(separator='\n', strip=True)
                        # Check if it looks like a transcript
                        if self._is_likely_transcript(text):
                            logger.info(f"✅ Found transcript using selector: {selector}")
                            return self._clean_transcript(text)
                
                # Look for "transcript" heading followed by content
                headings = soup.find_all(['h1', 'h2', 'h3', 'h4'], 
                                       string=re.compile(r'transcript', re.I))
                for heading in headings:
                    next_element = heading.find_next_sibling()
                    if next_element:
                        text = next_element.get_text(separator='\n', strip=True)
                        if self._is_likely_transcript(text):
                            logger.info("✅ Found transcript after heading")
                            return self._clean_transcript(text)
                
        except Exception as e:
            logger.debug(f"Failed to scrape transcript: {e}")
        
        return None
    
    async def _try_podcast_specific_methods(self, episode: Episode) -> Optional[str]:
        """Try podcast-specific methods to find transcripts"""
        podcast_lower = episode.podcast.lower()
        
        # A16Z often has transcripts on their blog
        if 'a16z' in podcast_lower:
            return await self._try_a16z_transcript(episode)
        
        # Tim Ferriss publishes transcripts on his blog
        if 'tim ferriss' in podcast_lower or 'ferriss' in podcast_lower:
            return await self._try_tim_ferriss_transcript(episode)
        
        # American Optimist on Substack
        if 'american optimist' in podcast_lower:
            return await self._try_american_optimist_transcript(episode)
        
        # Add more podcast-specific methods as needed
        
        return None
    
    async def _try_a16z_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find A16Z transcript from their blog"""
        # A16Z sometimes publishes transcripts on their blog
        # This would require searching their site or API
        # For now, this is a placeholder
        return None
    
    async def _try_tim_ferriss_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find Tim Ferriss transcript from tim.blog"""
        logger.info("🔍 Looking for Tim Ferriss transcript on tim.blog...")
        
        # Extract episode number from title
        episode_match = re.search(r'#(\d+)', episode.title)
        if not episode_match:
            return None
            
        episode_num = episode_match.group(1)
        
        # Try common URL patterns for Tim Ferriss transcripts
        url_patterns = [
            f"https://tim.blog/{episode.published.year}/{episode.published.strftime('%m')}/{episode.published.strftime('%d')}/transcript",
            f"https://tim.blog/podcast/transcripts/ep-{episode_num}",
            # Search for the episode page and look for transcript link
        ]
        
        for url in url_patterns:
            try:
                session = await self._get_session()
                async with session.get(url, allow_redirects=True) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Look for transcript section
                        transcript_div = soup.find('div', class_='transcript') or \
                                       soup.find('div', id='transcript') or \
                                       soup.find('article', class_='entry-content')
                        
                        if transcript_div:
                            text = transcript_div.get_text(separator='\n', strip=True)
                            if self._is_likely_transcript(text):
                                logger.info("✅ Found Tim Ferriss transcript")
                                return self._clean_transcript(text)
            except Exception as e:
                logger.debug(f"Failed to fetch from {url}: {e}")
                continue
        
        # Try searching tim.blog for the episode
        try:
            search_query = re.sub(r'#\d+:\s*', '', episode.title)[:50]  # Remove episode number
            search_url = f"https://tim.blog/?s={search_query.replace(' ', '+')}"
            
            session = await self._get_session()
            async with session.get(search_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for matching article
                    articles = soup.find_all('article')
                    for article in articles[:3]:  # Check first 3 results
                        link = article.find('a', href=True)
                        if link and 'transcript' in link.get('href', '').lower():
                            # Found a transcript link
                            transcript = await self._scrape_from_page(link['href'])
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"Tim Ferriss search failed: {e}")
        
        return None
    
    async def _try_american_optimist_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find American Optimist transcript from Substack"""
        logger.info("🔍 Looking for American Optimist transcript on Substack...")
        
        # American Optimist is hosted on Substack
        # Try to find the Substack post URL
        if episode.link and 'substack.com' in episode.link:
            # Direct Substack post link
            transcript = await self._scrape_substack_post(episode.link)
            if transcript:
                return transcript
        
        # Try searching americanoptimist.substack.com
        try:
            # Clean episode title for search
            search_title = re.sub(r'Ep\s*\d+:\s*', '', episode.title)[:50]
            search_url = f"https://americanoptimist.substack.com/archive?sort=search&search={search_title.replace(' ', '%20')}"
            
            session = await self._get_session()
            async with session.get(search_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Find matching post
                    posts = soup.find_all('a', href=True)
                    for post in posts:
                        href = post.get('href', '')
                        if '/p/' in href and search_title.lower()[:20] in post.get_text().lower():
                            # Found matching post
                            full_url = f"https://americanoptimist.substack.com{href}" if href.startswith('/') else href
                            transcript = await self._scrape_substack_post(full_url)
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"American Optimist search failed: {e}")
        
        return None
    
    async def _scrape_substack_post(self, url: str) -> Optional[str]:
        """Scrape transcript from Substack post"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Substack post content is usually in div.post-content or div.body
                    content_div = soup.find('div', class_='post-content') or \
                                soup.find('div', class_='body') or \
                                soup.find('div', class_='available-content')
                    
                    if content_div:
                        # Remove audio player and buttons
                        for element in content_div.find_all(['button', 'audio', 'div'], class_=['audio-player', 'subscribe-widget']):
                            element.decompose()
                        
                        text = content_div.get_text(separator='\n', strip=True)
                        
                        # Check if it's a transcript (not just show notes)
                        if self._is_likely_transcript(text) or len(text) > 5000:
                            logger.info("✅ Found Substack transcript")
                            return self._clean_transcript(text)
        except Exception as e:
            logger.debug(f"Failed to scrape Substack post: {e}")
        
        return None
    
    def _is_likely_transcript(self, text: str) -> bool:
        """Check if text is likely a transcript"""
        if not text or len(text) < 1000:  # Too short
            return False
        
        # Check for dialogue patterns
        dialogue_patterns = [
            r'\n\s*\w+\s*:\s*',  # Name: dialogue
            r'\[\d+:\d+:\d+\]',  # Timestamps
            r'\[\d+:\d+\]',      # Shorter timestamps
            r'Speaker \d+:',     # Speaker 1: etc
        ]
        
        for pattern in dialogue_patterns:
            if re.search(pattern, text):
                return True
        
        # Check word count (transcripts are usually long)
        word_count = len(text.split())
        if word_count > 2000:  # Reasonable threshold for podcast transcript
            return True
        
        return False
    
    def _clean_transcript(self, text: str) -> str:
        """Clean transcript text"""
        # Remove excessive whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Remove common non-transcript elements
        lines = text.split('\n')
        cleaned_lines = []
        
        skip_patterns = [
            r'^Share$',
            r'^Subscribe$',
            r'^Download$',
            r'^Tweet$',
            r'^Email$',
            r'^\d+:\d+$',  # Lone timestamps
            r'^Advertisement$',
        ]
        
        for line in lines:
            line = line.strip()
            if not line:
                cleaned_lines.append('')
                continue
            
            # Skip lines matching skip patterns
            if any(re.match(pattern, line, re.I) for pattern in skip_patterns):
                continue
            
            cleaned_lines.append(line)
        
        # Join and clean up
        cleaned = '\n'.join(cleaned_lines)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        return cleaned.strip()