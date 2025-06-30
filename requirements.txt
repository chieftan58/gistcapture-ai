#!/usr/bin/env python3
"""
Renaissance Weekly - Podcast Intelligence System
Main entry point - FIXED with better error handling
"""

import asyncio
import os
import sys
import signal
from pathlib import Path

# Ensure the package can be imported when run directly
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.utils.logging import setup_logging

logger = setup_logging()

# Global app instance for cleanup
app_instance = None


def signal_handler(signum, frame):
    """Handle interrupt signals gracefully"""
    logger.info("\n⚠️  Interrupt received, cleaning up...")
    if app_instance:
        asyncio.create_task(app_instance.cleanup())
    sys.exit(0)


def print_help():
    """Print help information"""
    print("Renaissance Weekly - Podcast Intelligence System\n")
    print("Usage:")
    print("  python main.py [days]                    # Normal mode (default: 7 days)")
    print("  python main.py verify [days]             # Run verification report")
    print("  python main.py check \"Podcast Name\" [days] # Check single podcast")
    print("  python main.py reload-prompts            # Reload prompts from disk")
    print("  python main.py -h                        # Show this help\n")
    print("Environment Variables:")
    print("  VERIFY_APPLE_PODCASTS=true/false   # Enable Apple verification (default: true)")
    print("  FETCH_MISSING_EPISODES=true/false  # Auto-fetch missing episodes (default: true)")
    print("  TESTING_MODE=true/false            # Limit transcription to 10 min (default: true)")
    print("  OPENAI_MODEL=gpt-4o                # ChatGPT model to use (default: gpt-4o)")
    print("  OPENAI_TEMPERATURE=0.3             # Model temperature (default: 0.3)")
    print("  OPENAI_MAX_TOKENS=4000             # Max tokens for response (default: 4000)")
    print("\nExamples:")
    print("  python main.py                     # Process last 7 days")
    print("  python main.py 14                  # Process last 14 days")
    print("  python main.py verify              # Run verification report")
    print("  python main.py check \"Tim Ferriss\" # Debug Tim Ferriss podcast")
    print("  python main.py reload-prompts      # Reload prompts for A/B testing")


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
    """Main entry point"""
    global app_instance
    
    mode, days_back, podcast_name = parse_arguments()
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        logger.info("🎙️  Renaissance Weekly - Podcast Intelligence System")
        logger.info(f"📅 Mode: {mode}, Days back: {days_back}")
        
        app_instance = RenaissanceWeekly()
        
        if mode == "verify":
            await app_instance.run_verification_report(days_back)
        elif mode == "check":
            await app_instance.check_single_podcast(podcast_name, days_back)
        elif mode == "reload-prompts":
            app_instance.summarizer.reload_prompts()
            logger.info("✅ Prompts reloaded successfully")
        else:
            await app_instance.run(days_back)
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        # Cleanup
        if app_instance:
            await app_instance.cleanup()


if __name__ == "__main__":
    # Set up async event loop with better compatibility
    if sys.platform == 'win32':
        # Windows specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        # Run the main function
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error in event loop: {e}")
        sys.exit(1)