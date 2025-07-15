#!/usr/bin/env python3
"""
Check transcripts by viewing the beginning and end of each episode.
This helps verify that complete episodes were captured.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
import textwrap

def format_transcript_preview(transcript, chars_per_section=1500):
    """Show beginning and end of transcript with clear markers"""
    if not transcript:
        return "No transcript available"
    
    total_length = len(transcript)
    
    # If transcript is short, show all of it
    if total_length <= chars_per_section * 2:
        return transcript
    
    # Get beginning and end
    beginning = transcript[:chars_per_section]
    ending = transcript[-chars_per_section:]
    
    # Find good breaking points (end of sentences)
    begin_break = beginning.rfind('. ')
    if begin_break > chars_per_section * 0.7:  # Only use if we're not losing too much
        beginning = beginning[:begin_break + 1]
    
    end_break = ending.find('. ')
    if end_break > 0 and end_break < chars_per_section * 0.3:
        ending = ending[end_break + 2:]
    
    return f"{beginning}\n\n{'='*80}\n[... MIDDLE SECTION OMITTED - Total length: {total_length:,} characters ...]\n{'='*80}\n\n{ending}"


def main():
    # Connect to database
    db_path = Path("/workspaces/gistcapture-ai/renaissance_weekly.db")
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create output directory
    output_dir = Path("transcript_checks")
    output_dir.mkdir(exist_ok=True)
    
    # Get all episodes with transcripts
    cursor.execute("""
        SELECT 
            podcast, 
            title, 
            published,
            COALESCE(transcript, transcript_test) as transcript_content,
            CASE 
                WHEN transcript IS NOT NULL THEN 'Full'
                WHEN transcript_test IS NOT NULL THEN 'Test'
            END as mode,
            LENGTH(COALESCE(transcript, transcript_test)) as length,
            transcript_source
        FROM episodes 
        WHERE transcript IS NOT NULL OR transcript_test IS NOT NULL
        ORDER BY published DESC
    """)
    
    episodes = cursor.fetchall()
    print(f"\nFound {len(episodes)} episodes with transcripts\n")
    
    # Create a summary file
    summary_file = output_dir / "00_TRANSCRIPT_SUMMARY.txt"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("TRANSCRIPT VERIFICATION SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total episodes with transcripts: {len(episodes)}\n\n")
        
        # Statistics
        full_count = sum(1 for ep in episodes if ep[4] == 'Full')
        test_count = sum(1 for ep in episodes if ep[4] == 'Test')
        
        f.write(f"Full mode transcripts: {full_count}\n")
        f.write(f"Test mode transcripts: {test_count}\n")
        f.write("\n" + "=" * 80 + "\n\n")
        
        # Episode list with details
        f.write("EPISODE LIST:\n\n")
        
        for i, (podcast, title, published, transcript, mode, length, source) in enumerate(episodes, 1):
            # Write to summary
            f.write(f"{i}. {podcast} - {title[:60]}...\n")
            f.write(f"   Date: {published[:10]}")
            f.write(f" | Mode: {mode}")
            f.write(f" | Length: {length:,} chars")
            f.write(f" | Source: {source or 'Unknown'}\n")
            
            # Estimate if this is a full transcript based on length
            # Rough estimate: ~150 chars per minute of speech
            estimated_minutes = length / 150
            if mode == 'Test' and estimated_minutes < 20:
                f.write(f"   ⚠️  Likely a TEST transcript (~{estimated_minutes:.0f} min)\n")
            elif estimated_minutes > 40:
                f.write(f"   ✅ Likely a FULL transcript (~{estimated_minutes:.0f} min)\n")
            else:
                f.write(f"   ⚡ Medium length (~{estimated_minutes:.0f} min)\n")
            f.write("\n")
            
            # Create individual file for this episode
            safe_filename = f"{i:03d}_{podcast.replace('/', '_')}_{title[:40].replace('/', '_')}.txt"
            episode_file = output_dir / safe_filename
            
            with open(episode_file, 'w', encoding='utf-8') as ef:
                ef.write(f"TRANSCRIPT CHECK: {title}\n")
                ef.write("=" * 80 + "\n")
                ef.write(f"Podcast: {podcast}\n")
                ef.write(f"Published: {published}\n")
                ef.write(f"Mode: {mode}\n")
                ef.write(f"Source: {source or 'Unknown'}\n")
                ef.write(f"Total Length: {length:,} characters (~{estimated_minutes:.0f} min of speech)\n")
                ef.write("=" * 80 + "\n\n")
                
                ef.write("BEGINNING OF TRANSCRIPT:\n")
                ef.write("-" * 40 + "\n\n")
                
                preview = format_transcript_preview(transcript)
                ef.write(preview)
                
                ef.write("\n\n" + "-" * 40 + "\n")
                ef.write("END OF TRANSCRIPT CHECK\n")
    
    print(f"\n✅ Transcript checks exported to: {output_dir}/")
    print(f"\nFiles created:")
    print(f"  - 00_TRANSCRIPT_SUMMARY.txt - Overview of all transcripts")
    print(f"  - Individual files for each episode showing beginning and end")
    print(f"\n💡 Tip: Look for episodes with 40+ minutes estimated length for full transcripts")
    
    # Also create a quick stats file
    stats_file = output_dir / "00_QUICK_STATS.txt"
    with open(stats_file, 'w', encoding='utf-8') as f:
        f.write("QUICK TRANSCRIPT STATISTICS\n")
        f.write("=" * 50 + "\n\n")
        
        # Group by podcast
        cursor.execute("""
            SELECT 
                podcast,
                COUNT(*) as episode_count,
                AVG(LENGTH(COALESCE(transcript, transcript_test))) as avg_length,
                MAX(LENGTH(COALESCE(transcript, transcript_test))) as max_length,
                MIN(LENGTH(COALESCE(transcript, transcript_test))) as min_length
            FROM episodes 
            WHERE transcript IS NOT NULL OR transcript_test IS NOT NULL
            GROUP BY podcast
            ORDER BY podcast
        """)
        
        for podcast, count, avg_len, max_len, min_len in cursor.fetchall():
            f.write(f"{podcast}:\n")
            f.write(f"  Episodes: {count}\n")
            f.write(f"  Avg length: {avg_len:,.0f} chars (~{avg_len/150:.0f} min)\n")
            f.write(f"  Max length: {max_len:,.0f} chars (~{max_len/150:.0f} min)\n")
            f.write(f"  Min length: {min_len:,.0f} chars (~{min_len/150:.0f} min)\n")
            f.write("\n")
    
    conn.close()
    print(f"\n📊 Check 00_QUICK_STATS.txt for podcast-by-podcast statistics")


if __name__ == "__main__":
    main()