#!/usr/bin/env python3
"""
Diagnostic script to identify and fix transcript cache issues.
This script will create test episodes, save transcripts, and verify retrieval.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.config import DB_PATH
from renaissance_weekly.transcripts.finder import TranscriptFinder

# Enable verbose logging
import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class TranscriptCacheDiagnostic:
    def __init__(self):
        self.db = PodcastDatabase()
        self.transcript_finder = TranscriptFinder(self.db)
        self.test_results = []
        
    def create_test_episode(self, test_id: int, published_date: datetime) -> Episode:
        """Create a test episode with controlled data"""
        return Episode(
            podcast=f"Test Podcast {test_id}",
            title=f"Test Episode {test_id}",
            published=published_date,
            audio_url=f"https://example.com/test{test_id}.mp3",
            transcript_url=None,
            description=f"Test description {test_id}",
            link=f"https://example.com/test{test_id}",
            duration="1:00:00",
            guid=f"test-guid-{test_id}-{published_date.isoformat()}"
        )
    
    def inspect_database_state(self, episode: Episode, mode: str):
        """Inspect what's actually in the database"""
        print(f"\n{'='*80}")
        print(f"DATABASE INSPECTION - Episode: {episode.title}, Mode: {mode}")
        print('='*80)
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Show all episodes with this title
            cursor.execute("""
                SELECT id, podcast, title, published, guid, 
                       transcript, transcript_test, transcription_mode,
                       created_at, updated_at
                FROM episodes
                WHERE title = ?
            """, (episode.title,))
            
            results = cursor.fetchall()
            if results:
                for row in results:
                    print(f"\nDatabase Row:")
                    print(f"  ID: {row[0]}")
                    print(f"  Podcast: {row[1]}")
                    print(f"  Title: {row[2]}")
                    print(f"  Published: {row[3]} (type in DB: {type(row[3])})")
                    print(f"  GUID: {row[4]}")
                    print(f"  Transcript (full): {len(row[5]) if row[5] else 'NULL'} chars")
                    print(f"  Transcript (test): {len(row[6]) if row[6] else 'NULL'} chars")
                    print(f"  Transcription Mode: {row[7]}")
                    print(f"  Created: {row[8]}")
                    print(f"  Updated: {row[9]}")
            else:
                print("  NO ROWS FOUND!")
                
            # Show what queries would be run
            print(f"\nQuery attempts that will be made:")
            print(f"  1. By GUID: {episode.guid}")
            print(f"  2. By title/date: {episode.podcast}, {episode.title}, {episode.published.isoformat()}")
            
    async def test_save_and_retrieve(self, episode: Episode, mode: str, test_name: str):
        """Test saving and retrieving a transcript"""
        print(f"\n{'='*80}")
        print(f"TEST: {test_name}")
        print(f"Mode: {mode}")
        print('='*80)
        
        test_transcript = f"This is a test transcript for {episode.title} in {mode} mode. " * 100
        
        # Save the transcript
        print(f"\n1. SAVING transcript...")
        print(f"   Episode details:")
        print(f"   - Podcast: {episode.podcast}")
        print(f"   - Title: {episode.title}")
        print(f"   - Published: {episode.published} (type: {type(episode.published)})")
        print(f"   - GUID: {episode.guid}")
        print(f"   - Mode: {mode}")
        print(f"   - Transcript length: {len(test_transcript)} chars")
        
        save_result = self.db.save_episode(
            episode=episode,
            transcript=test_transcript,
            transcript_source=TranscriptSource.API_TRANSCRIPTION,
            transcription_mode=mode
        )
        print(f"   Save result (row ID): {save_result}")
        
        # Inspect database immediately after save
        self.inspect_database_state(episode, mode)
        
        # Try to retrieve the transcript
        print(f"\n2. RETRIEVING transcript...")
        transcript, source = await self.transcript_finder.find_transcript(episode, mode)
        
        if transcript:
            print(f"   ✅ RETRIEVED successfully!")
            print(f"   - Length: {len(transcript)} chars")
            print(f"   - Source: {source}")
            print(f"   - Matches saved: {transcript == test_transcript}")
            
            if transcript != test_transcript:
                print(f"   ❌ ERROR: Retrieved transcript doesn't match saved!")
                print(f"   - Saved length: {len(test_transcript)}")
                print(f"   - Retrieved length: {len(transcript)}")
                
            self.test_results.append({
                'test': test_name,
                'mode': mode,
                'success': True,
                'matches': transcript == test_transcript
            })
        else:
            print(f"   ❌ FAILED to retrieve!")
            self.test_results.append({
                'test': test_name,
                'mode': mode,
                'success': False,
                'matches': False
            })
            
        # Try direct database query to see what's there
        print(f"\n3. DIRECT DATABASE QUERY...")
        transcript_col = 'transcript_test' if mode == 'test' else 'transcript'
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT {transcript_col}, transcription_mode
                FROM episodes
                WHERE guid = ?
            """, (episode.guid,))
            result = cursor.fetchone()
            if result:
                print(f"   Direct query found: {len(result[0]) if result[0] else 'NULL'} chars, mode: {result[1]}")
            else:
                print(f"   Direct query found: NO ROWS")
    
    async def run_all_tests(self):
        """Run comprehensive tests"""
        print("\n" + "="*80)
        print("TRANSCRIPT CACHE DIAGNOSTIC TEST SUITE")
        print("="*80)
        
        # Test 1: Basic save and retrieve with current datetime
        now = datetime.now(timezone.utc)
        episode1 = self.create_test_episode(1, now)
        await self.test_save_and_retrieve(episode1, 'test', 'Basic Test Mode')
        await self.test_save_and_retrieve(episode1, 'full', 'Basic Full Mode')
        
        # Test 2: Different timezone representations
        tz_tests = [
            ('UTC', now),
            ('No TZ', now.replace(tzinfo=None)),
            ('Local TZ', now.astimezone()),
            ('String', now.isoformat())
        ]
        
        for i, (tz_name, pub_date) in enumerate(tz_tests, start=2):
            if isinstance(pub_date, str):
                # For string test, create episode with string date then convert
                episode = self.create_test_episode(100 + i, now)
                episode.published = pub_date  # Override with string
            else:
                episode = self.create_test_episode(100 + i, pub_date)
            await self.test_save_and_retrieve(episode, 'test', f'Timezone Test - {tz_name}')
        
        # Test 3: Episodes with no GUID
        episode_no_guid = self.create_test_episode(200, now)
        episode_no_guid.guid = None
        await self.test_save_and_retrieve(episode_no_guid, 'test', 'No GUID Test')
        
        # Test 4: Save in one mode, retrieve in another
        episode_cross = self.create_test_episode(300, now)
        print(f"\n{'='*80}")
        print("CROSS-MODE TEST: Save in test, try to retrieve in full")
        print('='*80)
        
        # Save in test mode
        self.db.save_episode(
            episode=episode_cross,
            transcript="Test mode transcript",
            transcript_source=TranscriptSource.API_TRANSCRIPTION,
            transcription_mode='test'
        )
        
        # Try to retrieve in full mode
        transcript_full, _ = await self.transcript_finder.find_transcript(episode_cross, 'full')
        print(f"Retrieved in full mode: {transcript_full is not None}")
        
        # Try to retrieve in test mode
        transcript_test, _ = await self.transcript_finder.find_transcript(episode_cross, 'test')
        print(f"Retrieved in test mode: {transcript_test is not None}")
        
        # Test 5: Rapid save and retrieve (race condition test)
        print(f"\n{'='*80}")
        print("RACE CONDITION TEST: Rapid save and retrieve")
        print('='*80)
        
        for i in range(5):
            episode_race = self.create_test_episode(400 + i, now)
            
            # Save
            self.db.save_episode(
                episode=episode_race,
                transcript=f"Race test {i}",
                transcript_source=TranscriptSource.API_TRANSCRIPTION,
                transcription_mode='test'
            )
            
            # Immediately retrieve (no delay)
            transcript, _ = await self.transcript_finder.find_transcript(episode_race, 'test')
            print(f"Iteration {i}: Retrieved = {transcript is not None}")
            
            if not transcript:
                # Add small delay and retry
                await asyncio.sleep(0.1)
                transcript, _ = await self.transcript_finder.find_transcript(episode_race, 'test')
                print(f"  After 0.1s delay: Retrieved = {transcript is not None}")
        
        # Print summary
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print('='*80)
        
        success_count = sum(1 for r in self.test_results if r['success'])
        match_count = sum(1 for r in self.test_results if r['matches'])
        total_count = len(self.test_results)
        
        print(f"Total tests: {total_count}")
        print(f"Successful retrievals: {success_count}")
        print(f"Content matches: {match_count}")
        print(f"Failed retrievals: {total_count - success_count}")
        
        if success_count < total_count:
            print("\n❌ CACHE ISSUES DETECTED!")
            failed_tests = [r for r in self.test_results if not r['success']]
            for test in failed_tests:
                print(f"  - {test['test']} ({test['mode']} mode)")
        else:
            print("\n✅ ALL TESTS PASSED!")
    
    async def cleanup(self):
        """Cleanup test data"""
        await self.transcript_finder.cleanup()

async def main():
    diagnostic = TranscriptCacheDiagnostic()
    try:
        await diagnostic.run_all_tests()
    finally:
        await diagnostic.cleanup()

if __name__ == "__main__":
    asyncio.run(main())