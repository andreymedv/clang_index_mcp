#!/usr/bin/env python3
"""
Cache Migration Tool

Command-line tool for migrating JSON caches to SQLite format.
Provides progress reporting, verification, and backup creation.

Features:
- Automatic backup before migration
- Progress reporting during migration
- Verification after migration
- Batch migration support (multiple projects)
- Dry-run mode
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server import diagnostics
from mcp_server.cache_migration import (
    migrate_json_to_sqlite,
    verify_migration,
    create_migration_backup,
    should_migrate,
    create_migration_marker
)


def migrate_single_cache(cache_dir: Path, dry_run: bool = False,
                        skip_backup: bool = False,
                        skip_verification: bool = False,
                        verbose: bool = False) -> Dict[str, Any]:
    """
    Migrate a single cache directory.

    Args:
        cache_dir: Path to cache directory
        dry_run: If True, don't actually migrate
        skip_backup: If True, skip backup creation
        skip_verification: If True, skip post-migration verification
        verbose: If True, show detailed progress

    Returns:
        Dict with migration results
    """
    result = {
        "cache_dir": str(cache_dir),
        "success": False,
        "message": "",
        "backup_path": None,
        "migration_time": 0,
        "symbols_migrated": 0,
        "files_migrated": 0,
        "verification_passed": False
    }

    json_path = cache_dir / "cache_info.json"
    db_path = cache_dir / "cache.db"

    # Check if migration needed
    if not should_migrate(cache_dir):
        if db_path.exists():
            result["message"] = "Already migrated to SQLite"
        elif not json_path.exists():
            result["message"] = "No JSON cache found"
        else:
            result["message"] = "Migration marker exists (already migrated)"
        return result

    # Dry run check
    if dry_run:
        result["message"] = "Dry run - migration would proceed"
        result["success"] = True
        return result

    try:
        # Step 1: Create backup
        if not skip_backup:
            if verbose:
                print(f"  Creating backup...")
            backup_path = create_migration_backup(cache_dir)
            result["backup_path"] = str(backup_path)
            if verbose:
                print(f"  Backup created: {backup_path}")
        else:
            if verbose:
                print(f"  Skipping backup (--skip-backup)")

        # Step 2: Migrate
        if verbose:
            print(f"  Migrating JSON to SQLite...")

        start_time = time.time()
        success, message = migrate_json_to_sqlite(json_path, db_path)
        result["migration_time"] = time.time() - start_time

        if not success:
            result["message"] = f"Migration failed: {message}"
            return result

        if verbose:
            print(f"  Migration completed in {result['migration_time']:.2f}s")

        # Step 3: Verify
        if not skip_verification:
            if verbose:
                print(f"  Verifying migration...")

            verify_success, verify_message = verify_migration(json_path, db_path)

            if verify_success:
                result["verification_passed"] = True
                if verbose:
                    print(f"  Verification passed")
            else:
                result["message"] = f"Verification failed: {verify_message}"
                if verbose:
                    print(f"  ❌ Verification failed: {verify_message}")
                return result
        else:
            result["verification_passed"] = True
            if verbose:
                print(f"  Skipping verification (--skip-verification)")

        # Step 4: Create marker
        create_migration_marker(cache_dir)

        result["success"] = True
        result["message"] = "Migration successful"

        # Get symbol and file counts
        from mcp_server.sqlite_cache_backend import SqliteCacheBackend
        try:
            backend = SqliteCacheBackend(db_path)
            stats = backend.get_symbol_stats()
            result["symbols_migrated"] = stats.get("total_symbols", 0)
            result["files_migrated"] = stats.get("total_files", 0)
            backend._close()
        except Exception:
            pass

    except Exception as e:
        result["message"] = f"Error during migration: {e}"
        result["success"] = False

    return result


def migrate_batch(cache_dirs: List[Path], **kwargs) -> List[Dict[str, Any]]:
    """
    Migrate multiple cache directories.

    Args:
        cache_dirs: List of cache directories
        **kwargs: Options to pass to migrate_single_cache

    Returns:
        List of migration results
    """
    results = []

    for cache_dir in cache_dirs:
        print(f"\n{'=' * 70}")
        print(f"Migrating: {cache_dir}")
        print(f"{'=' * 70}")

        result = migrate_single_cache(cache_dir, **kwargs)
        results.append(result)

        # Print summary
        if result["success"]:
            print(f"✅ {result['message']}")
            if result.get("symbols_migrated"):
                print(f"   Symbols: {result['symbols_migrated']:,}")
            if result.get("files_migrated"):
                print(f"   Files: {result['files_migrated']:,}")
            if result.get("migration_time"):
                print(f"   Time: {result['migration_time']:.2f}s")
        else:
            print(f"❌ {result['message']}")

    return results


def print_summary(results: List[Dict[str, Any]]):
    """Print migration summary."""
    print(f"\n{'=' * 70}")
    print("MIGRATION SUMMARY")
    print(f"{'=' * 70}\n")

    total = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total - successful

    print(f"Total Caches: {total}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    if failed > 0:
        print(f"\nFailed Migrations:")
        for result in results:
            if not result["success"]:
                print(f"  ❌ {result['cache_dir']}")
                print(f"     {result['message']}")

    total_symbols = sum(r.get("symbols_migrated", 0) for r in results if r["success"])
    total_files = sum(r.get("files_migrated", 0) for r in results if r["success"])
    total_time = sum(r.get("migration_time", 0) for r in results if r["success"])

    if total_symbols > 0:
        print(f"\nTotal Migrated:")
        print(f"  Symbols: {total_symbols:,}")
        print(f"  Files: {total_files:,}")
        print(f"  Time: {total_time:.2f}s")

    print(f"\n{'=' * 70}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate JSON cache(s) to SQLite format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate current directory's cache
  %(prog)s

  # Migrate specific cache directory
  %(prog)s --cache-dir /path/to/project/.mcp_cache

  # Batch migrate multiple projects
  %(prog)s --batch /path/to/project1 /path/to/project2

  # Dry run to check what would be migrated
  %(prog)s --dry-run

  # Skip backup (not recommended)
  %(prog)s --skip-backup

  # Skip verification (faster but risky)
  %(prog)s --skip-verification
"""
    )

    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Path to cache directory (default: .mcp_cache)"
    )
    parser.add_argument(
        "--batch",
        type=Path,
        nargs="+",
        help="Migrate multiple cache directories"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually migrating"
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip backup creation (not recommended)"
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip post-migration verification (faster but risky)"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    # Determine cache directories
    if args.batch:
        # Batch mode: migrate multiple directories
        cache_dirs = []
        for path in args.batch:
            if path.is_dir():
                # Check if it's a cache dir or contains .mcp_cache
                if (path / "cache_info.json").exists() or (path / "cache.db").exists():
                    cache_dirs.append(path)
                elif (path / ".mcp_cache").exists():
                    cache_dirs.append(path / ".mcp_cache")
                else:
                    print(f"⚠️  No cache found in: {path}", file=sys.stderr)
            else:
                print(f"⚠️  Not a directory: {path}", file=sys.stderr)

        if not cache_dirs:
            print("❌ No valid cache directories found", file=sys.stderr)
            sys.exit(1)

    else:
        # Single mode
        if args.cache_dir:
            cache_dir = args.cache_dir
        else:
            cache_dir = Path.cwd() / ".mcp_cache"

        if not cache_dir.exists():
            print(f"❌ Cache directory not found: {cache_dir}", file=sys.stderr)
            sys.exit(1)

        cache_dirs = [cache_dir]

    # Migrate
    results = migrate_batch(
        cache_dirs,
        dry_run=args.dry_run,
        skip_backup=args.skip_backup,
        skip_verification=args.skip_verification,
        verbose=args.verbose
    )

    # Output
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if len(results) > 1:
            print_summary(results)

    # Exit code
    failed = sum(1 for r in results if not r["success"])
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
