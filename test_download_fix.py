#!/usr/bin/env python3
"""
Test download fix
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.config import PODCAST_CONFIGS
from renaissance_weekly.download_manager import DownloadManager
from renaissance_weekly.models import Episode
from datetime import datetime

async def test_download():
    """Test download with podcast configs"""
    
    # Create a test episode
    episode = Episode(
        podcast="All-In",
        title="Test Episode",
        published=datetime.now(),
        duration=3600,
        audio_url="https://example.com/test.mp3",
        transcript_url=None,
        description="Test"
    )
    
    # Build podcast configs mapping
    podcast_configs = {}
    for config in PODCAST_CONFIGS:
        podcast_configs[config['name']] = config
    
    print(f"Found {len(podcast_configs)} podcast configs")
    print(f"All-In config: {podcast_configs.get('All-In', {}).get('retry_strategy', 'Not found')}")
    
    # Create download manager
    manager = DownloadManager(concurrency=1)
    
    # Test download
    result = await manager.download_episodes([episode], podcast_configs)
    
    print(f"Download result: {result}")

if __name__ == "__main__":
    asyncio.run(test_download())