"""Testing utilities and helpers for Renaissance Weekly tests"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, AsyncMock

from renaissance_weekly.models import Episode


class TestDataGenerator:
    """Generate realistic test data"""
    
    @staticmethod
    def create_mock_openai_response(content: str = None) -> Dict:
        """Create mock OpenAI API response"""
        if content is None:
            content = """
            **Executive Summary**: This episode explores cutting-edge developments 
            in artificial intelligence and their implications for society.
            
            **Key Topics**:
            - Large language models and their capabilities
            - AI safety and alignment challenges
            - Economic impacts of automation
            
            **Notable Insights**:
            - AI development is accelerating faster than expected
            - Need for proactive governance frameworks
            - Importance of public education about AI
            """
        
        return {
            'choices': [{
                'message': {
                    'content': content
                }
            }]
        }
    
    @staticmethod
    def create_mock_assemblyai_transcript() -> str:
        """Create mock AssemblyAI transcript with speaker labels"""
        return """
        Speaker A: Welcome to today's episode. I'm excited to discuss AI safety with our guest.
        
        Speaker B: Thanks for having me. AI safety is becoming increasingly important.
        
        Speaker A: Can you explain the alignment problem?
        
        Speaker B: Sure. The alignment problem refers to ensuring AI systems do what we want them to do, 
        even as they become more capable. It's about aligning AI goals with human values.
        
        Speaker A: What are the main challenges?
        
        Speaker B: There are several. First, defining human values precisely is difficult. 
        Second, ensuring AI systems maintain these values as they learn and adapt. 
        Third, preventing unintended consequences from optimization.
        
        Speaker A: How can we address these challenges?
        
        Speaker B: We need multiple approaches: technical research on alignment, 
        governance frameworks, and public engagement. No single solution will be sufficient.
        """
    
    @staticmethod
    def create_mock_email_digest(episodes: List[Episode], summaries: Dict[str, str]) -> str:
        """Create mock email digest HTML"""
        html = """
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .episode { margin: 20px 0; padding: 15px; border: 1px solid #ddd; }
                .podcast-name { color: #666; font-size: 14px; }
                .episode-title { font-size: 18px; font-weight: bold; }
                .summary { margin-top: 10px; }
            </style>
        </head>
        <body>
            <h1>Renaissance Weekly Digest</h1>
        """
        
        for episode in episodes:
            key = f"{episode.podcast} - {episode.title}"
            summary = summaries.get(key, "No summary available")
            html += f"""
            <div class="episode">
                <div class="podcast-name">{episode.podcast}</div>
                <div class="episode-title">{episode.title}</div>
                <div class="summary">{summary}</div>
            </div>
            """
        
        html += """
        </body>
        </html>
        """
        return html


class MockFactory:
    """Factory for creating mock objects"""
    
    @staticmethod
    def create_mock_download_manager(success_rate: float = 1.0) -> Mock:
        """Create mock download manager with configurable success rate"""
        mock = Mock()
        
        async def download_episodes(episodes, *args, **kwargs):
            import random
            results = {'success': [], 'failed': []}
            
            for episode in episodes:
                if random.random() < success_rate:
                    results['success'].append(episode)
                else:
                    results['failed'].append({
                        **episode,
                        'error': 'Simulated download failure'
                    })
            
            return results
        
        mock.download_episodes = AsyncMock(side_effect=download_episodes)
        return mock
    
    @staticmethod
    def create_mock_transcript_finder(has_transcript: bool = True) -> Mock:
        """Create mock transcript finder"""
        mock = Mock()
        
        if has_transcript:
            mock.find_transcript = AsyncMock(
                return_value=("Mock transcript content", "test_source")
            )
        else:
            mock.find_transcript = AsyncMock(
                return_value=(None, None)
            )
        
        return mock
    
    @staticmethod
    def create_mock_rate_limiter() -> Mock:
        """Create mock rate limiter that doesn't delay"""
        mock = Mock()
        mock.acquire = AsyncMock()
        return mock


class AsyncTestHelper:
    """Helper for async testing patterns"""
    
    @staticmethod
    async def run_with_timeout(coro, timeout: float = 5.0):
        """Run coroutine with timeout"""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            raise AssertionError(f"Test timed out after {timeout} seconds")
    
    @staticmethod
    async def wait_for_condition(
        condition_func, 
        timeout: float = 5.0, 
        interval: float = 0.1
    ) -> bool:
        """Wait for condition to become true"""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if await condition_func():
                return True
            await asyncio.sleep(interval)
        return False
    
    @staticmethod
    async def gather_with_errors(*coros):
        """Gather that doesn't fail on first error"""
        results = await asyncio.gather(*coros, return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise Exception(f"Multiple errors: {errors}")
        return results


class PerformanceProfiler:
    """Simple performance profiler for tests"""
    
    def __init__(self):
        self.timings = {}
        self.start_times = {}
    
    def start(self, name: str):
        """Start timing a section"""
        import time
        self.start_times[name] = time.time()
    
    def stop(self, name: str):
        """Stop timing and record"""
        import time
        if name in self.start_times:
            elapsed = time.time() - self.start_times[name]
            if name not in self.timings:
                self.timings[name] = []
            self.timings[name].append(elapsed)
            del self.start_times[name]
    
    def report(self) -> Dict[str, Dict[str, float]]:
        """Generate timing report"""
        report = {}
        for name, times in self.timings.items():
            report[name] = {
                'count': len(times),
                'total': sum(times),
                'average': sum(times) / len(times),
                'min': min(times),
                'max': max(times)
            }
        return report


def assert_valid_summary(summary: str):
    """Assert that a summary has the expected format"""
    assert isinstance(summary, str)
    assert len(summary) > 100  # Not empty
    assert "Executive Summary" in summary or "Key" in summary
    # Check for common summary sections
    expected_sections = ["Summary", "Topics", "Insights", "Key"]
    assert any(section in summary for section in expected_sections)


def assert_valid_episode(episode: Episode):
    """Assert that an episode has valid data"""
    assert isinstance(episode.podcast, str) and len(episode.podcast) > 0
    assert isinstance(episode.title, str) and len(episode.title) > 0
    assert isinstance(episode.published, datetime)
    assert episode.published.tzinfo is not None  # Has timezone
    assert isinstance(episode.audio_url, str) and episode.audio_url.startswith('http')


def create_test_environment() -> Dict[str, Any]:
    """Create isolated test environment variables"""
    test_env = {
        'TESTING_MODE': 'true',
        'LOG_LEVEL': 'WARNING',
        'OPENAI_API_KEY': 'test-key',
        'SENDGRID_API_KEY': 'test-key',
        'ASSEMBLYAI_API_KEY': 'test-key'
    }
    
    # Save original environment
    original_env = {}
    for key in test_env:
        original_env[key] = os.environ.get(key)
    
    # Set test environment
    for key, value in test_env.items():
        os.environ[key] = value
    
    return original_env


def restore_environment(original_env: Dict[str, Any]):
    """Restore original environment variables"""
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value