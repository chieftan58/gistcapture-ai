"""Shared test configuration and fixtures for Renaissance Weekly tests"""

import os
import sys
import json
import shutil
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from unittest.mock import Mock, MagicMock, AsyncMock

import pytest
import pytest_asyncio
from faker import Faker

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from renaissance_weekly.models import Episode, TranscriptSource
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.config import TESTING_MODE

# Initialize faker for test data generation
fake = Faker()


# ===== Configuration Fixtures =====

@pytest.fixture(scope="session")
def test_mode():
    """Ensure we're in testing mode"""
    original = os.environ.get('TESTING_MODE')
    os.environ['TESTING_MODE'] = 'true'
    yield True
    if original is not None:
        os.environ['TESTING_MODE'] = original
    else:
        os.environ.pop('TESTING_MODE', None)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config(temp_dir, monkeypatch):
    """Mock configuration values"""
    monkeypatch.setattr('renaissance_weekly.config.TEMP_DIR', temp_dir)
    monkeypatch.setattr('renaissance_weekly.config.DB_PATH', temp_dir / 'test.db')
    monkeypatch.setattr('renaissance_weekly.config.TESTING_MODE', True)
    return {
        'temp_dir': temp_dir,
        'db_path': temp_dir / 'test.db',
        'testing_mode': True
    }


# ===== Database Fixtures =====

@pytest.fixture
def test_db(mock_config):
    """Create a test database"""
    db_path = mock_config['db_path']
    db = PodcastDatabase(db_path)
    yield db
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def populated_db(test_db):
    """Database with sample episodes"""
    episodes = create_sample_episodes(10)
    for episode in episodes:
        test_db.save_episode(episode)
    # Add some with summaries
    for i in range(5):
        test_db.save_summary(
            episodes[i].podcast,
            episodes[i].title,
            f"Test summary for episode {i}",
            'test'
        )
    return test_db


# ===== Model Factories =====

def create_episode(
    podcast: str = None,
    title: str = None,
    published: datetime = None,
    audio_url: str = None,
    **kwargs
) -> Episode:
    """Factory for creating test episodes"""
    if published is None:
        # Random date within last 30 days
        days_ago = fake.random_int(min=0, max=30)
        published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    
    return Episode(
        podcast=podcast or fake.random_element([
            "The Tim Ferriss Show", "Lex Fridman", "Huberman Lab",
            "All-In", "Dwarkesh Podcast", "The Drive"
        ]),
        title=title or f"{fake.catch_phrase()} with {fake.name()}",
        published=published,
        audio_url=audio_url or fake.url(),
        transcript_url=kwargs.get('transcript_url'),
        description=kwargs.get('description', fake.paragraph()),
        link=kwargs.get('link', fake.url()),
        duration=kwargs.get('duration', f"{fake.random_int(30, 180)}:00"),
        guid=kwargs.get('guid', fake.uuid4())
    )


def create_sample_episodes(count: int = 5) -> List[Episode]:
    """Create multiple sample episodes"""
    return [create_episode() for _ in range(count)]


# ===== Mock Fixtures =====

@pytest.fixture
def mock_openai():
    """Mock OpenAI API responses"""
    mock = MagicMock()
    
    # Mock transcription
    mock.audio.transcriptions.create = AsyncMock(
        return_value=MagicMock(text="This is a test transcript. Speaker 1: Hello. Speaker 2: Hi there.")
    )
    
    # Mock chat completion
    mock.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="**Executive Summary**: This is a test summary with key insights."
                    )
                )
            ]
        )
    )
    
    return mock


@pytest.fixture
def mock_assemblyai():
    """Mock AssemblyAI responses"""
    mock = MagicMock()
    mock.Transcriber = MagicMock(return_value=MagicMock(
        transcribe=AsyncMock(return_value=MagicMock(
            status='completed',
            text="AssemblyAI transcript: Speaker 1 discusses important topics.",
            error=None
        ))
    ))
    return mock


@pytest.fixture
def mock_sendgrid():
    """Mock SendGrid email sending"""
    mock = MagicMock()
    mock.send = AsyncMock(return_value=MagicMock(
        status_code=202,
        body=b'',
        headers={'X-Message-Id': 'test-message-id'}
    ))
    return mock


@pytest.fixture
def mock_http_responses():
    """Mock HTTP responses for various services"""
    import responses
    
    # Mock RSS feeds
    rss_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Test Podcast</title>
            <item>
                <title>Test Episode</title>
                <pubDate>Wed, 10 Jan 2025 10:00:00 GMT</pubDate>
                <enclosure url="https://example.com/audio.mp3" type="audio/mpeg"/>
                <description>Test description</description>
                <guid>test-guid-123</guid>
            </item>
        </channel>
    </rss>'''
    
    with responses.RequestsMock() as rsps:
        # Mock RSS feeds
        rsps.add(
            responses.GET,
            "https://feeds.example.com/podcast",
            body=rss_content,
            content_type='application/rss+xml'
        )
        
        # Mock audio file download
        rsps.add(
            responses.GET,
            "https://example.com/audio.mp3",
            body=b'fake audio content',
            content_type='audio/mpeg',
            headers={'Content-Length': '1000000'}
        )
        
        yield rsps


# ===== Async Fixtures =====

@pytest_asyncio.fixture
async def async_client():
    """Async HTTP client for testing"""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        yield session


# ===== Test Data Fixtures =====

@pytest.fixture
def sample_transcript():
    """Sample transcript text"""
    return """
    Host: Welcome to the show. Today we're discussing artificial intelligence.
    
    Guest: Thanks for having me. AI is transforming every industry.
    
    Host: Can you give us some examples?
    
    Guest: Sure. In healthcare, AI is helping diagnose diseases earlier.
    In finance, it's detecting fraud in real-time.
    In education, it's personalizing learning experiences.
    
    Host: What about the risks?
    
    Guest: We need to consider bias, privacy, and job displacement.
    Responsible AI development is crucial.
    
    Host: Thank you for these insights.
    """


@pytest.fixture
def sample_summary():
    """Sample episode summary"""
    return """
    **Executive Summary**: Leading AI researcher discusses the transformative 
    impact of artificial intelligence across industries, emphasizing both 
    opportunities and challenges.
    
    **Key Topics**:
    - Healthcare applications: Early disease diagnosis
    - Financial sector: Real-time fraud detection
    - Education: Personalized learning experiences
    
    **Important Insights**:
    - AI adoption is accelerating across all sectors
    - Ethical considerations are paramount
    - Need for responsible development practices
    
    **Action Items**:
    - Evaluate AI opportunities in your industry
    - Consider ethical implications
    - Stay informed on AI developments
    """


@pytest.fixture
def podcast_configs():
    """Test podcast configurations"""
    return {
        "The Tim Ferriss Show": {
            "name": "The Tim Ferriss Show",
            "rss_url": "https://feeds.example.com/tim-ferriss",
            "apple_podcast_id": "863897795"
        },
        "Lex Fridman": {
            "name": "Lex Fridman",
            "rss_url": "https://feeds.example.com/lex-fridman",
            "apple_podcast_id": "1434243584"
        },
        "Test Podcast": {
            "name": "Test Podcast",
            "rss_url": "https://feeds.example.com/test",
            "apple_podcast_id": "123456789"
        }
    }


# ===== Performance Testing Fixtures =====

@pytest.fixture
def benchmark_timer():
    """Simple timer for performance tests"""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def __enter__(self):
            self.start_time = time.time()
            return self
        
        def __exit__(self, *args):
            self.end_time = time.time()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
    
    return Timer


# ===== Utility Functions =====

def assert_episode_equal(e1: Episode, e2: Episode, check_dates: bool = True):
    """Helper to compare episodes"""
    assert e1.podcast == e2.podcast
    assert e1.title == e2.title
    if check_dates:
        assert abs((e1.published - e2.published).total_seconds()) < 1
    assert e1.audio_url == e2.audio_url


async def wait_for_condition(condition_func, timeout: float = 5.0, interval: float = 0.1):
    """Wait for a condition to become true"""
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        if await condition_func():
            return True
        await asyncio.sleep(interval)
    return False


# ===== Cleanup =====

@pytest.fixture(autouse=True)
def cleanup_test_files(request, temp_dir):
    """Automatic cleanup of test files"""
    yield
    # Cleanup any stray test files
    patterns = ['test_*.mp3', 'test_*.json', '*.log']
    for pattern in patterns:
        for file in Path('.').glob(pattern):
            if file.is_file():
                file.unlink()