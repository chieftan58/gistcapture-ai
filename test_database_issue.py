#!/usr/bin/env python3
"""Test to identify the exact database issue"""

import sqlite3
import sys
from datetime import datetime

# Connect to the database
conn = sqlite3.connect('renaissance_weekly.db')
cursor = conn.cursor()

print("=== Testing Database Save Issue ===\n")

# First, let's check if we can insert a simple record
print("1. Testing simple INSERT with all required columns...")

try:
    cursor.execute("""
        INSERT INTO episodes (
            podcast, title, published, audio_url, transcript_url,
            description, link, duration, guid, transcript,
            transcript_source, summary, transcript_test, summary_test,
            transcription_mode, paragraph_summary, paragraph_summary_test
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        'Test Podcast', 'Test Episode', datetime.now().isoformat(),
        'http://test.mp3', 'http://test.transcript',
        'Test description', 'http://test.link',
        '1h 23m', 'test-guid-123',
        'Test transcript content', 'assemblyai',
        'Test summary', 'Test transcript test mode', 'Test summary test mode',
        'test', 'Test paragraph summary', 'Test paragraph summary test'
    ))
    
    conn.commit()
    print("✅ INSERT succeeded!")
    print(f"   Last row ID: {cursor.lastrowid}")
    
    # Verify it was saved
    cursor.execute("SELECT COUNT(*) FROM episodes WHERE guid = ?", ('test-guid-123',))
    count = cursor.fetchone()[0]
    print(f"   Verified in database: {'YES' if count > 0 else 'NO'}")
    
except sqlite3.Error as e:
    print(f"❌ INSERT failed with error: {e}")
    print(f"   Error type: {type(e).__name__}")

# Check if there are any constraint issues
print("\n2. Checking table constraints...")
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='episodes'")
create_sql = cursor.fetchone()[0]
print("Table creation SQL:")
print(create_sql[:500] + "..." if len(create_sql) > 500 else create_sql)

# Check for any unique constraints
print("\n3. Checking for unique constraints...")
cursor.execute("PRAGMA index_list(episodes)")
indexes = cursor.fetchall()
for idx in indexes:
    print(f"   Index: {idx[1]} (unique: {idx[2]})")
    cursor.execute(f"PRAGMA index_info({idx[1]})")
    cols = cursor.fetchall()
    for col in cols:
        cursor.execute("SELECT name FROM pragma_table_info('episodes') WHERE cid = ?", (col[1],))
        col_name = cursor.fetchone()[0]
        print(f"      - {col_name}")

# Check current row count
print("\n4. Current database state...")
cursor.execute("SELECT COUNT(*) FROM episodes")
total_count = cursor.fetchone()[0]
print(f"   Total episodes in database: {total_count}")

# Clean up test record if it was inserted
try:
    cursor.execute("DELETE FROM episodes WHERE guid = ?", ('test-guid-123',))
    conn.commit()
    print("\n✅ Test record cleaned up")
except:
    pass

conn.close()