"""Direct Apple Podcasts episode fetcher for problematic podcasts"""

import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AppleEpisodeFetcher:
    """Fetches episodes directly from Apple Podcasts API, bypassing RSS feeds"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Renaissance Weekly/1.0',
            'Accept': 'application/json'
        })
    
    async def fetch_episodes_direct(self, podcast_config: Dict, days_back: int = 7) -> List[Episode]:
        """
        Fetch episodes directly from Apple Podcasts API.
        This bypasses RSS feeds entirely, which is useful for Cloudflare-protected podcasts.
        """
        apple_id = podcast_config.get("apple_id")
        podcast_name = podcast_config.get("name")
        
        if not apple_id:
            logger.warning(f"No Apple ID configured for {podcast_name}")
            return []
        
        logger.info(f"🍎 Fetching {podcast_name} episodes directly from Apple API")
        
        try:
            # Use Apple's episode lookup API
            url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcastEpisode&limit=200"
            response = self.session.get(url, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Apple API returned status {response.status_code}")
                return []
            
            data = response.json()
            if data.get("resultCount", 0) == 0:
                logger.warning(f"No results from Apple API for {podcast_name}")
                return []
            
            # Parse episodes
            episodes = []
            cutoff = datetime.now() - timedelta(days=days_back)
            
            for item in data.get("results", []):
                if item.get("wrapperType") == "podcastEpisode":
                    try:
                        # Parse release date
                        release_date = datetime.fromisoformat(
                            item.get("releaseDate", "").replace("Z", "+00:00")
                        )
                        if release_date.tzinfo:
                            release_date = release_date.replace(tzinfo=None)
                        
                        # Check if within date range
                        if release_date < cutoff:
                            continue
                        
                        # Create episode object
                        episode = Episode(
                            podcast=podcast_name,
                            title=item.get('trackName', 'Unknown'),
                            published=release_date,
                            audio_url=item.get('episodeUrl', ''),  # This will be Substack URL
                            description=item.get('description', ''),
                            duration=self._format_duration(item.get('trackTimeMillis', 0)),
                            guid=f"apple-{item.get('trackId', '')}",
                            apple_podcast_id=apple_id
                        )
                        
                        # Add metadata that will help with YouTube search
                        episode.metadata = {
                            'episode_number': self._extract_episode_number(episode.title),
                            'guest_name': self._extract_guest_name(episode.title),
                            'file_extension': item.get('episodeFileExtension', 'mp3')
                        }
                        
                        episodes.append(episode)
                        
                    except Exception as e:
                        logger.error(f"Error parsing episode: {e}")
                        continue
            
            # Sort by date (newest first)
            episodes.sort(key=lambda x: x.published, reverse=True)
            
            logger.info(f"✅ Found {len(episodes)} episodes from Apple API")
            
            # Log episodes for debugging
            for i, ep in enumerate(episodes[:3], 1):
                logger.debug(f"  {i}. {ep.title} ({ep.published.strftime('%Y-%m-%d')})")
            
            return episodes
            
        except Exception as e:
            logger.error(f"Error fetching from Apple API: {e}")
            return []
    
    def _format_duration(self, millis: int) -> str:
        """Convert milliseconds to duration string"""
        if not millis:
            return "Unknown"
        
        seconds = millis // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:00"
        else:
            return f"{minutes:02d}:00"
    
    def _extract_episode_number(self, title: str) -> Optional[int]:
        """Extract episode number from title"""
        # Look for patterns like "Ep 118:" or "Episode 118" or "#118"
        patterns = [
            r'Ep\s+(\d+)[:\s]',
            r'Episode\s+(\d+)[:\s]',
            r'#(\d+)[:\s]',
            r'(\d+)[:\s]'  # Just number at start
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
        
        return None
    
    def _extract_guest_name(self, title: str) -> Optional[str]:
        """Extract guest name from episode title"""
        # Common patterns:
        # "Ep 118: Marc Andreessen on AI..."
        # "Marc Andreessen: How to..."
        # "Interview with Marc Andreessen"
        
        # Remove episode number prefix
        title_clean = re.sub(r'^(Ep\.?\s*\d+[:\s]+|Episode\s*\d+[:\s]+|#\d+[:\s]+)', '', title, flags=re.IGNORECASE)
        
        # Look for name before colon or "on"
        patterns = [
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:',  # "Name Name:"
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+on\s+',  # "Name Name on"
            r'^(?:Interview with|Conversation with|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # "with Name"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title_clean)
            if match:
                return match.group(1).strip()
        
        # If title has colon, everything before it might be the guest
        if ':' in title_clean:
            potential_guest = title_clean.split(':')[0].strip()
            # Check if it looks like a name (2-4 capitalized words)
            words = potential_guest.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                return potential_guest
        
        return None
    
    def build_youtube_search_queries(self, episode: Episode, podcast_config: Dict) -> List[str]:
        """Build intelligent YouTube search queries for an episode"""
        queries = []
        
        # Get metadata
        ep_num = getattr(episode, 'metadata', {}).get('episode_number')
        guest = getattr(episode, 'metadata', {}).get('guest_name')
        
        # Get YouTube channel if configured
        youtube_channel = podcast_config.get('retry_strategy', {}).get('youtube_channel')
        channel_name = podcast_config.get('retry_strategy', {}).get('youtube_channel_name', 'Joe Lonsdale')
        
        # Build queries in order of specificity
        if ep_num and guest:
            # Most specific: episode number + guest
            queries.append(f'"{podcast_config["name"]}" episode {ep_num} {guest}')
            queries.append(f'{channel_name} {guest} episode {ep_num}')
        
        if guest:
            # Guest-based search
            queries.append(f'"{podcast_config["name"]}" {guest}')
            queries.append(f'{channel_name} {guest}')
        
        if ep_num:
            # Episode number search
            queries.append(f'"{podcast_config["name"]}" episode {ep_num}')
            queries.append(f'{channel_name} "Ep {ep_num}"')
        
        # Full title search (fallback)
        queries.append(f'{channel_name} "{episode.title}"')
        
        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        
        return unique_queries