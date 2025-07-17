"""YouTube download strategy - bypasses most protections"""

import asyncio
import subprocess
import os
import re
from pathlib import Path
from typing import Optional, Tuple, Dict
from . import DownloadStrategy
from ..utils.logging import get_logger

logger = get_logger(__name__)


class YouTubeStrategy(DownloadStrategy):
    """Download from YouTube - bypasses Cloudflare and most protections"""
    
    # Known YouTube URLs for specific episodes
    EPISODE_MAPPINGS = {
        # American Optimist
        "American Optimist|Marc Andreessen": "https://www.youtube.com/watch?v=pRoKi4VL_5s",
        "American Optimist|Dave Rubin": "https://www.youtube.com/watch?v=w1FRqBOxS8g", 
        "American Optimist|Scott Wu": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",
        "American Optimist|Flying Cars": "https://www.youtube.com/watch?v=TVg_DK8-kMw",
        "American Optimist|Boris Sofman": "https://www.youtube.com/watch?v=l2sdZ1IyZx8",
        "American Optimist|Waymo": "https://www.youtube.com/watch?v=l2sdZ1IyZx8",
        
        # Dwarkesh Podcast
        "Dwarkesh Podcast|Stephen Kotkin": "https://www.youtube.com/watch?v=YMfd3EoHfPI",
        "Dwarkesh Podcast|Stalin": "https://www.youtube.com/watch?v=YMfd3EoHfPI",
        
        # Add more mappings as discovered
    }
    
    # YouTube channels for podcasts
    YOUTUBE_CHANNELS = {
        "American Optimist": "americanoptimist",
        "Dwarkesh Podcast": "DwarkeshPatel",
        "The Drive": "peterattiamd",
        "The Tim Ferriss Show": "TimFerriss",
        "Lex Fridman": "lexfridman",
        "Huberman Lab": "hubermanlab",
    }
    
    @property
    def name(self) -> str:
        return "youtube"
    
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Priority for Cloudflare-protected podcasts and YouTube URLs"""
        # Always try YouTube for known problematic podcasts
        if podcast_name in ["American Optimist", "Dwarkesh Podcast"]:
            return True
        
        # Handle YouTube URLs
        return "youtube.com" in url or "youtu.be" in url
    
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """Download from YouTube using yt-dlp"""
        podcast = episode_info.get('podcast', '')
        title = episode_info.get('title', '')
        
        # First try to find YouTube URL
        youtube_url = await self._find_youtube_url(podcast, title, url)
        if not youtube_url:
            return False, "No YouTube URL found for this episode"
        
        logger.info(f"🎥 Found YouTube URL: {youtube_url}")
        
        # Try downloading with yt-dlp Python module
        try:
            import yt_dlp
        except ImportError:
            return False, "yt-dlp module not found. Please install with: pip install yt-dlp"
            
        # Use cookie manager to get cookie file
        from ..utils.cookie_manager import cookie_manager
        cookie_file = cookie_manager.get_cookie_file('youtube')
        
        # Configure yt-dlp options
        base_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
            'outtmpl': str(output_path.with_suffix('.%(ext)s')),
            'extractaudio': True,
            'audioformat': 'mp3',
            'audioquality': '192K',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
        }
        
        approaches = [
            # First try with cookie file
            {
                'name': 'cookie_file',
                'opts': {**base_opts, 'cookiefile': str(cookie_file)} if cookie_file else None
            },
            
            # Try with browser cookies
            {'name': 'firefox', 'opts': {**base_opts, 'cookiesfrombrowser': ('firefox',)}},
            {'name': 'chrome', 'opts': {**base_opts, 'cookiesfrombrowser': ('chrome',)}},
            {'name': 'chromium', 'opts': {**base_opts, 'cookiesfrombrowser': ('chromium',)}},
            {'name': 'edge', 'opts': {**base_opts, 'cookiesfrombrowser': ('edge',)}},
            {'name': 'safari', 'opts': {**base_opts, 'cookiesfrombrowser': ('safari',)}},
            
            # Try without cookies
            {'name': 'no_cookies', 'opts': base_opts},
        ]
        
        last_error = None
        for i, approach in enumerate(approaches):
            if approach['opts'] is None:
                continue
                
            try:
                logger.info(f"🎬 Attempt {i+1}: {approach['name']}")
                
                # Run yt-dlp in executor to avoid blocking
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, 
                    self._download_with_ytdlp_sync, 
                    youtube_url, 
                    approach['opts']
                )
                
                if result:
                    # Check if file was created and rename if needed
                    for suffix in ['.mp3', '.m4a', '.opus', '.webm']:
                        potential_path = output_path.with_suffix(suffix)
                        if potential_path.exists():
                            file_size = potential_path.stat().st_size
                            if file_size > 1000:  # At least 1KB
                                if suffix != '.mp3':
                                    # Convert to mp3 if needed
                                    try:
                                        convert_cmd = ['ffmpeg', '-i', str(potential_path), '-acodec', 'mp3', 
                                                     '-ab', '192k', str(output_path), '-y']
                                        subprocess.run(convert_cmd, capture_output=True, check=True)
                                        potential_path.unlink()  # Remove original file
                                    except:
                                        # If conversion fails, just rename
                                        potential_path.rename(output_path)
                                else:
                                    if potential_path != output_path:
                                        potential_path.rename(output_path)
                                
                                logger.info(f"✅ YouTube download successful with {approach['name']} ({file_size / 1024 / 1024:.1f} MB)")
                                return True, None
                            else:
                                potential_path.unlink()  # Remove empty file
                                logger.warning(f"❌ Downloaded file too small: {file_size} bytes")
                        
            except Exception as e:
                last_error = str(e)
                logger.warning(f"❌ Approach {i+1} ({approach['name']}) exception: {last_error}")
                continue
        
        # All approaches failed
        error_msg = "YouTube download failed - may need authentication"
        if last_error:
            if "Sign in" in last_error or "bot" in last_error.lower():
                error_msg = "YouTube requires sign-in - please login to YouTube in Firefox/Chrome"
        
        return False, error_msg
    
    async def _find_youtube_url(self, podcast: str, title: str, original_url: str) -> Optional[str]:
        """Find YouTube URL for the episode"""
        # If already a YouTube URL, return it
        if "youtube.com" in original_url or "youtu.be" in original_url:
            return original_url
        
        # Check known mappings with stricter matching
        # First try exact podcast + key terms match
        for key, url in self.EPISODE_MAPPINGS.items():
            key_parts = key.split('|')
            if len(key_parts) >= 2:
                key_podcast = key_parts[0]
                key_identifier = key_parts[1].lower()
                
                # Must match podcast name exactly
                if key_podcast.lower() == podcast.lower():
                    # Check if key identifier is in title
                    if key_identifier in title.lower():
                        logger.info(f"✅ Found known YouTube mapping: {key}")
                        return url
        
        # For American Optimist, try YouTube search API
        if podcast == "American Optimist":
            youtube_url = await self._search_youtube_for_episode(podcast, title)
            if youtube_url:
                return youtube_url
        
        # Build search query
        channel = self.YOUTUBE_CHANNELS.get(podcast, "")
        if channel:
            search_terms = f"{channel} {title}"
        else:
            search_terms = f"{podcast} {title} full episode"
        
        logger.info(f"🔍 Would search YouTube for: {search_terms}")
        
        # TODO: Implement actual YouTube search for other podcasts
        # For now, return None - in production, this would search YouTube
        return None
    
    def _download_with_ytdlp_sync(self, url: str, ydl_opts: dict) -> bool:
        """Synchronous yt-dlp download helper for use in executor"""
        try:
            import yt_dlp
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            return True
            
        except Exception as e:
            logger.debug(f"yt-dlp sync download failed: {e}")
            return False
    
    async def _search_youtube_for_episode(self, podcast: str, title: str) -> Optional[str]:
        """Search YouTube for American Optimist episodes using YouTube Data API or yt-dlp"""
        # Extract episode number if present
        ep_match = re.search(r'Ep\s*(\d+)', title, re.IGNORECASE)
        ep_number = ep_match.group(1) if ep_match else None
        
        # Try YouTube Data API if available
        youtube_api_key = os.getenv('YOUTUBE_API_KEY')
        if youtube_api_key:
            try:
                import aiohttp
                import json
                
                # Clean up title for search - remove common prefixes
                search_title = re.sub(r'^Ep\s*\d+:\s*', '', title, flags=re.IGNORECASE)
                
                # Build search query
                if ep_number:
                    query = f"American Optimist Episode {ep_number}"
                else:
                    # Extract key guest names or topics
                    query = f"American Optimist {search_title[:50]}"
                
                url = "https://www.googleapis.com/youtube/v3/search"
                params = {
                    'part': 'snippet',
                    'q': query,
                    'channelId': 'UCTy-AhFHOvQ9Z0HDrwgl3Xw',  # American Optimist channel ID
                    'type': 'video',
                    'maxResults': 5,
                    'key': youtube_api_key
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            items = data.get('items', [])
                            
                            # Look for best match
                            for item in items:
                                video_title = item['snippet']['title']
                                video_id = item['id']['videoId']
                                
                                # Check if episode number matches
                                if ep_number and f"Episode {ep_number}" in video_title:
                                    logger.info(f"✅ Found YouTube match by episode number: {video_title}")
                                    return f"https://www.youtube.com/watch?v={video_id}"
                                
                                # Check for key terms from title
                                key_terms = extract_key_terms(title)
                                matches = sum(1 for term in key_terms if term.lower() in video_title.lower())
                                if matches >= 2:  # At least 2 key terms match
                                    logger.info(f"✅ Found YouTube match by key terms: {video_title}")
                                    return f"https://www.youtube.com/watch?v={video_id}"
                            
                            # If no strong match, return first result as fallback
                            if items:
                                video_id = items[0]['id']['videoId']
                                logger.info(f"⚠️ Using first YouTube result: {items[0]['snippet']['title']}")
                                return f"https://www.youtube.com/watch?v={video_id}"
                                
            except Exception as e:
                logger.warning(f"YouTube API search failed: {e}")
        
        # Fallback: Use yt-dlp search
        try:
            import yt_dlp
            
            search_query = f"ytsearch5:American Optimist {ep_number if ep_number else title[:50]}"
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                entries = info.get('entries', [])
                
                for entry in entries:
                    if 'American Optimist' in entry.get('channel', ''):
                        video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                        logger.info(f"✅ Found via yt-dlp search: {entry.get('title', 'Unknown')}")
                        return video_url
                
        except Exception as e:
            logger.warning(f"yt-dlp search failed: {e}")
        
        return None


def extract_key_terms(title: str) -> list:
    """Extract key terms from episode title for matching"""
    # Remove common words and episode prefixes
    title = re.sub(r'^Ep\s*\d+:\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\b(on|the|with|and|of|in|at|to|for|&)\b', ' ', title, flags=re.IGNORECASE)
    
    # Extract likely names (capitalized words)
    words = title.split()
    key_terms = []
    
    for word in words:
        # Keep capitalized words (likely names) and significant words
        if word and (word[0].isupper() or len(word) > 5):
            clean_word = re.sub(r'[^\w]', '', word)
            if clean_word and len(clean_word) > 2:
                key_terms.append(clean_word)
    
    return key_terms[:5]  # Return top 5 terms