# Agent Workflows

Read this file when adding a new MCP tool, modifying symbol extraction, or recovering from cache issues.

## Adding a New MCP Tool

1. Define the public tool schema in `clang_index_mcp/_mcp/consolidated_tools.py` (`list_tools_b()`)
2. Add the consolidated handler in `clang_index_mcp/_mcp/consolidated_tools.py` (`handle_tool_call_b()`)
3. Add the internal handler in `clang_index_mcp/_mcp/tool_handlers/*.py` and register it via `ToolRegistry`
4. Implement analyzer logic in `clang_index_mcp/_search/query_engine.py`, `clang_index_mcp/_search/call_graph_service.py`, or `clang_index_mcp/_symbols/symbol_extractor.py` as appropriate
5. Add tests in `tests/test_*.py`
6. Update agent instructions if architecturally significant

## Modifying Symbol Extraction Logic

1. Edit `clang_index_mcp/_compilation/clang_symbol_parser.py` (`ClangSymbolParser._process_cursor()` recursive AST walker)
2. Update `clang_index_mcp/_symbols/model/symbol_info.py` if changing `SymbolInfo` structure
3. Update extractors in `clang_index_mcp/_symbols/` (`alias_extractor.py`, `documentation_extractor.py`, etc.) as needed
4. If changing SQLite schema:
   - Update `clang_index_mcp/_persistence/schema.sql` with new columns/tables
   - Increment the schema version in `schema.sql`
   - Update `CURRENT_SCHEMA_VERSION` in `clang_index_mcp/_persistence/sqlite_cache_backend.py`
   - Database will automatically recreate on version mismatch (development mode)
5. Run `make test` to verify no regressions
6. Test with example project: `python -m clang_index_mcp` + set `examples/compile_commands_example/`

## Cache Invalidation and Corruption Recovery

```bash
# Check for corrupted databases
python scripts/fix_corrupted_cache.py

# Check and fix specific project cache
python scripts/fix_corrupted_cache.py /path/to/project

# Manually clear all cache
rm -rf .mcp_cache/

# Manually clear specific project cache
rm -rf .mcp_cache/<project_hash>_
```

**Database Corruption:**
If you see "database disk image is malformed" errors, the SQLite cache is corrupted. This can happen if indexing was interrupted improperly (e.g., SIGKILL, power loss). Use the `fix_corrupted_cache.py` script to diagnose and repair.
