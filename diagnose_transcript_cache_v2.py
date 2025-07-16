#!/usr/bin/env python3
"""
Focused diagnostic to reproduce the transcript cache issue in production scenarios.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.config import DB_PATH
from renaissance_weekly.transcripts.finder import TranscriptFinder

class ProductionCacheDiagnostic:
    def __init__(self):
        self.db = PodcastDatabase()
        self.transcript_finder = TranscriptFinder(self.db)
        self.failures = []
        
    async def test_production_scenario(self):
        """Test the exact scenario that's failing in production"""
        print("\n" + "="*80)
        print("PRODUCTION SCENARIO TEST")
        print("Simulating: Save transcript in full mode, then try to retrieve it")
        print("="*80)
        
        # Create a realistic episode
        episode = Episode(
            podcast="The Tim Ferriss Show",
            title="Episode #650: Test Episode for Cache Diagnosis",
            published=datetime.now(timezone.utc) - timedelta(days=2),
            audio_url="https://example.com/audio.mp3",
            transcript_url=None,
            description="Test episode description",
            link="https://example.com/episode",
            duration="1:30:00",
            guid="tim-ferriss-650-test"
        )
        
        # Simulate production flow
        print("\n1. PRODUCTION FLOW - FULL MODE")
        print("-" * 40)
        
        # Save transcript in full mode (as production does)
        test_transcript = "This is a production test transcript. " * 500
        print(f"Saving transcript in FULL mode...")
        print(f"  Episode: {episode.podcast} - {episode.title}")
        print(f"  GUID: {episode.guid}")
        print(f"  Transcript length: {len(test_transcript)} chars")
        
        save_result = self.db.save_episode(
            episode=episode,
            transcript=test_transcript,
            transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
            transcription_mode='full'
        )
        print(f"  Save result: {save_result}")
        
        # Check database state
        print("\n2. DATABASE STATE CHECK")
        print("-" * 40)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT podcast, title, published, guid, 
                       LENGTH(transcript), LENGTH(transcript_test), 
                       transcription_mode, created_at, updated_at
                FROM episodes
                WHERE guid = ?
            """, (episode.guid,))
            
            row = cursor.fetchone()
            if row:
                print(f"  Found in DB:")
                print(f"    Podcast: {row[0]}")
                print(f"    Title: {row[1]}")
                print(f"    Published: {row[2]}")
                print(f"    GUID: {row[3]}")
                print(f"    Transcript (full): {row[4] or 'NULL'} chars")
                print(f"    Transcript (test): {row[5] or 'NULL'} chars")
                print(f"    Mode: {row[6]}")
                print(f"    Created: {row[7]}")
                print(f"    Updated: {row[8]}")
            else:
                print("  ❌ NOT FOUND IN DATABASE!")
                self.failures.append("Episode not saved to database")
                
        # Now try to retrieve it (simulating next run)
        print("\n3. RETRIEVAL ATTEMPT (FULL MODE)")
        print("-" * 40)
        print("Simulating next run - trying to retrieve transcript...")
        
        # Clear any in-memory caches by creating new finder
        new_finder = TranscriptFinder(self.db)
        transcript, source = await new_finder.find_transcript(episode, 'full')
        
        if transcript:
            print(f"  ✅ Retrieved successfully!")
            print(f"    Length: {len(transcript)} chars")
            print(f"    Source: {source}")
            print(f"    Matches original: {transcript == test_transcript}")
        else:
            print(f"  ❌ FAILED TO RETRIEVE!")
            self.failures.append("Failed to retrieve transcript in full mode")
            
            # Try some debug queries
            print("\n4. DEBUG QUERIES")
            print("-" * 40)
            
            # Try different query approaches
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                
                # Query 1: By GUID with transcript column
                cursor.execute("""
                    SELECT transcript FROM episodes 
                    WHERE guid = ? AND transcript IS NOT NULL
                """, (episode.guid,))
                result1 = cursor.fetchone()
                print(f"  Query by GUID (transcript column): {'Found' if result1 else 'Not found'}")
                
                # Query 2: By title/date
                cursor.execute("""
                    SELECT transcript FROM episodes 
                    WHERE podcast = ? AND title = ? 
                    AND date(published) = date(?)
                    AND transcript IS NOT NULL
                """, (episode.podcast, episode.title, episode.published.isoformat()))
                result2 = cursor.fetchone()
                print(f"  Query by title/date: {'Found' if result2 else 'Not found'}")
                
                # Query 3: Show all columns for this GUID
                cursor.execute("SELECT * FROM episodes WHERE guid = ?", (episode.guid,))
                all_cols = cursor.fetchone()
                if all_cols:
                    col_names = [desc[0] for desc in cursor.description]
                    print("\n  All columns for this episode:")
                    for i, (name, value) in enumerate(zip(col_names, all_cols)):
                        if name in ['transcript', 'transcript_test', 'summary', 'summary_test']:
                            value = f"{len(value) if value else 0} chars"
                        print(f"    {name}: {value}")
        
        # Test cross-mode scenario
        print("\n5. CROSS-MODE TEST")
        print("-" * 40)
        print("Testing: Save in full mode, try to retrieve in test mode")
        
        transcript_test, source_test = await new_finder.find_transcript(episode, 'test')
        if transcript_test:
            print(f"  ⚠️  Retrieved in TEST mode: {len(transcript_test)} chars")
            self.failures.append("Cross-mode retrieval should not work!")
        else:
            print(f"  ✅ Correctly failed to retrieve in test mode")
            
        await new_finder.cleanup()
            
    async def test_real_world_episodes(self):
        """Test with actual podcast episode patterns"""
        print("\n" + "="*80)
        print("REAL-WORLD EPISODE PATTERNS TEST")
        print("="*80)
        
        # Test various real-world scenarios
        test_cases = [
            {
                'name': 'Episode with special characters',
                'episode': Episode(
                    podcast="All-In Podcast",
                    title="E165: Nvidia's trillion-dollar problem, Apple's EU battle & more",
                    published=datetime.now(timezone.utc) - timedelta(days=1),
                    audio_url="https://example.com/allin165.mp3",
                    transcript_url=None,
                    description="Test",
                    link="https://example.com/allin165",
                    duration="1:45:00",
                    guid="allin-e165-special-chars"
                )
            },
            {
                'name': 'Episode with very long title',
                'episode': Episode(
                    podcast="The Tim Ferriss Show",
                    title="Episode #651: " + "Very Long Title " * 20,
                    published=datetime.now(timezone.utc) - timedelta(hours=6),
                    audio_url="https://example.com/tf651.mp3",
                    transcript_url=None,
                    description="Test",
                    link="https://example.com/tf651",
                    duration="2:00:00",
                    guid=None  # Test without GUID
                )
            }
        ]
        
        for test_case in test_cases:
            print(f"\nTest: {test_case['name']}")
            print("-" * 40)
            
            episode = test_case['episode']
            transcript = f"Test transcript for {test_case['name']}. " * 100
            
            # Save in full mode
            self.db.save_episode(
                episode=episode,
                transcript=transcript,
                transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
                transcription_mode='full'
            )
            
            # Try to retrieve
            retrieved, source = await self.transcript_finder.find_transcript(episode, 'full')
            
            if retrieved:
                print(f"  ✅ Success: Retrieved {len(retrieved)} chars")
            else:
                print(f"  ❌ Failed to retrieve")
                self.failures.append(f"Failed: {test_case['name']}")
                
                # Debug query
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT COUNT(*) FROM episodes 
                        WHERE podcast = ? AND title LIKE ?
                    """, (episode.podcast, episode.title[:50] + '%'))
                    count = cursor.fetchone()[0]
                    print(f"  Episodes with similar title in DB: {count}")
                    
    async def run_all_tests(self):
        """Run all diagnostic tests"""
        await self.test_production_scenario()
        await self.test_real_world_episodes()
        
        # Summary
        print("\n" + "="*80)
        print("DIAGNOSTIC SUMMARY")
        print("="*80)
        
        if self.failures:
            print(f"❌ FAILURES DETECTED: {len(self.failures)}")
            for failure in self.failures:
                print(f"  - {failure}")
            return False
        else:
            print("✅ ALL TESTS PASSED!")
            return True
            
    async def cleanup(self):
        """Cleanup resources"""
        await self.transcript_finder.cleanup()

async def main():
    diagnostic = ProductionCacheDiagnostic()
    try:
        success = await diagnostic.run_all_tests()
        return 0 if success else 1
    finally:
        await diagnostic.cleanup()

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)