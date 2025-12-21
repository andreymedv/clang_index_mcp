# Issue Fixing Plan - Prioritized Roadmap

**Created:** 2025-12-21
**Branch:** fix/refresh-project-timeout
**Status:** Planning phase - no fixes started yet

## Executive Summary

Analysis of 13 documented issues from manual testing sessions (Linux + macOS). After dependency analysis, identified that:
- **Issue #3 (FD leak)** already fixed in PR #62 ✅
- **Issue #8** likely a symptom of Issues #13 + #12 (not independent root cause)
- **Issues #13 → #12 → #8** must be fixed in that order due to dependencies

## Testing Workflow Analysis

From tester perspective, typical workflow:
```
set_project_directory → get_indexing_status → get_server_status → refresh_project
```

### Impact by Workflow Step

**Step 1: `set_project_directory`**
- Issue #1 ⚠️ Race condition - immediate status queries may fail
- ~~Issue #3~~ ✅ FD leak - ALREADY FIXED in PR #62

**Step 2: `get_indexing_status`**
- No issues (works correctly)

**Step 3: `get_server_status`**
- Issue #10 ⚠️ Reports zero files (misleading diagnostics)

**Step 4: `refresh_project`**
- ~~Issue #2~~ ✅ Timeout - ALREADY FIXED in current branch
- Issue #11 ⚠️ No progress reporting (poor UX)
- Issue #12 🔴 Database connection errors (dependency tracking fails)
- Issue #13 🔴 Headers with wrong compilation args (parse errors)
- Issue #8 🔴 Missing headers after refresh (likely symptom of #12 + #13)
- Issue #6 ⚠️ Sequential processing (slow performance)

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

### Phase 1: Workflow Foundation
**Quick wins to enable reliable testing**

#### 1. Issue #10: get_server_status Reports Zero Files ⚡ TRIVIAL
- **Priority:** HIGH (2-minute fix, immediate improvement)
- **Impact:** All platforms
- **Root cause:** Regression from FD leak fix (commit 2e6700f)
  - Removed `self.translation_units` dict (was causing FD leak)
  - But `get_server_status` still references it → returns 0
- **Location:** `mcp_server/cpp_mcp_server.py:997,1000`
- **Fix:**
  ```python
  # OLD (broken):
  "parsed_files": len(analyzer.translation_units),    # Dict no longer exists!
  "project_files": len(analyzer.translation_units),

  # NEW (correct):
  "parsed_files": len(analyzer.file_index),
  "project_files": len(analyzer.file_index),
  ```
- **Validation:** Verify status shows correct file counts after indexing
- **Effort:** 2 lines changed
- **Risk:** None (simple replacement)

---

#### 2. Issue #1: set_project_directory State Synchronization Race
- **Priority:** HIGH (blocks workflow step 1→2)
- **Impact:** All platforms
- **Symptom:** `get_indexing_status` fails immediately after `set_project_directory`
  - First call succeeds: "Indexing started in background"
  - Immediate status query: "Error: Project directory not set"
  - Wait few seconds, query again: Works correctly
- **Root cause:** State not set immediately, only after background work starts
- **Location:** `mcp_server/cpp_mcp_server.py` - `set_project_directory` handler
- **Approach:** Apply same async pattern as Issue #2 fix
  - Set state immediately before starting background indexing
  - Return success message
  - Background indexing continues asynchronously
- **Validation:** Call `get_indexing_status` immediately after `set_project_directory`
- **Effort:** Low (template exists from Issue #2)
- **Risk:** Low (proven pattern)

---

### Phase 2: Refresh Correctness
**Fix in dependency order - critical for data integrity**

#### 3. Issue #13: Headers Re-Analyzed with Fallback Args 🔴 HIGH PRIORITY
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
- **Fix (Option 1 - Recommended):** Filter headers from directory scan
  ```python
  # change_scanner.py:171-177
  current_source_files = set()
  for file_path in self.analyzer.file_scanner.find_cpp_files():
      # Skip headers - they'll be detected via header_tracker
      if file_path.endswith(('.h', '.hpp', '.hxx', '.h++')):
          continue
      current_source_files.add(file_path)
  ```

- **Fix (Option 2):** Categorize headers correctly
  ```python
  # change_scanner.py:185-186
  elif change_type == ChangeType.MODIFIED:
      # Check if it's a header or source
      if normalized_path.endswith(('.h', '.hpp', '.hxx', '.h++')):
          changeset.modified_headers.add(normalized_path)
      else:
          changeset.modified_files.add(normalized_path)
  ```

- **Fix (Option 3):** Skip headers in incremental_analyzer
  ```python
  # incremental_analyzer.py:141-143
  for source_file in changes.modified_files:
      # Skip headers - they're handled via modified_headers
      if source_file.endswith(('.h', '.hpp', '.hxx', '.h++')):
          continue
      self._handle_source_change(source_file)
      files_to_analyze.add(source_file)
  ```

- **Validation:**
  - Index project → refresh → check no boost/Foundation header errors
  - Verify headers only processed as dependencies of .cpp files
  - Compare args used for headers during initial indexing vs refresh

- **Effort:** Low (small code change, well-defined problem)
- **Risk:** Low (clear logic fix)
- **Dependencies:** None - but **blocks Issue #8 diagnosis**

---

#### 4. Issue #12: Database Connection Lifecycle Bug 🔴 HIGH PRIORITY
- **Priority:** CRITICAL (must fix before Issue #8)
- **Impact:** Dependency tracking fails during refresh
- **Symptom:** During refresh, warnings appear:
  ```
  [WARNING] Failed to update dependencies for /path/to/File.h:
  Cannot operate on a closed database.
  ```
- **Root cause:** Shared SQLite connection with mismatched lifecycle
  1. `cpp_analyzer.py:270` - DependencyGraphBuilder created with shared connection
     ```python
     if hasattr(self.cache_manager.backend, "conn"):
         self.dependency_graph = DependencyGraphBuilder(self.cache_manager.backend.conn)
     ```
  2. `cpp_analyzer.py:310` - cache_manager.close() closes the shared connection
  3. DependencyGraphBuilder still holds reference to closed connection
  4. Operations fail: `self.conn.cursor()` → "Cannot operate on a closed database"

- **Location:**
  - Connection sharing: `mcp_server/cpp_analyzer.py:270`
  - Connection closing: `mcp_server/cpp_analyzer.py:310`
  - Failed usage: `mcp_server/dependency_graph.py:173`

- **Fix (Option 1 - Recommended):** Keep connection open during operations
  ```python
  # Don't close cache_manager until all operations complete
  # Ensure connection lifecycle matches operation lifecycle
  ```

- **Fix (Option 2):** Separate dependency connection
  ```python
  # Create separate connection for dependency_graph
  self.dependency_graph = DependencyGraphBuilder(
      sqlite3.connect(db_path)  # Own connection, not shared
  )
  ```

- **Fix (Option 3):** Check connection before use
  ```python
  # dependency_graph.py:update_dependencies
  def update_dependencies(self, source_file: str, included_files: List[str]) -> int:
      if not self._is_connection_open():
          diagnostics.warning("Database connection closed, skipping dependency update")
          return 0
      # ... existing code
  ```

- **Validation:**
  - Index project → refresh → check no "closed database" warnings
  - Verify dependencies updated for all re-analyzed files
  - Check dependency graph integrity after refresh

- **Effort:** Medium (connection lifecycle management)
- **Risk:** Medium (database operations, need careful testing)
- **Dependencies:** None - but **blocks Issue #8 diagnosis**

---

#### 5. Issue #8: Missing Headers After Refresh 🔴 RE-EVALUATE
- **Priority:** CRITICAL (data integrity issue)
- **Impact:** Header files and symbols disappear after refresh
- **Symptom:**
  - After refresh, search for known header files: no results
  - Search for classes defined in headers: no results
  - Suggests headers were not indexed or data was deleted

- **Hypothesis:** **Symptom of Issues #13 + #12, not independent root cause**
  - Issue #13 → headers parsed with wrong args → parse fails → no symbols extracted
  - Issue #12 → dependency tracking fails → headers not tracked → missing from DB
  - Both contribute to missing header data

- **Strategy:**
  1. ✅ Fix Issue #13 first (headers with wrong args)
  2. ✅ Fix Issue #12 second (database connection)
  3. ⚠️ Re-test Issue #8 from scratch
  4. If still occurs → investigate header_tracker state preservation

- **Investigation (if persists after #13 + #12 fixed):**
  - Check if headers exist in `file_index` after refresh
  - Check if headers exist in SQLite database
  - Run `diagnose_cache.py` to inspect header entries
  - Check if headers being passed to `_process_file_worker()`
  - Verify `header_tracker.json` cache file valid after refresh
  - Determine if issue occurs after incremental vs full refresh

- **Location:** TBD (depends on investigation results)
- **Effort:** Unknown (may not need fix if #13 + #12 resolve it)
- **Risk:** Unknown
- **Dependencies:** **REQUIRES #13 and #12 fixed first**

---

### Phase 3: UX Enhancements
**Non-blocking improvements**

#### 6. Issue #11: refresh_project Missing Progress Reporting
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
  - Missing parameter: `cpp_analyzer.py:2158` - `refresh_if_needed()`
  - Missing parameter: `incremental_analyzer.py:89` - `perform_incremental_analysis()`
  - Background refresh: `cpp_mcp_server.py` - `run_background_refresh()`

- **Fix:** Add progress callback support
  1. Add `progress_callback` parameter to refresh methods
  2. Update `run_background_refresh` to create and pass callback
  3. Modify `_reanalyze_files` to report progress during file processing

- **Validation:**
  - Refresh project, check `get_indexing_status` shows progress
  - Verify progress updates during long refreshes
  - Ensure progress resets after completion

- **Effort:** Medium (architectural change across multiple files)
- **Risk:** Low (additive change, doesn't affect existing functionality)

---

#### 7. Issue #6: Sequential Processing in Incremental Refresh
- **Priority:** MEDIUM (performance optimization, not blocking)
- **Impact:** Incremental refresh slower than necessary
- **Symptom:** Refresh uses fewer subprocesses than initial indexing
  - Initial indexing: full ProcessPoolExecutor with multiple workers (6-7x speedup)
  - Incremental refresh: appears to use fewer workers or single-threaded

- **Investigation areas:**
  - `refresh_project` implementation may not pass files to parallel processing
  - Incremental analyzer may process files sequentially
  - Different code path for re-analysis vs initial indexing
  - ProcessPoolExecutor not being reused with full workers

- **Location:**
  - `mcp_server/cpp_analyzer.py` - `refresh_project()` method
  - `mcp_server/incremental_analyzer.py` - re-analysis implementation

- **Effort:** Medium (ensure parallel processing in refresh path)
- **Risk:** Low (performance optimization, doesn't change functionality)

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

## Success Metrics

### Phase 1 Complete:
- ✅ File counts shown correctly in status
- ✅ No state race condition after `set_project_directory`
- ✅ Reliable testing workflow enabled

### Phase 2 Complete:
- ✅ No header parse errors during refresh
- ✅ No database connection errors during refresh
- ✅ Headers present and correct after refresh
- ✅ Refresh results match initial indexing results

### Phase 3 Complete:
- ✅ Progress reporting during refresh
- ✅ Parallel processing performance in refresh
- ✅ Consistent UX between indexing and refresh

---

## Timeline Estimate

**Phase 1:** 1-2 hours (quick wins)
**Phase 2:** 4-6 hours (critical fixes with dependencies)
**Phase 3:** 3-4 hours (enhancements)

**Total:** 8-12 hours of development + testing time

---

## References

- Manual test observations: `docs/MANUAL_TEST_OBSERVATIONS.md`
- Issue #2 fix (template): Commit e155aba
- FD leak fix (reference): PR #62, commits 2e6700f, 9b2a3b1, etc.
- Resource monitoring: `docs/INTERRUPT_HANDLING.md`, CLAUDE.md
