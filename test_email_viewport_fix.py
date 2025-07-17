#!/usr/bin/env python3
"""Test the email viewport fix for 'Read Full Summary' button"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from renaissance_weekly.models import Episode
from renaissance_weekly.email.digest import EmailDigest

def create_test_episode(index: int, paragraph_length: str = "medium") -> Episode:
    """Create a test episode with specified paragraph length"""
    
    # Different paragraph lengths to test buffer behavior
    paragraphs = {
        "short": "This is a short paragraph summary. It's only about 30 words long and tests the minimum buffer scenario. The guest discusses important topics briefly.",
        
        "medium": "This is a medium-length paragraph summary that represents a typical episode overview. The conversation covers multiple important topics including market dynamics, investment strategies, and future predictions. The guest shares insights from their extensive experience in the field, discussing both challenges and opportunities. This summary is approximately 150 words which is our target length. The discussion touches on key themes that would interest our investment-focused audience, including technological disruption, market cycles, and portfolio management strategies. The host and guest explore various scenarios and their potential impacts on different asset classes.",
        
        "long": "This is a long paragraph summary that tests the dynamic buffer with extended content. The episode features an in-depth conversation with a prominent investor who shares their journey from early career to becoming a successful fund manager. They discuss the evolution of markets over the past two decades, highlighting key turning points and lessons learned. The conversation covers macroeconomic themes, including inflation, monetary policy, and global trade dynamics. The guest provides specific examples of successful investments and explains their analytical framework. They also discuss common mistakes investors make and how to avoid them. The dialogue includes technical analysis of market structures, liquidity conditions, and risk management techniques. Throughout the episode, both host and guest examine current market conditions and provide forward-looking perspectives on various asset classes including equities, fixed income, commodities, and alternative investments. This extended summary ensures we test the buffer behavior with maximum content length to verify the viewport positioning works correctly even with very long paragraph summaries that push the button further down the page."
    }
    
    full_summary = """## Investment Thesis and Market Dynamics

The guest begins by outlining their core investment philosophy, which centers on identifying asymmetric opportunities in dislocated markets. They explain how their approach has evolved from traditional value investing to incorporating growth metrics and technological disruption factors.

### Key Market Observations

1. **Liquidity Conditions**: The current market environment presents unique challenges with central bank policies creating artificial liquidity conditions.

2. **Sector Rotation**: Evidence suggests a significant rotation from growth to value stocks, though the guest argues this is premature.

3. **Global Macro Factors**: Discussion of how geopolitical tensions and supply chain disruptions create both risks and opportunities.

### Portfolio Construction Strategy

The conversation delves into specific portfolio construction techniques:

- **Risk Parity Approach**: Balancing risk across asset classes rather than capital allocation
- **Dynamic Hedging**: Using options strategies to protect downside while maintaining upside exposure  
- **Alternative Assets**: Incorporating commodities and real assets as inflation hedges

### Technology and Disruption

A significant portion of the discussion focuses on technological disruption:

The guest explains how artificial intelligence and machine learning are fundamentally changing market dynamics. They provide examples of how algorithmic trading has increased market efficiency while also creating new forms of systemic risk.

### Specific Investment Examples

The guest shares several concrete examples from their portfolio:

1. **Energy Transition Play**: Long position in lithium miners coupled with shorts in traditional auto manufacturers
2. **Financial Technology**: Investments in payment processing infrastructure
3. **Healthcare Innovation**: Biotech companies developing novel therapeutics

### Risk Management Philosophy

The discussion concludes with insights on risk management:

- The importance of position sizing and portfolio diversification
- How to identify and avoid value traps
- The role of patience in achieving superior returns

### Forward-Looking Perspectives

The guest provides their outlook for the next 12-18 months, highlighting potential catalysts and warning signs investors should monitor. They emphasize the importance of remaining flexible and adapting to changing market conditions while maintaining disciplined investment processes.

This comprehensive discussion provides valuable insights for both professional investors and those seeking to improve their investment approach."""
    
    episode = Episode(
        podcast=f"Test Podcast {index}",
        title=f"Episode {index}: Deep Dive into Market Dynamics with Expert Guest",
        description="A comprehensive discussion about investment strategies and market analysis",
        audio_url=f"https://example.com/episode{index}",
        published=datetime.now() - timedelta(days=index),
        duration="60 min",
        guid=f"test-episode-{index}",
        apple_podcast_id="test-id"
    )
    
    # Add the summary fields directly as they're not part of the Episode dataclass
    episode.summary = full_summary
    episode.paragraph_summary = paragraphs[paragraph_length]
    
    return episode

def main():
    """Generate test email with different paragraph lengths"""
    
    # Create test episodes with different paragraph lengths
    episodes = [
        create_test_episode(1, "short"),
        create_test_episode(2, "medium"), 
        create_test_episode(3, "long"),
    ]
    
    # Generate email
    digest = EmailDigest()
    
    # Create full summaries list
    full_summaries = [episode.summary for episode in episodes]
    paragraph_summaries = [episode.paragraph_summary for episode in episodes]
    
    html_content = digest.create_expandable_email(full_summaries, episodes, paragraph_summaries)
    
    # Save to file
    output_file = Path("test_viewport_fix_email.html")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✅ Test email generated: {output_file}")
    print("\nTest scenarios included:")
    print("1. Short paragraph - tests minimum buffer")
    print("2. Medium paragraph - typical use case")  
    print("3. Long paragraph - tests dynamic buffer scaling")
    print("\nTo test:")
    print("1. Open the HTML file in a mobile browser/email client")
    print("2. For each episode, scroll past the 'Read Full Summary' button")
    print("3. Click the button and verify the full summary starts at the beginning")
    print("4. The longer the paragraph, the better the positioning should be")

if __name__ == "__main__":
    main()