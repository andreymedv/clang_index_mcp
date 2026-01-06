# MCP Testing Skill - Technical Specification

> **Purpose:** Automated testing framework for C++ MCP Server using Claude Code Skills and Task agents.

## Overview

The MCP Testing Skill (`/test-mcp`) is a comprehensive testing automation system that manages the complete lifecycle of testing the C++ MCP Server:
- **Project Management**: Clone, configure, and prepare test projects
- **Server Orchestration**: Launch, monitor, and control MCP server instances
- **Test Execution**: Run predefined and custom test scenarios
- **Result Analysis**: Validate results, detect issues, provide recommendations

**Key Goal**: Eliminate manual testing loops, minimize token consumption, provide full automation for test scenarios and issue reproduction.

---

## Architecture

### High-Level Flow

```
User: /test-mcp test=issue-13 tier=2 protocol=sse

Skill (test-mcp)
  ↓
  ├─► Task Agent 1: Project Preparation
  │   - Validate project exists and is configured
  │   - Generate compile_commands.json if needed (CMake)
  │   - Return: {ready: true, project_path, compile_commands_path}
  │
  ├─► Task Agent 2: Server Management
  │   - Launch MCP server in background (SSE/stdio/HTTP)
  │   - Wait for server ready (health check)
  │   - Return: {server_pid, endpoint, status}
  │
  ├─► Task Agent 3: Test Execution
  │   - Execute test scenario (call MCP tools via curl/stdio)
  │   - Collect results and metrics
  │   - Return: {results, metrics, raw_logs_path}
  │
  ├─► Task Agent 4: Result Analysis
  │   - Validate against expected outcomes
  │   - Detect anomalies and issues
  │   - Return: {status: PASS/FAIL, issues, recommendations}
  │
  └─► Skill Output (to user)
      ✅/❌ Test: issue-13 (tier2, SSE)
      Files indexed: 5687/5700
      Time: 8m 42s
      Issues: [list]
      Recommendations: [actions]
```

### Task Agents Isolation

**Why Task agents?**
- Each agent runs in isolated context (minimal token usage)
- Agents communicate via structured results (not full logs)
- Background operations don't pollute main conversation
- Parallel execution where possible

**Agent Responsibilities:**

| Agent | Input | Output | Duration |
|-------|-------|--------|----------|
| **Project Preparation** | project_spec, tier | {ready, paths} | 10s-5m |
| **Server Management** | protocol, port, project | {server_info} | 5-10s |
| **Test Execution** | test_scenario, server | {results, metrics} | 30s-15m |
| **Result Analysis** | results, expected | {status, issues} | 5-10s |

---

## Command API

### Core Commands

#### 1. List Projects
```bash
/test-mcp list-projects
```
**Output:**
```
Available test projects:
  tier1: /home/andrey/repos/cplusplus_mcp/examples/compile_commands_example
         ~18 files, compile_commands.json: ✓
  tier2: /home/andrey/ProjectName
         ~5700 files, compile_commands.json: ✓
```

#### 2. Setup Project
```bash
/test-mcp setup-project url=https://github.com/protocolbuffers/protobuf [name=protobuf] [commit=v21.12] [build_dir=build]
/test-mcp setup-project path=/local/path [name=custom]
```
**Actions:**
- Clone repository (if URL) to `.test-projects/<name>/`
- Checkout specific commit/tag if specified (for reproducibility)
- Detect CMake project (CMakeLists.txt)
- Run: `cmake -B <build_dir> -DCMAKE_EXPORT_COMPILE_COMMANDS=ON`
- Validate compile_commands.json exists
- Add to project registry with commit hash

**Output:**
```
✓ Project 'protobuf' prepared
  Path: .test-projects/protobuf
  Files: 423 C++ files
  compile_commands.json: ✓ (build/compile_commands.json)
```

#### 3. Run Test
```bash
/test-mcp test=<scenario> [tier=1|2] [project=<name>] [protocol=sse|stdio|http]
```

**Examples:**
```bash
# Quick smoke test
/test-mcp test=basic-indexing tier=1

# Issue reproduction on tier2
/test-mcp test=issue-13 tier=2 protocol=sse

# Custom project test
/test-mcp test=incremental-refresh project=protobuf

# Full regression (all tests, tier1+tier2)
/test-mcp test=regression
```

**Output:**
```
✅ Test: basic-indexing (tier1, SSE)
   Files indexed: 18/18
   Time: 3.2s
   MCP Tools tested:
     - set_project_directory: ✓
     - get_indexing_status: ✓
     - search_classes: ✓ (found 5 classes)
     - search_functions: ✓ (found 12 functions)
   Issues: None
```

#### 4. Validate Project
```bash
/test-mcp validate-project project=<name>
```
**Checks:**
- Project directory exists
- compile_commands.json exists and valid JSON
- At least one C++ file present
- Build configuration matches project

**Output:**
```
✓ Project 'tier1' validation
  Directory: ✓
  compile_commands.json: ✓ (18 entries)
  C++ files: ✓ (18 found)
  Status: READY
```

#### 5. Remove Project
```bash
/test-mcp remove-project name=<name>
```
**Actions:**
- Delete `.test-projects/<name>/`
- Remove from registry
- Confirm deletion

#### 6. Health Check
```bash
/test-mcp health-check
```
**Checks:**
- MCP server can start (stdio mode)
- Basic tool calls work (list_tools)
- libclang available
- Python environment OK

---

## Test Scenarios

### Predefined Scenarios

#### 1. `basic-indexing`
**Purpose:** Quick smoke test of core functionality
**Project:** tier1 (small, fast)
**Steps:**
1. Start server (SSE)
2. `set_project_directory` → tier1 path
3. Wait for indexing complete (`get_indexing_status`)
4. Verify file count matches expected (18 files)
5. Test basic searches (`search_classes`, `search_functions`)
6. Shutdown server

**Expected:** All files indexed, basic tools work
**Duration:** ~5-10 seconds

#### 2. `issue-13` (boost headers with wrong args)
**Purpose:** Reproduce Issue #13 - headers included by multiple sources parsed with wrong args
**Project:** tier2 (large, has boost dependencies)
**Steps:**
1. Start server (SSE)
2. `set_project_directory` → tier2 path
3. Wait for indexing complete
4. Query specific boost header symbols that were failing
5. Verify symbols are found correctly
6. Check parse error logs for boost headers

**Expected (before fix):** Some boost headers fail to parse or parse with wrong symbols
**Expected (after fix):** All boost headers parse correctly
**Duration:** ~5-15 minutes

#### 3. `incremental-refresh`
**Purpose:** Test incremental analysis after file changes
**Project:** tier1
**Steps:**
1. Initial indexing
2. Modify one source file (add a function)
3. Call `refresh_project`
4. Verify only modified file + dependents re-indexed
5. Verify new symbol appears in search results
6. Check metrics: incremental speedup vs full re-index

**Expected:** 10-30x speedup, new symbol found
**Duration:** ~10-20 seconds

#### 4. `all-protocols`
**Purpose:** Verify all transport protocols work
**Project:** tier1
**Steps:**
1. Test stdio mode (basic tool call)
2. Test SSE mode (basic tool call)
3. Test HTTP mode (basic tool call)
4. Verify results identical across protocols

**Expected:** All protocols functional
**Duration:** ~15-30 seconds

#### 5. `regression`
**Purpose:** Full regression test suite
**Runs:** All above tests on tier1 and tier2
**Expected:** All tests pass
**Duration:** ~15-20 minutes

### Custom Scenarios

Users can define custom test scenarios in YAML:

```yaml
# .test-scenarios/custom-test.yaml
name: custom-analysis
project: protobuf
protocol: sse
steps:
  - tool: set_project_directory
    args: {path: "$PROJECT_PATH"}
  - tool: wait_for_indexing
  - tool: search_classes
    args: {pattern: "Message"}
    expect:
      - count: "> 10"
      - names_include: ["MessageLite", "Message"]
  - tool: get_class_info
    args: {class_name: "Message"}
    expect:
      - has_methods: true
```

---

## Project Management

### Project Registry

**Location:** `.test-projects/registry.json` (in repository root, gitignored)

**Storage Strategy:**
- **Persistent storage**: Projects remain between Claude Code sessions
- **Git ignored**: `.test-projects/` added to `.gitignore`
- **User-managed cleanup**: No automatic deletion of old projects
- **Commit pinning**: Cloned projects use specific commit/tag for reproducibility

Stored in `.test-projects/registry.json`:

```json
{
  "version": "1.0",
  "projects": {
    "tier1": {
      "type": "builtin",
      "path": "/home/andrey/repos/cplusplus_mcp/examples/compile_commands_example",
      "compile_commands": "compile_commands.json",
      "file_count": 18,
      "created": "2025-12-27T10:00:00Z",
      "last_validated": "2025-12-27T10:00:00Z",
      "last_used": "2025-12-27T14:30:00Z"
    },
    "tier2": {
      "type": "builtin",
      "path": "/home/andrey/ProjectName",
      "compile_commands": "build.debug/compile_commands.json",
      "file_count": 5700,
      "created": "2025-12-27T10:00:00Z",
      "last_validated": "2025-12-27T10:00:00Z",
      "last_used": "2025-12-27T12:00:00Z"
    },
    "protobuf": {
      "type": "cloned",
      "source_url": "https://github.com/protocolbuffers/protobuf",
      "commit": "a1b2c3d4e5f",
      "tag": "v21.12",
      "path": ".test-projects/protobuf",
      "compile_commands": "build/compile_commands.json",
      "build_dir": "build",
      "file_count": 423,
      "disk_usage_mb": 156,
      "created": "2025-12-27T11:00:00Z",
      "last_validated": "2025-12-27T11:00:00Z",
      "last_used": "2025-12-27T14:30:00Z"
    }
  }
}
```

### CMake Configuration Workflow

For projects requiring `compile_commands.json` generation:

1. **Detect CMake:** Look for `CMakeLists.txt`
2. **Configure:**
   ```bash
   mkdir -p <build_dir>
   cmake -B <build_dir> -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
   ```
3. **Validate:** Check `<build_dir>/compile_commands.json` exists
4. **Register:** Add to project registry with paths

**Error Handling:**
- If CMake fails, ask user for manual configuration
- If no CMakeLists.txt, inform user CMake not detected
- Provide fallback: user can manually generate and specify path

---

## Result Reporting

### Output Format

**Minimal (default):**
```
✅ Test: basic-indexing (tier1, SSE, 3.2s)
   Files: 18/18, Issues: None
```

**Standard (most tests):**
```
✅ Test: incremental-refresh (tier1, SSE)
   Initial indexing: 18 files, 3.1s
   File modified: src/example.cpp (+1 function)
   Incremental refresh: 2 files, 0.2s (15.5x speedup)
   New symbol found: ✓ newFunction()
   Issues: None
```

**Detailed (on failure or verbose mode):**
```
❌ Test: issue-13 (tier2, SSE)
   Files indexed: 5687/5700 (13 failed)
   Time: 8m 42s
   Issues:
     1. Parse errors in boost headers (13 files)
        - boost/mpl/vector.hpp: "expected ';' after class"
        - boost/fusion/include/vector.hpp: similar errors
        Cause: Headers parsed with wrong compilation args
        See: .test-results/20251227_100000/parse_errors.log

     2. Missing symbols in search results
        - Expected: boost::mpl::vector class
        - Found: not in index

   Recommendations:
     - Apply header tracking fix from Issue #13
     - Re-run test after fix

   Logs: .test-results/20251227_100000/
```

### Test Results Storage

```
.test-results/
├── 20251227_100000_basic-indexing_tier1_sse/
│   ├── test-config.json          # Test parameters
│   ├── server.log                # MCP server output
│   ├── test-execution.log        # Test step logs
│   ├── results.json              # Structured results
│   └── metrics.json              # Performance metrics
├── 20251227_101500_issue-13_tier2_sse/
│   ├── test-config.json
│   ├── server.log
│   ├── parse_errors.log          # Extracted parse errors
│   ├── results.json
│   └── metrics.json
└── latest -> 20251227_101500_issue-13_tier2_sse/
```

---

## Implementation Plan

### Phase 1: MVP - Basic Skill with Tier 1/2 (Week 1)

**Goal:** Working skill with 2-3 basic tests on existing projects

**Deliverables:**
1. Skill structure in `.claude/skills/test-mcp/`
   - `__init__.py` - Entry point
   - `project_manager.py` - Project registry
   - `test_runner.py` - Test orchestration
   - `scenarios/` - Test scenario definitions

2. Commands implemented:
   - `/test-mcp list-projects` (tier1, tier2 only)
   - `/test-mcp test=basic-indexing tier=1`
   - `/test-mcp test=issue-13 tier=2`

3. Test scenarios:
   - `basic-indexing` (tier1, SSE only)
   - `issue-13` (tier2, SSE only)

4. Output: Minimal format

**Success Criteria:**
- Can run basic-indexing test end-to-end
- Can reproduce Issue #13
- Results reported clearly (PASS/FAIL)

### Phase 2: Project Management (Week 2)

**Goal:** Add project setup and CMake support

**Deliverables:**
1. Commands:
   - `/test-mcp setup-project url=... name=...`
   - `/test-mcp validate-project project=...`
   - `/test-mcp remove-project name=...`

2. CMake integration:
   - Auto-detect CMakeLists.txt
   - Run cmake with DCMAKE_EXPORT_COMPILE_COMMANDS=ON
   - Validate compile_commands.json

3. Project registry (`.test-projects/registry.json`)

**Success Criteria:**
- Can clone and configure public CMake project (e.g., protobuf)
- Project added to registry
- Can run tests on new project

### Phase 3: Extended Test Scenarios (Week 3)

**Goal:** Add more test scenarios and protocol support

**Deliverables:**
1. Test scenarios:
   - `incremental-refresh`
   - `all-protocols` (stdio/SSE/HTTP)
   - `regression`

2. Protocol support:
   - stdio mode testing
   - HTTP mode testing
   - SSE mode (already working)

3. Output formats:
   - Standard format with metrics
   - Detailed format on failure

**Success Criteria:**
- All 5 predefined scenarios work
- All 3 protocols tested
- Proper error reporting

### Phase 4: Advanced Features (Week 4)

**Goal:** Custom scenarios, analysis, recommendations

**Deliverables:**
1. Custom scenario support (YAML definitions)
2. Result analysis agent (detect patterns, suggest fixes)
3. Auto-fix capability (optional, with user approval)
4. Integration with pytest (can run existing tests)

**Success Criteria:**
- Can define and run custom test scenario
- Skill can suggest fixes for known issues
- Can trigger pytest suite from skill

### Phase 5: Polish & Documentation (Week 5)

**Goal:** Production-ready, documented

**Deliverables:**
1. Comprehensive user documentation
2. Error handling and edge cases
3. Performance optimizations
4. Example scenarios for common use cases

---

## Technical Details

### Task Agent Communication

Agents communicate via structured JSON results stored in temporary files:

**Project Preparation Agent:**
```json
{
  "status": "ready",
  "project_path": "/path/to/project",
  "compile_commands_path": "/path/to/compile_commands.json",
  "file_count": 423,
  "validation": {
    "directory_exists": true,
    "compile_commands_valid": true,
    "cpp_files_found": true
  }
}
```

**Server Management Agent:**
```json
{
  "status": "running",
  "protocol": "sse",
  "endpoint": "http://localhost:8000",
  "pid": 12345,
  "health_check": "OK"
}
```

**Test Execution Agent:**
```json
{
  "status": "completed",
  "results": {
    "set_project_directory": {"success": true, "time_ms": 100},
    "get_indexing_status": {"success": true, "files_indexed": 18, "time_ms": 50},
    "search_classes": {"success": true, "results_count": 5, "time_ms": 2}
  },
  "metrics": {
    "total_time_s": 3.2,
    "files_indexed": 18,
    "indexing_time_s": 2.8
  },
  "logs_path": ".test-results/20251227_100000/test-execution.log"
}
```

### Server Lifecycle Management

**Startup:**
```python
# Skill launches background process via Task agent
# Agent uses Bash(run_in_background=true)
server_pid = launch_server(protocol="sse", port=8000, project_path=path)

# Wait for health check
wait_for_server(endpoint="http://localhost:8000", timeout=30)
```

**Shutdown:**
```python
# Always cleanup, even on failure
try:
    run_test(server_endpoint)
finally:
    kill_server(server_pid)
    verify_no_orphans()
```

**Monitoring:**
```python
# Task agent monitors server during test
monitor_server_health(pid, check_interval=5)
# If server crashes, immediately fail test and report
```

### Protocol-Specific Testing

**SSE (recommended for testing):**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}'
```

**stdio:**
```python
# Send JSON-RPC via stdin, read from stdout
echo '{"jsonrpc":"2.0","method":"tools/call",...}' | python -m mcp_server.cpp_mcp_server
```

**HTTP:**
```bash
curl -s -X POST http://localhost:8000/mcp/v1/tools/call -d '{...}'
```

---

## Security Considerations

### Proprietary Code Protection

**CRITICAL:** Skill must respect proprietary code boundaries:

- ✅ Can use tier2 (/home/andrey/ProjectName) for testing
- ✅ Can call MCP tools on tier2 project
- ✅ Can analyze MCP tool *responses* (symbol lists, etc.)
- ❌ NEVER read tier2 source file contents directly
- ❌ NEVER display tier2 code in logs or output

**Implementation:**
```python
# In test execution agent
if project.is_proprietary:
    # Only use MCP tools, never Read tool on source files
    allowed_tools = ["search_*", "get_*", "find_*"]  # MCP tools only
    forbidden_tools = ["Read", "Grep"]  # on project files
```

### Safe Project Cloning

**When cloning public projects:**
- Validate URL is from known hosting (github.com, gitlab.com, etc.)
- Clone to isolated `.test-projects/` directory
- Never clone with `--recursive` by default (avoid huge submodules)
- Size limit: warn if repo > 500MB

---

## Future Enhancements

**Post-MVP features to consider:**

1. **Parallel Test Execution:** Run multiple tests concurrently
2. **Continuous Testing:** Watch for code changes, auto-run tests
3. **Performance Regression Detection:** Compare metrics across runs
4. **Issue Bisection:** Auto-bisect to find commit that introduced issue
5. **Test Report Dashboard:** HTML report with charts and trends
6. **Integration with GitHub Actions:** Run tests in CI

---

## Appendix: Example Usage Session

```bash
# Initial setup
$ /test-mcp list-projects
Available projects: tier1, tier2

# Setup a new project for testing
$ /test-mcp setup-project url=https://github.com/protocolbuffers/protobuf name=protobuf
⏳ Cloning protobuf...
⏳ Configuring CMake...
✓ Project 'protobuf' prepared (423 C++ files)

# Run quick smoke test
$ /test-mcp test=basic-indexing tier=1
⏳ Starting server (SSE)...
⏳ Indexing tier1 project...
✅ Test: basic-indexing (tier1, SSE, 3.2s)
   Files: 18/18, Issues: None

# Reproduce an issue
$ /test-mcp test=issue-13 tier=2
⏳ Starting server (SSE)...
⏳ Indexing tier2 project (~5700 files)...
❌ Test: issue-13 (tier2, SSE, 8m 42s)
   Files: 5687/5700 (13 failed - boost headers)
   Issue confirmed: boost headers parsed with wrong args
   Recommendation: Apply header tracking fix

# After applying fix, re-test
$ /test-mcp test=issue-13 tier=2
⏳ Starting server (SSE)...
⏳ Indexing tier2 project...
✅ Test: issue-13 (tier2, SSE, 9m 15s)
   Files: 5700/5700, Issues: None
   ✓ Issue #13 FIXED

# Run full regression before PR
$ /test-mcp test=regression
⏳ Running regression suite (5 tests, tier1+tier2)...
✅ All tests passed (12m 34s)
   Ready for PR
```
