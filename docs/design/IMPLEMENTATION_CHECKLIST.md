# SQLite Cache Implementation Checklist

**Status:** Ready to Start
**Approved:** 2025-11-17
**Timeline:** 3.5 weeks (24 working days)
**Team:** 1 developer

---

## Approved Requirements

✅ **Timeline:** 3.5 weeks
✅ **FTS5:** Include in v3.0
✅ **NFS Support:** Do NOT support (simplifies implementation)
✅ **Platforms:** Windows, Linux, macOS (all three)

---

## Phase 1: Foundation (Week 1, Days 1-4)

**Goal:** Create production-ready SQLite backend with safety features

**Duration:** 4 days
**Start:** Day 1
**End:** Day 4

### Day 1: Core SQLite Backend Structure

- [ ] **1.1** Create `mcp_server/sqlite_cache_backend.py`
  - [ ] Class structure with `__init__`, connection management
  - [ ] Database path handling
  - [ ] Connection configuration (timeout, isolation level)
  - [ ] Platform detection (Windows/Linux/macOS)
  - [ ] No NFS detection needed (per requirement)

- [ ] **1.2** Create database schema file `mcp_server/schema.sql`
  - [ ] Main `symbols` table with all columns
  - [ ] `file_metadata` table
  - [ ] `cache_metadata` table
  - [ ] `schema_version` table
  - [ ] `header_tracker` table
  - [ ] `parse_errors` table
  - [ ] All indexes (name, kind, file, parent, namespace, project)
  - [ ] Composite index (name, kind, is_project)
  - [ ] Timestamp indexes (updated_at, indexed_at)

- [ ] **1.3** Implement schema initialization
  - [ ] `_init_database()` method
  - [ ] `_execute_schema()` to run schema.sql
  - [ ] `_configure_optimizations()` for PRAGMA settings
  - [ ] WAL mode configuration
  - [ ] Cache size configuration
  - [ ] Synchronous mode configuration

**Deliverables:**
- `sqlite_cache_backend.py` (~150 lines)
- `schema.sql` (~100 lines)

**Success Criteria:**
- Database creates successfully
- All tables present
- All indexes created
- PRAGMA settings verified

---

### Day 2: Schema Migration Framework

- [ ] **2.1** Create migrations directory structure
  - [ ] Create `mcp_server/migrations/` directory
  - [ ] Create `001_initial_schema.sql` migration
  - [ ] Create migration README

- [ ] **2.2** Implement `SchemaMigration` class
  - [ ] Create `mcp_server/schema_migrations.py`
  - [ ] `get_current_version()` method
  - [ ] `needs_migration()` method
  - [ ] `migrate()` method to apply pending migrations
  - [ ] `_apply_migration(version)` to run single migration
  - [ ] Version tracking in `schema_version` table

- [ ] **2.3** Integrate migration into backend init
  - [ ] Call migration check in `__init__`
  - [ ] Handle migration errors gracefully
  - [ ] Log migration progress

- [ ] **2.4** Write migration tests
  - [ ] Test v0 → v1 migration
  - [ ] Test current version detection
  - [ ] Test forward-only enforcement (no downgrades)
  - [ ] Test missing migration file handling

**Deliverables:**
- `schema_migrations.py` (~150 lines)
- `migrations/001_initial_schema.sql` (~100 lines)
- `migrations/README.md` (~50 lines)
- Migration tests (~100 lines)

**Success Criteria:**
- Migration from empty DB to v1 works
- Version tracking accurate
- Error handling robust

---

### Day 3: Concurrent Write Safety & Connection Lifecycle

- [ ] **3.1** Implement concurrent write safety
  - [ ] Configure WAL mode in `__init__`
  - [ ] Implement `_busy_handler()` with exponential backoff
  - [ ] Set connection timeout (30s)
  - [ ] Configure `check_same_thread=False`
  - [ ] Platform-specific configuration (Windows vs Unix)

- [ ] **3.2** Implement connection lifecycle management
  - [ ] `_ensure_connected()` method
  - [ ] `_connect()` method
  - [ ] `_close()` method
  - [ ] `__enter__` and `__exit__` for context manager
  - [ ] Last access tracking
  - [ ] Idle connection timeout (5 minutes)

- [ ] **3.3** Implement basic CRUD operations
  - [ ] `save_symbol(symbol: SymbolInfo)` - single insert
  - [ ] `save_symbols_batch(symbols: List[SymbolInfo])` - bulk insert
  - [ ] `load_symbol_by_usr(usr: str)` - single read
  - [ ] `load_symbols_by_name(name: str)` - multi read
  - [ ] `delete_symbols_by_file(file_path: str)` - file deletion
  - [ ] `_symbol_to_tuple()` helper for SQL parameters
  - [ ] `_row_to_symbol()` helper for result parsing

- [ ] **3.4** Write concurrency tests
  - [ ] Test concurrent reads (5 threads)
  - [ ] Test concurrent writes (3 threads)
  - [ ] Test database locked scenario
  - [ ] Test busy handler retry logic
  - [ ] Test connection lifecycle

**Deliverables:**
- Connection management code (~150 lines)
- CRUD operations (~200 lines)
- Concurrency tests (~200 lines)

**Success Criteria:**
- Concurrent reads work without errors
- Concurrent writes handled with retry
- Connections close properly
- No resource leaks

---

### Day 4: Full-Text Search (FTS5) Implementation

- [ ] **4.1** Add FTS5 schema to schema.sql
  - [ ] Create `symbols_fts` virtual table
  - [ ] Add triggers for INSERT (symbols_ai)
  - [ ] Add triggers for DELETE (symbols_ad)
  - [ ] Add triggers for UPDATE (symbols_au)

- [ ] **4.2** Implement FTS5 search methods
  - [ ] `search_symbols_fts(pattern, kind, project_only)`
  - [ ] `search_symbols_regex(pattern, kind, project_only)` as fallback
  - [ ] Query construction for FTS5 MATCH syntax
  - [ ] Handle prefix search (e.g., "Vec*")
  - [ ] Handle exact match

- [ ] **4.3** Write FTS5 tests
  - [ ] Test FTS5 index creation
  - [ ] Test FTS5 triggers maintain sync
  - [ ] Test prefix search
  - [ ] Test exact match
  - [ ] Test performance (10K symbols < 10ms)
  - [ ] Test fallback to regex search

- [ ] **4.4** Update schema migration for FTS5
  - [ ] Ensure FTS5 in initial schema
  - [ ] Test FTS5 with migration

**Deliverables:**
- FTS5 schema (~50 lines)
- FTS5 search methods (~100 lines)
- FTS5 tests (~150 lines)

**Success Criteria:**
- FTS5 searches work correctly
- Triggers keep FTS in sync
- Performance < 10ms for 10K symbols
- Prefix and exact searches work

---

## Phase 2: Integration & Testing (Week 1-2, Days 5-10)

**Goal:** Integrate with CppAnalyzer, ensure production readiness

**Duration:** 6 days
**Start:** Day 5
**End:** Day 10

### Day 5: Adapter Pattern & Feature Flag

- [ ] **5.1** Create backend interface abstraction
  - [ ] Define `CacheBackend` protocol/base class
  - [ ] Methods: `save_cache()`, `load_cache()`, `save_file_cache()`, etc.
  - [ ] Ensure both JSON and SQLite implement same interface

- [ ] **5.2** Refactor `JsonCacheBackend`
  - [ ] Create `mcp_server/json_cache_backend.py`
  - [ ] Extract existing JSON logic from `CacheManager`
  - [ ] Implement `CacheBackend` interface
  - [ ] Ensure backward compatibility

- [ ] **5.3** Update `CacheManager` to use adapter
  - [ ] Add feature flag: `CLANG_INDEX_USE_SQLITE` (default: "1")
  - [ ] Backend selection logic in `__init__`
  - [ ] Delegate all operations to backend
  - [ ] Fallback to JSON on SQLite errors

- [ ] **5.4** Write adapter tests
  - [ ] Test feature flag ON → uses SQLite
  - [ ] Test feature flag OFF → uses JSON
  - [ ] Test fallback on SQLite error
  - [ ] Test backend interface compatibility

**Deliverables:**
- `CacheBackend` interface (~50 lines)
- `json_cache_backend.py` (~400 lines, extracted)
- Updated `cache_manager.py` (~150 lines modified)
- Adapter tests (~150 lines)

**Success Criteria:**
- Feature flag works correctly
- Both backends work independently
- Fallback to JSON successful
- No regression in JSON mode

---

### Day 6: Automatic Migration & Integration

- [ ] **6.1** Implement automatic JSON → SQLite migration
  - [ ] Create `mcp_server/cache_migration.py`
  - [ ] `migrate_json_to_sqlite(json_path, db_path)` function
  - [ ] Load cache_info.json
  - [ ] Extract all symbols from class_index and function_index
  - [ ] Batch insert into SQLite
  - [ ] Migrate file_hashes to file_metadata table
  - [ ] Migrate cache metadata

- [ ] **6.2** Implement migration verification
  - [ ] `verify_migration(json_path, db_path)` function
  - [ ] Symbol count check
  - [ ] Random sample verification (100 symbols)
  - [ ] Metadata verification

- [ ] **6.3** Integrate auto-migration into CacheManager
  - [ ] `_maybe_migrate_from_json()` method
  - [ ] Check for `.migrated_to_sqlite` marker
  - [ ] Create backup before migration
  - [ ] Run migration on first SQLite use
  - [ ] Create marker file on success

- [ ] **6.4** Write migration tests
  - [ ] Test small project migration (100 symbols)
  - [ ] Test medium project migration (10K symbols)
  - [ ] Test migration verification
  - [ ] Test backup creation
  - [ ] Test marker file prevents re-migration

**Deliverables:**
- `cache_migration.py` (~300 lines)
- Migration integration (~100 lines)
- Migration tests (~250 lines)

**Success Criteria:**
- Migration preserves all symbols
- Verification passes
- Backup created
- Idempotent (marker prevents re-run)

---

### Day 7: CppAnalyzer Integration

- [ ] **7.1** Integrate SQLite backend with analyzer load
  - [ ] Update `_load_cache()` to use backend abstraction
  - [ ] Test cache loading with SQLite backend
  - [ ] Verify all indexes populated correctly

- [ ] **7.2** Integrate SQLite backend with analyzer save
  - [ ] Update `_save_cache()` to use backend abstraction
  - [ ] Implement bulk symbol collection
  - [ ] Test cache saving with SQLite backend

- [ ] **7.3** Implement incremental updates
  - [ ] `update_file_symbols(file_path, symbols)` method
  - [ ] Delete old symbols for file
  - [ ] Insert new symbols
  - [ ] Update file_metadata

- [ ] **7.4** Write integration tests
  - [ ] Test full index → save → load cycle
  - [ ] Test incremental file update
  - [ ] Test cache invalidation on file change
  - [ ] Test cache invalidation on config change

**Deliverables:**
- Analyzer integration (~150 lines modified)
- Incremental update logic (~100 lines)
- Integration tests (~300 lines)

**Success Criteria:**
- Full indexing works with SQLite
- Save/load cycle preserves data
- Incremental updates work
- Cache invalidation triggers correctly

---

### Day 8-9: Performance Benchmarking & Optimization

- [ ] **8.1** Create benchmark suite
  - [ ] Create `tests/benchmark_cache.py`
  - [ ] Benchmark startup time (cold/warm)
  - [ ] Benchmark search operations
  - [ ] Benchmark save operations
  - [ ] Benchmark incremental updates
  - [ ] Compare JSON vs SQLite

- [ ] **8.2** Implement test data generators
  - [ ] Generate test projects (1K, 10K, 50K, 100K symbols)
  - [ ] Realistic symbol distributions
  - [ ] Realistic file structures

- [ ] **8.3** Run benchmarks on all platforms
  - [ ] Linux benchmarks
  - [ ] macOS benchmarks
  - [ ] Windows benchmarks
  - [ ] Document results

- [ ] **8.4** Optimize based on results
  - [ ] Identify bottlenecks
  - [ ] Optimize slow queries
  - [ ] Add missing indexes if needed
  - [ ] Tune PRAGMA settings

- [ ] **8.5** Implement query performance monitoring
  - [ ] Add `QueryProfiler` class
  - [ ] `_profile_query()` context manager
  - [ ] `get_query_stats()` method
  - [ ] Feature flag: `CLANG_INDEX_PROFILE_QUERIES`

**Deliverables:**
- `benchmark_cache.py` (~300 lines)
- Test data generators (~150 lines)
- Performance report document (~100 lines)
- Query profiling (~100 lines)

**Success Criteria:**
- Startup < 500ms for 100K symbols
- FTS5 search < 5ms for 100K symbols
- Bulk write > 5000 symbols/sec
- All platforms benchmarked

---

### Day 10: ProcessPoolExecutor Testing

- [ ] **10.1** Test SQLite with ProcessPoolExecutor
  - [ ] Create `tests/test_processpool_cache.py`
  - [ ] Test concurrent reads (4 workers)
  - [ ] Test cache hit performance
  - [ ] Test isolated connections
  - [ ] Test no database locked errors

- [ ] **10.2** Test bulk symbol collection pattern
  - [ ] Test thread-local buffer collection
  - [ ] Test bulk write to SQLite
  - [ ] Verify performance improvement

- [ ] **10.3** End-to-end ProcessPool test
  - [ ] Index test project with ProcessPool
  - [ ] Verify all symbols saved
  - [ ] Compare performance vs ThreadPool

**Deliverables:**
- ProcessPool tests (~300 lines)
- E2E test results

**Success Criteria:**
- ProcessPool mode works with SQLite
- No connection sharing issues
- Performance better than JSON
- All tests pass on 3 platforms

---

## Phase 3: Production Features (Week 2-3, Days 11-18)

**Goal:** Add production-ready features and polish

**Duration:** 8 days
**Start:** Day 11
**End:** Day 18

### Day 11-12: Database Maintenance & Health

- [ ] **11.1** Implement database maintenance
  - [ ] `should_vacuum()` - check if vacuum needed (weekly)
  - [ ] `auto_vacuum()` - run VACUUM and ANALYZE
  - [ ] `optimize_database()` - run PRAGMA optimize
  - [ ] Schedule in cache save flow

- [ ] **11.2** Implement database health checks
  - [ ] `verify_integrity()` - PRAGMA integrity_check
  - [ ] `check_database_size()` - warn if > 500MB
  - [ ] `auto_repair()` - attempt repair on corruption
  - [ ] `backup_database()` - create .backup file

- [ ] **11.3** Implement cache statistics
  - [ ] `get_cache_stats()` - symbol count, file count, DB size
  - [ ] `get_query_stats()` - query performance metrics
  - [ ] Include in cache save metadata

- [ ] **11.4** Write maintenance tests
  - [ ] Test vacuum reduces size
  - [ ] Test integrity check detects corruption
  - [ ] Test auto-repair attempts recovery
  - [ ] Test statistics accuracy

**Deliverables:**
- Maintenance methods (~200 lines)
- Health check methods (~150 lines)
- Maintenance tests (~200 lines)

**Success Criteria:**
- Vacuum reclaims space
- Integrity check works
- Statistics accurate
- Auto-repair functional

---

### Day 13-14: Error Handling & Recovery

- [ ] **13.1** Implement comprehensive error handling
  - [ ] Handle database locked errors
  - [ ] Handle corruption errors
  - [ ] Handle disk full errors
  - [ ] Handle permission errors
  - [ ] Fallback to JSON on persistent errors

- [ ] **13.2** Implement error logging
  - [ ] Log SQLite errors to diagnostics
  - [ ] Track error counts
  - [ ] Implement error rate monitoring
  - [ ] Auto-fallback at 5% error rate

- [ ] **13.3** Implement recovery mechanisms
  - [ ] Restore from backup on corruption
  - [ ] Rebuild cache from source on unrecoverable error
  - [ ] Clear cache and restart on critical errors

- [ ] **13.4** Write error handling tests
  - [ ] Test database locked recovery
  - [ ] Test corruption recovery
  - [ ] Test disk full handling
  - [ ] Test fallback to JSON
  - [ ] Test error rate monitoring

**Deliverables:**
- Error handling (~200 lines)
- Recovery mechanisms (~150 lines)
- Error tests (~300 lines)

**Success Criteria:**
- All error types handled gracefully
- Recovery mechanisms work
- No crashes on errors
- Fallback to JSON successful

---

### Day 15-16: Platform-Specific Testing & Fixes

- [ ] **15.1** Windows-specific testing
  - [ ] Test on Windows 10/11
  - [ ] Test file locking behavior
  - [ ] Test path handling (backslashes)
  - [ ] Test NTFS-specific issues
  - [ ] Fix any Windows-specific bugs

- [ ] **15.2** macOS-specific testing
  - [ ] Test on macOS (if available)
  - [ ] Test APFS-specific issues
  - [ ] Test case-sensitivity handling
  - [ ] Fix any macOS-specific bugs

- [ ] **15.3** Linux-specific testing
  - [ ] Test on Ubuntu/Debian
  - [ ] Test on RHEL/CentOS
  - [ ] Test ext4/btrfs/xfs filesystems
  - [ ] Fix any Linux-specific bugs

- [ ] **15.4** Cross-platform compatibility
  - [ ] Ensure consistent behavior across platforms
  - [ ] Document platform differences
  - [ ] Add platform detection utilities
  - [ ] Platform-specific configuration

**Deliverables:**
- Platform test results
- Platform-specific fixes (~100 lines)
- Platform compatibility tests (~200 lines)

**Success Criteria:**
- All tests pass on Windows
- All tests pass on macOS
- All tests pass on Linux
- No critical platform differences

---

### Day 17-18: Monitoring & Diagnostics Tools

- [ ] **17.1** Create cache statistics tool
  - [ ] Create `scripts/cache_stats.py`
  - [ ] Show backend type (JSON/SQLite)
  - [ ] Show database size
  - [ ] Show symbol count breakdown
  - [ ] Show last vacuum time
  - [ ] Show query statistics
  - [ ] Show health status

- [ ] **17.2** Create cache diagnostic tool
  - [ ] Create `scripts/diagnose_cache.py`
  - [ ] Check cache integrity
  - [ ] Check for corruption
  - [ ] Check for missing indexes
  - [ ] Check for schema version mismatch
  - [ ] Suggest fixes

- [ ] **17.3** Create migration tool
  - [ ] Create `scripts/migrate_cache.py`
  - [ ] Command-line interface
  - [ ] Progress reporting
  - [ ] Verification
  - [ ] Backup creation
  - [ ] Support batch migration

**Deliverables:**
- `cache_stats.py` (~150 lines)
- `diagnose_cache.py` (~200 lines)
- `migrate_cache.py` (~200 lines)

**Success Criteria:**
- Tools provide useful diagnostics
- Migration tool works for large projects
- Progress reporting clear
- All tools tested on 3 platforms

---

## Phase 4: Documentation & Release (Week 3, Days 19-24)

**Goal:** Complete documentation and prepare for release

**Duration:** 6 days
**Start:** Day 19
**End:** Day 24

### Day 19-20: User Documentation

- [ ] **19.1** Update main README
  - [ ] Add SQLite cache section
  - [ ] Document feature flag
  - [ ] Document migration process
  - [ ] Performance improvements section

- [ ] **19.2** Create migration guide
  - [ ] Create `docs/MIGRATION_GUIDE.md`
  - [ ] Pre-migration checklist
  - [ ] Step-by-step migration
  - [ ] Verification steps
  - [ ] Rollback instructions
  - [ ] Troubleshooting

- [ ] **19.3** Update configuration documentation
  - [ ] Update `CONFIGURATION.md`
  - [ ] Document `CLANG_INDEX_USE_SQLITE` flag
  - [ ] Document `CLANG_INDEX_PROFILE_QUERIES` flag
  - [ ] SQLite-specific settings

- [ ] **19.4** Create troubleshooting guide
  - [ ] Update `TROUBLESHOOTING.md`
  - [ ] Common SQLite errors
  - [ ] Migration issues
  - [ ] Performance issues
  - [ ] Platform-specific issues

**Deliverables:**
- Updated README (~100 lines added)
- `MIGRATION_GUIDE.md` (~300 lines)
- Updated `CONFIGURATION.md` (~50 lines added)
- Updated `TROUBLESHOOTING.md` (~150 lines added)

**Success Criteria:**
- Clear migration instructions
- All flags documented
- Common issues covered
- Examples provided

---

### Day 21-22: Developer Documentation & Code Quality

- [ ] **21.1** Add comprehensive docstrings
  - [ ] All public methods documented
  - [ ] All classes documented
  - [ ] Parameter types and return types
  - [ ] Usage examples

- [ ] **21.2** Update architecture documentation
  - [ ] Update `ANALYSIS_STORAGE_ARCHITECTURE.md`
  - [ ] SQLite architecture section
  - [ ] Schema documentation
  - [ ] Migration framework documentation

- [ ] **21.3** Create API documentation
  - [ ] Document `SqliteCacheBackend` API
  - [ ] Document migration API
  - [ ] Document maintenance API
  - [ ] Code examples

- [ ] **21.4** Code quality review
  - [ ] Run linters (pylint, mypy)
  - [ ] Fix any issues
  - [ ] Add type hints where missing
  - [ ] Remove debug code
  - [ ] Clean up comments

**Deliverables:**
- Complete docstrings
- Updated architecture docs (~200 lines)
- API documentation (~150 lines)
- Clean, linted code

**Success Criteria:**
- All public APIs documented
- No linter errors
- Type hints complete
- Code clean and readable

---

### Day 23: Final Testing & Validation

- [ ] **23.1** Run full test suite
  - [ ] All unit tests pass (3 platforms)
  - [ ] All integration tests pass (3 platforms)
  - [ ] All performance benchmarks meet targets
  - [ ] No regressions in JSON mode

- [ ] **23.2** Manual testing
  - [ ] Test with real projects (small, medium, large)
  - [ ] Test migration on existing caches
  - [ ] Test error scenarios
  - [ ] Test recovery mechanisms

- [ ] **23.3** Stress testing
  - [ ] 100K symbol project
  - [ ] 500K symbol project (if available)
  - [ ] Concurrent analyzer instances
  - [ ] Rapid file changes (incremental updates)

- [ ] **23.4** Create validation report
  - [ ] Test results summary
  - [ ] Performance metrics
  - [ ] Platform compatibility
  - [ ] Known issues

**Deliverables:**
- Test results report
- Validation checklist
- Known issues list

**Success Criteria:**
- All tests pass on 3 platforms
- Performance targets met
- No critical bugs
- Ready for release

---

### Day 24: Release Preparation

- [ ] **24.1** Update version numbers
  - [ ] Bump version to 3.0.0
  - [ ] Update CHANGELOG
  - [ ] Update pyproject.toml

- [ ] **24.2** Create release notes
  - [ ] Feature highlights
  - [ ] Performance improvements
  - [ ] Migration instructions
  - [ ] Breaking changes (if any)
  - [ ] Known issues

- [ ] **24.3** Prepare rollout plan
  - [ ] Alpha phase plan (internal testing)
  - [ ] Beta phase plan (wider testing)
  - [ ] GA phase plan (general availability)
  - [ ] Monitoring setup
  - [ ] Rollback plan

- [ ] **24.4** Final review
  - [ ] Review all code changes
  - [ ] Review all documentation
  - [ ] Review test coverage
  - [ ] Get sign-off from stakeholders

**Deliverables:**
- Version 3.0.0 release
- Release notes
- Rollout plan
- Final review report

**Success Criteria:**
- Release ready for alpha
- Documentation complete
- Rollout plan approved
- All deliverables complete

---

## Test Coverage Requirements

### Unit Tests (Target: 95%+ coverage)

- [ ] `SqliteCacheBackend` class
  - [ ] Connection management
  - [ ] CRUD operations
  - [ ] FTS5 searches
  - [ ] Concurrent access
  - [ ] Error handling

- [ ] `SchemaMigration` class
  - [ ] Version detection
  - [ ] Migration application
  - [ ] Error handling

- [ ] Migration functions
  - [ ] JSON to SQLite conversion
  - [ ] Verification
  - [ ] Backup creation

- [ ] Platform-specific code
  - [ ] Windows paths
  - [ ] Unix paths
  - [ ] macOS specific

### Integration Tests

- [ ] Full indexing workflow
- [ ] Cache save/load cycle
- [ ] Incremental updates
- [ ] Migration from JSON
- [ ] ProcessPool mode
- [ ] Feature flag switching
- [ ] Fallback to JSON

### Performance Tests

- [ ] Startup time benchmarks
- [ ] Search performance benchmarks
- [ ] Write performance benchmarks
- [ ] Memory usage tests
- [ ] Concurrent access performance

### Platform Tests

- [ ] Windows 10/11
- [ ] Linux (Ubuntu 20.04+)
- [ ] macOS (10.15+)

---

## Deliverables Summary

### Code

- [ ] `mcp_server/sqlite_cache_backend.py` (~800 lines)
- [ ] `mcp_server/schema_migrations.py` (~150 lines)
- [ ] `mcp_server/json_cache_backend.py` (~400 lines)
- [ ] `mcp_server/cache_migration.py` (~300 lines)
- [ ] `mcp_server/schema.sql` (~150 lines)
- [ ] `mcp_server/migrations/001_initial_schema.sql` (~100 lines)
- [ ] Updated `mcp_server/cache_manager.py` (~200 lines modified)
- [ ] Updated `mcp_server/cpp_analyzer.py` (~100 lines modified)

**Total new code:** ~2,200 lines
**Total modified code:** ~300 lines

### Tests

- [ ] `tests/test_sqlite_cache_backend.py` (~500 lines)
- [ ] `tests/test_schema_migrations.py` (~200 lines)
- [ ] `tests/test_cache_migration.py` (~300 lines)
- [ ] `tests/test_cache_integration.py` (~400 lines)
- [ ] `tests/test_processpool_cache.py` (~300 lines)
- [ ] `tests/benchmark_cache.py` (~300 lines)

**Total test code:** ~2,000 lines

### Documentation

- [ ] `MIGRATION_GUIDE.md` (~300 lines)
- [ ] Updated `README.md` (~100 lines added)
- [ ] Updated `CONFIGURATION.md` (~50 lines added)
- [ ] Updated `TROUBLESHOOTING.md` (~150 lines added)
- [ ] Updated `ANALYSIS_STORAGE_ARCHITECTURE.md` (~200 lines added)
- [ ] API documentation (~150 lines)

**Total documentation:** ~950 lines

### Tools

- [ ] `scripts/cache_stats.py` (~150 lines)
- [ ] `scripts/diagnose_cache.py` (~200 lines)
- [ ] `scripts/migrate_cache.py` (~200 lines)

**Total tools code:** ~550 lines

### Grand Total

- **Code:** ~2,500 lines
- **Tests:** ~2,000 lines
- **Documentation:** ~950 lines
- **Tools:** ~550 lines
- **TOTAL:** ~6,000 lines

---

## Success Metrics

### Performance (100K symbols)

- [ ] Cold startup < 500ms ✓ Target: 450ms
- [ ] Warm startup < 100ms ✓ Target: 80ms
- [ ] Name search < 5ms ✓ Target: 2ms (FTS5)
- [ ] Memory usage < 50MB ✓ Target: 45MB
- [ ] Disk usage < 40MB ✓ Target: 32MB
- [ ] Incremental update < 50ms ✓ Target: 45ms

### Quality

- [ ] Test coverage > 95%
- [ ] No critical bugs
- [ ] No performance regressions vs JSON
- [ ] All platforms supported (Windows, Linux, macOS)

### Usability

- [ ] Automatic migration works
- [ ] Feature flag works
- [ ] Fallback to JSON works
- [ ] Clear error messages
- [ ] Good documentation

---

## Risk Mitigation

### High-Risk Items

1. **Database corruption**
   - Mitigation: WAL mode, integrity checks, auto-repair, backups
   - Contingency: Fallback to JSON

2. **Performance regression**
   - Mitigation: Extensive benchmarking, optimization
   - Contingency: Identify bottlenecks, optimize or rollback

3. **Platform compatibility issues**
   - Mitigation: Test on all 3 platforms early
   - Contingency: Platform-specific code paths

4. **Migration data loss**
   - Mitigation: Backup, verification, testing
   - Contingency: Restore from backup, JSON fallback

---

## Daily Progress Tracking

Update this section daily:

### Week 1
- [ ] Day 1 complete
- [ ] Day 2 complete
- [ ] Day 3 complete
- [ ] Day 4 complete
- [ ] Day 5 complete

### Week 2
- [ ] Day 6 complete
- [ ] Day 7 complete
- [ ] Day 8 complete
- [ ] Day 9 complete
- [ ] Day 10 complete

### Week 3
- [ ] Day 11 complete
- [ ] Day 12 complete
- [ ] Day 13 complete
- [ ] Day 14 complete
- [ ] Day 15 complete
- [ ] Day 16 complete
- [ ] Day 17 complete
- [ ] Day 18 complete

### Week 4
- [ ] Day 19 complete
- [ ] Day 20 complete
- [ ] Day 21 complete
- [ ] Day 22 complete
- [ ] Day 23 complete
- [ ] Day 24 complete

---

## Notes

- FTS5 included in v3.0 (approved)
- No NFS support (approved)
- Support Windows, Linux, macOS (approved)
- Timeline: 3.5 weeks / 24 days (approved)

---

## Next Steps

1. ✅ Get checklist approved
2. ⬜ Start Day 1: Core SQLite Backend Structure
3. ⬜ Daily progress updates
4. ⬜ Weekly reviews with stakeholder

---

**Status:** 🟡 Awaiting Approval

**Approver:** _________________ Date: _________
