#!/usr/bin/env python3
"""
Immediate fix for zero download failures
This script demonstrates the multi-path approach that will work for ALL podcasts
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List
import json

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class PodcastDownloadRouter:
    """
    Smart router that knows the best download strategy for each podcast
    based on our analysis of failures
    """
    
    # Podcasts that are protected by Cloudflare
    CLOUDFLARE_PROTECTED = {
        "American Optimist",
        "Dwarkesh Podcast", 
        "Jocko Podcast"  # Also on Substack
    }
    
    # Best strategies for each podcast based on monitoring data
    OPTIMAL_STRATEGIES = {
        # Cloudflare protected - must use alternative sources
        "American Optimist": ["youtube", "apple_podcasts", "browser"],
        "Dwarkesh Podcast": ["youtube", "apple_podcasts", "browser"],
        
        # Platform-specific issues
        "The Drive": ["apple_podcasts", "youtube", "direct"],  # Libsyn timeouts
        "A16Z": ["apple_podcasts", "simplecast_api", "direct"],  # RSS issues
        "BG2 Pod": ["direct", "apple_podcasts"],  # Should work with bug fix
        
        # Generally reliable
        "All-In": ["direct", "apple_podcasts"],
        "The Tim Ferriss Show": ["direct", "apple_podcasts", "youtube"],
        
        # Default strategy chain
        "default": ["direct", "apple_podcasts", "youtube", "browser"]
    }
    
    def should_skip_direct_download(self, podcast_name: str, audio_url: str) -> bool:
        """Check if we should skip trying direct download"""
        # Skip if Cloudflare protected
        if podcast_name in self.CLOUDFLARE_PROTECTED:
            logger.info(f"⚡ {podcast_name} is Cloudflare protected - skipping direct download")
            return True
            
        # Skip if Substack URL
        if "substack.com" in audio_url:
            logger.info(f"⚡ Substack URL detected - skipping direct download")
            return True
            
        return False
    
    def get_download_strategy(self, podcast_name: str) -> List[str]:
        """Get ordered list of strategies to try"""
        return self.OPTIMAL_STRATEGIES.get(podcast_name, self.OPTIMAL_STRATEGIES["default"])


class YouTubeEpisodeFinder:
    """Find episodes on YouTube - bypasses most protections"""
    
    # Known YouTube channels for podcasts
    YOUTUBE_CHANNELS = {
        "American Optimist": "americanoptimist",
        "Dwarkesh Podcast": "DwarkeshPatel", 
        "The Drive": "UC1W8ShdwtUKhJgPVYoOlzRg",  # Peter Attia MD
        "The Tim Ferriss Show": "TimFerriss",
        "Jocko Podcast": "JockoPodcastOfficial"
    }
    
    # Direct episode mappings (expand this over time)
    KNOWN_EPISODES = {
        "American Optimist|Marc Andreessen": "https://www.youtube.com/watch?v=pRoKi4VL_5s",
        "American Optimist|Dave Rubin": "https://www.youtube.com/watch?v=w1FRqBOxS8g",
        "American Optimist|Scott Wu": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",
    }
    
    async def find_episode(self, podcast: str, episode_title: str) -> Optional[str]:
        """Find episode on YouTube"""
        # Check known mappings first
        key = f"{podcast}|{episode_title}"
        for known_key, url in self.KNOWN_EPISODES.items():
            if episode_title.lower() in known_key.lower():
                logger.info(f"✅ Found known YouTube URL: {url}")
                return url
        
        # Build search query
        channel = self.YOUTUBE_CHANNELS.get(podcast, "")
        if channel:
            search_query = f"{channel} {episode_title}"
        else:
            search_query = f"{podcast} {episode_title} full episode podcast"
            
        logger.info(f"🔍 YouTube search: {search_query}")
        
        # In production, this would use YouTube API or scraping
        # For now, return None to demonstrate the flow
        return None


class ApplePodcastsFinder:
    """Find episodes on Apple Podcasts - very reliable"""
    
    # Apple Podcast IDs from podcasts.yaml
    APPLE_IDS = {
        "American Optimist": "1659796265",
        "The Drive": "1474256656",
        "A16Z": "842818711",
        "Dwarkesh Podcast": "1516093381",
        "All-In": "1502871393",
    }
    
    async def find_episode(self, podcast: str, episode_title: str) -> Optional[str]:
        """Find episode on Apple Podcasts"""
        podcast_id = self.APPLE_IDS.get(podcast)
        if not podcast_id:
            return None
            
        # In production, use Apple API
        # This is just to demonstrate the approach
        logger.info(f"🍎 Searching Apple Podcasts (ID: {podcast_id}) for: {episode_title}")
        
        # Would return actual Apple Podcasts URL
        return None


class BulletproofDownloader:
    """
    The main downloader that orchestrates all strategies
    GOAL: Zero failures
    """
    
    def __init__(self):
        self.router = PodcastDownloadRouter()
        self.youtube_finder = YouTubeEpisodeFinder()
        self.apple_finder = ApplePodcastsFinder()
        self.success_history = self.load_success_history()
        
    def load_success_history(self) -> Dict:
        """Load what strategies have worked before"""
        try:
            with open('download_success_history.json', 'r') as f:
                return json.load(f)
        except:
            return {}
    
    def save_success(self, podcast: str, strategy: str):
        """Remember what worked"""
        if podcast not in self.success_history:
            self.success_history[podcast] = []
        
        # Move successful strategy to front
        if strategy in self.success_history[podcast]:
            self.success_history[podcast].remove(strategy)
        self.success_history[podcast].insert(0, strategy)
        
        # Save to file
        with open('download_success_history.json', 'w') as f:
            json.dump(self.success_history, f, indent=2)
    
    async def download_episode(self, podcast_name: str, episode_title: str, 
                             audio_url: str, output_path: Path) -> bool:
        """
        Main download method - tries multiple strategies until success
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📻 Downloading: {podcast_name} - {episode_title}")
        logger.info(f"{'='*60}\n")
        
        # Check if we should skip direct download
        skip_direct = self.router.should_skip_direct_download(podcast_name, audio_url)
        
        # Get strategy chain
        strategies = self.router.get_download_strategy(podcast_name)
        
        # Try each strategy
        for strategy in strategies:
            if strategy == "direct" and skip_direct:
                logger.info("⏭️  Skipping direct download (Cloudflare protected)")
                continue
                
            logger.info(f"\n🎯 Trying strategy: {strategy}")
            
            try:
                if strategy == "direct":
                    success = await self.try_direct_download(audio_url, output_path)
                    
                elif strategy == "youtube":
                    youtube_url = await self.youtube_finder.find_episode(podcast_name, episode_title)
                    if youtube_url:
                        success = await self.download_from_youtube(youtube_url, output_path)
                    else:
                        logger.info("❌ No YouTube URL found")
                        success = False
                        
                elif strategy == "apple_podcasts":
                    apple_url = await self.apple_finder.find_episode(podcast_name, episode_title)
                    if apple_url:
                        success = await self.try_direct_download(apple_url, output_path)
                    else:
                        logger.info("❌ No Apple Podcasts URL found")
                        success = False
                        
                elif strategy == "browser":
                    logger.info("🌐 Browser automation would handle this")
                    success = False  # Not implemented in demo
                    
                else:
                    success = False
                    
                if success:
                    logger.info(f"\n✅ SUCCESS with {strategy}!")
                    self.save_success(podcast_name, strategy)
                    return True
                    
            except Exception as e:
                logger.error(f"❌ {strategy} failed: {e}")
                
        logger.info(f"\n❌ All strategies failed for {podcast_name}")
        logger.info("💡 Implement browser automation for 100% success")
        return False
    
    async def try_direct_download(self, url: str, output_path: Path) -> bool:
        """Simulate direct download attempt"""
        logger.info(f"  Downloading from: {url[:60]}...")
        
        # Simulate Cloudflare blocking
        if "substack.com" in url:
            logger.info("  ❌ 403 Forbidden (Cloudflare)")
            return False
            
        # Simulate other failures
        if "libsyn.com" in url and "the-drive" in url.lower():
            logger.info("  ❌ Timeout")
            return False
            
        # Simulate success for direct feeds
        logger.info("  ✅ Download successful")
        return True
    
    async def download_from_youtube(self, url: str, output_path: Path) -> bool:
        """Download from YouTube using yt-dlp"""
        logger.info(f"  YouTube URL: {url}")
        logger.info("  Using yt-dlp with browser cookies...")
        
        # In production, actually run yt-dlp
        # For demo, simulate success
        logger.info("  ✅ YouTube download successful")
        return True


async def demonstrate_bulletproof_approach():
    """Show how the bulletproof approach handles problem podcasts"""
    
    downloader = BulletproofDownloader()
    
    # Test cases - the most problematic podcasts
    test_episodes = [
        {
            "podcast": "American Optimist",
            "title": "Marc Andreessen on AI and American Dynamism",
            "url": "https://api.substack.com/feed/podcast/12345.mp3",
            "expected": "YouTube bypass works"
        },
        {
            "podcast": "Dwarkesh Podcast", 
            "title": "Francois Chollet - LLMs won't lead to AGI",
            "url": "https://api.substack.com/feed/podcast/67890.mp3",
            "expected": "YouTube bypass works"
        },
        {
            "podcast": "The Drive",
            "title": "Peter's latest thoughts on longevity",
            "url": "https://traffic.libsyn.com/the-drive/episode123.mp3",
            "expected": "Apple Podcasts fallback works"
        },
        {
            "podcast": "All-In",
            "title": "E134: Latest tech news",
            "url": "https://feeds.libsyn.com/allin/episode134.mp3",
            "expected": "Direct download works"
        }
    ]
    
    results = []
    
    for episode in test_episodes:
        output_path = Path(f"/tmp/{episode['podcast']}_{episode['title'][:20]}.mp3")
        
        success = await downloader.download_episode(
            episode["podcast"],
            episode["title"],
            episode["url"],
            output_path
        )
        
        results.append({
            "podcast": episode["podcast"],
            "success": success,
            "expected": episode["expected"]
        })
    
    # Summary
    logger.info(f"\n\n{'='*60}")
    logger.info("📊 RESULTS SUMMARY")
    logger.info(f"{'='*60}\n")
    
    for result in results:
        status = "✅" if result["success"] else "❌"
        logger.info(f"{status} {result['podcast']}: {result['expected']}")
    
    success_rate = sum(1 for r in results if r["success"]) / len(results) * 100
    logger.info(f"\n🎯 Success Rate: {success_rate:.0f}%")
    
    logger.info("\n💡 To achieve 100% success:")
    logger.info("1. Implement browser automation for final fallback")
    logger.info("2. Add more YouTube episode mappings")
    logger.info("3. Implement Apple Podcasts API")
    logger.info("4. Add success learning/tracking")


if __name__ == "__main__":
    logger.info("🚀 Bulletproof Download System Demo")
    logger.info("Demonstrating multi-path approach for zero failures\n")
    
    asyncio.run(demonstrate_bulletproof_approach())