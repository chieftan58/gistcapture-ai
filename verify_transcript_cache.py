#!/usr/bin/env python3
"""Verify transcript cache is working"""

import sys
sys.path.append('.')

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.models import Episode
from datetime import datetime

# Create database instance
db = PodcastDatabase()

# Create a test episode object matching the Marc Andreessen episode
episode = Episode(
    podcast="American Optimist",
    title="Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance",
    published=datetime.fromisoformat("2025-07-11T11:00:00"),  # Approximate date
    audio_url="https://example.com",
    guid="whatever-guid"  # We'll test without GUID first
)

print("=== Testing Transcript Cache Lookup ===\n")

# Test 1: Look up with full mode
print("1. Testing lookup in FULL mode...")
transcript, source = db.get_transcript(episode, transcription_mode='full')
if transcript:
    print(f"✅ Found transcript! Length: {len(transcript)} chars")
    print(f"   Source: {source}")
else:
    print("❌ No transcript found")

# Test 2: Look up with test mode
print("\n2. Testing lookup in TEST mode...")
transcript, source = db.get_transcript(episode, transcription_mode='test')
if transcript:
    print(f"✅ Found transcript! Length: {len(transcript)} chars")
    print(f"   Source: {source}")
else:
    print("❌ No transcript found")

# Test 3: Check what's actually in the database
print("\n3. Checking database directly...")
import sqlite3
conn = sqlite3.connect('podcast_data.db')
cursor = conn.cursor()

cursor.execute("""
    SELECT guid, LENGTH(transcript), LENGTH(transcript_test), transcription_mode, 
           date(published) as pub_date
    FROM episodes 
    WHERE podcast = ? AND title = ?
""", ("American Optimist", "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance"))

result = cursor.fetchone()
if result:
    print(f"   GUID: {result[0]}")
    print(f"   Transcript length: {result[1]}")
    print(f"   Transcript_test length: {result[2]}")
    print(f"   Mode: {result[3]}")
    print(f"   Published date: {result[4]}")
else:
    print("   ❌ Episode not found in database!")

conn.close()