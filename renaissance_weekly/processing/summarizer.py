"""Generate executive summaries using ChatGPT - FIXED with external prompts"""

import os
from pathlib import Path
from typing import Optional

from ..models import Episode, TranscriptSource
from ..config import SUMMARY_DIR, BASE_DIR, TESTING_MODE
from ..utils.logging import get_logger
from ..utils.helpers import slugify, retry_with_backoff, CircuitBreaker
from ..utils.clients import openai_client, openai_rate_limiter

logger = get_logger(__name__)


class Summarizer:
    """Generate executive summaries for podcast episodes using configurable prompts"""
    
    def __init__(self):
        self.prompts_dir = BASE_DIR / "prompts"
        self.system_prompt = self._load_prompt("system_prompt.txt")
        self.summary_prompt_template = self._load_prompt("summary_prompt.txt")
        
        # Configuration from environment
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", "4000"))
        
        # Circuit breaker for OpenAI API
        self.openai_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            rate_limit_threshold=3,
            rate_limit_recovery=300.0,  # 5 minutes for rate limits
            correlation_id="openai-chat"
        )
        
        logger.info(f"📝 Summarizer initialized with model: {self.model}")
    
    def _load_prompt(self, filename: str) -> str:
        """Load prompt from file with fallback to defaults"""
        prompt_path = self.prompts_dir / filename
        
        try:
            if prompt_path.exists():
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    logger.debug(f"Loaded prompt from {filename}")
                    return content
            else:
                logger.warning(f"Prompt file not found: {prompt_path}")
                # Return default prompts as fallback
                if filename == "system_prompt.txt":
                    return self._get_default_system_prompt()
                elif filename == "summary_prompt.txt":
                    return self._get_default_summary_prompt()
                else:
                    return ""
        except Exception as e:
            logger.error(f"Error loading prompt {filename}: {e}")
            # Return defaults on error
            if filename == "system_prompt.txt":
                return self._get_default_system_prompt()
            elif filename == "summary_prompt.txt":
                return self._get_default_summary_prompt()
            else:
                return ""
    
    async def generate_summary(self, episode: Episode, transcript: str, source: TranscriptSource) -> Optional[str]:
        """Generate executive summary using ChatGPT"""
        try:
            # Note: Transcript validation is now done earlier in the pipeline
            # to allow fallback to audio transcription when needed
            
            # Create safe filename for summary cache
            date_str = episode.published.strftime('%Y%m%d')
            safe_podcast = slugify(episode.podcast)[:30]
            safe_title = slugify(episode.title)[:50]
            summary_file = SUMMARY_DIR / f"{date_str}_{safe_podcast}_{safe_title}_summary.md"
            
            # Check cache first
            if summary_file.exists():
                logger.info("✅ Found cached summary")
                with open(summary_file, 'r', encoding='utf-8') as f:
                    return f.read()
            
            # Prepare the prompt with episode data
            prompt = self._prepare_prompt(episode, transcript, source)
            
            mode_info = " (TESTING MODE: 5-min clips)" if TESTING_MODE else ""
            logger.info(f"🤖 Generating summary with {self.model}{mode_info}...")
            
            # Call OpenAI API with rate limiting and circuit breaker
            response = await self._call_openai_api(prompt)
            
            if not response:
                logger.error("❌ Failed to generate summary")
                return None
            
            summary = response
            
            # Don't add metadata footer since the new prompt format is self-contained
            
            # Cache the summary
            try:
                with open(summary_file, 'w', encoding='utf-8') as f:
                    f.write(summary)
                logger.info(f"💾 Summary cached: {summary_file.name}")
            except Exception as e:
                logger.warning(f"Failed to cache summary: {e}")
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Summary generation error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _prepare_prompt(self, episode: Episode, transcript: str, source: TranscriptSource) -> str:
        """Prepare the prompt with episode data"""
        # Truncate transcript if too long (leave room for response)
        max_transcript_chars = 100000  # Adjust based on model limits
        truncated_transcript = transcript[:max_transcript_chars]
        if len(transcript) > max_transcript_chars:
            truncated_transcript += "\n\n[TRANSCRIPT TRUNCATED DUE TO LENGTH]"
        
        # Replace all placeholders in template
        prompt = self.summary_prompt_template
        prompt = prompt.replace("{episode_title}", episode.title)
        prompt = prompt.replace("{podcast_name}", episode.podcast)
        prompt = prompt.replace("{source}", source.value)
        prompt = prompt.replace("{transcript}", truncated_transcript)
        
        # Extract guest name from title if possible (common patterns)
        guest_name = self._extract_guest_name(episode.title, episode.description)
        prompt = prompt.replace("{guest_name}", guest_name)
        
        # Format publish date
        publish_date = episode.published.strftime('%B %d, %Y')
        prompt = prompt.replace("{publish_date}", publish_date)
        
        return prompt
    
    def _validate_transcript_content(self, transcript: str, source: TranscriptSource) -> bool:
        """
        Validate that the transcript contains actual episode content, not just metadata.
        
        Args:
            transcript: The transcript text to validate
            source: The source of the transcript
            
        Returns:
            True if transcript appears to be full content, False if it's just metadata
        """
        # Adjust thresholds based on testing mode
        # In testing mode (5 min clips), expect ~750 words at 150 wpm speaking rate
        min_words = 500 if TESTING_MODE else 1000
        min_chars = 2500 if TESTING_MODE else 5000
        
        # Check minimum length
        word_count = len(transcript.split())
        if word_count < min_words:
            logger.warning(f"Transcript too short: {word_count} words (minimum: {min_words}, testing_mode={TESTING_MODE})")
            return False
        
        # Check character count
        char_count = len(transcript)
        if char_count < min_chars:
            logger.warning(f"Transcript too short: {char_count} characters (minimum: {min_chars}, testing_mode={TESTING_MODE})")
            return False
        
        # Check for metadata-only patterns
        metadata_patterns = [
            # Common description patterns
            r'^(In this episode|On this episode|This week|Today)',
            r'^(Join us as|Listen as|Tune in)',
            r'^(Subscribe|Follow|Download)',
            r'^(Show notes|Episode notes|Links mentioned)',
            # URL-heavy content (likely show notes)
            r'https?://\S+',
            # Social media patterns
            r'@\w+',
            r'#\w+',
            # Common metadata labels
            r'(Guest|Host|Episode|Duration|Published|Recorded):',
        ]
        
        # Count lines that look like metadata
        lines = transcript.split('\n')
        metadata_line_count = 0
        url_count = 0
        
        for line in lines[:50]:  # Check first 50 lines
            for pattern in metadata_patterns:
                import re
                if re.search(pattern, line, re.IGNORECASE):
                    metadata_line_count += 1
                    break
            
            # Count URLs
            url_count += len(re.findall(r'https?://\S+', line))
        
        # If more than 30% of early lines look like metadata, it's probably not a full transcript
        # Be more lenient in test mode since 5-minute clips might have intro-heavy starts
        max_metadata_ratio = 0.5 if TESTING_MODE else 0.3
        metadata_ratio = metadata_line_count / min(len(lines), 50)
        if metadata_ratio > max_metadata_ratio:
            logger.warning(f"High metadata ratio: {metadata_ratio:.1%} of first 50 lines (max: {max_metadata_ratio:.0%})")
            return False
        
        # If there are too many URLs early on, it's likely show notes
        if url_count > 10:
            logger.warning(f"Too many URLs in beginning: {url_count} (likely show notes)")
            return False
        
        # Check for conversation patterns (good sign of real transcript)
        conversation_patterns = [
            r'^\w+:',  # Speaker labels (e.g., "John:")
            r'"[^"]+"',  # Quoted speech
            r'\b(said|says|asked|asks|replied|replies)\b',  # Speech verbs
            r'\b(um|uh|yeah|okay|right|well)\b',  # Filler words
        ]
        
        conversation_indicators = 0
        for line in lines[:100]:  # Check first 100 lines
            for pattern in conversation_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    conversation_indicators += 1
                    break
        
        # If we see conversation patterns, it's likely a real transcript
        # Adjust threshold for test mode (5-minute clips have fewer patterns)
        min_indicators = 1 if TESTING_MODE else 10
        if conversation_indicators >= min_indicators:
            logger.info(f"✅ Transcript validation passed: {word_count} words, {conversation_indicators} conversation indicators (min: {min_indicators})")
            return True
        
        # Check source reliability
        reliable_sources = [
            TranscriptSource.OFFICIAL_TRANSCRIPT,
            TranscriptSource.YOUTUBE_TRANSCRIPT,
            TranscriptSource.AUDIO_TRANSCRIPTION,
            TranscriptSource.API_TRANSCRIPTION,
        ]
        
        if source in reliable_sources:
            # More lenient for reliable sources
            if word_count >= 500 and char_count >= 2500:
                logger.info(f"✅ Transcript validation passed (reliable source: {source.value})")
                return True
        
        # Special handling for test mode audio transcriptions
        if TESTING_MODE and source == TranscriptSource.AUDIO_TRANSCRIPTION:
            # Very lenient for test mode audio transcriptions
            if word_count >= 200 and char_count >= 1000:
                logger.info(f"✅ Transcript validation passed (test mode audio: {word_count} words, {conversation_indicators} conversation indicators)")
                return True
        
        # Log detailed validation metrics for debugging
        logger.info(f"Validation metrics - Words: {word_count}/{min_words}, Chars: {char_count}/{min_chars}, "
                   f"Conversation indicators: {conversation_indicators}/{min_indicators}, "
                   f"Metadata ratio: {metadata_ratio:.1%}/{max_metadata_ratio:.0%}, URLs: {url_count}")
        logger.warning(f"Transcript validation failed: insufficient conversation content")
        return False
    
    def _extract_guest_name(self, title: str, description: Optional[str]) -> str:
        """Try to extract guest name from episode title or description"""
        import re
        
        # Common patterns in podcast titles
        patterns = [
            r'with\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',  # "with Jane Doe |"
            r'featuring\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',  # "featuring John Smith"
            r'ft\.\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',  # "ft. Jane Doe"
            r'guest[:\s]+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',  # "Guest: John Smith"
            r'[\|\-]\s*([A-Z][a-zA-Z\s]+?)\s*[\|\-]',  # "| Jane Doe |"
            r'^([A-Z][a-zA-Z\s]+?):\s',  # "John Smith: Topic"
        ]
        
        # Try title first
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                guest = match.group(1).strip()
                # Basic validation - should be 2-4 words, not too long
                if 2 <= len(guest.split()) <= 4 and len(guest) < 50:
                    return guest
        
        # Try description if available
        if description:
            for pattern in patterns:
                match = re.search(pattern, description[:200], re.IGNORECASE)  # Check first 200 chars
                if match:
                    guest = match.group(1).strip()
                    if 2 <= len(guest.split()) <= 4 and len(guest) < 50:
                        return guest
        
        # Default if no guest found
        return "[Guest Name]"
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Call OpenAI API with enhanced retry logic and rate limiting"""
        import asyncio
        import uuid
        
        correlation_id = str(uuid.uuid4())[:8]
        
        # Check for dry-run mode
        if os.getenv('DRY_RUN') == 'true':
            logger.info(f"[{correlation_id}] 🧪 DRY RUN: Skipping OpenAI summarization API call")
            return """## 🧪 DRY RUN SUMMARY

This is a dry-run summary. In normal operation, this would contain:

### 🔑 Quick Take
The actual AI-generated summary of the podcast episode.

### Core Sections
Detailed insights from the episode organized by topic.

### 🛠️ Apply It
Actionable takeaways from the episode.

---
*This summary was generated in dry-run mode without making API calls.*"""
        
        # Wait for rate limiter before making API call
        wait_time = await openai_rate_limiter.acquire(correlation_id)
        if wait_time > 0:
            logger.info(f"[{correlation_id}] Rate limiting: waiting {wait_time:.1f}s before API call")
            await asyncio.sleep(wait_time)
        
        # Log current rate limiter usage
        usage = openai_rate_limiter.get_current_usage()
        logger.info(f"[{correlation_id}] OpenAI rate limit usage: {usage['current_requests']}/{usage['max_requests']} ({usage['utilization']:.1f}%)")
        
        # Create the full user message with transcript
        user_message = prompt
        
        # Define the API call function for retry and circuit breaker
        async def api_call():
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            def sync_api_call():
                try:
                    return openai_client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": self.system_prompt if self.system_prompt else "You are a helpful assistant."},
                            {"role": "user", "content": user_message}
                        ],
                        max_tokens=self.max_tokens,
                        temperature=self.temperature
                    )
                except Exception as e:
                    # Wrap the exception to preserve response information
                    if hasattr(e, 'response'):
                        raise e
                    else:
                        # Create a wrapper exception
                        class APIError(Exception):
                            def __init__(self, message):
                                super().__init__(message)
                                self.response = None
                        
                        raise APIError(str(e))
            
            return await loop.run_in_executor(None, sync_api_call)
        
        try:
            # Call with circuit breaker and enhanced retry
            async def circuit_breaker_call():
                return await retry_with_backoff(
                    api_call,
                    max_attempts=5,  # Increased for rate limits
                    base_delay=2.0,
                    max_delay=300.0,  # 5 minutes max
                    exceptions=(Exception,),
                    correlation_id=correlation_id,
                    handle_rate_limit=True  # Enable special rate limit handling
                )
            
            response = await self.openai_circuit_breaker.call(circuit_breaker_call)
            
            if response and response.choices:
                content = response.choices[0].message.content
                if content:
                    logger.info(f"[{correlation_id}] ✅ Summary generated: {len(content)} characters")
                    return content
                else:
                    logger.warning(f"[{correlation_id}] Empty response from API")
            
        except Exception as e:
            error_msg = str(e)
            
            if "circuit breaker is open" in error_msg.lower():
                logger.error(f"[{correlation_id}] Circuit breaker is open - too many failures")
            elif "429" in error_msg:
                logger.error(f"[{correlation_id}] Rate limit error despite retry attempts")
            else:
                logger.error(f"[{correlation_id}] API call failed: {error_msg}")
            
            raise
        
        return None
    
    def _create_metadata_section(self, episode: Episode, source: TranscriptSource) -> str:
        """Create metadata section for the summary"""
        metadata = f"\n\n---\n\n"
        metadata += f"**Episode**: {episode.title}\n"
        metadata += f"**Podcast**: {episode.podcast}\n"
        metadata += f"**Published**: {episode.published.strftime('%Y-%m-%d')}\n"
        metadata += f"**Duration**: {episode.duration}\n"
        metadata += f"**Transcript Source**: {source.value}\n"
        
        if episode.link:
            metadata += f"**Link**: [{episode.title}]({episode.link})\n"
        
        metadata += f"\n*Summary generated by Renaissance Weekly using {self.model}*\n"
        
        return metadata
    
    def reload_prompts(self):
        """Reload prompts from disk - useful for A/B testing"""
        logger.info("🔄 Reloading prompts...")
        self.system_prompt = self._load_prompt("system_prompt.txt")
        self.summary_prompt_template = self._load_prompt("summary_prompt.txt")
        logger.info("✅ Prompts reloaded")
    
    def _get_default_system_prompt(self) -> str:
        """Default system prompt as fallback"""
        return """You are the lead writer for Renaissance Weekly, a premium newsletter that serves the intellectually ambitious. Your readers include founders, investors, scientists, and polymaths who expect world-class curation and insight. You have a gift for finding the profound in the practical and making complex ideas irresistibly clear."""
    
    def _get_default_summary_prompt(self) -> str:
        """Default summary prompt template as fallback"""
        return """EPISODE {episode_title}   |   PODCAST {podcast_name}
GUEST {guest_name}   |   DATE {publish_date}

AUDIENCE
Busy, curious professionals.

GOAL
Produce a one-page brief (≤550 words) that a smart reader can scan in 2–3 minutes and walk away with new insight or action.

STYLE
Conversational, idea-dense, Tim-Ferriss-meets-The-Economist.
Use bullets or short paragraphs; prefer vivid examples over summary clichés.

OUTPUT
1. 🔑 **Quick Take** – 3–4 sentences: hook + why it matters.
2. **Core Sections (2–4)** – Invent headers that fit the content (e.g., "Mind-Body Hacks", "Macro Signals"). Each header followed by 3-7 tight bullets (≤2 sentences each).
3. 🛠️ **Apply It** – 3–4 actionable bullets OR, if no obvious actions, a short "So What?" paragraph.
4. Optional: **Quote** (≤20 words) + **Links** (≤4).

RULES
- No filler like "In this episode…".  
- Active voice, no buzzwords.  
- Hard stop: 550 words.  
- Omit any section that has no substance.

READY? Create the brief."""