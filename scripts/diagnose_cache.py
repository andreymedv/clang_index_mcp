#!/usr/bin/env python3
"""
Cache Diagnostic Tool

Diagnoses cache health and suggests fixes for common issues:
- Checks cache integrity
- Checks for corruption
- Checks for missing indexes
- Checks for schema version mismatch
- Checks FTS5 index health
- Provides actionable recommendations
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.schema_migrations import SchemaMigration  # noqa: E402
from mcp_server.sqlite_cache_backend import SqliteCacheBackend  # noqa: E402


class CacheDiagnostic:
    """Cache diagnostic runner."""

    def __init__(self, cache_dir: Path):
        """Initialize diagnostic tool."""
        self.cache_dir = cache_dir
        self.db_path = cache_dir / "symbols.db"
        self.issues = []
        self.warnings = []
        self.suggestions = []

    def run(self) -> Dict[str, Any]:
        """Run all diagnostics."""
        results = {
            "cache_dir": str(self.cache_dir),
            "cache_type": "SQLite",
            "issues": [],
            "warnings": [],
            "suggestions": [],
            "checks": {},
        }

        # Check if SQLite cache exists
        if self.db_path.exists():
            self._diagnose_sqlite(results)
        else:
            results["cache_type"] = "None"
            results["issues"].append("No SQLite cache found")
            results["suggestions"].append("Run the analyzer to create a cache")

        return results

    def _diagnose_sqlite(self, results: Dict[str, Any]):
        """Run SQLite-specific diagnostics."""
        try:
            backend = SqliteCacheBackend(self.db_path)

            # 1. Integrity check
            results["checks"]["integrity"] = self._check_integrity(backend)

            # 2. Schema version check
            results["checks"]["schema_version"] = self._check_schema_version(backend)

            # 3. Index health check
            results["checks"]["indexes"] = self._check_indexes(backend)

            # 4. FTS5 health check
            results["checks"]["fts5"] = self._check_fts5_health(backend)

            # 5. WAL mode check
            results["checks"]["wal_mode"] = self._check_wal_mode(backend)

            # 6. Database size check
            results["checks"]["size"] = self._check_database_size(backend)

            # 7. Symbol count sanity check
            results["checks"]["symbols"] = self._check_symbol_sanity(backend)

            backend._close()

            # Aggregate issues and suggestions
            for check_name, check_result in results["checks"].items():
                if not check_result.get("passed", True):
                    results["issues"].extend(check_result.get("issues", []))
                if check_result.get("warnings"):
                    results["warnings"].extend(check_result["warnings"])
                if check_result.get("suggestions"):
                    results["suggestions"].extend(check_result["suggestions"])

        except Exception as e:
            results["issues"].append(f"Failed to open SQLite database: {e}")
            results["suggestions"].append(
                "Database may be corrupted. Try running sqlite_cache_backend.auto_maintenance()"
            )

    def _check_integrity(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check database integrity."""
        check = {
            "name": "Integrity Check",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            is_healthy, message = backend.check_integrity(full=False)

            if not is_healthy:
                check["passed"] = False
                check["issues"].append(f"Integrity check failed: {message}")
                check["suggestions"].append("Run VACUUM to repair database")
                check["suggestions"].append("If VACUUM fails, restore from backup or delete cache")

        except Exception as e:
            check["passed"] = False
            check["issues"].append(f"Integrity check error: {e}")

        return check

    def _check_schema_version(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check schema version."""
        check = {
            "name": "Schema Version",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            migration = SchemaMigration(backend.conn)
            current_version = migration.get_current_version()
            expected_version = backend.CURRENT_SCHEMA_VERSION

            if current_version != expected_version:
                if current_version < expected_version:
                    check["warnings"].append(
                        f"Schema outdated: v{current_version} (expected v{expected_version})"
                    )
                    check["suggestions"].append("Schema will be auto-upgraded on next use")
                else:
                    check["passed"] = False
                    check["issues"].append(
                        f"Schema too new: v{current_version} (expected v{expected_version})"
                    )
                    check["suggestions"].append("Update your code or delete the cache")

        except Exception as e:
            check["issues"].append(f"Schema version check failed: {e}")

        return check

    def _check_indexes(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check that all required indexes exist."""
        check = {
            "name": "Index Health",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            # Get list of indexes
            cursor = backend.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
            existing_indexes = {row[0] for row in cursor.fetchall()}

            # Required indexes (from schema.sql)
            required_indexes = {
                "idx_symbols_name",
                "idx_symbols_kind",
                "idx_symbols_file",
                "idx_symbols_parent_class",
                "idx_symbols_namespace",
                "idx_symbols_project",
                "idx_symbols_name_kind_project",
                "idx_symbols_updated_at",
                "idx_file_metadata_indexed_at",
            }

            missing_indexes = required_indexes - existing_indexes

            if missing_indexes:
                check["passed"] = False
                check["issues"].append(f"Missing indexes: {', '.join(missing_indexes)}")
                check["suggestions"].append("Recreate database from schema.sql or run migrations")

        except Exception as e:
            check["issues"].append(f"Index check failed: {e}")

        return check

    def _check_fts5_health(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check FTS5 index health."""
        check = {
            "name": "FTS5 Health",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            # Check FTS5 table exists
            cursor = backend.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols_fts'"
            )
            if not cursor.fetchone():
                check["passed"] = False
                check["issues"].append("FTS5 table 'symbols_fts' not found")
                check["suggestions"].append("Recreate database from schema.sql")
                return check

            # Check FTS5 count vs symbol count
            cursor = backend.conn.execute("SELECT COUNT(*) FROM symbols_fts")
            fts_count = cursor.fetchone()[0]

            cursor = backend.conn.execute("SELECT COUNT(*) FROM symbols")
            symbol_count = cursor.fetchone()[0]

            if fts_count != symbol_count:
                check["warnings"].append(
                    f"FTS5 count mismatch: {fts_count} FTS vs {symbol_count} symbols"
                )
                check["suggestions"].append("Run backend.optimize() to rebuild FTS5 index")

        except Exception as e:
            check["issues"].append(f"FTS5 check failed: {e}")

        return check

    def _check_wal_mode(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check WAL mode configuration."""
        check = {
            "name": "WAL Mode",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            cursor = backend.conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0].lower()

            if journal_mode != "wal":
                check["warnings"].append(f"Journal mode is '{journal_mode}', expected 'wal'")
                check["suggestions"].append("WAL mode provides better concurrency")
                check["suggestions"].append("Run: PRAGMA journal_mode=WAL")

        except Exception as e:
            check["issues"].append(f"WAL mode check failed: {e}")

        return check

    def _check_database_size(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check database size."""
        check = {
            "name": "Database Size",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            stats = backend.get_symbol_stats()
            db_size_mb = stats.get("db_size_mb", 0)

            # Warn if very large
            if db_size_mb > 1000:
                check["warnings"].append(f"Database is very large: {db_size_mb:.1f} MB")
                check["suggestions"].append("Consider running VACUUM to reclaim space")

            # Check for wasted space
            cursor = backend.conn.execute("PRAGMA freelist_count")
            freelist_count = cursor.fetchone()[0]

            if freelist_count > 1000:
                cursor = backend.conn.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                waste_mb = (freelist_count * page_size) / (1024 * 1024)

                if waste_mb > 10:
                    check["warnings"].append(f"Wasted space: ~{waste_mb:.1f} MB")
                    check["suggestions"].append("Run VACUUM to reclaim space")

        except Exception as e:
            check["issues"].append(f"Size check failed: {e}")

        return check

    def _check_symbol_sanity(self, backend: SqliteCacheBackend) -> Dict[str, Any]:
        """Check symbol counts for sanity."""
        check = {
            "name": "Symbol Counts",
            "passed": True,
            "issues": [],
            "warnings": [],
            "suggestions": [],
        }

        try:
            stats = backend.get_symbol_stats()
            total_symbols = stats.get("total_symbols", 0)

            if total_symbols == 0:
                check["warnings"].append("Cache contains no symbols")
                check["suggestions"].append("Run the analyzer to index your project")
            elif total_symbols > 1000000:
                check["warnings"].append(f"Very large symbol count: {total_symbols:,}")
                check["suggestions"].append("Consider excluding dependencies or system headers")

        except Exception as e:
            check["issues"].append(f"Symbol count check failed: {e}")

        return check


def print_diagnostic_results(results: Dict[str, Any]):
    """Print diagnostic results."""
    print("=" * 70)
    print("CACHE DIAGNOSTIC REPORT")
    print("=" * 70)
    print()

    print(f"Cache Directory: {results['cache_dir']}")
    print(f"Cache Type: {results['cache_type']}")
    print()

    # Individual checks
    if results.get("checks"):
        print("─" * 70)
        print("DIAGNOSTIC CHECKS")
        print("─" * 70)
        for check_name, check_result in results["checks"].items():
            status = "[PASS] PASS" if check_result.get("passed", True) else "[ERROR] FAIL"
            print(f"{check_result['name']:30s} {status}")
        print()

    # Issues
    if results["issues"]:
        print("─" * 70)
        print("ISSUES FOUND")
        print("─" * 70)
        for i, issue in enumerate(results["issues"], 1):
            print(f"{i}. [ERROR] {issue}")
        print()

    # Warnings
    if results["warnings"]:
        print("─" * 70)
        print("WARNINGS")
        print("─" * 70)
        for i, warning in enumerate(results["warnings"], 1):
            print(f"{i}. [WARNING]  {warning}")
        print()

    # Suggestions
    if results["suggestions"]:
        print("─" * 70)
        print("SUGGESTIONS")
        print("─" * 70)
        for i, suggestion in enumerate(results["suggestions"], 1):
            print(f"{i}. [TIP] {suggestion}")
        print()

    # Overall status
    print("=" * 70)
    if not results["issues"]:
        if not results["warnings"]:
            print("[PASS] Cache is healthy")
        else:
            print(f"[WARNING]  Cache is functional but has {len(results['warnings'])} warning(s)")
    else:
        print(f"[ERROR] Cache has {len(results['issues'])} issue(s)")
    print("=" * 70)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Diagnose cache health and suggest fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cache-dir", type=Path, help="Path to cache directory (default: .mcp_cache)"
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed diagnostic information"
    )

    args = parser.parse_args()

    # Determine cache directory
    if args.cache_dir:
        cache_dir = args.cache_dir
    else:
        cache_dir = Path.cwd() / ".mcp_cache"

    if not cache_dir.exists():
        print(f"[ERROR] Cache directory not found: {cache_dir}", file=sys.stderr)
        sys.exit(1)

    # Run diagnostics
    diagnostic = CacheDiagnostic(cache_dir)
    results = diagnostic.run()

    # Output
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_diagnostic_results(results)

    # Exit code based on issues
    sys.exit(1 if results["issues"] else 0)


if __name__ == "__main__":
    main()
