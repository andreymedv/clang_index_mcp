# Claude Testing Guide - MCP Server Testing

**Audience:** Claude Code (AI assistant)
**Purpose:** Guide for testing and debugging MCP server functionality
**Created:** 2025-12-21
**Updated:** 2025-12-21 (Revised based on practical testing experience)

## Overview

This guide describes different approaches for testing the C++ MCP server. Choose the appropriate method based on what you're testing.

## Testing Approaches

### Approach 1: Direct Python Testing (Recommended for Quick Validation)

**Best for:** Quick iteration during development, verifying code fixes, unit-style testing

**How it works:**
- Create simple Python scripts that import CppAnalyzer directly
- Test specific functionality without MCP protocol overhead
- Fast, simple, no network complexity

**Example:**
```python
from mcp_server.cpp_analyzer import CppAnalyzer

analyzer = CppAnalyzer("examples/compile_commands_example")
analyzer.index_project()
print(f"Files indexed: {len(analyzer.file_index)}")
```

**Pros:**
- ✅ Extremely simple - just import and use
- ✅ Fast iteration (no server startup)
- ✅ Easy to debug (direct Python debugging)
- ✅ No protocol complexity
- ✅ Perfect for fixing and verifying individual issues

**Cons:**
- ❌ Doesn't test MCP protocol layer
- ❌ Doesn't test client integration
- ❌ Doesn't test transport (SSE/HTTP/stdio)

**When to use:**
- Fixing and testing Issue #10, #13, #12 (code-level fixes)
- Verifying analyzer behavior
- Quick validation during development
- Unit-style testing

---

### Approach 2: SSE Testing via MCP Client Libraries (For Integration Testing)

**Best for:** Testing MCP protocol, client integration, end-to-end workflows

**How it works:**
- Use MCP Python SDK or client libraries
- Connect via SSE protocol
- Test full request/response flow

**Note:** Direct curl testing of SSE is complex due to session management. SSE protocol requires:
1. Establishing session via GET /sse
2. Receiving session ID
3. POST messages to /messages with session context
4. This is NOT a simple REST API

**Pros:**
- ✅ Tests full MCP protocol
- ✅ Tests client integration
- ✅ Realistic end-to-end testing

**Cons:**
- ❌ Requires MCP client library setup
- ❌ More complex than direct Python testing
- ❌ Slower iteration

**When to use:**
- Final integration testing before release
- Testing MCP protocol compliance
- Testing with actual MCP clients
- End-to-end workflow validation

---

### Approach 3: Using test_mcp_console.py (Existing Test Script)

**Best for:** Manual testing with real codebases, demonstrations

**How it works:**
- Run existing `scripts/test_mcp_console.py` script
- Interactive console-style testing
- Tests analyzer directly (like Approach 1)

**Usage:**
```bash
python scripts/test_mcp_console.py /path/to/cpp/project
```

**Pros:**
- ✅ Ready to use (already in repo)
- ✅ Tests with real codebases
- ✅ Interactive feedback

**Cons:**
- ❌ May need updates (references removed translation_units)
- ❌ Not automated

**When to use:**
- Manual testing with real projects
- Demonstrating functionality
- Quick exploratory testing

## Testing Strategy: Two-Tier Approach

### Tier 1: Quick Validation (examples/)
**Use for:** Rapid iteration during development, basic functionality verification

**Project:** `examples/compile_commands_example/`
- Small, fast (~10-20 files)
- Has compile_commands.json
- Quick indexing (<5 seconds)
- Good for testing core functionality without complexity

**When to use:**
- During active development of a fix
- Testing basic MCP tool responses
- Verifying state transitions
- Quick smoke tests after code changes

### Tier 2: Real-World Validation (Large Projects)
**Use for:** Final validation, performance testing, reproducing complex issues

**Project:** See `.claude/CLAUDE.md` for actual project paths (local only, not in git)
- Large codebase (1000+ files)
- Real third-party dependencies (boost, vcpkg, etc.)
- compile_commands.json from real build
- Reproduces issues like FD leaks, parse errors with dependencies

**When to use:**
- Final validation before PR
- Testing issues that require complexity (Issue #13 boost headers, Issue #3 FD leak)
- Performance benchmarking
- Integration testing with real-world scenarios

---

## SSE Server Setup

### Starting the Server

**Basic startup:**
```bash
# From project root
python -m mcp_server.cpp_mcp_server --transport sse --port 8000
```

**With debug logging:**
```bash
MCP_DEBUG=1 PYTHONUNBUFFERED=1 python -m mcp_server.cpp_mcp_server --transport sse --port 8000
```

**In background (for automated testing):**
```bash
python -m mcp_server.cpp_mcp_server --transport sse --port 8000 &
SERVER_PID=$!

# Later, to stop:
kill $SERVER_PID
```

**Expected output:**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Verifying Server is Running

```bash
# Check if server is listening
curl -s http://localhost:8000/health || echo "Server not running"

# Check process
ps aux | grep cpp_mcp_server
```

---

## MCP Protocol via SSE

### HTTP Endpoints

SSE transport provides these endpoints:
- `POST /mcp/v1/tools/list` - List available tools
- `POST /mcp/v1/tools/call` - Call a tool
- `POST /mcp/v1/prompts/list` - List prompts (if any)
- `POST /mcp/v1/resources/list` - List resources (if any)

All use JSON-RPC 2.0 protocol.

### Request Format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {}
}
```

### Response Format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [...]
  }
}
```

---

## Testing MCP Tools with curl

### 1. List Available Tools

```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/list \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | jq '.'
```

**Expected:** JSON response with 16 tools listed

---

### 2. Set Project Directory

**Template:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "set_project_directory",
      "arguments": {
        "path": "/path/to/your/cpp/project"
      }
    }
  }' | jq -r '.result.content[0].text'
```

**Quick test (examples/):**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "set_project_directory",
      "arguments": {
        "path": "/home/andrey/repos/cplusplus_mcp/examples/compile_commands_example"
      }
    }
  }' | jq -r '.result.content[0].text'
```

**Expected output:**
```
Set project directory to: /path/to/your/cpp/project
Indexing started in background. Auto-refresh enabled.
Use 'get_indexing_status' to check progress.
Tools are available but will return partial results until indexing completes.
```

---

### 3. Get Indexing Status

**Template:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_indexing_status",
      "arguments": {}
    }
  }' | jq '.'
```

**Expected during indexing:**
```json
{
  "state": "indexing",
  "is_fully_indexed": false,
  "is_ready_for_queries": true,
  "progress": {
    "indexed_files": 123,
    "total_files": 500,
    "completion_percentage": 24.6,
    "current_file": "/path/to/file.cpp",
    "eta_seconds": 12.3
  }
}
```

**Expected after completion:**
```json
{
  "state": "indexed",
  "is_fully_indexed": true,
  "is_ready_for_queries": true,
  "progress": null
}
```

**Testing Issue #1 (state race):**
```bash
# Set directory and immediately query status (should work, not fail)
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"set_project_directory","arguments":{"path":"/path/to/project"}}}' > /dev/null

# Immediate status query (Issue #1: used to fail with "directory not set")
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
  | jq -r '.result.content[0].text'
```

---

### 4. Get Server Status

**Template:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "get_server_status",
      "arguments": {}
    }
  }' | jq '.'
```

**Expected output:**
```json
{
  "analyzer_type": "python_enhanced",
  "call_graph_enabled": true,
  "usr_tracking_enabled": true,
  "compile_commands_enabled": true,
  "compile_commands_path": "/path/to/build/compile_commands.json",
  "compile_commands_cache_enabled": true,
  "parsed_files": 5678,
  "indexed_classes": 1234,
  "indexed_functions": 4567,
  "project_files": 5678
}
```

**Testing Issue #10 (file counts):**
```bash
# After indexing completes, verify counts are non-zero
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_server_status","arguments":{}}}' \
  | jq '.result.content[0].text | fromjson | {parsed_files, project_files}'

# Should show: {"parsed_files": 123, "project_files": 123}
# NOT: {"parsed_files": 0, "project_files": 0}
```

---

### 5. Search Classes

**Template:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {
        "pattern": ".*",
        "limit": 10
      }
    }
  }' | jq -r '.result.content[0].text'
```

**Search for specific class:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {
        "pattern": "MyClass"
      }
    }
  }' | jq -r '.result.content[0].text'
```

**List all classes in specific file:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "search_classes",
      "arguments": {
        "pattern": ".*",
        "file_name": "MyFile.h"
      }
    }
  }' | jq -r '.result.content[0].text'
```

---

### 6. Refresh Project

**Incremental refresh:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "refresh_project",
      "arguments": {
        "incremental": true
      }
    }
  }' | jq -r '.result.content[0].text'
```

**Force full refresh:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "refresh_project",
      "arguments": {
        "force_full": true
      }
    }
  }' | jq -r '.result.content[0].text'
```

**Expected (Issue #2 fixed - non-blocking):**
```
Refresh started in background (incremental mode).
Checking for file changes and re-analyzing as needed.
Use 'get_indexing_status' to monitor progress.
Tools remain available during refresh.
```

**Testing Issue #11 (progress reporting):**
```bash
# Start refresh
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' > /dev/null

# Poll status during refresh
while true; do
  STATUS=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
    | jq -r '.result.content[0].text | fromjson | .state')

  echo "State: $STATUS"

  if [ "$STATUS" = "indexed" ]; then
    break
  fi

  sleep 2
done
```

---

## Testing Workflow

### Standard Test Sequence

```bash
#!/bin/bash
# Complete test workflow

PROJECT_PATH="/path/to/your/cpp/project"

echo "=== 1. Set project directory ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"set_project_directory\",\"arguments\":{\"path\":\"$PROJECT_PATH\"}}}" \
  | jq -r '.result.content[0].text'

echo -e "\n=== 2. Get indexing status (immediate - tests Issue #1) ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
  | jq -r '.result.content[0].text'

echo -e "\n=== 3. Wait for indexing to complete ==="
while true; do
  STATE=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
    | jq -r '.result.content[0].text | fromjson | .state')

  echo "State: $STATE"

  if [ "$STATE" = "indexed" ]; then
    break
  fi

  sleep 2
done

echo -e "\n=== 4. Get server status (tests Issue #10) ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"get_server_status","arguments":{}}}' \
  | jq '.result.content[0].text | fromjson | {parsed_files, indexed_classes, indexed_functions, project_files}'

echo -e "\n=== 5. Search for classes (baseline) ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"search_classes","arguments":{"pattern":".*","limit":5}}}' \
  | jq -r '.result.content[0].text'

echo -e "\n=== 6. Refresh project (tests Issue #2) ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' \
  | jq -r '.result.content[0].text'

echo -e "\n=== 7. Verify classes still present (tests Issue #8) ==="
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"search_classes","arguments":{"pattern":".*","limit":5}}}' \
  | jq -r '.result.content[0].text'
```

---

## Debugging Techniques

### 1. Server Logs

**Watch logs in real-time:**
```bash
# Start server with debug logging and watch output
MCP_DEBUG=1 PYTHONUNBUFFERED=1 python -m mcp_server.cpp_mcp_server --transport sse --port 8000 2>&1 | tee server.log
```

**Grep for specific issues:**
```bash
# Issue #12: Database connection errors
tail -f server.log | grep -i "closed database"

# Issue #13: Header parse errors
tail -f server.log | grep -E "(boost|Foundation).* not found"

# General errors
tail -f server.log | grep -E "\[ERROR\]|\[WARNING\]"
```

### 2. Resource Monitoring

**Monitor file descriptors (Issue #3):**
```bash
# Get server PID
SERVER_PID=$(pgrep -f "cpp_mcp_server.*sse.*8000" | head -1)

# Monitor FD count (should stay stable at ~10-15)
watch -n 2 "echo '=== FD Monitor ==='; \
  echo 'Main: \$(ls /proc/$SERVER_PID/fd 2>/dev/null | wc -l) FDs'; \
  pgrep -P $SERVER_PID | while read wpid; do \
    echo 'Worker \$wpid: \$(ls /proc/\$wpid/fd 2>/dev/null | wc -l) FDs'; \
  done"

# Check for open C++ files (should be near zero)
lsof -p $SERVER_PID $(pgrep -P $SERVER_PID | tr '\n' ',' | sed 's/,$//' | sed 's/^/,/') 2>/dev/null | \
  grep -E '\.(cpp|h|cc|hpp)$' | wc -l
```

**Monitor memory usage:**
```bash
# Memory per process
ps -p $SERVER_PID $(pgrep -P $SERVER_PID | tr '\n' ',') -o pid,rss,cmd --no-headers | \
  awk '{printf "PID %s: %.1f MB - %s\n", $1, $2/1024, substr($0, index($0,$3))}'
```

### 3. Cache Inspection

**Diagnose cache health:**
```bash
python scripts/diagnose_cache.py /path/to/project

# Check for corrupted databases
python scripts/fix_corrupted_cache.py /path/to/project
```

**View cache statistics:**
```bash
python scripts/cache_stats.py
```

### 4. Parse Error Diagnostics

**Diagnose specific file:**
```bash
python scripts/diagnose_parse_errors.py /path/to/project /path/to/file.cpp
```

**View centralized error log:**
```bash
python scripts/view_parse_errors.py /path/to/project
```

---

## Issue-Specific Testing

### Issue #1: State Synchronization Race

**Test procedure:**
1. Start server
2. Call `set_project_directory`
3. **Immediately** call `get_indexing_status` (no delay)
4. Should return valid state, NOT "Project directory not set"

**Validation:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"set_project_directory","arguments":{"path":"/path/to/project"}}}' > /dev/null

# Immediate query (zero delay)
RESPONSE=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
  | jq -r '.result.content[0].text')

# Should NOT contain "not set"
echo "$RESPONSE" | grep -q "not set" && echo "FAIL: Issue #1 still present" || echo "PASS: Issue #1 fixed"
```

---

### Issue #10: File Counts Zero

**Test procedure:**
1. Index a project with files
2. Call `get_server_status`
3. Check `parsed_files` and `project_files` are non-zero

**Validation:**
```bash
# After indexing completes
COUNTS=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_server_status","arguments":{}}}' \
  | jq '.result.content[0].text | fromjson | {parsed_files, project_files}')

echo "$COUNTS"

# Check for zeros
echo "$COUNTS" | grep -q '"parsed_files": 0' && echo "FAIL: Issue #10 still present" || echo "PASS: Issue #10 fixed"
```

---

### Issue #13: Headers with Wrong Args

**Test procedure:**
1. Index large project with third-party dependencies (boost, vcpkg)
2. Modify a header file
3. Call `refresh_project(incremental=true)`
4. Check logs for boost/Foundation header errors

**Validation:**
```bash
# Modify a header to trigger refresh
touch /path/to/project/SomeHeader.h

# Start refresh
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' > /dev/null

# Watch logs for header errors
tail -20 server.log | grep -E "boost|Foundation.*not found" && \
  echo "FAIL: Issue #13 still present" || \
  echo "PASS: No third-party header errors"
```

---

### Issue #12: Database Connection Errors

**Test procedure:**
1. Index project
2. Call `refresh_project(incremental=true)`
3. Check logs for "Cannot operate on a closed database"

**Validation:**
```bash
# Start refresh
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' > /dev/null

# Wait for completion
sleep 5

# Check logs
tail -50 server.log | grep -i "closed database" && \
  echo "FAIL: Issue #12 still present" || \
  echo "PASS: No database connection errors"
```

---

### Issue #8: Missing Headers After Refresh

**Test procedure:**
1. Index project
2. Search for header file and verify found
3. Refresh project
4. Search for same header, verify still found

**Validation:**
```bash
# Baseline: search for header
BEFORE=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_classes","arguments":{"pattern":".*","file_name":"MyHeader.h"}}}' \
  | jq -r '.result.content[0].text' | grep -c "MyHeader.h")

echo "Headers found before refresh: $BEFORE"

# Refresh
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' > /dev/null

# Wait for completion
sleep 5

# Check after refresh
AFTER=$(curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_classes","arguments":{"pattern":".*","file_name":"MyHeader.h"}}}' \
  | jq -r '.result.content[0].text' | grep -c "MyHeader.h")

echo "Headers found after refresh: $AFTER"

[ "$BEFORE" -eq "$AFTER" ] && echo "PASS: Headers preserved" || echo "FAIL: Issue #8 - headers missing"
```

---

## Quick Reference Commands

### Server Management
```bash
# Start server
python -m mcp_server.cpp_mcp_server --transport sse --port 8000

# Start with debug
MCP_DEBUG=1 PYTHONUNBUFFERED=1 python -m mcp_server.cpp_mcp_server --transport sse --port 8000

# Stop server (if running in background)
pkill -f "cpp_mcp_server.*sse"
```

### Common Tool Calls
```bash
# Set directory
curl -s -X POST http://localhost:8000/mcp/v1/tools/call -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"set_project_directory","arguments":{"path":"PROJECT_PATH"}}}' | jq -r '.result.content[0].text'

# Get status
curl -s -X POST http://localhost:8000/mcp/v1/tools/call -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' | jq '.'

# Refresh
curl -s -X POST http://localhost:8000/mcp/v1/tools/call -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"refresh_project","arguments":{"incremental":true}}}' | jq -r '.result.content[0].text'
```

### Monitoring
```bash
# FD count
lsof -p $(pgrep -f cpp_mcp_server) | wc -l

# Memory usage
ps -p $(pgrep -f cpp_mcp_server) -o rss=

# Watch logs
tail -f server.log | grep -E "ERROR|WARNING"
```

---

## Best Practices

### 1. Always Start Fresh
- Kill existing server instances before starting new tests
- Clear cache if testing from clean state: `rm -rf .mcp_cache/`
- Use separate terminals for server and testing commands

### 2. Use jq for Response Parsing
- Install jq: `sudo apt install jq` (Linux) or `brew install jq` (macOS)
- Parse JSON responses easily
- Extract specific fields for validation

### 3. Monitor Resources
- Watch FD counts during large project indexing
- Monitor memory usage during refresh operations
- Check for error logs in real-time

### 4. Save Test Scripts
- Create reusable test scripts for common workflows
- Version control test scripts in `scripts/test_*.sh`
- Document expected outputs

### 5. Incremental Testing
- Start with small project (examples/)
- Verify basic functionality works
- Move to large project for final validation
- Don't skip quick tests to save time

---

## Troubleshooting

### Server Won't Start
```bash
# Check if port already in use
lsof -i :8000

# Kill process using port
kill $(lsof -t -i :8000)

# Try different port
python -m mcp_server.cpp_mcp_server --transport sse --port 8001
```

### Tool Call Returns Error
```bash
# Check response for error details
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{...}}' \
  | jq '.error'

# Check server logs
tail -50 server.log
```

### Timeout During Indexing
```bash
# Check if indexing actually running
ps aux | grep cpp_mcp_server

# Check progress
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_indexing_status","arguments":{}}}' \
  | jq '.result.content[0].text | fromjson | .progress'
```

### Database Corruption
```bash
# Diagnose and fix
python scripts/fix_corrupted_cache.py /path/to/project

# Nuclear option: clear cache
rm -rf .mcp_cache/
```

---

## Notes

- **Real project paths:** See `.claude/CLAUDE.md` for actual paths (local only)
- **Port conflicts:** Change port if 8000 is in use
- **Debug logging:** Enable `MCP_DEBUG=1` for verbose output (increases token usage)
- **Long operations:** Some operations (large project indexing) may take minutes
- **Background mode:** Use `&` to run server in background, capture PID for later kill
