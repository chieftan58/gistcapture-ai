"""
Special downloader for American Optimist that bypasses Cloudflare
"""

import asyncio
import aiohttp
import subprocess
import logging
from pathlib import Path
from typing import Optional
import re
import json
from datetime import datetime

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AmericanOptimistDownloader:
    """Special download handler for American Optimist episodes"""
    
    @staticmethod
    async def download_episode(episode: Episode, output_path: Path) -> bool:
        """
        Download American Optimist episode using alternative methods
        Since Substack is blocked, we'll try multiple approaches
        """
        logger.info(f"🎯 Special American Optimist download handler for: {episode.title}")
        
        # Extract episode number
        ep_match = re.search(r'Ep\.?\s*(\d+)', episode.title, re.IGNORECASE)
        ep_num = ep_match.group(1) if ep_match else None
        
        if not ep_num:
            logger.warning(f"Could not extract episode number from: {episode.title}")
            return False
        
        # Method 1: Try direct podcast CDNs that might have it
        cdn_urls = await AmericanOptimistDownloader._find_cdn_urls(episode, ep_num)
        for url in cdn_urls:
            if await AmericanOptimistDownloader._try_download(url, output_path):
                logger.info(f"✅ Downloaded from CDN: {url}")
                return True
        
        # Method 2: Try alternative podcast platforms
        alt_urls = await AmericanOptimistDownloader._find_alternative_platforms(episode, ep_num)
        for url in alt_urls:
            if await AmericanOptimistDownloader._try_download(url, output_path):
                logger.info(f"✅ Downloaded from alternative platform: {url}")
                return True
        
        # Method 3: Try web scraping for audio URL
        scraped_url = await AmericanOptimistDownloader._scrape_for_audio(episode)
        if scraped_url and await AmericanOptimistDownloader._try_download(scraped_url, output_path):
            logger.info(f"✅ Downloaded from scraped URL: {scraped_url}")
            return True
        
        # Method 4: Last resort - use yt-dlp with specific YouTube search
        youtube_url = await AmericanOptimistDownloader._find_on_youtube(episode, ep_num)
        if youtube_url:
            if await AmericanOptimistDownloader._download_with_ytdlp(youtube_url, output_path):
                logger.info(f"✅ Downloaded from YouTube: {youtube_url}")
                return True
        
        logger.error(f"❌ All download methods failed for: {episode.title}")
        return False
    
    @staticmethod
    async def _find_cdn_urls(episode: Episode, ep_num: str) -> list:
        """Find potential CDN URLs"""
        urls = []
        
        # Common podcast CDN patterns
        # Try various CDN patterns that podcasts often use
        patterns = [
            f"https://traffic.megaphone.fm/JOE{ep_num.zfill(4)}.mp3",
            f"https://dcs.megaphone.fm/JOE{ep_num.zfill(4)}.mp3",
            f"https://chrt.fm/track/968G3/traffic.megaphone.fm/JOE{ep_num.zfill(4)}.mp3",
            f"https://pdst.fm/e/americanoptimist/episode{ep_num}.mp3",
            f"https://media.transistor.fm/americanoptimist/{ep_num}.mp3"
        ]
        
        return patterns
    
    @staticmethod
    async def _find_alternative_platforms(episode: Episode, ep_num: str) -> list:
        """Find URLs from alternative platforms"""
        urls = []
        
        # Try to find on platforms that might mirror the content
        # This would need actual API integration or web scraping
        
        return urls
    
    @staticmethod
    async def _scrape_for_audio(episode: Episode) -> Optional[str]:
        """Try to scrape for audio URL from various sources"""
        # This would implement web scraping for audio URLs
        # from podcast aggregator sites
        return None
    
    @staticmethod
    async def _find_on_youtube(episode: Episode, ep_num: str) -> Optional[str]:
        """Find the episode on YouTube using specific searches"""
        # Extract guest name for better search
        title_clean = re.sub(r'^Ep\.?\s*\d+[:\s]+', '', episode.title, flags=re.IGNORECASE)
        guest_match = re.search(r'^([^:]+)(?:\s+on\s+|\s*:)', title_clean)
        guest = guest_match.group(1).strip() if guest_match else None
        
        # Build very specific search queries
        queries = []
        if guest:
            queries.append(f'"Joe Lonsdale" "American Optimist" "{guest}" episode {ep_num}')
        queries.append(f'"American Optimist Episode {ep_num}" "Joe Lonsdale"')
        queries.append(f'Joe Lonsdale American Optimist Ep {ep_num} full episode')
        
        # Use direct YouTube URLs if we know them
        # These would be manually curated for known episodes
        known_episodes = {
            "118": "https://www.youtube.com/watch?v=EXAMPLE118",  # Would need real URLs
            "117": "https://www.youtube.com/watch?v=EXAMPLE117",
            # etc.
        }
        
        if ep_num in known_episodes:
            return known_episodes[ep_num]
        
        # Otherwise, return a search URL that yt-dlp can handle
        # But this requires yt-dlp to work without bot detection
        return f"ytsearch1:{queries[0]}"
    
    @staticmethod
    async def _try_download(url: str, output_path: Path) -> bool:
        """Try to download from a URL"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Accept': 'audio/*,*/*'
                }
                
                async with session.get(url, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        content = await response.read()
                        if len(content) > 1_000_000:  # At least 1MB
                            output_path.write_bytes(content)
                            return True
        except Exception as e:
            logger.debug(f"Download failed from {url}: {e}")
        
        return False
    
    @staticmethod
    async def _download_with_ytdlp(url: str, output_path: Path) -> bool:
        """Download using yt-dlp"""
        try:
            cmd = [
                'python', '-m', 'yt_dlp',
                '-f', 'bestaudio/best',
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '192K',
                '-o', str(output_path.with_suffix('')),  # yt-dlp adds extension
                '--quiet',
                '--no-warnings',
                url
            ]
            
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=120)
            
            # Check if file was created
            if output_path.exists():
                return True
            elif output_path.with_suffix('.mp3').exists():
                # yt-dlp might have added .mp3
                output_path.with_suffix('.mp3').rename(output_path)
                return True
            
            if stderr:
                logger.error(f"yt-dlp error: {stderr.decode()}")
            
        except Exception as e:
            logger.error(f"yt-dlp download failed: {e}")
        
        return False
    
    @staticmethod
    def is_american_optimist(episode: Episode) -> bool:
        """Check if this is an American Optimist episode that needs special handling"""
        return (
            episode.podcast == "American Optimist" and
            episode.audio_url and
            "substack.com" in episode.audio_url
        )