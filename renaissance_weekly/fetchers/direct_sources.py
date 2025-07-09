"""
Direct source URLs for problematic podcasts
"""

from typing import Optional, Dict, List
from datetime import datetime, timedelta
import re

# Known working patterns and direct sources
DIRECT_SOURCES = {
    "American Optimist": {
        "youtube_channels": [
            "UCz5_k4_g7JMhslbGxJNpy0g",  # Joe Lonsdale's channel ID
        ],
        "search_patterns": [
            "Joe Lonsdale {guest}",
            "Joe Lonsdale Ep {episode_num}",
        ],
        "rss_alternative": "https://feeds.buzzsprout.com/2233907.rss",  # Alternative feed if exists
    },
    "Dwarkesh Podcast": {
        "youtube_channels": [
            "UCCaEbmz8gvyJHXFR42uSbXQ",  # Dwarkesh Patel's channel
        ],
        "search_patterns": [
            "Dwarkesh Patel {title}",
            "Dwarkesh {guest}",
        ],
    },
    "All-In": {
        "youtube_channels": [
            "UCESLZhusAkFfsNsApnjF_Cg",  # All-In Podcast channel
        ],
        "search_patterns": [
            "All In Podcast E{episode_num}",
            "All-In Pod {title}",
        ],
        "alternative_hosts": [
            "https://anchor.fm/s/4d7b1d50/podcast/rss",  # Anchor.fm feed
        ]
    },
    "The Drive": {
        "apple_override": True,  # Force Apple Podcasts only
        "alternative_hosts": [
            "https://feeds.simplecast.com/MLZDifHo",  # If they have alternative feed
        ]
    }
}

def get_direct_sources(podcast_name: str, episode_title: str) -> Dict[str, List[str]]:
    """Get direct source URLs and search patterns for problematic podcasts"""
    
    if podcast_name not in DIRECT_SOURCES:
        return {}
    
    config = DIRECT_SOURCES[podcast_name]
    result = {
        "youtube_queries": [],
        "alternative_urls": [],
        "force_apple": config.get("apple_override", False)
    }
    
    # Build YouTube queries
    if "search_patterns" in config:
        for pattern in config["search_patterns"]:
            query = pattern
            
            # Extract episode number
            ep_match = re.search(r'(?:Ep?|E|Episode)\s*(\d+)', episode_title)
            if ep_match and "{episode_num}" in pattern:
                query = query.replace("{episode_num}", ep_match.group(1))
            
            # Extract guest name
            guest_match = re.search(r':\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', episode_title)
            if guest_match and "{guest}" in pattern:
                query = query.replace("{guest}", guest_match.group(1))
            
            # Use title
            if "{title}" in pattern:
                # Clean title
                clean_title = re.sub(r'^(?:Ep?|Episode)\s*\d+\s*[:|-]\s*', '', episode_title)
                query = query.replace("{title}", clean_title[:50])
            
            if query != pattern:  # Only add if we made substitutions
                result["youtube_queries"].append(query)
    
    # Add alternative URLs
    if "alternative_hosts" in config:
        result["alternative_urls"].extend(config["alternative_hosts"])
    
    if "rss_alternative" in config:
        result["alternative_urls"].append(config["rss_alternative"])
    
    return result