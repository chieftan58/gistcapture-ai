"""Unit tests for database operations"""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from tests.conftest import create_episode, create_sample_episodes


class TestPodcastDatabase:
    """Test database operations"""
    
    @pytest.mark.unit
    def test_database_initialization(self, temp_dir):
        """Test database creates tables correctly"""
        import sqlite3
        db_path = temp_dir / "test.db"
        db = PodcastDatabase(db_path)
        
        assert db_path.exists()
        
        # Verify tables exist
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='episodes'
            """)
            assert cursor.fetchone() is not None
    
    @pytest.mark.unit
    def test_save_and_retrieve_episode(self, test_db):
        """Test saving and retrieving episodes"""
        episode = create_episode()
        
        # Save episode
        test_db.save_episode(episode)
        
        # Retrieve episode
        retrieved = test_db.get_episode(
            episode.podcast, 
            episode.title, 
            episode.published
        )
        
        assert retrieved is not None
        assert retrieved.podcast == episode.podcast
        assert retrieved.title == episode.title
        assert retrieved.audio_url == episode.audio_url
    
    @pytest.mark.unit
    def test_episode_exists(self, test_db):
        """Test checking if episode exists"""
        episode = create_episode()
        
        # Should not exist initially
        assert not test_db.episode_exists(
            episode.podcast,
            episode.title,
            episode.published
        )
        
        # Save episode
        test_db.save_episode(episode)
        
        # Should exist now
        assert test_db.episode_exists(
            episode.podcast,
            episode.title,
            episode.published
        )
    
    @pytest.mark.unit
    def test_get_episodes_by_date_range(self, test_db):
        """Test retrieving episodes within date range"""
        now = datetime.now(timezone.utc)
        
        # Create episodes at different times
        old_episode = Episode(
            podcast="Test Podcast",
            title="Old Episode",
            published=now - timedelta(days=10),
            audio_url="https://example.com/old.mp3"
        )
        recent_episode = Episode(
            podcast="Test Podcast",
            title="Recent Episode",
            published=now - timedelta(days=2),
            audio_url="https://example.com/recent.mp3"
        )
        
        test_db.save_episode(old_episode)
        test_db.save_episode(recent_episode)
        
        # Get episodes from last 7 days
        episodes = test_db.get_episodes_needing_processing(days=7)
        
        # Should only get recent episode
        assert len(episodes) == 1
        assert episodes[0].title == "Recent Episode"
    
    @pytest.mark.unit
    def test_save_and_get_transcript(self, test_db):
        """Test transcript operations"""
        episode = create_episode()
        test_db.save_episode(episode)
        
        transcript = "This is a test transcript."
        
        # Save transcript
        test_db.save_transcript(
            episode.podcast,
            episode.title,
            transcript,
            TranscriptSource.AUDIO_TRANSCRIPTION
        )
        
        # Retrieve transcript
        retrieved = test_db.get_transcript(
            episode.podcast,
            episode.title,
            'test'  # mode
        )
        
        assert retrieved == transcript
    
    @pytest.mark.unit
    def test_save_and_get_summary(self, test_db):
        """Test summary operations"""
        episode = create_episode()
        test_db.save_episode(episode)
        
        summary = "This is a test summary."
        
        # Save summary
        test_db.save_summary(
            episode.podcast,
            episode.title,
            summary,
            'test'  # mode
        )
        
        # Retrieve summary
        retrieved = test_db.get_episode_summary(
            episode.podcast,
            episode.title,
            episode.published,
            'test'
        )
        
        assert retrieved == summary
    
    @pytest.mark.unit
    def test_mode_separation(self, test_db):
        """Test that test and full modes are separated"""
        episode = create_episode()
        test_db.save_episode(episode)
        
        # Save different summaries for different modes
        test_summary = "Test mode summary"
        full_summary = "Full mode summary"
        
        test_db.save_summary(
            episode.podcast,
            episode.title,
            test_summary,
            'test'
        )
        
        test_db.save_summary(
            episode.podcast,
            episode.title,
            full_summary,
            'full'
        )
        
        # Retrieve by mode
        assert test_db.get_episode_summary(
            episode.podcast,
            episode.title,
            episode.published,
            'test'
        ) == test_summary
        
        assert test_db.get_episode_summary(
            episode.podcast,
            episode.title,
            episode.published,
            'full'
        ) == full_summary
    
    @pytest.mark.unit
    def test_update_episode_status(self, test_db):
        """Test updating episode processing status"""
        import sqlite3
        episode = create_episode()
        test_db.save_episode(episode)
        
        # Update status
        test_db.update_episode_status(
            episode.podcast,
            episode.title,
            'processing',
            failure_reason='Test failure',
            retry_count=1
        )
        
        # Verify update
        with sqlite3.connect(test_db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT processing_status, failure_reason, retry_count
                FROM episodes
                WHERE podcast = ? AND title = ?
            """, (episode.podcast, episode.title))
            
            row = cursor.fetchone()
            assert row[0] == 'processing'
            assert row[1] == 'Test failure'
            assert row[2] == 1
    
    @pytest.mark.unit
    def test_get_failed_episodes(self, test_db):
        """Test retrieving failed episodes by error type"""
        # Create episodes with different failure reasons
        for i, reason in enumerate(['cloudflare_403', 'timeout', 'transcription_failed']):
            episode = Episode(
                podcast="Test Podcast",
                title=f"Episode {i}",
                published=datetime.now(timezone.utc),
                audio_url=f"https://example.com/{i}.mp3"
            )
            test_db.save_episode(episode)
            test_db.update_episode_status(
                episode.podcast,
                episode.title,
                'failed',
                failure_reason=reason
            )
        
        # Get failed episodes
        failed = test_db.get_failed_episodes()
        
        assert 'cloudflare_403' in failed
        assert len(failed['cloudflare_403']) == 1
        assert 'timeout' in failed
        assert len(failed['timeout']) == 1
        assert 'transcription_failed' in failed
        assert len(failed['transcription_failed']) == 1
    
    @pytest.mark.unit
    def test_get_last_episode_info(self, test_db):
        """Test getting last episode info for podcasts"""
        now = datetime.now(timezone.utc)
        
        # Create episodes for different podcasts
        podcasts = ["Podcast A", "Podcast B", "Podcast C"]
        for i, podcast in enumerate(podcasts):
            episode = Episode(
                podcast=podcast,
                title=f"Latest Episode of {podcast}",
                published=now - timedelta(days=i*5),
                audio_url=f"https://example.com/{podcast}.mp3"
            )
            test_db.save_episode(episode)
        
        # Get last episode info
        info = test_db.get_last_episode_info(podcasts)
        
        assert len(info) == 3
        assert info["Podcast A"]['title'] == "Latest Episode of Podcast A"
        assert info["Podcast B"]['title'] == "Latest Episode of Podcast B"
        assert info["Podcast C"]['title'] == "Latest Episode of Podcast C"
    
    @pytest.mark.unit
    def test_concurrent_access(self, test_db):
        """Test database handles concurrent access"""
        import threading
        
        episodes = create_sample_episodes(10)
        errors = []
        
        def save_episodes():
            try:
                for episode in episodes:
                    test_db.save_episode(episode)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=save_episodes) for _ in range(5)]
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Should have no errors
        assert len(errors) == 0
        
        # Verify episodes saved (may have duplicates due to unique constraint)
        all_episodes = test_db.get_episodes_needing_processing(days=30)
        assert len(all_episodes) > 0