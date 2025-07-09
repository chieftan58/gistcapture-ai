"""Configuration and constants for Renaissance Weekly"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Directories
BASE_DIR = Path.cwd()
TRANSCRIPT_DIR = BASE_DIR / "transcripts"
AUDIO_DIR = BASE_DIR / "audio"
SUMMARY_DIR = BASE_DIR / "summaries"
CACHE_DIR = BASE_DIR / "cache"
TEMP_DIR = BASE_DIR / "temp"
DB_PATH = BASE_DIR / "podcast_data.db"

# Create directories
for dir_path in [TRANSCRIPT_DIR, AUDIO_DIR, SUMMARY_DIR, CACHE_DIR, TEMP_DIR]:
    dir_path.mkdir(exist_ok=True)

# Email configuration
EMAIL_FROM = "insights@gistcapture.ai"
EMAIL_TO = os.getenv("EMAIL_TO", "caddington05@gmail.com")

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
PODCASTINDEX_API_KEY = os.getenv("PODCASTINDEX_API_KEY")
PODCASTINDEX_API_SECRET = os.getenv("PODCASTINDEX_API_SECRET")
TADDY_API_KEY = os.getenv("TADDY_API_KEY")

# Testing configuration
TESTING_MODE = os.getenv("TESTING_MODE", "true").lower() == "true"
# Set to 15 minutes for optimal test mode results (was 5, then 10)
MAX_TRANSCRIPTION_MINUTES = int(os.getenv("MAX_TRANSCRIPTION_MINUTES", "15")) if TESTING_MODE else float('inf')

# Feature flags
VERIFY_APPLE_PODCASTS = os.getenv("VERIFY_APPLE_PODCASTS", "true").lower() == "true"
FETCH_MISSING_EPISODES = os.getenv("FETCH_MISSING_EPISODES", "true").lower() == "true"

# Load podcast configurations from YAML file
def load_podcast_configs():
    """Load podcast configurations from podcasts.yaml"""
    yaml_file = BASE_DIR / "podcasts.yaml"
    
    # If YAML file doesn't exist, create a template
    if not yaml_file.exists():
        template = """# Renaissance Weekly Podcast List
# Provide multiple identifiers - the system will use ALL of them to ensure we never miss an episode
# Required: name
# Recommended: apple_id AND (apple_url OR rss_feed OR search_term)

podcasts:
  - name: "Example Podcast"
    apple_id: "123456789"
    apple_url: "https://podcasts.apple.com/us/podcast/example/id123456789"
    search_term: "Example Podcast Keywords"
    rss_feed: "https://example.com/rss"  # Optional direct RSS feed
"""
        with open(yaml_file, 'w') as f:
            f.write(template)
        print(f"Created template podcasts.yaml file at {yaml_file}")
        print("Please edit this file to add your podcasts.")
        return []
    
    # Load the YAML file
    with open(yaml_file, 'r') as f:
        data = yaml.safe_load(f)
    
    # Convert to the format expected by the rest of the system
    podcast_configs = []
    for podcast in data.get('podcasts', []):
        # Extract Apple ID from URL if not provided directly
        apple_id = podcast.get('apple_id')
        if not apple_id and podcast.get('apple_url'):
            # Extract ID from URL like /id1727278168
            import re
            match = re.search(r'/id(\d+)', podcast['apple_url'])
            if match:
                apple_id = match.group(1)
        
        # Build RSS feeds list
        rss_feeds = podcast.get('rss_feeds', [])
        if isinstance(rss_feeds, str):
            rss_feeds = [rss_feeds]
        if podcast.get('rss_feed'):
            rss_feeds.append(podcast['rss_feed'])
        
        config = {
            "name": podcast['name'],
            "apple_id": apple_id,
            "apple_url": podcast.get('apple_url'),
            "search_term": podcast.get('search_term', podcast['name']),  # Default to name
            "description": podcast.get('description', f"Podcast: {podcast['name']}"),
            "rss_feeds": list(set(rss_feeds)),  # Deduplicate
            "website": podcast.get('website'),
            "force_apple": podcast.get('force_apple', True),
            "has_transcripts": podcast.get('has_transcripts', False),
            "retry_strategy": podcast.get('retry_strategy', {})  # Load retry strategy
        }
        podcast_configs.append(config)
    
    return podcast_configs

# Load podcasts from YAML
PODCAST_CONFIGS = load_podcast_configs()

# Validate that we have podcasts loaded
if not PODCAST_CONFIGS:
    print("⚠️  WARNING: No podcasts loaded from podcasts.yaml")
    print("   Please add podcasts to the file and restart.")