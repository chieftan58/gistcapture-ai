#!/usr/bin/env python3
"""Test progress-based download timeout for long episodes"""

import asyncio
import sys
from pathlib import Path
from renaissance_weekly.transcripts.audio_downloader import PlatformAudioDownloader
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)


def test_progress_download():
    """Test downloading a long podcast episode with progress tracking"""
    
    # Test URL - replace with actual long episode URL if needed
    test_urls = [
        # Add Tim Ferriss episode URL here when available
        "https://example.com/test.mp3"
    ]
    
    if len(sys.argv) > 1:
        test_urls = [sys.argv[1]]
    
    downloader = PlatformAudioDownloader()
    
    for url in test_urls:
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing download of: {url}")
        logger.info(f"{'='*60}\n")
        
        output_path = Path(f"test_download_{Path(url).stem}.mp3")
        
        try:
            success = downloader.download_audio(url, output_path, "Test Podcast")
            
            if success:
                file_size = output_path.stat().st_size / (1024 * 1024)
                logger.info(f"\n✅ SUCCESS: Downloaded {file_size:.1f}MB")
                logger.info(f"File saved to: {output_path}")
                
                # Clean up test file
                if output_path.exists():
                    output_path.unlink()
                    logger.info("Cleaned up test file")
            else:
                logger.error("\n❌ FAILED: Download unsuccessful")
                
        except Exception as e:
            logger.error(f"\n❌ ERROR: {e}")
            
        logger.info(f"\n{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_progress_download()
    else:
        print("Usage: python test_progress_download.py <audio_url>")
        print("\nExample:")
        print("python test_progress_download.py https://example.com/long-episode.mp3")
        print("\nThe new progress-based timeout will:")
        print("- Continue downloading as long as data is flowing (min 1KB/s)")
        print("- Timeout after 60 seconds of no progress")
        print("- Have a maximum timeout of 30 minutes")
        print("- Show progress updates every 10MB with speed and ETA")