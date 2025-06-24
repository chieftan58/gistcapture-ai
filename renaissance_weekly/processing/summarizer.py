"""Generate executive summaries using GPT-4o"""

from pathlib import Path
from typing import Optional

from ..models import Episode, TranscriptSource
from ..config import SUMMARY_DIR
from ..utils.logging import get_logger
from ..utils.helpers import slugify
from ..utils.clients import openai_client

logger = get_logger(__name__)


class Summarizer:
    """Generate executive summaries for podcast episodes"""
    
    async def generate_summary(self, episode: Episode, transcript: str, source: TranscriptSource) -> Optional[str]:
        """Generate executive summary using GPT-4o"""
        try:
            # Create safe filename for summary with readable format
            date_str = episode.published.strftime('%Y%m%d')
            safe_podcast = slugify(episode.podcast)[:30]
            safe_title = slugify(episode.title)[:50]
            summary_file = SUMMARY_DIR / f"{date_str}_{safe_podcast}_{safe_title}_summary.md"
            
            if summary_file.exists():
                logger.info("✅ Found cached summary")
                with open(summary_file, 'r', encoding='utf-8') as f:
                    return f.read()
            
            # Executive summary prompt
            prompt = self._create_summary_prompt(episode, transcript, source)
            
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,
                temperature=0.3
            )
            
            summary = response.choices[0].message.content
            
            # Add metadata
            summary += self._create_metadata_section(episode, source)
            
            # Cache summary
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            return summary
            
        except Exception as e:
            logger.error(f"❌ Summary generation error: {e}")
            return None
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for GPT-4o"""
        return """You are the lead writer for Renaissance Weekly, a premium newsletter that serves the intellectually ambitious. Your readers include founders, investors, scientists, and polymaths who expect world-class curation and insight. You have a gift for finding the profound in the practical and making complex ideas irresistibly clear."""
    
    def _create_summary_prompt(self, episode: Episode, transcript: str, source: TranscriptSource) -> str:
        """Create the summary generation prompt"""
        return f"""EPISODE: {episode.title}
PODCAST: {episode.podcast}
TRANSCRIPT SOURCE: {source.value}

TRANSCRIPT:
{transcript[:100000]}  # Limit for API

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
    
    def _create_metadata_section(self, episode: Episode, source: TranscriptSource) -> str:
        """Create metadata section for the summary"""
        metadata = f"\n\n---\n\n"
        metadata += f"**Episode**: {episode.title}\n"
        metadata += f"**Podcast**: {episode.podcast}\n"
        metadata += f"**Published**: {episode.published.strftime('%Y-%m-%d')}\n"
        metadata += f"**Transcript Source**: {source.value}\n"
        if episode.link:
            metadata += f"**Link**: [{episode.title}]({episode.link})\n"
        
        return metadata