#!/usr/bin/env python3
"""Test that transcription mode defaults to 'full' throughout the system"""

import sys
sys.path.append('.')

print("=" * 80)
print("TESTING TRANSCRIPTION MODE CONSISTENCY")
print("=" * 80)

# Test 1: Check database default
print("\n1. Testing database save_episode default mode:")
from renaissance_weekly.database import PodcastDatabase
import inspect
sig = inspect.signature(PodcastDatabase.save_episode)
default_mode = sig.parameters['transcription_mode'].default
print(f"   Default mode: {default_mode}")
print(f"   ✅ PASS" if default_mode == 'full' else f"   ❌ FAIL - Expected 'full', got '{default_mode}'")

# Test 2: Check app default
print("\n2. Testing app initialization default mode:")
from renaissance_weekly.app import RenaissanceWeekly
app = RenaissanceWeekly()
print(f"   Current mode: {app.current_transcription_mode}")
print(f"   ✅ PASS" if app.current_transcription_mode == 'full' else f"   ❌ FAIL")

# Test 3: Check download manager default
print("\n3. Testing download manager default mode:")
from renaissance_weekly.download_manager import DownloadManager
sig = inspect.signature(DownloadManager.__init__)
default_mode = sig.parameters['transcription_mode'].default
print(f"   Default mode: {default_mode}")
print(f"   ✅ PASS" if default_mode == 'full' else f"   ❌ FAIL")

# Test 4: Check UI configuration
print("\n4. Testing UI configuration default mode:")
from renaissance_weekly.ui.selection import EpisodeSelector
selector = EpisodeSelector(db=app.db)
default_config = selector.configuration
print(f"   Configuration: {default_config}")
if 'transcription_mode' in default_config:
    mode = default_config['transcription_mode']
    print(f"   Mode: {mode}")
    print(f"   ✅ PASS" if mode == 'full' else f"   ❌ FAIL")
else:
    print("   Mode not yet set (will be set during initialization)")

# Test 5: Test episode saving with current mode
print("\n5. Testing episode save with app's current mode:")
from renaissance_weekly.models import Episode
from datetime import datetime

test_episode = Episode(
    podcast="Test Podcast",
    title="Mode Test Episode",
    published=datetime.now(),
    audio_url="https://example.com/test.mp3",
    guid="test-mode-guid-123"
)

try:
    # This should use the app's current mode (full)
    result = app.db.save_episode(test_episode, transcription_mode=app.current_transcription_mode)
    print(f"   Save result: {'SUCCESS' if result > 0 else 'FAILED'}")
    
    # Check what mode was actually saved
    import sqlite3
    with sqlite3.connect(app.db.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT transcription_mode FROM episodes 
            WHERE guid = ?
        """, ("test-mode-guid-123",))
        saved_mode = cursor.fetchone()
        if saved_mode:
            print(f"   Saved with mode: {saved_mode[0]}")
            print(f"   ✅ PASS" if saved_mode[0] == 'full' else f"   ❌ FAIL")
        
        # Clean up
        cursor.execute("DELETE FROM episodes WHERE guid = ?", ("test-mode-guid-123",))
        conn.commit()
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 80)
print("SUMMARY: All components should default to 'full' mode")
print("=" * 80)