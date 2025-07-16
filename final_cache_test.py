#!/usr/bin/env python3
"""
Final comprehensive test of the transcript cache fix.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.transcripts.finder import TranscriptFinder

# Enable debug logging
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def final_test():
    """Final comprehensive test"""
    db = PodcastDatabase()
    finder = TranscriptFinder(db)
    
    print("\nFINAL TRANSCRIPT CACHE TEST")
    print("="*60)
    
    # Test 1: Full production simulation
    print("\n1. PRODUCTION SIMULATION TEST")
    print("-"*40)
    
    episode = Episode(
        podcast="The Tim Ferriss Show",
        title="Episode #700: Final Cache Test",
        published=datetime.now(timezone.utc),
        audio_url="https://example.com/tf700.mp3",
        transcript_url=None,
        description="Final test episode",
        link="https://example.com/tf700",
        duration="2:00:00",
        guid="tim-ferriss-700-final-test"
    )
    
    # First run: Save transcript in full mode
    print("First run: Saving transcript in full mode...")
    transcript_content = "This is the final test transcript. " * 1000
    
    save_result = db.save_episode(
        episode=episode,
        transcript=transcript_content,
        transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
        transcription_mode='full'
    )
    print(f"Save result: {save_result}")
    
    # Second run: Try to retrieve in full mode
    print("\nSecond run: Retrieving transcript in full mode...")
    cached_transcript, cached_source = await finder.find_transcript(episode, 'full')
    
    if cached_transcript:
        print(f"✅ SUCCESS: Found cached transcript!")
        print(f"   Length: {len(cached_transcript)} chars")
        print(f"   Source: {cached_source}")
        print(f"   Matches: {cached_transcript == transcript_content}")
    else:
        print(f"❌ FAILURE: Cache miss - transcript not found")
        print(f"   This would cause re-transcription with AssemblyAI")
        
    # Test 2: Cross-mode isolation
    print("\n2. CROSS-MODE ISOLATION TEST")
    print("-"*40)
    
    # Try to retrieve the same episode in test mode
    test_transcript, test_source = await finder.find_transcript(episode, 'test')
    
    if test_transcript:
        print(f"❌ FAILURE: Found transcript in wrong mode!")
        print(f"   This indicates mode isolation is broken")
    else:
        print(f"✅ SUCCESS: Mode isolation working correctly")
        
    # Test 3: String date handling
    print("\n3. STRING DATE HANDLING TEST")
    print("-"*40)
    
    # Create episode with string date
    episode_str = Episode(
        podcast="Test Podcast",
        title="String Date Test",
        published="2025-07-16T12:00:00",  # String instead of datetime
        audio_url="https://example.com/string.mp3",
        transcript_url=None,
        description="Test",
        link="https://example.com/string",
        duration="1:00:00",
        guid="string-date-test"
    )
    
    # This should not crash
    try:
        save_result = db.save_episode(
            episode=episode_str,
            transcript="String date test transcript",
            transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
            transcription_mode='full'
        )
        print(f"✅ SUCCESS: Handled string date without crashing (ID: {save_result})")
    except Exception as e:
        print(f"❌ FAILURE: String date caused error: {e}")
        
    await finder.cleanup()
    
    print("\n" + "="*60)
    print("FINAL TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(final_test())