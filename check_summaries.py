#!/usr/bin/env python3
"""
Export all summaries to readable text files for review.
"""

import sqlite3
from pathlib import Path
from datetime import datetime

def main():
    # Connect to database
    db_path = Path("/workspaces/gistcapture-ai/renaissance_weekly.db")
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create output directory
    output_dir = Path("summary_exports")
    output_dir.mkdir(exist_ok=True)
    
    # Get all episodes with summaries
    cursor.execute("""
        SELECT 
            podcast, 
            title, 
            published,
            summary,
            summary_test,
            CASE 
                WHEN summary IS NOT NULL AND summary_test IS NOT NULL THEN 'Both'
                WHEN summary IS NOT NULL THEN 'Full'
                WHEN summary_test IS NOT NULL THEN 'Test'
            END as available_modes,
            LENGTH(COALESCE(summary, summary_test)) as length
        FROM episodes 
        WHERE summary IS NOT NULL OR summary_test IS NOT NULL
        ORDER BY published DESC
    """)
    
    episodes = cursor.fetchall()
    print(f"\nFound {len(episodes)} episodes with summaries\n")
    
    # Create master file with all summaries
    master_file = output_dir / "ALL_SUMMARIES.txt"
    with open(master_file, 'w', encoding='utf-8') as f:
        f.write("RENAISSANCE WEEKLY - ALL SUMMARIES\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total episodes with summaries: {len(episodes)}\n")
        f.write("=" * 80 + "\n\n")
        
        for i, (podcast, title, published, summary_full, summary_test, modes, length) in enumerate(episodes, 1):
            f.write(f"\n{'='*80}\n")
            f.write(f"Episode {i}: {title}\n")
            f.write(f"Podcast: {podcast}\n")
            f.write(f"Published: {published[:10]}\n")
            f.write(f"Available: {modes} mode summaries\n")
            f.write(f"{'='*80}\n\n")
            
            if summary_full:
                f.write("FULL MODE SUMMARY:\n")
                f.write("-" * 40 + "\n")
                f.write(summary_full)
                f.write("\n\n")
            
            if summary_test:
                f.write("TEST MODE SUMMARY (15 min):\n")
                f.write("-" * 40 + "\n")
                f.write(summary_test)
                f.write("\n\n")
            
            # Also create individual files by podcast
            podcast_dir = output_dir / podcast.replace('/', '_')
            podcast_dir.mkdir(exist_ok=True)
            
            safe_filename = f"{published[:10]}_{title[:50].replace('/', '_')}.txt"
            episode_file = podcast_dir / safe_filename
            
            with open(episode_file, 'w', encoding='utf-8') as ef:
                ef.write(f"{title}\n")
                ef.write("=" * len(title) + "\n\n")
                ef.write(f"Podcast: {podcast}\n")
                ef.write(f"Published: {published}\n\n")
                
                # Write whichever summary is available (prefer full)
                if summary_full:
                    ef.write("Summary (Full Episode):\n")
                    ef.write("-" * 20 + "\n\n")
                    ef.write(summary_full)
                elif summary_test:
                    ef.write("Summary (Test Mode - 15 min only):\n")
                    ef.write("-" * 20 + "\n\n")
                    ef.write(summary_test)
    
    # Create index file
    index_file = output_dir / "00_INDEX.txt"
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write("SUMMARY EXPORT INDEX\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Total episodes with summaries: {len(episodes)}\n\n")
        
        # Group by podcast
        current_podcast = None
        for podcast, title, published, _, _, modes, _ in episodes:
            if podcast != current_podcast:
                f.write(f"\n{podcast}:\n")
                current_podcast = podcast
            f.write(f"  - {published[:10]} | {title[:60]}... ({modes})\n")
    
    conn.close()
    
    print(f"\n✅ Summaries exported to: {output_dir}/")
    print(f"\nFiles created:")
    print(f"  - ALL_SUMMARIES.txt - All summaries in one file")
    print(f"  - 00_INDEX.txt - Quick index of all episodes")
    print(f"  - Individual folders for each podcast with episode files")
    print(f"\n💡 Tip: Open ALL_SUMMARIES.txt to read all summaries in order")


if __name__ == "__main__":
    main()