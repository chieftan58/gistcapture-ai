"""
Special handler for American Optimist podcast
Bypasses Substack/Cloudflare by using alternative sources
"""

import re
from typing import Optional, List, Dict
from datetime import datetime

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AmericanOptimistHandler:
    """Special handling for American Optimist podcast"""
    
    # Direct YouTube mappings from americanoptimist.com
    YOUTUBE_MAPPINGS = {
        "118": "https://www.youtube.com/watch?v=pRoKi4VL_5s",  # Marc Andreessen
        "117": "https://www.youtube.com/watch?v=w1FRqBOxS8g",  # Dave Rubin
        "115": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",  # Scott Wu
        "114": "https://www.youtube.com/watch?v=TVg_DK8-kMw",  # Flying Cars
    }
    
    @staticmethod
    def enhance_episode_for_download(episode: Episode) -> Episode:
        """
        Enhance American Optimist episode with alternative audio URLs
        Since Substack URLs are blocked, we add YouTube search as primary audio_url
        """
        # Extract episode number and guest from title
        ep_match = re.search(r'Ep\.?\s*(\d+)', episode.title, re.IGNORECASE)
        ep_num = ep_match.group(1) if ep_match else None
        
        # Clean title for guest extraction
        title_clean = re.sub(r'^Ep\.?\s*\d+[:\s]+', '', episode.title, flags=re.IGNORECASE)
        
        # Check if we have a direct YouTube mapping
        youtube_url = None
        if ep_num and ep_num in AmericanOptimistHandler.YOUTUBE_MAPPINGS:
            youtube_url = AmericanOptimistHandler.YOUTUBE_MAPPINGS[ep_num]
            logger.info(f"✅ Found direct YouTube URL for Ep {ep_num}: {youtube_url}")
        else:
            # Build YouTube search URL that yt-dlp can handle
            if ep_num:
                # Primary search: specific episode number
                youtube_url = f"ytsearch1:Joe Lonsdale American Optimist Episode {ep_num}"
            else:
                # Fallback: use title
                youtube_url = f"ytsearch1:Joe Lonsdale American Optimist {title_clean[:50]}"
        
        # Create enhanced episode with YouTube URL as audio URL
        enhanced = Episode(
            podcast=episode.podcast,
            title=episode.title,
            published=episode.published,
            duration=episode.duration,
            audio_url=youtube_url,  # Use direct YouTube URL or search!
            transcript_url=episode.transcript_url,
            description=episode.description,
            link=getattr(episode, 'link', None),
            guid=getattr(episode, 'guid', None),
            apple_podcast_id=getattr(episode, 'apple_podcast_id', None)
        )
        
        logger.info(f"Enhanced American Optimist episode: {episode.title}")
        logger.info(f"  Original URL: {episode.audio_url}")
        logger.info(f"  Enhanced URL: {enhanced.audio_url}")
        
        return enhanced
    
    @staticmethod
    def get_alternative_sources(episode: Episode) -> List[str]:
        """
        Get list of alternative audio sources for American Optimist
        Returns list of URLs to try in order
        """
        sources = []
        
        # Extract episode info
        ep_match = re.search(r'Ep\.?\s*(\d+)', episode.title, re.IGNORECASE)
        ep_num = ep_match.group(1) if ep_match else None
        
        if ep_num:
            # Check for direct YouTube mapping first
            if ep_num in AmericanOptimistHandler.YOUTUBE_MAPPINGS:
                sources.append(AmericanOptimistHandler.YOUTUBE_MAPPINGS[ep_num])
            
            # YouTube searches (yt-dlp format)
            sources.extend([
                f"ytsearch1:Joe Lonsdale American Optimist Episode {ep_num}",
                f"ytsearch1:American Optimist Ep {ep_num} Joe Lonsdale",
                f"ytsearch1:\"American Optimist\" \"Episode {ep_num}\""
            ])
        
        # Extract guest name for better search
        title_clean = re.sub(r'^Ep\.?\s*\d+[:\s]+', '', episode.title, flags=re.IGNORECASE)
        if ':' in title_clean:
            guest = title_clean.split(':')[0].strip()
            sources.append(f"ytsearch:Joe Lonsdale {guest} American Optimist")
        
        # Generic fallback
        sources.append(f"ytsearch:Joe Lonsdale American Optimist {title_clean[:30]}")
        
        return sources
    
    @staticmethod
    def should_use_special_handling(episode: Episode) -> bool:
        """Check if this episode needs special handling"""
        # American Optimist with Substack URL needs special handling
        return (
            episode.podcast == "American Optimist" and 
            episode.audio_url and 
            "substack.com" in episode.audio_url
        )