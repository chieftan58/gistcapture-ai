#!/usr/bin/env python3
"""
Analyze logs to understand cache behavior in production.
"""

import re
from pathlib import Path
from collections import defaultdict

def analyze_cache_behavior():
    """Analyze log file for cache hit/miss patterns"""
    
    log_file = Path("renaissance_weekly.log")
    if not log_file.exists():
        print("No log file found")
        return
    
    # Patterns to look for
    patterns = {
        'checking_cache': re.compile(r'Checking database cache\.\.\.'),
        'cache_found': re.compile(r'Database result: Found'),
        'cache_not_found': re.compile(r'Database result: Not found'),
        'cached_transcript': re.compile(r'CACHED TRANSCRIPT.*?: (.*?) - (.*?)\.\.\.'),
        'transcribing_audio': re.compile(r'No valid transcript found - transcribing from audio'),
        'assemblyai_start': re.compile(r'Using AssemblyAI for transcription'),
        'mode_info': re.compile(r'Transcript mode: (\w+)'),
        'saving_episode': re.compile(r'Saving episode: (.*?) - (.*?)\.\.\.'),
        'episode_processing': re.compile(r'Processing episode: (.*?) - (.*?)$'),
    }
    
    # Stats
    stats = defaultdict(int)
    recent_episodes = []
    current_episode = None
    current_mode = None
    
    # Read last 10000 lines
    with open(log_file, 'r') as f:
        lines = f.readlines()[-10000:]
    
    for line in lines:
        # Track current episode being processed
        match = patterns['episode_processing'].search(line)
        if match:
            current_episode = f"{match.group(1)} - {match.group(2)}"
            
        # Track mode
        match = patterns['mode_info'].search(line)
        if match:
            current_mode = match.group(1)
            
        # Count cache checks
        if patterns['checking_cache'].search(line):
            stats['cache_checks'] += 1
            
        # Count cache hits
        if patterns['cache_found'].search(line):
            stats['cache_hits'] += 1
            if current_episode:
                recent_episodes.append({
                    'episode': current_episode,
                    'mode': current_mode,
                    'result': 'HIT'
                })
                
        # Count cache misses
        if patterns['cache_not_found'].search(line):
            stats['cache_misses'] += 1
            if current_episode:
                recent_episodes.append({
                    'episode': current_episode,
                    'mode': current_mode,
                    'result': 'MISS'
                })
                
        # Count actual transcriptions
        if patterns['assemblyai_start'].search(line):
            stats['assemblyai_transcriptions'] += 1
            
        # Count saves
        if patterns['saving_episode'].search(line):
            stats['episodes_saved'] += 1
    
    # Print analysis
    print("TRANSCRIPT CACHE ANALYSIS")
    print("="*60)
    print(f"Total cache checks: {stats['cache_checks']}")
    print(f"Cache hits: {stats['cache_hits']}")
    print(f"Cache misses: {stats['cache_misses']}")
    if stats['cache_checks'] > 0:
        hit_rate = (stats['cache_hits'] / stats['cache_checks']) * 100
        print(f"Cache hit rate: {hit_rate:.1f}%")
    print(f"\nAssemblyAI transcriptions: {stats['assemblyai_transcriptions']}")
    print(f"Episodes saved: {stats['episodes_saved']}")
    
    # Show recent cache activity
    print("\nRECENT CACHE ACTIVITY (last 20):")
    print("-"*60)
    for entry in recent_episodes[-20:]:
        status = "✅" if entry['result'] == 'HIT' else "❌"
        print(f"{status} {entry['result']:4} | Mode: {entry['mode'] or 'unknown':4} | {entry['episode'][:50]}")
    
    # Look for specific patterns that indicate problems
    print("\nPOTENTIAL ISSUES:")
    print("-"*60)
    
    # Check for episodes that were saved but then had cache misses
    saved_episodes = set()
    for line in lines:
        match = patterns['saving_episode'].search(line)
        if match:
            saved_episodes.add(f"{match.group(1)} - {match.group(2)}")
    
    missed_after_save = []
    for entry in recent_episodes:
        if entry['result'] == 'MISS' and any(entry['episode'].startswith(saved) for saved in saved_episodes):
            missed_after_save.append(entry['episode'])
    
    if missed_after_save:
        print(f"❌ Episodes with cache misses after being saved: {len(missed_after_save)}")
        for ep in missed_after_save[-5:]:
            print(f"   - {ep}")
    else:
        print("✅ No episodes with cache misses after being saved")

if __name__ == "__main__":
    analyze_cache_behavior()