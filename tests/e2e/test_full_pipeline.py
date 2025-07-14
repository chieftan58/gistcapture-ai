"""End-to-end tests for the complete Renaissance Weekly pipeline"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.models import Episode
from renaissance_weekly.config import PODCAST_CONFIGS


class TestFullPipeline:
    """Test complete processing pipeline"""
    
    @pytest.fixture
    def app(self, mock_config, test_db):
        """Create app instance with mocked dependencies"""
        app = RenaissanceWeekly()
        app.db = test_db
        return app
    
    @pytest.fixture
    def mock_episodes(self):
        """Create mock episodes for testing"""
        now = datetime.now(timezone.utc)
        return [
            Episode(
                podcast="The Tim Ferriss Show",
                title="Episode 1: Test Guest",
                published=now - timedelta(days=2),
                audio_url="https://example.com/tim1.mp3",
                description="Great conversation about productivity"
            ),
            Episode(
                podcast="Lex Fridman",
                title="Episode 2: AI Research",
                published=now - timedelta(days=3),
                audio_url="https://example.com/lex1.mp3",
                description="Deep dive into artificial intelligence"
            )
        ]
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_complete_pipeline_success(
        self, app, mock_episodes, mock_openai, mock_assemblyai, mock_sendgrid, temp_dir
    ):
        """Test successful end-to-end pipeline execution"""
        
        # Mock episode fetching
        with patch.object(app, '_fetch_episodes', return_value=mock_episodes):
            # Mock download manager
            with patch('renaissance_weekly.download_manager.DownloadManager') as mock_dm:
                mock_dm_instance = mock_dm.return_value
                mock_dm_instance.download_episodes = AsyncMock(return_value={
                    'success': [e.to_dict() for e in mock_episodes],
                    'failed': []
                })
                
                # Mock transcript finder
                with patch('renaissance_weekly.transcripts.comprehensive_finder.ComprehensiveTranscriptFinder') as mock_tf:
                    mock_tf_instance = mock_tf.return_value
                    mock_tf_instance.find_transcript = AsyncMock(
                        return_value=("Test transcript content", "test_source")
                    )
                    
                    # Mock OpenAI
                    with patch('openai.AsyncOpenAI', return_value=mock_openai):
                        # Mock SendGrid
                        with patch('sendgrid.SendGridAPIClient', return_value=mock_sendgrid):
                            # Run pipeline
                            summaries = await app.run(
                                days=7,
                                selected_podcasts=["The Tim Ferriss Show", "Lex Fridman"],
                                mode='test'
                            )
                            
                            # Verify results
                            assert len(summaries) == 2
                            assert all("Executive Summary" in s for s in summaries.values())
                            
                            # Verify email was sent
                            mock_sendgrid.send.assert_called_once()
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pipeline_with_failures(
        self, app, mock_episodes, mock_openai, temp_dir
    ):
        """Test pipeline handles partial failures gracefully"""
        
        # Add a failing episode
        failing_episode = Episode(
            podcast="American Optimist",
            title="Protected Episode",
            published=datetime.now(timezone.utc) - timedelta(days=1),
            audio_url="https://substack.com/protected.mp3"
        )
        all_episodes = mock_episodes + [failing_episode]
        
        with patch.object(app, '_fetch_episodes', return_value=all_episodes):
            with patch('renaissance_weekly.download_manager.DownloadManager') as mock_dm:
                # Mock partial download success
                mock_dm_instance = mock_dm.return_value
                mock_dm_instance.download_episodes = AsyncMock(return_value={
                    'success': [e.to_dict() for e in mock_episodes],
                    'failed': [{
                        **failing_episode.to_dict(),
                        'error': 'Cloudflare protection (403)'
                    }]
                })
                
                # Continue with mocking...
                with patch('renaissance_weekly.transcripts.comprehensive_finder.ComprehensiveTranscriptFinder') as mock_tf:
                    mock_tf_instance = mock_tf.return_value
                    mock_tf_instance.find_transcript = AsyncMock(
                        return_value=("Test transcript", "test_source")
                    )
                    
                    with patch('openai.AsyncOpenAI', return_value=mock_openai):
                        summaries = await app.run(
                            days=7,
                            selected_podcasts=["The Tim Ferriss Show", "Lex Fridman", "American Optimist"],
                            mode='test',
                            skip_email=True  # Skip email for this test
                        )
                        
                        # Should process successful episodes
                        assert len(summaries) == 2
                        assert "American Optimist" not in summaries
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pipeline_caching(self, app, mock_episodes, test_db):
        """Test pipeline uses cached data correctly"""
        
        # Pre-populate cache with summaries
        for episode in mock_episodes:
            test_db.save_episode(episode)
            test_db.save_transcript(
                episode.podcast,
                episode.title,
                "Cached transcript",
                "database"
            )
            test_db.save_summary(
                episode.podcast,
                episode.title,
                "**Executive Summary**: Cached summary",
                'test'
            )
        
        with patch.object(app, '_fetch_episodes', return_value=mock_episodes):
            # Mock OpenAI - should NOT be called due to caching
            mock_openai = MagicMock()
            with patch('openai.AsyncOpenAI', return_value=mock_openai):
                summaries = await app.run(
                    days=7,
                    selected_podcasts=["The Tim Ferriss Show", "Lex Fridman"],
                    mode='test',
                    skip_email=True
                )
                
                # Verify cached summaries used
                assert len(summaries) == 2
                assert all("Cached summary" in s for s in summaries.values())
                
                # OpenAI should not have been called
                mock_openai.chat.completions.create.assert_not_called()
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pipeline_concurrency(self, app, mock_openai):
        """Test pipeline handles concurrent processing correctly"""
        
        # Create many episodes to test concurrency
        episodes = []
        for i in range(20):
            episodes.append(Episode(
                podcast=f"Podcast {i % 5}",
                title=f"Episode {i}",
                published=datetime.now(timezone.utc) - timedelta(days=1),
                audio_url=f"https://example.com/ep{i}.mp3"
            ))
        
        processed_count = 0
        
        async def mock_process_episode(episode):
            nonlocal processed_count
            processed_count += 1
            await asyncio.sleep(0.1)  # Simulate processing time
            return f"Summary for {episode.title}"
        
        with patch.object(app, '_fetch_episodes', return_value=episodes):
            with patch.object(app, 'process_episode', side_effect=mock_process_episode):
                with patch('renaissance_weekly.app.ResourceAwareConcurrencyManager') as mock_cm:
                    # Allow higher concurrency for test
                    mock_cm.return_value.calculate_safe_concurrency.return_value = 10
                    
                    summaries = await app.run(
                        days=7,
                        selected_podcasts=[f"Podcast {i}" for i in range(5)],
                        mode='test',
                        skip_email=True
                    )
                    
                    # All episodes should be processed
                    assert processed_count == 20
                    assert len(summaries) == 20
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_pipeline_cancellation(self, app, mock_episodes):
        """Test pipeline cancellation works correctly"""
        
        processing_started = asyncio.Event()
        
        async def slow_process_episode(episode):
            processing_started.set()
            await asyncio.sleep(10)  # Long processing
            return "Should not reach here"
        
        with patch.object(app, '_fetch_episodes', return_value=mock_episodes):
            with patch.object(app, 'process_episode', side_effect=slow_process_episode):
                # Start processing in background
                process_task = asyncio.create_task(
                    app.run(
                        days=7,
                        selected_podcasts=["The Tim Ferriss Show"],
                        mode='test',
                        skip_email=True
                    )
                )
                
                # Wait for processing to start
                await processing_started.wait()
                
                # Cancel processing
                app.cancel_processing()
                
                # Task should complete quickly due to cancellation
                try:
                    await asyncio.wait_for(process_task, timeout=2.0)
                except asyncio.CancelledError:
                    pass  # Expected
                
                assert app._processing_cancelled is True
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_mode_separation(self, app, mock_episodes, test_db):
        """Test that test and full modes are properly separated"""
        
        episode = mock_episodes[0]
        
        # Save different data for different modes
        test_db.save_episode(episode)
        test_db.save_summary(episode.podcast, episode.title, "Test mode summary", 'test')
        test_db.save_summary(episode.podcast, episode.title, "Full mode summary", 'full')
        
        with patch.object(app, '_fetch_episodes', return_value=[episode]):
            # Run in test mode
            summaries_test = await app.run(
                days=7,
                selected_podcasts=[episode.podcast],
                mode='test',
                skip_email=True
            )
            
            # Run in full mode
            summaries_full = await app.run(
                days=7,
                selected_podcasts=[episode.podcast],
                mode='full',
                skip_email=True
            )
            
            # Verify correct summaries used
            assert "Test mode summary" in list(summaries_test.values())[0]
            assert "Full mode summary" in list(summaries_full.values())[0]
    
    @pytest.mark.e2e
    def test_health_check(self, app, mock_openai, mock_assemblyai):
        """Test system health check"""
        
        with patch('openai.OpenAI', return_value=mock_openai):
            with patch('assemblyai.Client', return_value=mock_assemblyai):
                # Should pass with all services available
                health = app.health_check()
                
                assert health['database'] is True
                assert health['openai'] is True
                assert health['assemblyai'] is True
                assert health['disk_space'] is True
                assert health['memory'] is True
    
    @pytest.mark.e2e
    def test_processing_time_estimation(self, app, mock_episodes, test_db):
        """Test processing time estimation"""
        
        # Mix of cached and new episodes
        for i, episode in enumerate(mock_episodes[:1]):
            test_db.save_episode(episode)
            test_db.save_summary(episode.podcast, episode.title, "Cached", 'test')
        
        estimate = app.estimate_processing_time(
            mock_episodes,
            mode='test',
            use_assemblyai=True
        )
        
        assert 'total_minutes' in estimate
        assert 'episodes_to_download' in estimate
        assert 'episodes_to_transcribe' in estimate
        assert 'episodes_to_summarize' in estimate
        
        # Cached episode should not need processing
        assert estimate['episodes_to_download'] == 1  # Only uncached episode