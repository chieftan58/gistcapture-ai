"""Unit tests for episode summarization"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from renaissance_weekly.processing.summarizer import EpisodeSummarizer
from renaissance_weekly.models import Episode


class TestEpisodeSummarizer:
    """Test AI-powered summarization"""
    
    @pytest.fixture
    def summarizer(self, mock_openai):
        """Create summarizer with mocked OpenAI"""
        with patch('openai.AsyncOpenAI', return_value=mock_openai):
            return EpisodeSummarizer()
    
    @pytest.fixture
    def sample_episode(self):
        """Create sample episode"""
        return Episode(
            podcast="Test Podcast",
            title="AI Safety with Expert Guest",
            published=None,
            audio_url="https://example.com/test.mp3",
            description="Discussion about AI safety and alignment"
        )
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_summarize_basic(self, summarizer, sample_episode, sample_transcript):
        """Test basic summarization"""
        summary = await summarizer.summarize(
            sample_episode,
            sample_transcript
        )
        
        assert summary is not None
        assert len(summary) > 100
        assert "Executive Summary" in summary
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_summarize_with_retry(self, mock_openai, sample_episode, sample_transcript):
        """Test summarization retry on failure"""
        # Make first call fail, second succeed
        call_count = 0
        
        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("API Error")
            return Mock(choices=[Mock(message=Mock(content="Retry summary"))])
        
        mock_openai.chat.completions.create = mock_create
        
        with patch('openai.AsyncOpenAI', return_value=mock_openai):
            summarizer = EpisodeSummarizer()
            summary = await summarizer.summarize(sample_episode, sample_transcript)
            
            assert call_count == 2  # Retried once
            assert "Retry summary" in summary
    
    @pytest.mark.unit
    def test_prompt_construction(self, summarizer, sample_episode):
        """Test prompt is constructed correctly"""
        prompt = summarizer._build_prompt(
            sample_episode,
            "Test transcript content",
            include_metadata=True
        )
        
        assert sample_episode.podcast in prompt
        assert sample_episode.title in prompt
        assert "Test transcript content" in prompt
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handles_empty_transcript(self, summarizer, sample_episode):
        """Test handling of empty transcript"""
        with pytest.raises(ValueError, match="empty"):
            await summarizer.summarize(sample_episode, "")
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handles_long_transcript(self, summarizer, sample_episode, mock_openai):
        """Test handling of very long transcripts"""
        # Create a very long transcript
        long_transcript = "This is a test. " * 10000  # ~50k chars
        
        summary = await summarizer.summarize(sample_episode, long_transcript)
        
        # Should handle without error
        assert summary is not None
        
        # Verify transcript was truncated in prompt
        call_args = mock_openai.chat.completions.create.call_args
        messages = call_args[1]['messages']
        assert len(messages[-1]['content']) < len(long_transcript)
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_rate_limiting(self, sample_episode, sample_transcript):
        """Test rate limiting is applied"""
        mock_limiter = Mock()
        mock_limiter.acquire = AsyncMock()
        
        with patch('renaissance_weekly.processing.summarizer.openai_rate_limiter', mock_limiter):
            summarizer = EpisodeSummarizer()
            await summarizer.summarize(sample_episode, sample_transcript)
            
            # Rate limiter should be called
            mock_limiter.acquire.assert_called()
    
    @pytest.mark.unit
    def test_summary_validation(self, summarizer):
        """Test summary validation logic"""
        # Valid summary
        valid = summarizer._validate_summary(
            "**Executive Summary**: This is a valid summary with insights."
        )
        assert valid is True
        
        # Invalid summaries
        assert summarizer._validate_summary("") is False
        assert summarizer._validate_summary("Too short") is False
        assert summarizer._validate_summary("No formatting here") is False
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_custom_prompt_loading(self, summarizer, temp_dir):
        """Test loading custom prompts"""
        # Create custom prompt file
        prompt_file = temp_dir / "custom_prompt.txt"
        prompt_file.write_text("Custom prompt: {title}")
        
        with patch('renaissance_weekly.config.PROMPTS_DIR', temp_dir):
            prompt = summarizer._load_prompt_template("custom_prompt.txt")
            assert "Custom prompt:" in prompt
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_temperature_settings(self, mock_openai, sample_episode, sample_transcript):
        """Test temperature configuration"""
        with patch.dict('os.environ', {'OPENAI_TEMPERATURE': '0.7'}):
            summarizer = EpisodeSummarizer()
            await summarizer.summarize(sample_episode, sample_transcript)
            
            # Verify temperature was set
            call_args = mock_openai.chat.completions.create.call_args
            assert call_args[1]['temperature'] == 0.7
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_model_selection(self, mock_openai, sample_episode, sample_transcript):
        """Test model can be configured"""
        with patch.dict('os.environ', {'OPENAI_MODEL': 'gpt-4'}):
            summarizer = EpisodeSummarizer()
            await summarizer.summarize(sample_episode, sample_transcript)
            
            # Verify model was used
            call_args = mock_openai.chat.completions.create.call_args
            assert call_args[1]['model'] == 'gpt-4'
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_structured_output_parsing(self, summarizer):
        """Test parsing of structured summary sections"""
        raw_summary = """
        **Executive Summary**: Main summary here.
        
        **Key Topics**:
        - Topic 1
        - Topic 2
        
        **Notable Insights**:
        - Insight 1
        - Insight 2
        """
        
        sections = summarizer._parse_summary_sections(raw_summary)
        
        assert 'executive_summary' in sections
        assert 'key_topics' in sections
        assert len(sections['key_topics']) == 2
        assert 'notable_insights' in sections
        assert len(sections['notable_insights']) == 2