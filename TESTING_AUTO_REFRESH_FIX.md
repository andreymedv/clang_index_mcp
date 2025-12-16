# Testing Auto-Refresh Fix with LM Studio

## What Was Changed

**Temporary fix applied**: Disabled auto-refresh after cache load to prevent false "all files added" detection.

**Location**: `mcp_server/cpp_mcp_server.py:649-665`

## Expected Behavior

### Before Fix (Broken):
1. Start LM Studio, connect to MCP server
2. Call `set_project_directory` with `/path/to/project`
3. Server indexes ~9,788 files (slow, takes minutes)
4. LM Studio disconnects/restarts server
5. Call `set_project_directory` again
6. **BUG**: Server re-indexes ALL 9,788 files despite having valid cache

### After Fix (Should Work):
1. Start LM Studio, connect to MCP server
2. Call `set_project_directory` with `/path/to/project`
3. Server indexes ~9,788 files (slow, takes minutes)
4. LM Studio disconnects/restarts server
5. Call `set_project_directory` again
6. **FIXED**: Server loads from cache in 2-5 seconds, no re-indexing
7. Log shows: "Auto-refresh skipped (cache loaded successfully) - use 'refresh_project' tool if needed"

## Testing Steps

### 1. Restart LM Studio
```bash
# Kill LM Studio completely
killall "LM Studio"
# Or close it from the UI
```

### 2. Start Fresh
- Launch LM Studio
- Ensure MCP server is configured correctly
- Wait for server to start

### 3. First Indexing (Fresh Start)
Call the tool:
```json
{
  "tool": "set_project_directory",
  "arguments": {
    "project_path": "/path/to/project"
  }
}
```

**Watch the logs** (should show normal indexing):
```
[INFO] Finding C++ files...
[INFO] Found 9788 C++ files to index
Progress: 100/9788 files (1%) ...
```

Wait for indexing to complete (several minutes).

### 4. Trigger Restart
Two ways to test:

#### Option A: Wait for Timeout
- Wait 5-10 minutes without sending queries
- LM Studio should disconnect and restart server
- This simulates the real-world scenario

#### Option B: Force Restart
```bash
# Find the MCP server process
ps aux | grep cpp_mcp_server

# Kill it (LM Studio will restart it)
kill <PID>
```

### 5. Second Indexing (Cache Test)
After restart, call the tool again:
```json
{
  "tool": "set_project_directory",
  "arguments": {
    "project_path": "/path/to/project"
  }
}
```

**Watch the logs** (should show cache load):
```
[INFO] Loaded cache with 123 classes, 456 functions
[INFO] Auto-refresh skipped (cache loaded successfully) - use 'refresh_project' tool if needed
```

**Key indicators of success**:
- ✅ Returns in 2-5 seconds (not minutes)
- ✅ No "Progress: X/9788 files" messages
- ✅ No "Starting incremental analysis" message
- ✅ No "9788 added" message

### 6. Verify Queries Work
After cache load, test a query:
```json
{
  "tool": "search_classes",
  "arguments": {
    "pattern": ".*Editor.*"
  }
}
```

Should return results immediately from cached data.

### 7. Manual Refresh (When Needed)
If you actually modify code and want to refresh:
```json
{
  "tool": "refresh_project",
  "arguments": {
    "incremental": true
  }
}
```

This will run incremental analysis and only re-index changed files.

## What to Look For

### ✅ Success Signs:
- Cache loads in seconds (not minutes)
- No "9788 added" message in logs
- Queries return data immediately
- Log shows "Auto-refresh skipped"

### ❌ Failure Signs:
- Still re-indexing all files on restart
- Log shows "Starting incremental analysis"
- Log shows "9788 added"
- Takes minutes to become ready

## Logs to Check

**LM Studio Console** (stderr):
```
[INFO] Auto-refresh skipped (cache loaded successfully) - use 'refresh_project' tool if needed
```

**If you see this, the fix is working!**

## Known Limitations

With this temporary fix:
- Auto-refresh is **disabled** after server restart
- You must **manually** call `refresh_project` to detect file changes
- This is a tradeoff: fast startup vs auto-detection

## Next Steps

If this fix works:
1. We'll investigate why incremental analyzer fails after cache load
2. Implement proper fix that preserves auto-refresh functionality
3. Add session persistence so server remembers last project

If this fix doesn't work:
- The problem is elsewhere (cache loading itself, not auto-refresh)
- Need deeper investigation

## Reverting the Fix

If you want to revert:
```bash
git checkout mcp_server/cpp_mcp_server.py
```

This will restore the original behavior (with auto-refresh enabled).
