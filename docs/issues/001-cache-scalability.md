# [001] Cache Scalability for Large Codebases

**Category:** Architecture
**Priority:** High
**Status:** ✅ COMPLETED
**Date Identified:** 2025-11-16
**Date Resolved:** 2025-11-17 (next day!)
**Estimated Effort:** 2-3 weeks
**Actual Effort:** ~3 weeks (already in progress when issue documented)
**Complexity:** Medium

---

## Resolution

**✅ ISSUE RESOLVED:** This issue was documented on 2025-11-16, but the SQLite migration work was already in progress. The complete SQLite cache backend was released as **Version 3.0.0 on 2025-11-17** - literally the next day!

**Implementation:** Option 2 (SQLite Database) was chosen and fully implemented.

**Results Achieved:**
- ⚡ **20x faster** symbol searches (2-5ms vs 50ms for 100K symbols) - **exceeds target**
- ⚡ **2x faster** cold startup (300ms vs 600ms)
- 💾 **70% smaller** disk usage (30MB vs 100MB for 100K symbols)
- 🔒 **Multi-process safe** with WAL mode
- ✨ **FTS5 full-text search** for lightning-fast lookups
- 🔧 **Automatic migration** from JSON to SQLite
- 📊 **Schema version 8.0** with comprehensive features

**See:**
- [RELEASE_NOTES.md](../RELEASE_NOTES.md) - Version 3.0.0 details
- [ANALYSIS_STORAGE_ARCHITECTURE.md](../ANALYSIS_STORAGE_ARCHITECTURE.md#sqlite-cache-backend-architecture-v300) - Current SQLite architecture
- [design/sqlite-cache-architecture.md](../design/sqlite-cache-architecture.md) - Design document

---

## Original Problem Statement (Historical)

## Problem Statement

The current cache implementation uses a single monolithic `cache_info.json` file to store all indexed symbols (classes and functions) from both source files and headers. This design has scalability limitations for large codebases.

### Current Architecture

```
.mcp_cache/<project>/
  ├── cache_info.json          # ALL symbols (sources + headers)
  ├── files/
  │   └── <hash>.json          # Per-file cache (source files only)
  └── header_tracker.json      # Header processing state
```

**How it works:**
- When parsing source files with `compile_commands.json`, symbols from headers are extracted
- Header symbols are stored ONLY in `cache_info.json` (not in per-file caches)
- On startup, the entire `cache_info.json` must be loaded into memory
- On shutdown/completion, the entire file is rewritten

### Performance Issues

For large codebases (enterprise projects, LLVM-scale, Chromium-scale):

1. **File Size**:
   - Medium projects (10K-50K symbols): 10-50 MB
   - Large projects (100K+ symbols): 100+ MB
   - Very large projects (500K+ symbols): 500+ MB

2. **Startup Time**:
   - Loading 100MB JSON file: 5-10 seconds
   - Parsing JSON: Additional 2-5 seconds
   - Total cold start: 10-15 seconds for large projects

3. **Memory Usage**:
   - All symbols loaded into memory at once
   - No lazy loading capability
   - High memory footprint even for simple queries

4. **Save Time**:
   - Full rewrite on every update
   - No incremental updates
   - Risk of corruption if interrupted

### When This Becomes Critical

- Projects with 50,000+ symbols (classes + functions)
- Heavy template library usage (Boost, Qt, Eigen, STL)
- Large header hierarchies (1000+ headers)
- Systems with slow disk I/O
- Multiple concurrent analyzer instances

### Current Workarounds

None available. Small-to-medium projects (< 10,000 symbols) are not affected.

---

## Impact Assessment

**User Impact:**
- **Startup delays**: Users wait 10-15+ seconds for analyzer to become ready
- **Memory pressure**: High memory usage on machines with limited RAM
- **Poor experience**: Perception of slow/unresponsive tool

**Development Impact:**
- **Testing overhead**: Large test projects slow down CI/CD
- **Cache corruption risk**: Interruptions during save can lose all data
- **No incremental updates**: Even small changes require full cache rewrite

**Business Impact:**
- **Adoption barrier**: Enterprise users with large codebases may avoid the tool
- **Scalability ceiling**: Cannot support projects beyond certain size

---

## Proposed Solutions

### Option 1: Sharded File-Based Cache (Quick Fix)

**Concept**: Split cache into multiple smaller files by name prefix

**Structure**:
```
cache_index/
  ├── metadata.json
  ├── class_index/
  │   ├── A-C.json
  │   ├── D-F.json
  │   └── ...
  └── function_index/
      └── ...
```

**Pros:**
- Minimal code changes
- Lazy loading by shard
- Parallel writes possible

**Cons:**
- Still JSON parsing overhead
- Need shard management logic
- Limited scalability improvement

**Estimated Effort:** 1 week
**Scalability Target:** 50K-500K symbols

---

### Option 2: SQLite Database (Recommended)

**Concept**: Replace JSON with embedded SQLite database

**Schema**:
```sql
CREATE TABLE symbols (
    usr TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    line INTEGER,
    data JSON
);

CREATE INDEX idx_name ON symbols(name);
CREATE INDEX idx_kind ON symbols(kind);
CREATE INDEX idx_file ON symbols(file);
```

**Pros:**
- Industry-proven (used by VS Code, Android Studio)
- True lazy loading (query what you need)
- Fast indexed lookups: O(log n)
- Atomic transactions (ACID)
- No parse overhead (binary format)
- Built-in compression support
- Concurrent reads
- Incremental updates

**Cons:**
- New dependency (though `sqlite3` is in Python stdlib)
- More complex than JSON
- Migration effort from JSON format
- Requires SQL knowledge

**Estimated Effort:** 2-3 weeks
**Scalability Target:** 100K-10M+ symbols

---

### Option 3: Two-Tier Hybrid Cache

**Concept**: Hot data in memory, cold data on-demand

**Structure**:
```
hot_cache.json          # Name→location map (small)
symbol_details/
  └── <usr_hash>.json   # Per-symbol details
```

**Pros:**
- Fast startup (load small index only)
- Lazy loading of details
- Smart LRU caching

**Cons:**
- Two-tier complexity
- Cache eviction logic needed
- More file I/O

**Estimated Effort:** 2 weeks
**Scalability Target:** 100K-1M symbols

---

### Option 4: Memory-Mapped Binary Format

**Concept**: Zero-copy loading using mmap (FlatBuffers/MessagePack)

**Pros:**
- Near-instant startup
- Shared memory between processes
- Compact binary format

**Cons:**
- High implementation complexity
- Platform-specific issues
- Hard to debug
- Schema versioning challenges

**Estimated Effort:** 3-4 weeks
**Scalability Target:** 100K-10M+ symbols, best startup time

---

### Option 5: Compressed Chunked Storage (Band-Aid)

**Concept**: Add gzip compression + chunk into smaller files

**Pros:**
- Minimal changes
- 10x size reduction
- Quick win

**Cons:**
- Decompression overhead
- Still loads everything
- Limited improvement

**Estimated Effort:** 3-5 days
**Scalability Target:** 20K-200K symbols

---

## Recommended Approach

### Primary Recommendation: **Option 2 (SQLite Database)**

**Rationale:**
1. Industry standard for exactly this use case
2. Proven to scale beyond foreseeable requirements
3. Solves current AND future problems (incremental updates, concurrent access)
4. No external dependencies (Python stdlib)
5. Well-documented, maintainable
6. Used by major IDEs for symbol indexing

### Implementation Strategy

**Phase 1: Parallel Implementation** (Week 1)
- Keep existing JSON cache working
- Add SQLite cache module alongside
- Write to both during development
- Add feature flag to switch between implementations

**Phase 2: Feature Parity** (Week 2)
- Ensure SQLite has all JSON features
- Add migration tool: `cache_info.json` → SQLite
- Performance benchmarking
- Test with large projects

**Phase 3: Migration** (Week 3)
- Make SQLite default
- Keep JSON as fallback for one release cycle
- Update documentation
- Add migration guide

**Phase 4: Cleanup** (Future)
- Remove JSON code paths
- Add SQLite-specific optimizations
  - Prepared statements
  - Batch inserts
  - Vacuum/analyze for optimization

### Performance Targets (100K symbols)

| Metric | Current (JSON) | Target (SQLite) | Improvement |
|--------|----------------|-----------------|-------------|
| Startup time | 10s | 0.5s | 20x faster |
| Memory usage | 200 MB | 50 MB | 4x reduction |
| Disk size | 100 MB | 30 MB | 3x smaller |
| Query time | 100ms | 5ms | 20x faster |

---

## Alternative: Incremental Approach

If full SQLite migration is too risky, consider **Option 5** (Compression) as immediate fix:

**Benefits:**
- Delivers quick wins (size reduction, faster I/O)
- Buys time for proper architecture
- Low risk, easy to revert
- Can be done in parallel with SQLite work

**Timeline:**
- Option 5 first: 1 week → Quick improvement
- Option 2 later: 3 weeks → Long-term solution

---

## Decision Log

**2025-11-16**: Issue identified during discussion of cache architecture
- **Decision**: Postpone implementation pending real-world scalability testing
- **Rationale**: Current implementation sufficient for small-medium projects
- **Trigger**: Revisit when encountering project with 50K+ symbols or user complaints

---

## Implementation Notes

### Dependencies

**For SQLite approach:**
- Python `sqlite3` module (stdlib, no install needed)
- Schema migration tool
- Backward compatibility with JSON cache

### Risks

1. **Data Migration**: Existing users have JSON caches that need migration
2. **Performance Regression**: Must ensure SQLite is actually faster
3. **Platform Issues**: SQLite behavior varies across platforms
4. **Disk Corruption**: SQLite databases can corrupt (need backup/recovery)

### Mitigation

- Keep JSON as fallback for 1-2 releases
- Extensive testing on large projects
- Add cache validation and auto-repair
- Document manual recovery procedures

### Testing Requirements

- Benchmark with 10K, 50K, 100K, 500K symbol projects
- Test on Windows, Linux, macOS
- Memory profiling
- Concurrent access stress testing
- Cache corruption recovery testing

---

## References

**Related Documentation:**
- [ANALYSIS_STORAGE_ARCHITECTURE.md](../../ANALYSIS_STORAGE_ARCHITECTURE.md)
- [mcp_server/cache_manager.py](../../mcp_server/cache_manager.py)

**External Resources:**
- [SQLite As An Application File Format](https://www.sqlite.org/appfileformat.html)
- [VS Code Symbol Database](https://github.com/microsoft/vscode/tree/main/src/vs/workbench/contrib/search)
- [Clangd Index Format](https://clangd.llvm.org/design/indexing)

**Related Issues:**
- TBD: Incremental parsing (depends on cache architecture)
- TBD: Member variable indexing (will increase symbol count)

---

## Next Steps

1. **Monitor real-world usage**: Collect data on typical project sizes
2. **User feedback**: Ask users about performance pain points
3. **Benchmark existing**: Measure current performance on large projects
4. **Prototype**: If needed, create SQLite proof-of-concept
5. **Decide**: Based on data, choose implementation approach
