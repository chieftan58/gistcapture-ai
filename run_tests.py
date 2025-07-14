#!/usr/bin/env python3
"""Test runner for Renaissance Weekly with helpful options"""

import sys
import subprocess
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Run Renaissance Weekly tests')
    parser.add_argument('--unit', action='store_true', help='Run only unit tests')
    parser.add_argument('--integration', action='store_true', help='Run only integration tests')
    parser.add_argument('--e2e', action='store_true', help='Run only end-to-end tests')
    parser.add_argument('--coverage', action='store_true', help='Generate coverage report')
    parser.add_argument('--watch', action='store_true', help='Watch for changes and rerun')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--failed', action='store_true', help='Run only failed tests')
    parser.add_argument('--parallel', '-n', help='Run tests in parallel (e.g., -n 4)')
    parser.add_argument('tests', nargs='*', help='Specific test files or patterns')
    
    args = parser.parse_args()
    
    # Build pytest command
    cmd = ['pytest']
    
    # Add markers based on flags
    markers = []
    if args.unit:
        markers.append('unit')
    if args.integration:
        markers.append('integration')
    if args.e2e:
        markers.append('e2e')
    
    if markers:
        cmd.extend(['-m', ' or '.join(markers)])
    
    # Add other options
    if args.coverage:
        cmd.extend(['--cov=renaissance_weekly', '--cov-report=html', '--cov-report=term'])
    
    if args.verbose:
        cmd.append('-v')
    
    if args.failed:
        cmd.append('--lf')
    
    if args.parallel:
        cmd.extend(['-n', args.parallel])
    
    # Add specific tests if provided
    if args.tests:
        cmd.extend(args.tests)
    
    # Run tests
    if args.watch:
        # Use pytest-watch
        watch_cmd = ['ptw'] + cmd[1:]  # Remove 'pytest' as ptw adds it
        print(f"Running: {' '.join(watch_cmd)}")
        subprocess.run(watch_cmd)
    else:
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd)
        sys.exit(result.returncode)


if __name__ == '__main__':
    main()