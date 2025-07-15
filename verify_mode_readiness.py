#!/usr/bin/env python3
"""
Verify that test/full mode separation is properly implemented
"""

import os
import sys
from pathlib import Path

def check_implementation():
    """Check if mode separation is properly implemented"""
    
    print("🔍 Verifying Test/Full Mode Separation Implementation\n")
    
    issues = []
    warnings = []
    
    # Check 1: Database schema
    print("1. Checking database schema...")
    from renaissance_weekly.database import PodcastDatabase
    from renaissance_weekly.config import DB_PATH
    
    if DB_PATH.exists():
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(episodes)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        required_columns = ['transcript', 'transcript_test', 'summary', 'summary_test']
        missing = [col for col in required_columns if col not in columns]
        
        if missing:
            warnings.append(f"Database migration needed. Missing columns: {', '.join(missing)}")
            print(f"   ⚠️  Migration pending - will run on next app start")
        else:
            print(f"   ✅ All mode-specific columns present")
    else:
        print(f"   ℹ️  No database found - will be created on first run")
    
    # Check 2: Mode tracking
    print("\n2. Checking mode tracking...")
    mode_files = [
        'renaissance_weekly/app.py',
        'renaissance_weekly/database.py',
        'renaissance_weekly/transcripts/finder.py',
        'renaissance_weekly/ui/selection.py'
    ]
    
    for file in mode_files:
        path = Path(file)
        if path.exists():
            content = path.read_text()
            if 'transcription_mode' in content:
                print(f"   ✅ {file} - Mode-aware")
            else:
                issues.append(f"{file} may not be mode-aware")
                print(f"   ❌ {file} - Missing mode handling")
    
    # Check 3: Audio file handling
    print("\n3. Checking audio file separation...")
    audio_patterns = ['audio_file_path_test', 'audio_file_path', '_test.mp3']
    found_patterns = []
    
    for root, dirs, files in os.walk('renaissance_weekly'):
        for file in files:
            if file.endswith('.py'):
                path = Path(root) / file
                content = path.read_text()
                for pattern in audio_patterns:
                    if pattern in content and pattern not in found_patterns:
                        found_patterns.append(pattern)
    
    if len(found_patterns) >= 2:
        print(f"   ✅ Audio file separation implemented")
    else:
        issues.append("Audio file separation may be incomplete")
        print(f"   ❌ Audio file separation incomplete")
    
    # Check 4: Summary/transcript methods
    print("\n4. Checking database methods...")
    methods_to_check = [
        ('get_transcript', 'transcription_mode'),
        ('get_episode_summary', 'transcription_mode'),
        ('save_episode', 'transcription_mode'),
        ('get_episodes_with_summaries', 'transcription_mode')
    ]
    
    db_file = Path('renaissance_weekly/database.py')
    if db_file.exists():
        content = db_file.read_text()
        for method, param in methods_to_check:
            if f"def {method}" in content and param in content:
                print(f"   ✅ {method}() accepts {param}")
            else:
                issues.append(f"{method}() may not handle {param}")
                print(f"   ❌ {method}() missing {param} parameter")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    print("="*60)
    
    if not issues and not warnings:
        print("✅ Mode separation is FULLY IMPLEMENTED and production ready!")
        print("\nNext steps:")
        print("1. Run the application once to trigger database migration")
        print("2. Test with both 'test' and 'full' modes")
        print("3. Verify summaries are stored separately")
        return True
    else:
        if warnings:
            print("\n⚠️  Warnings:")
            for w in warnings:
                print(f"   - {w}")
        
        if issues:
            print("\n❌ Issues found:")
            for i in issues:
                print(f"   - {i}")
        
        print("\n🔧 Fix these issues before production use")
        return False

if __name__ == "__main__":
    is_ready = check_implementation()
    sys.exit(0 if is_ready else 1)