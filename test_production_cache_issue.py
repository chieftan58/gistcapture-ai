#!/usr/bin/env python3
"""
Test the exact production scenario where transcripts are being re-transcribed.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.transcripts.finder import TranscriptFinder

async def test_production_issue():
    """
    Reproduce the exact issue:
    1. Run in full mode, save transcript
    2. Run again in full mode, check if it finds the cached transcript
    """
    db = PodcastDatabase()
    
    # Create a test episode similar to real podcasts
    episode = Episode(
        podcast="Test Podcast Production",
        title="Episode 123: Testing Cache Issue",
        published=datetime.now(timezone.utc) - timedelta(days=3),
        audio_url="https://example.com/test123.mp3",
        transcript_url=None,
        description="Testing production cache issue",
        link="https://example.com/episode123",
        duration="1:00:00",
        guid="test-production-guid-123"
    )
    
    print("TEST: Production Cache Issue")
    print("="*60)
    
    # STEP 1: First run - save transcript in full mode
    print("\n1. FIRST RUN (Full Mode) - Saving transcript")
    print("-"*40)
    
    transcript_content = "This is a test transcript content. " * 1000  # ~35k chars
    
    # Save the transcript
    result = db.save_episode(
        episode=episode,
        transcript=transcript_content,
        transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
        transcription_mode='full'
    )
    
    print(f"Saved episode ID: {result}")
    print(f"Transcript length: {len(transcript_content)} chars")
    
    # STEP 2: Second run - try to retrieve in full mode
    print("\n2. SECOND RUN (Full Mode) - Looking for cached transcript")
    print("-"*40)
    
    # Create new finder instance (simulating new run)
    finder = TranscriptFinder(db)
    
    # This is what happens in app.py
    cached_transcript, cached_source = await finder.find_transcript(episode, 'full')
    
    if cached_transcript:
        print(f"✅ Found cached transcript!")
        print(f"   Length: {len(cached_transcript)} chars")
        print(f"   Source: {cached_source}")
        print(f"   Matches original: {cached_transcript == transcript_content}")
    else:
        print(f"❌ CACHE MISS - Transcript not found!")
        print("   This would trigger re-transcription with AssemblyAI")
        
    # STEP 3: Check what's actually in the database
    print("\n3. DATABASE INSPECTION")
    print("-"*40)
    
    import sqlite3
    from renaissance_weekly.config import DB_PATH
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Get all info about this episode
        cursor.execute("""
            SELECT 
                id, guid, transcription_mode,
                CASE WHEN transcript IS NULL THEN 'NULL' ELSE LENGTH(transcript) END as transcript_len,
                CASE WHEN transcript_test IS NULL THEN 'NULL' ELSE LENGTH(transcript_test) END as transcript_test_len,
                created_at, updated_at
            FROM episodes
            WHERE guid = ?
        """, (episode.guid,))
        
        row = cursor.fetchone()
        if row:
            print(f"Database record found:")
            print(f"   ID: {row[0]}")
            print(f"   GUID: {row[1]}")
            print(f"   Mode: {row[2]}")
            print(f"   Transcript (full): {row[3]} chars")
            print(f"   Transcript (test): {row[4]} chars")
            print(f"   Created: {row[5]}")
            print(f"   Updated: {row[6]}")
    
    # STEP 4: Try different retrieval methods
    print("\n4. TESTING DIFFERENT RETRIEVAL METHODS")
    print("-"*40)
    
    # Direct database query
    transcript_direct, source_direct = db.get_transcript(episode, 'full')
    print(f"Direct DB query: {'Found' if transcript_direct else 'Not found'}")
    
    # Without mode (backwards compatibility)
    transcript_no_mode, source_no_mode = db.get_transcript(episode, None)
    print(f"No mode specified: {'Found' if transcript_no_mode else 'Not found'}")
    
    # Wrong mode
    transcript_wrong, source_wrong = db.get_transcript(episode, 'test')
    print(f"Wrong mode (test): {'Found' if transcript_wrong else 'Not found'}")
    
    await finder.cleanup()
    
    # Return success/failure
    return cached_transcript is not None

async def main():
    success = await test_production_issue()
    
    print("\n" + "="*60)
    if success:
        print("✅ CACHE IS WORKING CORRECTLY")
    else:
        print("❌ CACHE ISSUE CONFIRMED - Transcripts would be re-generated")
    print("="*60)
    
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)