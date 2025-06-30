"""Generate executive summaries using ChatGPT - FIXED with external prompts"""

import os
from pathlib import Path
from typing import Optional

from ..models import Episode, TranscriptSource
from ..config import SUMMARY_DIR, BASE_DIR
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
            
            logger.info(f"🤖 Generating summary with {self.model}...")
            
            # Call OpenAI API with rate limiting and circuit breaker
            response = await self._call_openai_api(prompt)
            
            if not response:
                logger.error("❌ Failed to generate summary")
                return None
            
            summary = response
            
            # Add metadata footer
            summary += self._create_metadata_section(episode, source)
            
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
        
        # Replace placeholders in template
        prompt = self.summary_prompt_template
        prompt = prompt.replace("{episode_title}", episode.title)
        prompt = prompt.replace("{podcast_name}", episode.podcast)
        prompt = prompt.replace("{source}", source.value)
        prompt = prompt.replace("{transcript}", truncated_transcript)
        
        return prompt
    
    async def _call_openai_api(self, prompt: str) -> Optional[str]:
        """Call OpenAI API with enhanced retry logic and rate limiting"""
        import asyncio
        import uuid
        
        correlation_id = str(uuid.uuid4())[:8]
        
        # Wait for rate limiter before making API call
        wait_time = await openai_rate_limiter.acquire(correlation_id)
        if wait_time > 0:
            logger.info(f"[{correlation_id}] Rate limiting: waiting {wait_time:.1f}s before API call")
            await asyncio.sleep(wait_time)
        
        # Log current rate limiter usage
        usage = openai_rate_limiter.get_current_usage()
        logger.info(f"[{correlation_id}] OpenAI rate limit usage: {usage['current_requests']}/{usage['max_requests']} ({usage['utilization']:.1f}%)")
        
        # Define the API call function for retry and circuit breaker
        async def api_call():
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            
            def sync_api_call():
                try:
                    return openai_client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": prompt}
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
        return """EPISODE: {episode_title}
PODCAST: {podcast_name}
TRANSCRIPT SOURCE: {source}

TRANSCRIPT:
{transcript}

You are creating an executive briefing for Renaissance Weekly readers - busy professionals, founders, investors, and thought leaders who value their time above all else. This is not a generic summary; it's a strategic distillation that respects both the depth of the conversation and the reader's need for actionable intelligence.

Your task: Transform this podcast into a compelling narrative that captures not just what was said, but why it matters for someone building the future.

STRUCTURE YOUR SUMMARY AS FOLLOWS:

## Executive Summary & Guest Profile
Start with a 3-4 sentence executive summary that captures the absolute essence of this conversation. What is the ONE transformative insight that changes how we think about the topic?

Then provide a rich 2-3 paragraph profile of the guest that goes beyond credentials. Who is this person really? What unique vantage point do they bring? What makes their perspective invaluable? Include their most impressive achievements, their contrarian positions, and why Renaissance Weekly readers should care about their worldview.

## The Core Argument
In 2-3 flowing paragraphs, articulate the central thesis of this conversation. This is not a list of topics discussed, but a narrative explanation of the big idea that emerges. What worldview is being advanced? What conventional wisdom is being challenged? Write this as you would explain it to a brilliant friend over coffee.

## Key Insights That Matter
Present 5-7 insights, but make each one substantial (3-4 sentences). These should be:
- Counterintuitive or perspective-shifting
- Backed by specific examples or data from the conversation
- Written with vivid language that makes abstract concepts concrete
- Focused on insights that change how we act, not just how we think

Format each with a bold header that captures the essence, like:
**The 10,000 hour rule is dead - here's what actually drives mastery**
Then explain the insight with specificity and nuance.

## The Moment of Revelation
Identify and describe 1-2 pivotal moments in the conversation where a genuinely surprising insight emerged. Set the scene - what question prompted it? How did the guest's demeanor change? Quote the key exchange and explain why this moment matters. This brings the reader into the room.

## Practical Frameworks & Mental Models
Extract 3-4 concrete frameworks or mental models discussed. For each:
- Name it memorably
- Explain how it works in 2-3 sentences
- Provide a specific example of application
- Connect it to broader principles

## What You Can Do This Week
5-6 specific actions, but make them sophisticated and contextualized:
- Not just "try meditation" but "implement the 4-7-8 breathing protocol before high-stakes meetings"
- Include the why and expected outcome
- Range from 5-minute experiments to longer-term implementations
- Focus on high-leverage activities that compound

## The Deeper Game Being Played
A short, reflective paragraph that zooms out to the meta-level. What's really at stake in this conversation? How does it connect to larger trends in technology, society, or human performance? This is where you earn the reader's trust as a curator of ideas.

## Resources & Rabbit Holes
Organize resources intelligently:
**Essential Reading**: 2-3 books with one-sentence explanations of their core value
**Tools for Implementation**: Specific apps/services with use cases
**Further Exploration**: Related thinkers, concepts, or episodes to explore
**The Guest's Work**: Where to follow up directly

Remember: Your readers chose Renaissance Weekly because they refuse to choose between breadth and depth. Give them both. Write with the precision of The Economist, the insight of The New Yorker, and the practical value of the best business writing. Every sentence should either inform, inspire, or instruct.

Avoid corporate jargon, buzzwords, and filler. Use vivid, precise language. If you wouldn't say it to a brilliant friend, don't write it here."""