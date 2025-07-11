#!/usr/bin/env python3
"""Quick cleanup script for Dwarkesh and American Optimist episodes"""

import sys
sys.path.insert(0, '/workspaces/gistcapture-ai')

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

def check_and_clean_episodes():
    """Check and clean up episodes for problematic podcasts"""
    
    db_path = Path('/workspaces/gistcapture-ai/renaissance_weekly.db')
    
    print("🔧 Renaissance Weekly - Quick Episode Cleanup")
    print("=" * 50)
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Check current episodes for American Optimist and Dwarkesh
        for podcast in ["American Optimist", "Dwarkesh Podcast"]:
            print(f"\n📻 {podcast}:")
            
            # Get all recent episodes
            cursor.execute("""
                SELECT title, published, duration, audio_url 
                FROM episodes 
                WHERE podcast = ? 
                ORDER BY published DESC 
                LIMIT 20
            """, (podcast,))
            
            episodes = cursor.fetchall()
            
            if episodes:
                print(f"   Found {len(episodes)} recent episodes")
                
                youtube_episodes = []
                real_episodes = []
                
                for title, published, duration, audio_url in episodes:
                    # Check if this looks like a YouTube video
                    is_youtube = (
                        audio_url and ('youtube.com' in audio_url or 'youtu.be' in audio_url) or
                        duration and duration < 600  # Less than 10 minutes
                    )
                    
                    if is_youtube:
                        youtube_episodes.append((title, published, duration, audio_url))
                        print(f"   🎥 YouTube: {title[:50]}... ({duration//60 if duration else 0} min)")
                    else:
                        real_episodes.append((title, published, duration, audio_url))
                        print(f"   📻 Real: {title[:50]}... ({duration//60 if duration else 0} min)")
                
                print(f"\n   Summary: {len(real_episodes)} real episodes, {len(youtube_episodes)} YouTube videos")
                
                # Clean up YouTube videos
                if youtube_episodes:
                    print(f"   🧹 Cleaning up {len(youtube_episodes)} YouTube videos...")
                    
                    for title, published, duration, audio_url in youtube_episodes:
                        cursor.execute("""
                            DELETE FROM episodes 
                            WHERE podcast = ? AND title = ? AND published = ?
                        """, (podcast, title, published))
                    
                    conn.commit()
                    print(f"   ✅ Removed {len(youtube_episodes)} YouTube videos")
                
                # Show remaining real episodes
                if real_episodes:
                    print(f"   📋 Remaining real episodes:")
                    for title, published, duration, audio_url in real_episodes[:3]:
                        duration_min = duration // 60 if duration else 0
                        print(f"      - {title[:60]}...")
                        print(f"        {duration_min} min, {published[:10]}")
            else:
                print(f"   No episodes found")

def check_configuration():
    """Check the podcast configuration"""
    
    print(f"\n\n🔧 Configuration Check")
    print("=" * 50)
    
    import yaml
    
    with open('/workspaces/gistcapture-ai/podcasts.yaml', 'r') as f:
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
                print(f"   ✅ Correctly configured")

if __name__ == "__main__":
    check_and_clean_episodes()
    check_configuration()
    
    print(f"\n\n✅ Cleanup complete!")
    print("Next steps:")
    print("1. Run: python main.py 7")
    print("2. Check that episodes are correctly fetched from RSS/Apple")
    print("3. Test downloads with improved system")