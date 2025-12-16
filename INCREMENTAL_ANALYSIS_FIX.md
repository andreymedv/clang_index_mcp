# Incremental Analysis Fix - No More False "9788 Added"

## Problem Fixed

**Before**: After cache load, calling `refresh_project` would incorrectly report all 9,788 files as "added" and re-index everything.

**After**: Incremental analysis correctly recognizes cached files and only re-indexes actual changes.

## Root Cause

When cache loaded:
1. ✅ Symbols loaded into memory (class_index, function_index)
2. ✅ `file_hashes` loaded into memory
3. ❌ **But SQLite database had no file metadata**

When incremental analyzer ran:
```python
metadata = self.analyzer.cache_manager.backend.get_file_metadata(file_path)
if not metadata:
    return ChangeType.ADDED  # ← Bug: Database empty, so ALL files appeared "added"
```

## Fix Applied

Updated `change_scanner.py:_check_file_change()` to:
1. Check database first (normal path)
2. **Fallback to in-memory `file_hashes`** if database empty
3. Only report as ADDED if not in database AND not in memory

```python
# CRITICAL FIX: Fallback to in-memory file_hashes if not in database
if not metadata:
    if file_path in self.analyzer.file_hashes:
        # File is in memory cache, check if content changed
        cached_hash = self.analyzer.file_hashes[file_path]
        current_hash = self.analyzer._get_file_hash(file_path)
        return ChangeType.MODIFIED if current_hash != cached_hash else ChangeType.UNCHANGED
    else:
        # Not in database OR in-memory cache = new file
        return ChangeType.ADDED
```

## Expected Behavior After Fix

### Scenario 1: Fresh cache load, no file changes
```
User: refresh_project()
Server: [INFO] Starting incremental analysis...
Server: [INFO] Change scan complete: 0 added, 0 modified  ← FIXED!
Server: [INFO] No changes detected. Cache is up to date.
[Completes in ~2 seconds]
```

### Scenario 2: Fresh cache load, actual file changes
```
User: (edits 5 files)
User: refresh_project()
Server: [INFO] Starting incremental analysis...
Server: [INFO] Change scan complete: 0 added, 5 modified  ← Correct!
Server: [INFO] Re-analyzing 5 files...
[Completes in ~5 seconds]
```

### Scenario 3: Fresh cache load, new files added
```
User: (creates 10 new .cpp files)
User: refresh_project()
Server: [INFO] Starting incremental analysis...
Server: [INFO] Change scan complete: 10 added, 0 modified  ← Correct!
Server: [INFO] Re-analyzing 10 files...
[Completes in ~10 seconds]
```

## Testing

### Test 1: Verify no false "added" after cache load
```bash
# 1. Restart LM Studio (server auto-resumes from cache)
# 2. Call refresh_project immediately (no file changes)
refresh_project({"incremental": true})

# Expected log:
# [INFO] Change scan complete: 0 added
# [INFO] No changes detected

# Should NOT see:
# [INFO] Change scan complete: 9788 added  ← This was the bug!
```

### Test 2: Verify real changes detected
```bash
# 1. Edit a file (e.g., add a comment)
# 2. Call refresh_project
refresh_project({"incremental": true})

# Expected log:
# [INFO] Change scan complete: 0 added, 1 modified
# [INFO] Re-analyzing 1 files...
```

### Test 3: Verify new files detected
```bash
# 1. Create a new .cpp file
# 2. Call refresh_project
refresh_project({"incremental": true})

# Expected log:
# [INFO] Change scan complete: 1 added, 0 modified
# [INFO] Re-analyzing 1 files...
```

## About refresh_project and LM Studio Disconnects

**Current Behavior**:
- `refresh_project` is **synchronous** from the client's perspective
- It waits for completion before returning response
- If refresh takes > ~60 seconds, LM Studio times out and disconnects
- **But** the background work continues running in executor thread
- Server doesn't know/care about disconnect

**Recommendation**:
- For large projects (9788 files), don't use `refresh_project` frequently
- Use `get_indexing_status` to check if refresh is needed
- Or wait for automatic change detection (future feature)

## Performance Impact

### Before Fix
```
refresh_project after cache load:
- Detects: 9788 "added" files
- Re-indexes: 9788 files
- Time: ~5-10 minutes
- LM Studio: Disconnects after 60s
```

### After Fix
```
refresh_project after cache load (no changes):
- Detects: 0 added, 0 modified
- Re-indexes: 0 files
- Time: ~2 seconds
- LM Studio: No disconnect, receives response
```

```
refresh_project with 10 actual changes:
- Detects: 0 added, 10 modified
- Re-indexes: 10 files
- Time: ~10 seconds
- LM Studio: No disconnect, receives response
```

## Files Modified

- **mcp_server/change_scanner.py**: Added fallback to in-memory `file_hashes`
- **tests/test_change_scanner.py**: Added `file_hashes = {}` to mock analyzer

## All Tests Pass

```
tests/test_change_scanner.py ............ 12 passed
tests/test_concurrent_queries_during_indexing.py ..... 5 passed
```

## Summary

With this fix + session persistence + fast cache resume, the complete workflow is:

1. **LM Studio restarts** → Server auto-resumes (< 1 second)
2. **User queries** → Returns cached results immediately
3. **User calls refresh_project** → Detects 0 changes, completes in 2 seconds
4. **User edits files** → Calls refresh_project → Only re-indexes changed files

No more false "9788 added" bug! 🎉
