---
name: mcp-skill
description: Automated framework for testing of 'cpp_mcp_server' server over stdio/SSE/HTTP protocols with test projects
---

## Quick Start

```bash
# List available test projects
/test-mcp list-projects

# Run quick smoke test
/test-mcp test=basic-indexing tier=1

# Reproduce an issue
/test-mcp test=issue-13 tier=2

# Create new test project from github repository user/repo
/test-mcp setup-project url=https://github.com/user/repo

# Run custom scenario described by YAML file
/test-mcp test=custom scenario=.test-scenarios/my-test.yaml
```

## Documentation

[Full specification](docs/MCP_TESTING_SKILL.md)
[YAML scenario specification](YAML_SCENARIO_SPEC.md)

## Structure

```
.claude/skills/test-mcp/
├── SKILL.md                     # This file
├── YAML_SCENARIO_SPEC.md        # YAML-based test scenario specification
├── __init__.py                  # Skill entry point
├── project_manager.py           # Project registry and management
├── server_manager.py            # MCP server lifecycle
├── test_runner.py               # Test execution orchestration
├── result_analyzer.py           # Result validation and analysis
├── scenarios/                   # Test scenario definitions
│   ├── basic_indexing.py
│   ├── issue_13.py
│   └── ...
└── utils/                       # Shared utilities
    ├── registry.py              # Registry operations
    ├── validation.py            # Project validation
    └── cmake_helper.py          # CMake operations
```

## Direct framework usage

```bash
# List available projects
python .claude/skills/test-mcp/__init__.py list-projects

# Setup a new project from GitHub
python .claude/skills/test-mcp/__init__.py setup-project url=https://github.com/user/repo name=myproject

# Run tests
python .claude/skills/test-mcp/__init__.py test test=basic-indexing tier=1 protocol=http
```
