#!/usr/bin/env python
"""Find unclosed aiohttp sessions in the codebase"""

import os
from pathlib import Path

def find_session_creations(file_path):
    """Find aiohttp.ClientSession() calls without proper cleanup"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    issues = []
    if 'aiohttp.ClientSession' in content:
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Look for session creation without async with
            if 'aiohttp.ClientSession()' in line and 'async with' not in line:
                issues.append((file_path, i, line.strip()))
            # Look for self.session = aiohttp.ClientSession
            elif 'self.session = aiohttp.ClientSession' in line:
                # Check if there's a cleanup method in the file
                if 'cleanup' not in content and '__aexit__' not in content and 'close()' not in content:
                    issues.append((file_path, i, line.strip()))
    
    return issues

# Search all Python files
print("🔍 Searching for unclosed aiohttp sessions...\n")
all_issues = []
for py_file in Path('renaissance_weekly').rglob('*.py'):
    issues = find_session_creations(py_file)
    all_issues.extend(issues)

if all_issues:
    print(f"Found {len(all_issues)} potential memory leaks:\n")
    for file_path, line_num, line in all_issues:
        print(f"📍 {file_path}:{line_num}")
        print(f"   {line}")
        print()
else:
    print("✅ No obvious session leaks found!")