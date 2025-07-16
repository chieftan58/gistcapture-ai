#!/usr/bin/env python3
"""
Test with a real episode pattern to reproduce the exact issue.
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

async def test_real_episode_cache():
    """Test with a real episode pattern"""
    
    db = PodcastDatabase()
    
    # Create an episode similar to what we see in production
    # Using We Study Billionaires as example
    episode = Episode(
        podcast="We Study Billionaires",
        title="BTC244: Bitcoin Strategic Reserve Test Episode",
        published=datetime.fromisoformat("2025-07-16T12:00:00"),  # No timezone
        audio_url="https://example.com/btc244.mp3",
        transcript_url=None,
        description="Test episode",
        link="https://example.com/btc244",
        duration="1:00:00",
        guid="test-btc244-guid-2025-07-16"
    )
    
    print("REAL EPISODE PATTERN TEST")
    print("="*60)
    print(f"Episode details:")
    print(f"  Podcast: {episode.podcast}")
    print(f"  Title: {episode.title}")
    print(f"  Published: {episode.published} (type: {type(episode.published)})")
    print(f"  Published TZ: {episode.published.tzinfo}")
    print(f"  GUID: {episode.guid}")
    
    # Step 1: Save transcript in full mode
    print("\n1. SAVING transcript in FULL mode...")
    transcript_content = "Real episode transcript content. " * 1000
    
    save_result = db.save_episode(
        episode=episode,
        transcript=transcript_content,
        transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
        transcription_mode='full'
    )
    print(f"   Saved with ID: {save_result}")
    
    # Step 2: Check what's in the database
    print("\n2. DATABASE CHECK...")
    import sqlite3
    from renaissance_weekly.config import DB_PATH
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT guid, published, transcription_mode,
                   CASE WHEN transcript IS NULL THEN 'NULL' ELSE LENGTH(transcript) END
            FROM episodes
            WHERE guid = ?
        """, (episode.guid,))
        row = cursor.fetchone()
        if row:
            print(f"   Found in DB:")
            print(f"     GUID: {row[0]}")
            print(f"     Published (in DB): {row[1]}")
            print(f"     Mode: {row[2]}")
            print(f"     Transcript: {row[3]} chars")
    
    # Step 3: Try to retrieve with finder
    print("\n3. RETRIEVAL ATTEMPT...")
    finder = TranscriptFinder(db)
    
    # Enable debug logging
    import logging
    logging.getLogger('renaissance_weekly.database').setLevel(logging.DEBUG)
    
    transcript, source = await finder.find_transcript(episode, 'full')
    
    if transcript:
        print(f"   ✅ FOUND transcript: {len(transcript)} chars")
    else:
        print(f"   ❌ CACHE MISS - No transcript found")
        
        # Try manual queries to debug
        print("\n4. DEBUG QUERIES...")
        
        # Try with exact GUID
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT transcript FROM episodes 
                WHERE guid = ?
            """, (episode.guid,))
            result = cursor.fetchone()
            print(f"   Direct GUID query: {'Found' if result and result[0] else 'Not found'}")
            
            # Check all episodes for this podcast
            cursor.execute("""
                SELECT guid, published, transcription_mode 
                FROM episodes 
                WHERE podcast = ?
                ORDER BY created_at DESC
                LIMIT 5
            """, (episode.podcast,))
            print(f"\n   Recent episodes for {episode.podcast}:")
            for row in cursor.fetchall():
                print(f"     GUID: {row[0]}, Published: {row[1]}, Mode: {row[2]}")
    
    await finder.cleanup()
    
    # Test with timezone-aware datetime
    print("\n" + "="*60)
    print("TESTING WITH TIMEZONE-AWARE DATETIME")
    print("="*60)
    
    episode_tz = Episode(
        podcast="We Study Billionaires",
        title="BTC245: Timezone Test Episode",
        published=datetime.now(timezone.utc),  # With timezone
        audio_url="https://example.com/btc245.mp3",
        transcript_url=None,
        description="Test episode",
        link="https://example.com/btc245",
        duration="1:00:00",
        guid="test-btc245-guid-tz"
    )
    
    print(f"Published: {episode_tz.published} (TZ: {episode_tz.published.tzinfo})")
    
    # Save
    db.save_episode(
        episode=episode_tz,
        transcript="TZ test transcript",
        transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
        transcription_mode='full'
    )
    
    # Retrieve
    transcript_tz, _ = await finder.find_transcript(episode_tz, 'full')
    print(f"Result: {'✅ Found' if transcript_tz else '❌ Not found'}")

async def main():
    await test_real_episode_cache()

if __name__ == "__main__":
    asyncio.run(main())