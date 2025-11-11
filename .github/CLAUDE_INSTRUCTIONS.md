# Claude AI Instructions for clang_index_mcp

This file contains important workflow instructions for Claude when working on this repository.

---

## Current Development Context

**Last Updated**: 2025-11-11
**Current Base Branch**: `compile_commands-support`
**Reason**: Active development of compile_commands.json integration features

> **Note to Claude**: If the user asks you to work from a different branch than what's documented here, ask if this file should be updated to reflect the new development focus. Don't automatically assume this file is always correct - it needs manual updates when development priorities change.

---

## Branch Workflow

### Start Work from the Current Base Branch

**⚠️ IMPORTANT: When starting ANY session involving code analysis, documentation, or development work:**

1. **CHECK USER'S REQUEST**: See which branch the user mentions in their initial request

2. **COMPARE WITH THIS FILE**: Check if it matches the "Current Base Branch" above

3. **IF MISMATCH**: Ask the user:
   - "I see `.github/CLAUDE_INSTRUCTIONS.md` says to use `[branch-from-file]`, but you mentioned `[branch-from-user]`. Should I update the instructions file to reflect the new development focus?"

4. **FIRST ACTION**: Checkout the appropriate base branch
   ```bash
   git checkout compile_commands-support  # Or whatever the current base is
   ```

5. **VERIFY**: Confirm you're on the correct branch before analyzing code
   ```bash
   git branch --show-current
   ```

6. **BASE YOUR WORK**: Create feature branches from the current base branch
   ```bash
   git checkout -b claude/feature-name-<session-id>
   ```

### Why This Matters

**Currently**, the `compile_commands-support` branch contains critical features not present in other branches:

- **CompileCommandsManager**: Integration with `compile_commands.json` for accurate parsing
- **Enhanced CppAnalyzer**: Support for project-specific compilation flags
- **Improved caching**: Two-level cache system optimized for compile commands
- **Additional MCP tools**: compile_commands-specific functionality

Working from the wrong branch will result in:
- ❌ Outdated code analysis
- ❌ Incorrect documentation
- ❌ Missing key features in recommendations
- ❌ Wasted time re-doing work

> **This section will change** when compile_commands-support is merged or when development shifts to a different branch.

## Feature Branch Naming Convention

When creating feature branches for Claude sessions:

**Pattern**: `claude/<descriptive-name>-<session-id>`

**Examples**:
- `claude/study-compile-commands-011CV1vZNzZzFevdJdjW5g3x`
- `claude/fix-cache-invalidation-012ABC3def4...`
- `claude/add-documentation-013XYZ5ghi6...`

**Requirements**:
- Must start with `claude/` prefix
- Must end with the session ID (for git push authorization)
- Descriptive middle part for clarity

## Repository Structure

Key directories and their purposes:

```
clang_index_mcp/
├── mcp_server/               # Core MCP server implementation
│   ├── cpp_analyzer.py       # Main analysis engine (CompileCommands integration here!)
│   ├── cache_manager.py      # Two-level caching system
│   ├── compile_commands_manager.py  # NEW: Compile commands support
│   ├── search_engine.py      # Query interface
│   └── ...
├── .mcp_cache/              # Cache storage (project-specific subdirs)
├── examples/                # Example projects
│   └── compile_commands_example/  # Demo with compile_commands.json
├── tests/                   # Test suite
└── docs/                    # Documentation (if exists)
```

## Common Tasks Checklist

### Starting a New Session

- [ ] Read this file first
- [ ] Checkout `compile_commands-support` branch
- [ ] Verify branch with `git branch --show-current`
- [ ] Review recent commits with `git log --oneline -5`

### Code Analysis

- [ ] Confirm on `compile_commands-support` branch
- [ ] Check for CompileCommandsManager integration when analyzing cpp_analyzer.py
- [ ] Look for compile_commands.json support in examples
- [ ] Consider cache implications (both global and per-file)

### Creating Documentation

- [ ] Base analysis on `compile_commands-support` code
- [ ] Include compile commands features in documentation
- [ ] Verify code snippets match actual implementation
- [ ] Include accurate line numbers from current branch

### Committing Work

- [ ] Create feature branch from `compile_commands-support`
- [ ] Use descriptive commit messages
- [ ] Push to `claude/<name>-<session-id>` branch
- [ ] Use `git push -u origin <branch-name>` (not to compile_commands-support directly)

## Key Features to Remember (compile_commands-support branch)

### 1. CompileCommandsManager
- Located: `mcp_server/compile_commands_manager.py`
- Purpose: Load and manage `compile_commands.json`
- Integration: Used in `CppAnalyzer.index_file()` at line ~307

### 2. Two-Level Caching
- Global cache: `cache_info.json`
- Per-file cache: `files/{hash}.json`
- Location: `.mcp_cache/{project_name}_{hash}/`

### 3. Project Isolation
- Each analyzed project gets unique cache directory
- Hash-based separation (MD5 of project path)
- No data sharing between projects

### 4. Compile Args Priority
1. compile_commands.json (if available)
2. Hardcoded fallback args
3. vcpkg includes (if found)

## Git Push Requirements

**CRITICAL**: Pushes to `claude/*` branches require matching session ID suffix.

```bash
# ✅ CORRECT (session ID matches branch suffix)
git push -u origin claude/study-compile-commands-011CV1vZNzZzFevdJdjW5g3x

# ❌ WRONG (will fail with 403)
git push -u origin compile_commands-support
git push -u origin main
```

**On network failures**: Retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s)

## Updating This File

**When development focus changes** (e.g., feature branch gets merged, working on a different feature, etc.):

1. Update the "Current Development Context" section at the top:
   - **Last Updated**: Current date
   - **Current Base Branch**: New base branch name
   - **Reason**: Why this branch is now the base

2. Update the "Why This Matters" section to reflect features in the new base branch

3. Commit the changes:
   ```bash
   git add .github/CLAUDE_INSTRUCTIONS.md
   git commit -m "Update Claude instructions: switch base branch to [new-branch]"
   ```

**Claude should offer to help** with this update when it detects a mismatch between user requests and documented instructions.

## Questions or Issues?

- Check existing documentation: `DEVELOPMENT.md`, `README.md`, `COMPILE_COMMANDS_INTEGRATION.md`
- Review test files: `tests/test_compile_commands_manager.py`, `tests/test_analyzer_integration.py`
- Examine examples: `examples/compile_commands_example/`

---

**Last Updated**: 2025-11-11
**Maintained By**: Repository owner
**Purpose**: Ensure consistent Claude AI workflow across sessions
