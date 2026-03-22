#!/usr/bin/env python3
"""Quick script to test JobSpy search directly.

Usage:
    # Single search
    python test_jobspy_search.py --query "Software Engineer" --location "Netherlands"
    
    # Full crawl (uses searches.yaml)
    python test_jobspy_search.py --full
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from jobpilot.discovery.jobspy import search_jobs, run_discovery
from jobpilot.config import load_env, ensure_dirs
from jobpilot.database import init_db

def main():
    parser = argparse.ArgumentParser(description="Test JobSpy search")
    parser.add_argument("--query", default="Software Engineer", help="Search query")
    parser.add_argument("--location", default="Netherlands", help="Location")
    parser.add_argument("--results", type=int, default=10, help="Results per site (set to 0 to get all available)")
    parser.add_argument("--hours", type=int, default=240, help="Hours old")
    parser.add_argument("--full", action="store_true", help="Run full crawl from searches.yaml")
    parser.add_argument("--remote", action="store_true", help="Remote only")
    parser.add_argument(
        "--experience-level",
        nargs="+",
        default=None,
        help="Filter by experience level(s): entry-level, senior, manager, director, executive. "
             "Use 'all' or leave empty for no filtering. Example: --experience-level entry-level junior"
    )
    
    args = parser.parse_args()
    
    # Bootstrap
    load_env()
    ensure_dirs()
    init_db()
    
    # Process experience_level
    experience_level = None
    if args.experience_level:
        if "all" in args.experience_level:
            experience_level = None
        else:
            experience_level = args.experience_level
    
    if args.full:
        # Method 2: Full crawl (uses searches.yaml config)
        print("=" * 60)
        print("Running full crawl from searches.yaml...")
        print("=" * 60)
        result = run_discovery()
        print(f"\nResults: {result}")
    else:
        # Method 1: Single search
        print("=" * 60)
        print(f"Single search: '{args.query}' in {args.location}")
        if args.results == 0:
            print("Results: all available (no limit)")
        else:
            print(f"Results: {args.results} per site")
        if experience_level:
            print(f"Experience level filter: {experience_level}")
        else:
            print("Experience level filter: all (no filtering)")
        print("=" * 60)
        result = search_jobs(
            query=args.query,
            location=args.location,
            sites=["indeed", "linkedin"],
            remote_only=args.remote,
            results_per_site=args.results,
            hours_old=args.hours,
            country_indeed="netherlands",
            experience_level=experience_level
        )
        print(f"\nResults: {result}")
        if result.get("filtered", 0) > 0:
            print(f"  Filtered: {result['filtered']} jobs by experience level")

if __name__ == "__main__":
    main()
