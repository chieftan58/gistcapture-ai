"""Unit tests for episode fetching"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import feedparser

from renaissance_weekly.fetchers.episode_fetcher import EpisodeFetcher
from renaissance_weekly.models import Episode


class TestEpisodeFetcher:
    """Test episode fetching functionality"""
    
    @pytest.fixture
    def fetcher(self):
        """Create episode fetcher instance"""
        return EpisodeFetcher()
    
    @pytest.fixture
    def mock_rss_feed(self):
        """Create mock RSS feed data"""
        now = datetime.now(timezone.utc)
        return {
            'feed': {
                'title': 'Test Podcast'
            },
            'entries': [
                {
                    'title': 'Recent Episode',
                    'published_parsed': (now - timedelta(days=2)).timetuple(),
                    'enclosures': [{'url': 'https://example.com/recent.mp3', 'type': 'audio/mpeg'}],
                    'summary': 'Recent episode description',
                    'link': 'https://example.com/recent',
                    'id': 'recent-123'
                },
                {
                    'title': 'Old Episode',
                    'published_parsed': (now - timedelta(days=10)).timetuple(),
                    'enclosures': [{'url': 'https://example.com/old.mp3', 'type': 'audio/mpeg'}],
                    'summary': 'Old episode description',
                    'link': 'https://example.com/old',
                    'id': 'old-456'
                }
            ]
        }
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_fetch_episodes_basic(self, mock_parse, fetcher, mock_rss_feed):
        """Test basic episode fetching"""
        mock_parse.return_value = mock_rss_feed
        
        episodes = fetcher.fetch_episodes("Test Podcast", days=7)
        
        # Should only get recent episode
        assert len(episodes) == 1
        assert episodes[0].title == "Recent Episode"
        assert episodes[0].podcast == "Test Podcast"
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_fetch_episodes_date_filtering(self, mock_parse, fetcher, mock_rss_feed):
        """Test date filtering works correctly"""
        mock_parse.return_value = mock_rss_feed
        
        # Get episodes from last 30 days
        episodes = fetcher.fetch_episodes("Test Podcast", days=30)
        
        # Should get both episodes
        assert len(episodes) == 2
        
        # Get episodes from last 5 days
        episodes = fetcher.fetch_episodes("Test Podcast", days=5)
        
        # Should only get recent episode
        assert len(episodes) == 1
        assert episodes[0].title == "Recent Episode"
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_handle_missing_fields(self, mock_parse, fetcher):
        """Test handling of RSS entries with missing fields"""
        now = datetime.now(timezone.utc)
        mock_feed = {
            'feed': {'title': 'Test Podcast'},
            'entries': [
                {
                    'title': 'Episode without audio',
                    'published_parsed': now.timetuple(),
                    # No enclosures
                    'summary': 'Description',
                    'link': 'https://example.com/ep1'
                },
                {
                    'title': 'Episode with audio',
                    'published_parsed': now.timetuple(),
                    'enclosures': [{'url': 'https://example.com/ep2.mp3'}],
                    'summary': 'Description',
                    'link': 'https://example.com/ep2'
                }
            ]
        }
        mock_parse.return_value = mock_feed
        
        episodes = fetcher.fetch_episodes("Test Podcast", days=7)
        
        # Should only get episode with audio
        assert len(episodes) == 1
        assert episodes[0].title == "Episode with audio"
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_handle_parse_errors(self, mock_parse, fetcher):
        """Test handling of RSS parse errors"""
        # Simulate parse error
        mock_parse.side_effect = Exception("Parse error")
        
        episodes = fetcher.fetch_episodes("Test Podcast", days=7)
        
        # Should return empty list, not crash
        assert episodes == []
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_large_feed_handling(self, mock_parse, fetcher):
        """Test handling of large RSS feeds"""
        # Create a feed with many entries
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(100):
            entries.append({
                'title': f'Episode {i}',
                'published_parsed': (now - timedelta(days=i)).timetuple(),
                'enclosures': [{'url': f'https://example.com/ep{i}.mp3'}],
                'summary': f'Description {i}',
                'link': f'https://example.com/ep{i}',
                'id': f'ep-{i}'
            })
        
        mock_feed = {
            'feed': {'title': 'Test Podcast'},
            'entries': entries
        }
        mock_parse.return_value = mock_feed
        
        # Fetch with 7 day limit
        episodes = fetcher.fetch_episodes("Test Podcast", days=7)
        
        # Should only get episodes from last 7 days
        assert len(episodes) <= 8  # 0-7 days
        assert all(e.title.startswith("Episode") for e in episodes)
    
    @pytest.mark.unit
    def test_episode_deduplication(self, fetcher):
        """Test that duplicate episodes are handled"""
        episodes = [
            Episode(
                podcast="Test",
                title="Episode 1",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/1.mp3"
            ),
            Episode(
                podcast="Test",
                title="Episode 1",  # Duplicate title
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/1-dup.mp3"
            ),
            Episode(
                podcast="Test",
                title="Episode 2",
                published=datetime.now(timezone.utc),
                audio_url="https://example.com/2.mp3"
            )
        ]
        
        # Apply deduplication logic
        unique = fetcher._deduplicate_episodes(episodes)
        
        assert len(unique) == 2
        assert {e.title for e in unique} == {"Episode 1", "Episode 2"}
    
    @pytest.mark.unit
    @patch('requests.get')
    def test_apple_podcasts_fallback(self, mock_get, fetcher):
        """Test Apple Podcasts API fallback"""
        # Mock Apple Podcasts API response
        mock_response = Mock()
        mock_response.json.return_value = {
            'results': [{
                'feedUrl': 'https://example.com/feed.xml'
            }]
        }
        mock_get.return_value = mock_response
        
        # Test getting feed URL from Apple ID
        feed_url = fetcher._get_feed_from_apple_id("123456789")
        
        assert feed_url == 'https://example.com/feed.xml'
        mock_get.assert_called_once()
    
    @pytest.mark.unit
    def test_smart_date_parsing(self, fetcher):
        """Test various date format parsing"""
        test_dates = [
            "Wed, 10 Jan 2025 10:00:00 GMT",
            "2025-01-10T10:00:00Z",
            "10 Jan 2025 10:00:00 +0000",
            "January 10, 2025"
        ]
        
        for date_str in test_dates:
            parsed = fetcher._parse_date(date_str)
            assert parsed is not None
            assert isinstance(parsed, datetime)
    
    @pytest.mark.unit
    @patch('feedparser.parse')
    def test_streaming_large_feeds(self, mock_parse, fetcher):
        """Test streaming approach for large feeds"""
        # Simulate a very large feed (>10MB)
        large_feed_content = "x" * (10 * 1024 * 1024)  # 10MB
        
        mock_parse.return_value = {
            'feed': {'title': 'Large Podcast'},
            'entries': []
        }
        
        with patch('requests.head') as mock_head:
            mock_head.return_value.headers = {'Content-Length': str(len(large_feed_content))}
            
            # Should handle large feed gracefully
            episodes = fetcher.fetch_episodes("Large Podcast", days=7)
            assert isinstance(episodes, list)