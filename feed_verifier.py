# feed_verifier.py - RSS Feed Verification Tool for Renaissance Weekly
import feedparser
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
from pathlib import Path
import time
from urllib.parse import urlparse

class FeedVerifier:
    """Verify and diagnose RSS feed issues"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Renaissance Weekly Feed Verifier/2.0'
        })
        self.results = {}
        
    def verify_all_feeds(self, podcast_configs: List[Dict], days_back: int = 7):
        """Verify all configured podcast feeds"""
        print("🔍 RSS FEED VERIFICATION REPORT")
        print("=" * 80)
        print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Looking for episodes from the last {days_back} days")
        print("=" * 80)
        
        total_podcasts = len(podcast_configs)
        working_podcasts = 0
        total_feeds_tested = 0
        working_feeds = 0
        
        # Test each podcast
        for config in podcast_configs:
            podcast_name = config["name"]
            print(f"\n📻 {podcast_name}")
            print("-" * 40)
            
            podcast_working = False
            feed_results = []
            
            # Test RSS feeds if available
            if "rss_feeds" in config:
                for url in config["rss_feeds"]:
                    total_feeds_tested += 1
                    result = self.verify_feed(url, podcast_name, days_back)
                    feed_results.append(result)
                    
                    if result["status"] == "working":
                        working_feeds += 1
                        podcast_working = True
            
            # Test Apple Podcasts if available
            if "apple_id" in config and not podcast_working:
                print("\n  🍎 Checking Apple Podcasts fallback...")
                apple_result = self.verify_apple_podcasts(config["apple_id"], podcast_name, days_back)
                if apple_result["status"] == "working":
                    podcast_working = True
                    feed_results.append(apple_result)
            
            if podcast_working:
                working_podcasts += 1
                print(f"\n  ✅ {podcast_name}: At least one source is working")
            else:
                print(f"\n  ❌ {podcast_name}: No working sources found!")
            
            self.results[podcast_name] = {
                "working": podcast_working,
                "feeds": feed_results,
                "has_transcripts": config.get("has_transcripts", False)
            }
        
        # Summary report
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"Total podcasts tested: {total_podcasts}")
        print(f"Working podcasts: {working_podcasts}/{total_podcasts} ({working_podcasts/total_podcasts*100:.1f}%)")
        print(f"Total RSS feeds tested: {total_feeds_tested}")
        print(f"Working RSS feeds: {working_feeds}/{total_feeds_tested} ({working_feeds/total_feeds_tested*100:.1f}% if total_feeds_tested > 0 else 0)")
        
        # Problem podcasts
        problem_podcasts = [name for name, data in self.results.items() if not data["working"]]
        if problem_podcasts:
            print(f"\n⚠️  PROBLEM PODCASTS ({len(problem_podcasts)}):")
            for podcast in problem_podcasts:
                print(f"  - {podcast}")
        
        # Save results
        self.save_results()
        
        # Recommendations
        self.print_recommendations()
        
    def verify_feed(self, url: str, podcast_name: str, days_back: int) -> Dict:
        """Verify a single RSS feed"""
        print(f"\n  🔗 Testing: {url}")
        result = {
            "url": url,
            "status": "unknown",
            "error": None,
            "episodes_found": 0,
            "recent_episodes": 0,
            "latest_episode": None,
            "response_time": None,
            "feed_type": None
        }
        
        start_time = time.time()
        
        try:
            # First try HEAD request
            head_response = self.session.head(url, timeout=10, allow_redirects=True)
            if head_response.status_code != 200:
                result["status"] = "http_error"
                result["error"] = f"HTTP {head_response.status_code}"
                print(f"    ❌ HTTP Error: {head_response.status_code}")
                return result
            
            # Parse feed
            feed = feedparser.parse(url, agent='Renaissance Weekly/2.0')
            result["response_time"] = time.time() - start_time
            
            # Check if feed is valid
            if feed.bozo:
                result["status"] = "parse_error"
                result["error"] = str(feed.bozo_exception) if hasattr(feed, 'bozo_exception') else "Unknown parse error"
                print(f"    ❌ Parse Error: {result['error']}")
                return result
            
            # Check for entries
            if not feed.entries:
                result["status"] = "no_entries"
                result["error"] = "Feed has no entries"
                print(f"    ❌ No entries found")
                return result
            
            # Analyze entries
            result["episodes_found"] = len(feed.entries)
            result["feed_type"] = feed.version if hasattr(feed, 'version') else "unknown"
            
            cutoff = datetime.now() - timedelta(days=days_back)
            recent_episodes = []
            
            for entry in feed.entries[:10]:  # Check first 10
                pub_date = self._parse_date(entry)
                if pub_date:
                    if pub_date > cutoff:
                        recent_episodes.append({
                            "title": entry.get('title', 'Unknown'),
                            "date": pub_date.strftime('%Y-%m-%d'),
                            "has_audio": self._has_audio(entry)
                        })
                    
                    if not result["latest_episode"] or pub_date > result["latest_episode"]["date"]:
                        result["latest_episode"] = {
                            "title": entry.get('title', 'Unknown'),
                            "date": pub_date,
                            "date_str": pub_date.strftime('%Y-%m-%d')
                        }
            
            result["recent_episodes"] = len(recent_episodes)
            result["status"] = "working"
            
            # Print results
            print(f"    ✅ Working! Found {result['episodes_found']} episodes")
            print(f"    📅 Latest: {result['latest_episode']['date_str']} - {result['latest_episode']['title'][:50]}...")
            print(f"    🆕 Recent episodes (last {days_back} days): {result['recent_episodes']}")
            print(f"    ⏱️  Response time: {result['response_time']:.2f}s")
            
            # Warnings
            if result["recent_episodes"] == 0:
                print(f"    ⚠️  No recent episodes - podcast might be on hiatus")
            
            # Check audio availability
            if recent_episodes:
                no_audio = [ep for ep in recent_episodes if not ep["has_audio"]]
                if no_audio:
                    print(f"    ⚠️  {len(no_audio)} recent episodes missing audio URLs")
            
        except requests.exceptions.Timeout:
            result["status"] = "timeout"
            result["error"] = "Request timed out"
            print(f"    ❌ Timeout")
        except requests.exceptions.ConnectionError:
            result["status"] = "connection_error"
            result["error"] = "Connection failed"
            print(f"    ❌ Connection error")
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            print(f"    ❌ Error: {e}")
        
        return result
    
    def verify_apple_podcasts(self, apple_id: str, podcast_name: str, days_back: int) -> Dict:
        """Verify Apple Podcasts as fallback"""
        result = {
            "url": f"apple_podcasts:{apple_id}",
            "status": "unknown",
            "error": None,
            "episodes_found": 0,
            "recent_episodes": 0,
            "feed_url": None
        }
        
        try:
            lookup_url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcast"
            response = self.session.get(lookup_url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("results"):
                    podcast_info = data["results"][0]
                    feed_url = podcast_info.get("feedUrl")
                    
                    if feed_url:
                        result["feed_url"] = feed_url
                        print(f"    Found RSS feed: {feed_url}")
                        
                        # Test the feed
                        feed_result = self.verify_feed(feed_url, podcast_name, days_back)
                        result.update(feed_result)
                        result["url"] = f"apple_podcasts:{apple_id}"
                    else:
                        result["status"] = "no_feed"
                        result["error"] = "No RSS feed found in Apple Podcasts"
                else:
                    result["status"] = "not_found"
                    result["error"] = "Podcast not found in Apple Podcasts"
            else:
                result["status"] = "api_error"
                result["error"] = f"Apple API returned {response.status_code}"
                
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        
        return result
    
    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse date from feed entry"""
        # Try parsed date fields
        for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    return datetime(*getattr(entry, field)[:6])
                except:
                    continue
        
        # Try string dates
        for field in ['published', 'updated', 'pubDate']:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    from dateutil import parser
                    date = parser.parse(getattr(entry, field))
                    if date.tzinfo:
                        date = date.replace(tzinfo=None)
                    return date
                except:
                    continue
        
        return None
    
    def _has_audio(self, entry) -> bool:
        """Check if entry has audio URL"""
        # Check enclosures
        if hasattr(entry, 'enclosures'):
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('audio/'):
                    return True
                elif enclosure.get('href', '').lower().endswith(('.mp3', '.m4a', '.mp4')):
                    return True
        
        # Check links
        if hasattr(entry, 'links'):
            for link in entry.links:
                if link.get('type', '').startswith('audio/'):
                    return True
                elif link.get('rel') == 'enclosure':
                    return True
        
        return False
    
    def save_results(self):
        """Save verification results to file"""
        output_file = Path("feed_verification_results.json")
        
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "results": self.results,
            "summary": {
                "total_podcasts": len(self.results),
                "working_podcasts": len([r for r in self.results.values() if r["working"]]),
                "problem_podcasts": [name for name, data in self.results.items() if not data["working"]]
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, default=str)
        
        print(f"\n💾 Results saved to: {output_file}")
    
    def print_recommendations(self):
        """Print recommendations based on results"""
        print("\n" + "=" * 80)
        print("💡 RECOMMENDATIONS")
        print("=" * 80)
        
        recommendations = []
        
        # Check for podcasts with no working feeds
        for name, data in self.results.items():
            if not data["working"]:
                recommendations.append(f"🔴 {name}: All feeds are failing. Consider:")
                recommendations.append(f"   - Finding alternative RSS URLs")
                recommendations.append(f"   - Implementing web scraping for this podcast")
                recommendations.append(f"   - Checking if the podcast has moved platforms")
        
        # Check for slow feeds
        slow_feeds = []
        for name, data in self.results.items():
            for feed in data["feeds"]:
                if feed.get("response_time", 0) > 5:
                    slow_feeds.append((name, feed["url"], feed["response_time"]))
        
        if slow_feeds:
            recommendations.append("\n🐌 Slow feeds detected:")
            for name, url, time in slow_feeds:
                recommendations.append(f"   - {name}: {url} ({time:.1f}s)")
            recommendations.append("   Consider moving these to lower priority")
        
        # Check for podcasts without recent episodes
        inactive_podcasts = []
        for name, data in self.results.items():
            if data["working"]:
                has_recent = any(feed.get("recent_episodes", 0) > 0 for feed in data["feeds"])
                if not has_recent:
                    inactive_podcasts.append(name)
        
        if inactive_podcasts:
            recommendations.append("\n⏸️  Possibly inactive podcasts:")
            for name in inactive_podcasts:
                recommendations.append(f"   - {name}")
        
        # Success stories
        perfect_podcasts = []
        for name, data in self.results.items():
            if data["working"] and all(feed["status"] == "working" for feed in data["feeds"] if "rss_feeds" in feed):
                perfect_podcasts.append(name)
        
        if perfect_podcasts:
            recommendations.append(f"\n✨ {len(perfect_podcasts)} podcasts with all feeds working perfectly!")
        
        if recommendations:
            for rec in recommendations:
                print(rec)
        else:
            print("✅ All systems operational!")
        
        # Additional suggestions
        print("\n📋 Additional suggestions:")
        print("1. Run this verification weekly to catch feed issues early")
        print("2. Consider implementing PodcastIndex.org as a universal fallback")
        print("3. Set up monitoring alerts for critical podcast feeds")
        print("4. Keep a backup of working feed URLs in your database")


def main():
    """Run feed verification independently"""
    print("🚀 Renaissance Weekly Feed Verifier")
    print("This tool helps diagnose RSS feed issues\n")
    
    # Import podcast configs from main.py
    try:
        from main import PODCAST_CONFIGS
        
        verifier = FeedVerifier()
        
        # Get days_back from command line
        import sys
        days_back = 7
        if len(sys.argv) > 1 and sys.argv[1].isdigit():
            days_back = int(sys.argv[1])
        
        verifier.verify_all_feeds(PODCAST_CONFIGS, days_back)
        
    except ImportError:
        print("❌ Could not import PODCAST_CONFIGS from main.py")
        print("Make sure main.py is in the same directory")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()