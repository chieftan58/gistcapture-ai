#!/usr/bin/env python3
"""
Fix Dwarkesh and American Optimist episode issues
1. Clean up YouTube videos incorrectly fetched as episodes  
2. Test the fixed configuration
"""

import sys
sys.path.insert(0, '/workspaces/gistcapture-ai')

from renaissance_weekly.database import PodcastDatabase
from datetime import datetime, timedelta

def clean_youtube_episodes():
    """Remove YouTube videos that were incorrectly fetched as podcast episodes"""
    
    db = PodcastDatabase()
    
    print("🧹 Cleaning up incorrectly fetched YouTube videos...")
    print("=" * 60)
    
    # Check episodes for American Optimist and Dwarkesh
    problematic_podcasts = ["American Optimist", "Dwarkesh Podcast"]
    
    for podcast in problematic_podcasts:
        print(f"\n📻 Checking {podcast}...")
        
        # Get all episodes for this podcast in last 30 days
        since_date = datetime.now() - timedelta(days=30)
        episodes = db.get_episodes_since(podcast, since_date)
        
        youtube_episodes = []
        real_episodes = []
        
        for episode in episodes:
            # Check if this looks like a YouTube video instead of podcast episode
            if any(indicator in episode.get('audio_url', '').lower() for indicator in ['youtube.com', 'youtu.be']):
                youtube_episodes.append(episode)
            elif any(indicator in episode.get('title', '').lower() for indicator in ['youtube', 'clip', 'short']):
                youtube_episodes.append(episode)
            elif episode.get('duration', 0) < 300:  # Less than 5 minutes - likely not a real episode
                youtube_episodes.append(episode)
            else:
                real_episodes.append(episode)
        
        print(f"   Real episodes: {len(real_episodes)}")
        print(f"   YouTube videos: {len(youtube_episodes)}")
        
        if youtube_episodes:
            print(f"   🗑️  Removing {len(youtube_episodes)} YouTube videos...")
            for episode in youtube_episodes:
                # Remove from database
                db.cursor.execute("""
                    DELETE FROM episodes 
                    WHERE podcast = ? AND title = ? AND published = ?
                """, (podcast, episode['title'], episode['published']))
            
            db.conn.commit()
            print(f"   ✅ Cleaned up {len(youtube_episodes)} incorrect episodes")
        
        # Show remaining episodes
        if real_episodes:
            print(f"   📋 Remaining episodes:")
            for episode in real_episodes[:5]:  # Show first 5
                print(f"      - {episode['title'][:60]}...")
                print(f"        Duration: {episode.get('duration', 0)//60:.0f} min, Published: {episode['published']}")

def test_configuration():
    """Test the fixed podcast configuration"""
    
    print("\n\n🧪 Testing Fixed Configuration")
    print("=" * 60)
    
    from renaissance_weekly.config import load_podcast_configs
    
    configs = load_podcast_configs()
    
    for podcast_name in ["American Optimist", "Dwarkesh Podcast"]:
        if podcast_name in configs:
            config = configs[podcast_name]
            retry_strategy = config.get('retry_strategy', {})
            primary = retry_strategy.get('primary', 'rss')
            
            print(f"\n📻 {podcast_name}:")
            print(f"   Primary strategy: {primary}")
            print(f"   Should fetch from: {'RSS/Apple' if primary != 'youtube_search' else 'YouTube (PROBLEM!)'}")
            
            if primary == 'youtube_search':
                print(f"   ❌ Still configured for YouTube episode fetching!")
                print(f"   🔧 Should be: 'apple_podcasts' or 'rss'")
            else:
                print(f"   ✅ Correctly configured")

def show_current_episodes():
    """Show current episodes for problematic podcasts"""
    
    print("\n\n📋 Current Episodes")
    print("=" * 60)
    
    db = PodcastDatabase()
    
    for podcast in ["American Optimist", "Dwarkesh Podcast"]:
        print(f"\n📻 {podcast}:")
        
        # Get episodes from last 14 days
        since_date = datetime.now() - timedelta(days=14)
        episodes = db.get_episodes_since(podcast, since_date)
        
        if episodes:
            print(f"   Found {len(episodes)} episodes in last 14 days:")
            for episode in episodes:
                title = episode['title'][:50] + "..." if len(episode['title']) > 50 else episode['title']
                duration_min = episode.get('duration', 0) // 60
                published = episode['published'][:10] if episode['published'] else 'Unknown'
                
                print(f"   📅 {published} | {duration_min:3d}min | {title}")
        else:
            print(f"   No episodes found in last 14 days")

if __name__ == "__main__":
    print("🔧 Renaissance Weekly - Episode Cleanup & Configuration Test")
    print("=" * 70)
    
    # Step 1: Clean up incorrect episodes
    clean_youtube_episodes()
    
    # Step 2: Test configuration
    test_configuration()
    
    # Step 3: Show current episodes
    show_current_episodes()
    
    print("\n\n✅ Cleanup complete!")
    print("Next steps:")
    print("1. Run: python main.py 7")
    print("2. Check that Dwarkesh and American Optimist show correct episode counts")
    print("3. Test download with the improved system")