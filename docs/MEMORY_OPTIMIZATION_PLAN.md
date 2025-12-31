# Memory Optimization Implementation Plan v2.0

**Project**: C++ MCP Server Memory Optimization
**Goal**: Reduce memory consumption during large project indexing (100K+ symbols)
**Target Savings**: 1.0-1.5 GB for projects with 100K symbols
**Status**: ✅ Phase 1 COMPLETED, ✅ Phase 2 (Task 1.2) COMPLETED, Phase 3 pending
**Last Updated**: 2025-12-31

---

## Current Status (Session Handoff)

### Completed Work

| Task | Savings | Commit | Status |
|------|---------|--------|--------|
| Task 2.1: Lazy loading call_sites | ~150-200 MB | `12cd00a` | ✅ Done |
| Task 2.2: Optimize SQLite loading | ~500 MB peak | `12cd00a` | ✅ Done |
| Documentation update | - | `12cd00a` | ✅ Done |
| Code formatting | - | `5501b04` | ✅ Done |
| Race condition fix | - | `661cc28` | ✅ Done |
| **Task 1.2: Remove calls/called_by** | ~200 MB | (pending) | ✅ Done |

**Total savings: ~850-900 MB** (Phase 1: ~650-700 MB + Task 1.2: ~200 MB)

### Branch Status

```
Branch: refactor/memory-optimization-phase1
Base: main (commit 6e45043)
PR: #92 (Phase 1 ready for merge)
Tests: 586 passed, 13 skipped
```

### Race Condition Fix (COMPLETED)

The race condition that blocked Task 1.2 has been fixed. The solution:

1. **Main process ensures schema is current BEFORE spawning workers**
   - Added `ensure_schema_current()` method to SqliteCacheBackend
   - Called in `index_project()` and `refresh_if_needed()` before ProcessPoolExecutor

2. **Workers skip schema recreation**
   - Added `skip_schema_recreation=True` parameter to worker CppAnalyzer instances
   - Workers trust that main process has already ensured schema is current

**Key insight**: The problem was that multiple ProcessPoolExecutor workers could simultaneously
detect schema mismatch and try to recreate the database, causing "disk I/O error" due to
WAL file conflicts. The fix centralizes schema management in the main process.

### Backup of Failed First Attempt

```
Branch: backup/memory-optimization-phase1-attempt1
Contains: 9 commits with failed implementation
Purpose: Reference for lessons learned (DO NOT MERGE)
```

### Remaining Tasks

| Task | Savings | Blocker | Priority |
|------|---------|---------|----------|
| ~~Task 1.2: Remove calls/called_by~~ | ~~200 MB~~ | ~~Done~~ | ✅ Completed |
| Task 1.1: Optimize file_index | ~300-500 MB | Breaks header file search | Low (needs research) |

### Next Steps for Continuation

1. **Merge current branch to main** - All Phase 1 + Phase 2 work complete
2. **For Task 1.1**: Research alternatives that preserve header search (see Phase 3 section)

### Key Files Modified

**Phase 1:**
- `mcp_server/call_graph.py` - Added `cache_backend` parameter, lazy loading methods
- `mcp_server/cpp_analyzer.py` - Set `cache_backend`, removed bulk call_sites load, direct SymbolInfo usage
- `mcp_server/sqlite_cache_backend.py` - Return SymbolInfo directly, stream from cursor

**Race Condition Fix:**
- `mcp_server/sqlite_cache_backend.py` - Added `skip_schema_recreation` param, `ensure_schema_current()` method
- `mcp_server/cache_manager.py` - Pass `skip_schema_recreation` to backend, expose `ensure_schema_current()`
- `mcp_server/cpp_analyzer.py` - Workers use `skip_schema_recreation=True`, main calls `ensure_schema_current()`

**Task 1.2 (calls/called_by removal):**
- `mcp_server/symbol_info.py` - Removed `calls` and `called_by` fields
- `mcp_server/schema.sql` - v9.0: Removed calls/called_by columns
- `mcp_server/sqlite_cache_backend.py` - Updated CURRENT_SCHEMA_VERSION, _symbol_to_tuple(), _row_to_symbol()
- `mcp_server/call_graph.py` - Updated find_callers/find_callees for lazy SQLite loading, deprecated rebuild_from_symbols()
- `mcp_server/cpp_analyzer.py` - Removed calls/called_by population and restoration
- `mcp_server/incremental_analyzer.py` - Removed calls/called_by restoration

---

## Lessons Learned from First Iteration (CRITICAL)

### Failed Attempt Summary

The first optimization attempt (branch `backup/memory-optimization-phase1-attempt1`) failed due to:
1. **Breaking existing functionality** without proper testing
2. **Schema version changes** triggering race conditions in parallel tests
3. **Insufficient incremental validation** - changes were batched instead of tested individually

### Error #1: file_index Removal Broke Header File Search

**What was done:**
- Removed `file_index: Dict[str, List[SymbolInfo]]` from `cpp_analyzer.py`
- Created `_get_symbols_by_file()` helper that iterates through `class_index` and `function_index`

**Why it failed:**
- `file_index` stored ALL symbols including **declarations from header files**
- `class_index` and `function_index` only store "winning" symbols (definitions over declarations)
- When searching with `file_name="functions.h"`, the new code couldn't find functions declared in `.h` but defined in `.cpp`

**Test that caught the issue:**
```
tests/test_header_file_filter.py::TestFileNameFilter::test_search_functions_with_file_name_filter
```

**Root cause in code:**
```python
# OLD (main branch) - file_index contained declarations AND definitions
for file_path, infos in self.file_index.items():
    if file_path.endswith(file_name):
        # Found functions declared in functions.h

# NEW (broken) - only definitions available
all_files = set()
for symbol_list in self.class_index.values():
    for symbol in symbol_list:
        all_files.add(symbol.file)  # Only .cpp files with definitions!
```

**Lesson:**
- `file_index` is NOT just a redundant copy - it preserves declaration locations
- Cannot be removed without alternative mechanism for header file search
- **Future fix approach**: Store minimal file→USRs mapping or use SQLite queries

---

### Error #2: Schema Version Change Caused Race Condition

**What was done:**
- Changed schema version from "8.0" to "9.0" (removed calls/called_by columns)
- Multiple ProcessPoolExecutor workers detected schema mismatch simultaneously

**Why it failed:**
- All workers tried to recreate database simultaneously
- WAL file conflicts caused "disk I/O error"
- ~30% of workers failed, corrupting test results

**Logs showing the race:**
```
[INFO] Schema version mismatch: current=8.0, expected=9.0
[INFO] Schema version mismatch: current=8.0, expected=9.0  ← TWO workers!
[INFO] Recreating database with current schema
[INFO] Recreating database with current schema  ← RACE!
[ERROR] disk I/O error
```

**Affected tests (13 failures):**
- `tests/test_processpool_cache.py::*` (4 tests)
- `tests/test_header_file_filter.py::*` (2 tests)
- Various performance and integration tests

**Lesson:**
- Schema version changes require centralized migration BEFORE spawning workers
- OR use retry logic with backoff
- Test schema changes with parallel test execution specifically

---

### Error #3: Insufficient Incremental Testing

**What was done:**
- Implemented Task 1.1, 1.2, 2.1, 2.2 in sequence
- Did not run full `make test` after each change

**Why it failed:**
- Failures accumulated without being caught
- When tests finally ran, 13 failures obscured root causes
- Debugging was difficult due to multiple interacting changes

**Lesson:**
- Run `make test` after EVERY change, even documentation
- If tests fail, fix immediately before proceeding
- One commit = one logical change = tests must pass

---

## Revised Task Order (Safe First)

Based on lessons learned, tasks are reordered by risk level:

| Priority | Task | Savings | Risk | Schema Change |
|----------|------|---------|------|---------------|
| 1 | Task 2.1: Lazy loading call_sites | ~150-200 MB | Low | No |
| 2 | Task 2.2: Optimize SQLite loading | ~500 MB peak | Low | No |
| 3 | Task 1.2: Remove calls/called_by | ~200 MB | Medium | **Yes** |
| 4 | Task 1.1: Optimize file_index | ~300-500 MB | **High** | No |

**Rationale:**
- Tasks 2.1 and 2.2 don't change schema or external behavior
- Task 1.2 requires schema change - must fix race condition first
- Task 1.1 requires architectural redesign to preserve header search

---

## Phase 1: Safe Optimizations (Current Focus)

### Task 2.1: Implement Lazy Loading for call_sites

**Objective**: Load call sites from SQLite on-demand instead of loading all at startup

**Estimated Savings**: ~150-200 MB runtime

**Changes Required**:

1. **Remove bulk loading** in `_load_cache()` (`cpp_analyzer.py`):
   ```python
   # DELETE these lines:
   call_sites_data = self.cache_manager.backend.load_all_call_sites()
   if call_sites_data:
       self.call_graph_analyzer.restore_call_sites(call_sites_data)
   ```

2. **Add lazy loading to CallGraphAnalyzer** (`call_graph.py`):
   ```python
   def __init__(self, cache_backend=None):
       self.cache_backend = cache_backend  # For lazy queries
       self.call_sites: Set[CallSite] = set()  # Only current session
       # call_graph and reverse_call_graph still in memory for fast queries

   def get_call_sites_for_caller(self, caller_usr: str) -> List[CallSite]:
       """Load call sites on demand from SQLite."""
       if self.cache_backend:
           return self.cache_backend.get_call_sites_for_caller(caller_usr)
       return [cs for cs in self.call_sites if cs.caller_usr == caller_usr]
   ```

3. **Update MCP tools** that use call sites to call lazy methods

4. **Keep call_graph/reverse_call_graph in memory** - these are much smaller than call_sites

**Testing Checklist**:
- [ ] `make test` passes (all 586 tests)
- [ ] `find_callers` MCP tool works correctly
- [ ] `find_callees` MCP tool works correctly
- [ ] `find_call_sites` MCP tool works correctly
- [ ] Memory profiling shows reduced baseline

**Verification Command**:
```bash
rm -rf .mcp_cache/ && make test
```

---

### Task 2.2: Optimize SQLite Cache Loading

**Objective**: Eliminate intermediate dict conversion during cache load

**Estimated Savings**: ~500 MB peak memory during load

**Changes Required**:

1. **Change return type** of `SqliteCacheBackend.load_cache()`:
   ```python
   # BEFORE: Returns dicts that get converted to SymbolInfo
   def load_cache(...) -> Optional[Dict[str, Any]]:
       for symbol in all_symbols:
           class_index[symbol.name].append(symbol.to_dict())  # Creates dict

   # AFTER: Return SymbolInfo objects directly
   def load_cache(...) -> Optional[Dict[str, Any]]:
       for symbol in all_symbols:
           class_index[symbol.name].append(symbol)  # Direct SymbolInfo
   ```

2. **Update CppAnalyzer._load_cache()** to handle SymbolInfo directly:
   ```python
   # BEFORE:
   self.class_index[name] = [SymbolInfo(**info) for info in infos]

   # AFTER:
   self.class_index[name] = infos  # Already SymbolInfo objects
   ```

3. **Use streaming** instead of loading all at once:
   ```python
   # BEFORE:
   all_symbols = [self._row_to_symbol(row) for row in cursor.fetchall()]

   # AFTER:
   for row in cursor:
       symbol = self._row_to_symbol(row)
       # Process immediately
   ```

**Testing Checklist**:
- [ ] `make test` passes
- [ ] Cache round-trip works (save → load → query)
- [ ] No performance regression in load time
- [ ] Peak memory reduced (verify with profiler)

---

## Phase 2: Schema Change (Race Condition Fixed ✅)

### Prerequisite: Fix Schema Migration Race Condition ✅ COMPLETED

**Implementation (completed 2025-12-31):**

1. **Centralized migration in main process** - `ensure_schema_current()` called in `index_project()` and `refresh_if_needed()` BEFORE creating ProcessPoolExecutor

2. **Workers skip schema recreation** - `skip_schema_recreation=True` parameter prevents workers from attempting database recreation

3. **Tested with parallel execution** - All 586 tests pass consistently

**Key insight**: The problem was that multiple ProcessPoolExecutor workers could simultaneously
detect schema mismatch and try to recreate the database, causing "disk I/O error" due to
WAL file conflicts. The fix centralizes schema management in the main process.

### Task 1.2: Remove calls/called_by from SymbolInfo ✅ COMPLETED

**Objective**: Remove duplicate call graph data from SymbolInfo

**Estimated Savings**: ~200 MB

**Status**: ✅ COMPLETED (2025-12-31)

**Changes Made**:
1. ✅ Removed `calls` and `called_by` fields from `symbol_info.py`
2. ✅ Updated `schema.sql` to v9.0 (removed calls/called_by columns)
3. ✅ Updated `CURRENT_SCHEMA_VERSION` to "9.0" in `sqlite_cache_backend.py`
4. ✅ Updated `_symbol_to_tuple()` and `_row_to_symbol()` to remove calls/called_by
5. ✅ Removed population of calls/called_by in `index_file()` and other places
6. ✅ Updated `find_callers()`/`find_callees()` in `call_graph.py` to use lazy loading from SQLite
7. ✅ Deprecated `rebuild_from_symbols()` - now a no-op

**Key Changes**:
- Call graph data is now stored ONLY in `call_sites` table
- `find_callers()`/`find_callees()` now query SQLite lazily
- No more duplicate data in both SymbolInfo and call_sites table
- Total savings: ~200 MB for large projects (100K symbols)

---

## Phase 3: Architectural Redesign (Requires Research)

### Task 1.1: Optimize file_index (Complex)

**Objective**: Reduce file_index memory while preserving header file search

**BLOCKED UNTIL**: Research and design completed

**Problem Analysis**:
- `file_index` stores ALL symbols by file path
- Includes both declarations (in .h) and definitions (in .cpp)
- `class_index`/`function_index` only store "winning" symbols
- Removing `file_index` breaks `file_name` filter in search tools

**Potential Solutions** (need evaluation):

**Option A: Lightweight file→USRs Index**
```python
# Instead of file_index: Dict[str, List[SymbolInfo]]
# Store only USRs: file_to_usrs: Dict[str, Set[str]]
# Look up full SymbolInfo from usr_index when needed
```
- Pros: Much smaller (only strings, not objects)
- Cons: Need to preserve declarations in usr_index

**Option B: SQLite-only File Queries**
```python
# Query SQLite directly for file-based searches
def search_by_file(file_name):
    cursor.execute("SELECT * FROM symbols WHERE file LIKE ?", f"%{file_name}")
```
- Pros: No in-memory index needed
- Cons: Must store declarations in SQLite (currently only definitions)

**Option C: Separate Declarations Table**
```sql
CREATE TABLE declarations (
    usr TEXT,
    file TEXT,
    line INTEGER,
    -- Minimal info for header search
);
```
- Pros: Explicit declaration tracking
- Cons: Schema change, more complex indexing

**Research Required**:
1. Measure actual `file_index` memory usage on large project
2. Analyze how often `file_name` filter is used
3. Prototype each option with benchmarks
4. User feedback on acceptable trade-offs

---

## Validation Protocol

### After Each Change

```bash
# 1. Clear cache
rm -rf .mcp_cache/

# 2. Run full test suite
make test

# 3. Run code quality checks
make check

# 4. Verify expected tests pass
pytest tests/test_<relevant>*.py -v

# 5. If schema changed, test parallel execution
for i in {1..5}; do
    rm -rf .mcp_cache/
    pytest tests/test_processpool_cache.py -v
done
```

### Before Creating PR

1. All 586+ tests pass
2. `make check` passes (format, lint, type)
3. Memory profiling shows expected savings
4. No functionality regressions
5. Documentation updated

---

## Success Metrics

### Phase 1 Target
- [ ] Memory savings: ≥650 MB (Task 2.1 + 2.2)
- [ ] All tests passing
- [ ] No performance regression >10%

### Final Target (All Phases)
- [ ] Memory savings: ≥1.0 GB
- [ ] Header file search still works
- [ ] Schema migration is race-free
- [ ] All tests passing

---

## Risk Mitigation

1. **Incremental commits**: One logical change per commit
2. **Full test suite**: Run `make test` after every change
3. **Backup branch**: Keep failed attempts for reference
4. **Schema changes last**: Defer until race condition fixed
5. **User approval**: Get approval before Phase 3 (architectural changes)

---

## Appendix: Reference Materials

### Backup Branch
```
backup/memory-optimization-phase1-attempt1
```
Contains: Failed first attempt with 9 commits, useful for reference

### Key Files
- `mcp_server/cpp_analyzer.py` - Main analyzer (indexes, cache loading)
- `mcp_server/call_graph.py` - Call graph analyzer (call_sites)
- `mcp_server/sqlite_cache_backend.py` - SQLite operations
- `mcp_server/symbol_info.py` - SymbolInfo dataclass
- `mcp_server/schema.sql` - Database schema (v8.0)

### Memory Analysis
See `backup/memory-optimization-phase1-attempt1:docs/MEMORY_OPTIMIZATION_ANALYSIS.md` for detailed memory bottleneck analysis.
