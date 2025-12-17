#!/usr/bin/env python3
"""
Utility script for developers to view and analyze parse error logs.

This script provides easy access to the centralized error log created by
the C++ analyzer when files fail to parse.

Usage:
    # View recent errors
    python scripts/view_parse_errors.py <project_root>

    # View errors for specific file
    python scripts/view_parse_errors.py <project_root> --filter "MyClass.cpp"

    # View full error summary
    python scripts/view_parse_errors.py <project_root> --summary

    # Clear old errors (older than 7 days)
    python scripts/view_parse_errors.py <project_root> --clear-old 7

    # Clear all errors
    python scripts/view_parse_errors.py <project_root> --clear-all
"""

import sys
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cache_manager import CacheManager


def print_error_entry(error, index=None, verbose=False):
    """Print a single error entry in a readable format."""
    prefix = f"\n[{index}] " if index is not None else "\n"

    print(f"{prefix}{'=' * 70}")
    print(f"Time: {error.get('timestamp_readable', 'Unknown')}")
    print(f"File: {error.get('file_path', 'Unknown')}")
    print(f"Error Type: {error.get('error_type', 'Unknown')}")
    print(f"Retry Count: {error.get('retry_count', 0)}")
    print(f"\nError Message:")
    print(f"  {error.get('error_message', 'No message')}")

    if verbose and error.get("stack_trace"):
        print(f"\nStack Trace:")
        print(error.get("stack_trace"))


def view_errors(project_root: str, args):
    """View parse errors from the log."""
    cache_mgr = CacheManager(Path(project_root))

    if args.summary:
        # Show summary
        summary = cache_mgr.get_error_summary()

        print("\n" + "=" * 70)
        print("PARSE ERROR SUMMARY")
        print("=" * 70)
        print(f"Total errors logged: {summary['total_errors']}")
        print(f"Unique files with errors: {summary['unique_files']}")
        print(f"Error log location: {summary['error_log_path']}")

        print(f"\nError Types:")
        for error_type, count in sorted(
            summary["error_types"].items(), key=lambda x: x[1], reverse=True
        ):
            print(f"  {error_type}: {count}")

        print(f"\nMost Recent Errors:")
        for i, error in enumerate(summary["recent_errors"], 1):
            print_error_entry(error, i, verbose=args.verbose)

    else:
        # Show individual errors
        errors = cache_mgr.get_parse_errors(limit=args.limit, file_path_filter=args.filter)

        if not errors:
            print("No parse errors found.")
            if args.filter:
                print(f"(Filter: '{args.filter}')")
            return

        print("\n" + "=" * 70)
        print(f"PARSE ERRORS (showing {len(errors)} most recent)")
        if args.filter:
            print(f"Filter: '{args.filter}'")
        print("=" * 70)

        for i, error in enumerate(errors, 1):
            print_error_entry(error, i, verbose=args.verbose)


def clear_errors(project_root: str, args):
    """Clear parse errors from the log."""
    cache_mgr = CacheManager(Path(project_root))

    if args.clear_all:
        count = cache_mgr.clear_error_log()
        print(f"Cleared {count} error(s) from the log.")
    elif args.clear_old is not None:
        count = cache_mgr.clear_error_log(older_than_days=args.clear_old)
        print(f"Cleared {count} error(s) older than {args.clear_old} days.")


def main():
    parser = argparse.ArgumentParser(
        description="View and analyze C++ parse error logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("project_root", help="Path to the C++ project root directory")

    parser.add_argument(
        "--summary", "-s", action="store_true", help="Show error summary with statistics"
    )

    parser.add_argument(
        "--filter", "-f", type=str, help="Filter errors by file path (substring match)"
    )

    parser.add_argument(
        "--limit", "-l", type=int, default=20, help="Maximum number of errors to show (default: 20)"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Show full stack traces")

    parser.add_argument(
        "--clear-old",
        type=int,
        metavar="DAYS",
        help="Clear errors older than specified number of days",
    )

    parser.add_argument("--clear-all", action="store_true", help="Clear all errors from the log")

    args = parser.parse_args()

    # Validate project root
    project_path = Path(args.project_root)
    if not project_path.exists():
        print(f"Error: Project root does not exist: {args.project_root}", file=sys.stderr)
        sys.exit(1)

    # Handle clearing
    if args.clear_all or args.clear_old is not None:
        clear_errors(args.project_root, args)
        return

    # View errors
    view_errors(args.project_root, args)


if __name__ == "__main__":
    main()
