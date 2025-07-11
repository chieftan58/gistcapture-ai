"""Apple Podcasts strategy - reliable fallback for most podcasts"""

from pathlib import Path
from typing import Optional, Tuple, Dict
from . import DownloadStrategy
from ..utils.logging import get_logger

logger = get_logger(__name__)


class ApplePodcastsStrategy(DownloadStrategy):
    """Download from Apple Podcasts - very reliable"""
    
    # Apple Podcast IDs from your podcasts.yaml
    APPLE_IDS = {
        "A16Z": "842818711",
        "All-In": "1502871393", 
        "American Optimist": "1659796265",
        "BG2 Pod": "1418450584",
        "Dwarkesh Podcast": "1516093381",
        "Founders": "1228971012",
        "Huberman Lab": "1545953110",
        "Lex Fridman": "1434243584",
        "Market Huddle": "1608566002",
        "Odd Lots": "1404073830",
        "The Drive": "1474256656",
        "The Tim Ferriss Show": "1053901193",
        "We Study Billionaires": "1055085742",
    }
    
    @property
    def name(self) -> str:
        return "apple_podcasts"
    
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Can handle if we have Apple Podcast ID"""
        return podcast_name in self.APPLE_IDS
    
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """Find and download from Apple Podcasts"""
        podcast = episode_info.get('podcast', '')
        title = episode_info.get('title', '')
        
        if podcast not in self.APPLE_IDS:
            return False, f"No Apple Podcast ID for {podcast}"
        
        apple_id = self.APPLE_IDS[podcast]
        logger.info(f"🍎 Searching Apple Podcasts (ID: {apple_id}) for: {title}")
        
        # Get Apple Podcasts feed URL
        apple_feed_url = f"https://podcasts.apple.com/podcast/id{apple_id}"
        
        try:
            # Search for the episode on Apple Podcasts
            # Use direct Apple Podcasts API approach instead of ReliableEpisodeFetcher
            
            import aiohttp
            import feedparser
            from datetime import datetime
            
            # Try to get RSS feed from Apple Podcasts
            async with aiohttp.ClientSession() as session:
                # Apple Podcasts lookup API
                lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
                
                async with session.get(lookup_url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                    if response.status == 200:
                        try:
                            data = await response.json()
                            if data.get('resultCount', 0) > 0:
                                feed_url = data['results'][0].get('feedUrl')
                                if feed_url:
                                    logger.info(f"Found Apple RSS feed: {feed_url}")
                                    
                                    # Get the RSS feed
                                    async with session.get(feed_url, headers={'User-Agent': 'Mozilla/5.0'}) as feed_response:
                                        if feed_response.status == 200:
                                            feed_content = await feed_response.text()
                                            
                                            # Parse feed to find matching episode
                                            feed = feedparser.parse(feed_content)
                                            
                                            # Look for matching episode
                                            for entry in feed.entries[:10]:  # Check last 10 episodes
                                                entry_title = entry.get('title', '')
                                                
                                                # Flexible title matching
                                                if self._titles_match(title, entry_title):
                                                    # Found matching episode
                                                    for link in entry.get('links', []):
                                                        if link.get('type', '').startswith('audio/'):
                                                            apple_audio_url = link.get('href')
                                                            if apple_audio_url:
                                                                logger.info(f"✅ Found Apple audio URL: {apple_audio_url[:80]}...")
                                                                
                                                                # Download using direct strategy
                                                                from .direct_strategy import DirectDownloadStrategy
                                                                direct = DirectDownloadStrategy()
                                                                
                                                                success, error = await direct.download(
                                                                    apple_audio_url, output_path, episode_info
                                                                )
                                                                
                                                                if success:
                                                                    return True, None
                        except Exception as e:
                            logger.warning(f"iTunes API response parsing error: {e}")
                            # Continue to fallback method
            
            return False, "Episode not found on Apple Podcasts"
            
        except Exception as e:
            error_msg = f"Apple Podcasts search error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def _titles_match(self, target_title: str, feed_title: str) -> bool:
        """Check if two episode titles match (flexible matching)"""
        target_words = set(target_title.lower().split())
        feed_words = set(feed_title.lower().split())
        
        # Remove common words
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'with', 'on', 'in', 'at', 'to', 'for'}
        target_words -= common_words
        feed_words -= common_words
        
        # Check if significant portion of words match
        if not target_words or not feed_words:
            return False
        
        intersection = target_words & feed_words
        similarity = len(intersection) / min(len(target_words), len(feed_words))
        
        return similarity > 0.6  # 60% word match threshold