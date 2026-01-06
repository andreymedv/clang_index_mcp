# MCP Testing Skill - User Guide

## Introduction

The `/test-mcp` skill is a comprehensive testing framework for the C++ MCP Server. It allows you to:
- Run automated tests on C++ projects
- Clone and configure test projects from GitHub
- Create custom test scenarios using YAML
- Validate MCP server functionality
- Run the existing pytest suite

## Quick Start

### 1. List Available Projects

```bash
/test-mcp list-projects
```

This shows all registered test projects (tier1, tier2, and any custom projects).

### 2. Run a Basic Test

```bash
# Quick smoke test on tier1 (~5-10 seconds)
/test-mcp test=basic-indexing tier=1
```

This tests basic indexing and search functionality on a small project.

### 3. View Help

```bash
/test-mcp help
```

Shows all available commands and scenarios.

## Installation & Setup

The skill is already installed in `.claude/skills/test-mcp/`. No additional setup required unless you want to:

1. **Add custom projects** - Use `setup-project` command
2. **Create custom scenarios** - Add YAML files to `.test-scenarios/`

## Core Commands

### list-projects
List all registered test projects.

```bash
/test-mcp list-projects
```

**Output:**
- Project name
- Project path
- File count
- Whether compile_commands.json exists

### test
Run a test scenario.

```bash
# Built-in scenarios
/test-mcp test=<scenario> tier=<1|2> [protocol=http]

# Custom YAML scenarios
/test-mcp test=custom scenario=<file.yaml> tier=<1|2>
```

**Parameters:**
- `test` - Scenario name (required)
- `tier` - Use tier1 (small) or tier2 (large) project
- `project` - Use specific project by name (optional, overrides tier)
- `protocol` - http, sse, or stdio (default: http)
- `scenario` - Path to YAML file (for custom scenarios)

**Examples:**
```bash
# Quick smoke test
/test-mcp test=basic-indexing tier=1

# Test incremental analysis
/test-mcp test=incremental-refresh tier=1

# Test protocol compatibility
/test-mcp test=all-protocols tier=1

# Run custom scenario
/test-mcp test=custom scenario=quick-check.yaml tier=1
```

### setup-project
Clone and configure a C++ project from GitHub.

```bash
/test-mcp setup-project url=<github-url> [name=<name>] [tag=<tag>]
```

**Parameters:**
- `url` - GitHub repository URL (required)
- `name` - Project name (optional, defaults to repo name)
- `tag` - Git tag to checkout (optional)
- `commit` - Git commit hash to checkout (optional)

**Example:**
```bash
/test-mcp setup-project url=https://github.com/nlohmann/json name=json-test tag=v3.11.3
```

**What it does:**
1. Clones the repository to `.test-projects/<name>/`
2. Checks out specified tag/commit
3. Detects CMakeLists.txt and runs cmake if present
4. Generates compile_commands.json automatically
5. Adds project to registry

### validate-project
Validate a project's configuration.

```bash
/test-mcp validate-project project=<name>
```

**Checks:**
- Project directory exists
- compile_commands.json exists and is valid JSON
- C++ source files present

**Example:**
```bash
/test-mcp validate-project project=tier1
```

### remove-project
Remove a project from registry.

```bash
/test-mcp remove-project project=<name> [delete=yes]
```

**Parameters:**
- `project` - Project name (required)
- `delete` - Set to "yes" to delete files (optional, requires confirmation)

**Example:**
```bash
# Remove from registry only
/test-mcp remove-project project=json-test

# Remove and delete files
/test-mcp remove-project project=json-test delete=yes
```

**Note:** Builtin projects (tier1, tier2) cannot be removed.

### pytest
Run the existing pytest suite.

```bash
/test-mcp pytest
```

Executes all pytest tests in the repository with formatted output.

## Built-in Test Scenarios

### basic-indexing
**Purpose:** Quick smoke test of core functionality
**Project:** tier1 (~18 files)
**Duration:** ~5-10 seconds
**Tests:**
- Project indexing
- Class search
- Function search

**Usage:**
```bash
/test-mcp test=basic-indexing tier=1
```

### issue-13
**Purpose:** Reproduce Issue #13 (boost headers parsing)
**Project:** tier2 (~5700 files)
**Duration:** ~5-15 minutes
**Tests:**
- Large project indexing
- Boost library symbol detection
- Header processing with multiple compilation units

**Usage:**
```bash
/test-mcp test=issue-13 tier=2
```

**Note:** This test is slow. Use tier2 only when testing large project scenarios.

### incremental-refresh
**Purpose:** Test incremental analysis after file changes
**Project:** tier1
**Duration:** ~10-20 seconds
**Tests:**
- Initial indexing
- File modification
- Incremental refresh
- New symbol detection
- Speedup measurement

**Usage:**
```bash
/test-mcp test=incremental-refresh tier=1
```

### all-protocols
**Purpose:** Verify transport protocol compatibility
**Project:** tier1
**Duration:** ~15-30 seconds
**Tests:**
- HTTP protocol functionality
- SSE protocol functionality
- Result consistency across protocols

**Usage:**
```bash
/test-mcp test=all-protocols tier=1
```

## Custom YAML Scenarios

### Creating a Custom Scenario

1. Create a YAML file in `.test-scenarios/` directory
2. Define test steps using MCP tools
3. Add expectations to validate results

**Example:**
```yaml
name: my-test
description: My custom test scenario
project: tier1
protocol: http

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"
    description: "Set project directory"

  - tool: wait_for_indexing
    timeout: 30
    description: "Wait for indexing"

  - tool: search_classes
    args:
      pattern: "Example"
    expect:
      - type: count
        operator: ">="
        value: 1
    description: "Search for Example classes"
```

### Running a Custom Scenario

```bash
# Scenario in .test-scenarios/
/test-mcp test=custom scenario=my-test.yaml tier=1

# Scenario with full path
/test-mcp test=custom scenario=/path/to/scenario.yaml tier=1
```

### YAML Format Reference

See [YAML_SCENARIO_SPEC.md](../../.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md) for complete format specification.

**Key features:**
- Special variables: `$PROJECT_PATH`, `$PROJECT_NAME`, `$BUILD_DIR`
- Expectation types: count, content_includes, content_matches, has_field, no_error
- Step-specific timeouts
- All MCP tools supported

## Workflows

### Testing After Code Changes

```bash
# 1. Quick validation
/test-mcp test=basic-indexing tier=1

# 2. Test incremental analysis
/test-mcp test=incremental-refresh tier=1

# 3. Run full test suite
/test-mcp pytest
```

### Adding a New Test Project

```bash
# 1. Clone and configure
/test-mcp setup-project url=https://github.com/user/repo name=myproject

# 2. Validate setup
/test-mcp validate-project project=myproject

# 3. Run basic test
/test-mcp test=basic-indexing project=myproject

# 4. Create custom scenario for project-specific tests
# (Edit .test-scenarios/myproject-test.yaml)

# 5. Run custom scenario
/test-mcp test=custom scenario=myproject-test.yaml project=myproject
```

### Testing a Specific Feature

Create a custom YAML scenario targeting the feature:

```yaml
name: feature-test
description: Test specific feature
project: tier1
protocol: http

steps:
  - tool: set_project_directory
    args:
      project_path: "$PROJECT_PATH"

  - tool: wait_for_indexing
    timeout: 30

  # Add feature-specific test steps
  - tool: find_callers
    args:
      function_name: "myFunction"
    expect:
      - type: count
        operator: ">="
        value: 1
```

## Understanding Test Results

### Success Output
```
✅ Test: basic-indexing (tier1, HTTP, 3.2s)
   Files indexed: 18/18
   Classes found: 5 (expected: 5)
   Functions found: 12 (expected: 12)
   Issues: None
   Logs: .test-results/20251228_100000_basic-indexing_tier1_http/
```

### Failure Output
```
❌ Test: basic-indexing (tier1, HTTP, 4.1s)
   Files indexed: 16/18 (2 failed)
   Issues:
     - File count mismatch (expected 18, got 16)
   Logs: .test-results/20251228_100000_basic-indexing_tier1_http/
```

### Detailed Logs

All test results are saved in `.test-results/<timestamp>_<scenario>_<project>_<protocol>/`:
- `test-config.json` - Test parameters
- `results.json` - Structured results
- `analysis.json` - Analysis with status and issues

## Best Practices

1. **Start small** - Use tier1 for rapid iteration
2. **Use tier2 sparingly** - Only when testing large project scenarios
3. **Custom scenarios** - Create reusable scenarios for common test patterns
4. **Validate first** - Run `validate-project` before running tests
5. **Clean up** - Remove unused test projects to save disk space
6. **Version control** - Keep custom scenarios in `.test-scenarios/` (tracked in git)

## Tips & Tricks

### Fast Iteration
```bash
# Use tier1 for quick feedback
/test-mcp test=basic-indexing tier=1

# Custom scenarios are faster than Python tests
/test-mcp test=custom scenario=quick-check.yaml tier=1
```

### Debugging Failures
```bash
# 1. Check detailed logs
cat .test-results/<latest>/results.json | jq

# 2. Validate project setup
/test-mcp validate-project project=tier1

# 3. Run with specific protocol
/test-mcp test=basic-indexing tier=1 protocol=http
```

### Organizing Scenarios
```
.test-scenarios/
├── quick/
│   ├── smoke-test.yaml
│   └── basic-search.yaml
├── features/
│   ├── inheritance.yaml
│   └── namespaces.yaml
└── integration/
    └── full-workflow.yaml
```

## Next Steps

- Read [Command Reference](TEST_MCP_COMMAND_REFERENCE.md) for detailed command documentation
- Read [YAML Scenario Spec](../../.claude/skills/test-mcp/YAML_SCENARIO_SPEC.md) for custom scenario format
- Check [FAQ and Troubleshooting](TEST_MCP_FAQ.md) for common issues
- See example scenarios in `.test-scenarios/` directory
