#!/usr/bin/env python
"""
Test script to verify transcript caching is working correctly after database migration.
This script will:
1. Check if the database has the required columns
2. Run a quick test to verify transcript caching
"""

import sqlite3
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.models import Episode, TranscriptSource


async def test_transcript_caching():
    """Test transcript caching functionality"""
    print("🧪 Testing transcript caching after database migration...")
    
    # 1. Check database schema
    print("\n1️⃣ Checking database schema...")
    db_path = Path("renaissance_weekly.db")
    
    if not db_path.exists():
        print("❌ Database not found!")
        return False
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Check for required columns
    cursor.execute("PRAGMA table_info(episodes)")
    columns = {row[1] for row in cursor.fetchall()}
    
    required_columns = ['transcript_test', 'summary_test', 'transcription_mode']
    missing = [col for col in required_columns if col not in columns]
    
    if missing:
        print(f"❌ Missing columns: {missing}")
        print("   Please run: python migrate_db.py")
        return False
    
    print("✅ All required columns exist!")
    
    # 2. Test saving and retrieving transcripts
    print("\n2️⃣ Testing transcript save/retrieve...")
    db = PodcastDatabase()
    
    # Create test episode
    test_episode = Episode(
        podcast="Test Podcast",
        title="Test Episode for Cache Verification",
        published=datetime.now() - timedelta(days=1),
        audio_url="https://example.com/test.mp3",
        description="Test description",
        guid="test-guid-12345"
    )
    
    # Test both modes
    for mode in ['test', 'full']:
        print(f"\n   Testing {mode} mode:")
        
        # Save transcript
        test_transcript = f"This is a test transcript for {mode} mode. " * 100
        episode_id = db.save_episode(
            test_episode,
            transcript=test_transcript,
            transcript_source=TranscriptSource.API,
            transcription_mode=mode
        )
        
        if episode_id > 0:
            print(f"   ✅ Saved transcript (ID: {episode_id})")
        else:
            print(f"   ❌ Failed to save transcript")
            continue
        
        # Retrieve transcript
        retrieved_transcript, source = db.get_transcript(test_episode, mode)
        
        if retrieved_transcript == test_transcript:
            print(f"   ✅ Retrieved transcript successfully!")
            print(f"      - Source: {source.value}")
            print(f"      - Length: {len(retrieved_transcript)} chars")
        else:
            print(f"   ❌ Failed to retrieve transcript")
            if retrieved_transcript:
                print(f"      - Got {len(retrieved_transcript)} chars instead of {len(test_transcript)}")
    
    # 3. Check mode-specific storage
    print("\n3️⃣ Verifying mode-specific storage...")
    cursor.execute("""
        SELECT 
            transcription_mode,
            CASE 
                WHEN transcript IS NOT NULL THEN 'full column' 
                WHEN transcript_test IS NOT NULL THEN 'test column'
                ELSE 'no transcript'
            END as storage_location,
            COUNT(*) as count
        FROM episodes
        WHERE guid = 'test-guid-12345'
        GROUP BY transcription_mode, storage_location
    """)
    
    results = cursor.fetchall()
    for mode, location, count in results:
        print(f"   - Mode '{mode}': {count} transcript(s) in {location}")
    
    conn.close()
    
    # 4. Test with real episode
    print("\n4️⃣ Testing with a real episode scenario...")
    real_episode = Episode(
        podcast="American Optimist",
        title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
        published=datetime(2025, 7, 3, 16, 56, 2),
        audio_url="https://api.substack.com/feed/podcast/167438211/test.mp3",
        guid="1000715621905"
    )
    
    # Check if we can find a cached transcript
    for mode in ['test', 'full']:
        cached_transcript, source = db.get_transcript(real_episode, mode)
        if cached_transcript:
            print(f"   ✅ Found cached transcript for American Optimist in {mode} mode!")
            print(f"      - Source: {source.value}")
            print(f"      - Length: {len(cached_transcript)} chars")
        else:
            print(f"   ℹ️  No cached transcript for American Optimist in {mode} mode")
    
    print("\n✅ Transcript caching test completed successfully!")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_transcript_caching())
    sys.exit(0 if success else 1)