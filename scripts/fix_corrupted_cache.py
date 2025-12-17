#!/usr/bin/env python3
"""
Fix corrupted database cache

This script helps diagnose and fix corrupted SQLite database caches
that can occur if indexing is interrupted improperly.

Usage:
    python scripts/fix_corrupted_cache.py [project_path]

If project_path is not provided, it will check all cache directories.
"""

import sys
import os
import sqlite3
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_database(db_path):
    """Check if a database is corrupted"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Try a simple query
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()

        conn.close()

        if result and result[0] == "ok":
            return True, "Database is healthy"
        else:
            return False, f"Database integrity check failed: {result}"

    except sqlite3.DatabaseError as e:
        return False, f"Database error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def get_cache_directory():
    """Get the cache directory path"""
    return Path.home() / ".mcp_cache"


def find_project_cache(project_path):
    """Find cache directory for a specific project"""
    from mcp_server.project_identity import ProjectIdentity

    project_path = os.path.abspath(project_path)

    # Try to find config file
    config_file = None
    config_path = os.path.join(project_path, "cpp-analyzer-config.json")
    if os.path.exists(config_path):
        config_file = config_path

    # Get project identity
    identity = ProjectIdentity(project_path, config_file)
    cache_dir = identity.get_cache_directory()

    return cache_dir


def remove_cache_directory(cache_dir):
    """Remove a cache directory"""
    try:
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            return True, f"Removed cache directory: {cache_dir}"
        else:
            return False, f"Cache directory does not exist: {cache_dir}"
    except Exception as e:
        return False, f"Error removing cache directory: {e}"


def scan_all_caches():
    """Scan all cache directories for corruption"""
    cache_dir = get_cache_directory()

    if not cache_dir.exists():
        print(f"No cache directory found at: {cache_dir}")
        return []

    print(f"Scanning cache directory: {cache_dir}\n")

    results = []
    for project_dir in cache_dir.iterdir():
        if not project_dir.is_dir():
            continue

        db_path = project_dir / "cache.db"
        if not db_path.exists():
            continue

        print(f"Checking: {project_dir.name}")
        is_healthy, message = check_database(str(db_path))

        results.append(
            {
                "project_dir": project_dir,
                "db_path": db_path,
                "is_healthy": is_healthy,
                "message": message,
            }
        )

        if is_healthy:
            print(f"  ✓ {message}")
        else:
            print(f"  ✗ {message}")

    return results


def main():
    """Main entry point"""
    print("=" * 70)
    print("Database Cache Corruption Fixer")
    print("=" * 70)
    print()

    if len(sys.argv) > 1:
        # Check specific project
        project_path = sys.argv[1]

        if not os.path.isdir(project_path):
            print(f"Error: Directory '{project_path}' does not exist")
            sys.exit(1)

        print(f"Finding cache for project: {project_path}\n")

        try:
            cache_dir = find_project_cache(project_path)
            print(f"Cache directory: {cache_dir}\n")

            db_path = Path(cache_dir) / "cache.db"

            if not db_path.exists():
                print(f"No database found at: {db_path}")
                print("The project has not been indexed yet or cache was already cleared.")
                sys.exit(0)

            print("Checking database integrity...")
            is_healthy, message = check_database(str(db_path))
            print(f"{message}\n")

            if not is_healthy:
                response = input("Database is corrupted. Delete cache and rebuild? [y/N]: ")
                if response.lower() == "y":
                    success, msg = remove_cache_directory(cache_dir)
                    if success:
                        print(f"✓ {msg}")
                        print("\nYou can now re-index the project. The cache will be rebuilt.")
                    else:
                        print(f"✗ {msg}")
                        sys.exit(1)
                else:
                    print("Aborted. Cache not deleted.")
            else:
                print("Database is healthy. No action needed.")

        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

    else:
        # Scan all caches
        results = scan_all_caches()

        if not results:
            print("No cache directories found.")
            sys.exit(0)

        print("\n" + "=" * 70)
        print("Summary")
        print("=" * 70)

        corrupted = [r for r in results if not r["is_healthy"]]

        if corrupted:
            print(f"\nFound {len(corrupted)} corrupted database(s):\n")
            for r in corrupted:
                print(f"  - {r['project_dir'].name}")
                print(f"    {r['message']}")

            print("\nTo fix corrupted caches, you can:")
            print("1. Delete specific project cache:")
            print("   rm -rf ~/.mcp_cache/<project_dir_name>")
            print("\n2. Delete all caches:")
            print("   rm -rf ~/.mcp_cache/")
            print("\n3. Run this script with the project path:")
            print("   python scripts/fix_corrupted_cache.py /path/to/project")
        else:
            print("\nAll databases are healthy!")


if __name__ == "__main__":
    main()
