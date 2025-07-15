#!/usr/bin/env python3
"""
Migration script to add paragraph_summary columns to database
"""

import sqlite3
from pathlib import Path
import sys

# Add the parent directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.config import DB_PATH
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

def migrate_database():
    """Add paragraph_summary columns to episodes table"""
    try:
        # Use the main database path
        db_path = Path.cwd() / "renaissance_weekly.db"
        
        logger.info(f"Opening database: {db_path}")
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Check if columns already exist
            cursor.execute("PRAGMA table_info(episodes)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # Add paragraph_summary column if it doesn't exist
            if 'paragraph_summary' not in columns:
                logger.info("Adding paragraph_summary column...")
                cursor.execute("ALTER TABLE episodes ADD COLUMN paragraph_summary TEXT")
                logger.info("✅ Added paragraph_summary column")
            else:
                logger.info("paragraph_summary column already exists")
            
            # Add paragraph_summary_test column if it doesn't exist
            if 'paragraph_summary_test' not in columns:
                logger.info("Adding paragraph_summary_test column...")
                cursor.execute("ALTER TABLE episodes ADD COLUMN paragraph_summary_test TEXT")
                logger.info("✅ Added paragraph_summary_test column")
            else:
                logger.info("paragraph_summary_test column already exists")
            
            conn.commit()
            
        logger.info("✅ Database migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    if migrate_database():
        print("Migration successful!")
    else:
        print("Migration failed!")
        sys.exit(1)