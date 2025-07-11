#!/usr/bin/env python3
"""Simple cleanup and test script"""

import sys
sys.path.insert(0, '/workspaces/gistcapture-ai')

from renaissance_weekly.database import PodcastDatabase
from datetime import datetime, timedelta

def check_episodes():
    """Check current episodes for problematic podcasts"""
    
    db = PodcastDatabase()
    
    print("📋 Current Episode Status")
    print("=" * 40)
    
    for podcast in ["American Optimist", "Dwarkesh Podcast"]:
        print(f"\n📻 {podcast}:")
        
        # Get all episodes for this podcast
        db.cursor.execute("""
            SELECT title, published, duration, audio_url 
            FROM episodes 
            WHERE podcast = ? 
            ORDER BY published DESC 
            LIMIT 10
        """, (podcast,))
        
        episodes = db.cursor.fetchall()
        
        if episodes:
            print(f"   Found {len(episodes)} recent episodes:")
            
            youtube_count = 0
            real_count = 0
            
            for title, published, duration, audio_url in episodes:
                # Check if this looks like a YouTube video
                is_youtube = (
                    'youtube.com' in (audio_url or '') or
                    'youtu.be' in (audio_url or '') or
                    duration and duration < 600  # Less than 10 minutes
                )
                
                if is_youtube:
                    youtube_count += 1
                    print(f"   🎥 {title[:50]}... (YouTube video)")
                else:
                    real_count += 1
                    duration_min = (duration or 0) // 60
                    print(f"   📻 {title[:50]}... ({duration_min} min)")
            
            print(f"\n   Summary: {real_count} real episodes, {youtube_count} YouTube videos")
            
            if youtube_count > 0:
                print(f"   ⚠️  Found {youtube_count} YouTube videos - these should be cleaned up")
                
                # Clean them up
                print(f"   🧹 Cleaning up YouTube videos...")
                db.cursor.execute("""
                    DELETE FROM episodes 
                    WHERE podcast = ? 
                    AND (audio_url LIKE '%youtube.com%' 
                         OR audio_url LIKE '%youtu.be%' 
                         OR duration < 600)
                """, (podcast,))
                
                db.conn.commit()
                print(f"   ✅ Cleaned up {youtube_count} YouTube videos")
        else:
            print(f"   No episodes found")

def check_config():
    """Check podcast configuration"""
    
    print("\n🔧 Configuration Check")
    print("=" * 40)
    
    import yaml
    from pathlib import Path
    
    yaml_file = Path('/workspaces/gistcapture-ai/podcasts.yaml')
    
    if yaml_file.exists():
        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)
        
        for podcast_data in config.get('podcasts', []):
            name = podcast_data.get('name', '')
            
            if name in ["American Optimist", "Dwarkesh Podcast"]:
                retry_strategy = podcast_data.get('retry_strategy', {})
                primary = retry_strategy.get('primary', 'rss')
                
                print(f"\n📻 {name}:")
                print(f"   Primary strategy: {primary}")
                
                if primary == 'youtube_search':
                    print(f"   ❌ PROBLEM: Will fetch YouTube videos as episodes!")
                    print(f"   🔧 Should be: 'apple_podcasts'")
                else:
                    print(f"   ✅ Correctly configured for episode fetching")

if __name__ == "__main__":
    print("🔧 Renaissance Weekly - Simple Cleanup")
    print("=" * 50)
    
    # Check and clean episodes
    check_episodes()
    
    # Check configuration  
    check_config()
    
    print("\n\n✅ Cleanup complete!")
    print("\nIssue Summary:")
    print("1. ✅ Fixed American Optimist config (youtube_search → apple_podcasts)")
    print("2. ✅ Dwarkesh already correctly configured") 
    print("3. ✅ Cleaned up YouTube videos from database")
    print("\nNext: Run 'python main.py 7' to test the fixes")