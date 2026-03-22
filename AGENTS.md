# AGENTS.md

Purpose: working notes for Codex and similar coding agents in this repository. This file replaces older Jules-specific review instructions.

## Project Summary

This repository contains an MCP server for semantic C++ analysis built on libclang. The server indexes C++ projects and exposes tools for symbol search, class hierarchy inspection, call graph queries, type alias tracking, and related code-understanding tasks.

The codebase is under active development. Prioritize correctness, regression safety, and preserving performance characteristics of the analyzer.

## First Steps

When starting work:

1. Read `CLAUDE.md` for detailed architecture and workflow notes.
2. Read `./.claude/CLAUDE.md` for host-local and private project instructions. This file is gitignored and may be hidden from normal file listings unless hidden files are included.
3. Inspect the relevant code before proposing or making changes.
4. Check `git status` before editing. The worktree may already contain user changes.
5. Prefer small, targeted edits that fit the existing style.

## Key Commands

Setup and local development:

```bash
./server_setup.sh
source mcp_env/bin/activate
make install-dev
python scripts/test_installation.py
```

Primary validation commands:

```bash
make test
make check
make lint
make format
make type-check
```

Useful focused runs:

```bash
pytest tests/test_analyzer_integration.py
pytest tests/test_compile_commands_manager.py::test_specific
make run
make dev
```

## Testing Constraints

- Never run multiple `pytest` processes at the same time in this repository. The SQLite cache can conflict across concurrent test runs.
- If code changes touch analyzer behavior, prefer running `make test`.
- If code changes affect formatting, linting, or typing expectations, run the relevant `make` target or `make check`.
- If you could not run the appropriate validation, say so explicitly in the final response.

## Architecture Hotspots

Most changes will touch one of these areas:

- `mcp_server/cpp_mcp_server.py`: MCP tool schemas and request handlers.
- `mcp_server/cpp_analyzer.py`: core indexing pipeline, AST traversal, symbol extraction, and worker logic.
- `mcp_server/call_graph.py`: SQLite-backed call graph storage and queries.
- `mcp_server/sqlite_cache_backend.py`: schema management, SQLite tuning, and persistence behavior.
- `mcp_server/incremental_analyzer.py`: change detection and incremental refresh behavior.
- `mcp_server/compile_commands_manager.py`: compile_commands.json loading and lookup.
- `mcp_server/header_tracker.py`: header deduplication logic.

Treat the following behaviors as critical unless the task explicitly requires changing them:

- Translation units must be cleaned up promptly to avoid file descriptor leaks.
- SQLite PRAGMAs must be applied on every connection.
- Call graph data should remain SQLite-backed rather than duplicated in memory.
- Incremental analysis and compile_commands invalidation must remain correct.
- Header deduplication and multi-process parsing are major performance features; do not casually regress them.

## Configuration and Runtime Notes

- Project config lives in `cpp-analyzer-config.json`.
- Cache data lives under `.mcp_cache/`.
- `compile_commands.json` integration is enabled by default when available.
- Useful environment variables:
  - `CPP_ANALYZER_USE_THREADS=true` to disable process workers during debugging.
  - `MCP_DEBUG=1` for verbose logging.
  - `PYTHONUNBUFFERED=1` for unbuffered output.
  - `LIBCLANG_PATH=/path/to/libclang.so` to override libclang discovery.

## Change Guidelines

- Preserve the current code style and naming patterns.
- Keep schema changes coordinated:
  - Update `mcp_server/schema.sql`.
  - Increment the schema version there.
  - Update `CURRENT_SCHEMA_VERSION` in `mcp_server/sqlite_cache_backend.py`.
- Add or update tests whenever behavior changes.
- Update documentation when user-visible behavior, architecture, or workflows change.
- Do not revert unrelated user changes in the worktree.

## Validation Expectations By Change Type

- New or changed MCP tool: validate the handler, analyzer integration, tests, and any user-facing docs.
- Symbol extraction change: verify analyzer behavior carefully and watch for schema/test fallout.
- Cache or schema change: verify recreation/invalidation behavior and test affected queries.
- Performance-sensitive change: avoid extra in-memory state, repeated parsing, or redundant SQLite work.
- Resource-management change: pay attention to file descriptors, process cleanup, and translation unit lifetime.

## Practical Reminders for Agents

- Prefer `rg` for search.
- Use the existing `make` targets instead of inventing new workflows.
- Prefer semantic MCP tools over raw text search when the server is already running and the task is code-understanding rather than implementation.
- For debugging parse issues, thread mode is often easier to reason about than process mode.
- If `compile_commands.json` changes, expect analyzer state or caches to need refresh.

## Definition of Done

A task is not complete until you have done the relevant combination of:

1. implemented the requested change,
2. updated tests and docs if needed,
3. run appropriate validation when feasible,
4. reported any remaining risks or unverified areas clearly.
