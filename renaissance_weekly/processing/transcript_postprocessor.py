"""Intelligent transcript post-processing using GPT-4 to fix errors automatically"""

import json
import asyncio
from typing import Tuple, Optional

from ..utils.logging import get_logger
from ..utils.helpers import retry_with_backoff
from ..utils.clients import openai_client, openai_rate_limiter

logger = get_logger(__name__)


class TranscriptPostProcessor:
    """Use GPT-4 to automatically fix transcription errors based on context"""
    
    def __init__(self):
        self.model = "gpt-4o-mini"  # Fast and effective for this task
        self.chunk_size = 15000  # Process in chunks to handle long transcripts
        
        # Common error patterns to check for
        self.error_indicators = [
            # Name errors
            "Heath Raboy", "Heath Rabois", "Keith Raboy",
            "Jason Kalkanis", "Jason Kalakanis",
            "Chamath Palihapatiya", "Shamath", "Chamat",
            "David Sachs", "David Sax",
            "Peter Teal", "Peter Theil",
            "Elon Must",
            "Eric Townsend", "Erik Townsand",
            "Lex Friedman", "Lex Freedman",
            "Tim Ferris", "Tim Feriss",
            "Megan Kelly", "Meghan Kelly",
            
            # Company errors
            "Open AI", "Open A.I.",
            "Space X", "Space-X",
            "Pay Pal",
            "Founder's Fund", "Founders' Fund",
            "Andreessen Horovitz",
            "Y-Combinator",
            
            # Technical terms
            "L.L.M.", "L L M",
            "A.I.", "A I",
            "I.P.O.", "I P O",
            "G.P.U.", "G P U",
            "A.P.I.", "A P I"
        ]
    
    def needs_processing(self, transcript: str) -> bool:
        """Quick check if transcript likely has errors"""
        return any(error in transcript for error in self.error_indicators)
        
    async def process_transcript(self, transcript: str, podcast_name: str, episode_title: str) -> Tuple[str, int]:
        """
        Process transcript to fix errors automatically
        
        Returns:
            Tuple of (processed_transcript, number_of_corrections)
        """
        if not transcript or len(transcript) < 100:
            return transcript, 0
            
        logger.info(f"🤖 Post-processing transcript for {podcast_name} - {episode_title[:50]}...")
        
        # For long transcripts, process the most important parts
        # Focus on the beginning where hosts/guests are introduced
        sample_length = min(len(transcript), self.chunk_size)
        transcript_sample = transcript[:sample_length]
        
        # Build a focused prompt
        prompt = self._build_prompt(transcript_sample, podcast_name, episode_title)
        
        try:
            # Use sync API with executor
            loop = asyncio.get_event_loop()
            
            def sync_api_call():
                return openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert transcript editor who fixes transcription errors, especially proper names and technical terms. You have deep knowledge of technology, finance, and business personalities."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1,  # Low temperature for consistency
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
            
            # Run in executor to avoid blocking
            response = await loop.run_in_executor(None, sync_api_call)
            
            result = json.loads(response.choices[0].message.content)
            
            # Apply corrections to full transcript
            processed_transcript = transcript
            corrections_made = 0
            
            for correction in result.get("corrections", []):
                original = correction["original"]
                fixed = correction["fixed"]
                
                # Count occurrences before replacement
                count = processed_transcript.count(original)
                
                if count > 0:
                    processed_transcript = processed_transcript.replace(original, fixed)
                    corrections_made += count
                    logger.info(f"   ✓ Fixed '{original}' → '{fixed}' ({count} occurrences)")
            
            # If we processed a sample, check if there might be more errors in the rest
            if len(transcript) > sample_length and corrections_made > 0:
                logger.info(f"   ℹ️  Processed first {sample_length} chars. Full transcript may have more corrections.")
            
            return processed_transcript, corrections_made
                
        except Exception as e:
            logger.error(f"Post-processing failed: {e}")
            # Return original on error
            return transcript, 0
    
    def _build_prompt(self, transcript_sample: str, podcast_name: str, episode_title: str) -> str:
        """Build focused prompt for GPT-4"""
        
        # Podcast-specific context
        podcast_contexts = {
            "All-In": "This is the All-In Podcast with regular hosts Jason Calacanis, Chamath Palihapitiya, David Sacks, and David Friedberg. Common guests include Keith Rabois, Brad Gerstner, and other tech/finance figures.",
            "MacroVoices": "This is MacroVoices with Erik Townsend and Patrick Ceresna. They discuss macro investing with guests like Jeff Snider, Luke Gromen, and Brent Johnson.",
            "Lex Fridman Podcast": "This is the Lex Fridman Podcast featuring conversations with scientists, engineers, and intellectuals.",
            "The Tim Ferriss Show": "This is The Tim Ferriss Show featuring interviews with world-class performers.",
            "Acquired": "This is Acquired with Ben Gilbert and David Rosenthal, discussing company histories and strategies.",
            "The Megyn Kelly Show": "This is The Megyn Kelly Show featuring political and cultural commentary."
        }
        
        context = podcast_contexts.get(podcast_name, f"This is {podcast_name}, a podcast about business, technology, and investing.")
        
        return f"""Analyze this transcript excerpt from "{episode_title}" and identify transcription errors.

CONTEXT: {context}

TRANSCRIPT EXCERPT:
{transcript_sample}

TASK: Identify and fix transcription errors, focusing on:
1. People's names (especially podcast hosts and notable guests)
2. Company names (tech companies, investment firms)
3. Technical terms and acronyms
4. Financial/investment terms

Look for patterns like:
- Names that sound similar but are misspelled (e.g., "Heath Raboy" should be "Keith Rabois")
- Companies with spacing issues (e.g., "Open AI" should be "OpenAI")
- Acronyms with unnecessary periods (e.g., "A.I." should be "AI")
- Common figures in tech/finance whose names are mangled

Return a JSON object with this structure:
{{
    "corrections": [
        {{
            "original": "exact text to replace",
            "fixed": "corrected text",
            "confidence": 0.95,
            "reason": "Keith Rabois is a well-known venture capitalist, not Heath Raboy"
        }}
    ]
}}

Only include corrections you're confident about (confidence > 0.8).
Keep original capitalization patterns unless fixing a clear error.
Don't change informal speech patterns or filler words."""
    
    async def validate_corrections(self, original: str, corrected: str, podcast_name: str) -> bool:
        """Validate that corrections make sense in context"""
        
        # Quick sanity checks
        if len(corrected) > len(original) * 2:
            return False  # Correction too different
            
        if corrected.lower() == original.lower():
            return False  # No real change
            
        # Could add more validation here
        return True


# Singleton instance
transcript_postprocessor = TranscriptPostProcessor()