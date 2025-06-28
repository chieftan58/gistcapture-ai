#!/usr/bin/env python3
"""
Renaissance Weekly - Podcast Intelligence System
Main entry point
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure the package can be imported when run directly
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.utils.logging import setup_logging

logger = setup_logging()


def print_help():
    """Print help information"""
    print("Renaissance Weekly - Podcast Intelligence System\n")
    print("Usage:")
    print("  python main.py [days]                    # Normal mode (default: 7 days)")
    print("  python main.py verify [days]             # Run verification report")
    print("  python main.py check \"Podcast Name\" [days] # Check single podcast")
    print("  python main.py -h                        # Show this help\n")
    print("Environment Variables:")
    print("  VERIFY_APPLE_PODCASTS=true/false   # Enable Apple verification (default: true)")
    print("  FETCH_MISSING_EPISODES=true/false  # Auto-fetch missing episodes (default: true)")
    print("  TESTING_MODE=true/false            # Limit transcription to 20 min (default: true)")
    print("\nExamples:")
    print("  python main.py                     # Process last 7 days")
    print("  python main.py 14                  # Process last 14 days")
    print("  python main.py verify              # Run verification report")
    print("  python main.py check \"Tim Ferriss\" # Debug Tim Ferriss podcast")


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
        elif sys.argv[1].isdigit():
            days_back = int(sys.argv[1])
        elif sys.argv[1] in ["-h", "--help"]:
            print_help()
            sys.exit(0)
    
    return mode, days_back, podcast_name


async def main():
    """Main entry point"""
    mode, days_back, podcast_name = parse_arguments()
    
    try:
        app = RenaissanceWeekly()
        
        if mode == "verify":
            await app.run_verification_report(days_back)
        elif mode == "check":
            await app.check_single_podcast(podcast_name, days_back)
        else:
            await app.run(days_back)
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    # Set up async event loop
    if os.name == 'nt':  # Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(0)