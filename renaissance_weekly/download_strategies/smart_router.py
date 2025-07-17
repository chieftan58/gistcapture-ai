"""Smart download router - orchestrates all download strategies"""

import json
import asyncio
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from .youtube_strategy import YouTubeStrategy
from .direct_strategy import DirectDownloadStrategy
from .apple_strategy import ApplePodcastsStrategy
from .browser_strategy import BrowserStrategy
from ..utils.logging import get_logger
from ..config import TEMP_DIR

logger = get_logger(__name__)


class SmartDownloadRouter:
    """Routes downloads to the best strategy based on podcast, URL, and historical success"""
    
    # Podcast-specific routing rules based on analysis
    ROUTING_RULES = {
        # Cloudflare-protected podcasts - skip direct download
        "American Optimist": ["youtube", "browser"],
        "Dwarkesh Podcast": ["youtube", "apple_podcasts", "browser"],
        
        # Platform-specific issues
        "The Drive": ["apple_podcasts", "youtube", "direct"],  # Libsyn timeouts
        "A16Z": ["apple_podcasts", "direct", "youtube"],       # RSS issues
        "BG2 Pod": ["direct", "apple_podcasts"],              # Should work with bug fix
        
        # Generally reliable (try direct first)
        "All-In": ["direct", "apple_podcasts", "youtube"],
        "The Tim Ferriss Show": ["direct", "apple_podcasts", "youtube"],
        "Lex Fridman": ["direct", "apple_podcasts", "youtube"],
        "Huberman Lab": ["direct", "apple_podcasts", "youtube"],
        
        # Default strategy chain
        "default": ["direct", "apple_podcasts", "youtube", "browser"]
    }
    
    def __init__(self):
        self.strategies = {
            "youtube": YouTubeStrategy(),
            "direct": DirectDownloadStrategy(),
            "apple_podcasts": ApplePodcastsStrategy(),
            "browser": BrowserStrategy(),
        }
        
        self.success_history_file = TEMP_DIR / "download_success_history.json"
        self.success_history = self._load_success_history()
    
    def _load_success_history(self) -> Dict:
        """Load what strategies have worked before"""
        try:
            if self.success_history_file.exists():
                with open(self.success_history_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Could not load success history: {e}")
        return {}
    
    def _save_success_history(self):
        """Save success history to file"""
        try:
            TEMP_DIR.mkdir(exist_ok=True)
            with open(self.success_history_file, 'w') as f:
                json.dump(self.success_history, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not save success history: {e}")
    
    def record_success(self, podcast: str, strategy: str):
        """Remember what worked for future use"""
        if podcast not in self.success_history:
            self.success_history[podcast] = []
        
        # Move successful strategy to front
        if strategy in self.success_history[podcast]:
            self.success_history[podcast].remove(strategy)
        self.success_history[podcast].insert(0, strategy)
        
        # Keep only last 5 successful strategies
        self.success_history[podcast] = self.success_history[podcast][:5]
        
        self._save_success_history()
        logger.info(f"✅ Recorded success: {podcast} -> {strategy}")
    
    def _get_strategy_order(self, podcast_name: str, audio_url: str) -> List[str]:
        """Get ordered list of strategies to try"""
        # If it's a YouTube URL, prioritize YouTube strategy
        if "youtube.com" in audio_url or "youtu.be" in audio_url:
            logger.info(f"🎥 Detected YouTube URL - prioritizing YouTube strategy")
            return ["youtube", "browser"]  # YouTube first, browser as fallback
        
        # Start with successful strategies from history
        historical_strategies = self.success_history.get(podcast_name, [])
        
        # Get default routing rules
        default_strategies = self.ROUTING_RULES.get(podcast_name, self.ROUTING_RULES["default"])
        
        # Combine: historical first, then defaults (avoiding duplicates)
        strategy_order = list(historical_strategies)
        for strategy in default_strategies:
            if strategy not in strategy_order:
                strategy_order.append(strategy)
        
        # Skip direct download for known problematic URLs
        if ("substack.com" in audio_url or 
            podcast_name in ["American Optimist", "Dwarkesh Podcast"]):
            strategy_order = [s for s in strategy_order if s != "direct"]
            logger.info(f"⚡ Skipping direct download for {podcast_name} (Cloudflare protected)")
        
        return strategy_order
    
    async def download_with_fallback(self, episode_info: Dict, output_path: Path) -> bool:
        """Try multiple strategies until one succeeds"""
        
        podcast_name = episode_info.get('podcast', 'Unknown')
        episode_title = episode_info.get('title', 'Unknown')
        audio_url = episode_info.get('audio_url', '')
        
        logger.info(f"\n🎯 Smart routing for: {podcast_name} - {episode_title}")
        logger.info(f"Original URL: {audio_url[:80]}...")
        
        # Get strategy order
        strategy_order = self._get_strategy_order(podcast_name, audio_url)
        logger.info(f"📋 Strategy order: {' → '.join(strategy_order)}")
        
        # Try each strategy
        for i, strategy_name in enumerate(strategy_order):
            if strategy_name not in self.strategies:
                logger.warning(f"⚠️  Strategy '{strategy_name}' not available")
                continue
            
            strategy = self.strategies[strategy_name]
            
            # Check if strategy can handle this
            if not strategy.can_handle(audio_url, podcast_name):
                logger.debug(f"⏭️  {strategy_name} cannot handle this URL/podcast")
                continue
            
            logger.info(f"\n📡 Attempt {i+1}/{len(strategy_order)}: {strategy_name}")
            
            try:
                success, error = await strategy.download(audio_url, output_path, episode_info)
                
                if success:
                    logger.info(f"✅ SUCCESS with {strategy_name}!")
                    self.record_success(podcast_name, strategy_name)
                    return True
                else:
                    logger.warning(f"❌ {strategy_name} failed: {error}")
                    
                    # Small delay between attempts
                    if i < len(strategy_order) - 1:
                        await asyncio.sleep(1)
                        
            except Exception as e:
                logger.error(f"❌ {strategy_name} crashed: {e}")
                continue
        
        # All strategies failed
        logger.error(f"\n💀 All {len(strategy_order)} strategies failed for {podcast_name}")
        logger.info("💡 Consider:")
        logger.info("   1. Adding YouTube URLs to youtube_strategy.py")
        logger.info("   2. Installing Playwright: pip install playwright && playwright install chromium")
        logger.info("   3. Logging into YouTube in Firefox/Chrome")
        
        return False
    
    def get_statistics(self) -> Dict:
        """Get download strategy statistics"""
        stats = {
            'total_podcasts_tracked': len(self.success_history),
            'strategies_by_success': {},
            'podcast_success_rates': {}
        }
        
        # Count strategy usage
        all_strategies = []
        for podcast_strategies in self.success_history.values():
            all_strategies.extend(podcast_strategies)
        
        for strategy in all_strategies:
            stats['strategies_by_success'][strategy] = stats['strategies_by_success'].get(strategy, 0) + 1
        
        return stats