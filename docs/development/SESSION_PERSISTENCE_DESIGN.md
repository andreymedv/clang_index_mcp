# Session Persistence & Cache Recovery Design

## Problem Summary

When LM Studio restarts the MCP server (after timeout or inactivity), the server:
1. **Loses state** - Forgets which project was being analyzed
2. **Re-indexes everything** - Despite having a valid cache, incremental analysis reports 9,788 files as "added"
3. **Errors on missing files** - compile_commands.json references generated files that don't exist
4. **Forces user intervention** - User must call `set_project_directory` again

## Root Causes

### 1. No Session Persistence
- Global variables (`analyzer`, `state_manager`) are lost on process restart
- No mechanism to remember last project directory
- Each restart is a clean slate

### 2. Cache Metadata Mismatch
The incremental analyzer checks file metadata via `cache_manager.backend.get_file_metadata()`, which queries SQLite directly. When cache loads:
- Symbols are loaded into memory (class_index, function_index)
- file_hashes dictionary is populated
- **But**: `get_file_metadata()` queries the database, not memory
- If database doesn't have metadata → file marked as ADDED

Possible causes:
- File metadata not saved to database before shutdown
- Database schema version mismatch causing recreation
- Path normalization differences (realpath vs original path)

### 3. Auto-Refresh Too Aggressive
```python
# cpp_mcp_server.py:649-660
if auto_refresh and hasattr(analyzer, 'cache_loaded') and analyzer.cache_loaded:
    incremental = IncrementalAnalyzer(analyzer)
    result = incremental.perform_incremental_analysis()
```

Runs **immediately** after cache load, even if:
- Cache was just saved 30 seconds ago (before server restart)
- No files have actually changed
- User just wants to resume work

### 4. Missing Generated Files
compile_commands.json references Qt-generated files (qrc_*.cpp, mocs_compilation.cpp) that may not exist if:
- Build was cleaned
- Different build configuration
- Generated files are gitignored

## Proposed Solutions

### Phase 1: Session Persistence (Quick Win)

**Goal**: Server remembers last project and resumes without re-indexing

**Implementation**:
```python
# .mcp_cache/session.json
{
  "last_project": {
    "path": "/path/to/project",
    "config_file": "/path/to/project/cpp-analyzer-config.json",
    "last_accessed": "2025-12-14T18:46:42Z",
    "cache_valid": true
  }
}
```

**Changes**:
1. **Save session on `set_project_directory`**
   - Create `.mcp_cache/session.json` with project info
   - Update timestamp on successful indexing

2. **Auto-resume on server start**
   - In `cpp_mcp_server.py` startup, check for session.json
   - If found and cache valid, auto-load project WITHOUT auto_refresh
   - Set `analyzer_initialized = True` immediately

3. **Add `resume_session` tool**
   - Explicit tool to resume last session
   - Returns project path and indexing status
   - Allows user control

**Pros**:
- Survives server restarts
- No re-indexing on reconnect
- Simple implementation

**Cons**:
- Doesn't fix the "9788 added" bug
- Still requires cache to be valid

### Phase 2: Fix Cache Metadata Issue (Critical)

**Goal**: Incremental analysis correctly recognizes cached files

**Investigation needed**:
```bash
# Check if file metadata is in database after cache load
python scripts/diagnose_cache.py /path/to/project

# Add debug logging
# In change_scanner.py:_check_file_change()
metadata = self.analyzer.cache_manager.backend.get_file_metadata(file_path)
if not metadata:
    diagnostics.debug(f"No metadata for {file_path} - checking file_hashes")
    # Fallback to in-memory file_hashes
    if file_path in self.analyzer.file_hashes:
        diagnostics.warning(f"File in file_hashes but not in database: {file_path}")
```

**Potential fixes**:

1. **Ensure file metadata is saved**
   ```python
   # In sqlite_cache_backend.py
   def save_file_metadata(self, file_path, file_hash, ...):
       # Verify write succeeded
       self._connection.commit()
   ```

2. **Fallback to file_hashes**
   ```python
   # In change_scanner.py:_check_file_change()
   if not metadata:
       # Try in-memory file_hashes as fallback
       if file_path in self.analyzer.file_hashes:
           cached_hash = self.analyzer.file_hashes[file_path]
           current_hash = self.analyzer._get_file_hash(file_path)
           return ChangeType.MODIFIED if current_hash != cached_hash else ChangeType.UNCHANGED
       return ChangeType.ADDED
   ```

3. **Path normalization consistency**
   ```python
   # Ensure all paths are normalized the same way
   # Use os.path.realpath() consistently in:
   # - Cache saving
   # - Cache loading
   # - Change detection
   ```

### Phase 3: Smart Auto-Refresh (UX Improvement)

**Goal**: Don't re-index immediately after cache load if cache is fresh

**Implementation**:
```python
# In cpp_mcp_server.py:run_background_indexing()
if auto_refresh and hasattr(analyzer, 'cache_loaded') and analyzer.cache_loaded:
    # Check cache age
    cache_metadata = analyzer.cache_manager.backend.get_cache_metadata()
    cache_age_seconds = time.time() - cache_metadata.get('last_updated', 0)

    # Only auto-refresh if cache is older than 5 minutes
    if cache_age_seconds > 300:  # 5 minutes
        diagnostics.info(f"Cache is {cache_age_seconds:.0f}s old, running auto-refresh")
        incremental = IncrementalAnalyzer(analyzer)
        result = incremental.perform_incremental_analysis()
    else:
        diagnostics.info(f"Cache is fresh ({cache_age_seconds:.0f}s old), skipping auto-refresh")
```

**Alternative**: Add `auto_refresh_threshold` config option
```json
// cpp-analyzer-config.json
{
  "auto_refresh_threshold_seconds": 300,  // Default: 5 minutes
  "auto_refresh_on_startup": false        // Default: true
}
```

### Phase 4: Handle Missing Generated Files (Robustness)

**Goal**: Don't error on missing files in compile_commands.json

**Changes**:
1. **Filter out non-existent files**
   ```python
   # In compile_commands_manager.py:get_all_files()
   def get_all_files(self) -> List[str]:
       if not self._compile_commands:
           return []

       files = []
       for entry in self._compile_commands.values():
           file_path = entry['file']
           # Skip non-existent files (e.g., generated files)
           if not os.path.exists(file_path):
               diagnostics.debug(f"Skipping non-existent file: {file_path}")
               continue
           files.append(file_path)
       return files
   ```

2. **Add config option**
   ```json
   {
     "compile_commands": {
       "enabled": true,
       "skip_missing_files": true  // NEW: Skip files that don't exist
     }
   }
   ```

## Recommended Implementation Order

1. **Phase 2 (Critical)**: Fix cache metadata issue
   - This solves the "9788 added" problem
   - Required for other phases to work

2. **Phase 1 (High Priority)**: Session persistence
   - Immediate UX improvement
   - Works with Phase 2 fix

3. **Phase 3 (Medium Priority)**: Smart auto-refresh
   - Reduces unnecessary work
   - Improves startup time

4. **Phase 4 (Low Priority)**: Handle missing files
   - Nice to have
   - Reduces log spam

## Alternative: Complete Redesign

If the cache issues are too complex, consider:

### Option A: Stateless Mode
- Cache is read-only
- No auto-refresh
- User explicitly calls `refresh_project` when needed
- Pros: Simple, predictable
- Cons: May have stale data

### Option B: Daemon Mode
- MCP server runs continuously as daemon
- Never restarts (survives LM Studio disconnect)
- Session persists in memory
- Pros: No state loss
- Cons: More complex, resource usage

### Option C: Hybrid Approach
- Keep stateless mode as default
- Add "persistent mode" flag for users who want auto-resume
- Let users choose tradeoff

## Testing Plan

After implementing fixes:

1. **Test session persistence**
   ```bash
   # Start server, set project, kill server, restart
   # Verify: Project remembered, no re-indexing
   ```

2. **Test cache metadata**
   ```bash
   # Index project, restart server, set_project_directory
   # Verify: Incremental analysis shows 0 added (or actual changes only)
   ```

3. **Test auto-refresh threshold**
   ```bash
   # Index project, restart immediately
   # Verify: No auto-refresh (cache fresh)
   # Wait 6 minutes, restart
   # Verify: Auto-refresh runs (cache stale)
   ```

4. **Test missing files**
   ```bash
   # compile_commands.json with non-existent files
   # Verify: No errors, files skipped gracefully
   ```

## Metrics to Track

- **Cache hit rate** after server restart
- **Time to resume** (with session persistence vs without)
- **Incremental analysis accuracy** (true changes vs false positives)
- **Error rate** from missing files

## Questions for User

1. **Priority**: Which issue bothers you most?
   - Losing project state on restart?
   - 9788 files re-indexed?
   - Missing file errors?

2. **Frequency**: How often does LM Studio restart the server?
   - Every query timeout?
   - After X minutes of inactivity?
   - Random disconnects?

3. **Workflow**: What do you expect after reconnect?
   - Server remembers project automatically?
   - User explicitly resumes session?
   - Fresh start every time?

4. **Cache age**: How often do you modify code?
   - Continuously (every few minutes)?
   - Periodically (every hour)?
   - Rarely (once per day)?

This will help prioritize which fixes to implement first.
