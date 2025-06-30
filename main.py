#!/usr/bin/env python3
"""
Renaissance Weekly - Podcast Intelligence System
Main entry point - PRODUCTION READY with enhanced error handling
"""

import asyncio
import os
import sys
import signal
from pathlib import Path
import logging
from datetime import datetime

# Ensure the package can be imported when run directly
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.utils.logging import setup_logging, get_logger

# Set up logging first
logger = setup_logging()

# Global app instance for cleanup
app_instance = None


def signal_handler(signum, frame):
    """Handle interrupt signals gracefully"""
    logger.info("\n⚠️  Interrupt received, cleaning up...")
    if app_instance:
        # Use asyncio.run to properly cleanup
        try:
            asyncio.run(app_instance.cleanup())
        except:
            pass
    sys.exit(0)


def print_help():
    """Print help information"""
    print("Renaissance Weekly - Podcast Intelligence System\n")
    print("Usage:")
    print("  python main.py [days]                    # Normal mode (default: 7 days)")
    print("  python main.py verify [days]             # Run verification report")
    print("  python main.py check \"Podcast Name\" [days] # Check single podcast")
    print("  python main.py reload-prompts            # Reload prompts from disk")
    print("  python main.py test                      # Run system diagnostics")
    print("  python main.py -h                        # Show this help\n")
    print("Environment Variables:")
    print("  VERIFY_APPLE_PODCASTS=true/false   # Enable Apple verification (default: true)")
    print("  FETCH_MISSING_EPISODES=true/false  # Auto-fetch missing episodes (default: true)")
    print("  TESTING_MODE=true/false            # Limit transcription to 20 min (default: true)")
    print("  OPENAI_MODEL=gpt-4o                # ChatGPT model to use (default: gpt-4o)")
    print("  OPENAI_TEMPERATURE=0.3             # Model temperature (default: 0.3)")
    print("  OPENAI_MAX_TOKENS=4000             # Max tokens for response (default: 4000)")
    print("  EMAIL_TO=your@email.com            # Recipient email address")
    print("\nExamples:")
    print("  python main.py                     # Process last 7 days")
    print("  python main.py 14                  # Process last 14 days")
    print("  python main.py verify              # Run verification report")
    print("  python main.py check \"Tim Ferriss\" # Debug Tim Ferriss podcast")
    print("  python main.py test                # Run system diagnostics")


def run_system_diagnostics():
    """Run system diagnostics to check configuration"""
    logger.info("🔧 Running system diagnostics...")
    
    # Check environment variables
    logger.info("\n📋 Environment Variables:")
    required_vars = ["OPENAI_API_KEY", "SENDGRID_API_KEY"]
    optional_vars = ["EMAIL_TO", "PODCASTINDEX_API_KEY", "PODCASTINDEX_API_SECRET", 
                     "TADDY_API_KEY", "TESTING_MODE"]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            logger.info(f"  ✅ {var}: Set ({len(value)} chars)")
        else:
            logger.error(f"  ❌ {var}: NOT SET")
    
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            logger.info(f"  ✅ {var}: {value[:30]}...")
        else:
            logger.info(f"  ⚠️  {var}: Not set (optional)")
    
    # Check directories
    logger.info("\n📁 Directories:")
    from renaissance_weekly.config import TRANSCRIPT_DIR, AUDIO_DIR, SUMMARY_DIR, CACHE_DIR, TEMP_DIR
    
    for name, path in [
        ("Transcripts", TRANSCRIPT_DIR),
        ("Audio", AUDIO_DIR),
        ("Summaries", SUMMARY_DIR),
        ("Cache", CACHE_DIR),
        ("Temp", TEMP_DIR)
    ]:
        if path.exists():
            logger.info(f"  ✅ {name}: {path}")
        else:
            logger.warning(f"  ⚠️  {name}: {path} (will be created)")
    
    # Check podcast configuration
    logger.info("\n📻 Podcast Configuration:")
    try:
        from renaissance_weekly.config import PODCAST_CONFIGS
        logger.info(f"  Total podcasts configured: {len(PODCAST_CONFIGS)}")
        
        # Count by identifier type
        apple_count = sum(1 for p in PODCAST_CONFIGS if p.get("apple_id"))
        rss_count = sum(1 for p in PODCAST_CONFIGS if p.get("rss_feeds"))
        search_count = sum(1 for p in PODCAST_CONFIGS if p.get("search_term"))
        
        logger.info(f"  With Apple ID: {apple_count}")
        logger.info(f"  With RSS feeds: {rss_count}")
        logger.info(f"  With search terms: {search_count}")
        
        # Show first few podcasts
        logger.info("\n  First 5 podcasts:")
        for i, podcast in enumerate(PODCAST_CONFIGS[:5]):
            logger.info(f"    {i+1}. {podcast['name']}")
            
    except Exception as e:
        logger.error(f"  ❌ Error loading podcast config: {e}")
    
    # Check database
    logger.info("\n💾 Database:")
    try:
        from renaissance_weekly.database import PodcastDatabase
        db = PodcastDatabase()
        recent = db.get_recent_episodes(days_back=7)
        logger.info(f"  ✅ Database accessible")
        logger.info(f"  Episodes in last 7 days: {len(recent)}")
    except Exception as e:
        logger.error(f"  ❌ Database error: {e}")
    
    # Check OpenAI connection
    logger.info("\n🤖 OpenAI API:")
    try:
        from renaissance_weekly.utils.clients import openai_client
        # Test with a simple completion
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=10
        )
        logger.info("  ✅ OpenAI API connection successful")
    except Exception as e:
        logger.error(f"  ❌ OpenAI API error: {e}")
    
    # Check SendGrid
    logger.info("\n📧 SendGrid API:")
    try:
        from renaissance_weekly.utils.clients import sendgrid_client
        # Just check if client initializes
        logger.info("  ✅ SendGrid client initialized")
        logger.info(f"  From: {os.getenv('EMAIL_FROM', 'insights@gistcapture.ai')}")
        logger.info(f"  To: {os.getenv('EMAIL_TO', 'caddington05@gmail.com')}")
    except Exception as e:
        logger.error(f"  ❌ SendGrid error: {e}")
    
    # Check system tools
    logger.info("\n🛠️  System Tools:")
    import shutil
    
    for tool in ["ffmpeg", "ffprobe", "curl", "wget"]:
        path = shutil.which(tool)
        if path:
            logger.info(f"  ✅ {tool}: {path}")
        else:
            logger.warning(f"  ⚠️  {tool}: Not found (optional but recommended)")
    
    logger.info("\n✅ Diagnostics complete!")


def parse_arguments():
    """Parse command line arguments"""
    days_back = 7
    mode = "normal"
    podcast_name = None
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "verify":
            mode = "verify"
            if len(sys.argv) > 2 and sys.argv[2].isdigit():
                days_back = int(sys.argv[2])
        elif sys.argv[1] == "check":
            mode = "check"
            if len(sys.argv) > 2:
                podcast_name = sys.argv[2]
                if len(sys.argv) > 3 and sys.argv[3].isdigit():
                    days_back = int(sys.argv[3])
            else:
                print("Error: Please specify a podcast name")
                print("Usage: python main.py check \"Podcast Name\" [days]")
                sys.exit(1)
        elif sys.argv[1] == "reload-prompts":
            mode = "reload-prompts"
        elif sys.argv[1] == "test":
            mode = "test"
        elif sys.argv[1].isdigit():
            days_back = int(sys.argv[1])
        elif sys.argv[1] in ["-h", "--help"]:
            print_help()
            sys.exit(0)
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print_help()
            sys.exit(1)
    
    return mode, days_back, podcast_name


async def main():
    """Main entry point with production safeguards"""
    global app_instance
    
    mode, days_back, podcast_name = parse_arguments()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run diagnostics if requested
    if mode == "test":
        run_system_diagnostics()
        return
    
    try:
        logger.info("🎙️  Renaissance Weekly - Podcast Intelligence System")
        logger.info(f"📅 Mode: {mode}, Days back: {days_back}")
        logger.info(f"🕐 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Initialize app with error handling
        try:
            app_instance = RenaissanceWeekly()
        except Exception as e:
            logger.error(f"❌ Failed to initialize system: {e}")
            logger.error("Run 'python main.py test' to diagnose issues")
            sys.exit(1)
        
        # Execute based on mode
        if mode == "verify":
            await app_instance.run_verification_report(days_back)
        elif mode == "check":
            await app_instance.check_single_podcast(podcast_name, days_back)
        elif mode == "reload-prompts":
            app_instance.summarizer.reload_prompts()
            logger.info("✅ Prompts reloaded successfully")
        else:
            await app_instance.run(days_back)
        
        logger.info(f"✅ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Send alert email if in production
        if not os.getenv("TESTING_MODE", "true").lower() == "true":
            try:
                from renaissance_weekly.utils.alerts import send_error_alert
                send_error_alert(str(e), traceback.format_exc())
            except:
                pass
        
        sys.exit(1)
    finally:
        # Ensure cleanup happens
        if app_instance:
            try:
                await app_instance.cleanup()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")


def main_wrapper():
    """Wrapper to handle event loop properly across platforms"""
    # Set up async event loop with better compatibility
    if sys.platform == 'win32':
        # Windows specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Configure asyncio for production
    if not os.getenv("TESTING_MODE", "true").lower() == "true":
        # In production, enable debug mode for better error tracking
        import warnings
        warnings.filterwarnings("default", category=DeprecationWarning)
        os.environ['PYTHONASYNCIODEBUG'] = '1'
    
    try:
        # Create new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run main
        loop.run_until_complete(main())
        
        # Clean up pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # Wait for task cancellation
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        
        # Close loop
        loop.close()
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error in event loop: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main_wrapper()