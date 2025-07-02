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
from ..robustness_config import should_use_feature
from .substack_enhanced import AmericanOptimistEnhanced, DwarkeshPodcastEnhanced

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
        
        # 2. Try podcast-specific methods FIRST (before generic scraping)
        transcript = await self._try_podcast_specific_methods(episode)
        if transcript:
            logger.info("✅ Found transcript using podcast-specific method")
            return transcript, TranscriptSource.SCRAPED
        
        # 3. Use comprehensive transcript finder for all sources (if enabled)
        if should_use_feature('use_comprehensive_transcript_finder'):
            async with self.comprehensive_finder:
                transcript, source = await self.comprehensive_finder.find_transcript(episode)
                if transcript:
                    logger.info(f"✅ Found transcript via comprehensive search (source: {source.value})")
                    return transcript, source
        else:
            logger.debug("Comprehensive transcript finder is disabled via feature flag")
        
        # 4. Try to scrape from episode page (fallback to original method)
        if episode.link:
            transcript = await self._scrape_from_page(episode.link)
            if transcript:
                logger.info("✅ Found transcript from episode page")
                return transcript, TranscriptSource.SCRAPED
        
        # 5. Try Podcast Index API
        podcast_index_url = await self.podcast_index.find_episode_transcript(
            episode.title, episode.podcast
        )
        if podcast_index_url:
            transcript = await self._fetch_from_url(podcast_index_url)
            if transcript:
                logger.info("✅ Found transcript from Podcast Index")
                return transcript, TranscriptSource.RSS_FEED
        
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
        
        # Dwarkesh Podcast on Substack
        if 'dwarkesh' in podcast_lower:
            return await self._try_dwarkesh_transcript(episode)
        
        # Huberman Lab often has detailed show notes
        if 'huberman' in podcast_lower:
            return await self._try_huberman_transcript(episode)
        
        # The Doctor's Farmacy
        if 'farmacy' in podcast_lower or 'doctor' in podcast_lower:
            return await self._try_doctors_farmacy_transcript(episode)
        
        # The Drive (Peter Attia)
        if 'the drive' in podcast_lower or 'attia' in podcast_lower:
            return await self._try_the_drive_transcript(episode)
        
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
        logger.info("🔍 Looking for American Optimist transcript...")
        
        # First try the enhanced multi-source approach
        try:
            transcript, audio_url = await AmericanOptimistEnhanced.get_content(episode)
            if transcript:
                logger.info("✅ Found American Optimist transcript via enhanced methods")
                return transcript
        except Exception as e:
            logger.debug(f"Enhanced methods failed: {e}")
        
        # Fall back to standard Substack scraping
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
    
    async def _try_dwarkesh_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find Dwarkesh Podcast transcript from Substack"""
        logger.info("🔍 Looking for Dwarkesh Podcast transcript...")
        
        # First try the enhanced multi-source approach
        try:
            transcript, audio_url = await DwarkeshPodcastEnhanced.get_content(episode)
            if transcript:
                logger.info("✅ Found Dwarkesh transcript via enhanced methods")
                return transcript
        except Exception as e:
            logger.debug(f"Enhanced methods failed: {e}")
        
        # Fall back to standard Substack scraping
        if episode.link and 'substack.com' in episode.link:
            transcript = await self._scrape_substack_post(episode.link)
            if transcript:
                return transcript
        
        # Try searching dwarkeshpatel.substack.com
        try:
            # Clean episode title for search
            search_title = re.sub(r'Episode\s*\d+:\s*', '', episode.title)[:50]
            search_url = f"https://dwarkeshpatel.substack.com/archive?sort=search&search={search_title.replace(' ', '%20')}"
            
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
                            full_url = f"https://dwarkeshpatel.substack.com{href}" if href.startswith('/') else href
                            transcript = await self._scrape_substack_post(full_url)
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"Dwarkesh search failed: {e}")
        
        return None
    
    async def _try_huberman_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find Huberman Lab transcript from show notes"""
        logger.info("🔍 Looking for Huberman Lab transcript...")
        
        # Huberman often has detailed show notes that serve as partial transcripts
        if episode.link:
            transcript = await self._scrape_huberman_show_notes(episode.link)
            if transcript:
                return transcript
        
        # Try hubermanlab.com search
        try:
            # Extract episode number or guest name
            title_parts = episode.title.split(':')
            search_query = title_parts[-1].strip() if len(title_parts) > 1 else episode.title
            search_query = search_query[:50]
            
            search_url = f"https://www.hubermanlab.com/search?query={search_query.replace(' ', '+')}"
            
            session = await self._get_session()
            async with session.get(search_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for matching episode links
                    links = soup.find_all('a', href=True)
                    for link in links[:5]:  # Check first 5 results
                        href = link.get('href', '')
                        if '/episode/' in href:
                            full_url = f"https://www.hubermanlab.com{href}" if href.startswith('/') else href
                            transcript = await self._scrape_huberman_show_notes(full_url)
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"Huberman search failed: {e}")
        
        return None
    
    async def _scrape_huberman_show_notes(self, url: str) -> Optional[str]:
        """Scrape Huberman Lab show notes which often contain detailed summaries"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for show notes/timestamps section
                    content_selectors = [
                        'div.show-notes',
                        'div.episode-notes',
                        'div.timestamps',
                        'div[class*="content"]',
                        'article',
                        'main'
                    ]
                    
                    for selector in content_selectors:
                        content = soup.select_one(selector)
                        if content:
                            text = content.get_text(separator='\n', strip=True)
                            # Huberman show notes are very detailed, even if not full transcripts
                            if len(text) > 2000:  # Lower threshold for show notes
                                logger.info("✅ Found Huberman Lab show notes/summary")
                                return self._clean_transcript(text)
        except Exception as e:
            logger.debug(f"Failed to scrape Huberman show notes: {e}")
        
        return None
    
    async def _try_doctors_farmacy_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find Doctor's Farmacy transcript"""
        logger.info("🔍 Looking for Doctor's Farmacy transcript...")
        
        # The Doctor's Farmacy sometimes has transcripts on their website
        if episode.link:
            transcript = await self._scrape_doctors_farmacy_page(episode.link)
            if transcript:
                return transcript
        
        # Try drhyman.com search
        try:
            # Extract guest name or topic
            title_parts = episode.title.split('with')
            search_query = title_parts[-1].strip() if len(title_parts) > 1 else episode.title
            search_query = re.sub(r'[^\w\s]', '', search_query)[:40]
            
            search_url = f"https://drhyman.com/?s={search_query.replace(' ', '+')}"
            
            session = await self._get_session()
            async with session.get(search_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for podcast episode links
                    articles = soup.find_all('article', limit=5)
                    for article in articles:
                        link = article.find('a', href=True)
                        if link and ('podcast' in link.get('href', '') or 'farmacy' in link.get('href', '')):
                            transcript = await self._scrape_doctors_farmacy_page(link['href'])
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"Doctor's Farmacy search failed: {e}")
        
        return None
    
    async def _scrape_doctors_farmacy_page(self, url: str) -> Optional[str]:
        """Scrape Doctor's Farmacy episode page"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for transcript or detailed show notes
                    content_selectors = [
                        'div.transcript',
                        'div.episode-content',
                        'div.entry-content',
                        'article.post-content',
                        'main article'
                    ]
                    
                    for selector in content_selectors:
                        content = soup.select_one(selector)
                        if content:
                            # Remove navigation and social elements
                            for elem in content.find_all(['nav', 'aside', 'footer']):
                                elem.decompose()
                            
                            text = content.get_text(separator='\n', strip=True)
                            if self._is_likely_transcript(text) or len(text) > 3000:
                                logger.info("✅ Found Doctor's Farmacy content")
                                return self._clean_transcript(text)
        except Exception as e:
            logger.debug(f"Failed to scrape Doctor's Farmacy page: {e}")
        
        return None
    
    async def _try_the_drive_transcript(self, episode: Episode) -> Optional[str]:
        """Try to find The Drive (Peter Attia) transcript"""
        logger.info("🔍 Looking for The Drive transcript on peterattia.com...")
        
        # The Drive episodes often have transcripts on peterattia.com
        # First try to extract episode number from title
        episode_match = re.search(r'#(\d+)', episode.title) or re.search(r'AMA\s*(\d+)', episode.title)
        
        # Try various URL patterns for Peter Attia's site
        urls_to_try = []
        
        if episode.link:
            # Sometimes the episode link points to the transcript page
            urls_to_try.append(episode.link)
            
            # Try replacing libsyn link with peterattia.com
            if 'libsyn.com' in episode.link:
                # Extract slug from libsyn URL
                slug_match = re.search(r'/([^/]+?)(?:-\d+)?$', episode.link)
                if slug_match:
                    slug = slug_match.group(1)
                    urls_to_try.extend([
                        f"https://peterattia.com/podcast/{slug}/",
                        f"https://www.peterattia.com/podcast/{slug}/",
                        f"https://peterattia.com/{slug}/",
                    ])
        
        if episode_match:
            episode_num = episode_match.group(1)
            urls_to_try.extend([
                f"https://peterattia.com/podcast/episode-{episode_num}/",
                f"https://www.peterattia.com/podcast/episode-{episode_num}/",
                f"https://peterattia.com/episode-{episode_num}/",
            ])
        
        # Try to search based on guest names from title
        # Extract guest names (usually after the topic, separated by |)
        title_parts = episode.title.split('|')
        if len(title_parts) > 1:
            guest_part = title_parts[-1].strip()
            # Remove common suffixes like M.D., Ph.D.
            guest_clean = re.sub(r'\b(M\.D\.|Ph\.D\.|Dr\.)\b', '', guest_part).strip()
            guest_slug = guest_clean.lower().replace(' ', '-').replace(',', '')
            urls_to_try.extend([
                f"https://peterattia.com/podcast/{guest_slug}/",
                f"https://www.peterattia.com/{guest_slug}/",
            ])
        
        # Try each URL
        for url in urls_to_try:
            try:
                transcript = await self._scrape_peterattia_page(url)
                if transcript:
                    return transcript
            except Exception as e:
                logger.debug(f"Failed to fetch from {url}: {e}")
                continue
        
        # If we couldn't find it by direct URL, try searching the site
        try:
            # Clean up episode title for search
            search_title = re.sub(r'#\d+:\s*', '', episode.title)
            search_title = re.sub(r'\s*\|.*$', '', search_title)[:50]  # Remove guest names for search
            
            # Peter Attia's site search
            search_url = f"https://peterattia.com/?s={search_title.replace(' ', '+')}"
            
            session = await self._get_session()
            async with session.get(search_url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Look for podcast episode links in search results
                    articles = soup.find_all('article', limit=5)
                    for article in articles:
                        link = article.find('a', href=True)
                        if link and '/podcast/' in link.get('href', ''):
                            transcript = await self._scrape_peterattia_page(link['href'])
                            if transcript:
                                return transcript
        except Exception as e:
            logger.debug(f"The Drive search failed: {e}")
        
        return None
    
    async def _scrape_peterattia_page(self, url: str) -> Optional[str]:
        """Scrape transcript from Peter Attia's website"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Peter Attia's site often has transcripts in specific sections
                    # First, look for "Full Transcript" or "Transcript" sections
                    transcript_headers = soup.find_all(['h2', 'h3'], string=re.compile(r'transcript', re.I))
                    
                    for header in transcript_headers:
                        # Get the content after the transcript header
                        content_div = header.find_next_sibling('div') or header.parent
                        if content_div:
                            # Sometimes transcript is in a toggle/accordion
                            transcript_content = content_div.find('div', class_=re.compile(r'transcript|content|text', re.I))
                            if transcript_content:
                                text = transcript_content.get_text(separator='\n', strip=True)
                                if self._is_likely_transcript(text):
                                    logger.info("✅ Found The Drive transcript in accordion/toggle")
                                    return self._clean_transcript(text)
                            else:
                                # Try getting all text after the header
                                text = content_div.get_text(separator='\n', strip=True)
                                if self._is_likely_transcript(text):
                                    logger.info("✅ Found The Drive transcript after header")
                                    return self._clean_transcript(text)
                    
                    # Look for specific transcript containers
                    transcript_selectors = [
                        'div.podcast-transcript',
                        'div.episode-transcript',
                        'div.transcript-content',
                        'div.transcript-text',
                        'section.transcript',
                        'div[class*="transcript"]',
                        'div.entry-content div.content',  # Common WordPress pattern
                        'div.podcast-content',
                    ]
                    
                    for selector in transcript_selectors:
                        elements = soup.select(selector)
                        for element in elements:
                            # Skip if it's just show notes or timestamps
                            text = element.get_text(separator='\n', strip=True)
                            
                            # Check if this is actual transcript content, not just show notes
                            if self._is_likely_transcript(text) and not self._is_show_notes(text):
                                logger.info(f"✅ Found The Drive transcript using selector: {selector}")
                                return self._clean_transcript(text)
                    
                    # Sometimes the transcript is in the main content area
                    # but we need to skip the show notes section
                    main_content = soup.find('div', class_='entry-content') or soup.find('article')
                    if main_content:
                        # Find all text sections
                        sections = main_content.find_all(['div', 'section'], recursive=False)
                        
                        for section in sections:
                            # Skip sections that look like show notes
                            section_text = section.get_text(separator='\n', strip=True)
                            if self._is_likely_transcript(section_text) and not self._is_show_notes(section_text):
                                logger.info("✅ Found The Drive transcript in main content")
                                return self._clean_transcript(section_text)
                    
        except Exception as e:
            logger.debug(f"Failed to scrape Peter Attia page: {e}")
        
        return None
    
    def _is_show_notes(self, text: str) -> bool:
        """Check if text is show notes rather than transcript"""
        lines = text.split('\n')[:30]  # Check first 30 lines
        
        show_notes_indicators = [
            'show notes',
            'timestamps',
            'topics discussed',
            'key takeaways',
            'resources mentioned',
            'links from this episode',
            'in this episode',
            'episode highlights',
            'chapter markers',
        ]
        
        # Count indicators
        indicator_count = 0
        timestamp_count = 0
        url_count = 0
        
        for line in lines:
            line_lower = line.lower()
            
            # Check for show notes indicators
            if any(indicator in line_lower for indicator in show_notes_indicators):
                indicator_count += 1
            
            # Check for timestamps
            if re.search(r'\[?\d{1,2}:\d{2}(?::\d{2})?\]?', line):
                timestamp_count += 1
            
            # Check for URLs
            if re.search(r'https?://', line):
                url_count += 1
        
        # If we see multiple indicators, it's likely show notes
        if indicator_count >= 2 or timestamp_count >= 5 or url_count >= 5:
            return True
        
        # Check if most lines are very short (typical of show notes)
        short_lines = sum(1 for line in lines if len(line.strip()) < 50)
        if short_lines > len(lines) * 0.7:
            return True
        
        return False