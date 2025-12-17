#!/usr/bin/env python3
"""
Cache Statistics Tool

Shows comprehensive statistics about the C++ analyzer SQLite cache, including:
- Database size
- Symbol count breakdown by kind
- File statistics
- Last vacuum time
- Query performance statistics
- Health status
"""

import sys
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server import diagnostics
from mcp_server.sqlite_cache_backend import SqliteCacheBackend
from mcp_server.cache_manager import CacheManager


def format_size(bytes_value: int) -> str:
    """Format byte size in human-readable format."""
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1024 * 1024:
        return f"{bytes_value / 1024:.2f} KB"
    elif bytes_value < 1024 * 1024 * 1024:
        return f"{bytes_value / (1024 * 1024):.2f} MB"
    else:
        return f"{bytes_value / (1024 * 1024 * 1024):.2f} GB"


def get_sqlite_cache_stats(cache_dir: Path) -> Dict[str, Any]:
    """Get statistics for SQLite cache."""
    db_path = cache_dir / "symbols.db"

    if not db_path.exists():
        return {"error": "No SQLite cache found"}

    stats = {"backend_type": "SQLite", "db_path": str(db_path)}

    try:
        backend = SqliteCacheBackend(db_path)

        # Get symbol statistics
        symbol_stats = backend.get_symbol_stats()
        stats.update(symbol_stats)

        # Get cache statistics
        cache_stats = backend.get_cache_stats()
        if "file_stats" in cache_stats:
            stats["file_stats"] = cache_stats["file_stats"]
        if "top_files" in cache_stats:
            stats["top_files"] = cache_stats["top_files"]
        if "metadata" in cache_stats:
            stats["metadata"] = cache_stats["metadata"]

        # Get health status
        health = backend.get_health_status()
        stats["health_status"] = health["status"]
        stats["health_warnings"] = health.get("warnings", [])
        stats["health_errors"] = health.get("errors", [])

        # Get performance metrics
        perf_search = backend.monitor_performance("search")
        stats["performance_search_ms"] = perf_search

        # Format database size
        if "db_size_bytes" in stats:
            stats["db_size_formatted"] = format_size(stats["db_size_bytes"])

        backend._close()

    except Exception as e:
        stats["error"] = str(e)

    return stats


def print_stats(stats: Dict[str, Any]):
    """Print statistics in formatted output."""
    print("=" * 70)
    print("CACHE STATISTICS")
    print("=" * 70)
    print()

    if "error" in stats:
        print(f"[ERROR] Error: {stats['error']}")
        return

    # Backend type
    print(f"Backend Type: {stats.get('backend_type', 'Unknown')}")
    print()

    # Size information
    print("─" * 70)
    print("SIZE INFORMATION")
    print("─" * 70)
    if "db_size_formatted" in stats:
        print(f"Database Size: {stats['db_size_formatted']}")
        print(f"  Raw bytes: {stats.get('db_size_bytes', 0):,}")
    elif "cache_size_formatted" in stats:
        print(f"Cache Size: {stats['cache_size_formatted']}")
        print(f"  Raw bytes: {stats.get('cache_size_bytes', 0):,}")
    print()

    # Symbol statistics
    print("─" * 70)
    print("SYMBOL STATISTICS")
    print("─" * 70)
    print(f"Total Symbols: {stats.get('total_symbols', 0):,}")

    if "by_kind" in stats:
        print("\nBy Kind:")
        for kind, count in sorted(stats["by_kind"].items(), key=lambda x: x[1], reverse=True):
            print(f"  {kind:20s}: {count:,}")
    else:
        if "class_symbols" in stats:
            print(f"  Classes: {stats['class_symbols']:,}")
        if "function_symbols" in stats:
            print(f"  Functions: {stats['function_symbols']:,}")

    if "project_symbols" in stats:
        print(f"\nProject Symbols: {stats['project_symbols']:,}")
    if "dependency_symbols" in stats:
        print(f"Dependency Symbols: {stats['dependency_symbols']:,}")
    print()

    # File statistics
    print("─" * 70)
    print("FILE STATISTICS")
    print("─" * 70)
    print(f"Total Files: {stats.get('total_files', 0):,}")

    if "file_stats" in stats:
        fs = stats["file_stats"]
        print(f"Average Symbols per File: {fs.get('avg_symbols_per_file', 0):.1f}")
        print(f"Max Symbols in a File: {fs.get('max_symbols_in_file', 0):,}")

    if "top_files" in stats and stats["top_files"]:
        print("\nTop Files by Symbol Count:")
        for i, file_info in enumerate(stats["top_files"][:5], 1):
            file_path = file_info.get("file", "unknown")
            # Shorten path if too long
            if len(file_path) > 60:
                file_path = "..." + file_path[-57:]
            print(f"  {i}. {file_path}")
            print(f"     Symbols: {file_info.get('symbol_count', 0):,}")
    print()

    # Performance (SQLite only)
    if stats.get("backend_type") == "SQLite" and "performance_search_ms" in stats:
        print("─" * 70)
        print("PERFORMANCE METRICS")
        print("─" * 70)
        perf = stats["performance_search_ms"]
        if "fts_search_ms" in perf:
            print(f"FTS5 Search: {perf['fts_search_ms']:.2f} ms")
        if "like_search_ms" in perf:
            print(f"LIKE Search: {perf['like_search_ms']:.2f} ms")
        print()

    # Health status (SQLite only)
    if stats.get("backend_type") == "SQLite":
        print("─" * 70)
        print("HEALTH STATUS")
        print("─" * 70)
        status = stats.get("health_status", "unknown")
        if status == "healthy":
            print(f"Status: [PASS] {status.upper()}")
        elif status == "warning":
            print(f"Status: [WARNING]  {status.upper()}")
        elif status == "error":
            print(f"Status: [ERROR] {status.upper()}")
        else:
            print(f"Status: {status}")

        warnings = stats.get("health_warnings", [])
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for warning in warnings:
                print(f"  [WARNING]  {warning}")

        errors = stats.get("health_errors", [])
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for error in errors:
                print(f"  [ERROR] {error}")
        print()

    # Metadata
    if "metadata" in stats and stats["metadata"]:
        print("─" * 70)
        print("METADATA")
        print("─" * 70)
        for key, value in stats["metadata"].items():
            print(f"{key}: {value}")
        print()

    print("=" * 70)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Show comprehensive cache statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cache-dir", type=Path, help="Path to cache directory (default: .mcp_cache)"
    )
    parser.add_argument("--json", action="store_true", help="Output statistics as JSON")

    args = parser.parse_args()

    # Determine cache directory
    if args.cache_dir:
        cache_dir = args.cache_dir
    else:
        cache_dir = Path.cwd() / ".mcp_cache"

    if not cache_dir.exists():
        print(f"[ERROR] Cache directory not found: {cache_dir}", file=sys.stderr)
        sys.exit(1)

    # Get SQLite cache statistics
    db_path = cache_dir / "symbols.db"

    if not db_path.exists():
        print(f"[ERROR] No SQLite cache found in {cache_dir}", file=sys.stderr)
        sys.exit(1)

    stats = get_sqlite_cache_stats(cache_dir)

    # Output
    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print_stats(stats)


if __name__ == "__main__":
    main()
