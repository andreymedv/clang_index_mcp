# SQLite Cache Architecture - Design Summary

**Date:** 2025-11-17
**Status:** Ready for Review
**Branch:** `claude/fix-cache-scalability-01AzJ96xJMbpLZ9Gbs9hShds`

---

## Overview

This directory contains the complete architectural design for migrating from JSON-based cache to SQLite-based cache to address scalability issues in large codebases.

---

## Documents

### 1. [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) ⭐ START HERE

**The main document you should review.** This is the final, production-ready implementation plan that incorporates all improvements from the architectural review.

**UPDATE (2025-11-17):** After rebasing to latest `origin/compile_commands-support`, all design remains valid. See [ADDENDUM-performance-optimizations.md](./ADDENDUM-performance-optimizations.md) for compatibility analysis with new ProcessPoolExecutor and bulk write optimizations.

**Contents:**
- Executive summary with updated metrics
- 4-phase implementation plan (3.5 weeks)
- Enhanced database schema with FTS5
- Critical features implementation (concurrency, migrations, FTS5)
- Testing strategy and rollout plan
- Risk mitigation and rollback procedures

**Key Improvements:**
- ✅ Schema migration framework
- ✅ Concurrent write safety (WAL mode, busy handler)
- ✅ Full-text search (FTS5) for 20x faster searches
- ✅ Connection lifecycle management
- ✅ Platform-specific configuration

---

### 2. [sqlite-cache-architecture.md](./sqlite-cache-architecture.md)

**The original comprehensive design document.** This is a detailed 1000+ line technical specification covering all aspects of the SQLite cache implementation.

**Contents:**
- Detailed problem analysis
- 5 alternative solutions (SQLite, Sharded JSON, Hybrid, Memory-mapped, Compressed)
- Complete database schema design
- Implementation strategy (4 phases)
- Performance optimizations
- Backward compatibility
- Testing requirements
- Rollout plan
- Risk analysis

**Use this for:** Deep technical understanding, reference during implementation

---

### 3. [sqlite-cache-architecture-review.md](./sqlite-cache-architecture-review.md)

**Critical architectural review.** This document identifies gaps and improvements in the original design.

**Contents:**
- 6 critical issues identified
- 23 improvement opportunities
- Detailed solutions for each issue
- Risk assessment update
- Recommendations for mandatory vs. optional improvements

**Key Issues Found:**
- 🔴 Schema migration strategy missing → Fixed in final plan
- 🔴 Concurrent write safety not addressed → Fixed in final plan
- 🟡 Full-text search not considered → Added to final plan
- 🟡 Connection lifecycle not specified → Fixed in final plan
- 🟡 Large call graphs inefficient → Documented, deferred to v3.1
- 🟡 Query performance monitoring missing → Added to final plan

**Use this for:** Understanding the review process, seeing what was improved

---

### 4. [ADDENDUM-performance-optimizations.md](./ADDENDUM-performance-optimizations.md) 🆕

**Compatibility analysis after rebase.** This document analyzes the impact of new performance optimizations (ProcessPoolExecutor, bulk writes) on the SQLite cache design.

**Contents:**
- Analysis of upstream changes (ProcessPoolExecutor, bulk writes, orjson)
- Impact assessment on SQLite design
- Compatibility verification
- Performance comparison (JSON vs SQLite with ProcessPool)
- Updated testing requirements

**Key Finding:**
- ✅ **All design remains valid** - no changes needed
- ✅ **SQLite works better with ProcessPool** than JSON does
- ✅ WAL mode eliminates read contention in multi-process mode
- ✅ Design already includes all necessary multi-process support

**Use this for:** Understanding why the design didn't change after rebase

---

## Quick Stats

### Performance Targets (100K symbols)

| Metric | Current (JSON) | Target (SQLite) | Expected (Final) |
|--------|----------------|-----------------|------------------|
| Cold startup | 10,000ms | 500ms | **450ms** ✓ |
| Warm startup | 8,000ms | 100ms | **80ms** ✓ |
| Name search | 50ms | 5ms | **2ms** ✓ (FTS5) |
| Memory usage | 200MB | 50MB | **45MB** ✓ |
| Disk usage | 100MB | 30MB | **32MB** (with FTS5 index) |
| Incremental update | 5,000ms | 50ms | **45ms** ✓ |

### Implementation Effort

- **Original estimate:** 3 weeks
- **Final estimate:** 3.5 weeks (with improvements)
- **Risk level:** Medium → Medium-Low
- **Complexity:** Medium

---

## Key Design Decisions

### 1. Adapter Pattern for Backend Abstraction

```python
class CacheManager:
    def __init__(self, project_root: Path):
        # Feature flag controls backend
        use_sqlite = os.getenv('CLANG_INDEX_USE_SQLITE', '1') == '1'

        if use_sqlite:
            self.backend = SqliteCacheBackend(db_path)
        else:
            self.backend = JsonCacheBackend(cache_dir)
```

**Why:** Risk-free deployment with instant rollback capability

---

### 2. Schema Migration Framework

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    description TEXT
);
```

**Why:** Future-proof for schema changes (v3.0 → v3.1 → v4.0)

---

### 3. Full-Text Search (FTS5)

```sql
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name, kind, usr UNINDEXED,
    content=symbols
);
```

**Why:** 20x faster searches (50ms → 2ms)

---

### 4. Concurrent Write Safety

```python
# WAL mode + busy handler + retry logic
self.conn.execute("PRAGMA journal_mode = WAL")
self.conn.set_busy_handler(self._busy_handler)
```

**Why:** Production-ready, handles concurrent analyzer instances

---

### 5. Keep In-Memory Indexes Unchanged

**Why:** No changes to search_engine.py or cpp_analyzer.py query logic. SQLite is purely a persistence layer optimization.

---

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│         CppAnalyzer (Unchanged)         │
│  In-Memory Indexes:                     │
│  ├─ class_index                         │
│  ├─ function_index                      │
│  ├─ file_index                          │
│  └─ usr_index                           │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│     CacheManager (Adapter Pattern)      │
│  Feature Flag: USE_SQLITE_CACHE         │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
┌──────────────────┐  ┌──────────────────┐
│ JsonCacheBackend │  │SqliteCacheBackend│
│   (Fallback)     │  │  (Primary)       │
└──────────────────┘  └──────────────────┘
         │                   │
         ▼                   ▼
┌──────────────────┐  ┌──────────────────┐
│ cache_info.json  │  │   symbols.db     │
│    100MB         │  │     32MB         │
└──────────────────┘  └──────────────────┘
```

---

## Database Schema (Final)

### Core Tables

```sql
-- Main symbols table
CREATE TABLE symbols (
    usr TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER NOT NULL,
    column INTEGER NOT NULL,
    signature TEXT,
    is_project BOOLEAN,
    namespace TEXT,
    access TEXT,
    parent_class TEXT,
    base_classes TEXT,  -- JSON array
    calls TEXT,         -- JSON array
    called_by TEXT,     -- JSON array
    created_at REAL,
    updated_at REAL
);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    name, kind, usr UNINDEXED,
    content=symbols
);

-- File metadata
CREATE TABLE file_metadata (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    indexed_at REAL NOT NULL
);

-- Schema versioning
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    description TEXT
);

-- Metadata
CREATE TABLE cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
```

### Key Indexes

```sql
CREATE INDEX idx_symbol_name ON symbols(name);
CREATE INDEX idx_symbol_kind ON symbols(kind);
CREATE INDEX idx_symbol_file ON symbols(file);
CREATE INDEX idx_name_kind_project ON symbols(name, kind, is_project);
CREATE INDEX idx_symbol_updated ON symbols(updated_at);  -- For incremental updates
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1, Days 1-4)
- Create `SqliteCacheBackend` class
- Implement schema with migration framework
- Add concurrent write safety (WAL, busy handler)
- Platform-specific configuration

**Deliverables:** 600 lines core code + 300 lines tests

---

### Phase 2: Integration & Testing (Week 1-2, Days 5-10)
- Integrate with CppAnalyzer
- Automatic migration from JSON
- Performance benchmarking
- Concurrent access testing
- Platform testing (Windows, Linux, macOS)

**Deliverables:** 400 lines integration + 250 lines benchmarks

---

### Phase 3: Optimization & Polish (Week 2-3, Days 11-18)
- Implement FTS5 full-text search
- Query performance monitoring
- Database maintenance (auto-vacuum)
- Prepared statements for hot paths

**Deliverables:** 150 lines FTS5 + 100 lines monitoring

---

### Phase 4: Production Readiness (Week 3, Days 19-24)
- Comprehensive documentation
- Safety mechanisms (backup, verify, repair)
- Monitoring & diagnostics tools
- Deployment guide

**Deliverables:** Complete docs + deployment tools

---

## Testing Strategy

### Unit Tests (95% coverage target)
- Schema creation and migration
- Symbol CRUD operations
- Concurrent write safety
- FTS5 search performance
- Platform-specific behavior

### Integration Tests
- Full indexing workflow
- Cache invalidation
- Migration integrity
- Incremental updates

### Performance Tests
- Startup time benchmarks
- Query performance
- Memory usage
- Disk space usage

### Stress Tests
- 10 concurrent writers
- 1M symbols dataset
- Network filesystem
- Database corruption recovery

---

## Rollout Plan

### Week 1-2: Alpha (Internal)
- Feature flag: `CLANG_INDEX_USE_SQLITE=1` (opt-in)
- Development projects only
- Monitor and fix issues

### Week 3: Beta
- Feature flag: Default ON
- All internal projects
- Collect feedback

### Week 4: GA
- Deploy to all users
- SQLite default, JSON fallback
- Monitor adoption

### Week 8+: Cleanup
- Remove JSON backend
- Remove feature flags
- Archive old code

---

## Risk Analysis

### Critical Risks (Mitigated)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss | Low | High | Auto-backup, verification, rollback |
| Performance regression | Medium | Medium | Benchmarking, auto-rollback |
| Database corruption | Low | High | WAL mode, integrity checks, auto-repair |
| Platform issues | Medium | Medium | Platform testing, fallback to JSON |

### Rollback Triggers

- SQLite error rate > 5% → Auto-fallback
- Startup time > 2x baseline → Auto-rollback
- Symbol count mismatch > 1% → Immediate rollback

---

## Questions for Review

### 1. Timeline
**Q:** Is 3.5 weeks acceptable?
**A:** Yes, includes all safety features and optimizations

### 2. FTS5 Full-Text Search
**Q:** Include in v3.0 or defer to v3.1?
**Recommendation:** Include in v3.0 (big performance win, low risk)

### 3. Network Filesystems
**Q:** Should we support network filesystems?
**Recommendation:** Support with warning (disable WAL mode)

### 4. Platform Support
**Q:** Windows, Linux, macOS?
**Recommendation:** All three (test matrix included)

### 5. Telemetry
**Q:** Add telemetry for adoption tracking?
**Recommendation:** Defer to v3.1 (privacy concerns)

---

## Next Steps

### If Approved:

1. ✅ Create feature branch (already on `claude/fix-cache-scalability-01AzJ96xJMbpLZ9Gbs9hShds`)
2. ⬜ Review and approve design
3. ⬜ Set up task tracking (GitHub issues/project)
4. ⬜ Begin Phase 1 implementation
5. ⬜ Weekly progress reviews

### If Changes Needed:

1. Provide feedback on design
2. Identify specific concerns
3. Revise design document
4. Re-review

---

## Files Generated

```
docs/design/
├── SUMMARY.md                           # This file
├── IMPLEMENTATION_PLAN.md               # ⭐ Main document to review
├── sqlite-cache-architecture.md         # Original comprehensive design
└── sqlite-cache-architecture-review.md  # Critical review with improvements
```

---

## Conclusion

The SQLite cache architecture is **production-ready** with:

✅ **Clear design** - Well-documented, reviewed, and improved
✅ **Safety features** - Concurrent writes, migrations, rollback
✅ **Performance targets** - 20x faster startup, 10x faster searches
✅ **Comprehensive testing** - Unit, integration, stress tests
✅ **Gradual rollout** - Feature flag, monitoring, auto-rollback

**Status:** 🟢 **Ready for Implementation**

---

**How to Review:**

1. Start with [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) (main document)
2. Review database schema and key features
3. Check implementation phases and timeline
4. Review testing strategy and rollout plan
5. Ask questions or provide feedback
6. Approve or request changes

**Estimated Review Time:** 30-45 minutes for main document
