#!/usr/bin/env python3
"""
Comprehensive regression test suite for transcript cache.
Tests all edge cases and scenarios.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
import json

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.transcripts.finder import TranscriptFinder

class TranscriptCacheTest:
    def __init__(self):
        self.db = PodcastDatabase()
        self.finder = TranscriptFinder(self.db)
        self.test_results = []
        
    async def test_case(self, name: str, episode: Episode, mode: str, 
                       expected_result: bool = True):
        """Run a single test case"""
        print(f"\n[TEST] {name}")
        print("-" * 50)
        
        # Save transcript
        transcript = f"Test transcript for {name} " * 100
        save_result = self.db.save_episode(
            episode=episode,
            transcript=transcript,
            transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
            transcription_mode=mode
        )
        
        if save_result <= 0:
            print(f"  ❌ Save failed! Result: {save_result}")
            self.test_results.append({'name': name, 'passed': False, 'error': 'Save failed'})
            return
            
        # Try to retrieve
        retrieved, source = await self.finder.find_transcript(episode, mode)
        
        if expected_result:
            if retrieved and retrieved == transcript:
                print(f"  ✅ PASS: Retrieved {len(retrieved)} chars")
                self.test_results.append({'name': name, 'passed': True})
            else:
                print(f"  ❌ FAIL: Expected to find transcript but didn't")
                self.test_results.append({'name': name, 'passed': False, 'error': 'Not retrieved'})
        else:
            if not retrieved:
                print(f"  ✅ PASS: Correctly didn't find transcript")
                self.test_results.append({'name': name, 'passed': True})
            else:
                print(f"  ❌ FAIL: Found transcript when shouldn't have")
                self.test_results.append({'name': name, 'passed': False, 'error': 'Unexpected retrieval'})
    
    async def run_all_tests(self):
        """Run comprehensive test suite"""
        print("TRANSCRIPT CACHE REGRESSION TEST SUITE")
        print("="*60)
        
        # Test 1: Basic functionality
        await self.test_case(
            "Basic Full Mode",
            Episode(
                podcast="Test Podcast",
                title="Basic Episode",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/basic.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/basic",
                duration="1:00:00",
                guid="test-basic-guid"
            ),
            'full'
        )
        
        # Test 2: Test mode
        await self.test_case(
            "Basic Test Mode",
            Episode(
                podcast="Test Podcast",
                title="Test Mode Episode",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/test.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/test",
                duration="0:15:00",
                guid="test-test-mode-guid"
            ),
            'test'
        )
        
        # Test 3: No GUID
        await self.test_case(
            "Episode Without GUID",
            Episode(
                podcast="Test Podcast",
                title="No GUID Episode",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/noguid.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/noguid",
                duration="1:00:00",
                guid=None
            ),
            'full'
        )
        
        # Test 4: Special characters in title
        await self.test_case(
            "Special Characters",
            Episode(
                podcast="Test Podcast",
                title="Episode #123: Test's \"Special\" Characters & More!",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/special.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/special",
                duration="1:00:00",
                guid="test-special-chars"
            ),
            'full'
        )
        
        # Test 5: Very long title
        await self.test_case(
            "Long Title",
            Episode(
                podcast="Test Podcast",
                title="Episode with " + "very long title " * 50,
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/long.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/long",
                duration="1:00:00",
                guid="test-long-title"
            ),
            'full'
        )
        
        # Test 6: Date without timezone
        await self.test_case(
            "No Timezone Date",
            Episode(
                podcast="Test Podcast",
                title="No TZ Episode",
                published=datetime.now().replace(tzinfo=None),
                audio_url="https://example.com/notz.mp3",
                transcript_url=None,
                description="Test",
                link="https://example.com/notz",
                duration="1:00:00",
                guid="test-no-tz"
            ),
            'full'
        )
        
        # Test 7: Cross-mode retrieval (should fail)
        episode_cross = Episode(
            podcast="Test Podcast",
            title="Cross Mode Episode",
            published=datetime.now(timezone.utc),
            audio_url="https://example.com/cross.mp3",
            transcript_url=None,
            description="Test",
            link="https://example.com/cross",
            duration="1:00:00",
            guid="test-cross-mode"
        )
        
        # Save in test mode
        self.db.save_episode(
            episode=episode_cross,
            transcript="Test mode transcript",
            transcript_source=TranscriptSource.AUDIO_TRANSCRIPTION,
            transcription_mode='test'
        )
        
        # Try to retrieve in full mode (should fail)
        await self.test_case(
            "Cross-mode Retrieval",
            episode_cross,
            'full',
            expected_result=False
        )
        
        # Test 8: Real podcast names
        for podcast_name in ["The Tim Ferriss Show", "All-In Podcast", "We Study Billionaires"]:
            await self.test_case(
                f"Real Podcast: {podcast_name}",
                Episode(
                    podcast=podcast_name,
                    title=f"Episode #100: Test Episode",
                    published=datetime.now(timezone.utc) - timedelta(days=1),
                    audio_url="https://example.com/real.mp3",
                    transcript_url=None,
                    description="Test",
                    link="https://example.com/real",
                    duration="1:30:00",
                    guid=f"test-{podcast_name.lower().replace(' ', '-')}-100"
                ),
                'full'
            )
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for r in self.test_results if r['passed'])
        total = len(self.test_results)
        
        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {total - passed}")
        
        if passed < total:
            print("\nFailed tests:")
            for result in self.test_results:
                if not result['passed']:
                    print(f"  - {result['name']}: {result.get('error', 'Unknown error')}")
        
        return passed == total
    
    async def cleanup(self):
        """Cleanup resources"""
        await self.finder.cleanup()

async def main():
    test = TranscriptCacheTest()
    try:
        success = await test.run_all_tests()
        return 0 if success else 1
    finally:
        await test.cleanup()

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)