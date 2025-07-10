"""Universal YouTube handler for all problematic podcasts"""

import re
from typing import Optional, Dict
from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class UniversalYouTubeHandler:
    """Handles YouTube mappings for all problematic podcasts"""
    
    # YouTube URL mappings for all problematic podcasts
    YOUTUBE_MAPPINGS = {
        "American Optimist": {
            "118": "https://www.youtube.com/watch?v=pRoKi4VL_5s",  # Marc Andreessen
            "117": "https://www.youtube.com/watch?v=w1FRqBOxS8g",  # Dave Rubin
            "115": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",  # Scott Wu
            "114": "https://www.youtube.com/watch?v=TVg_DK8-kMw",  # Flying Cars
        },
        
        "Dwarkesh Podcast": {
            "rome": "https://www.youtube.com/watch?v=QFzgSmN8Ng8",      # Kyle Harper - Rome
            "stalin": "https://www.youtube.com/watch?v=d5W_EwOtCGU",    # Stephen Kotkin - Stalin
            "satya": "https://www.youtube.com/watch?v=T6xP4ZfGE1g",     # Satya Nadella
            "sholto": "https://www.youtube.com/watch?v=hM_h0UA7upI",    # Sholto Douglas
            "church": "https://www.youtube.com/watch?v=nBDeqW7jlNY",    # George Church
        },
        
        "All-In": {
            "big_beautiful": "https://www.youtube.com/watch?v=PS76GPJAKq0",  # E234
            "bestie": "https://www.youtube.com/watch?v=R7mZHjG9XBQ",         # Recent
        },
        
        "The Drive": {
            # The Drive episodes would be added here as discovered
        }
    }
    
    # Keyword mappings for better matching
    KEYWORD_MAPPINGS = {
        "American Optimist": {
            "marc andreessen": "118",
            "dave rubin": "117",
            "scott wu": "115",
            "flying cars": "114",
        },
        
        "Dwarkesh Podcast": {
            "rome": "rome",
            "stalin": "stalin", 
            "kotkin": "stalin",
            "satya": "satya",
            "nadella": "satya",
            "sholto": "sholto",
            "douglas": "sholto",
            "church": "church",
            "george church": "church",
        },
        
        "All-In": {
            "big beautiful bill": "big_beautiful",
            "elon trump": "big_beautiful",
            "bestie": "bestie",
        }
    }
    
    @classmethod
    def should_handle(cls, podcast_name: str) -> bool:
        """Check if this podcast needs YouTube handling"""
        return podcast_name in cls.YOUTUBE_MAPPINGS
    
    @classmethod
    def enhance_episode(cls, episode: Episode) -> Episode:
        """Enhance episode with YouTube URL if available"""
        if not cls.should_handle(episode.podcast):
            return episode
            
        youtube_url = cls.find_youtube_url(episode.podcast, episode.title)
        
        if youtube_url:
            logger.info(f"✅ Found YouTube URL for {episode.podcast}: {episode.title[:50]}...")
            episode.audio_url = youtube_url
        else:
            # Fallback to YouTube search
            clean_title = episode.title.replace(":", "").split("—")[0].strip()
            search_query = f"ytsearch1:{episode.podcast} {clean_title[:50]}"
            episode.audio_url = search_query
            logger.info(f"📍 Will search YouTube: {search_query}")
        
        return episode
    
    @classmethod
    def find_youtube_url(cls, podcast_name: str, title: str) -> Optional[str]:
        """Find YouTube URL for episode"""
        if podcast_name not in cls.YOUTUBE_MAPPINGS:
            return None
            
        title_lower = title.lower()
        mappings = cls.YOUTUBE_MAPPINGS[podcast_name]
        keywords = cls.KEYWORD_MAPPINGS.get(podcast_name, {})
        
        # Method 1: Extract episode number for American Optimist
        if podcast_name == "American Optimist":
            ep_match = re.search(r'Ep\.?\s*(\d+)', title, re.IGNORECASE)
            if ep_match:
                ep_num = ep_match.group(1)
                if ep_num in mappings:
                    return mappings[ep_num]
        
        # Method 2: Keyword matching
        for keyword, key in keywords.items():
            if keyword in title_lower and key in mappings:
                return mappings[key]
        
        # Method 3: Direct key matching
        for key, url in mappings.items():
            if key.lower() in title_lower:
                return url
        
        return None
    
    @classmethod
    def get_manual_urls(cls, podcast_name: str) -> Dict[str, str]:
        """Get manual download URLs for a podcast"""
        if podcast_name not in cls.YOUTUBE_MAPPINGS:
            return {}
        
        return cls.YOUTUBE_MAPPINGS[podcast_name]
    
    @classmethod
    def get_download_instructions(cls, episode: Episode) -> str:
        """Get specific download instructions for failed episode"""
        youtube_url = cls.find_youtube_url(episode.podcast, episode.title)
        
        if youtube_url:
            return f"""YouTube authentication required. Options:
1. Manual download from: {youtube_url}
2. Use online converter: https://yt1s.com
3. Use 'Manual URL' button in UI
4. Download with browser extension"""
        else:
            return f"""No direct YouTube mapping found. Options:
1. Search YouTube manually for: {episode.podcast} {episode.title[:50]}
2. Use original RSS URL if available
3. Skip this episode for now"""