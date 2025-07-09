#!/usr/bin/env python3
"""
Test script specifically for the 4 problematic podcasts with enhanced debugging
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.app import RenaissanceWeekly
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)

# The 4 problematic podcasts
PROBLEM_PODCASTS = ["All-In", "American Optimist", "Dwarkesh Podcast", "The Drive"]

async def test_problem_podcasts():
    """Test only the 4 problematic podcasts"""
    logger.info("Testing 4 problematic podcasts with enhanced strategies")
    logger.info("="*60)
    
    # Create app instance
    app = RenaissanceWeekly()
    
    # Filter podcast configs to only include the 4 problematic ones
    problem_configs = [
        config for config in app.podcast_configs 
        if config['name'] in PROBLEM_PODCASTS
    ]
    
    logger.info(f"Found {len(problem_configs)} problematic podcast configs")
    
    # Show retry strategies
    for config in problem_configs:
        logger.info(f"\n{config['name']}:")
        retry_strategy = config.get('retry_strategy', {})
        if retry_strategy:
            logger.info(f"  Primary: {retry_strategy.get('primary', 'None')}")
            logger.info(f"  Fallback: {retry_strategy.get('fallback', 'None')}")
            logger.info(f"  Skip RSS: {retry_strategy.get('skip_rss', False)}")
            logger.info(f"  Force Apple: {retry_strategy.get('force_apple', False)}")
        else:
            logger.info("  No retry strategy configured")
    
    # Process only these podcasts
    try:
        logger.info(f"\n{'='*60}")
        logger.info("Starting focused processing...")
        
        # Run with limited concurrency to avoid memory issues
        app.io_concurrency = 2  # Limit concurrency
        
        await app.run(
            days_back=7,
            mode="verify",  # Just verify, don't send email
            podcast_filter=PROBLEM_PODCASTS  # Only process these podcasts
        )
        
    except Exception as e:
        logger.error(f"Error during processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_problem_podcasts())