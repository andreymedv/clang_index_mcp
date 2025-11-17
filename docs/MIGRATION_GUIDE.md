# SQLite Cache Migration Guide

**Version:** 3.0.0
**Date:** 2025-11-17

---

## Table of Contents

- [Overview](#overview)
- [Why Migrate to SQLite?](#why-migrate-to-sqlite)
- [Pre-Migration Checklist](#pre-migration-checklist)
- [Migration Methods](#migration-methods)
  - [Automatic Migration](#automatic-migration)
  - [Manual Migration](#manual-migration)
  - [Batch Migration](#batch-migration)
- [Verification](#verification)
- [Rollback Instructions](#rollback-instructions)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## Overview

Starting with version 3.0.0, Clang Index MCP supports a high-performance SQLite cache backend as an alternative to the JSON-based cache. This guide will help you migrate your existing JSON cache to SQLite.

**Key Benefits:**
- ⚡ **20x faster** symbol searches with FTS5 full-text search
- 💾 **70% smaller** disk usage (30MB vs 100MB for 100K symbols)
- 🚀 **2x faster** startup time (300ms vs 600ms for 100K symbols)
- 🔒 **Better concurrency** with WAL mode for multi-process access

---

## Why Migrate to SQLite?

### Performance Improvements

| Metric | JSON Cache | SQLite Cache | Improvement |
|--------|-----------|--------------|-------------|
| Cold startup (100K symbols) | ~600ms | ~300ms | **2x faster** |
| Symbol search | ~50ms | ~2-5ms | **20x faster** |
| Disk usage (100K symbols) | ~100MB | ~30MB | **70% smaller** |
| Concurrent reads | Blocked | Supported | **Much better** |

### Feature Improvements

- **Full-Text Search:** FTS5-powered search with prefix matching
- **Incremental Updates:** Faster file-level cache updates
- **Better Concurrency:** WAL mode allows concurrent reads during writes
- **Health Monitoring:** Built-in integrity checks and diagnostics
- **Database Maintenance:** VACUUM, OPTIMIZE, ANALYZE for optimal performance

---

## Pre-Migration Checklist

Before migrating, ensure you meet these requirements:

### ✅ Prerequisites

- [ ] **Version 3.0.0+** installed
- [ ] **Existing JSON cache** in `.mcp_cache/cache_info.json`
- [ ] **Free disk space** (at least 50% of current cache size)
- [ ] **Read/Write permissions** on cache directory
- [ ] **No active analysis** (close all analyzer instances)

### 📋 Recommended Preparations

- [ ] **Backup your cache** (automatic, but good to verify)
- [ ] **Note cache size** (for comparison after migration)
- [ ] **Check cache health** with `scripts/diagnose_cache.py`
- [ ] **Review configuration** settings that affect caching

### ⚠️ Important Notes

- Migration is **one-way** (JSON → SQLite only)
- Original JSON cache is **preserved** (not deleted)
- Automatic **backup created** before migration
- Migration is **idempotent** (safe to retry)

---

## Migration Methods

### Automatic Migration

**Recommended for most users.** Migration happens automatically on first use.

#### Step 1: Enable SQLite Backend

Set the environment variable:

```bash
export CLANG_INDEX_USE_SQLITE=1
```

Or add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
# Use SQLite cache for Clang Index MCP
export CLANG_INDEX_USE_SQLITE=1
```

**Note:** SQLite is the **default** in v3.0.0+, so this may not be needed.

#### Step 2: Run Analyzer

Simply use the analyzer as normal. Migration happens automatically:

```bash
# Migration occurs on first SQLite cache access
clang-index-mcp analyze /path/to/project
```

#### Step 3: Verify Migration

Check that SQLite cache was created:

```bash
ls -lh .mcp_cache/cache.db
```

You should see the SQLite database file and a `.migrated_to_sqlite` marker.

#### What Happens During Automatic Migration

1. **Check:** Verifies JSON cache exists and no SQLite cache exists
2. **Backup:** Creates timestamped backup in `.mcp_cache/backup_YYYYMMDD_HHMMSS/`
3. **Migrate:** Extracts all symbols and metadata from JSON
4. **Verify:** Validates symbol counts and random sample
5. **Mark:** Creates `.migrated_to_sqlite` marker to prevent re-migration
6. **Complete:** SQLite cache is ready for use

**Duration:** 1-5 seconds for typical projects (10K-50K symbols)

---

### Manual Migration

**Recommended for:**
- Large projects (> 100K symbols)
- Batch migration of multiple projects
- When you want explicit control over the process

#### Using the Migration Tool

```bash
# Basic migration
python3 scripts/migrate_cache.py

# Specify cache directory
python3 scripts/migrate_cache.py --cache-dir /path/to/project/.mcp_cache

# Verbose output
python3 scripts/migrate_cache.py --verbose

# Dry run (check without migrating)
python3 scripts/migrate_cache.py --dry-run
```

#### Advanced Options

```bash
# Skip backup creation (not recommended)
python3 scripts/migrate_cache.py --skip-backup

# Skip verification (faster but risky)
python3 scripts/migrate_cache.py --skip-verification

# JSON output for automation
python3 scripts/migrate_cache.py --json
```

---

### Batch Migration

Migrate multiple projects at once:

```bash
# Migrate multiple projects
python3 scripts/migrate_cache.py --batch \
  /path/to/project1/.mcp_cache \
  /path/to/project2/.mcp_cache \
  /path/to/project3/.mcp_cache

# Or with parent directories (tool finds .mcp_cache automatically)
python3 scripts/migrate_cache.py --batch \
  /path/to/project1 \
  /path/to/project2 \
  /path/to/project3
```

**Output:**
```
======================================================================
Migrating: /path/to/project1/.mcp_cache
======================================================================
✅ Migration successful
   Symbols: 15,234
   Files: 145
   Time: 2.34s

======================================================================
Migrating: /path/to/project2/.mcp_cache
======================================================================
✅ Migration successful
   Symbols: 45,123
   Files: 512
   Time: 5.67s

======================================================================
MIGRATION SUMMARY
======================================================================

Total Caches: 2
Successful: 2
Failed: 0

Total Migrated:
  Symbols: 60,357
  Files: 657
  Time: 8.01s
```

---

## Verification

After migration, verify the cache is healthy and complete.

### Quick Verification

Check that the SQLite database exists:

```bash
ls -lh .mcp_cache/cache.db
ls -lh .mcp_cache/.migrated_to_sqlite
```

### Comprehensive Verification

#### 1. Check Cache Statistics

```bash
python3 scripts/cache_stats.py
```

**Expected output:**
```
======================================================================
CACHE STATISTICS
======================================================================

Backend Type: SQLite

──────────────────────────────────────────────────────────────────────
SIZE INFORMATION
──────────────────────────────────────────────────────────────────────
Database Size: 28.45 MB
  Raw bytes: 29,835,264

──────────────────────────────────────────────────────────────────────
SYMBOL STATISTICS
──────────────────────────────────────────────────────────────────────
Total Symbols: 15,234

By Kind:
  function            : 8,456
  class               : 3,234
  method              : 2,345
  ...

Project Symbols: 12,456
Dependency Symbols: 2,778

──────────────────────────────────────────────────────────────────────
HEALTH STATUS
──────────────────────────────────────────────────────────────────────
Status: ✅ HEALTHY
```

#### 2. Run Health Diagnostics

```bash
python3 scripts/diagnose_cache.py
```

**Expected output:**
```
======================================================================
CACHE DIAGNOSTIC REPORT
======================================================================

Cache Directory: .mcp_cache
Cache Type: SQLite

──────────────────────────────────────────────────────────────────────
DIAGNOSTIC CHECKS
──────────────────────────────────────────────────────────────────────
Integrity Check                ✅ PASS
Schema Version                 ✅ PASS
Index Health                   ✅ PASS
FTS5 Health                    ✅ PASS
WAL Mode                       ✅ PASS
Database Size                  ✅ PASS
Symbol Counts                  ✅ PASS

======================================================================
✅ Cache is healthy
======================================================================
```

#### 3. Compare Symbol Counts

Compare JSON and SQLite symbol counts to ensure completeness:

```bash
# Count JSON symbols (before migration)
python3 -c "
import json
with open('.mcp_cache/cache_info.json') as f:
    data = json.load(f)
    class_count = sum(len(v) for v in data.get('class_index', {}).values())
    func_count = sum(len(v) for v in data.get('function_index', {}).values())
    print(f'JSON symbols: {class_count + func_count}')
"

# Count SQLite symbols (after migration)
python3 scripts/cache_stats.py --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f\"SQLite symbols: {data['total_symbols']}\")
"
```

Counts should match exactly.

#### 4. Test Analyzer Functionality

Run a simple query to verify the analyzer works:

```bash
# Test symbol lookup
clang-index-mcp query "find-symbol MyClass"
```

---

## Rollback Instructions

If you need to revert to JSON cache:

### Option 1: Disable SQLite (Keep Both)

```bash
# Disable SQLite backend (fall back to JSON)
export CLANG_INDEX_USE_SQLITE=0

# Or remove from environment
unset CLANG_INDEX_USE_SQLITE
```

The original JSON cache remains intact, so the analyzer will use it.

### Option 2: Delete SQLite Cache

```bash
# Remove SQLite cache and marker
rm .mcp_cache/cache.db
rm .mcp_cache/.migrated_to_sqlite

# JSON cache will be used automatically
```

### Option 3: Restore from Backup

If you need to restore the exact pre-migration state:

```bash
# Find backup directory
ls -lt .mcp_cache/backup_*/

# Restore from most recent backup
cp -r .mcp_cache/backup_20251117_143022/* .mcp_cache/

# Clean up SQLite files
rm .mcp_cache/cache.db
rm .mcp_cache/.migrated_to_sqlite
```

---

## Troubleshooting

### Migration Fails: "Migration verification failed"

**Cause:** Symbol count mismatch between JSON and SQLite.

**Solution:**
```bash
# 1. Check diagnostic output for details
python3 scripts/diagnose_cache.py --verbose

# 2. Try re-migration (automatic backup is created)
rm .mcp_cache/cache.db .mcp_cache/.migrated_to_sqlite
python3 scripts/migrate_cache.py --verbose

# 3. If still fails, check JSON cache integrity
python3 -c "
import json
try:
    with open('.mcp_cache/cache_info.json') as f:
        json.load(f)
    print('JSON cache is valid')
except Exception as e:
    print(f'JSON cache error: {e}')
"
```

### Migration Fails: "Database is locked"

**Cause:** Another process is using the cache.

**Solution:**
```bash
# 1. Close all analyzer instances
# 2. Check for stale lock files
ls -la .mcp_cache/*.db-wal .mcp_cache/*.db-shm

# 3. Remove lock files if no processes are using cache
rm .mcp_cache/*.db-wal .mcp_cache/*.db-shm

# 4. Retry migration
python3 scripts/migrate_cache.py
```

### Migration Fails: "Disk full"

**Cause:** Insufficient disk space.

**Solution:**
```bash
# 1. Check disk space
df -h .mcp_cache

# 2. Free up space or use a different location
export CLANG_INDEX_CACHE_DIR=/path/with/more/space

# 3. Retry migration
python3 scripts/migrate_cache.py
```

### Performance Worse After Migration

**Cause:** Database not optimized after migration.

**Solution:**
```bash
# Run database optimization
python3 -c "
from pathlib import Path
from mcp_server.sqlite_cache_backend import SqliteCacheBackend

db = SqliteCacheBackend(Path('.mcp_cache/cache.db'))
db.auto_maintenance()
db._close()
print('Optimization complete')
"
```

### "FTS5 not available" Error

**Cause:** SQLite built without FTS5 support (rare).

**Solution:**
```bash
# Check SQLite version and FTS5 support
python3 -c "
import sqlite3
print(f'SQLite version: {sqlite3.sqlite_version}')
conn = sqlite3.connect(':memory:')
try:
    conn.execute('CREATE VIRTUAL TABLE test USING fts5(content)')
    print('FTS5: Available')
except:
    print('FTS5: Not available - reinstall Python with full SQLite')
"
```

---

## FAQ

### Q: Is migration reversible?

**A:** Yes. The original JSON cache is preserved. You can switch back by setting `CLANG_INDEX_USE_SQLITE=0` or deleting the SQLite cache.

### Q: How long does migration take?

**A:** Typically 1-5 seconds for projects with 10K-50K symbols. Larger projects (100K+ symbols) may take 10-30 seconds.

### Q: Will migration affect my code analysis?

**A:** No. The analyzer functionality remains the same. Only the cache storage backend changes.

### Q: Can I delete the JSON cache after migration?

**A:** Yes, but keep it for a while (1-2 weeks) to ensure SQLite cache is working properly. The migration tool creates a backup anyway.

### Q: What happens if migration is interrupted?

**A:** Migration is safe to retry. If interrupted, delete `.mcp_cache/cache.db` and run migration again.

### Q: Can I use both JSON and SQLite caches?

**A:** No. The analyzer uses one backend at a time, selected by `CLANG_INDEX_USE_SQLITE` (default: 1 = SQLite).

### Q: Does migration work on Windows/macOS/Linux?

**A:** Yes. Migration is cross-platform and tested on all three operating systems.

### Q: What if I have multiple projects?

**A:** Use batch migration: `python3 scripts/migrate_cache.py --batch project1 project2 project3`

### Q: How do I know migration was successful?

**A:** Run `python3 scripts/diagnose_cache.py`. You should see all checks passing with "✅ Cache is healthy".

### Q: Can I automate migration in CI/CD?

**A:** Yes. Use `--json` flag for machine-readable output:
```bash
python3 scripts/migrate_cache.py --json | jq '.success'
```

---

## Additional Resources

- **Performance Benchmarks:** See `docs/design/sqlite-cache-architecture.md`
- **Configuration Options:** See `CONFIGURATION.md`
- **Troubleshooting:** See `TROUBLESHOOTING.md`
- **Architecture Details:** See `ANALYSIS_STORAGE_ARCHITECTURE.md`

---

## Support

If you encounter issues not covered in this guide:

1. Run diagnostics: `python3 scripts/diagnose_cache.py --verbose`
2. Check logs in `.mcp_cache/migration.log` (if exists)
3. Report issues at: https://github.com/andreymedv/clang_index_mcp/issues

---

**Last Updated:** 2025-11-17
**Version:** 3.0.0
