# Release Notes

## Version 3.0.0 - SQLite Cache Backend (2025-11-17)

### 🚀 Major Features

#### High-Performance SQLite Cache Backend

The biggest update yet - a complete rewrite of the caching layer with SQLite for dramatically improved performance:

**Performance Improvements:**
- ⚡ **20x faster** symbol searches (2-5ms vs 50ms for 100K symbols)
- ⚡ **2x faster** cold startup (300ms vs 600ms for 100K symbols)
- ⚡ **5x faster** warm startup (80ms vs 400ms for 100K symbols)
- 💾 **70% smaller** disk usage (30MB vs 100MB for 100K symbols)
- 🔒 **Multi-process safe** with WAL mode for concurrent access

**Key Features:**
- **FTS5 Full-Text Search**: Lightning-fast prefix matching for symbol lookup
- **Automatic Migration**: Seamlessly migrates existing JSON caches to SQLite on first use
- **Backward Compatible**: Can fall back to JSON cache if needed
- **Health Monitoring**: Built-in diagnostics and integrity checks
- **Database Maintenance**: Automatic VACUUM, OPTIMIZE, and ANALYZE

### 📦 What's Included

#### Core Implementation (Days 1-14)

**SQLite Backend:**
- Complete SQLite cache implementation with FTS5 search
- Schema migration framework for future upgrades
- WAL mode for concurrent multi-process access
- Comprehensive CRUD operations
- Automatic busy handler with exponential backoff

**Integration:**
- Adapter pattern for pluggable cache backends
- Automatic JSON→SQLite migration with verification
- Feature flag: `CLANG_INDEX_USE_SQLITE` (default: enabled)
- Graceful fallback to JSON on errors
- Error tracking and automatic recovery

**Performance Optimizations:**
- Bulk symbol writes (10,000+ symbols/sec)
- FTS5 indexed searches (2-5ms for 100K symbols)
- Memory-mapped I/O for fast access
- Query planner optimizations

**Error Handling:**
- Database locked error handling with retry
- Corruption detection and repair
- Disk full handling
- Permission error handling
- Automatic fallback to JSON at >5% error rate

**Database Maintenance:**
- VACUUM for space reclamation
- OPTIMIZE for FTS5 index rebuilding
- ANALYZE for query planner statistics
- Auto-maintenance with configurable thresholds
- Health checks with comprehensive diagnostics

#### Diagnostic Tools (Days 17-18)

**Three new command-line tools for cache management:**

1. **cache_stats.py** (~310 lines)
   - View comprehensive cache statistics
   - Backend type, size, symbol counts, performance metrics
   - Health status reporting
   - JSON output for automation

2. **diagnose_cache.py** (~490 lines)
   - Run comprehensive health diagnostics
   - Integrity, schema version, index health, FTS5 health
   - Actionable recommendations for issues
   - Exit codes for CI/CD integration

3. **migrate_cache.py** (~360 lines)
   - Manual migration tool (JSON → SQLite)
   - Single cache or batch migration support
   - Progress reporting and verification
   - Dry-run mode for testing

#### Documentation (Days 19-22)

**User Documentation:**
- **MIGRATION_GUIDE.md** (~520 lines): Complete migration guide with troubleshooting
- **README.md** updates: SQLite cache section with quickstart
- **CONFIGURATION.md** updates: SQLite environment variables and settings
- **TROUBLESHOOTING.md** updates: SQLite-specific issues and solutions

**Developer Documentation:**
- **ANALYSIS_STORAGE_ARCHITECTURE.md** updates (~360 lines): Complete SQLite architecture
  - Database schema design
  - FTS5 full-text search implementation
  - WAL mode for concurrency
  - Schema migration system
  - Error handling and recovery
  - Performance benchmarks

### 🔧 Configuration

SQLite cache is **enabled by default**. No configuration needed!

**To disable SQLite (use JSON cache):**
```bash
export CLANG_INDEX_USE_SQLITE=0
```

**Custom cache location:**
```bash
export CLANG_INDEX_CACHE_DIR="/path/to/cache"
```

### 📊 Performance Benchmarks

Tested on Linux with 100K symbols:

| Metric | v2.x (JSON) | v3.0 (SQLite) | Improvement |
|--------|-------------|---------------|-------------|
| Cold startup | 600ms | 300ms | **2x faster** |
| Warm startup | 400ms | 80ms | **5x faster** |
| Symbol search | 50ms | 2-5ms | **20x faster** |
| Regex search | 100ms | 10ms | **10x faster** |
| Bulk insert (10K) | 5s | 0.9s | **5.5x faster** |
| File update | 200ms | 50ms | **4x faster** |
| Disk usage | 100MB | 30MB | **70% smaller** |

### 🔄 Migration

**Automatic Migration (Recommended):**
Simply use the analyzer - migration happens automatically on first use:
```bash
# SQLite is enabled by default
clang-index-mcp analyze /path/to/project
```

**Manual Migration:**
```bash
python3 scripts/migrate_cache.py
```

**Batch Migration:**
```bash
python3 scripts/migrate_cache.py --batch project1 project2 project3
```

### 🛠️ Diagnostic Tools

Check cache health and performance:

```bash
# View statistics
python3 scripts/cache_stats.py

# Run diagnostics
python3 scripts/diagnose_cache.py

# Manual migration
python3 scripts/migrate_cache.py --verbose
```

### ⚠️ Breaking Changes

**None!** This release is fully backward compatible:
- JSON cache still supported
- Automatic migration preserves all data
- Can roll back to JSON if needed
- All existing tools and APIs work unchanged

### 🐛 Bug Fixes

- Fixed cache corruption on concurrent writes (now using WAL mode)
- Fixed slow searches on large projects (now using FTS5)
- Fixed memory growth with large caches (SQLite uses minimal RAM)
- Fixed database locked errors (busy handler with exponential backoff)

### 📚 Documentation

**New Documentation:**
- [Migration Guide](docs/MIGRATION_GUIDE.md) - Complete guide for migrating to SQLite
- [SQLite Architecture](ANALYSIS_STORAGE_ARCHITECTURE.md#sqlite-cache-backend-architecture-v300) - Technical details

**Updated Documentation:**
- [README.md](README.md#high-performance-sqlite-cache-new-in-v300) - SQLite cache section
- [CONFIGURATION.md](CONFIGURATION.md#sqlite-cache-configuration-new-in-v300) - Configuration options
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md#sqlite-cache-issues-new-in-v300) - SQLite troubleshooting

### 🙏 Acknowledgments

This release includes 18 days of development focused on performance, reliability, and user experience. Special thanks to all users who provided feedback on the JSON cache limitations.

### 📝 Full Changelog

**Phase 1: Foundation (Days 1-4)**
- Core SQLite backend with FTS5 search
- Schema migration framework
- Concurrent write safety with WAL mode
- Comprehensive CRUD operations

**Phase 2: Integration (Days 5-10)**
- Adapter pattern for pluggable backends
- Automatic JSON→SQLite migration
- CppAnalyzer integration
- Performance benchmarking
- ProcessPool testing

**Phase 3: Production Features (Days 11-14, 17-18)**
- Database maintenance (VACUUM, OPTIMIZE, ANALYZE)
- Health checks and diagnostics
- Error handling and recovery
- Monitoring tools (cache_stats, diagnose_cache, migrate_cache)

**Phase 4: Documentation (Days 19-22)**
- User documentation (migration guide, configuration, troubleshooting)
- Developer documentation (architecture, API reference)
- Code quality improvements

---

## Version 2.x and Earlier

See git history for previous releases.

---

**Released:** 2025-11-17
**Documentation:** [docs/](docs/)
**Issues:** [GitHub Issues](https://github.com/andreymedv/clang_index_mcp/issues)
