# Issue Fixing Plan - Prioritized Roadmap

**Created:** 2025-12-21
**Last Updated:** 2025-12-25
**Status:** ✅ **ALL CRITICAL ISSUES FIXED** - Phases 1-3 Complete

## Executive Summary

Analysis of 13 documented issues from manual testing sessions (Linux + macOS). **All critical and medium-priority issues have been successfully fixed across Phases 1-3.**

### Completion Status:
- ✅ **Phase 1: Workflow Foundation** - COMPLETE (Issues #10, #1)
- ✅ **Phase 2: Refresh Correctness** - COMPLETE (Issues #13, #12, #8)
- ✅ **Phase 3: UX Enhancements** - COMPLETE (Issues #11, #6)
- 📋 **Phase 4: Deferred Issues** - For future consideration (Issues #4, #5, #7, #9)

### Quick Reference - Fixed Issues:
- ✅ **Issue #1** - State synchronization race (PR #66, commit dfa65e6)
- ✅ **Issue #2** - refresh_project timeout (PR #63, commit e155aba)
- ✅ **Issue #3** - File descriptor leak (PR #62, commits 2e6700f, 9b2a3b1, etc.)
- ✅ **Issue #6** - Sequential processing in refresh (PR #73, commits fd1d513, 414698b)
- ✅ **Issue #8** - Missing header symbols (PR #71, commits cded32c, 66474f1)
- ✅ **Issue #10** - Zero file counts in status (PR #64, commit 939a257)
- ✅ **Issue #11** - Missing progress reporting (PR #72, commit c33042e)
- ✅ **Issue #12** - Database connection lifecycle (PR #69, commit fcc90fa)
- ✅ **Issue #13** - Headers with fallback args (PR #67, commit 69f7378)

## Testing Workflow Analysis

From tester perspective, typical workflow:
```
set_project_directory → get_indexing_status → get_server_status → refresh_project
```

### Impact by Workflow Step

**Step 1: `set_project_directory`**
- ~~Issue #1~~ ✅ Race condition - **FIXED** in PR #66
- ~~Issue #3~~ ✅ FD leak - **FIXED** in PR #62

**Step 2: `get_indexing_status`**
- ✅ No issues (works correctly)

**Step 3: `get_server_status`**
- ~~Issue #10~~ ✅ Reports zero files - **FIXED** in PR #64

**Step 4: `refresh_project`**
- ~~Issue #2~~ ✅ Timeout - **FIXED** in PR #63
- ~~Issue #11~~ ✅ No progress reporting - **FIXED** in PR #72
- ~~Issue #12~~ ✅ Database connection errors - **FIXED** in PR #69
- ~~Issue #13~~ ✅ Headers with wrong compilation args - **FIXED** in PR #67
- ~~Issue #8~~ ✅ Missing headers after refresh - **FIXED** in PR #71
- ~~Issue #6~~ ✅ Sequential processing - **FIXED** in PR #73

---

## Critical Issue Dependencies

### Dependency Chain (Must Fix in Order)

```
Issue #13: Headers Re-Analyzed with Fallback Args
    ↓ causes
Issue #8: Missing Headers After Refresh
    ↑ also caused by
Issue #12: Database Connection Lifecycle Bug
```

**Explanation:**
- **Issue #13** causes headers to be re-analyzed with fallback args (missing boost, vcpkg paths)
  - Parse failures → symbols not extracted → missing from database
- **Issue #12** causes dependency tracking to fail during refresh
  - Headers not properly tracked → missing from database
- **Issue #8** is likely a **symptom** of both #13 and #12, not separate root cause
  - **Strategy:** Fix #13 and #12 first, then re-test #8 (may disappear)

### Pattern Similarity

```
Issue #2: refresh_project timeout (FIXED in current branch)
    ↓ same async pattern applies to
Issue #1: set_project_directory state race (NEEDS FIX)
```

Both need async operation with immediate return. Fix for #2 serves as template for #1.

---

## Prioritized Fixing Order

### Phase 1: Workflow Foundation ✅ COMPLETE
**Quick wins to enable reliable testing**

#### 1. Issue #10: get_server_status Reports Zero Files ✅ FIXED
- **Status:** ✅ **FIXED** in PR #64 (commit 939a257)
- **Priority:** HIGH (2-minute fix, immediate improvement)
- **Impact:** All platforms
- **Root cause:** Regression from FD leak fix (commit 2e6700f)
  - Removed `self.translation_units` dict (was causing FD leak)
  - But `get_server_status` still references it → returns 0
- **Location:** `mcp_server/cpp_mcp_server.py:997,1000`
- **Fix Applied:**
  ```python
  # OLD (broken):
  "parsed_files": len(analyzer.translation_units),    # Dict no longer exists!
  "project_files": len(analyzer.translation_units),

  # NEW (correct):
  "parsed_files": len(analyzer.file_index),
  "project_files": len(analyzer.file_index),
  ```
- **Validation:** ✅ Status now shows correct file counts after indexing
- **Effort:** 2 lines changed
- **Risk:** None (simple replacement)

---

#### 2. Issue #1: set_project_directory State Synchronization Race ✅ FIXED
- **Status:** ✅ **FIXED** in PR #66 (commit dfa65e6)
- **Priority:** HIGH (blocks workflow step 1→2)
- **Impact:** All platforms
- **Symptom:** `get_indexing_status` fails immediately after `set_project_directory`
  - First call succeeds: "Indexing started in background"
  - Immediate status query: "Error: Project directory not set"
  - Wait few seconds, query again: Works correctly
- **Root cause:** State not set immediately, only after background work starts
- **Location:** `mcp_server/cpp_mcp_server.py` - `set_project_directory` handler
- **Fix Applied:** Applied same async pattern as Issue #2 fix
  - Set state immediately before starting background indexing
  - Return success message
  - Background indexing continues asynchronously
- **Validation:** ✅ `get_indexing_status` works immediately after `set_project_directory`
- **Effort:** Low (template exists from Issue #2)
- **Risk:** Low (proven pattern)

---

### Phase 2: Refresh Correctness ✅ COMPLETE
**Fix in dependency order - critical for data integrity**

#### 3. Issue #13: Headers Re-Analyzed with Fallback Args ✅ FIXED
- **Status:** ✅ **FIXED** in PR #67 (commit 69f7378)
- **Priority:** CRITICAL (must fix before Issue #8)
- **Impact:** Parse errors during refresh (missing boost, vcpkg, Foundation headers)
- **Symptom:** During refresh, headers parsed with fallback args instead of proper compile_commands.json args
  ```
  [WARNING] /path/to/File.h: Continuing despite 1 error(s):
  [fatal] 'boost/preprocessor/cat.hpp' file not found
  ```
- **Root cause:** `ChangeScanner` incorrectly categorizes headers as "source files"
  1. `find_cpp_files()` returns BOTH `.cpp` AND `.h` files
  2. `change_scanner.py:171` scans all as "source files"
  3. Modified headers added to `changeset.modified_files` (line 186)
  4. `incremental_analyzer.py:141-143` directly re-analyzes them
  5. Headers not in `compile_commands.json` → fallback args used
  6. Fallback args lack third-party include paths → parse errors

- **Why initial indexing works:**
  - Headers processed as dependencies of source files
  - Source files have proper compile args from compile_commands.json
  - Headers inherit those args when included

- **Why refresh fails:**
  - Headers detected as standalone "modified files"
  - Directly re-analyzed independent of source files
  - No compile args available → fallback used

- **Location:** `mcp_server/change_scanner.py:171-186`
- **Fix Applied (Option 1):** Filter headers from directory scan
  ```python
  # change_scanner.py:171-177
  current_source_files = set()
  for file_path in self.analyzer.file_scanner.find_cpp_files():
      # Skip headers - they'll be detected via header_tracker
      if file_path.endswith(('.h', '.hpp', '.hxx', '.h++')):
          continue
      current_source_files.add(file_path)
  ```

- **Validation:** ✅ Confirmed
  - No boost/Foundation header errors during refresh
  - Headers only processed as dependencies of .cpp files
  - Same compile args used for headers during initial indexing and refresh

- **Effort:** Low (small code change, well-defined problem)
- **Risk:** Low (clear logic fix)

---

#### 4. Issue #12: Database Connection Lifecycle Bug ✅ FIXED
- **Status:** ✅ **FIXED** in PR #69 (commit fcc90fa)
- **Priority:** CRITICAL (must fix before Issue #8)
- **Impact:** Dependency tracking fails during refresh
- **Symptom:** During refresh, warnings appear:
  ```
  [WARNING] Failed to update dependencies for /path/to/File.h:
  Cannot operate on a closed database.
  ```
- **Root cause:** Shared SQLite connection with mismatched lifecycle
  1. `cpp_analyzer.py:270` - DependencyGraphBuilder created with shared connection
  2. `cpp_analyzer.py:310` - cache_manager.close() closes the shared connection
  3. DependencyGraphBuilder still holds reference to closed connection
  4. Operations fail: `self.conn.cursor()` → "Cannot operate on a closed database"

- **Location:**
  - Connection sharing: `mcp_server/cpp_analyzer.py:270`
  - Connection closing: `mcp_server/cpp_analyzer.py:310`
  - Failed usage: `mcp_server/dependency_graph.py:173`

- **Fix Applied:** Separate dependency connection (Option 2)
  ```python
  # Create separate connection for dependency_graph
  self.dependency_graph = DependencyGraphBuilder(
      sqlite3.connect(db_path)  # Own connection, not shared
  )
  ```

- **Validation:** ✅ Confirmed
  - No "closed database" warnings during refresh
  - Dependencies updated for all re-analyzed files
  - Dependency graph integrity maintained after refresh

- **Effort:** Medium (connection lifecycle management)
- **Risk:** Medium (database operations, thorough testing performed)

---

#### 5. Issue #8: Missing Headers After Refresh ✅ FIXED
- **Status:** ✅ **FIXED** in PR #71 (commits cded32c, 66474f1)
- **Priority:** CRITICAL (data integrity issue)
- **Impact:** Header files and symbols disappear after refresh
- **Symptom:**
  - After refresh, search for known header files: no results
  - Search for classes defined in headers: no results
  - Suggests headers were not indexed or data was deleted

- **Confirmed Root Cause:** Headers incorrectly marked as deleted during refresh
  - After fixing #13 and #12, issue still persisted
  - Investigation revealed headers being marked for deletion incorrectly
  - Incremental refresh logic treating headers as stale/deleted files

- **Fix Applied:** Two-part fix
  1. **Partial fix (commit cded32c):** Prevent headers from being marked as deleted
     - Modified incremental analyzer to preserve header tracking state
     - Prevented false deletion of header symbols

  2. **Complete fix (commit 66474f1):** Ensure header symbols persist correctly
     - Fixed header tracking state preservation across refresh operations
     - Ensured header symbols remain in database after refresh
     - Validated header dependency tracking maintains integrity

- **Validation:** ✅ Confirmed
  - Header files found after incremental refresh
  - Header symbols found after refresh (classes, functions in headers)
  - Same results before and after refresh
  - No false deletion of header data

- **Effort:** Medium (required investigation after #13 + #12)
- **Risk:** Medium (critical data integrity fix, thoroughly tested)

---

### Phase 3: UX Enhancements ✅ COMPLETE
**Non-blocking improvements**

#### 6. Issue #11: refresh_project Missing Progress Reporting ✅ FIXED
- **Status:** ✅ **FIXED** in PR #72 (commit c33042e)
- **Priority:** MEDIUM (UX enhancement, not blocking)
- **Impact:** No visibility during refresh (inconsistent with initial indexing)
- **Symptom:** During refresh, `get_indexing_status` returns `progress: null`
  - Initial indexing shows: indexed_files, total_files, completion_percentage, ETA
  - Refresh shows: `progress: null` for entire operation

- **Root cause:** Progress tracking not implemented for refresh operations
  - `set_project_directory` → passes `progress_callback` to `index_project()`
  - `refresh_project` → calls `refresh_if_needed()` with NO progress_callback
  - Neither `refresh_if_needed()` nor `perform_incremental_analysis()` accepts callback

- **Location:**
  - `cpp_analyzer.py:2158` - `refresh_if_needed()`
  - `incremental_analyzer.py:89` - `perform_incremental_analysis()`
  - `cpp_mcp_server.py` - `run_background_refresh()`

- **Fix Applied:** Added progress callback support
  1. Added `progress_callback` parameter to refresh methods
  2. Updated `run_background_refresh` to create and pass callback
  3. Modified `_reanalyze_files` to report progress during file processing

- **Validation:** ✅ Confirmed
  - `get_indexing_status` now shows progress during refresh
  - Progress updates correctly during long refreshes
  - Progress resets to null after completion

- **Effort:** Medium (architectural change across multiple files)
- **Risk:** Low (additive change, doesn't affect existing functionality)

---

#### 7. Issue #6: Sequential Processing in Incremental Refresh ✅ FIXED
- **Status:** ✅ **FIXED** in PR #73 (commits fd1d513, 414698b)
- **Priority:** MEDIUM (performance optimization, not blocking)
- **Impact:** Incremental refresh slower than necessary
- **Symptom:** Refresh uses fewer subprocesses than initial indexing
  - Initial indexing: full ProcessPoolExecutor with multiple workers (6-7x speedup)
  - Incremental refresh: was using sequential processing

- **Root Cause:** Incremental refresh used sequential file processing loop
  - `_reanalyze_files()` processed files one-by-one
  - Did not leverage ProcessPoolExecutor for parallel execution
  - Different code path from initial indexing

- **Location:**
  - `mcp_server/cpp_analyzer.py` - `refresh_project()` method
  - `mcp_server/incremental_analyzer.py` - re-analysis implementation

- **Fix Applied:** Refactored to use ProcessPoolExecutor
  - Modified `_reanalyze_files()` to use parallel processing
  - Reuses same ProcessPoolExecutor pattern as initial indexing
  - Achieves 6-7x speedup on refresh operations

- **Validation:** ✅ Confirmed
  - Refresh now uses full ProcessPoolExecutor with multiple workers
  - Performance matches initial indexing (6-7x speedup on multi-core)
  - Parallel processing verified during incremental refresh

- **Effort:** Medium (refactored refresh path for parallelism)
- **Risk:** Low (performance optimization, thoroughly tested)

---

### Phase 4: Deferred Issues
**Handle separately or in future work**

- **Issue #4:** Class search uses substring matching (minor usability)
- **Issue #5:** Tool descriptions misleading (affects small models only)
- **Issue #7:** Unauthorized full refresh (important but separate concern)
- **Issue #9:** libclang paths on macOS (platform-specific, workaround exists)

---

## Testing Strategy

### Manual Testing Workflow

For each fix, follow standard testing workflow:

1. **Setup:**
   - Start MCP server (SSE mode recommended for debugging)
   - Choose test project (examples/compile_commands_example or larger project)

2. **Initial indexing:**
   - Call `set_project_directory`
   - Monitor `get_indexing_status` until complete
   - Call `get_server_status` to verify file counts

3. **Verify baseline:**
   - Search for classes, functions, headers
   - Verify symbols found correctly
   - Record baseline results

4. **Trigger refresh:**
   - Modify some files (touch or edit)
   - Call `refresh_project(incremental=true)`
   - Monitor status during refresh

5. **Verify refresh results:**
   - Search for same symbols as baseline
   - Verify no missing data
   - Check for errors in logs

6. **Edge cases:**
   - Full refresh: `refresh_project(force_full=true)`
   - Header modifications (cascade to dependents)
   - compile_commands.json changes

### Validation Checklist

**Issue #10 (File counts):**
- ✅ `get_server_status` shows non-zero file counts
- ✅ `parsed_files` matches actual number of processed files
- ✅ `project_files` matches total files in project

**Issue #1 (State race):**
- ✅ `get_indexing_status` works immediately after `set_project_directory`
- ✅ No "Project directory not set" error
- ✅ State reported correctly throughout indexing

**Issue #13 (Headers with wrong args):**
- ✅ No boost/vcpkg/Foundation header errors during refresh
- ✅ Headers only processed as dependencies of source files
- ✅ Same compile args used during initial indexing and refresh

**Issue #12 (Database connection):**
- ✅ No "Cannot operate on a closed database" warnings
- ✅ Dependencies updated for all re-analyzed files
- ✅ Dependency graph integrity maintained

**Issue #8 (Missing headers):**
- ✅ Header files found after refresh
- ✅ Header symbols found after refresh
- ✅ Same results before and after refresh

---

## Implementation Notes

### Code Style
- Follow existing patterns in codebase
- Use diagnostics module for logging
- Add comments explaining non-obvious logic
- Update docstrings if function signatures change

### Testing
- Run `make test` before committing
- Add integration tests for fixed issues
- Test on both Linux and macOS if possible
- Monitor resource usage (FD counts, memory)

### Documentation
- Update CLAUDE.md if architectural changes
- Add comments to MANUAL_TEST_OBSERVATIONS.md with test results
- Document any breaking changes or behavior changes

### Git Workflow
- Create feature branch for each issue: `fix/issue-N-description`
- Write clear commit messages (use sample paths, not real paths)
- Create PR for review
- Merge to main after approval

---

## Risk Assessment

### Low Risk (Safe to fix immediately)
- ✅ Issue #10: File counts (trivial replacement)
- ✅ Issue #1: State race (proven pattern from #2)

### Medium Risk (Requires careful testing)
- ⚠️ Issue #13: Headers with wrong args (logic change, but well-defined)
- ⚠️ Issue #12: Database connection (connection lifecycle management)

### Unknown Risk (Needs investigation first)
- ❓ Issue #8: Missing headers (depends on #13 + #12 results)

---

## Success Metrics ✅ ALL ACHIEVED

### Phase 1 Complete: ✅
- ✅ File counts shown correctly in status (Issue #10)
- ✅ No state race condition after `set_project_directory` (Issue #1)
- ✅ Reliable testing workflow enabled

### Phase 2 Complete: ✅
- ✅ No header parse errors during refresh (Issue #13)
- ✅ No database connection errors during refresh (Issue #12)
- ✅ Headers present and correct after refresh (Issue #8)
- ✅ Refresh results match initial indexing results

### Phase 3 Complete: ✅
- ✅ Progress reporting during refresh (Issue #11)
- ✅ Parallel processing performance in refresh (Issue #6)
- ✅ Consistent UX between indexing and refresh

---

## Timeline - Actual

**Phase 1:** ~2 hours (Issues #10, #1)
- PR #64, PR #66

**Phase 2:** ~6 hours (Issues #13, #12, #8)
- PR #67, PR #69, PR #71

**Phase 3:** ~4 hours (Issues #11, #6)
- PR #72, PR #73

**Total:** ~12 hours of development + testing
**Period:** 2025-12-21 to 2025-12-25

---

## References

- Manual test observations: `docs/MANUAL_TEST_OBSERVATIONS.md`
- Issue #2 fix (template): Commit e155aba
- FD leak fix (reference): PR #62, commits 2e6700f, 9b2a3b1, etc.
- Resource monitoring: `docs/INTERRUPT_HANDLING.md`, CLAUDE.md
