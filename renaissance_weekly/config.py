"""Configuration and constants for Renaissance Weekly"""

import os
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
MAX_TRANSCRIPTION_MINUTES = 20 if TESTING_MODE else float('inf')

# Feature flags
VERIFY_APPLE_PODCASTS = os.getenv("VERIFY_APPLE_PODCASTS", "true").lower() == "true"
FETCH_MISSING_EPISODES = os.getenv("FETCH_MISSING_EPISODES", "true").lower() == "true"

# Podcast configurations
PODCAST_CONFIGS = [
    {
        "name": "Market Huddle",
        "description": "Expert market analysis and financial insights",
        "rss_feeds": [
            "https://markethuddle.substack.com/feed",
        ],
        "apple_id": "1552799888",
        "website": "https://markethuddle.substack.com",
        "force_apple": True
    },
    {
        "name": "Macro Voices",
        "description": "Global macro investing insights with Erik Townsend",
        "rss_feeds": [
            "https://feeds.feedburner.com/MacroVoices",
        ],
        "apple_id": "1079172742"
    },
    {
        "name": "Forward Guidance",
        "description": "The Fed, macro markets, and investment strategy",
        "rss_feeds": [
            "https://feeds.megaphone.fm/forwardguidance",
        ],
        "apple_id": "1562820083"
    },
    {
        "name": "Odd Lots",
        "description": "Bloomberg's Joe Weisenthal and Tracy Alloway explore markets",
        "rss_feeds": [
            "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/8a94442e-5a74-4fa2-8b8d-ae27003a8d6b/982f5071-765c-403d-969d-ae27003a8d83/podcast.rss",
        ],
        "apple_id": "1056200096",
        "force_apple": True
    },
    {
        "name": "BG2 Pod",
        "description": "Bill Gurley on venture capital, technology, and business strategy",
        "rss_feeds": [
            "https://feeds.megaphone.fm/BG2POD",
            "https://feeds.megaphone.fm/BGUR8742038096",
        ],
        "apple_id": "1728994116",
        "force_apple": True
    },
    {
        "name": "We Study Billionaires",
        "description": "Investing insights from studying the world's best investors",
        "rss_feeds": [
            "https://feeds.megaphone.fm/PPLLC8974708240",
        ],
        "apple_id": "928933489",
        "force_apple": True
    },
    {
        "name": "American Optimist",
        "description": "Celebrating American innovation and entrepreneurship with Joe Lonsdale",
        "rss_feeds": [
            "https://feeds.transistor.fm/american-optimist-with-joe-lonsdale",
            "https://www.americanoptimist.com/podcast.rss",
        ],
        "apple_id": "1589085277",
        "website": "https://www.americanoptimist.com",
        "force_apple": True
    },
    {
        "name": "All-In",
        "description": "Tech, economics, and politics with Chamath, Jason, Sacks & Friedberg",
        "rss_feeds": [
            "https://feeds.megaphone.fm/all-in-with-chamath-jason-sacks-friedberg",
        ],
        "apple_id": "1502871393",
        "website": "https://www.allinpodcast.co"
    },
    {
        "name": "A16Z",
        "description": "Technology, innovation, and the future from Andreessen Horowitz",
        "rss_feeds": [
            "https://feeds.simplecast.com/JGE3yC0V",
        ],
        "apple_id": "842818711"
    },
    {
        "name": "Lunar Society",
        "description": "Deep conversations about technology and philosophy with Dwarkesh Patel",
        "rss_feeds": [
            "https://www.dwarkeshpatel.com/feed",
            "https://api.dwarkeshpatel.com/feed",
        ],
        "apple_id": "1598388196",
        "website": "https://www.dwarkeshpatel.com"
    },
    {
        "name": "Cognitive Revolution",
        "description": "AI's impact on business and society with Nathan Labenz",
        "rss_feeds": [
            "https://feeds.megaphone.fm/RINTP3108857801",
        ],
        "apple_id": "1669813431",
        "force_apple": True
    },
    {
        "name": "No Priors",
        "description": "AI and tech investing insights with leading VCs",
        "rss_feeds": [
            "https://feeds.megaphone.fm/nopriors",
        ],
        "apple_id": "1663480525"
    },
    {
        "name": "Modern Wisdom",
        "description": "Life lessons and wisdom with Chris Williamson",
        "rss_feeds": [
            "https://modernwisdom.libsyn.com/rss",
        ],
        "apple_id": "1347973549",
        "has_transcripts": True
    },
    {
        "name": "Knowledge Project",
        "description": "Master the best of what other people have figured out with Shane Parrish",
        "rss_feeds": [
            "https://theknowledgeproject.libsyn.com/rss",
        ],
        "apple_id": "990149481",
        "website": "https://fs.blog",
        "has_transcripts": True
    },
    {
        "name": "Founders",
        "description": "Learn from history's greatest entrepreneurs with David Senra",
        "rss_feeds": [
            "https://feeds.redcircle.com/2ff32e90-aaf5-44d9-8a56-1333db3554f8",
        ],
        "apple_id": "1227971746",
        "force_apple": True
    },
    {
        "name": "Tim Ferriss",
        "description": "Life hacks, productivity, and interviews with world-class performers",
        "rss_feeds": [
            "https://rss.art19.com/tim-ferriss-show",
            "https://tim.blog/feed/podcast/",
        ],
        "apple_id": "863897795",
        "website": "https://tim.blog",
        "has_transcripts": True
    },
    {
        "name": "The Drive",
        "description": "Dr. Peter Attia on longevity, health, and performance",
        "rss_feeds": [
            "https://peterattiamd.com/podcast/feed/",
            "https://feeds.megaphone.fm/TDC9352325831",
        ],
        "apple_id": "1227863024",
        "website": "https://peterattiamd.com",
        "has_transcripts": True,
        "force_apple": True
    },
    {
        "name": "Huberman Lab",
        "description": "Science-based tools for everyday life from neuroscientist Andrew Huberman",
        "rss_feeds": [
            "https://feeds.megaphone.fm/hubermanlab",
        ],
        "apple_id": "1545953110",
        "website": "https://hubermanlab.com",
        "has_transcripts": True
    },
    {
        "name": "The Doctor's Farmacy",
        "description": "Dr. Mark Hyman on functional medicine and health optimization",
        "rss_feeds": [
            "https://feeds.megaphone.fm/thedoctorsfarmacy",
            "https://feeds.megaphone.fm/TDC5878721074",
        ],
        "apple_id": "1382804627",
        "force_apple": True
    }
]