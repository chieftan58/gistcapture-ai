#!/usr/bin/env python3
"""Direct test of the cache check logic"""

import sys
sys.path.append('.')

import sqlite3
from pathlib import Path
from datetime import datetime

print("=" * 80)
print("DIRECT DATABASE CACHE CHECK TEST")
print("=" * 80)

# Test parameters
db_path = Path("podcast_data.db")
test_podcast = "American Optimist"
test_title = "Ep 118: Marc Andreessen on AI, Robotics & America's Industrial Renaissance"
mode = "full"  # or "test"

print(f"\nTest parameters:")
print(f"  Database: {db_path}")
print(f"  Podcast: {test_podcast}")
print(f"  Title: {test_title[:60]}...")
print(f"  Mode: {mode}")

# Determine columns based on mode
if mode == 'test':
    transcript_col = 'transcript_test'
    summary_col = 'summary_test'
    paragraph_col = 'paragraph_summary_test'
else:
    transcript_col = 'transcript'
    summary_col = 'summary'
    paragraph_col = 'paragraph_summary'

print(f"\nUsing columns:")
print(f"  Transcript: {transcript_col}")
print(f"  Summary: {summary_col}")
print(f"  Paragraph: {paragraph_col}")

# Execute the cache check query
try:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # This is the exact query from our cache check
        query = f"""
            SELECT {transcript_col}, {summary_col}, {paragraph_col}, guid, id, title
            FROM episodes 
            WHERE podcast = ? 
            AND (
                title = ? OR 
                title LIKE ? OR
                title LIKE ?
            )
            ORDER BY published DESC
            LIMIT 1
        """
        
        params = (
            test_podcast, 
            test_title,
            f"{test_title[:50]}%",  # Match by first 50 chars
            f"%{test_title[-50:]}"   # Match by last 50 chars
        )
        
        print(f"\nExecuting query...")
        print(f"Query: {query}")
        print(f"\nParameters:")
        for i, p in enumerate(params):
            print(f"  [{i}]: {p}")
        
        cursor.execute(query, params)
        result = cursor.fetchone()
        
        if result:
            cached_transcript, cached_summary, cached_paragraph, db_guid, db_id, db_title = result
            
            print(f"\n✅ FOUND MATCHING EPISODE!")
            print(f"  DB ID: {db_id}")
            print(f"  DB Title: {db_title}")
            print(f"  DB GUID: {db_guid}")
            print(f"  Transcript: {len(cached_transcript) if cached_transcript else 0} chars")
            print(f"  Full Summary: {len(cached_summary) if cached_summary else 0} chars")
            print(f"  Paragraph: {len(cached_paragraph) if cached_paragraph else 0} chars")
            
            if cached_summary and cached_paragraph:
                print(f"\n🎉 This episode is FULLY PROCESSED and would be CACHED!")
            elif cached_transcript:
                print(f"\n📝 This episode has transcript but needs summaries regenerated")
            else:
                print(f"\n⚠️  This episode has incomplete data")
        else:
            print(f"\n❌ NO MATCHING EPISODE FOUND!")
            
            # Let's see what episodes DO exist for this podcast
            print(f"\nChecking what episodes exist for '{test_podcast}'...")
            cursor.execute("""
                SELECT id, title, LENGTH(transcript), LENGTH(transcript_test), 
                       LENGTH(summary), LENGTH(summary_test)
                FROM episodes 
                WHERE podcast = ?
                ORDER BY published DESC
                LIMIT 5
            """, (test_podcast,))
            
            existing = cursor.fetchall()
            if existing:
                print(f"\nFound {len(existing)} episodes:")
                for row in existing:
                    print(f"  ID {row[0]}: {row[1][:60]}...")
                    print(f"     Transcript: full={row[2] or 0}, test={row[3] or 0}")
                    print(f"     Summary: full={row[4] or 0}, test={row[5] or 0}")
            else:
                print(f"  No episodes found for this podcast!")
                
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)