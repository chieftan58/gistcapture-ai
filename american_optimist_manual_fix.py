#!/usr/bin/env python3
"""
Manual fix for American Optimist downloads
Since automated methods are failing, this creates a mapping of episodes to working URLs
"""

import json
from datetime import datetime

# Manual mapping of American Optimist episodes to alternative sources
# This would need to be maintained manually or automated separately
EPISODE_MAPPING = {
    "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance": {
        "youtube_url": "https://www.youtube.com/watch?v=PC0s-nYB3CE",  # Found earlier
        "alternate_urls": [],
        "date": "2025-07-03T16:56:02Z"
    },
    "Ep 117: Dave Rubin on the Woke Right, Free Speech vs Conspiracy Theories & His New Tequila Company": {
        "youtube_url": None,  # Would need to find
        "alternate_urls": [],
        "date": "2025-06-26T20:19:29Z"
    },
    "Ep 116: California — the Next Revolution? A Conversation with Steve Hilton": {
        "youtube_url": None,  # Would need to find
        "alternate_urls": [],
        "date": "2025-06-19T20:03:40Z"
    }
}

def get_working_url(episode_title: str) -> str:
    """Get a working URL for the episode"""
    if episode_title in EPISODE_MAPPING:
        mapping = EPISODE_MAPPING[episode_title]
        if mapping.get("youtube_url"):
            return mapping["youtube_url"]
        if mapping.get("alternate_urls"):
            return mapping["alternate_urls"][0]
    
    # Fallback to search
    import re
    ep_match = re.search(r'Ep\.?\s*(\d+)', episode_title)
    if ep_match:
        ep_num = ep_match.group(1)
        return f"ytsearch:Joe Lonsdale American Optimist Episode {ep_num} full"
    
    return None

def save_mapping():
    """Save the mapping to a file"""
    with open("american_optimist_episodes.json", "w") as f:
        json.dump(EPISODE_MAPPING, f, indent=2)

def load_mapping():
    """Load the mapping from file"""
    try:
        with open("american_optimist_episodes.json", "r") as f:
            return json.load(f)
    except:
        return EPISODE_MAPPING

if __name__ == "__main__":
    print("American Optimist Episode Mapping")
    print("=" * 80)
    
    for title, info in EPISODE_MAPPING.items():
        print(f"\n{title}")
        print(f"  YouTube: {info.get('youtube_url', 'Not found')}")
        print(f"  Date: {info.get('date', 'Unknown')}")
    
    print("\n\nThis mapping would need to be integrated into the download manager")
    print("to provide working URLs for American Optimist episodes.")