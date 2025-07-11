#!/usr/bin/env python3
"""Analyze download failures to understand patterns"""

import json
from collections import defaultdict, Counter
from pathlib import Path

def analyze_failures():
    failures_file = Path('monitoring_data/failures.json')
    
    with open(failures_file) as f:
        failures = json.load(f)
    
    # Group failures by podcast
    podcast_failures = defaultdict(list)
    for failure in failures:
        podcast = failure.get('podcast', 'Unknown')
        podcast_failures[podcast].append(failure)
    
    # Focus on problematic podcasts
    problematic = ['American Optimist', 'Dwarkesh Podcast', 'The Drive', 'A16Z', 'BG2 Pod']
    
    print("=== DOWNLOAD FAILURE ANALYSIS ===\n")
    
    for podcast in problematic:
        failures_list = podcast_failures.get(podcast, [])
        if not failures_list:
            continue
            
        print(f"\n{podcast} ({len(failures_list)} failures):")
        print("-" * 50)
        
        # Count error types
        error_types = Counter()
        error_messages = []
        urls = []
        
        for f in failures_list:
            error_type = f.get('error_type', 'Unknown')
            error_msg = f.get('error_message', '')
            url = f.get('url', '')
            
            error_types[error_type] += 1
            if error_msg and error_msg not in error_messages:
                error_messages.append(error_msg)
            if url and url not in urls:
                urls.append(url)
        
        # Print error type breakdown
        print("\nError Types:")
        for error_type, count in error_types.most_common():
            print(f"  - {error_type}: {count}")
        
        # Print sample error messages
        print("\nSample Error Messages:")
        for msg in error_messages[:3]:
            print(f"  - {msg[:100]}...")
        
        # Print sample URLs
        print("\nSample URLs:")
        for url in urls[:3]:
            print(f"  - {url[:80]}...")
    
    # Overall statistics
    print("\n\n=== OVERALL FAILURE STATISTICS ===")
    total_failures = len(failures)
    print(f"Total failures: {total_failures}")
    
    # Component breakdown
    component_failures = Counter()
    for f in failures:
        component = f.get('component', 'Unknown')
        component_failures[component] += 1
    
    print("\nFailures by Component:")
    for component, count in component_failures.most_common():
        percentage = (count / total_failures) * 100
        print(f"  - {component}: {count} ({percentage:.1f}%)")

if __name__ == "__main__":
    analyze_failures()