#!/usr/bin/env python3
"""
Test the two-summary system with a sample full-length transcript
"""

import asyncio
from pathlib import Path
from datetime import datetime

from renaissance_weekly.processing.summarizer import Summarizer
from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.email.digest import create_expandable_email
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

# Sample full transcript (you can replace with a real one)
SAMPLE_TRANSCRIPT = """
[This is where you'd paste a real full-length transcript.
For testing, you could:
1. Get one from YouTube with subtitles
2. Use a transcript from a podcast website
3. Or let me generate a realistic sample for testing]
"""

async def test_full_summaries():
    """Test the two-summary generation system"""
    
    # Create a test episode
    test_episode = Episode(
        title="Stanley Druckenmiller on Fed Policy and Market Outlook",
        podcast="Masters in Business",
        published=datetime.now(),
        duration="1h 15m",
        link="https://example.com",
        audio_url="https://example.com/audio.mp3",
        description="Legendary investor Stanley Druckenmiller discusses..."
    )
    
    # Initialize summarizer
    summarizer = Summarizer()
    logger.info("🚀 Testing two-summary system with full episode...")
    
    # Generate both summaries
    logger.info("\n📝 Generating paragraph summary...")
    paragraph = await summarizer.generate_paragraph_summary(
        test_episode, 
        SAMPLE_TRANSCRIPT, 
        TranscriptSource.MANUAL_UPLOAD,
        mode='full',
        force_fresh=True
    )
    
    if paragraph:
        logger.info(f"\n✅ Paragraph Summary ({len(paragraph.split())} words):")
        logger.info("-" * 50)
        print(paragraph)
        logger.info("-" * 50)
    
    # Small delay between API calls
    await asyncio.sleep(0.5)
    
    logger.info("\n📄 Generating full summary...")
    full_summary = await summarizer.generate_full_summary(
        test_episode,
        SAMPLE_TRANSCRIPT,
        TranscriptSource.MANUAL_UPLOAD,
        mode='full',
        force_fresh=True
    )
    
    if full_summary:
        logger.info(f"\n✅ Full Summary ({len(full_summary.split())} words):")
        logger.info("-" * 50)
        print(full_summary[:500] + "..." if len(full_summary) > 500 else full_summary)
        logger.info("-" * 50)
    
    # Test email generation
    if paragraph and full_summary:
        logger.info("\n📧 Generating test email...")
        
        # Create email with single episode
        email_html = create_expandable_email(
            [full_summary],
            [test_episode], 
            [paragraph]
        )
        
        # Save email for viewing
        email_path = Path("test_email.html")
        with open(email_path, 'w') as f:
            f.write(email_html)
        
        logger.info(f"✅ Email saved to: {email_path}")
        logger.info("   Open in browser to test expandable sections")
    
    return paragraph, full_summary

if __name__ == "__main__":
    asyncio.run(test_full_summaries())