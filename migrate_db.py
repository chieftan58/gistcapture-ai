#!/usr/bin/env python3
"""
Manually trigger database migration to add mode-specific columns.
"""

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.config import DB_PATH

print(f"Migrating database at: {DB_PATH}")
print("This will add transcript_test and summary_test columns")
print("All existing transcripts and summaries will be cleared (Option A)")
print("")

# Simply creating the database instance will trigger migration if needed
db = PodcastDatabase()

print("\nMigration complete! Current schema:")

import sqlite3
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(episodes)")
columns = cursor.fetchall()

print("\nColumns in episodes table:")
for col in columns:
    if 'transcript' in col[1] or 'summary' in col[1]:
        print(f"  - {col[1]} ({col[2]})")

conn.close()