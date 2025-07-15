#!/usr/bin/env python
"""
Clear all caches for Renaissance Weekly to ensure fresh processing.
"""

import os
import shutil
import sqlite3
from pathlib import Path

def clear_caches():
    """Clear all cached data"""
    print("🧹 Clearing all Renaissance Weekly caches...")
    
    # 1. Clear summary files
    summary_dir = Path("summaries")
    if summary_dir.exists():
        count = len(list(summary_dir.glob("*.md")))
        for file in summary_dir.glob("*.md"):
            file.unlink()
        print(f"✓ Cleared {count} summary files")
    
    # 2. Clear audio files
    audio_dir = Path("audio")
    if audio_dir.exists():
        count = len(list(audio_dir.glob("*.mp3")))
        for file in audio_dir.glob("*.mp3"):
            file.unlink()
        print(f"✓ Cleared {count} audio files")
    
    # 3. Clear database caches
    db_path = Path("renaissance_weekly.db")
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Clear summaries
        cursor.execute("""
            UPDATE episodes 
            SET summary = NULL, 
                summary_test = NULL, 
                paragraph_summary = NULL, 
                paragraph_summary_test = NULL 
            WHERE summary IS NOT NULL 
               OR summary_test IS NOT NULL
               OR paragraph_summary IS NOT NULL
               OR paragraph_summary_test IS NOT NULL
        """)
        summaries_cleared = cursor.rowcount
        
        # Clear transcripts (optional - comment out if you want to keep transcripts)
        cursor.execute("""
            UPDATE episodes 
            SET transcript = NULL, 
                transcript_test = NULL 
            WHERE transcript IS NOT NULL 
               OR transcript_test IS NOT NULL
        """)
        transcripts_cleared = cursor.rowcount
        
        # Reset processing status
        cursor.execute("""
            UPDATE episodes 
            SET processing_status = 'pending',
                processing_started_at = NULL,
                processing_completed_at = NULL
            WHERE processing_status != 'pending'
        """)
        status_reset = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        print(f"✓ Cleared {summaries_cleared} episode summaries from database")
        print(f"✓ Cleared {transcripts_cleared} episode transcripts from database")
        print(f"✓ Reset processing status for {status_reset} episodes")
    
    # 4. Clear temporary files
    temp_dir = Path("temp")
    if temp_dir.exists():
        count = 0
        for pattern in ["download_state_*.json", "ui_state_*.json", "*.tmp"]:
            for file in temp_dir.glob(pattern):
                file.unlink()
                count += 1
        print(f"✓ Cleared {count} temporary files")
    
    # 5. Clear monitoring data (optional)
    monitoring_dir = Path("monitoring_data")
    if monitoring_dir.exists():
        response = input("Clear monitoring data? (y/N): ")
        if response.lower() == 'y':
            shutil.rmtree(monitoring_dir)
            monitoring_dir.mkdir()
            print("✓ Cleared monitoring data")
    
    print("\n✅ All caches cleared successfully!")
    print("   You can now run 'python main.py' for a fresh processing run.")


if __name__ == "__main__":
    clear_caches()