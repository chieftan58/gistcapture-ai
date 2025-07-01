"""
Redirect chain resolver to find direct CDN URLs for podcast audio files.
Bypasses tracking/analytics redirects to get to the actual audio file.
"""

import asyncio
import aiohttp
from typing import Optional, List, Tuple
from urllib.parse import urlparse
import logging

from ..utils.logging import get_logger

logger = get_logger(__name__)


class RedirectResolver:
    """Resolves redirect chains to find direct CDN URLs"""
    
    def __init__(self):
        self.max_redirects = 10
        self.timeout = 20
        self.session = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            # Don't follow redirects automatically - we want to inspect each one
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Accept': 'audio/mpeg, audio/mp4, audio/*',
                    'Accept-Encoding': 'identity',  # Don't use compression for audio
                    'Range': 'bytes=0-1',  # Only get first byte to check headers
                }
            )
        return self.session
    
    async def resolve_redirect_chain(self, url: str) -> Tuple[str, List[str]]:
        """
        Follow redirect chain to find the final CDN URL.
        
        Args:
            url: The starting URL (possibly with redirects)
            
        Returns:
            Tuple of (final_url, redirect_chain)
        """
        session = await self._get_session()
        redirect_chain = []
        current_url = url
        
        for i in range(self.max_redirects):
            try:
                # Make HEAD request first (faster)
                async with session.head(
                    current_url, 
                    allow_redirects=False,
                    ssl=False
                ) as response:
                    
                    redirect_chain.append({
                        'url': current_url,
                        'status': response.status,
                        'content_type': response.headers.get('Content-Type', ''),
                        'location': response.headers.get('Location', '')
                    })
                    
                    # Check if this is audio content (end of chain)
                    content_type = response.headers.get('Content-Type', '').lower()
                    if any(audio_type in content_type for audio_type in ['audio/', 'application/octet-stream']):
                        logger.info(f"✅ Found direct audio URL after {i} redirects")
                        return current_url, redirect_chain
                    
                    # Check for redirect
                    if response.status in [301, 302, 303, 307, 308]:
                        location = response.headers.get('Location')
                        if not location:
                            logger.warning(f"Redirect without Location header at: {current_url}")
                            break
                            
                        # Handle relative redirects
                        if not location.startswith('http'):
                            parsed = urlparse(current_url)
                            base = f"{parsed.scheme}://{parsed.netloc}"
                            location = base + location if location.startswith('/') else base + '/' + location
                        
                        logger.debug(f"Following redirect: {current_url[:50]}... -> {location[:50]}...")
                        current_url = location
                        continue
                    
                    # If not a redirect and not audio, might be an error
                    if response.status >= 400:
                        logger.warning(f"HTTP {response.status} at: {current_url}")
                        break
                    
                    # Success but not audio - might be HTML page
                    if response.status == 200:
                        logger.warning(f"HTTP 200 but not audio content at: {current_url}")
                        # Try GET request to check actual content
                        async with session.get(
                            current_url,
                            allow_redirects=False,
                            headers={'Range': 'bytes=0-1000'}  # Get first 1KB
                        ) as get_response:
                            content = await get_response.read()
                            
                            # Check if it's actually audio
                            if self._is_audio_content(content):
                                logger.info(f"✅ Confirmed audio content at: {current_url}")
                                return current_url, redirect_chain
                        break
                    
            except asyncio.TimeoutError:
                logger.error(f"Timeout resolving redirect at: {current_url}")
                break
            except Exception as e:
                logger.error(f"Error resolving redirect: {e}")
                break
        
        logger.warning(f"Failed to find direct CDN URL after {len(redirect_chain)} attempts")
        return current_url, redirect_chain
    
    def _is_audio_content(self, content: bytes) -> bool:
        """Check if content bytes look like audio"""
        if not content or len(content) < 4:
            return False
            
        # Audio file signatures
        audio_signatures = [
            b'ID3',         # MP3 with ID3
            b'\xFF\xFB',    # MP3
            b'\xFF\xF3',    # MP3
            b'\xFF\xF2',    # MP3
            b'ftyp',        # MP4/M4A (at offset 4)
            b'OggS',        # Ogg
            b'RIFF',        # WAV
            b'fLaC',        # FLAC
        ]
        
        # Check header
        header = content[:16]
        for sig in audio_signatures:
            if sig in header:
                return True
                
        # Check for HTML (definitely not audio)
        if header.lower().startswith(b'<!doctype') or header.lower().startswith(b'<html'):
            return False
            
        return False
    
    async def find_all_cdn_alternatives(self, url: str) -> List[str]:
        """
        Find CDN alternatives by following redirects and generating variations.
        
        Args:
            url: The starting URL
            
        Returns:
            List of alternative CDN URLs
        """
        alternatives = []
        
        # First, resolve redirects to get the actual CDN URL
        final_url, redirect_chain = await self.resolve_redirect_chain(url)
        
        # Add the final URL
        if final_url != url:
            alternatives.append(final_url)
        
        # Extract any CDN URLs from the redirect chain
        for redirect in redirect_chain:
            redirect_url = redirect['url']
            parsed = urlparse(redirect_url)
            
            # Look for CDN domains
            cdn_domains = [
                'cloudfront.net',
                'amazonaws.com',
                'akamaized.net',
                'fastly.net',
                'cloudflare.com',
                'azureedge.net',
                'stackpathdns.com',
                'bunnycdn.com',
                'cdn77.com',
                'keycdn.com'
            ]
            
            if any(cdn in parsed.netloc for cdn in cdn_domains):
                alternatives.append(redirect_url)
        
        # Generate CDN variations from the final URL
        final_parsed = urlparse(final_url)
        
        # Common CDN patterns
        cdn_variations = {
            'cloudfront.net': ['d1', 'd2', 'd3', 'd4'],
            'amazonaws.com': ['s3', 's3-us-west-1', 's3-us-west-2', 's3-us-east-1', 's3-eu-west-1'],
            'akamaized.net': ['media', 'audio', 'content', 'cdn'],
        }
        
        for domain, prefixes in cdn_variations.items():
            if domain in final_parsed.netloc:
                for prefix in prefixes:
                    # Replace subdomain
                    parts = final_parsed.netloc.split('.')
                    if len(parts) > 2:
                        parts[0] = prefix
                        new_netloc = '.'.join(parts)
                        new_url = final_url.replace(final_parsed.netloc, new_netloc)
                        if new_url not in alternatives:
                            alternatives.append(new_url)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_alternatives = []
        for alt in alternatives:
            if alt not in seen and alt != url:
                seen.add(alt)
                unique_alternatives.append(alt)
        
        logger.info(f"Found {len(unique_alternatives)} CDN alternatives for URL")
        return unique_alternatives