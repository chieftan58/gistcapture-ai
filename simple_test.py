#!/usr/bin/env python3
"""
SIMPLE TEST FOR RENAISSANCE WEEKLY
==================================

This is a simple test to verify the system works.
Just run: python simple_test.py

It tests the most basic functionality without any complexity.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add the project to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_episode_creation():
    """Test 1: Can we create an Episode?"""
    print("✓ Test 1: Creating an Episode object...")
    try:
        from renaissance_weekly.models import Episode
        
        episode = Episode(
            podcast="Test Podcast",
            title="Test Episode",
            published=datetime.now(timezone.utc),
            audio_url="https://example.com/test.mp3"
        )
        
        assert episode.podcast == "Test Podcast"
        assert episode.title == "Test Episode"
        assert episode.audio_url == "https://example.com/test.mp3"
        
        print("  ✅ SUCCESS: Episode created correctly!")
        return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


def test_database_creation():
    """Test 2: Can we create a database?"""
    print("\n✓ Test 2: Creating a test database...")
    try:
        from renaissance_weekly.database import PodcastDatabase
        from pathlib import Path
        import tempfile
        
        # Create temporary database
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = PodcastDatabase(db_path)
            
            # Check database file exists
            assert db_path.exists()
            
            print("  ✅ SUCCESS: Database created!")
            return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


def test_save_and_get_episode():
    """Test 3: Can we save and retrieve an episode?"""
    print("\n✓ Test 3: Saving and retrieving an episode...")
    try:
        from renaissance_weekly.database import PodcastDatabase
        from renaissance_weekly.models import Episode
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create database
            db_path = Path(tmpdir) / "test.db"
            db = PodcastDatabase(db_path)
            
            # Create episode
            episode = Episode(
                podcast="Test Show",
                title="Episode 1",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/ep1.mp3",
                description="This is a test episode"
            )
            
            # Save it
            db.save_episode(episode)
            
            # Get it back
            retrieved = db.get_episode(
                episode.podcast,
                episode.title,
                episode.published
            )
            
            # Check we got it
            assert retrieved is not None
            assert retrieved['title'] == "Episode 1"
            assert retrieved['podcast'] == "Test Show"
            
            print("  ✅ SUCCESS: Episode saved and retrieved!")
            return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


def test_date_filtering():
    """Test 4: Can we filter episodes by date?"""
    print("\n✓ Test 4: Testing date filtering...")
    try:
        from renaissance_weekly.database import PodcastDatabase
        from renaissance_weekly.models import Episode
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = PodcastDatabase(db_path)
            
            now = datetime.now(timezone.utc)
            
            # Create old episode (10 days ago)
            old_episode = Episode(
                podcast="Test Show",
                title="Old Episode",
                published=now - timedelta(days=10),
                audio_url="https://example.com/old.mp3"
            )
            
            # Create recent episode (2 days ago)
            recent_episode = Episode(
                podcast="Test Show", 
                title="Recent Episode",
                published=now - timedelta(days=2),
                audio_url="https://example.com/recent.mp3"
            )
            
            # Save both
            db.save_episode(old_episode)
            db.save_episode(recent_episode)
            
            # Get episodes from last 7 days
            recent = db.get_recent_episodes(days_back=7)
            
            # Should only get the recent one
            assert len(recent) == 1
            assert recent[0]['title'] == "Recent Episode"
            
            print("  ✅ SUCCESS: Date filtering works!")
            return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


def test_config_loading():
    """Test 5: Can we load configuration?"""
    print("\n✓ Test 5: Loading configuration...")
    try:
        from renaissance_weekly.config import PODCAST_CONFIGS
        
        # Check we have some podcasts configured
        assert len(PODCAST_CONFIGS) > 0
        
        # Check first podcast has required fields
        first_podcast = PODCAST_CONFIGS[0]
        assert "name" in first_podcast
        assert "apple_id" in first_podcast or "apple_url" in first_podcast
        assert "rss_feeds" in first_podcast
        
        # Find Tim Ferriss if it exists
        podcast_names = [p["name"] for p in PODCAST_CONFIGS]
        
        print(f"  ✅ SUCCESS: Found {len(PODCAST_CONFIGS)} podcasts configured!")
        print(f"     Including: {', '.join(podcast_names[:3])}...")
        return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        return False


def main():
    """Run all simple tests"""
    print("=" * 60)
    print("RENAISSANCE WEEKLY - SIMPLE TEST SUITE")
    print("=" * 60)
    print("\nThis will run 5 simple tests to verify the system works.\n")
    
    tests = [
        test_episode_creation,
        test_database_creation,
        test_save_and_get_episode,
        test_date_filtering,
        test_config_loading
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    print(f"\nTests passed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! The system is working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed. Check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())