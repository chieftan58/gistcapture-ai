#!/usr/bin/env python3
"""Test script to generate an email preview with the mobile fixes"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from renaissance_weekly.email.digest import EmailDigest
from renaissance_weekly.models import Episode

# Create test episodes
episodes = []
summaries = []

# Episode 1
ep1 = Episode(
    guid="test-1",
    title="Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
    podcast="American Optimist",
    published=datetime.now() - timedelta(days=2),
    duration="36 minutes",
    apple_podcast_id="1573141757",
    link="https://example.com/episode1"
)
episodes.append(ep1)

paragraph1 = """Marc Andreessen joins Joe Lonsdale to explore America's industrial renaissance driven by AI and robotics. They discuss how automation could revitalize American manufacturing, the geopolitical implications of technological leadership, and why the next decade might see unprecedented innovation in physical industries. Andreessen argues that combining AI with robotics will create a new paradigm where the US can compete globally in manufacturing while creating higher-value jobs. The conversation covers specific investment opportunities in industrial automation, the role of government policy in fostering innovation, and how startups are already disrupting traditional manufacturing processes."""

full_summary1 = """Marc Andreessen and Joe Lonsdale dive deep into the transformation of American manufacturing through AI and robotics. Andreessen opens by explaining how the convergence of artificial intelligence, computer vision, and advanced robotics is creating unprecedented opportunities for reindustrializing America.

## The New Manufacturing Paradigm

Andreessen describes three key factors driving this transformation:

1. **Cost Curves Inverting**: "For the first time in 40 years, the cost of automated manufacturing in the US is approaching parity with offshore manual labor," he explains. This is driven by falling compute costs, better sensors, and more sophisticated AI models that can handle complex manufacturing tasks.

2. **Supply Chain Resilience**: The pandemic exposed critical vulnerabilities in global supply chains. Andreessen argues that companies are now willing to pay a 10-20% premium for domestic production to ensure reliability and reduce geopolitical risk.

3. **Technological Leap**: Unlike previous automation waves that simply replaced human actions with mechanical ones, AI-powered robotics can now handle tasks requiring judgment, quality control, and adaptation - previously the exclusive domain of skilled workers.

## Investment Opportunities

The discussion turns to specific sectors ripe for disruption:

**Precision Manufacturing**: Companies like Machina Labs are using AI-guided robotics to create custom metal parts without traditional tooling. Andreessen notes their technology can reduce setup times from weeks to hours.

**Electronics Assembly**: New startups are tackling the complex challenge of PCB assembly and electronics manufacturing, traditionally dominated by Asian suppliers. The key innovation is computer vision systems that can identify and correct defects in real-time.

**Pharmaceutical Production**: AI-controlled clean rooms and quality control systems could bring drug manufacturing back to the US, addressing both security concerns and supply chain issues highlighted during COVID.

## The Labor Question

Lonsdale raises concerns about job displacement. Andreessen's response is nuanced: "We're not eliminating jobs, we're eliminating job categories while creating new ones." He cites historical precedents - how ATMs actually increased the number of bank tellers by making branches more economical to operate.

The new jobs will require different skills:
- Robot fleet management
- AI training and optimization
- System integration and maintenance
- Quality assurance for automated systems

## Policy Implications

The conversation shifts to what government can do to accelerate this transition:

1. **Tax Incentives**: Andreessen advocates for accelerated depreciation on robotics investments and R&D tax credits for automation technology.

2. **Regulatory Reform**: Many manufacturing regulations assume human workers. Rules need updating for lights-out factories and autonomous systems.

3. **Education**: Community colleges and trade schools should pivot from traditional manufacturing skills to robotics technician and AI operator training.

## Global Competition

Andreessen warns that China is moving aggressively into industrial AI: "They're not just copying anymore - they're innovating in manufacturing automation at a pace that should concern us."

He sees this as a new space race: "Whoever masters AI-powered manufacturing will dominate the 21st century economy. It's not just about cost - it's about capability, speed, and adaptability."

## Near-Term Catalysts

Looking ahead 12-18 months, Andreessen identifies several catalysts:

- Major automotive companies announcing fully automated factories
- Breakthrough demonstrations in textile and apparel manufacturing
- First FDA approvals for AI-supervised pharmaceutical production
- Significant government contracts for automated defense manufacturing

## The Venture Landscape

From an investment perspective, Andreessen is bullish: "We're seeing pre-seed companies with prototypes that would have required $50M to develop five years ago. The barriers to entry are falling rapidly."

He advises founders to focus on specific vertical applications rather than general-purpose robotics: "Pick an industry, understand its specific needs, and build a complete solution. The horizontal platform play is too capital intensive for startups."

## Conclusion

The conversation concludes with both agreeing that the 2020s will be remembered as the decade when American manufacturing was reborn through technology. Andreessen's parting thought: "We're not trying to recreate the factories of the 1950s. We're building something entirely new - distributed, intelligent, and adaptive manufacturing networks that will be the backbone of American prosperity for the next century."

The implications for investors are clear: this transformation will create massive value, but success requires understanding both the technology and the specific industry dynamics being disrupted."""

summaries.append({
    "episode": ep1,
    "paragraph_summary": paragraph1,
    "summary": full_summary1
})

# Episode 2
ep2 = Episode(
    guid="test-2",
    title="Episode 245: Stanley Druckenmiller on Fed Policy and Market Dynamics",
    podcast="We Study Billionaires",
    published=datetime.now() - timedelta(days=4),
    duration="1h 15m",
    apple_podcast_id="1573141758",
    link="https://example.com/episode2"
)
episodes.append(ep2)

paragraph2 = """Stanley Druckenmiller shares his latest macro views, expressing concern about persistent inflation and questioning the Fed's commitment to its 2% target. He reveals being short bonds and long commodities, particularly copper and gold, while maintaining exposure to AI beneficiaries like NVIDIA. Druckenmiller sees a 70% chance of a recession by late 2025 but paradoxically expects equity markets to rise first as the Fed eventually capitulates on rate cuts. His key insight: the market is underestimating both inflation persistence and the Fed's willingness to tolerate above-target inflation for political reasons."""

full_summary2 = """Stanley Druckenmiller provides a masterclass in macro thinking, walking through his current portfolio positioning and the reasoning behind each major position.

## The Inflation Debate

Druckenmiller opens with a contrarian view on inflation: "The market is making the same mistake it made in 2021 - assuming inflation is transitory. But this time, it's assuming disinflation is permanent."

He points to several factors supporting persistent inflation:
- Labor markets remain exceptionally tight despite rate hikes
- Fiscal deficits are running at 6-7% of GDP during an expansion
- Deglobalization is structurally inflationary
- The green transition requires massive commodity consumption

"The Fed says they're committed to 2% inflation, but their actions suggest otherwise. They're already talking about rate cuts with inflation at 3.5%. That tells you everything."

## Portfolio Positioning

Druckenmiller reveals his current positions:

**Short Bonds**: "I'm as short bonds as I've been since the early 1980s. The risk-reward is tremendously skewed. Either inflation reaccelerates and bonds get crushed, or we get a recession and the Fed prints money like crazy. Either way, bonds lose."

**Long Commodities**: Significant positions in copper, gold, and uranium. "The supply-demand dynamics in commodities are the best I've seen in my career. We've underinvested for a decade while demand is accelerating from the energy transition."

**Selective Equities**: Despite macro concerns, he owns AI beneficiaries. "NVIDIA isn't expensive if you believe AI is as transformative as I do. The mistake people make is using backward-looking earnings."

## The Recession Paradox

Druckenmiller presents a seemingly contradictory view: expecting both a recession and higher equity prices. His reasoning:

"Markets don't bottom on good news. They bottom on capitulation. When the recession hits, the Fed will panic and ease aggressively. Markets will sniff this out 6-9 months early."

He sees parallels to 1974 and 2009: "The best equity returns often come when the economy looks worst, because that's when policy support is maximum."

This creates a complex trading roadmap:
1. Stay long equities near-term as momentum continues
2. Get defensive in mid-2025 as recession approaches
3. Get aggressively long in late 2025 as Fed capitulates

"The hard part isn't knowing what will happen - it's getting the timing right. That's why I focus on price action and market signals rather than economic forecasts."

## Conclusion

Druckenmiller concludes with advice for investors: "Don't fight the Fed, but also don't trust the Fed. They'll tell you one thing and do another. Watch what they do, not what they say. And always remember - in macro, being early is the same as being wrong."

His parting wisdom: "The biggest opportunities come from the biggest mistakes. Right now, the mistake is believing we've returned to the low-inflation, low-rate world of 2010-2020. That world is gone. Position accordingly."
"""

summaries.append({
    "episode": ep2,
    "paragraph_summary": paragraph2,
    "summary": full_summary2
})

# Generate the email
digest = EmailDigest()
html = digest.generate_html_preview(summaries)

# Save to file
with open("test_mobile_email_output.html", "w") as f:
    f.write(html)

print("✅ Test email generated successfully!")
print("📧 Open 'test_mobile_email_output.html' to preview the email")
print("\nKey improvements implemented:")
print("1. ✓ Reduced header spacing - tighter gaps between title lines")
print("2. ✓ Forced light mode - white background on all platforms") 
print("3. ✓ Viewport fix - 150px negative margin to prevent jumping")
print("4. ✓ Background colors enforced with !important throughout")
print("\nNote: Button text change to 'Hide Full Summary' requires JavaScript")
print("which isn't supported in email clients. The button stays as 'Read Full Summary'.")