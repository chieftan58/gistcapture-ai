#!/usr/bin/env python3
"""Comprehensive database verification and diagnostics script"""

import sys
sys.path.append('.')

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.models import Episode, TranscriptSource
import json

print("=" * 80)
print("RENAISSANCE WEEKLY DATABASE DIAGNOSTICS")
print("=" * 80)

# Check which database files exist
print("\n1. DATABASE FILE CHECK:")
db_files = [
    ("podcast_data.db", "Active database"),
    ("renaissance_weekly.db", "Legacy/unused database"),
    ("podcast_data.db.backup", "Backup file")
]

for db_file, description in db_files:
    path = Path(db_file)
    if path.exists():
        size = path.stat().st_size
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        print(f"   ✅ {db_file} ({description})")
        print(f"      Size: {size:,} bytes")
        print(f"      Modified: {modified}")
    else:
        print(f"   ❌ {db_file} - NOT FOUND")

# Connect to the active database
db_path = "podcast_data.db"
if not Path(db_path).exists():
    print(f"\n❌ ERROR: Active database '{db_path}' not found!")
    sys.exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check table structure
print(f"\n2. TABLE STRUCTURE CHECK:")
cursor.execute("PRAGMA table_info(episodes)")
columns = cursor.fetchall()
print(f"   Total columns: {len(columns)}")

# Check for mode-specific columns
mode_columns = {
    'transcript': False,
    'transcript_test': False,
    'summary': False,
    'summary_test': False,
    'paragraph_summary': False,
    'paragraph_summary_test': False,
    'transcription_mode': False
}

for col in columns:
    col_name = col[1]
    if col_name in mode_columns:
        mode_columns[col_name] = True

print("\n   Mode-specific columns:")
for col, exists in mode_columns.items():
    status = "✅" if exists else "❌"
    print(f"   {status} {col}")

# Database statistics
print("\n3. DATABASE STATISTICS:")

# Total episodes
cursor.execute("SELECT COUNT(*) FROM episodes")
total_episodes = cursor.fetchone()[0]
print(f"   Total episodes: {total_episodes}")

# Episodes by mode
cursor.execute("""
    SELECT transcription_mode, COUNT(*) 
    FROM episodes 
    GROUP BY transcription_mode
""")
mode_counts = cursor.fetchall()
print("\n   Episodes by mode:")
for mode, count in mode_counts:
    print(f"      {mode or 'NULL'}: {count}")

# Episodes with transcripts
print("\n   Transcript availability:")
cursor.execute("""
    SELECT 
        COUNT(CASE WHEN transcript IS NOT NULL THEN 1 END) as full_transcripts,
        COUNT(CASE WHEN transcript_test IS NOT NULL THEN 1 END) as test_transcripts,
        COUNT(CASE WHEN transcript IS NOT NULL OR transcript_test IS NOT NULL THEN 1 END) as any_transcript
    FROM episodes
""")
result = cursor.fetchone()
print(f"      Full mode transcripts: {result[0]}")
print(f"      Test mode transcripts: {result[1]}")
print(f"      Any transcript: {result[2]}")

# Episodes with summaries
print("\n   Summary availability:")
cursor.execute("""
    SELECT 
        COUNT(CASE WHEN summary IS NOT NULL THEN 1 END) as full_summaries,
        COUNT(CASE WHEN summary_test IS NOT NULL THEN 1 END) as test_summaries,
        COUNT(CASE WHEN paragraph_summary IS NOT NULL THEN 1 END) as full_paragraphs,
        COUNT(CASE WHEN paragraph_summary_test IS NOT NULL THEN 1 END) as test_paragraphs
    FROM episodes
""")
result = cursor.fetchone()
print(f"      Full mode summaries: {result[0]}")
print(f"      Test mode summaries: {result[1]}")
print(f"      Full mode paragraphs: {result[2]}")
print(f"      Test mode paragraphs: {result[3]}")

# Recent episodes
print("\n4. RECENT EPISODES (Last 7 days):")
cursor.execute("""
    SELECT podcast, title, published, 
           LENGTH(transcript), LENGTH(transcript_test),
           LENGTH(summary), LENGTH(summary_test),
           transcription_mode, guid
    FROM episodes 
    WHERE published >= datetime('now', '-7 days')
    ORDER BY published DESC
    LIMIT 10
""")

recent = cursor.fetchall()
if recent:
    for row in recent:
        print(f"\n   📻 {row[0]}: {row[1][:60]}...")
        print(f"      Published: {row[2]}")
        print(f"      Mode: {row[7] or 'NULL'}")
        print(f"      GUID: {row[8][:20]}..." if row[8] else "      GUID: None")
        print(f"      Transcript: Full={row[3] or 0} chars, Test={row[4] or 0} chars")
        print(f"      Summary: Full={row[5] or 0} chars, Test={row[6] or 0} chars")
else:
    print("   No episodes found in the last 7 days")

# Check for duplicate episodes
print("\n5. DUPLICATE CHECK:")
cursor.execute("""
    SELECT podcast, title, COUNT(*) as count
    FROM episodes
    GROUP BY podcast, title
    HAVING count > 1
    ORDER BY count DESC
    LIMIT 5
""")

duplicates = cursor.fetchall()
if duplicates:
    print("   ⚠️ Found duplicate episodes:")
    for podcast, title, count in duplicates:
        print(f"      {podcast}: {title[:50]}... ({count} copies)")
else:
    print("   ✅ No duplicate episodes found")

# Check for potential date issues
print("\n6. DATE FORMAT ANALYSIS:")
cursor.execute("""
    SELECT DISTINCT 
        CASE 
            WHEN published LIKE '%T%' THEN 'ISO format with time'
            WHEN published LIKE '%-%-%' THEN 'Date only format'
            ELSE 'Other format'
        END as format,
        COUNT(*) as count
    FROM episodes
    GROUP BY format
""")

date_formats = cursor.fetchall()
print("   Date formats in database:")
for format_type, count in date_formats:
    print(f"      {format_type}: {count}")

# Sample date values
print("\n   Sample date values:")
cursor.execute("SELECT DISTINCT published FROM episodes ORDER BY RANDOM() LIMIT 5")
for (date_val,) in cursor.fetchall():
    print(f"      {date_val}")

# Podcast summary
print("\n7. PODCAST SUMMARY:")
cursor.execute("""
    SELECT podcast, 
           COUNT(*) as episodes,
           COUNT(CASE WHEN transcript IS NOT NULL OR transcript_test IS NOT NULL THEN 1 END) as with_transcript,
           COUNT(CASE WHEN summary IS NOT NULL OR summary_test IS NOT NULL THEN 1 END) as with_summary,
           MAX(published) as latest_episode
    FROM episodes
    GROUP BY podcast
    ORDER BY podcast
""")

podcasts = cursor.fetchall()
for podcast, episodes, transcripts, summaries, latest in podcasts:
    print(f"\n   {podcast}:")
    print(f"      Episodes: {episodes}")
    print(f"      With transcript: {transcripts} ({transcripts/episodes*100:.1f}%)")
    print(f"      With summary: {summaries} ({summaries/episodes*100:.1f}%)")
    print(f"      Latest: {latest}")

# Test transcript lookup
print("\n8. TESTING TRANSCRIPT LOOKUP:")
db = PodcastDatabase()

# Get a recent episode with a transcript
cursor.execute("""
    SELECT podcast, title, published, guid
    FROM episodes
    WHERE (transcript IS NOT NULL OR transcript_test IS NOT NULL)
    ORDER BY published DESC
    LIMIT 1
""")

if cursor.fetchone():
    cursor.execute("""
        SELECT podcast, title, published, guid
        FROM episodes
        WHERE (transcript IS NOT NULL OR transcript_test IS NOT NULL)
        ORDER BY published DESC
        LIMIT 1
    """)
    podcast, title, published, guid = cursor.fetchone()
    
    # Create episode object
    try:
        # Handle different date formats
        if isinstance(published, str):
            if 'T' in published:
                pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            else:
                pub_date = datetime.strptime(published, '%Y-%m-%d')
        else:
            pub_date = published
            
        episode = Episode(
            podcast=podcast,
            title=title,
            published=pub_date,
            audio_url="test",
            guid=guid
        )
        
        print(f"\n   Testing lookup for: {podcast} - {title[:50]}...")
        print(f"   GUID: {guid}")
        
        # Test full mode
        transcript, source = db.get_transcript(episode, transcription_mode='full')
        if transcript:
            print(f"   ✅ Full mode: Found {len(transcript)} chars (source: {source.value})")
        else:
            print(f"   ❌ Full mode: Not found")
            
        # Test test mode
        transcript, source = db.get_transcript(episode, transcription_mode='test')
        if transcript:
            print(f"   ✅ Test mode: Found {len(transcript)} chars (source: {source.value})")
        else:
            print(f"   ❌ Test mode: Not found")
            
    except Exception as e:
        print(f"   ❌ Error testing lookup: {e}")
else:
    print("   No episodes with transcripts found for testing")

conn.close()

print("\n" + "=" * 80)
print("DIAGNOSTICS COMPLETE")
print("=" * 80)