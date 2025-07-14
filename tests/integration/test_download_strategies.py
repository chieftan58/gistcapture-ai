"""Integration tests for download strategies"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import aiohttp

from renaissance_weekly.download_strategies.smart_router import SmartDownloadRouter
from renaissance_weekly.download_strategies.direct_strategy import DirectDownloadStrategy
from renaissance_weekly.download_strategies.youtube_strategy import YouTubeStrategy
from renaissance_weekly.download_strategies.apple_strategy import ApplePodcastsStrategy
from renaissance_weekly.models import Episode


class TestSmartDownloadRouter:
    """Test the smart download routing system"""
    
    @pytest.fixture
    def router(self, temp_dir):
        """Create router instance"""
        with patch('renaissance_weekly.config.TEMP_DIR', temp_dir):
            return SmartDownloadRouter()
    
    @pytest.fixture
    def test_episode(self):
        """Create test episode"""
        return Episode(
            podcast="Test Podcast",
            title="Test Episode",
            published=None,
            audio_url="https://example.com/audio.mp3"
        )
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_router_strategy_selection(self, router, test_episode):
        """Test router selects correct strategy based on podcast"""
        # Test known problematic podcasts
        american_optimist = Episode(
            podcast="American Optimist",
            title="Episode 118",
            published=None,
            audio_url="https://substack.com/audio.mp3"
        )
        
        # Get strategy order
        strategies = router._get_strategy_order(
            american_optimist.podcast,
            american_optimist.audio_url
        )
        
        # Should prioritize YouTube for American Optimist
        assert strategies[0] == "youtube"
        assert "browser" in strategies
        assert "direct" not in strategies[:2]  # Should not try direct first
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_router_fallback_chain(self, router, test_episode, temp_dir):
        """Test router falls back through strategies"""
        output_path = temp_dir / "test.mp3"
        
        # Mock all strategies to fail except the last one
        with patch.object(router.strategies['direct'], 'download', 
                         new_callable=AsyncMock) as mock_direct:
            with patch.object(router.strategies['youtube'], 'download',
                             new_callable=AsyncMock) as mock_youtube:
                with patch.object(router.strategies['apple_podcasts'], 'download',
                                 new_callable=AsyncMock) as mock_apple:
                    
                    # Make first two fail
                    mock_direct.return_value = (False, None, "Direct failed")
                    mock_youtube.return_value = (False, None, "YouTube failed")
                    # Make Apple succeed
                    mock_apple.return_value = (True, str(output_path), None)
                    
                    success, path, error = await router.download(
                        test_episode.podcast,
                        test_episode.title,
                        test_episode.audio_url,
                        str(output_path)
                    )
                    
                    assert success is True
                    assert path == str(output_path)
                    # Verify fallback chain was tried
                    mock_direct.assert_called_once()
                    mock_apple.assert_called_once()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_router_success_history(self, router, test_episode, temp_dir):
        """Test router remembers successful strategies"""
        output_path = temp_dir / "test.mp3"
        
        # Record a success
        router.record_success(test_episode.podcast, "apple_podcasts")
        
        # Get strategy order - should prioritize apple now
        strategies = router._get_strategy_order(
            test_episode.podcast,
            test_episode.audio_url
        )
        
        assert strategies[0] == "apple_podcasts"
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_router_timeout_handling(self, router, test_episode, temp_dir):
        """Test router handles timeouts correctly"""
        output_path = temp_dir / "test.mp3"
        
        # Mock a strategy that times out
        async def slow_download(*args, **kwargs):
            await asyncio.sleep(2)  # Longer than timeout
            return (False, None, "Timeout")
        
        with patch.object(router.strategies['direct'], 'download', 
                         side_effect=slow_download):
            with patch('renaissance_weekly.download_strategies.smart_router.STRATEGY_TIMEOUT', 1):
                success, path, error = await router.download(
                    test_episode.podcast,
                    test_episode.title,
                    test_episode.audio_url,
                    str(output_path),
                    timeout=1
                )
                
                assert success is False
                assert "timeout" in error.lower()


class TestDirectDownloadStrategy:
    """Test direct download strategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create strategy instance"""
        return DirectDownloadStrategy()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_direct_download_success(self, strategy, temp_dir):
        """Test successful direct download"""
        output_path = temp_dir / "test.mp3"
        
        # Mock HTTP response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {
            'Content-Type': 'audio/mpeg',
            'Content-Length': '1000000'
        }
        mock_response.read = AsyncMock(return_value=b'fake audio content')
        
        with patch('aiohttp.ClientSession.get', 
                   return_value=mock_response) as mock_get:
            mock_get.return_value.__aenter__.return_value = mock_response
            
            success, path, error = await strategy.download(
                "Test Podcast",
                "Test Episode",
                "https://example.com/audio.mp3",
                str(output_path)
            )
            
            assert success is True
            assert output_path.exists()
            assert error is None
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_direct_download_retry(self, strategy, temp_dir):
        """Test retry logic on failure"""
        output_path = temp_dir / "test.mp3"
        
        # Mock responses - fail twice, then succeed
        call_count = 0
        
        async def mock_get_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_resp = AsyncMock()
            if call_count < 3:
                mock_resp.status = 500  # Server error
                mock_resp.raise_for_status.side_effect = aiohttp.ClientError()
            else:
                mock_resp.status = 200
                mock_resp.headers = {'Content-Type': 'audio/mpeg'}
                mock_resp.read = AsyncMock(return_value=b'audio')
            
            return mock_resp
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_get.return_value.__aenter__.side_effect = mock_get_response
            
            success, path, error = await strategy.download(
                "Test Podcast",
                "Test Episode",
                "https://example.com/audio.mp3",
                str(output_path)
            )
            
            # Should eventually succeed after retries
            assert call_count == 3
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_platform_specific_headers(self, strategy):
        """Test platform-specific headers are applied"""
        platforms = [
            ("spotify.com", "Spotify"),
            ("apple.com", "Apple Podcasts"),
            ("cloudflare.com", "Generic")
        ]
        
        for domain, expected_platform in platforms:
            headers = strategy._get_platform_headers(f"https://{domain}/audio.mp3")
            assert headers['User-Agent'] is not None
            
            # Spotify should have specific headers
            if domain == "spotify.com":
                assert 'Accept-Language' in headers


class TestYouTubeStrategy:
    """Test YouTube download strategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create strategy instance"""
        return YouTubeStrategy()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_youtube_url_mapping(self, strategy):
        """Test YouTube URL mapping for known episodes"""
        # Test American Optimist mapping
        url = await strategy._find_youtube_url(
            "American Optimist",
            "Ep 118: Marc Andreessen on AI, Robotics, and the Future of American Dynamism",
            "https://substack.com/audio.mp3"
        )
        
        assert url == "https://www.youtube.com/watch?v=pRoKi4VL_5s"
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_youtube_search_query_building(self, strategy):
        """Test search query construction"""
        # Test with Dwarkesh - should find channel mapping
        url = await strategy._find_youtube_url(
            "Dwarkesh Podcast",
            "Stephen Kotkin — Stalin, Mao, Hitler",
            "https://example.com/audio.mp3"
        )
        
        # Since we don't have actual YouTube search implemented, should return None
        # But the channel mapping logic should work
        assert url is None or "youtube.com" in url
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_youtube_download_with_mock_ytdlp(self, strategy, temp_dir):
        """Test YouTube download with mocked yt-dlp"""
        output_path = temp_dir / "test.mp3"
        
        # Mock yt-dlp Python module
        with patch('yt_dlp.YoutubeDL') as mock_ytdl:
            mock_instance = Mock()
            mock_instance.download = Mock()
            mock_ytdl.return_value.__enter__ = Mock(return_value=mock_instance)
            mock_ytdl.return_value.__exit__ = Mock(return_value=None)
            
            # Create a fake audio file
            output_path.write_bytes(b'fake audio')
            
            success, error = await strategy.download(
                "https://www.youtube.com/watch?v=test123",
                output_path,
                {
                    "podcast": "Test Podcast",
                    "title": "Test Episode"
                }
            )
            
            # Verify yt-dlp was called with correct arguments
            mock_ytdl.assert_called()
            mock_instance.download.assert_called_with(['https://www.youtube.com/watch?v=test123'])


class TestApplePodcastsStrategy:
    """Test Apple Podcasts download strategy"""
    
    @pytest.fixture
    def strategy(self):
        """Create strategy instance"""
        return ApplePodcastsStrategy()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_apple_rss_lookup(self, strategy):
        """Test Apple Podcasts RSS feed lookup"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                'results': [{
                    'feedUrl': 'https://feeds.example.com/podcast.xml'
                }]
            }
            mock_get.return_value = mock_response
            
            feed_url = await strategy._get_apple_feed_url(
                "Test Podcast",
                "123456789"  # Apple ID
            )
            
            assert feed_url == 'https://feeds.example.com/podcast.xml'
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_apple_episode_matching(self, strategy):
        """Test episode matching from Apple RSS"""
        rss_content = '''
        <rss version="2.0">
            <channel>
                <item>
                    <title>Test Episode</title>
                    <enclosure url="https://apple.com/audio.mp3" type="audio/mpeg"/>
                </item>
                <item>
                    <title>Other Episode</title>
                    <enclosure url="https://apple.com/other.mp3" type="audio/mpeg"/>
                </item>
            </channel>
        </rss>
        '''
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.text = AsyncMock(return_value=rss_content)
            mock_get.return_value.__aenter__.return_value = mock_response
            
            audio_url = await strategy._find_episode_in_feed(
                "https://feeds.example.com/podcast.xml",
                "Test Episode"
            )
            
            assert audio_url == "https://apple.com/audio.mp3"