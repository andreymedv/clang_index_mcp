# MCP Testing Skill

Automated testing framework for C++ MCP Server.

## Quick Start

```bash
# List available test projects
/test-mcp list-projects

# Run quick smoke test
/test-mcp test=basic-indexing tier=1

# Reproduce an issue
/test-mcp test=issue-13 tier=2
```

## Documentation

See full specification: `/home/andrey/repos/cplusplus_mcp/docs/MCP_TESTING_SKILL.md`

## Implementation Status

- ✅ Phase 1: MVP - Basic Skill with tier1/tier2 (COMPLETE)
- ✅ Phase 2: Project Management (COMPLETE)
- [ ] Phase 3: Extended Test Scenarios
- [ ] Phase 4: Advanced Features
- [ ] Phase 5: Polish & Documentation

## Structure

```
.claude/skills/test-mcp/
├── README.md                    # This file
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

## Current Status

**Status:** Phase 1 & 2 COMPLETE ✅

**Working Features:**
- ✅ Server lifecycle management (HTTP transport)
- ✅ MCP protocol initialization handshake
- ✅ `list-projects` command
- ✅ `setup-project` command - Clone and configure from GitHub
- ✅ `validate-project` command
- ✅ `remove-project` command
- ✅ CMake auto-detection and configuration
- ✅ `test=basic-indexing` scenario (tier1, ~5-10s)
- ✅ `test=issue-13` scenario (tier2, ~5-15min)
- ✅ Automated result analysis and formatting
- ✅ Detailed test logs in `.test-results/`

**Usage:**
```bash
# List available projects
python .claude/skills/test-mcp/__init__.py list-projects

# Setup a new project from GitHub
python .claude/skills/test-mcp/__init__.py setup-project url=https://github.com/user/repo name=myproject

# Run tests
python .claude/skills/test-mcp/__init__.py test test=basic-indexing tier=1 protocol=http

# Or via Claude Code (when skill is registered)
/test-mcp test=basic-indexing tier=1
/test-mcp setup-project url=https://github.com/user/repo
```
