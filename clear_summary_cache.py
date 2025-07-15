#!/usr/bin/env python3
"""
Clear old summary cache files to ensure fresh summaries
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from renaissance_weekly.config import SUMMARY_DIR
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)


def clear_old_summaries():
    """Clear old-style summary files that don't include mode in filename"""
    
    if not SUMMARY_DIR.exists():
        logger.info("Summary directory doesn't exist yet")
        return 0
    
    # Pattern for old-style summaries (without mode)
    old_pattern = "*_*_*_summary.md"
    
    # Pattern for new-style summaries (with mode)
    new_test_pattern = "*_*_*_test_summary.md"
    new_full_pattern = "*_*_*_full_summary.md"
    
    deleted_count = 0
    kept_count = 0
    
    logger.info(f"🔍 Scanning {SUMMARY_DIR} for old-style summaries...")
    
    for summary_file in SUMMARY_DIR.glob("*.md"):
        filename = summary_file.name
        
        # Check if it's a new-style file (has mode)
        if filename.endswith("_test_summary.md") or filename.endswith("_full_summary.md"):
            kept_count += 1
            logger.debug(f"  ✅ Keeping mode-aware summary: {filename}")
        else:
            # Old-style file without mode - delete it
            logger.info(f"  🗑️  Deleting old-style summary: {filename}")
            summary_file.unlink()
            deleted_count += 1
    
    logger.info(f"\n📊 Summary:")
    logger.info(f"  - Deleted: {deleted_count} old-style summaries")
    logger.info(f"  - Kept: {kept_count} mode-aware summaries")
    
    if deleted_count > 0:
        logger.info("\n✅ Old summaries cleared! New summaries will be generated on next run.")
        logger.info("💡 Tip: Use 'python main.py [days] --force-fresh' to regenerate all summaries")
    else:
        logger.info("\n✅ No old-style summaries found - cache is already clean!")
    
    return deleted_count


if __name__ == "__main__":
    clear_old_summaries()