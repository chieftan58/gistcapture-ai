#!/usr/bin/env python3
"""Test the bulletproof download system"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add the project to path
sys.path.insert(0, '/workspaces/gistcapture-ai')

from renaissance_weekly.download_strategies.smart_router import SmartDownloadRouter
from renaissance_weekly.models import Episode


async def test_problem_podcasts():
    """Test the most problematic podcasts that are currently failing"""
    
    print("🚀 Testing Bulletproof Download System")
    print("=" * 60)
    print()
    
    # Create test episodes that are known to fail
    test_episodes = [
        {
            'episode': Episode(
                podcast="American Optimist",
                title="Marc Andreessen on AI and American Dynamism",
                audio_url="https://api.substack.com/feed/podcast/12345.mp3",  # This will fail
                published=datetime.now(),
                duration=3600
            ),
            'expected': "YouTube bypass should work"
        },
        {
            'episode': Episode(
                podcast="Dwarkesh Podcast",
                title="Francois Chollet - LLMs won't lead to AGI",
                audio_url="https://api.substack.com/feed/podcast/67890.mp3",  # This will fail
                published=datetime.now(),
                duration=3600
            ),
            'expected': "YouTube bypass should work"
        },
        {
            'episode': Episode(
                podcast="The Drive",
                title="Peter's latest thoughts on longevity",
                audio_url="https://traffic.libsyn.com/the-drive/episode123.mp3",  # May timeout
                published=datetime.now(),
                duration=3600
            ),
            'expected': "Apple Podcasts fallback should work"
        },
        {
            'episode': Episode(
                podcast="All-In",
                title="E134: Latest tech news and analysis",
                audio_url="https://feeds.libsyn.com/allin/episode134.mp3",
                published=datetime.now(),
                duration=3600
            ),
            'expected': "Direct download should work"
        }
    ]
    
    # Test each episode
    router = SmartDownloadRouter()
    results = []
    
    for test_case in test_episodes:
        episode = test_case['episode']
        expected = test_case['expected']
        
        print(f"📻 Testing: {episode.podcast} - {episode.title}")
        print(f"Expected: {expected}")
        print("-" * 40)
        
        # Create episode info dict
        episode_info = {
            'podcast': episode.podcast,
            'title': episode.title,
            'audio_url': episode.audio_url,
            'published': episode.published
        }
        
        # Create temporary output path
        output_path = Path(f"/tmp/test_{episode.podcast.replace(' ', '_')}.mp3")
        
        # Test download
        try:
            success = await router.download_with_fallback(episode_info, output_path)
            
            if success and output_path.exists():
                file_size = output_path.stat().st_size
                print(f"✅ SUCCESS! Downloaded {file_size / 1024 / 1024:.1f} MB")
                output_path.unlink()  # Clean up
                results.append({'podcast': episode.podcast, 'success': True})
            else:
                print(f"❌ FAILED - No file downloaded")
                results.append({'podcast': episode.podcast, 'success': False})
                
        except Exception as e:
            print(f"💥 ERROR: {e}")
            results.append({'podcast': episode.podcast, 'success': False})
        
        print()
    
    # Summary
    print("=" * 60)
    print("📊 RESULTS SUMMARY")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r['success'])
    total_count = len(results)
    success_rate = (success_count / total_count) * 100 if total_count > 0 else 0
    
    for result in results:
        status = "✅" if result['success'] else "❌"
        print(f"{status} {result['podcast']}")
    
    print(f"\n🎯 Success Rate: {success_rate:.0f}% ({success_count}/{total_count})")
    
    if success_rate >= 75:
        print("🎉 Excellent! The bulletproof system is working!")
    elif success_rate >= 50:
        print("🔧 Good progress! Some strategies are working.")
    else:
        print("⚠️  Need more work. Check error messages above.")
    
    print()
    print("💡 To improve success rate:")
    print("1. Add more YouTube episode mappings to youtube_strategy.py")
    print("2. Ensure you're logged into YouTube in Firefox/Chrome")
    print("3. Consider implementing Apple Podcasts API integration")
    
    # Show strategy statistics
    stats = router.get_statistics()
    if stats['strategies_by_success']:
        print(f"\n📈 Strategy Success Count:")
        for strategy, count in stats['strategies_by_success'].items():
            print(f"   {strategy}: {count} successes")


async def test_youtube_strategy_only():
    """Test just the YouTube strategy with known URLs"""
    
    print("\n🎥 Testing YouTube Strategy with Known URLs")
    print("=" * 60)
    
    from renaissance_weekly.download_strategies.youtube_strategy import YouTubeStrategy
    
    youtube = YouTubeStrategy()
    
    # Test with known YouTube URL
    episode_info = {
        'podcast': 'American Optimist',
        'title': 'Marc Andreessen on AI',
        'audio_url': 'https://api.substack.com/feed/podcast/fake.mp3',
        'published': datetime.now()
    }
    
    output_path = Path("/tmp/test_youtube_direct.mp3")
    
    print("Testing YouTube strategy with known mapping...")
    
    try:
        success, error = await youtube.download(
            episode_info['audio_url'],
            output_path,
            episode_info
        )
        
        if success:
            print("✅ YouTube strategy works!")
            if output_path.exists():
                output_path.unlink()
        else:
            print(f"❌ YouTube strategy failed: {error}")
            
    except Exception as e:
        print(f"💥 YouTube strategy error: {e}")


if __name__ == "__main__":
    print("Starting bulletproof download system test...\n")
    
    # Test the complete system
    asyncio.run(test_problem_podcasts())
    
    # Test YouTube strategy specifically
    asyncio.run(test_youtube_strategy_only())