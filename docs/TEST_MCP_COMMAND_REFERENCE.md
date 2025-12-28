# MCP Testing Skill - Command Reference

Complete reference for all `/test-mcp` commands.

## Command Syntax

```
/test-mcp <command> [parameters]
```

Parameters are passed as `key=value` pairs.

---

## Commands

### list-projects

List all registered test projects.

**Syntax:**
```bash
/test-mcp list-projects
```

**Parameters:** None

**Output:**
```
Available test projects:
  tier1: /path/to/examples/compile_commands_example
         ~18 files, compile_commands.json: ✓
  tier2: /path/to/myoffice
         ~5700 files, compile_commands.json: ✓
```

**Exit Codes:**
- 0: Success

---

### test

Run a test scenario (built-in or custom YAML).

**Syntax:**
```bash
/test-mcp test=<scenario> [tier=<1|2>] [project=<name>] [protocol=<http|sse|stdio>] [scenario=<path>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `test` | Yes | - | Scenario name or "custom" |
| `tier` | No | 1 | Use tier1 or tier2 project |
| `project` | No | - | Use specific project (overrides tier) |
| `protocol` | No | http | Transport protocol to use |
| `scenario` | Conditional | - | Path to YAML file (required if test=custom) |

**Built-in Scenarios:**
- `basic-indexing` - Quick smoke test
- `issue-13` - Boost headers test
- `incremental-refresh` - Incremental analysis test
- `all-protocols` - Protocol compatibility test
- `custom` - Run custom YAML scenario (requires scenario= parameter)

**Examples:**
```bash
# Run built-in scenario on tier1
/test-mcp test=basic-indexing tier=1

# Run on specific project
/test-mcp test=basic-indexing project=json-test

# Run with SSE protocol
/test-mcp test=basic-indexing tier=1 protocol=sse

# Run custom YAML scenario
/test-mcp test=custom scenario=quick-check.yaml tier=1

# Run custom scenario with full path
/test-mcp test=custom scenario=/path/to/test.yaml tier=1
```

**Output:**
```
⏳ Starting MCP server (HTTP mode)...
✓ Server started (PID: 12345)
⏳ Running test scenario 'basic-indexing'...
  Setting project directory...
  Waiting for indexing to complete...
  Testing search_classes...
  Testing search_functions...
⏳ Analyzing results...
⏳ Stopping MCP server...
✓ Server stopped

✅ Test: basic-indexing (tier1, HTTP, 3.2s)
   Files indexed: 18/18
   Classes found: 5 (expected: 5)
   Functions found: 12 (expected: 12)
   Issues: None
   Logs: .test-results/20251228_100000_basic-indexing_tier1_http/
```

**Exit Codes:**
- 0: Test passed
- 1: Test failed or error

---

### setup-project

Clone and configure a C++ project from GitHub.

**Syntax:**
```bash
/test-mcp setup-project url=<github-url> [name=<name>] [tag=<tag>] [commit=<hash>] [build-dir=<dir>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `url` | Yes | - | GitHub repository URL |
| `name` | No | Repo name | Project name for registry |
| `tag` | No | - | Git tag to checkout |
| `commit` | No | - | Git commit hash to checkout |
| `build-dir` | No | build | CMake build directory name |

**Examples:**
```bash
# Clone with default settings
/test-mcp setup-project url=https://github.com/nlohmann/json

# Clone with custom name and tag
/test-mcp setup-project url=https://github.com/nlohmann/json name=json-test tag=v3.11.3

# Clone specific commit
/test-mcp setup-project url=https://github.com/user/repo commit=abc123def
```

**What It Does:**
1. Clones repository to `.test-projects/<name>/`
2. Checks out specified tag or commit (if provided)
3. Detects `CMakeLists.txt`
4. Runs `cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON` (if CMake found)
5. Validates `compile_commands.json`
6. Calculates disk usage
7. Adds project to registry

**Output:**
```
Setting up project from https://github.com/nlohmann/json...
Project name: json-test
Tag: v3.11.3

Cloning https://github.com/nlohmann/json to .test-projects/json-test...
Checking out v3.11.3...
CMakeLists.txt detected, configuring with CMake...
CMake configuration successful, 85 compilation units

✓ Project 'json-test' setup complete (85 files, 248.5 MB)

You can now run tests on this project:
  /test-mcp test=basic-indexing project=json-test
```

**Requirements:**
- `git` must be in PATH
- `cmake` must be in PATH (for CMake projects)

**Exit Codes:**
- 0: Success
- 1: Setup failed (clone error, cmake error, etc.)

---

### validate-project

Validate a project's configuration.

**Syntax:**
```bash
/test-mcp validate-project project=<name>
```

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `project` | Yes | Project name to validate |

**Validation Checks:**
- Project exists in registry
- Project directory exists
- `compile_commands.json` exists (at specified path)
- `compile_commands.json` is valid JSON
- C++ source files present (*.cpp, *.cc)

**Examples:**
```bash
/test-mcp validate-project project=tier1
/test-mcp validate-project project=json-test
```

**Output (Success):**
```
✓ Project 'tier1' validation: READY
```

**Output (Failure):**
```
✗ Project 'json-test' validation: FAILED
  - compile_commands.json not found: /path/to/build/compile_commands.json
  - No C++ source files found
```

**Exit Codes:**
- 0: Validation passed
- 1: Validation failed

---

### remove-project

Remove a project from registry.

**Syntax:**
```bash
/test-mcp remove-project project=<name> [delete=<yes|no>]
```

**Parameters:**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `project` | Yes | - | Project name to remove |
| `delete` | No | no | Delete project files ("yes" or "no") |

**Examples:**
```bash
# Remove from registry only (keep files)
/test-mcp remove-project project=json-test

# Remove and delete files (with confirmation)
/test-mcp remove-project project=json-test delete=yes
```

**Output (Registry only):**
```
✓ Project 'json-test' removed from registry
  Files preserved (use delete=yes to remove)
```

**Output (With file deletion):**
```
⚠️  WARNING: This will delete all project files!
   Path: /path/to/.test-projects/json-test
   Size: 248.5 MB

Are you sure? (yes/no): yes
Deleting project files: /path/to/.test-projects/json-test
✓ Project 'json-test' removed from registry
  Files deleted
```

**Restrictions:**
- Cannot remove builtin projects (tier1, tier2)
- File deletion requires confirmation

**Exit Codes:**
- 0: Success
- 1: Removal failed or cancelled

---

### pytest

Run the existing pytest suite.

**Syntax:**
```bash
/test-mcp pytest
```

**Parameters:** None

**What It Does:**
- Runs `pytest -v --tb=short` in repository root
- Captures output
- Formats results

**Examples:**
```bash
/test-mcp pytest
```

**Output (Success):**
```
⏳ Running pytest suite...

✅ Pytest suite passed

============================= test session starts ==============================
collected 42 items

tests/test_analyzer.py::test_basic_indexing PASSED                       [  2%]
tests/test_analyzer.py::test_class_search PASSED                         [  4%]
...
============================== 42 passed in 5.23s ===============================
```

**Output (Failure):**
```
⏳ Running pytest suite...

❌ Pytest suite failed (exit code: 1)

============================= test session starts ==============================
collected 42 items

tests/test_analyzer.py::test_basic_indexing PASSED                       [  2%]
tests/test_analyzer.py::test_class_search FAILED                         [  4%]
...
=========================== short test summary info ============================
FAILED tests/test_analyzer.py::test_class_search - AssertionError
============================== 1 failed, 41 passed in 5.45s =====================
```

**Requirements:**
- `pytest` must be installed (`pip install pytest`)

**Timeout:**
- 5 minutes (300 seconds)

**Exit Codes:**
- 0: All tests passed
- 1: Some tests failed or pytest not found

---

### help

Show help information.

**Syntax:**
```bash
/test-mcp help
```

**Parameters:** None

**Output:**
Displays:
- Available commands
- Command syntax examples
- Available test scenarios
- Available protocols
- Documentation links

**Exit Codes:**
- 0: Success

---

## Special Parameters

### Protocol Selection

All test commands support `protocol=` parameter:

| Protocol | Description | Use Case |
|----------|-------------|----------|
| `http` | HTTP REST-like | Recommended for testing |
| `sse` | Server-Sent Events | Alternative transport |
| `stdio` | Standard I/O | Production mode |

**Example:**
```bash
/test-mcp test=basic-indexing tier=1 protocol=sse
```

### Project Selection

Tests can use either `tier=` or `project=`:

```bash
# Use tier (shorthand)
/test-mcp test=basic-indexing tier=1

# Use specific project
/test-mcp test=basic-indexing project=json-test
```

---

## Environment Variables

None required. The skill operates independently of environment variables.

---

## File Locations

| Location | Description |
|----------|-------------|
| `.test-projects/` | Cloned test projects (gitignored) |
| `.test-projects/registry.json` | Project registry (gitignored) |
| `.test-results/` | Test execution logs (gitignored) |
| `.test-scenarios/` | Custom YAML scenarios (tracked in git) |
| `.claude/skills/test-mcp/` | Skill implementation |

---

## Return Values

### Test Results Location

All test results are saved to:
```
.test-results/<timestamp>_<scenario>_<project>_<protocol>/
├── test-config.json    # Test parameters
├── results.json        # Structured results
└── analysis.json       # Analysis with issues
```

### Accessing Results Programmatically

```bash
# Get latest result directory
LATEST=$(ls -t .test-results/ | head -1)

# Parse results
cat .test-results/$LATEST/results.json | jq '.metrics'
cat .test-results/$LATEST/analysis.json | jq '.status'
```

---

## Common Patterns

### Run Multiple Tests
```bash
/test-mcp test=basic-indexing tier=1
/test-mcp test=incremental-refresh tier=1
/test-mcp test=all-protocols tier=1
```

### Setup and Test New Project
```bash
/test-mcp setup-project url=https://github.com/user/repo name=myproj
/test-mcp validate-project project=myproj
/test-mcp test=basic-indexing project=myproj
```

### Custom Test Workflow
```bash
# 1. Create custom scenario
echo "..." > .test-scenarios/my-test.yaml

# 2. Run custom test
/test-mcp test=custom scenario=my-test.yaml tier=1

# 3. Check results
cat .test-results/$(ls -t .test-results/ | head -1)/results.json | jq
```

---

## See Also

- [User Guide](TEST_MCP_USER_GUIDE.md) - Comprehensive usage guide
- [YAML Scenario Spec](.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md) - Custom scenario format
- [FAQ](TEST_MCP_FAQ.md) - Common questions and troubleshooting
