#!/usr/bin/env python3
"""
Test script to verify subprocess cleanup on interrupt

This script indexes a project and can be interrupted with Ctrl-C.
After interruption, check with 'ps aux | grep python' to verify
no orphaned worker processes remain.

Usage:
    python scripts/test_interrupt_cleanup.py <path-to-cpp-project>

Then press Ctrl-C during indexing and verify cleanup.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

_analyzer = None


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python test_interrupt_cleanup.py <path-to-cpp-project>")
        print("\nThis script tests subprocess cleanup on interrupt.")
        print("Start indexing, press Ctrl-C, then check with:")
        print("  ps aux | grep python")
        print("\nYou should see no orphaned worker processes.")
        sys.exit(1)

    project_path = sys.argv[1]

    if not os.path.isdir(project_path):
        print(f"Error: Directory '{project_path}' does not exist")
        sys.exit(1)

    try:
        from mcp_server.cpp_analyzer import CppAnalyzer

        print("=" * 70)
        print("Testing subprocess cleanup on interrupt (Ctrl-C)")
        print("=" * 70)
        print(f"\nIndexing project: {project_path}")
        print("\nPress Ctrl-C during indexing to test cleanup...")
        print("After interruption, check with: ps aux | grep python")
        print("You should see NO orphaned worker processes.\n")

        global _analyzer
        _analyzer = CppAnalyzer(project_path)

        # Start indexing (this will use ProcessPoolExecutor by default)
        print("Starting indexing with ProcessPoolExecutor...")
        indexed_count = _analyzer.index_project(force=True, include_dependencies=True)

        print(f"\n\nIndexing completed successfully: {indexed_count} files indexed")
        print("\nIf you didn't interrupt, try running again and press Ctrl-C during indexing.")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl-C)", file=sys.stderr)
        print("Cleaning up...", file=sys.stderr)
    finally:
        if _analyzer is not None:
            try:
                _analyzer.close()
                print("Analyzer closed successfully", file=sys.stderr)
                print("\nCheck for orphaned processes with: ps aux | grep python", file=sys.stderr)
            except Exception as e:
                print(f"Error closing analyzer: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
