#!/usr/bin/env python
"""
Database migration script to add missing columns for transcript caching.

This fixes the critical issue where transcripts are not being cached in full mode
because the required database columns are missing.
"""

import sqlite3
import sys
from pathlib import Path

def migrate_database():
    """Add missing columns to the episodes table"""
    db_path = Path("renaissance_weekly.db")
    
    if not db_path.exists():
        print("❌ Error: renaissance_weekly.db not found!")
        return False
    
    print("🔧 Starting database migration...")
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check existing columns
        cursor.execute("PRAGMA table_info(episodes)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        print(f"📊 Current columns: {len(existing_columns)}")
        
        # Columns that should exist
        required_columns = {
            'transcript_test', 'summary_test', 'transcription_mode',
            'audio_file_path', 'audio_file_path_test'
        }
        
        # Find missing columns
        missing_columns = required_columns - existing_columns
        
        if not missing_columns:
            print("✅ All required columns already exist!")
            return True
        
        print(f"🔍 Missing columns: {missing_columns}")
        
        # Add missing columns one by one
        for column in missing_columns:
            try:
                if column == 'transcription_mode':
                    cursor.execute("ALTER TABLE episodes ADD COLUMN transcription_mode TEXT DEFAULT 'test'")
                    print(f"  ✅ Added column: {column} (default='test')")
                else:
                    cursor.execute(f"ALTER TABLE episodes ADD COLUMN {column} TEXT")
                    print(f"  ✅ Added column: {column}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print(f"  ⚠️  Column {column} already exists")
                else:
                    raise
        
        # Update existing records to have transcription_mode='full' if they have transcripts
        cursor.execute("""
            UPDATE episodes 
            SET transcription_mode = 'full' 
            WHERE transcript IS NOT NULL 
            AND transcript != '' 
            AND (transcription_mode IS NULL OR transcription_mode = 'test')
        """)
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            print(f"📝 Updated {rows_updated} existing episodes to transcription_mode='full'")
        
        # Commit changes
        conn.commit()
        print("✅ Database migration completed successfully!")
        
        # Verify the migration
        cursor.execute("PRAGMA table_info(episodes)")
        final_columns = {row[1] for row in cursor.fetchall()}
        print(f"📊 Final columns: {len(final_columns)}")
        
        # Show column details
        print("\n📋 Episode table schema:")
        cursor.execute("PRAGMA table_info(episodes)")
        for row in cursor.fetchall():
            col_id, name, col_type, not_null, default, pk = row
            print(f"  - {name}: {col_type}" + (f" DEFAULT {default}" if default else ""))
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)