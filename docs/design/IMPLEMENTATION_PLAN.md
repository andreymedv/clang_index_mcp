# SQLite Cache Implementation Plan - Final Version

**Status:** Ready for Implementation
**Date:** 2025-11-17
**Approved By:** Architect Review
**Related Documents:**
- [Original Design](./sqlite-cache-architecture.md) - Comprehensive architecture document
- [Critical Review](./sqlite-cache-architecture-review.md) - Issues and improvements identified
- [Issue #001](../issues/001-cache-scalability.md) - Original problem statement

---

## Executive Summary

This document presents the **final approved implementation plan** for migrating from JSON-based cache to SQLite-based cache, incorporating critical improvements identified during architectural review.

### Key Improvements Over Original Design

✅ **Schema migration framework** - Future-proof versioning system
✅ **Concurrent write safety** - Proper locking and retry logic
✅ **Connection lifecycle management** - Prevents resource leaks
✅ **Full-text search (FTS5)** - 20x faster name searches
✅ **Query performance monitoring** - Production debugging capability
✅ **Platform-specific configuration** - Windows/Unix/Network FS support

### Updated Metrics

| Metric | Current (JSON) | Target (SQLite) | Expected (with FTS5) |
|--------|----------------|-----------------|----------------------|
| Cold startup | 10,000ms | 500ms | **450ms** ✓ |
| Name search | 50ms | 5ms | **2ms** ✓ (FTS5) |
| Memory usage | 200MB | 50MB | **45MB** ✓ |
| Disk usage | 100MB | 30MB | **32MB** (FTS5 index) |
| Incremental update | 5,000ms | 50ms | **45ms** ✓ |

### Timeline

**Original:** 3 weeks
**Updated:** 3.5 weeks (with improvements)

---

## Implementation Phases

### Phase 1: Foundation (Week 1, Days 1-4)

**Goal:** Create production-ready SQLite backend with safety features

**Core Tasks:**

1. ✅ **Create `SqliteCacheBackend` class**
   - Database initialization and schema creation
   - Connection lifecycle management
   - Schema migration framework
   - Concurrent write safety (busy handler, WAL mode)
   - Platform-specific configuration

2. ✅ **Enhanced Schema with Versioning**
   ```sql
   -- Version tracking for migrations
   CREATE TABLE schema_version (
       version INTEGER PRIMARY KEY,
       applied_at REAL NOT NULL,
       description TEXT
   );

   -- Full-text search index (FTS5)
   CREATE VIRTUAL TABLE symbols_fts USING fts5(
       name, kind, usr UNINDEXED,
       content=symbols,
       content_rowid=rowid
   );

   -- Metadata with vacuum tracking
   INSERT INTO cache_metadata VALUES
       ('last_vacuum', '0', strftime('%s', 'now'));
   ```

3. ✅ **Connection Management**
   ```python
   class SqliteCacheBackend:
       def __init__(self, db_path: Path):
           self.conn = sqlite3.connect(
               str(db_path),
               timeout=30.0,              # Wait for locks
               isolation_level=None,      # Manual transactions
               check_same_thread=False    # Multi-thread support
           )
           self.conn.execute("PRAGMA journal_mode = WAL")
           self.conn.set_busy_handler(self._busy_handler)
           self._check_schema_version()
   ```

4. ✅ **Migration Framework**
   - Create `mcp_server/migrations/` directory
   - Migration script runner
   - Version tracking
   - Rollback capability

**Deliverables:**
- `sqlite_cache_backend.py` (600 lines, +100 for safety)
- `cache_migration.py` (250 lines, +50 for backup)
- `migrations/001_initial_schema.sql` (150 lines)
- Modified `cache_manager.py` (50 lines)
- Unit tests (300 lines)

**Success Criteria:**
- ✅ All unit tests pass
- ✅ Schema migration works (v0 → v1)
- ✅ Concurrent write tests pass
- ✅ Platform tests pass (Windows, Linux)

---

### Phase 2: Integration & Testing (Week 1-2, Days 5-10)

**Goal:** Integrate with CppAnalyzer, ensure production readiness

**Core Tasks:**

1. ✅ **Full Integration**
   - Integrate with `CppAnalyzer._load_cache()`
   - Integrate with `CppAnalyzer._save_cache()`
   - Feature flag: `CLANG_INDEX_USE_SQLITE=1`
   - Automatic migration on first run

2. ✅ **Performance Benchmarking**
   ```bash
   # Comprehensive benchmark suite
   python tests/benchmark_cache.py --backend sqlite --symbols 10K,50K,100K,500K
   python tests/benchmark_cache.py --compare json vs sqlite
   python tests/benchmark_fts5.py  # Test FTS5 vs LIKE searches
   ```

3. ✅ **Migration Testing**
   - Test small projects (1K symbols)
   - Test medium projects (50K symbols)
   - Test large projects (500K symbols)
   - Test migration verification
   - Test rollback scenarios

4. ✅ **Concurrent Access Testing**
   - Multiple analyzer instances
   - Interrupted writes
   - Database locking scenarios
   - Recovery from corruption

5. ✅ **Platform Testing**
   - Windows (file locking, paths)
   - Linux (standard case)
   - macOS (if available)
   - Network filesystem (warning mode)

**Deliverables:**
- Integration tests (400 lines)
- Benchmark suite (250 lines)
- Migration verification (150 lines)
- Platform test suite (200 lines)
- Performance report document

**Success Criteria:**
- ✅ All tests pass on all platforms
- ✅ Performance meets targets
- ✅ Migration preserves data integrity
- ✅ Concurrent writes handled correctly

---

### Phase 3: Optimization & Polish (Week 2-3, Days 11-18)

**Goal:** Maximize performance, add production features

**Core Tasks:**

1. ✅ **Full-Text Search (FTS5)**
   - Implement FTS5 for symbol name searches
   - Create triggers to keep FTS index synced
   - Add FTS5-based search functions
   - Benchmark improvement (expect 20x speedup)

2. ✅ **Query Performance Monitoring**
   ```python
   class SqliteCacheBackend:
       def get_query_stats(self) -> Dict[str, Any]:
           """Return query performance statistics"""
           return {
               'search_symbols': {'count': 1234, 'avg_ms': 2.1},
               'load_by_usr': {'count': 5678, 'avg_ms': 0.3},
               ...
           }
   ```

3. ✅ **Database Maintenance**
   - Auto-vacuum (weekly)
   - Database size warnings
   - Integrity checks on startup
   - Optimization (ANALYZE)

4. ✅ **Prepared Statements for Hot Paths**
   ```python
   def _prepare_statements(self):
       """Pre-compile frequently used queries"""
       self._stmts = {
           'get_by_name': "SELECT * FROM symbols WHERE name = ?",
           'get_by_usr': "SELECT * FROM symbols WHERE usr = ?",
           'fts_search': "SELECT * FROM symbols WHERE usr IN (SELECT usr FROM symbols_fts WHERE name MATCH ?)"
       }
   ```

5. ✅ **Incremental Update Optimization**
   - Batch updates for modified files
   - Efficient deletion
   - Transaction management

**Deliverables:**
- FTS5 implementation (150 lines)
- Query profiling (100 lines)
- Maintenance utilities (150 lines)
- Performance tuning guide

**Success Criteria:**
- ✅ FTS5 searches < 5ms for 100K symbols
- ✅ Query profiling works
- ✅ Auto-vacuum reduces DB size
- ✅ Incremental updates < 50ms per file

---

### Phase 4: Production Readiness (Week 3, Days 19-24)

**Goal:** Documentation, safety, deployment preparation

**Core Tasks:**

1. ✅ **Comprehensive Documentation**
   - Architecture documentation (✓ this doc)
   - API documentation (docstrings)
   - User migration guide
   - Troubleshooting guide
   - Platform-specific notes

2. ✅ **Safety Mechanisms**
   - Automatic backup before migration
   - Integrity verification
   - Auto-repair for corruption
   - Rollback capability
   - Error recovery

3. ✅ **Monitoring & Diagnostics**
   ```python
   # Cache statistics tool
   python -m mcp_server.tools.cache_stats

   # Output:
   # Cache Statistics:
   # ├─ Backend: SQLite
   # ├─ Database size: 32.5 MB
   # ├─ Symbol count: 98,432
   # ├─ Last vacuum: 2 days ago
   # ├─ Query stats: 2.1ms avg
   # └─ Health: ✓ Good
   ```

4. ✅ **Deployment Tools**
   - Pre-migration script for large projects
   - Verification script
   - Rollback script
   - Migration progress reporting

**Deliverables:**
- Complete documentation (2000+ lines)
- Safety utilities (300 lines)
- Diagnostic tools (200 lines)
- Deployment guide

**Success Criteria:**
- ✅ All documentation complete and reviewed
- ✅ Safety mechanisms tested
- ✅ Rollback works
- ✅ Ready for production deployment

---

## Updated Database Schema

### Core Schema with Improvements

```sql
-- Schema version tracking (NEW)
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    description TEXT
);

INSERT INTO schema_version VALUES (1, strftime('%s', 'now'), 'Initial schema with FTS5');

-- Main symbols table (UNCHANGED)
CREATE TABLE symbols (
    usr TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    column INTEGER NOT NULL,
    signature TEXT DEFAULT '',
    is_project BOOLEAN NOT NULL,
    namespace TEXT DEFAULT '',
    access TEXT DEFAULT 'public',
    parent_class TEXT DEFAULT '',
    base_classes TEXT DEFAULT '[]',
    calls TEXT DEFAULT '[]',
    called_by TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- Indexes (ENHANCED)
CREATE INDEX idx_symbol_name ON symbols(name);
CREATE INDEX idx_symbol_kind ON symbols(kind);
CREATE INDEX idx_symbol_file ON symbols(file);
CREATE INDEX idx_symbol_parent ON symbols(parent_class);
CREATE INDEX idx_symbol_namespace ON symbols(namespace);
CREATE INDEX idx_symbol_project ON symbols(is_project);
CREATE INDEX idx_name_kind_project ON symbols(name, kind, is_project);
CREATE INDEX idx_symbol_updated ON symbols(updated_at);  -- NEW: For incremental updates

-- Full-text search (NEW)
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name,
    kind,
    usr UNINDEXED,
    content=symbols,
    content_rowid=rowid
);

-- Triggers to keep FTS in sync (NEW)
CREATE TRIGGER symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, kind, usr)
    VALUES (new.rowid, new.name, new.kind, new.usr);
END;

CREATE TRIGGER symbols_ad AFTER DELETE ON symbols BEGIN
    DELETE FROM symbols_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER symbols_au AFTER UPDATE ON symbols BEGIN
    UPDATE symbols_fts SET name = new.name, kind = new.kind
    WHERE rowid = old.rowid;
END;

-- File metadata (ENHANCED)
CREATE TABLE file_metadata (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    compile_args_hash TEXT,
    indexed_at REAL NOT NULL,
    symbol_count INTEGER DEFAULT 0
);

CREATE INDEX idx_file_indexed ON file_metadata(indexed_at);  -- NEW

-- Cache metadata (ENHANCED)
CREATE TABLE cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Initial metadata
INSERT INTO cache_metadata VALUES
    ('version', '"3.0"', strftime('%s', 'now')),
    ('include_dependencies', 'false', strftime('%s', 'now')),
    ('indexed_file_count', '0', strftime('%s', 'now')),
    ('last_vacuum', '0', strftime('%s', 'now'));  -- NEW: Track maintenance

-- Header tracker (UNCHANGED)
CREATE TABLE header_tracker (
    header_path TEXT PRIMARY KEY,
    processed_by TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    compile_commands_hash TEXT,
    processed_at REAL NOT NULL
);

-- Parse errors (UNCHANGED)
CREATE TABLE parse_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    file_hash TEXT NOT NULL,
    compile_args_hash TEXT,
    retry_count INTEGER DEFAULT 0,
    timestamp REAL NOT NULL
);

CREATE INDEX idx_error_file ON parse_errors(file_path);
CREATE INDEX idx_error_timestamp ON parse_errors(timestamp);
```

---

## Critical Features Implementation

### 1. Schema Migration Framework

```python
# mcp_server/schema_migrations.py

class SchemaMigration:
    """Manages database schema migrations"""

    CURRENT_VERSION = 1

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_current_version(self) -> int:
        """Get current schema version"""
        try:
            cursor = self.conn.execute("SELECT MAX(version) FROM schema_version")
            version = cursor.fetchone()[0]
            return version if version else 0
        except sqlite3.OperationalError:
            return 0

    def needs_migration(self) -> bool:
        """Check if migration is needed"""
        current = self.get_current_version()
        return current < self.CURRENT_VERSION

    def migrate(self):
        """Apply pending migrations"""
        current = self.get_current_version()

        if current > self.CURRENT_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is newer than "
                f"supported version {self.CURRENT_VERSION}"
            )

        for version in range(current + 1, self.CURRENT_VERSION + 1):
            self._apply_migration(version)

    def _apply_migration(self, version: int):
        """Apply a single migration"""
        migration_file = Path(__file__).parent / "migrations" / f"{version:03d}_*.sql"

        # Find migration file
        files = list(migration_file.parent.glob(f"{version:03d}_*.sql"))
        if not files:
            raise FileNotFoundError(f"Migration file not found for version {version}")

        migration_file = files[0]

        diagnostics.info(f"Applying schema migration: {migration_file.name}")

        with open(migration_file) as f:
            sql = f.read()

        with self.conn:
            self.conn.executescript(sql)
            self.conn.execute(
                "INSERT INTO schema_version VALUES (?, ?, ?)",
                (version, time.time(), migration_file.stem)
            )

        diagnostics.info(f"✓ Migration {version} applied successfully")
```

### 2. Concurrent Write Safety

```python
# mcp_server/sqlite_cache_backend.py

class SqliteCacheBackend:
    def __init__(self, db_path: Path):
        self.db_path = db_path

        # Configure for concurrent access
        self.conn = sqlite3.connect(
            str(db_path),
            timeout=30.0,              # Wait up to 30s for locks
            isolation_level=None,      # Manual transaction control
            check_same_thread=False    # Allow multi-threaded access
        )

        # Enable WAL mode for concurrent reads during writes
        self.conn.execute("PRAGMA journal_mode = WAL")

        # Configure for reliability
        self.conn.execute("PRAGMA synchronous = NORMAL")  # Balance safety and speed

        # Set busy handler for retries
        self.conn.set_busy_handler(self._busy_handler)

        # Platform-specific configuration
        self._configure_platform()

    def _busy_handler(self, retry_count: int) -> bool:
        """
        Called when database is locked.
        Implements exponential backoff.
        """
        if retry_count < 20:
            # Exponential backoff up to 1 second
            sleep_time = 0.001 * (2 ** min(retry_count, 10))
            time.sleep(sleep_time)
            return True  # Retry
        return False  # Give up

    def _configure_platform(self):
        """Platform-specific SQLite configuration"""
        if sys.platform == 'win32':
            # Windows: More conservative locking
            pass  # WAL mode handles this

        # Detect network filesystem
        if self._is_network_fs():
            diagnostics.warning(
                "Cache on network filesystem detected. "
                "Performance may be degraded."
            )
            # Disable WAL mode (not safe on network FS)
            self.conn.execute("PRAGMA journal_mode = DELETE")

    def _is_network_fs(self) -> bool:
        """Detect if database is on network filesystem"""
        if sys.platform == 'win32':
            return str(self.db_path).startswith('\\\\')  # UNC path
        else:
            # Check if mount point is network filesystem
            # Simplified check - could be more sophisticated
            return False

    def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
        """
        Batch insert/update symbols with retry logic.
        Implements atomic transaction.
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                with self.conn:  # Automatic transaction
                    self.conn.executemany(
                        """
                        INSERT OR REPLACE INTO symbols (
                            usr, name, kind, file, line, column, signature,
                            is_project, namespace, access, parent_class,
                            base_classes, calls, called_by, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [self._symbol_to_tuple(s) for s in symbols]
                    )
                return len(symbols)

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    # Database locked, retry
                    sleep_time = 1.0 * (attempt + 1)
                    diagnostics.warning(f"Database locked, retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                    continue
                raise

        return 0
```

### 3. Full-Text Search (FTS5)

```python
# mcp_server/sqlite_cache_backend.py

class SqliteCacheBackend:
    def search_symbols_fts(self, pattern: str, kind: str = None,
                           project_only: bool = True) -> List[SymbolInfo]:
        """
        Fast full-text search using FTS5.

        Pattern can be:
        - Exact: "Vector"
        - Prefix: "Vec*"
        - Fuzzy: "Vctor" (not supported by FTS5)

        Performance: 2-5ms for 100K symbols (vs 50ms with LIKE)
        """
        query = """
            SELECT s.* FROM symbols s
            WHERE s.usr IN (
                SELECT usr FROM symbols_fts
                WHERE name MATCH ?
            )
        """

        params = [pattern]

        if kind:
            query += " AND s.kind = ?"
            params.append(kind)

        if project_only:
            query += " AND s.is_project = 1"

        cursor = self.conn.execute(query, params)
        return [SymbolInfo(**dict(row)) for row in cursor]

    def search_symbols_regex(self, pattern: str, kind: str = None,
                             project_only: bool = True) -> List[SymbolInfo]:
        """
        Regex search (fallback for complex patterns).

        Slower than FTS5 but more flexible.
        Performance: 10-50ms for 100K symbols
        """
        query = "SELECT * FROM symbols WHERE name REGEXP ?"
        params = [pattern]

        if kind:
            query += " AND kind = ?"
            params.append(kind)

        if project_only:
            query += " AND is_project = 1"

        cursor = self.conn.execute(query, params)
        return [SymbolInfo(**dict(row)) for row in cursor]
```

---

## Migration Path

### Automatic Migration (Transparent to User)

```python
# mcp_server/cache_manager.py

class CacheManager:
    def __init__(self, project_root: Path):
        self.cache_dir = self._get_cache_dir()

        # Feature flag
        use_sqlite = os.getenv('CLANG_INDEX_USE_SQLITE', '1') == '1'

        if use_sqlite:
            db_path = self.cache_dir / "symbols.db"

            # Auto-migrate if needed
            if not db_path.exists():
                self._maybe_migrate_from_json()

            try:
                self.backend = SqliteCacheBackend(db_path)
                diagnostics.info("Using SQLite cache")
            except Exception as e:
                diagnostics.warning(f"SQLite cache unavailable: {e}")
                diagnostics.info("Falling back to JSON cache")
                self.backend = JsonCacheBackend(self.cache_dir)
        else:
            diagnostics.info("Using JSON cache (SQLite disabled)")
            self.backend = JsonCacheBackend(self.cache_dir)

    def _maybe_migrate_from_json(self):
        """Automatically migrate JSON cache if it exists"""
        json_cache = self.cache_dir / "cache_info.json"
        db_path = self.cache_dir / "symbols.db"
        migration_marker = self.cache_dir / ".migrated_to_sqlite"

        # Already migrated?
        if migration_marker.exists():
            return

        # No JSON cache to migrate?
        if not json_cache.exists():
            migration_marker.touch()
            return

        # Migrate
        diagnostics.info("Migrating cache to SQLite (one-time operation)...")

        try:
            # Create backup
            backup = json_cache.with_suffix('.json.backup')
            shutil.copy2(json_cache, backup)

            # Perform migration
            from .cache_migration import migrate_json_to_sqlite
            migrate_json_to_sqlite(json_cache, db_path)

            # Verify
            from .cache_migration import verify_migration
            if verify_migration(json_cache, db_path):
                migration_marker.touch()
                diagnostics.info("✓ Migration complete")
            else:
                raise RuntimeError("Migration verification failed")

        except Exception as e:
            diagnostics.error(f"Migration failed: {e}")
            diagnostics.info("Falling back to JSON cache")
            if db_path.exists():
                db_path.unlink()
```

---

## Testing Strategy

### Unit Tests (95% Coverage Target)

```python
# tests/test_sqlite_cache_backend.py

class TestSqliteCacheBackend:
    def test_schema_creation(self):
        """Test database schema creation"""
        backend = SqliteCacheBackend(":memory:")

        # Check tables exist
        tables = backend.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]

        assert 'symbols' in table_names
        assert 'file_metadata' in table_names
        assert 'cache_metadata' in table_names
        assert 'schema_version' in table_names
        assert 'symbols_fts' in table_names  # FTS5

    def test_concurrent_writes(self):
        """Test concurrent write safety"""
        backend = SqliteCacheBackend("/tmp/test_concurrent.db")

        def write_symbols(worker_id):
            symbols = [
                SymbolInfo(
                    name=f"Symbol_{worker_id}_{i}",
                    kind="class",
                    file=f"/test_{worker_id}.cpp",
                    line=i,
                    column=0,
                    usr=f"usr_{worker_id}_{i}"
                )
                for i in range(100)
            ]
            backend.save_symbols_batch(symbols)

        # 5 workers writing concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(write_symbols, i) for i in range(5)]
            [f.result() for f in futures]

        # Verify all symbols saved
        total = backend.count_symbols()
        assert total == 500

    def test_fts5_search_performance(self):
        """Test FTS5 search performance"""
        backend = SqliteCacheBackend(":memory:")

        # Insert 10K symbols
        symbols = [
            SymbolInfo(
                name=f"TestClass{i}",
                kind="class",
                file="/test.cpp",
                line=i,
                column=0,
                usr=f"usr_{i}"
            )
            for i in range(10000)
        ]
        backend.save_symbols_batch(symbols)

        # Measure FTS5 search
        start = time.perf_counter()
        results = backend.search_symbols_fts("TestClass*")
        elapsed = time.perf_counter() - start

        assert len(results) == 10000
        assert elapsed < 0.01  # Should be < 10ms

    def test_schema_migration(self):
        """Test schema migration from v0 to v1"""
        # Create old database (no schema_version table)
        db_path = Path("/tmp/test_migration.db")
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE symbols (usr TEXT PRIMARY KEY, name TEXT)")
        conn.close()

        # Open with migration support
        backend = SqliteCacheBackend(db_path)

        # Check schema_version table exists
        cursor = backend.conn.execute(
            "SELECT version FROM schema_version"
        )
        version = cursor.fetchone()[0]
        assert version == 1
```

---

## Rollout Plan

### Week 1-2: Alpha Testing (Internal)

- Deploy to development projects
- Feature flag: `CLANG_INDEX_USE_SQLITE=1` (opt-in)
- Monitor for issues
- Gather performance metrics

### Week 3: Beta Testing

- Deploy to all internal projects
- Feature flag: Default ON, can opt-out
- Monitor crash reports
- Collect user feedback

### Week 4: General Availability

- Deploy to all users
- Feature flag: SQLite default, JSON fallback
- Monitor adoption rate
- Address reported issues

### Week 8+: Cleanup

- Remove JSON backend (if stable for 1 month)
- Remove feature flags
- Archive JSON-related code
- Update documentation

---

## Risk Mitigation

### Automatic Rollback Triggers

1. **High Error Rate:** SQLite error rate > 5% → Fallback to JSON
2. **Performance Regression:** Startup time > 2x baseline → Rollback
3. **Data Loss:** Symbol count mismatch > 1% → Immediate rollback

### Manual Rollback

```bash
# Disable SQLite globally
export CLANG_INDEX_USE_SQLITE=0

# Force JSON backend
python -m mcp_server.tools.force_json_cache --project /path/to/project
```

---

## Summary

### What's Different from Original Design?

✅ **Schema migration framework** - Future-proof
✅ **Concurrent write safety** - Production-ready
✅ **FTS5 full-text search** - 20x faster searches
✅ **Query performance monitoring** - Debugging capability
✅ **Platform-specific config** - Windows/Unix/Network FS

### Updated Timeline

- **Week 1:** Foundation + safety features (4 days)
- **Week 1-2:** Integration + testing (6 days)
- **Week 2-3:** Optimization + FTS5 (7 days)
- **Week 3:** Production readiness (6 days)

**Total: 3.5 weeks**

### Ready to Implement?

✅ **Design approved** with improvements
✅ **Architecture reviewed** and validated
✅ **Critical issues addressed**
✅ **Test plan comprehensive**
✅ **Rollout strategy defined**

**Next Steps:**

1. Create feature branch: `feature/sqlite-cache-v3`
2. Set up task tracking (GitHub issues/project)
3. Begin Phase 1 implementation
4. Weekly progress reviews

---

## Questions for Final Approval

1. ✅ Is the 3.5-week timeline acceptable?

2. ✅ Should we include FTS5 in v3.0 or defer to v3.1?
   - **Recommendation:** Include in v3.0 (big performance win, low risk)

3. ⚠️ Should we support network filesystems?
   - **Recommendation:** Support with warning (disable WAL mode)

4. ⚠️ Should we add telemetry for adoption tracking?
   - **Recommendation:** Defer to v3.1 (privacy concerns)

5. ✅ Platform support: Windows, Linux, macOS?
   - **Recommendation:** All three (test matrix included)

---

**Status:** 🟢 Ready for Implementation

**Approver Signature:** _________________ Date: _________
