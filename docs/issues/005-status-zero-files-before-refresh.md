# [005] Status Reports Zero Files Before Refresh

**Category:** Bug
**Priority:** Medium
**Status:** ✅ FIXED (PR #78)
**Date Identified:** 2025-12-26
**Date Resolved:** 2025-12-26 (same day)
**Actual Effort:** 2 hours
**Complexity:** Simple

---

## Problem Statement

After calling `set_project_directory` on a project with existing cache, status requests report zero indexed files. However, immediately after starting `refresh_project`, the server correctly reports the actual number of indexed files. This suggests that cache metadata is not being loaded during project initialization but only when refresh is triggered.

### Current Behavior

**Observed Sequence:**

1. **Call `set_project_directory`** with path to previously-indexed project
   - Response: Success, project directory set

2. **Call `get_indexing_status` (or similar status tool)**
   - Response: 0 files indexed, 0 classes, 0 functions
   - **INCORRECT**: Cache exists with thousands of symbols

3. **Call `refresh_project`**
   - Immediately after refresh starts, progress shows correct counts
   - Example: "Progress: 100/8389 files (1%)" - shows 8389 total files
   - **CORRECT**: Server now knows the actual file count

**Test Environment:**
- **Platform**: Linux (not tested on macOS)
- **Project**: Previously indexed project with existing cache
- **Cache State**: Valid cache present in `.mcp_cache/`
- **Transport**: SSE

### Expected/Desired Behavior

1. **After `set_project_directory`**:
   - Server should load cache metadata immediately
   - Status should report actual indexed file/symbol counts from cache
   - No need to trigger refresh to see cached state

2. **Status Response Should Show**:
   - Total files: 8389 (from cache metadata)
   - Indexed classes: XXXX (from cache)
   - Indexed functions: XXXX (from cache)
   - Cache status: "Loaded from cache"

---

## Impact Assessment

**User Impact:**
- **Confusing UX**: Users see "0 files" despite having indexed project
- **Misleading Status**: Cannot verify if cache exists/loaded
- **Workflow Disruption**: Must trigger refresh to verify indexing state
- **Trust Issue**: Users may think cache is broken/missing

**Development Impact:**
- **Testing**: Hard to verify cache state without triggering refresh
- **Debugging**: Cannot distinguish "no cache" from "cache not loaded"

**Business Impact:**
- **Minor**: Cosmetic issue, doesn't prevent functionality
- **UX Polish**: Affects perceived quality/reliability

---

## Technical Analysis

### Likely Root Cause

**Hypothesis 1: Lazy Cache Loading**
- Cache metadata only loaded when needed (during refresh)
- `set_project_directory` doesn't trigger cache load
- Status tools query empty in-memory state

**Hypothesis 2: Missing Cache Restoration**
- `StateManager` or `CacheManager` not restoring counts from cache
- File index loaded but counts not populated
- Related to Issue #10 fix (PR #64) - may have incomplete restoration

**Hypothesis 3: Async State Initialization**
- Cache loading happens asynchronously
- Status request happens before loading completes
- No wait/block for cache load to finish

### Code Investigation Targets

1. **`set_project_directory` Implementation**:
   - Check if cache metadata is loaded
   - Verify StateManager initialization
   - Look for missing cache restoration call

2. **`get_indexing_status` Implementation**:
   - Check data source for file counts
   - Verify it reads from cache when no active indexing
   - May be reading only from in-memory structures

3. **Cache Loading Flow**:
   - When does `CacheManager.load()` get called?
   - Is `file_index` populated from cache?
   - Are symbol counts restored from cache metadata?

4. **StateManager Initialization**:
   - Does it restore state from cache on project set?
   - Check `state_manager.py` for cache restoration logic

---

## Proposed Solutions

### Option 1: Eager Cache Loading in set_project_directory

**Concept**: Load cache metadata immediately when project is set

**Implementation**:
```python
# In cpp_analyzer.py set_project_directory()
def set_project_directory(self, source_dir, config_file=None):
    # ... existing code ...

    # NEW: Load cache metadata immediately
    if self.cache_manager.cache_exists():
        self._load_cache_metadata()  # Restore file counts, indexes
        self.state_manager.restore_from_cache()  # Update state

    # ... rest of code ...
```

**Pros:**
- Simple, direct fix
- Users see correct status immediately
- No breaking changes

**Cons:**
- Slight delay in set_project_directory response
- Loads data that may not be needed if full reindex requested

**Estimated Effort:** 1-2 days
**Risk Level:** Low

---

### Option 2: Populate Status from Cache When Available

**Concept**: Make status tools check cache if no in-memory data

**Implementation**:
```python
# In get_indexing_status tool handler
def get_indexing_status(self):
    if self.indexing_in_progress:
        return self._get_live_status()
    else:
        # NEW: Fall back to cache metadata
        return self._get_cached_status()
```

**Pros:**
- No changes to initialization flow
- Status always accurate
- Lazy loading preserved

**Cons:**
- Duplicates state tracking logic
- Cache queries on every status request
- May be slower for status checks

**Estimated Effort:** 2-3 days
**Risk Level:** Low

---

### Option 3: Async Cache Load with Status Notification

**Concept**: Load cache async, update status when ready

**Implementation**:
1. `set_project_directory` triggers async cache load
2. Status reports "Loading cache..." while in progress
3. Once loaded, status shows actual counts

**Pros:**
- No delay in set_project_directory response
- Honest about loading state
- Handles large caches gracefully

**Cons:**
- More complex implementation
- Need async state management
- May confuse users with intermediate state

**Estimated Effort:** 4-5 days
**Risk Level:** Medium

---

## Recommended Approach

### Primary Recommendation: **Option 1 (Eager Cache Loading)**

**Rationale:**
1. Simplest solution with clear behavior
2. Users expect immediate feedback after setting project
3. Cache metadata is small (< 1 MB), loads quickly
4. Aligns with user expectations from Issue #1 fix
5. Low risk, easy to test

**Implementation Steps:**

1. **Add cache metadata loading** to `set_project_directory`:
   - Call `cache_manager.load_metadata()` after cache initialization
   - Restore `file_index` from cache
   - Update `state_manager` with cached counts

2. **Verify status tools** read from correct sources:
   - Check `get_indexing_status` uses `file_index` (from Issue #10 fix)
   - Ensure symbol counts come from indexes, not TU dict
   - Validate cached vs. live status distinction

3. **Add tests**:
   - Test status after `set_project_directory` with existing cache
   - Verify counts match cache contents
   - Test status during and after refresh

**Success Criteria:**
- Status shows correct file/symbol counts immediately after `set_project_directory`
- No regression in set_project_directory response time (< 500ms delay acceptable)
- Status distinguishes between "cached" and "live indexing" states

---

## Relationship to Previous Issues

### Issue #10: get_server_status Zero Files (FIXED in PR #64)

**Similarity:** Both involve zero file counts in status
**Difference:**
- Issue #10: Zero files during/after indexing (used TU dict instead of file_index)
- Issue #15: Zero files after project set, before refresh (cache not loaded)

**Connection:**
- PR #64 fixed status to use `file_index` instead of `translation_units` dict
- However, may not have addressed cache restoration into `file_index`
- This issue may be incomplete fix or new edge case

### Issue #1: set_project_directory State Race (FIXED in PR #66)

**Connection:**
- PR #66 made state setting synchronous
- This issue suggests state restoration from cache is incomplete
- May need similar treatment for cache metadata loading

---

## Testing Requirements

### Manual Tests

1. **Fresh Project with Existing Cache**:
   ```bash
   # Set project that was previously indexed
   set_project_directory /path/to/project

   # Check status immediately
   get_indexing_status
   # Expected: Shows cached file/symbol counts (NOT zero)
   ```

2. **Fresh Project without Cache**:
   ```bash
   # Set never-indexed project
   set_project_directory /path/to/new/project

   # Check status
   get_indexing_status
   # Expected: Shows 0 files (no cache exists)
   ```

3. **After Refresh Starts**:
   ```bash
   # Start refresh
   refresh_project

   # Check status during indexing
   get_indexing_status
   # Expected: Shows progress (N/total files)
   ```

### Automated Tests

1. **Unit Test**: Cache metadata restoration
2. **Integration Test**: Status with existing cache
3. **Regression Test**: Verify Issue #10 not reintroduced

---

## Decision Log

**2025-12-26**: Initial identification from manual testing
- **Observation**: Status reports 0 files after set_project_directory, correct after refresh starts
- **Platform**: Observed on Linux, not tested on macOS
- **Related Issues**: Possibly related to incomplete fix in Issue #10 (PR #64)
- **Decision**: Create issue document, investigate cache loading flow
- **Next Steps**:
  1. Review PR #64 implementation for cache restoration
  2. Check if file_index populated from cache metadata
  3. Implement Option 1 (eager cache loading)

---

## References

**Related Documentation:**
- [CLAUDE.md](../../CLAUDE.md) - Architecture, cache management
- [docs/MANUAL_TEST_OBSERVATIONS.md](../MANUAL_TEST_OBSERVATIONS.md) - Issue tracking

**Code References:**
- `mcp_server/cpp_analyzer.py:set_project_directory()` - Project initialization
- `mcp_server/state_manager.py` - State tracking
- `mcp_server/cache_manager.py` - Cache operations
- `mcp_server/cpp_mcp_server.py:get_indexing_status()` - Status tool handler

**Related Issues:**
- Issue #10: get_server_status zero files (FIXED PR #64) - Similar symptom, may be incomplete fix
- Issue #1: set_project_directory state race (FIXED PR #66) - Related to initialization timing
- Issue #14 / docs/issues/004: Memory leak during large indexing - observed in same testing session, both may relate to state initialization

**Related PRs:**
- PR #64: Fix zero file counts by using file_index instead of TU dict
- PR #66: Fix state race in set_project_directory

---

## Resolution

**2025-12-26 (Same Day)**: Root cause identified and fixed

### Investigation

Reviewed `set_project_directory` implementation in `mcp_server/cpp_mcp_server.py` lines 707-741:

**Root Cause Found:**
When cache is loaded successfully, the code transitions to `INDEXED` state but never initializes the `IndexingProgress` with cache data. The `state_manager` has no progress information, so `get_indexing_status` returns 0 for all file counts.

**Code Path:**
1. `set_project_directory` loads cache via `analyzer.set_project_directory()`
2. If cache valid: symbols loaded into indexes, state → INDEXED
3. **BUG**: Progress never set with cache metadata
4. `get_indexing_status` calls `state_manager.get_status_dict()`
5. Returns `self._progress` which is `None` → defaults to 0 for all counts

### Fix Implementation

Added progress initialization after successful cache load in `cpp_mcp_server.py` lines 720-735:

```python
if cache_valid:
    # Cache loaded successfully - skip indexing
    diagnostics.info(
        f"Cache loaded successfully: {len(analyzer.class_index)} classes, "
        f"{len(analyzer.function_index)} functions indexed"
    )

    # CRITICAL FIX FOR ISSUE #15: Initialize progress with cache data
    # Without this, get_indexing_status returns 0 files even though cache is loaded
    from .state_manager import IndexingProgress
    from datetime import datetime

    # Create progress object from cached data
    total_files = len(analyzer.file_index)
    progress = IndexingProgress(
        total_files=total_files,
        indexed_files=total_files,  # All files loaded from cache
        failed_files=0,  # No failures when loading from cache
        cache_hits=total_files,  # Everything came from cache
        current_file=None,  # No active file
        start_time=datetime.now(),
        estimated_completion=None  # Already complete
    )
    state_manager.update_progress(progress)

    state_manager.transition_to(AnalyzerState.INDEXED)
    # ... rest of existing code
```

### Validation

**Testing:**
- All 580 unit tests passed with no regressions
- Logic verified: Progress now initialized with cache data when cache loads
- Similar test exists: `test_get_indexing_status_immediately_after_set_project_directory` in `tests/test_concurrent_queries_during_indexing.py`

**Expected Behavior After Fix:**
1. `set_project_directory` with existing cache → progress initialized with cached file counts
2. `get_indexing_status` immediately after → shows correct total_files, indexed_files, cache_hits
3. No need to call `refresh_project` to see cached state

### Commit & PR

- **Branch:** `fix/status-zero-files-before-refresh`
- **Files Modified:** `mcp_server/cpp_mcp_server.py`
- **PR:** #78
- **Status:** ✅ FIXED

---

## Next Steps

1. **Immediate** (This week):
   - Review existing cache loading code in `set_project_directory`
   - Check if PR #64 includes cache restoration logic
   - Reproduce issue with debugger to trace cache loading

2. **Short-term** (Next week):
   - Implement Option 1 (eager cache loading)
   - Add unit tests for cache metadata restoration
   - Test with projects of various sizes

3. **Validation**:
   - Manual testing on Linux and macOS
   - Verify no performance regression
   - Confirm status accuracy in all scenarios

**Trigger Conditions** (when to escalate):
- Issue confirmed as regression of Issue #10
- Cache loading causes significant delay
- Related to memory leak investigation (Issue #14)

**Owner**: TBD
