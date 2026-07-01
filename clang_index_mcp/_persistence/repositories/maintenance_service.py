"""SQLite-backed database maintenance, health checks, and performance monitoring."""

import sqlite3
import time
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from ..._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class MaintenanceService:
    """Handles database maintenance, integrity checks, health status, and perf monitoring."""

    def __init__(self, conn_getter: Callable[[], Optional[sqlite3.Connection]]):
        self._conn_getter = conn_getter

    @property
    def conn(self) -> sqlite3.Connection:
        connection = self._conn_getter()
        assert connection is not None, "Database connection not initialized"
        return connection

    def get_symbol_stats(self) -> Dict[str, Any]:
        """Get detailed symbol statistics."""
        try:
            stats: Dict[str, Any] = {}
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols")
            stats["total_symbols"] = cursor.fetchone()[0]
            cursor = self.conn.execute("""
                SELECT kind, COUNT(*) as count
                FROM symbols
                GROUP BY kind
                ORDER BY count DESC
            """)
            stats["by_kind"] = {row["kind"]: row["count"] for row in cursor.fetchall()}
            cursor = self.conn.execute("""
                SELECT is_project, COUNT(*) as count
                FROM symbols
                GROUP BY is_project
            """)
            for row in cursor.fetchall():
                if row["is_project"]:
                    stats["project_symbols"] = row["count"]
                else:
                    stats["dependency_symbols"] = row["count"]
            cursor = self.conn.execute("SELECT COUNT(*) FROM file_metadata")
            stats["total_files"] = cursor.fetchone()[0]
            cursor = self.conn.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor = self.conn.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            stats["db_size_bytes"] = page_count * page_size
            stats["db_size_mb"] = stats["db_size_bytes"] / (1024 * 1024)
            return stats
        except Exception as e:
            diagnostics.error(f"Failed to get symbol stats: {e}")
            return {}

    def verify_integrity(self) -> bool:
        """Verify database integrity."""
        try:
            cursor = self.conn.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            if result == "ok":
                diagnostics.debug("Database integrity check: OK")
                return True
            else:
                diagnostics.error(f"Database integrity check failed: {result}")
                return False
        except Exception as e:
            diagnostics.error(f"Failed to check integrity: {e}")
            return False

    def vacuum(self) -> bool:
        """Reclaim space from deleted records."""
        try:
            stats_before = self.get_symbol_stats()
            size_before_mb = stats_before.get("db_size_mb", 0)
            diagnostics.info(f"Running VACUUM (database size: {size_before_mb:.2f} MB)...")
            start_time = time.time()
            self.conn.execute("VACUUM")
            elapsed = time.time() - start_time
            stats_after = self.get_symbol_stats()
            size_after_mb = stats_after.get("db_size_mb", 0)
            space_saved = size_before_mb - size_after_mb
            diagnostics.info(
                f"VACUUM complete in {elapsed:.2f}s. "
                f"Size: {size_before_mb:.2f} MB → {size_after_mb:.2f} MB "
                f"(saved {space_saved:.2f} MB)"
            )
            return True
        except Exception as e:
            diagnostics.error(f"VACUUM failed: {e}")
            return False

    def optimize(self) -> bool:
        """Optimize FTS5 indexes by rebuilding them."""
        try:
            diagnostics.info("Optimizing FTS5 indexes...")
            start_time = time.time()
            self.conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('optimize')")
            elapsed = time.time() - start_time
            diagnostics.info(f"FTS5 optimization complete in {elapsed:.2f}s")
            return True
        except Exception as e:
            diagnostics.error(f"FTS5 optimization failed: {e}")
            return False

    def rebuild_fts(self) -> bool:
        """Rebuild FTS5 index from scratch (C7)."""
        try:
            diagnostics.debug("Rebuilding FTS5 index...")
            start_time = time.time()
            self.conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
            elapsed = time.time() - start_time
            diagnostics.debug(f"FTS5 rebuild complete in {elapsed:.2f}s")
            return True
        except Exception as e:
            diagnostics.error(f"FTS5 rebuild failed: {e}")
            return False

    def analyze(self) -> bool:
        """Update query planner statistics."""
        try:
            diagnostics.info("Running ANALYZE...")
            start_time = time.time()
            self.conn.execute("ANALYZE")
            elapsed = time.time() - start_time
            diagnostics.info(f"ANALYZE complete in {elapsed:.2f}s")
            return True
        except Exception as e:
            diagnostics.error(f"ANALYZE failed: {e}")
            return False

    def auto_maintenance(
        self, vacuum_threshold_mb: float = 100.0, vacuum_min_waste_mb: float = 10.0
    ) -> Dict[str, Any]:
        """Run automatic maintenance based on database health."""
        try:
            diagnostics.info("Running auto-maintenance...")
            results: Dict[str, Any] = {
                "analyze": False,
                "optimize": False,
                "vacuum": False,
                "vacuum_skipped_reason": None,
            }
            results["analyze"] = self.analyze()
            results["optimize"] = self.optimize()
            stats = self.get_symbol_stats()
            db_size_mb = stats.get("db_size_mb", 0)
            if db_size_mb < vacuum_threshold_mb:
                results["vacuum_skipped_reason"] = (
                    f"Database too small ({db_size_mb:.2f} MB < {vacuum_threshold_mb} MB)"
                )
                diagnostics.info(results["vacuum_skipped_reason"])
            else:
                cursor = self.conn.execute("PRAGMA freelist_count")
                freelist_count = cursor.fetchone()[0]
                cursor = self.conn.execute("PRAGMA page_size")
                page_size = cursor.fetchone()[0]
                waste_mb = (freelist_count * page_size) / (1024 * 1024)
                if waste_mb >= vacuum_min_waste_mb:
                    diagnostics.info(
                        f"Running VACUUM (DB: {db_size_mb:.2f} MB, waste: {waste_mb:.2f} MB)"
                    )
                    results["vacuum"] = self.vacuum()
                else:
                    results["vacuum_skipped_reason"] = (
                        f"Insufficient waste ({waste_mb:.2f} MB < {vacuum_min_waste_mb} MB)"
                    )
                    diagnostics.info(results["vacuum_skipped_reason"])
            diagnostics.info(f"Auto-maintenance complete: {results}")
            return results
        except Exception as e:
            diagnostics.error(f"Auto-maintenance failed: {e}")
            return {"error": str(e)}

    def check_integrity(self, full: bool = False) -> Tuple[bool, str]:
        """Check database integrity with detailed reporting."""
        try:
            diagnostics.info(f"Running {'full' if full else 'quick'} integrity check...")
            start_time = time.time()
            if full:
                cursor = self.conn.execute("PRAGMA integrity_check")
            else:
                cursor = self.conn.execute("PRAGMA quick_check")
            results = [row[0] for row in cursor.fetchall()]
            elapsed = time.time() - start_time
            if results == ["ok"]:
                message = f"Integrity check passed in {elapsed:.2f}s"
                diagnostics.info(message)
                return True, message
            else:
                message = f"Integrity check FAILED: {', '.join(results[:5])}"
                if len(results) > 5:
                    message += f" (and {len(results) - 5} more issues)"
                diagnostics.error(message)
                return False, message
        except Exception as e:
            message = f"Integrity check error: {e}"
            diagnostics.error(message)
            return False, message

    def _check_fts5_health(self, health: Dict[str, Any], stats: Dict[str, Any]) -> None:
        """Check FTS5 index health and update health dict."""
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM symbols_fts")
            fts_count = cursor.fetchone()[0]
            symbol_count = stats.get("total_symbols", 0)
            fts_health = {"fts_count": fts_count, "symbol_count": symbol_count, "status": "ok"}
            if fts_count != symbol_count:
                warning = (
                    f"FTS5 count mismatch: {fts_count} FTS vs {symbol_count} symbols. "
                    "Consider running optimize()."
                )
                health["warnings"].append(warning)
                fts_health["status"] = "warning"
            health["checks"]["fts_index"] = fts_health
        except Exception as e:
            health["errors"].append(f"FTS5 check failed: {e}")
            health["checks"]["fts_index"] = {"status": "error", "error": str(e)}

    def _check_wal_mode(self, health: Dict[str, Any]) -> None:
        """Check WAL journal mode and update health dict."""
        try:
            cursor = self.conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0].lower()
            wal_health = {
                "journal_mode": journal_mode,
                "status": "ok" if journal_mode == "wal" else "warning",
            }
            if journal_mode != "wal":
                warning = f"Journal mode is '{journal_mode}', expected 'wal' for best performance"
                health["warnings"].append(warning)
            health["checks"]["wal_mode"] = wal_health
        except Exception as e:
            health["errors"].append(f"WAL check failed: {e}")

    @staticmethod
    def _determine_overall_status(health: Dict[str, Any]) -> None:
        """Set overall health status based on errors and warnings."""
        if health["errors"]:
            health["status"] = "error"
        elif health["warnings"]:
            health["status"] = "warning"
        else:
            health["status"] = "healthy"

    def get_health_status(self) -> Dict[str, Any]:
        """Get comprehensive database health status."""
        try:
            health: Dict[str, Any] = {
                "status": "unknown",
                "checks": {},
                "warnings": [],
                "errors": [],
            }
            is_healthy, message = self.check_integrity(full=False)
            health["checks"]["integrity"] = {"passed": is_healthy, "message": message}
            if not is_healthy:
                health["errors"].append(f"Integrity: {message}")
            stats = self.get_symbol_stats()
            db_size_mb = stats.get("db_size_mb", 0)
            health["checks"]["size"] = {"db_size_mb": db_size_mb, "status": "ok"}
            if db_size_mb > 500:
                warning = f"Database is very large ({db_size_mb:.2f} MB)"
                health["warnings"].append(warning)
                health["checks"]["size"]["status"] = "warning"
            self._check_fts5_health(health, stats)
            self._check_wal_mode(health)
            health["checks"]["tables"] = self.get_table_sizes()
            self._determine_overall_status(health)
            return health
        except Exception as e:
            diagnostics.error(f"Failed to get health status: {e}")
            return {"status": "error", "errors": [str(e)]}

    def get_table_sizes(self) -> Dict[str, Dict[str, Any]]:
        """Get size information for all tables."""
        try:
            tables: Dict[str, Dict[str, Any]] = {}
            cursor = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            table_names = [row[0] for row in cursor.fetchall()]
            for table_name in table_names:
                try:
                    cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row_count = cursor.fetchone()[0]
                    tables[table_name] = {"row_count": row_count, "status": "ok"}
                except Exception as e:
                    tables[table_name] = {"error": str(e), "status": "error"}
            return tables
        except Exception as e:
            diagnostics.error(f"Failed to get table sizes: {e}")
            return {}

    def get_cache_stats(
        self,
        db_path: Optional[str] = None,
        connection_timeout: int = 300,
        last_access: float = 0.0,
    ) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        try:
            stats: Dict[str, Any] = {}
            symbol_stats = self.get_symbol_stats()
            stats.update(symbol_stats)
            cursor = self.conn.execute("""
                SELECT
                    COUNT(*) as total_files,
                    SUM(symbol_count) as total_symbols_from_files,
                    AVG(symbol_count) as avg_symbols_per_file,
                    MAX(symbol_count) as max_symbols_in_file
                FROM file_metadata
            """)
            row = cursor.fetchone()
            stats["file_stats"] = {
                "total_files": row[0] or 0,
                "total_symbols_from_files": row[1] or 0,
                "avg_symbols_per_file": round(row[2], 2) if row[2] else 0,
                "max_symbols_in_file": row[3] or 0,
            }
            cursor = self.conn.execute("""
                SELECT file_path, symbol_count
                FROM file_metadata
                ORDER BY symbol_count DESC
                LIMIT 10
            """)
            stats["top_files"] = [
                {"file": row[0], "symbol_count": row[1]} for row in cursor.fetchall()
            ]
            cursor = self.conn.execute("SELECT key, value FROM cache_metadata")
            stats["metadata"] = {row[0]: row[1] for row in cursor.fetchall()}
            stats["performance"] = {
                "db_path": db_path or "",
                "connection_timeout": connection_timeout,
                "last_access_age_seconds": time.time() - last_access,
            }
            return stats
        except Exception as e:
            diagnostics.error(f"Failed to get cache stats: {e}")
            return {}

    def monitor_performance(self, operation: str = "search") -> Dict[str, float]:
        """Monitor database performance with sample queries."""
        try:
            metrics: Dict[str, float] = {}
            if operation == "search":
                start = time.time()
                cursor = self.conn.execute(
                    "SELECT COUNT(*) FROM symbols_fts WHERE name MATCH 'test*'"
                )
                cursor.fetchone()
                metrics["fts_search_ms"] = (time.time() - start) * 1000
                start = time.time()
                cursor = self.conn.execute("SELECT COUNT(*) FROM symbols WHERE name LIKE 'test%'")
                cursor.fetchone()
                metrics["like_search_ms"] = (time.time() - start) * 1000
            elif operation == "load":
                cursor = self.conn.execute("SELECT usr FROM symbols LIMIT 1")
                row = cursor.fetchone()
                if row:
                    usr = row[0]
                    start = time.time()
                    cursor = self.conn.execute("SELECT * FROM symbols WHERE usr = ?", (usr,))
                    cursor.fetchone()
                    metrics["load_by_usr_ms"] = (time.time() - start) * 1000
            elif operation == "write":
                test_tuple = (
                    "perf_test_usr",
                    "PerfTestSymbol",
                    "",
                    "function",
                    "/test/perf.cpp",
                    1,
                    1,
                    "void PerfTestSymbol",
                    True,
                    "",
                    "public",
                    "",
                    "[]",
                    False,
                    False,
                    None,
                    None,
                    None,
                    1,
                    1,
                    None,
                    None,
                    None,
                    None,
                    True,
                    False,
                    False,
                    False,
                    False,
                    None,
                    None,
                    time.time(),
                    time.time(),
                )
                start = time.time()
                self.conn.execute("SAVEPOINT perf_test")
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO symbols (
                        usr, name, qualified_name, kind, file, line, column, signature,
                        is_project, namespace, access, parent_class,
                        base_classes, is_template_specialization,
                        is_template, template_kind, template_parameters, primary_template_usr,
                        start_line, end_line, header_file, header_line,
                        header_start_line, header_end_line, is_definition,
                        is_virtual, is_pure_virtual, is_const, is_static,
                        brief, doc_comment,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    test_tuple,
                )
                self.conn.execute("ROLLBACK TO perf_test")
                metrics["write_symbol_ms"] = (time.time() - start) * 1000
            return metrics
        except Exception as e:
            diagnostics.error(f"Performance monitoring failed: {e}")
            return {}
