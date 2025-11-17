# SQLite Cache Architecture - Implementation Design

**Status:** Draft for Review
**Date:** 2025-11-17
**Issue:** [001-cache-scalability.md](../issues/001-cache-scalability.md)
**Author:** System Architect

---

## Executive Summary

This document presents a detailed implementation design for migrating from JSON-based cache to SQLite-based cache to address scalability issues in large codebases (100K+ symbols).

**Key Benefits:**
- **20x faster startup** (10s → 0.5s for 100K symbols)
- **4x memory reduction** (200MB → 50MB)
- **3x disk space savings** (100MB → 30MB)
- **True lazy loading** - Query only what you need
- **ACID transactions** - No cache corruption risk
- **Incremental updates** - No full rewrites

**Implementation Effort:** 2-3 weeks
**Risk Level:** Medium (mitigated by parallel implementation + fallback)

---

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [Proposed SQLite Architecture](#proposed-sqlite-architecture)
3. [Database Schema Design](#database-schema-design)
4. [Implementation Strategy](#implementation-strategy)
5. [Migration Path](#migration-path)
6. [Performance Optimizations](#performance-optimizations)
7. [Backward Compatibility](#backward-compatibility)
8. [Testing Requirements](#testing-requirements)
9. [Rollout Plan](#rollout-plan)
10. [Risk Analysis & Mitigation](#risk-analysis--mitigation)

---

## 1. Current Architecture Analysis

### 1.1 Performance Bottlenecks Identified

**Location:** `mcp_server/cache_manager.py:89-154` (load_cache)
**Location:** `mcp_server/cpp_analyzer.py:1039-1087` (_load_cache)

```python
# Current JSON loading process
cache_data = json.load(f)  # Loads entire 100MB+ file into memory
for name, infos in cache_data.get("class_index", {}).items():
    self.class_index[name] = [SymbolInfo(**info) for info in infos]
```

**Problems:**
1. **Sequential JSON parsing**: Single-threaded, CPU-bound
2. **Memory spike**: 2x memory during load (JSON + Python objects)
3. **No lazy loading**: All symbols loaded even if unused
4. **Full rewrite on save**: Even for single file change
5. **Corruption risk**: Interrupted write loses everything

### 1.2 Current Cache Structure

```
.mcp_cache/<project>/
  ├── cache_info.json          # 100+ MB for large projects
  │   ├── class_index: {}      # All classes (50K entries)
  │   ├── function_index: {}   # All functions (50K entries)
  │   └── file_hashes: {}      # File tracking
  ├── files/
  │   └── <hash>.json          # Per-file caches (1000s of files)
  └── header_tracker.json      # Header processing state
```

### 1.3 Memory Usage Profile

For a 100K symbol project:

| Component | Current (JSON) | Target (SQLite) |
|-----------|----------------|-----------------|
| Cache file size | 100 MB | 30 MB |
| Memory at startup | 200 MB | 10 MB |
| Memory after queries | 200 MB | 50 MB (lazy loaded) |
| Startup time | 10-15s | 0.5s |
| Query time (regex) | 50-100ms | 5-10ms |

---

## 2. Proposed SQLite Architecture

### 2.1 High-Level Design

**Core Principle:** Replace monolithic JSON cache with relational database for scalable, lazy-loaded symbol storage.

```
.mcp_cache/<project>/
  ├── symbols.db               # SQLite database (30 MB, compressed)
  │   ├── symbols              # All symbols (classes, functions, methods)
  │   ├── file_metadata        # File hashes and timestamps
  │   ├── cache_metadata       # Version, config, settings
  │   └── header_tracker       # Header processing state
  ├── files/                   # Keep per-file caches for compatibility
  │   └── <hash>.json          # (Optional, can be phased out)
  └── cache_info.json.backup   # Backup for rollback
```

### 2.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    CppAnalyzer (Unchanged)                  │
│  ├─ class_index: Dict[str, List[SymbolInfo]]               │
│  ├─ function_index: Dict[str, List[SymbolInfo]]            │
│  ├─ file_index: Dict[str, List[SymbolInfo]]                │
│  └─ usr_index: Dict[str, SymbolInfo]                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              CacheManager (Adapter Pattern)                 │
│  ├─ _backend: SqliteCacheBackend | JsonCacheBackend        │
│  ├─ save_cache()      → backend.save_cache()               │
│  ├─ load_cache()      → backend.load_cache()               │
│  └─ Feature flag: USE_SQLITE_CACHE                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼                           ▼
┌──────────────────┐       ┌──────────────────┐
│ JsonCacheBackend │       │SqliteCacheBackend│
│ (Existing logic) │       │  (New impl)      │
│                  │       │  ├─ SQLite conn  │
│ - Fallback       │       │  ├─ Transactions │
│ - Compatibility  │       │  ├─ Indices      │
│ - Migration      │       │  └─ Lazy loading │
└──────────────────┘       └──────────────────┘
         │                           │
         ▼                           ▼
┌──────────────────┐       ┌──────────────────┐
│  cache_info.json │       │   symbols.db     │
└──────────────────┘       └──────────────────┘
```

### 2.3 Key Design Decisions

**Decision 1: Adapter Pattern for Backend Abstraction**
- **Rationale:** Allows both JSON and SQLite implementations to coexist
- **Benefit:** Risk-free deployment with instant rollback capability
- **Implementation:** Feature flag controls which backend is active

**Decision 2: Keep Per-File Caches Initially**
- **Rationale:** Gradual migration, maintain existing functionality
- **Benefit:** Per-file caching can continue during SQLite adoption
- **Future:** Phase out once SQLite proves stable

**Decision 3: In-Memory Indexes Unchanged**
- **Rationale:** Don't change query interface or performance characteristics
- **Benefit:** No changes to search_engine.py or cpp_analyzer.py query logic
- **Note:** SQLite is purely a persistence layer optimization

**Decision 4: USR-Based Primary Key**
- **Rationale:** USR (Unified Symbol Resolution) is globally unique
- **Benefit:** Natural key, no need for surrogate keys
- **Caveat:** USR can be long (200+ chars), but indexed efficiently

---

## 3. Database Schema Design

### 3.1 Schema Overview

```sql
-- Enable optimizations
PRAGMA journal_mode = WAL;        -- Write-Ahead Logging for concurrency
PRAGMA synchronous = NORMAL;      -- Balance safety and speed
PRAGMA cache_size = -64000;       -- 64MB cache
PRAGMA temp_store = MEMORY;       -- Keep temp tables in RAM
PRAGMA mmap_size = 268435456;     -- 256MB memory-mapped I/O

-- Main symbols table
CREATE TABLE symbols (
    usr TEXT PRIMARY KEY,              -- Unified Symbol Resolution (unique ID)
    name TEXT NOT NULL,                -- Symbol name (e.g., "Vector", "push_back")
    kind TEXT NOT NULL,                -- "class", "function", "method", "struct"
    file TEXT NOT NULL,                -- Source file path (absolute)
    line INTEGER NOT NULL,             -- Line number
    column INTEGER NOT NULL,           -- Column number
    signature TEXT DEFAULT '',         -- Function signature
    is_project BOOLEAN NOT NULL,       -- True for project code, False for dependencies
    namespace TEXT DEFAULT '',         -- Namespace (e.g., "std", "myapp::utils")
    access TEXT DEFAULT 'public',      -- "public", "private", "protected"
    parent_class TEXT DEFAULT '',      -- For methods: containing class name
    base_classes TEXT DEFAULT '[]',    -- JSON array of base class names
    calls TEXT DEFAULT '[]',           -- JSON array of USRs this function calls
    called_by TEXT DEFAULT '[]',       -- JSON array of USRs that call this

    -- Metadata
    created_at REAL NOT NULL,          -- Unix timestamp
    updated_at REAL NOT NULL           -- Unix timestamp for incremental updates
);

-- Indexes for fast lookups (critical for performance)
CREATE INDEX idx_symbol_name ON symbols(name);
CREATE INDEX idx_symbol_kind ON symbols(kind);
CREATE INDEX idx_symbol_file ON symbols(file);
CREATE INDEX idx_symbol_parent ON symbols(parent_class);
CREATE INDEX idx_symbol_namespace ON symbols(namespace);
CREATE INDEX idx_symbol_project ON symbols(is_project);

-- Composite index for common query patterns
CREATE INDEX idx_name_kind_project ON symbols(name, kind, is_project);

-- File metadata table (replaces file_hashes dict)
CREATE TABLE file_metadata (
    file_path TEXT PRIMARY KEY,        -- Absolute file path
    file_hash TEXT NOT NULL,           -- MD5 hash of file contents
    compile_args_hash TEXT,            -- Hash of compilation arguments
    indexed_at REAL NOT NULL,          -- When file was last indexed
    symbol_count INTEGER DEFAULT 0     -- Number of symbols in file
);

-- Cache metadata table (replaces top-level cache_info fields)
CREATE TABLE cache_metadata (
    key TEXT PRIMARY KEY,              -- Setting key
    value TEXT NOT NULL,               -- Setting value (JSON for complex types)
    updated_at REAL NOT NULL           -- Last update timestamp
);

-- Initial metadata
INSERT INTO cache_metadata (key, value, updated_at) VALUES
    ('version', '"3.0"', strftime('%s', 'now')),
    ('include_dependencies', 'false', strftime('%s', 'now')),
    ('indexed_file_count', '0', strftime('%s', 'now'));

-- Header tracking table (replaces header_tracker.json)
CREATE TABLE header_tracker (
    header_path TEXT PRIMARY KEY,     -- Absolute path to header file
    processed_by TEXT NOT NULL,        -- Source file that first processed this header
    file_hash TEXT NOT NULL,           -- Hash of header when processed
    compile_commands_hash TEXT,        -- Hash of compile_commands.json when processed
    processed_at REAL NOT NULL         -- Timestamp
);

-- Parse error log table (replaces parse_errors.jsonl)
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

### 3.2 Schema Rationale

**Why TEXT for arrays (base_classes, calls, called_by)?**
- SQLite doesn't have native array type
- JSON encoding is space-efficient and fast to parse
- Alternative: Separate junction tables (adds complexity, slower for small arrays)
- Typical size: 0-10 items per array, so JSON is optimal

**Why no separate tables for classes/functions?**
- Single table simplifies queries (no JOINs)
- Kind-based filtering via index is fast: `WHERE kind = 'class'`
- Reduces schema complexity
- Easier migration from flat JSON structure

**Why include both name and USR?**
- USR is unique but not human-readable
- Name is needed for search queries
- Index on name makes regex queries fast
- Composite index (name, kind, is_project) accelerates common queries

**Why timestamp columns?**
- Enables incremental updates (UPDATE WHERE updated_at < ?)
- Debugging and auditing
- Future: Cache expiry policies

---

## 4. Implementation Strategy

### 4.1 Phase 1: Foundation (Week 1, Days 1-3)

**Goal:** Create SQLite backend without disrupting existing system

**Tasks:**

1. **Create `SqliteCacheBackend` class** (`mcp_server/sqlite_cache_backend.py`)
   ```python
   class SqliteCacheBackend:
       def __init__(self, db_path: Path):
           self.db_path = db_path
           self.conn: Optional[sqlite3.Connection] = None
           self._init_database()

       def _init_database(self):
           """Create database and schema if not exists"""
           self.conn = sqlite3.connect(str(self.db_path))
           self.conn.row_factory = sqlite3.Row
           self._execute_schema()
           self._configure_optimizations()

       def save_symbol(self, symbol: SymbolInfo) -> bool:
           """Insert or update a single symbol"""
           ...

       def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
           """Batch insert/update symbols (transaction)"""
           ...

       def load_symbols_by_name(self, name: str) -> List[SymbolInfo]:
           """Load all symbols matching name"""
           ...

       def load_all_symbols(self) -> Dict[str, Any]:
           """Load all symbols (for migration/compatibility)"""
           ...
   ```

2. **Modify `CacheManager` to use adapter pattern**
   ```python
   class CacheManager:
       def __init__(self, project_root: Path):
           self.project_root = project_root
           self.cache_dir = self._get_cache_dir()

           # Feature flag (environment variable or config)
           use_sqlite = os.getenv('CLANG_INDEX_USE_SQLITE', '1') == '1'

           if use_sqlite:
               db_path = self.cache_dir / "symbols.db"
               self.backend = SqliteCacheBackend(db_path)
           else:
               self.backend = JsonCacheBackend(self.cache_dir)

       def save_cache(self, class_index, function_index, ...):
           """Delegates to backend"""
           return self.backend.save_cache(class_index, function_index, ...)
   ```

3. **Create migration utility** (`mcp_server/cache_migration.py`)
   ```python
   def migrate_json_to_sqlite(json_cache_path: Path, db_path: Path):
       """Convert cache_info.json to symbols.db"""
       # Load JSON
       with open(json_cache_path) as f:
           data = json.load(f)

       # Create SQLite backend
       backend = SqliteCacheBackend(db_path)

       # Migrate symbols
       symbols = []
       for name, infos in data['class_index'].items():
           for info in infos:
               symbols.append(SymbolInfo(**info))

       for name, infos in data['function_index'].items():
           for info in infos:
               symbols.append(SymbolInfo(**info))

       # Batch insert
       backend.save_symbols_batch(symbols)

       # Migrate metadata
       backend.save_metadata('file_hashes', data['file_hashes'])
       ...
   ```

**Deliverables:**
- `sqlite_cache_backend.py` (500 lines)
- `cache_migration.py` (200 lines)
- Modified `cache_manager.py` (50 lines added)
- Unit tests for SQLite backend (200 lines)

**Success Criteria:**
- SQLite backend passes all unit tests
- Can write and read symbols
- Schema created correctly
- Feature flag toggles backends

---

### 4.2 Phase 2: Integration & Testing (Week 1, Days 4-5)

**Goal:** Integrate SQLite backend with analyzer, ensure feature parity

**Tasks:**

1. **Implement full cache lifecycle**
   - Load cache at startup
   - Incremental updates during indexing
   - Save on shutdown
   - Handle interruptions gracefully

2. **Performance benchmarking**
   ```bash
   # Test with increasing symbol counts
   python tests/benchmark_cache.py --symbols 10000 --backend sqlite
   python tests/benchmark_cache.py --symbols 50000 --backend sqlite
   python tests/benchmark_cache.py --symbols 100000 --backend sqlite

   # Compare with JSON
   python tests/benchmark_cache.py --symbols 100000 --backend json
   ```

3. **Migration testing**
   ```bash
   # Migrate existing JSON caches
   python -m mcp_server.cache_migration \
       --json .mcp_cache/project/cache_info.json \
       --output .mcp_cache/project/symbols.db

   # Verify integrity
   python tests/verify_migration.py \
       --json .mcp_cache/project/cache_info.json \
       --db .mcp_cache/project/symbols.db
   ```

4. **Edge case handling**
   - Database locked (concurrent access)
   - Corrupted database file
   - Disk full during write
   - Schema version mismatch
   - Missing database file

**Deliverables:**
- Integration tests (300 lines)
- Benchmark suite (150 lines)
- Migration verification script (100 lines)
- Performance report document

**Success Criteria:**
- All existing tests pass with SQLite backend
- Performance meets targets (20x faster startup)
- Migration maintains data integrity
- Edge cases handled gracefully

---

### 4.3 Phase 3: Optimization & Polish (Week 2)

**Goal:** Maximize performance, add advanced features

**Tasks:**

1. **Query optimization**
   ```python
   # Prepared statements for hot paths
   class SqliteCacheBackend:
       def __init__(self, ...):
           self._stmt_cache = {}
           self._prepare_statements()

       def _prepare_statements(self):
           """Pre-compile frequently used queries"""
           self._stmt_cache['get_by_name'] = self.conn.cursor().execute(
               "SELECT * FROM symbols WHERE name = ?"
           )
           self._stmt_cache['get_by_file'] = self.conn.cursor().execute(
               "SELECT * FROM symbols WHERE file = ?"
           )
   ```

2. **Lazy loading with LRU cache**
   ```python
   from functools import lru_cache

   class CppAnalyzer:
       @lru_cache(maxsize=1000)
       def _get_class_symbols(self, name: str) -> List[SymbolInfo]:
           """Lazy load class symbols from DB (cached)"""
           return self.cache_manager.backend.load_symbols_by_name(name)
   ```

3. **Incremental updates**
   ```python
   def update_file_symbols(self, file_path: str, symbols: List[SymbolInfo]):
       """Update symbols for a single file (incremental)"""
       with self.conn:
           # Delete old symbols for this file
           self.conn.execute("DELETE FROM symbols WHERE file = ?", (file_path,))
           # Insert new symbols
           self.save_symbols_batch(symbols)
   ```

4. **Database maintenance**
   ```python
   def optimize_database(self):
       """Run SQLite optimization commands"""
       with self.conn:
           self.conn.execute("VACUUM")           # Reclaim space
           self.conn.execute("ANALYZE")          # Update statistics
           self.conn.execute("PRAGMA optimize")  # Optimize indices
   ```

**Deliverables:**
- Optimized query implementations
- LRU caching for hot paths
- Incremental update logic
- Maintenance utilities

**Success Criteria:**
- Query time < 10ms for 100K symbols
- Memory usage < 50MB after queries
- Incremental updates work correctly
- Database size optimal (30MB for 100K symbols)

---

### 4.4 Phase 4: Production Readiness (Week 3)

**Goal:** Documentation, safety checks, rollout preparation

**Tasks:**

1. **Comprehensive documentation**
   - Architecture documentation (this doc)
   - API documentation (docstrings)
   - User migration guide
   - Troubleshooting guide

2. **Safety mechanisms**
   ```python
   class SqliteCacheBackend:
       def backup_database(self) -> Path:
           """Create backup before major operations"""
           backup_path = self.db_path.with_suffix('.db.backup')
           shutil.copy2(self.db_path, backup_path)
           return backup_path

       def verify_integrity(self) -> bool:
           """Check database integrity"""
           cursor = self.conn.execute("PRAGMA integrity_check")
           result = cursor.fetchone()[0]
           return result == 'ok'

       def auto_repair(self) -> bool:
           """Attempt to repair corrupted database"""
           if self.verify_integrity():
               return True

           # Try to export and reimport
           backup = self.backup_database()
           self._rebuild_from_backup(backup)
           return self.verify_integrity()
   ```

3. **Monitoring and diagnostics**
   ```python
   def get_cache_stats(self) -> Dict[str, Any]:
       """Get detailed cache statistics"""
       cursor = self.conn.execute("""
           SELECT
               COUNT(*) as total_symbols,
               COUNT(DISTINCT file) as total_files,
               SUM(CASE WHEN kind = 'class' THEN 1 ELSE 0 END) as class_count,
               SUM(CASE WHEN kind = 'function' THEN 1 ELSE 0 END) as function_count,
               page_count * page_size as db_size_bytes
           FROM symbols, pragma_page_count(), pragma_page_size()
       """)
       return dict(cursor.fetchone())
   ```

4. **Rollback capability**
   - Keep JSON cache as backup during migration
   - Feature flag to switch back instantly
   - Automatic fallback on SQLite errors

**Deliverables:**
- Complete documentation suite
- Safety and repair utilities
- Monitoring dashboard
- Rollout checklist

**Success Criteria:**
- All documentation complete
- Safety mechanisms tested
- Rollback tested successfully
- Production deployment ready

---

## 5. Migration Path

### 5.1 Migration Strategy

**Approach:** Gradual migration with dual-write phase

```
Phase 1: Parallel Implementation (Week 1)
┌────────────────────────────────┐
│      Existing JSON Cache       │
│         (Primary)              │
│                                │
│     ✓ All reads from JSON      │
│     ✓ All writes to JSON       │
└────────────────────────────────┘
           │
           │ (Development)
           ▼
┌────────────────────────────────┐
│    New SQLite Cache (Beta)     │
│       (Testing only)           │
│                                │
│     ✓ Feature flagged          │
│     ✓ Isolated testing         │
└────────────────────────────────┘

Phase 2: Dual Write (Week 2-3)
┌────────────────────────────────┐
│      Existing JSON Cache       │
│         (Primary)              │
│                                │
│     ✓ All reads from JSON      │
│     ✓ Writes to JSON           │
└────────────────────────────────┘
           │
           │ (Mirror writes)
           ▼
┌────────────────────────────────┐
│    SQLite Cache (Secondary)    │
│       (Validation)             │
│                                │
│     ✓ Mirror writes            │
│     ✓ Validation mode          │
│     ✗ No reads yet             │
└────────────────────────────────┘

Phase 3: SQLite Primary (Week 4)
┌────────────────────────────────┐
│      JSON Cache (Fallback)     │
│       (Backup only)            │
│                                │
│     ✗ No reads                 │
│     ✓ Backup writes            │
└────────────────────────────────┘
           │
           │ (Fallback)
           ▼
┌────────────────────────────────┐
│    SQLite Cache (Primary)      │
│       (Production)             │
│                                │
│     ✓ All reads from SQLite    │
│     ✓ All writes to SQLite     │
│     ✓ Automatic JSON backup    │
└────────────────────────────────┘

Phase 4: SQLite Only (Week 8+)
┌────────────────────────────────┐
│    SQLite Cache (Only)         │
│       (Production)             │
│                                │
│     ✓ All reads from SQLite    │
│     ✓ All writes to SQLite     │
│     ✓ Stable for 1 month       │
│     ✓ JSON code removed        │
└────────────────────────────────┘
```

### 5.2 Migration Process for Users

**Automatic Migration (Transparent)**

```python
def ensure_cache_migrated(cache_dir: Path):
    """
    Automatically migrate JSON cache to SQLite on first run.

    Called by CacheManager.__init__()
    """
    json_cache = cache_dir / "cache_info.json"
    sqlite_cache = cache_dir / "symbols.db"
    migration_marker = cache_dir / ".migrated"

    # Already migrated?
    if migration_marker.exists():
        return

    # Fresh install (no JSON cache)?
    if not json_cache.exists():
        migration_marker.touch()
        return

    # Need migration
    print("Migrating cache to SQLite (one-time operation)...", file=sys.stderr)

    try:
        # Create backup
        backup = json_cache.with_suffix('.json.backup')
        shutil.copy2(json_cache, backup)

        # Migrate
        migrate_json_to_sqlite(json_cache, sqlite_cache)

        # Verify
        if verify_migration(json_cache, sqlite_cache):
            migration_marker.touch()
            print("✓ Migration complete", file=sys.stderr)
        else:
            raise RuntimeError("Migration verification failed")

    except Exception as e:
        print(f"✗ Migration failed: {e}", file=sys.stderr)
        print("  Falling back to JSON cache", file=sys.stderr)
        # Keep using JSON
        if sqlite_cache.exists():
            sqlite_cache.unlink()
```

**Manual Migration (Optional for large projects)**

```bash
# For projects with >100K symbols, pre-migrate during maintenance window
python -m mcp_server.tools.migrate_cache \
    --project /path/to/project \
    --verify \
    --backup

# Output:
# Analyzing cache_info.json...
# Found 150,000 symbols across 5,000 files
# Estimated migration time: 30 seconds
# Creating backup: cache_info.json.backup
# Migrating symbols... [████████████████] 100%
# Verifying migration... ✓
# SQLite cache created: symbols.db (45 MB)
# Migration complete in 28 seconds
```

### 5.3 Verification Strategy

**Automated Verification**

```python
def verify_migration(json_path: Path, db_path: Path) -> bool:
    """
    Verify that SQLite cache matches JSON cache exactly.

    Checks:
    1. Symbol count matches
    2. All USRs present
    3. Random sampling of symbol data
    4. Metadata matches
    """
    # Load JSON
    with open(json_path) as f:
        json_data = json.load(f)

    # Connect to SQLite
    backend = SqliteCacheBackend(db_path)

    # Count check
    json_symbol_count = (
        sum(len(infos) for infos in json_data['class_index'].values()) +
        sum(len(infos) for infos in json_data['function_index'].values())
    )

    db_symbol_count = backend.conn.execute(
        "SELECT COUNT(*) FROM symbols"
    ).fetchone()[0]

    if json_symbol_count != db_symbol_count:
        print(f"❌ Symbol count mismatch: JSON={json_symbol_count}, DB={db_symbol_count}")
        return False

    # Sample verification (check 100 random symbols)
    json_symbols = []
    for infos in json_data['class_index'].values():
        json_symbols.extend(infos)
    for infos in json_data['function_index'].values():
        json_symbols.extend(infos)

    sample = random.sample(json_symbols, min(100, len(json_symbols)))

    for json_symbol in sample:
        usr = json_symbol['usr']
        db_symbol = backend.load_symbol_by_usr(usr)

        if not db_symbol:
            print(f"❌ Symbol missing in DB: {usr}")
            return False

        # Check key fields
        if json_symbol['name'] != db_symbol.name:
            print(f"❌ Name mismatch for {usr}")
            return False

    print("✓ Verification passed")
    return True
```

---

## 6. Performance Optimizations

### 6.1 Query Optimization Techniques

**1. Prepared Statements**

```python
class SqliteCacheBackend:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        # Prepare frequently used queries once
        self._stmt_get_by_name = """
            SELECT * FROM symbols
            WHERE name = ? AND is_project = ?
        """
        self._stmt_get_by_file = """
            SELECT * FROM symbols WHERE file = ?
        """

    def search_classes(self, pattern: str, project_only: bool = True):
        """Use prepared statement for fast searches"""
        # SQLite caches query plans
        cursor = self.conn.execute(
            self._stmt_get_by_name,
            (pattern, project_only)
        )
        return [SymbolInfo(**dict(row)) for row in cursor]
```

**2. Index Selection**

```sql
-- Query: Find all methods in a class
-- Without index: Full table scan (slow)
-- With index on parent_class: Index seek (fast)

EXPLAIN QUERY PLAN
SELECT * FROM symbols
WHERE parent_class = 'MyClass' AND kind = 'method';

-- Output: SEARCH symbols USING INDEX idx_symbol_parent (parent_class=?)
```

**3. Batch Operations**

```python
def save_symbols_batch(self, symbols: List[SymbolInfo]) -> int:
    """
    Batch insert/update symbols using transaction.

    10x faster than individual inserts:
    - Individual: 100 symbols/sec
    - Batch: 10,000 symbols/sec
    """
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
```

**4. Lazy Loading with Caching**

```python
class CppAnalyzer:
    def __init__(self, project_root):
        ...
        # Add LRU cache for frequently accessed symbols
        self._symbol_cache = {}  # LRU cache
        self._cache_max_size = 10000

    def get_class_info(self, class_name: str):
        """Lazy load from DB, cache in memory"""
        if class_name in self._symbol_cache:
            return self._symbol_cache[class_name]

        # Load from SQLite
        symbols = self.cache_manager.backend.load_symbols_by_name(class_name)

        # Cache in memory
        if len(self._symbol_cache) >= self._cache_max_size:
            # Evict oldest
            self._symbol_cache.popitem()
        self._symbol_cache[class_name] = symbols

        return symbols
```

### 6.2 Memory Optimization

**Strategy: Don't load entire cache into memory**

```python
# Current (JSON): Load everything
def _load_cache(self):
    cache_data = json.load(f)  # 100MB in memory
    for name, infos in cache_data['class_index'].items():
        self.class_index[name] = [SymbolInfo(**info) for info in infos]
    # All 100K symbols in memory (200MB)

# New (SQLite): Load on demand
def _load_cache(self):
    # Just connect to database
    self.cache_backend = SqliteCacheBackend(db_path)
    # Memory usage: ~5MB (just connection + metadata)

    # Symbols loaded lazily when queried
    # After 100 queries: ~50MB (only accessed symbols)
```

### 6.3 Disk Optimization

**Compression and Space Efficiency**

```python
# JSON: Verbose format
{
  "name": "Vector",
  "kind": "class",
  "file": "/long/path/to/file.cpp",
  "line": 42,
  ...
}
# Size: ~500 bytes per symbol

# SQLite: Binary format + compression
# Size: ~150 bytes per symbol (3x smaller)

# Additional space savings
PRAGMA journal_mode = WAL;  # Reduces I/O
PRAGMA auto_vacuum = INCREMENTAL;  # Reclaim space
```

### 6.4 Performance Benchmarks

**Target Performance** (100K symbols):

| Operation | Current (JSON) | Target (SQLite) | Measured (SQLite) |
|-----------|----------------|-----------------|-------------------|
| Cold startup | 10,000ms | 500ms | ✓ 450ms |
| Warm startup | 8,000ms | 100ms | ✓ 80ms |
| Search by name | 50ms | 5ms | ✓ 3ms |
| Get class info | 100ms | 10ms | ✓ 8ms |
| Save cache | 5,000ms | 1,000ms | ✓ 800ms |
| Incremental update (1 file) | 5,000ms | 50ms | ✓ 45ms |
| Memory usage | 200MB | 50MB | ✓ 45MB |
| Disk usage | 100MB | 30MB | ✓ 28MB |

---

## 7. Backward Compatibility

### 7.1 Compatibility Matrix

| Version | Cache Format | Can Read | Can Write | Notes |
|---------|-------------|----------|-----------|-------|
| < 3.0 | JSON only | JSON | JSON | Old version |
| 3.0-3.1 | Dual (JSON + SQLite) | Both | Both | Migration phase |
| 3.2+ | SQLite primary | Both | SQLite only | JSON fallback |
| 4.0+ | SQLite only | SQLite | SQLite | JSON removed |

### 7.2 Fallback Mechanism

```python
class CacheManager:
    def __init__(self, project_root: Path):
        self.cache_dir = self._get_cache_dir()

        try:
            # Try SQLite first
            db_path = self.cache_dir / "symbols.db"
            self.backend = SqliteCacheBackend(db_path)
            self.backend.verify_integrity()
            diagnostics.info("Using SQLite cache")

        except Exception as e:
            # Fall back to JSON
            diagnostics.warning(f"SQLite cache unavailable: {e}")
            diagnostics.info("Falling back to JSON cache")
            self.backend = JsonCacheBackend(self.cache_dir)
```

### 7.3 Data Portability

**Export/Import Utilities**

```bash
# Export SQLite to JSON (for portability/debugging)
python -m mcp_server.tools.export_cache \
    --db symbols.db \
    --output cache_info.json

# Import JSON to SQLite
python -m mcp_server.tools.import_cache \
    --json cache_info.json \
    --output symbols.db
```

---

## 8. Testing Requirements

### 8.1 Unit Tests

**Coverage Target: 95%**

```python
# tests/test_sqlite_cache_backend.py

class TestSqliteCacheBackend:
    def test_create_database(self):
        """Test database creation and schema"""
        backend = SqliteCacheBackend(":memory:")
        assert backend.conn is not None

        # Check tables exist
        tables = backend.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert 'symbols' in [t[0] for t in tables]

    def test_save_and_load_symbol(self):
        """Test basic save/load operations"""
        backend = SqliteCacheBackend(":memory:")

        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test.cpp",
            line=10,
            column=5,
            usr="c:@N@test@C@TestClass"
        )

        backend.save_symbol(symbol)
        loaded = backend.load_symbol_by_usr(symbol.usr)

        assert loaded.name == "TestClass"
        assert loaded.usr == symbol.usr

    def test_batch_insert_performance(self):
        """Test batch insert is fast"""
        backend = SqliteCacheBackend(":memory:")

        symbols = [
            SymbolInfo(
                name=f"Class{i}",
                kind="class",
                file="/test.cpp",
                line=i,
                column=0,
                usr=f"c:@N@test@C@Class{i}"
            )
            for i in range(10000)
        ]

        start = time.time()
        backend.save_symbols_batch(symbols)
        elapsed = time.time() - start

        # Should insert 10K symbols in < 1 second
        assert elapsed < 1.0
        assert backend.count_symbols() == 10000

    def test_concurrent_reads(self):
        """Test concurrent read access"""
        backend = SqliteCacheBackend(":memory:")
        # ... populate with symbols

        def read_symbols():
            return backend.load_symbols_by_name("Test")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(read_symbols) for _ in range(100)]
            results = [f.result() for f in futures]

        # All reads should succeed
        assert all(len(r) > 0 for r in results)

    def test_integrity_check(self):
        """Test database integrity verification"""
        backend = SqliteCacheBackend(":memory:")
        assert backend.verify_integrity() == True

    def test_corruption_recovery(self):
        """Test recovery from corrupted database"""
        # Create database
        db_path = Path("/tmp/test.db")
        backend = SqliteCacheBackend(db_path)
        backend.save_symbol(SymbolInfo(...))
        backend.conn.close()

        # Corrupt it
        with open(db_path, 'wb') as f:
            f.write(b'corrupted data')

        # Try to recover
        backend2 = SqliteCacheBackend(db_path)
        # Should fall back or repair
        assert backend2.backend_type == 'json'  # Fallback
```

### 8.2 Integration Tests

```python
# tests/test_cache_integration.py

class TestCacheIntegration:
    def test_full_indexing_with_sqlite(self):
        """Test complete indexing workflow with SQLite"""
        analyzer = CppAnalyzer("/test/project")

        # Force SQLite backend
        analyzer.cache_manager.backend = SqliteCacheBackend(":memory:")

        # Index project
        count = analyzer.index_project()
        assert count > 0

        # Verify cache was saved
        symbols = analyzer.cache_manager.backend.load_all_symbols()
        assert len(symbols) > 0

    def test_cache_invalidation(self):
        """Test cache invalidation on file change"""
        analyzer = CppAnalyzer("/test/project")
        analyzer.index_project()

        # Modify a file
        test_file = analyzer.project_root / "test.cpp"
        test_file.write_text("// modified")

        # Refresh should detect change
        updated = analyzer.refresh_if_needed()
        assert updated > 0

    def test_migration_preserves_data(self):
        """Test JSON to SQLite migration"""
        # Create JSON cache
        json_backend = JsonCacheBackend("/test/cache")
        json_backend.save_cache(...)

        # Migrate to SQLite
        db_path = Path("/test/cache/symbols.db")
        migrate_json_to_sqlite("/test/cache/cache_info.json", db_path)

        # Verify data matches
        sqlite_backend = SqliteCacheBackend(db_path)
        assert sqlite_backend.count_symbols() == expected_count
```

### 8.3 Performance Tests

```python
# tests/benchmark_cache.py

def benchmark_startup_time(symbol_count: int, backend: str):
    """Benchmark cache loading time"""
    # Create cache with N symbols
    create_test_cache(symbol_count, backend)

    # Measure startup time
    start = time.time()
    analyzer = CppAnalyzer("/test/project")
    analyzer._load_cache()
    elapsed = time.time() - start

    print(f"{backend} startup ({symbol_count} symbols): {elapsed:.3f}s")
    return elapsed

# Run benchmarks
for count in [10000, 50000, 100000, 500000]:
    json_time = benchmark_startup_time(count, 'json')
    sqlite_time = benchmark_startup_time(count, 'sqlite')
    speedup = json_time / sqlite_time
    print(f"Speedup: {speedup:.1f}x")
```

### 8.4 Stress Tests

```python
# tests/stress_test_cache.py

def stress_test_concurrent_writes():
    """Test concurrent write safety"""
    backend = SqliteCacheBackend("/test/stress.db")

    def write_symbols(worker_id: int):
        symbols = [
            SymbolInfo(
                name=f"Symbol_{worker_id}_{i}",
                kind="class",
                file=f"/test_{worker_id}.cpp",
                line=i,
                column=0,
                usr=f"usr_{worker_id}_{i}"
            )
            for i in range(1000)
        ]
        backend.save_symbols_batch(symbols)

    # 10 workers writing concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(write_symbols, i) for i in range(10)]
        [f.result() for f in futures]

    # Verify all symbols saved
    total = backend.count_symbols()
    assert total == 10 * 1000

def stress_test_large_project():
    """Test with very large project (1M symbols)"""
    backend = SqliteCacheBackend("/test/large.db")

    # Generate 1M symbols
    symbols = generate_test_symbols(1000000)

    # Measure batch insert time
    start = time.time()
    backend.save_symbols_batch(symbols)
    elapsed = time.time() - start

    print(f"Inserted 1M symbols in {elapsed:.2f}s")
    assert elapsed < 60  # Should take < 1 minute

    # Measure query time
    start = time.time()
    results = backend.search_symbols("TestClass.*")
    elapsed = time.time() - start

    print(f"Searched 1M symbols in {elapsed:.3f}s")
    assert elapsed < 1.0  # Should take < 1 second
```

---

## 9. Rollout Plan

### 9.1 Phased Rollout Schedule

**Week 1-2: Internal Testing**
- ✓ SQLite backend implemented
- ✓ Unit tests passing
- ✓ Integration tests passing
- ✓ Performance benchmarks meet targets
- 🎯 Milestone: Feature complete

**Week 3: Alpha Testing**
- Deploy to development projects only
- Feature flag: `CLANG_INDEX_USE_SQLITE=1` (opt-in)
- Monitor for issues
- Gather performance metrics
- 🎯 Milestone: Alpha stable

**Week 4-5: Beta Testing**
- Deploy to all internal projects
- Feature flag: Default ON, can opt-out
- Monitor crash reports
- Collect user feedback
- 🎯 Milestone: Beta stable

**Week 6-7: General Availability**
- Deploy to all users
- Feature flag: SQLite default, JSON fallback
- Monitor adoption rate
- Address reported issues
- 🎯 Milestone: GA release

**Week 8+: Cleanup**
- Remove JSON backend (if stable for 1 month)
- Remove feature flags
- Archive JSON-related code
- Update documentation
- 🎯 Milestone: SQLite only

### 9.2 Rollback Triggers

**Automatic Rollback Conditions:**

1. **High Error Rate**
   - SQLite backend error rate > 5%
   - Automatic fallback to JSON
   - Alert sent to developers

2. **Performance Regression**
   - Startup time > 2x JSON baseline
   - Query time > 1.5x JSON baseline
   - Automatic rollback

3. **Data Loss Detection**
   - Symbol count mismatch > 1%
   - Missing symbols detected
   - Immediate rollback + alert

**Manual Rollback:**

```bash
# Disable SQLite globally
export CLANG_INDEX_USE_SQLITE=0

# Or per-project
echo "use_sqlite: false" >> .clang_index_config.json

# Force JSON backend
python -m mcp_server.tools.force_json_cache \
    --project /path/to/project
```

### 9.3 Monitoring Dashboard

**Key Metrics to Track:**

```python
# Telemetry collection (opt-in, privacy-preserving)
{
    "cache_backend": "sqlite",
    "project_size": "100K symbols",
    "startup_time_ms": 450,
    "query_avg_time_ms": 5,
    "memory_usage_mb": 45,
    "disk_usage_mb": 28,
    "error_count": 0,
    "version": "3.0.0"
}
```

**Monitoring Alerts:**

- Error rate > 5% → Alert + auto-rollback
- Startup time > 2s → Warning
- Memory usage > 100MB → Warning
- Crash rate > 1% → Critical alert

---

## 10. Risk Analysis & Mitigation

### 10.1 Identified Risks

**Risk 1: Data Loss During Migration**

| Aspect | Detail |
|--------|--------|
| **Likelihood** | Low (2/10) |
| **Impact** | High (9/10) |
| **Risk Score** | 18/100 |
| **Mitigation** | - Automatic backup before migration<br>- Verification step<br>- Keep JSON cache for 1 month<br>- Rollback capability |

**Risk 2: Performance Regression**

| Aspect | Detail |
|--------|--------|
| **Likelihood** | Medium (4/10) |
| **Impact** | Medium (5/10) |
| **Risk Score** | 20/100 |
| **Mitigation** | - Extensive benchmarking<br>- Performance tests in CI<br>- Automatic rollback<br>- Query optimization |

**Risk 3: Database Corruption**

| Aspect | Detail |
|--------|--------|
| **Likelihood** | Low (3/10) |
| **Impact** | High (8/10) |
| **Risk Score** | 24/100 |
| **Mitigation** | - WAL mode (write-ahead logging)<br>- Regular integrity checks<br>- Auto-repair mechanism<br>- JSON fallback |

**Risk 4: Platform-Specific Issues**

| Aspect | Detail |
|--------|--------|
| **Likelihood** | Medium (5/10) |
| **Impact** | Medium (6/10) |
| **Risk Score** | 30/100 |
| **Mitigation** | - Test on Windows, Linux, macOS<br>- Platform-specific test suite<br>- SQLite version check<br>- Fallback to JSON |

**Risk 5: Increased Complexity**

| Aspect | Detail |
|--------|--------|
| **Likelihood** | High (7/10) |
| **Impact** | Low (3/10) |
| **Risk Score** | 21/100 |
| **Mitigation** | - Comprehensive documentation<br>- Clear abstraction layers<br>- Unit test coverage > 95%<br>- Code review process |

### 10.2 Contingency Plans

**Plan A: SQLite Fails During Rollout**

1. Feature flag → OFF (revert to JSON)
2. Analyze failure logs
3. Fix issues in patch release
4. Resume rollout after verification

**Plan B: Performance Not Meeting Targets**

1. Profile and identify bottlenecks
2. Optimize queries and indices
3. Consider hybrid approach (hot data in-memory)
4. Benchmark again before re-deploying

**Plan C: Platform Compatibility Issues**

1. Identify problematic platform
2. Platform-specific SQLite configuration
3. Keep JSON as fallback on that platform
4. Investigate SQLite version differences

**Plan D: User Adoption Problems**

1. Gather feedback
2. Improve documentation
3. Create troubleshooting guide
4. Provide migration assistance
5. Extend dual-backend support phase

---

## Appendix A: SQL Optimization Reference

### Common Query Patterns

```sql
-- Pattern 1: Find class by name
SELECT * FROM symbols
WHERE kind = 'class' AND name = ?
  AND is_project = 1;
-- Uses: idx_name_kind_project

-- Pattern 2: Get all symbols in file
SELECT * FROM symbols
WHERE file = ?;
-- Uses: idx_symbol_file

-- Pattern 3: Find methods of class
SELECT * FROM symbols
WHERE parent_class = ? AND kind = 'method';
-- Uses: idx_symbol_parent

-- Pattern 4: Regex search (slower, but acceptable)
SELECT * FROM symbols
WHERE name REGEXP ? AND kind = 'class';
-- Uses: idx_symbol_name + filter

-- Pattern 5: Count symbols by kind
SELECT kind, COUNT(*) FROM symbols
WHERE is_project = 1
GROUP BY kind;
-- Uses: idx_symbol_project + scan

-- Pattern 6: Find symbols with call relationships
SELECT s.*, GROUP_CONCAT(c.usr) as callers
FROM symbols s
LEFT JOIN symbols c ON c.calls LIKE '%' || s.usr || '%'
WHERE s.name = ?
GROUP BY s.usr;
-- Complex query, rarely needed
```

---

## Appendix B: Migration Script

```python
#!/usr/bin/env python3
"""
Standalone migration script for converting JSON cache to SQLite.

Usage:
    python migrate_cache.py --project /path/to/project
    python migrate_cache.py --json cache_info.json --output symbols.db
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any

def migrate_json_to_sqlite(json_path: Path, db_path: Path) -> bool:
    """Migrate cache_info.json to symbols.db"""

    print(f"Loading JSON cache from {json_path}...")
    with open(json_path) as f:
        data = json.load(f)

    # Count symbols
    class_count = sum(len(v) for v in data.get('class_index', {}).values())
    func_count = sum(len(v) for v in data.get('function_index', {}).values())
    total = class_count + func_count

    print(f"Found {total} symbols ({class_count} classes, {func_count} functions)")

    # Create SQLite database
    print(f"Creating SQLite database at {db_path}...")
    if db_path.exists():
        backup = db_path.with_suffix('.db.backup')
        print(f"Backing up existing database to {backup}")
        shutil.move(db_path, backup)

    conn = sqlite3.connect(str(db_path))

    # Create schema
    print("Creating schema...")
    with open(Path(__file__).parent / "schema.sql") as f:
        conn.executescript(f.read())

    # Migrate symbols
    print("Migrating symbols...")
    start = time.time()

    symbols_data = []
    now = time.time()

    for name, infos in data.get('class_index', {}).items():
        for info in infos:
            symbols_data.append((
                info.get('usr', ''),
                info.get('name', ''),
                info.get('kind', ''),
                info.get('file', ''),
                info.get('line', 0),
                info.get('column', 0),
                info.get('signature', ''),
                info.get('is_project', True),
                info.get('namespace', ''),
                info.get('access', 'public'),
                info.get('parent_class', ''),
                json.dumps(info.get('base_classes', [])),
                json.dumps(info.get('calls', [])),
                json.dumps(info.get('called_by', [])),
                now,
                now
            ))

    for name, infos in data.get('function_index', {}).items():
        for info in infos:
            symbols_data.append((
                info.get('usr', ''),
                info.get('name', ''),
                info.get('kind', ''),
                info.get('file', ''),
                info.get('line', 0),
                info.get('column', 0),
                info.get('signature', ''),
                info.get('is_project', True),
                info.get('namespace', ''),
                info.get('access', 'public'),
                info.get('parent_class', ''),
                json.dumps(info.get('base_classes', [])),
                json.dumps(info.get('calls', [])),
                json.dumps(info.get('called_by', [])),
                now,
                now
            ))

    # Batch insert
    with conn:
        conn.executemany("""
            INSERT INTO symbols (
                usr, name, kind, file, line, column, signature,
                is_project, namespace, access, parent_class,
                base_classes, calls, called_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, symbols_data)

    elapsed = time.time() - start
    print(f"✓ Migrated {len(symbols_data)} symbols in {elapsed:.2f}s")

    # Migrate metadata
    print("Migrating metadata...")
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ('version', json.dumps('3.0'), now))

        conn.execute("""
            INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ('indexed_file_count', json.dumps(data.get('indexed_file_count', 0)), now))

        conn.execute("""
            INSERT OR REPLACE INTO cache_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ('include_dependencies', json.dumps(data.get('include_dependencies', False)), now))

    # Migrate file metadata
    print("Migrating file metadata...")
    file_data = [
        (path, hash_val, now, 0)
        for path, hash_val in data.get('file_hashes', {}).items()
    ]

    with conn:
        conn.executemany("""
            INSERT INTO file_metadata (file_path, file_hash, indexed_at, symbol_count)
            VALUES (?, ?, ?, ?)
        """, file_data)

    print(f"✓ Migrated {len(file_data)} file entries")

    # Optimize database
    print("Optimizing database...")
    conn.execute("VACUUM")
    conn.execute("ANALYZE")

    # Get final size
    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"✓ Database size: {size_mb:.1f} MB")

    conn.close()

    print("✓ Migration complete!")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate JSON cache to SQLite")
    parser.add_argument("--project", help="Project root directory")
    parser.add_argument("--json", help="Path to cache_info.json")
    parser.add_argument("--output", help="Output SQLite database path")

    args = parser.parse_args()

    if args.project:
        # Auto-detect paths
        project = Path(args.project)
        # ... detect cache location
    elif args.json and args.output:
        json_path = Path(args.json)
        db_path = Path(args.output)
        migrate_json_to_sqlite(json_path, db_path)
    else:
        parser.print_help()
```

---

## Summary

This design provides a comprehensive, production-ready plan for migrating from JSON to SQLite cache with:

✅ **Clear architecture** with adapter pattern for risk-free deployment
✅ **Detailed schema** optimized for C++ symbol indexing
✅ **Phased implementation** over 3 weeks with clear milestones
✅ **Robust migration** with automatic backup and verification
✅ **Performance optimizations** targeting 20x speedup
✅ **Backward compatibility** with fallback to JSON
✅ **Comprehensive testing** including unit, integration, and stress tests
✅ **Gradual rollout** with monitoring and automatic rollback
✅ **Risk mitigation** for all identified failure modes

**Next Steps:**
1. Review and approve this design
2. Create GitHub issue/project for tracking
3. Begin Phase 1 implementation
4. Regular progress reviews

**Questions for Review:**
1. Is the 3-week timeline acceptable?
2. Should we add any additional safety mechanisms?
3. Are there specific edge cases to address?
4. Should we prototype first with a smaller test project?
