#!/usr/bin/env python
"""
Test script to verify guest name extraction and subject line generation.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project directory to path
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.models import Episode
from renaissance_weekly.email.digest import EmailDigest


def test_subject_extraction():
    """Test guest name extraction with real episode titles"""
    print("🧪 Testing guest name extraction and subject lines...")
    
    digest = EmailDigest()
    
    # Test cases
    test_titles = [
        "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
        "The Only Assets That Beat Fiat Debasement | Raoul Pal & Julien Bittel",
        "#763: Howard Marks and The Most Important Thing",
        "Daniel Kahneman: Thinking Fast and Slow",
        "Episode 25: Peter Thiel on Competition and Innovation",
        "Jim Grant: Interest Rates and Credit Markets",
        "Stanley Druckenmiller with Tony Pasquariello | The Besties",
    ]
    
    print("\n📋 Testing individual guest extraction:")
    for title in test_titles:
        guest = digest._extract_guest_name(title)
        print(f"Title: {title}")
        print(f"  → Guest: {guest}")
        print()
    
    # Test full subject line generation
    print("\n📧 Testing subject line generation:")
    
    # Scenario 1: Episodes with extractable guests
    episodes1 = [
        Episode(
            podcast="American Optimist",
            title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
            published=datetime.now() - timedelta(days=1),
            duration="36 minutes",
            audio_url="https://example.com/test1.mp3"
        ),
        Episode(
            podcast="Forward Guidance",
            title="The Only Assets That Beat Fiat Debasement | Raoul Pal & Julien Bittel",
            published=datetime.now() - timedelta(days=2),
            duration="1 hour 10 minutes",
            audio_url="https://example.com/test2.mp3"
        )
    ]
    
    subject1 = digest._generate_subject_line(episodes1)
    print(f"Scenario 1 (with guests): {subject1}")
    
    # Scenario 2: Episodes without extractable guests
    episodes2 = [
        Episode(
            podcast="Tim Ferriss",
            title="#818: Random Episode Title Without Clear Guest",
            published=datetime.now() - timedelta(days=1),
            duration="2 hours",
            audio_url="https://example.com/test3.mp3"
        ),
        Episode(
            podcast="Invest Like the Best",
            title="Market Update Q4 2024",
            published=datetime.now() - timedelta(days=2),
            duration="45 minutes",
            audio_url="https://example.com/test4.mp3"
        ),
        Episode(
            podcast="The Acquirers Podcast",
            title="Deep Value Investing Principles",
            published=datetime.now() - timedelta(days=3),
            duration="50 minutes",
            audio_url="https://example.com/test5.mp3"
        )
    ]
    
    subject2 = digest._generate_subject_line(episodes2)
    print(f"Scenario 2 (no guests): {subject2}")
    
    # Scenario 3: Many podcasts
    episodes3 = []
    for i in range(5):
        episodes3.append(Episode(
            podcast=f"Podcast {i+1}",
            title=f"Episode {i+1}",
            published=datetime.now() - timedelta(days=i),
            duration="1 hour",
            audio_url=f"https://example.com/test{i+6}.mp3"
        ))
    
    subject3 = digest._generate_subject_line(episodes3)
    print(f"Scenario 3 (many podcasts): {subject3}")
    
    print("\n✅ Testing complete!")


if __name__ == "__main__":
    test_subject_extraction()