"""
System-wide robustness configuration for maximum reliability.
"""

import os
from typing import Dict, List

# Transcript source priorities (in order of preference)
TRANSCRIPT_SOURCE_PRIORITY = [
    'database_cache',
    'rss_feed_url',
    'comprehensive_finder',  # New comprehensive finder with multiple APIs
    'podcast_index_api',
    'podcast_specific_scrapers',
    'youtube_transcripts',
    'web_scraping',
    'show_notes_extraction',
    'social_media',
    'archive_org',
    'audio_transcription',  # Last resort
]

# Audio source priorities
AUDIO_SOURCE_PRIORITY = [
    'rss_feed_url',
    'episode_webpage',
    'alternate_cdns',
    'platform_apis',  # Spotify, Apple, etc.
    'youtube_audio',
    'archive_org_audio',
    'podcast_mirrors',
]

# Platform-specific configurations
PLATFORM_CONFIGS = {
    'substack': {
        'requires_cookies': True,
        'use_browser_impersonation': True,
        'preferred_browsers': ['chrome', 'firefox', 'safari'],
        'alternative_domains': ['substack.com', 'api.substack.com'],
        'transcript_locations': [
            'div.post-content',
            'div.body',
            'div.available-content',
        ],
    },
    'spotify': {
        'api_available': True,
        'requires_auth': True,
        'transcript_api': 'spotify_episodes_api',
    },
    'apple_podcasts': {
        'api_available': True,
        'transcript_support': False,
        'alternative_sources': ['podcast_index', 'youtube'],
    },
}

# Retry configurations
RETRY_CONFIG = {
    'max_attempts': 5,
    'base_delay': 1.0,
    'max_delay': 30.0,
    'exponential_base': 2.0,
    'jitter': True,
}

# API configurations
API_CONFIGS = {
    'assemblyai': {
        'env_key': 'ASSEMBLYAI_API_KEY',
        'rate_limit': 5,  # requests per second
        'supports_search': True,
    },
    'rev_ai': {
        'env_key': 'REV_AI_API_KEY',
        'rate_limit': 10,
        'supports_search': False,
    },
    'deepgram': {
        'env_key': 'DEEPGRAM_API_KEY',
        'rate_limit': 20,
        'supports_search': True,
    },
    'podcast_index': {
        'env_key': 'PODCASTINDEX_API_KEY',
        'env_secret': 'PODCASTINDEX_API_SECRET',
        'rate_limit': 100,
    },
    'youtube': {
        'env_key': 'YOUTUBE_API_KEY',
        'rate_limit': 100,
    },
}

# Download strategies by priority
DOWNLOAD_STRATEGIES = [
    'platform_specific',
    'yt_dlp_with_cookies',
    'yt_dlp_with_impersonation',
    'direct_with_headers',
    'curl_with_options',
    'wget_with_retry',
    'youtube_dl_fallback',
]

# Browser user agents for different contexts
USER_AGENTS = {
    'podcast_app': 'Podcasts/1580.1 CFNetwork/1408.0.4 Darwin/22.5.0',
    'chrome': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'firefox': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'safari': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'googlebot': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    'edge': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
}

# Headers for different scenarios
HEADER_PRESETS = {
    'standard': {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    },
    'podcast_client': {
        'Accept': 'audio/mpeg, audio/mp4, audio/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Range': 'bytes=0-',
        'Connection': 'keep-alive',
    },
    'browser_like': {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    },
}

# Validation thresholds
VALIDATION_CONFIG = {
    'min_audio_size_bytes': 10000,  # 10KB minimum
    'max_audio_size_bytes': 500_000_000,  # 500MB maximum
    'min_transcript_length': 500,  # characters
    'min_transcript_words': 100,
    'max_transcript_length': 1_000_000,  # characters
}

# Feature flags for gradual rollout
FEATURE_FLAGS = {
    'use_comprehensive_transcript_finder': True,
    'use_multiple_audio_sources': True,
    'enable_browser_cookie_extraction': True,
    'enable_yt_dlp_impersonation': True,
    'enable_social_media_search': False,  # Coming soon
    'enable_ai_transcript_search': False,  # Coming soon
    'enable_distributed_downloading': False,  # For scaling
}

def get_platform_config(url: str) -> Dict:
    """Get platform-specific configuration based on URL"""
    domain = urlparse(url).netloc.lower() if url else ''
    
    for platform, config in PLATFORM_CONFIGS.items():
        if platform in domain:
            return config
    
    return {}

def should_use_feature(feature: str) -> bool:
    """Check if a feature flag is enabled"""
    return FEATURE_FLAGS.get(feature, False)