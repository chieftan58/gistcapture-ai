"""
Comprehensive transcript source finder with multiple fallbacks.
Searches across various platforms and APIs for existing transcripts.
"""

import re
import os
import asyncio
from typing import Optional, List, Dict, Tuple
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime

from ..utils.logging import get_logger
from ..models import Episode, TranscriptSource

logger = get_logger(__name__)


class ComprehensiveTranscriptFinder:
    """Find transcripts from multiple sources with intelligent fallbacks"""
    
    def __init__(self):
        self.session = None
        self._session_created = False
        
        # API keys for various services
        self.assemblyai_key = os.getenv('ASSEMBLYAI_API_KEY')
        self.rev_ai_key = os.getenv('REV_AI_API_KEY')
        self.deepgram_key = os.getenv('DEEPGRAM_API_KEY')
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if not self._session_created or self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
            self._session_created = True
        return self.session
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
            self._session_created = False
    
    async def find_transcript(self, episode: Episode) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """
        Find transcript from all available sources.
        Returns (transcript_text, source) tuple.
        """
        
        # 1. Check transcript aggregators
        transcript = await self._check_transcript_aggregators(episode)
        if transcript:
            return transcript, TranscriptSource.API
        
        # 2. Check podcast website with advanced scraping
        transcript = await self._advanced_website_scraping(episode)
        if transcript:
            return transcript, TranscriptSource.SCRAPED
        
        # 3. Check third-party transcript services
        transcript = await self._check_transcript_services(episode)
        if transcript:
            return transcript, TranscriptSource.API
        
        # 4. Check show notes and descriptions
        transcript = await self._extract_from_show_notes(episode)
        if transcript:
            return transcript, TranscriptSource.SCRAPED
        
        # 5. Check social media (Twitter threads, etc.)
        transcript = await self._check_social_media(episode)
        if transcript:
            return transcript, TranscriptSource.SCRAPED
        
        # 6. Check archive.org
        transcript = await self._check_archive_org(episode)
        if transcript:
            return transcript, TranscriptSource.SCRAPED
        
        return None, None
    
    async def _check_transcript_aggregators(self, episode: Episode) -> Optional[str]:
        """Check transcript aggregator services"""
        aggregators = [
            self._check_happyscribe,
            self._check_sonix,
            self._check_trint,
            self._check_otter_ai,
            self._check_temi,
        ]
        
        for aggregator in aggregators:
            try:
                transcript = await aggregator(episode)
                if transcript:
                    logger.info(f"Found transcript from {aggregator.__name__}")
                    return transcript
            except Exception as e:
                logger.debug(f"Error checking {aggregator.__name__}: {e}")
        
        return None
    
    async def _advanced_website_scraping(self, episode: Episode) -> Optional[str]:
        """Advanced website scraping with multiple strategies"""
        if not episode.link:
            return None
        
        try:
            session = await self._get_session()
            
            # Try with different user agents
            user_agents = [
                'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            ]
            
            for ua in user_agents:
                headers = {'User-Agent': ua}
                async with session.get(episode.link, headers=headers) as response:
                    if response.status != 200:
                        continue
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    # Advanced selectors for transcripts
                    selectors = [
                        # Common transcript containers
                        'div.transcript-content',
                        'div.episode-transcript',
                        'div.show-notes-transcript',
                        'article.transcript',
                        'section.transcript',
                        
                        # Platform-specific
                        'div.substack-post-content',  # Substack
                        'div.entry-content',  # WordPress
                        'div.post-content',  # Generic blog
                        'div.notion-page-content',  # Notion
                        
                        # ID-based
                        'div#transcript',
                        'div#episode-transcript',
                        'div#show-transcript',
                        
                        # Data attributes
                        '[data-transcript]',
                        '[data-content-type="transcript"]',
                        
                        # Accordion/collapsible content
                        'div.accordion-content',
                        'div.collapsible-content',
                        'details.transcript',
                    ]
                    
                    for selector in selectors:
                        elements = soup.select(selector)
                        for element in elements:
                            text = element.get_text(separator='\n', strip=True)
                            if self._is_likely_transcript(text):
                                return self._clean_transcript(text)
                    
                    # Check for "View Transcript" or similar links
                    transcript_link = await self._find_transcript_link(soup, episode.link)
                    if transcript_link:
                        transcript = await self._fetch_from_url(transcript_link)
                        if transcript:
                            return transcript
                    
        except Exception as e:
            logger.debug(f"Advanced scraping failed: {e}")
        
        return None
    
    async def _check_transcript_services(self, episode: Episode) -> Optional[str]:
        """Check third-party transcript services"""
        services = []
        
        # AssemblyAI
        if self.assemblyai_key:
            services.append(self._check_assemblyai)
        
        # Rev.ai
        if self.rev_ai_key:
            services.append(self._check_rev_ai)
        
        # Deepgram
        if self.deepgram_key:
            services.append(self._check_deepgram)
        
        for service in services:
            try:
                transcript = await service(episode)
                if transcript:
                    return transcript
            except Exception as e:
                logger.debug(f"Service check failed: {e}")
        
        return None
    
    async def _extract_from_show_notes(self, episode: Episode) -> Optional[str]:
        """Extract transcript from show notes/description"""
        if not episode.description:
            return None
        
        # Check if description contains a full transcript
        if len(episode.description) > 5000 and self._is_likely_transcript(episode.description):
            return self._clean_transcript(episode.description)
        
        # Look for transcript links in description
        transcript_patterns = [
            r'transcript[:\s]+(?:https?://[^\s]+)',
            r'full\s+transcript[:\s]+(?:https?://[^\s]+)',
            r'read\s+more[:\s]+(?:https?://[^\s]+)',
            r'show\s+notes[:\s]+(?:https?://[^\s]+)',
        ]
        
        for pattern in transcript_patterns:
            match = re.search(pattern, episode.description, re.I)
            if match:
                url = match.group(1)
                transcript = await self._fetch_from_url(url)
                if transcript:
                    return transcript
        
        return None
    
    async def _check_social_media(self, episode: Episode) -> Optional[str]:
        """Check social media for transcript threads"""
        # This would check:
        # - Twitter/X threads
        # - LinkedIn posts
        # - Medium articles
        # - Reddit discussions
        # Placeholder for now
        return None
    
    async def _check_archive_org(self, episode: Episode) -> Optional[str]:
        """Check Internet Archive for transcripts"""
        # This would search archive.org for transcripts
        # Placeholder for now
        return None
    
    async def _find_transcript_link(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find links to transcript pages"""
        import urllib.parse
        
        link_patterns = [
            'transcript', 'show notes', 'read more', 'full text',
            'view transcript', 'episode notes', 'detailed notes'
        ]
        
        for link in soup.find_all('a', href=True):
            link_text = link.get_text().lower()
            if any(pattern in link_text for pattern in link_patterns):
                href = link['href']
                # Make absolute URL
                full_url = urllib.parse.urljoin(base_url, href)
                return full_url
        
        return None
    
    async def _fetch_from_url(self, url: str) -> Optional[str]:
        """Fetch content from URL"""
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    if content.strip().startswith('<'):
                        # It's HTML, extract text
                        soup = BeautifulSoup(content, 'html.parser')
                        return soup.get_text(separator='\n', strip=True)
                    return content
        except Exception as e:
            logger.debug(f"Failed to fetch from URL: {e}")
        return None
    
    def _is_likely_transcript(self, text: str) -> bool:
        """Check if text is likely a transcript"""
        if not text or len(text) < 1000:
            return False
        
        # Check for dialogue patterns
        dialogue_patterns = [
            r'\n\s*\w+\s*:\s*',  # Name: dialogue
            r'\[\d+:\d+:\d+\]',  # Timestamps
            r'\[\d+:\d+\]',      # Shorter timestamps
            r'Speaker \d+:',     # Speaker 1: etc
            r'\(\d+:\d+\)',      # (00:00) timestamps
        ]
        
        pattern_count = 0
        for pattern in dialogue_patterns:
            if re.search(pattern, text):
                pattern_count += 1
        
        # Check word count
        word_count = len(text.split())
        
        # Heuristics for transcript detection
        if pattern_count >= 2:
            return True
        if word_count > 2000 and pattern_count >= 1:
            return True
        if word_count > 5000:
            # Long text, check for conversational patterns
            conversation_indicators = ['said', 'asked', 'replied', 'think', 'know', 'yeah', 'right']
            indicator_count = sum(1 for word in conversation_indicators if word in text.lower())
            if indicator_count > 20:
                return True
        
        return False
    
    def _clean_transcript(self, text: str) -> str:
        """Clean transcript text"""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Remove common non-transcript elements
        remove_patterns = [
            r'Share\s+on\s+\w+',
            r'Subscribe\s+to\s+\w+',
            r'Download\s+Episode',
            r'Listen\s+on\s+\w+',
            r'Follow\s+us\s+on\s+\w+',
        ]
        
        for pattern in remove_patterns:
            text = re.sub(pattern, '', text, flags=re.I)
        
        return text.strip()
    
    # Placeholder methods for various services
    async def _check_happyscribe(self, episode: Episode) -> Optional[str]:
        """Check HappyScribe for transcripts"""
        # Would implement HappyScribe API
        return None
    
    async def _check_sonix(self, episode: Episode) -> Optional[str]:
        """Check Sonix for transcripts"""
        # Would implement Sonix API
        return None
    
    async def _check_trint(self, episode: Episode) -> Optional[str]:
        """Check Trint for transcripts"""
        # Would implement Trint API
        return None
    
    async def _check_otter_ai(self, episode: Episode) -> Optional[str]:
        """Check Otter.ai for transcripts"""
        # Would implement Otter.ai API
        return None
    
    async def _check_temi(self, episode: Episode) -> Optional[str]:
        """Check Temi for transcripts"""
        # Would implement Temi API
        return None
    
    async def _check_assemblyai(self, episode: Episode) -> Optional[str]:
        """Check AssemblyAI for existing transcripts"""
        if not self.assemblyai_key:
            return None
        
        try:
            session = await self._get_session()
            headers = {
                'authorization': self.assemblyai_key,
                'content-type': 'application/json'
            }
            
            # First, check if we've already transcribed this episode
            # AssemblyAI doesn't have a direct search API, but we could store transcript IDs
            # For now, we'll skip this check
            
            # If you have a transcript ID stored, you can retrieve it like this:
            # transcript_id = get_stored_transcript_id(episode)  # Your storage logic
            # if transcript_id:
            #     url = f'https://api.assemblyai.com/v2/transcript/{transcript_id}'
            #     async with session.get(url, headers=headers) as response:
            #         if response.status == 200:
            #             data = await response.json()
            #             if data.get('status') == 'completed':
            #                 return data.get('text')
            
            logger.debug("AssemblyAI check: No existing transcript found")
            return None
            
        except Exception as e:
            logger.debug(f"AssemblyAI check failed: {e}")
            return None
    
    async def _check_rev_ai(self, episode: Episode) -> Optional[str]:
        """Check Rev.ai for transcripts"""
        if not self.rev_ai_key:
            return None
        
        try:
            session = await self._get_session()
            headers = {
                'Authorization': f'Bearer {self.rev_ai_key}',
                'Content-Type': 'application/json'
            }
            
            # Rev.ai allows listing jobs, so we can search for existing transcripts
            # by metadata if we stored episode info when creating the job
            url = 'https://api.rev.ai/speechtotext/v1/jobs'
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    jobs = await response.json()
                    
                    # Search for a job that matches this episode
                    # This assumes you store episode info in the job's metadata or name
                    for job in jobs:
                        if job.get('status') == 'completed':
                            # Check if job metadata matches episode
                            job_name = job.get('name', '')
                            if episode.title in job_name or episode.guid in job_name:
                                # Get the transcript
                                job_id = job['id']
                                transcript_url = f'https://api.rev.ai/speechtotext/v1/jobs/{job_id}/transcript'
                                
                                async with session.get(transcript_url, headers=headers) as trans_response:
                                    if trans_response.status == 200:
                                        data = await trans_response.json()
                                        # Rev.ai returns monologues, we need to extract text
                                        transcript_parts = []
                                        for monologue in data.get('monologues', []):
                                            for element in monologue.get('elements', []):
                                                if element['type'] == 'text':
                                                    transcript_parts.append(element['value'])
                                        
                                        if transcript_parts:
                                            return ' '.join(transcript_parts)
            
            logger.debug("Rev.ai check: No existing transcript found")
            return None
            
        except Exception as e:
            logger.debug(f"Rev.ai check failed: {e}")
            return None
    
    async def _check_deepgram(self, episode: Episode) -> Optional[str]:
        """Check Deepgram for transcripts"""
        if not self.deepgram_key:
            return None
        
        try:
            session = await self._get_session()
            headers = {
                'Authorization': f'Token {self.deepgram_key}',
                'Content-Type': 'application/json'
            }
            
            # Deepgram doesn't provide a way to list past transcriptions
            # You would need to implement your own storage of request IDs
            # For now, we'll return None
            
            # If you stored request IDs, you could retrieve like this:
            # request_id = get_stored_deepgram_request_id(episode)
            # if request_id:
            #     url = f'https://api.deepgram.com/v1/listen/{request_id}'
            #     async with session.get(url, headers=headers) as response:
            #         if response.status == 200:
            #             data = await response.json()
            #             # Extract transcript from Deepgram response format
            #             if 'results' in data and 'channels' in data['results']:
            #                 transcript = data['results']['channels'][0]['alternatives'][0]['transcript']
            #                 return transcript
            
            logger.debug("Deepgram check: No existing transcript found")
            return None
            
        except Exception as e:
            logger.debug(f"Deepgram check failed: {e}")
            return None
    
    async def transcribe_with_service(self, audio_url: str, service: str = 'assemblyai') -> Optional[str]:
        """Transcribe audio using a specific service"""
        if service == 'assemblyai' and self.assemblyai_key:
            return await self._transcribe_with_assemblyai(audio_url)
        elif service == 'rev' and self.rev_ai_key:
            return await self._transcribe_with_rev_ai(audio_url)
        elif service == 'deepgram' and self.deepgram_key:
            return await self._transcribe_with_deepgram(audio_url)
        else:
            logger.warning(f"Service {service} not available or not configured")
            return None
    
    async def _transcribe_with_assemblyai(self, audio_url: str) -> Optional[str]:
        """Transcribe audio using AssemblyAI"""
        try:
            session = await self._get_session()
            headers = {
                'authorization': self.assemblyai_key,
                'content-type': 'application/json'
            }
            
            # Submit audio for transcription
            data = {
                'audio_url': audio_url,
                'language_detection': True,
                'auto_highlights': True,
                'speaker_labels': True
            }
            
            async with session.post('https://api.assemblyai.com/v2/transcript', 
                                   headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    transcript_id = result['id']
                    
                    # Poll for completion
                    while True:
                        async with session.get(f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
                                             headers=headers) as poll_response:
                            if poll_response.status == 200:
                                poll_data = await poll_response.json()
                                status = poll_data['status']
                                
                                if status == 'completed':
                                    return poll_data['text']
                                elif status == 'error':
                                    logger.error(f"AssemblyAI transcription error: {poll_data.get('error')}")
                                    return None
                                else:
                                    # Still processing
                                    await asyncio.sleep(5)
            
            return None
            
        except Exception as e:
            logger.error(f"AssemblyAI transcription failed: {e}")
            return None
    
    async def _transcribe_with_rev_ai(self, audio_url: str) -> Optional[str]:
        """Transcribe audio using Rev.ai"""
        try:
            session = await self._get_session()
            headers = {
                'Authorization': f'Bearer {self.rev_ai_key}',
                'Content-Type': 'application/json'
            }
            
            # Submit job
            data = {
                'media_url': audio_url,
                'metadata': f'Episode transcription {datetime.now().isoformat()}'
            }
            
            async with session.post('https://api.rev.ai/speechtotext/v1/jobs',
                                   headers=headers, json=data) as response:
                if response.status == 200:
                    job = await response.json()
                    job_id = job['id']
                    
                    # Poll for completion
                    while True:
                        async with session.get(f'https://api.rev.ai/speechtotext/v1/jobs/{job_id}',
                                             headers=headers) as poll_response:
                            if poll_response.status == 200:
                                poll_data = await poll_response.json()
                                status = poll_data['status']
                                
                                if status == 'completed':
                                    # Get transcript
                                    transcript_url = f'https://api.rev.ai/speechtotext/v1/jobs/{job_id}/transcript'
                                    async with session.get(transcript_url, headers=headers) as trans_response:
                                        if trans_response.status == 200:
                                            trans_data = await trans_response.json()
                                            # Extract text from monologues
                                            transcript_parts = []
                                            for monologue in trans_data.get('monologues', []):
                                                for element in monologue.get('elements', []):
                                                    if element['type'] == 'text':
                                                        transcript_parts.append(element['value'])
                                            return ' '.join(transcript_parts)
                                elif status == 'failed':
                                    logger.error(f"Rev.ai transcription failed")
                                    return None
                                else:
                                    # Still processing
                                    await asyncio.sleep(5)
            
            return None
            
        except Exception as e:
            logger.error(f"Rev.ai transcription failed: {e}")
            return None
    
    async def _transcribe_with_deepgram(self, audio_url: str) -> Optional[str]:
        """Transcribe audio using Deepgram"""
        try:
            session = await self._get_session()
            headers = {
                'Authorization': f'Token {self.deepgram_key}',
                'Content-Type': 'application/json'
            }
            
            # Deepgram can do real-time transcription from URL
            data = {
                'url': audio_url
            }
            
            # Add parameters for better transcription
            params = {
                'model': 'general',
                'punctuate': 'true',
                'profanity_filter': 'false',
                'diarize': 'true',
                'smart_format': 'true'
            }
            
            url = 'https://api.deepgram.com/v1/listen?' + '&'.join(f'{k}={v}' for k, v in params.items())
            
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    # Extract transcript
                    if 'results' in result and 'channels' in result['results']:
                        channels = result['results']['channels']
                        if channels and len(channels) > 0:
                            alternatives = channels[0].get('alternatives', [])
                            if alternatives:
                                return alternatives[0]['transcript']
            
            return None
            
        except Exception as e:
            logger.error(f"Deepgram transcription failed: {e}")
            return None