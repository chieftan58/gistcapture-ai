#!/usr/bin/env python3
"""
Check transcripts with filtering options - view beginning and end of episodes.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import argparse

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
    if begin_break > chars_per_section * 0.7:
        beginning = beginning[:begin_break + 1]
    
    end_break = ending.find('. ')
    if end_break > 0 and end_break < chars_per_section * 0.3:
        ending = ending[end_break + 2:]
    
    return f"{beginning}\n\n{'='*80}\n[... MIDDLE SECTION OMITTED - Total length: {total_length:,} characters ...]\n{'='*80}\n\n{ending}"


def main():
    parser = argparse.ArgumentParser(description='Check podcast transcripts')
    parser.add_argument('--days', type=int, default=7, help='Check episodes from last N days (default: 7)')
    parser.add_argument('--podcast', type=str, help='Filter by specific podcast name')
    parser.add_argument('--mode', choices=['test', 'full', 'any'], default='any', 
                        help='Filter by transcription mode (default: any)')
    parser.add_argument('--limit', type=int, help='Limit number of episodes to check')
    parser.add_argument('--min-length', type=int, help='Only show transcripts longer than N characters')
    parser.add_argument('--search', type=str, help='Search for keyword in title')
    
    args = parser.parse_args()
    
    # Connect to database
    db_path = Path("/workspaces/gistcapture-ai/renaissance_weekly.db")
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Build query based on filters
    query = """
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
        WHERE (transcript IS NOT NULL OR transcript_test IS NOT NULL)
    """
    
    params = []
    
    # Add date filter
    if args.days:
        cutoff_date = (datetime.now() - timedelta(days=args.days)).isoformat()
        query += " AND published >= ?"
        params.append(cutoff_date)
    
    # Add podcast filter
    if args.podcast:
        query += " AND podcast LIKE ?"
        params.append(f"%{args.podcast}%")
    
    # Add mode filter
    if args.mode == 'test':
        query += " AND transcript_test IS NOT NULL"
    elif args.mode == 'full':
        query += " AND transcript IS NOT NULL"
    
    # Add length filter
    if args.min_length:
        query += " AND LENGTH(COALESCE(transcript, transcript_test)) >= ?"
        params.append(args.min_length)
    
    # Add search filter
    if args.search:
        query += " AND title LIKE ?"
        params.append(f"%{args.search}%")
    
    query += " ORDER BY published DESC"
    
    # Add limit
    if args.limit:
        query += f" LIMIT {args.limit}"
    
    cursor.execute(query, params)
    episodes = cursor.fetchall()
    
    print(f"\nFound {len(episodes)} episodes matching your criteria\n")
    
    if len(episodes) == 0:
        print("No episodes found. Try adjusting your filters.")
        return
    
    # Create output directory
    output_dir = Path("transcript_checks")
    output_dir.mkdir(exist_ok=True)
    
    # Create summary file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_file = output_dir / f"transcript_check_{timestamp}.txt"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("TRANSCRIPT VERIFICATION REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Filters applied:\n")
        if args.days:
            f.write(f"  - Last {args.days} days\n")
        if args.podcast:
            f.write(f"  - Podcast: {args.podcast}\n")
        if args.mode != 'any':
            f.write(f"  - Mode: {args.mode}\n")
        if args.min_length:
            f.write(f"  - Min length: {args.min_length:,} chars\n")
        if args.search:
            f.write(f"  - Search: {args.search}\n")
        f.write(f"\nTotal episodes found: {len(episodes)}\n")
        f.write("=" * 80 + "\n\n")
        
        for i, (podcast, title, published, transcript, mode, length, source) in enumerate(episodes, 1):
            print(f"Processing {i}/{len(episodes)}: {podcast} - {title[:50]}...")
            
            # Estimate minutes
            estimated_minutes = length / 150
            
            f.write(f"\n{'='*80}\n")
            f.write(f"Episode {i}: {title}\n")
            f.write(f"Podcast: {podcast}\n")
            f.write(f"Published: {published[:10]}\n")
            f.write(f"Mode: {mode}\n")
            f.write(f"Source: {source or 'Unknown'}\n")
            f.write(f"Length: {length:,} characters (~{estimated_minutes:.0f} minutes)\n")
            
            if mode == 'Test' and estimated_minutes < 20:
                f.write("⚠️  This appears to be a TEST transcript (partial episode)\n")
            elif estimated_minutes > 40:
                f.write("✅ This appears to be a FULL transcript\n")
            
            f.write("\n" + "-" * 40 + "\n")
            f.write("BEGINNING OF TRANSCRIPT:\n")
            f.write("-" * 40 + "\n\n")
            
            preview = format_transcript_preview(transcript)
            f.write(preview)
            
            f.write("\n" + "="*80 + "\n\n")
    
    conn.close()
    
    print(f"\n✅ Report saved to: {summary_file}")
    print(f"\n💡 Tips:")
    print(f"  - Look at the ending text to verify complete episodes were captured")
    print(f"  - Episodes with ~40+ minutes are likely full transcripts")
    print(f"  - Episodes with <20 minutes are likely test mode (partial)")


if __name__ == "__main__":
    main()