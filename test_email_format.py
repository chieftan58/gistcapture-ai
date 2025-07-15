#!/usr/bin/env python
"""
Test script to verify email formatting changes.
This will generate a sample email with the new format.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.models import Episode
from renaissance_weekly.email.digest import EmailDigest


def test_email_format():
    """Test the new email format with sample data"""
    print("🧪 Testing new email format...")
    
    # Create sample episodes
    episodes = [
        Episode(
            podcast="American Optimist",
            title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
            published=datetime.now() - timedelta(days=1),
            duration="36 minutes",
            audio_url="https://example.com/test1.mp3",
            apple_podcast_id="1573141757",
            description="Join Joe Lonsdale as he talks with Marc Andreessen about the future of AI. Sponsored by Eight Sleep - visit eightsleep.com/optimist for $150 off. Also brought to you by Athletic Greens - go to athleticgreens.com/optimist for a free vitamin D supplement.",
            link="https://podcasts.apple.com/us/podcast/american-optimist/id1573141757?i=1000715621905"
        ),
        Episode(
            podcast="Forward Guidance",
            title="The Only Assets That Beat Fiat Debasement | Raoul Pal & Julien Bittel",
            published=datetime.now() - timedelta(days=2),
            duration="1 hour 10 minutes",
            audio_url="https://example.com/test2.mp3",
            apple_podcast_id="1592743188",
            description="Raoul Pal and Julien Bittel discuss investment strategies. This episode is sponsored by Real Vision - visit realvision.com/forward for a free trial.",
            link="https://podcasts.apple.com/us/podcast/forward-guidance/id1592743188"
        )
    ]
    
    # Create sample summaries
    summaries = [
        {
            "episode": episodes[0],
            "paragraph_summary": "Marc Andreessen joins Joe Lonsdale to explore America's industrial renaissance driven by AI and robotics. They discuss how automation could revitalize American manufacturing, the geopolitical implications of technological leadership, and why the next decade might see unprecedented innovation in physical industries. Andreessen argues that combining AI with robotics will create a new paradigm where the US can compete globally in manufacturing while creating higher-value jobs.",
            "summary": """## Key Themes

### The New Industrial Revolution
Marc Andreessen argues that we're at the beginning of a new industrial revolution combining AI and robotics. Unlike previous automation waves, this one will be characterized by flexible, intelligent systems that can adapt to different tasks. He sees this as America's opportunity to reclaim manufacturing leadership.

### Investment Implications
The discussion highlights several investment themes:
- **Robotics companies** building general-purpose systems
- **AI infrastructure** players enabling edge computing
- **Supply chain** technology solving coordination problems
- **Energy infrastructure** to power compute-intensive operations

### The China Challenge
Andreessen addresses the geopolitical dimension, noting that China's manufacturing dominance is vulnerable to technological disruption. He believes the US can leapfrog China by building entirely new, automated supply chains rather than competing on labor costs.

### Future of Work
Contrary to doom scenarios, Andreessen is optimistic about employment. He argues that automation will create new categories of jobs we can't yet imagine, just as the internet created roles like "social media manager" that didn't exist 20 years ago.

## Resources Mentioned
- Book: "The Rise and Fall of American Growth" by Robert Gordon
- Paper: "The Economics of Artificial Intelligence" from NBER
- Website: a16z.com/future for more on their industrial thesis"""
        },
        {
            "episode": episodes[1],
            "paragraph_summary": "Raoul Pal and Julien Bittel analyze which assets can outperform currency debasement in the current macro environment. They examine the case for cryptocurrencies, technology stocks, and real assets, arguing that traditional 60/40 portfolios will struggle. The conversation reveals why exponential growth assets may be the only way to preserve wealth as central banks continue expanding money supply.",
            "summary": """## Investment Framework

### The Debasement Problem
Pal lays out the core challenge: central banks globally are debasing currencies at 8-15% annually through money printing. Traditional assets like bonds and even stocks struggle to keep pace. He shows data indicating that only assets with exponential growth characteristics have consistently beaten debasement.

### Crypto as the Solution
The discussion centers on cryptocurrency, particularly Bitcoin and Ethereum, as the primary debasement hedge. Pal argues that crypto's fixed supply and network effects create a structural advantage over fiat currencies. He presents data showing crypto's outperformance during monetary expansion periods.

### Technology Stocks
Beyond crypto, they identify specific technology companies with network effects and pricing power. Companies like NVIDIA benefiting from AI, or platforms with strong moats, can grow faster than money supply expansion. The key is finding businesses with exponential, not linear, growth.

### Portfolio Construction
Pal suggests a barbell approach:
- 20-30% in cryptocurrency for maximum debasement protection
- 40-50% in high-growth technology stocks
- 20-30% in cash/short-term bonds for optionality
- Minimal allocation to traditional value stocks or commodities

## Resources Mentioned
- Real Vision Pro for institutional research
- Book: "The Bitcoin Standard" by Saifedean Ammous
- Website: globalmacroinvestor.com for Pal's research"""
        }
    ]
    
    # Generate email HTML
    digest = EmailDigest()
    html = digest.generate_html_preview(summaries)
    
    # Save to file for viewing
    output_path = Path("test_email_output.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"✅ Test email saved to: {output_path}")
    print("\nKey changes implemented:")
    print("  1. ✅ Full episode title as header (no subtitle)")
    print("  2. ✅ Apple Podcasts logo fixed (base64 SVG)")
    print("  3. ✅ Changed to 'Full Episode' text")
    print("  4. ✅ Elegant single arrow (▶) that rotates on expand")
    print("  5. ✅ Scroll position fix with onclick handler")
    print("  6. ✅ Sponsors in footer-style box with bullet separators")
    
    print("\nOpen test_email_output.html in a browser to preview the changes.")


if __name__ == "__main__":
    test_email_format()