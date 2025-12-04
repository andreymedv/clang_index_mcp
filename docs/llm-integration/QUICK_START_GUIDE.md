# Quick Start Guide: Implementing LLM Integration Enhancements

This guide provides a quick checklist to get started implementing the LLM integration strategy.

## Prerequisites

- [x] Read `LLM_INTEGRATION_STRATEGY.md` for overview
- [x] Read `IMPLEMENTATION_DETAILS.md` for technical specifics
- [x] Understand current architecture (see `CLAUDE.md`)

## Phase 1: Line Ranges (Estimated: 1-2 days)

### Step 1: Update Data Structures (30 minutes)

1. Edit `mcp_server/symbol_info.py`:
   - Add fields: `start_line`, `end_line`, `header_file`, `header_line`, `header_start_line`, `header_end_line`
   - Make all new fields `Optional`

2. Edit `mcp_server/schema.sql`:
   - Increment `PRAGMA user_version` to `5`
   - Add new columns (see IMPLEMENTATION_DETAILS.md)

3. Edit `mcp_server/sqlite_cache_backend.py`:
   - Update `CURRENT_SCHEMA_VERSION = 5`

### Step 2: Extract Line Ranges (2-3 hours)

1. Edit `mcp_server/cpp_analyzer.py` → `_process_cursor()`:
   - Extract `cursor.extent.start.line` and `cursor.extent.end.line`
   - Handle declaration vs definition (check `cursor.get_definition()`)
   - Track header file location for declarations
   - See code example in IMPLEMENTATION_DETAILS.md

### Step 3: Update Tool Outputs (1 hour)

1. Edit `mcp_server/cpp_mcp_server.py`:
   - Update `get_class_info` to include line ranges
   - Update `get_function_info` to include line ranges
   - Update `search_classes` to include line ranges
   - Update `search_functions` to include line ranges

### Step 4: Test Line Ranges (1 hour)

```bash
# Clear cache to force re-indexing
make clean-cache

# Run tests
make test

# Manual test with example project
python scripts/test_mcp_console.py examples/compile_commands_example/

# In console:
set_project_directory examples/compile_commands_example/
search_classes *
# Verify output includes start_line, end_line, header_file
```

### Step 5: Add get_files_containing_symbol Tool (2-3 hours)

1. Edit `mcp_server/cpp_mcp_server.py`:
   - Add tool definition to `list_tools()`
   - Add handler to `call_tool()`
   - See IMPLEMENTATION_DETAILS.md for schema

2. Edit `mcp_server/cpp_analyzer.py`:
   - Add `get_files_containing_symbol()` method
   - Query symbol index + call graph
   - Return unique file list

### Step 6: Integration Test (1-2 hours)

Test with real-world workflow:

1. Configure Claude Desktop with MCP server
2. Test Scenario 1 from TEST_SCENARIOS.md
3. Verify line ranges work with filesystem server
4. Test Scenario 2 with file lists
5. Measure improvements

### Checkpoint: Phase 1 Complete ✅

- [ ] Line ranges extracted for all symbols
- [ ] Header file locations tracked
- [ ] get_files_containing_symbol works
- [ ] All existing tests pass
- [ ] Integration test successful

## Phase 2: Documentation (Estimated: 1 day)

### Step 1: Update Data Structures (15 minutes)

1. Edit `mcp_server/symbol_info.py`:
   - Add fields: `brief`, `doc_comment`

2. Edit `mcp_server/schema.sql`:
   - Increment version to `6`
   - Add columns: `brief TEXT`, `doc_comment TEXT`

3. Update `CURRENT_SCHEMA_VERSION = 6`

### Step 2: Extract Documentation (2-3 hours)

1. Edit `mcp_server/cpp_analyzer.py` → `_process_cursor()`:
   - Extract `cursor.brief_comment`
   - Extract `cursor.raw_comment`
   - Handle missing documentation gracefully
   - See code example in IMPLEMENTATION_DETAILS.md

### Step 3: Update Tool Outputs (30 minutes)

Add `brief` and `doc_comment` to all tool outputs.

### Step 4: Test Documentation (1 hour)

```bash
make clean-cache
make test

# Test with documented code (if available)
python scripts/test_mcp_console.py /path/to/documented/project/
```

### Checkpoint: Phase 2 Complete ✅

- [ ] Documentation extracted correctly
- [ ] Brief included in search results
- [ ] Full doc_comment available on request
- [ ] Missing docs handled gracefully

## Phase 3: Includes (Estimated: 1-2 days)

### Step 1: Design Decision (30 minutes)

Choose storage strategy:
- **Option A:** Store during indexing (recommended)
- **Option B:** Compute on-demand

If Option A, proceed:

### Step 2: Update Schema (30 minutes)

1. Edit `mcp_server/schema.sql`:
   - Increment version to `7`
   - Add `file_includes` table (see IMPLEMENTATION_DETAILS.md)

### Step 3: Extract Includes (2-3 hours)

1. Edit `mcp_server/cpp_analyzer.py`:
   - During file processing, call `translation_unit.get_includes()`
   - Store in database or cache structure
   - Track direct vs system includes

### Step 4: Add Tool (1-2 hours)

1. Edit `mcp_server/cpp_mcp_server.py`:
   - Add `get_file_includes` tool
   - Implement handler

### Checkpoint: Phase 3 Complete ✅

- [ ] Includes tracked for all files
- [ ] get_file_includes returns correct data
- [ ] System includes separated

## Testing After Each Phase

### Automated Tests

```bash
# Run all tests
make test

# Run with coverage
make test-coverage

# Check specific integration tests
pytest tests/test_analyzer_integration.py -v
```

### Manual Testing with MCP Console

```bash
# Start interactive console
python scripts/test_mcp_console.py /path/to/test/project/

# Test commands:
set_project_directory /path/to/test/project/
wait_for_indexing
get_class_info MyClass
get_files_containing_symbol MyClass
get_file_includes src/myfile.cpp
```

### Integration Testing with Claude Desktop

1. Configure MCP server in Claude Desktop
2. Test scenarios from TEST_SCENARIOS.md
3. Measure improvements
4. Document findings

## Performance Monitoring

After each phase, check:

```bash
# Profile indexing
python scripts/profile_analysis.py /path/to/project/

# Check cache size
du -sh .mcp_cache/

# View cache stats
python scripts/cache_stats.py
```

**Acceptable thresholds:**
- Indexing time increase: <50%
- Cache size increase: <100%
- Query time increase: <20%

## Troubleshooting

### Database Schema Issues

If you see "no such column" errors:

```bash
# Clear cache to trigger recreation
make clean-cache

# Or manually
rm -rf .mcp_cache/
```

### Performance Issues

If indexing is too slow:

```bash
# Check if parallelism is working
python scripts/diagnose_gil.py /path/to/project/

# Profile to find bottlenecks
python scripts/profile_analysis.py /path/to/project/
```

### Missing Data

If line ranges or documentation not appearing:

1. Check if libclang is providing the data:
   ```python
   cursor.extent.start.line  # Should be non-zero
   cursor.brief_comment      # May be None if no docs
   ```

2. Check database:
   ```bash
   sqlite3 .mcp_cache/*/symbols.db
   SELECT start_line, end_line, brief FROM symbols LIMIT 10;
   ```

## Git Workflow

Remember: NEVER commit directly to main!

```bash
# Create feature branch
git checkout main
git pull origin main
git checkout -b feature/line-ranges

# Make changes and commit
git add .
git commit -m "Feature: Add line ranges to symbol extraction"

# Push and create PR
git push -u origin feature/line-ranges
gh pr create --title "Feature: Add line ranges to symbol extraction" \
             --body "Implements Phase 1 of LLM integration strategy..."

# After PR merged, clean up
git checkout main
git pull origin main
git branch -d feature/line-ranges
```

## Documentation Updates

After implementing each phase, update:

- [ ] `CLAUDE.md` - Add new tools to tool list
- [ ] `README.md` - Update features if needed
- [ ] Tool docstrings in `cpp_mcp_server.py`
- [ ] This guide if process changed

## Useful Commands Reference

```bash
# Development
make install-editable          # Install in dev mode
make test                      # Run tests
make test-coverage             # Run with coverage
make lint                      # Check code style
make format                    # Format code

# Testing
python scripts/test_mcp_console.py <project_path>
python scripts/test_installation.py
python scripts/diagnose_parse_errors.py <project> <file>

# Cleanup
make clean-cache               # Clear cache only
make clean                     # Clear cache and build artifacts
make clean-all                 # Clear everything including venv

# Performance
python scripts/profile_analysis.py <project_path>
python scripts/diagnose_gil.py <project_path>
python scripts/cache_stats.py

# Cache management
python scripts/diagnose_cache.py
python scripts/fix_corrupted_cache.py
```

## Next Steps After Implementation

1. **Document findings:** Create summary of what worked well and what didn't
2. **Measure improvements:** Concrete before/after metrics
3. **Gather feedback:** Test with real users if possible
4. **Plan next phase:** Based on findings, decide what to implement next

## Resources

- **Main strategy:** `docs/LLM_INTEGRATION_STRATEGY.md`
- **Implementation details:** `docs/llm-integration/IMPLEMENTATION_DETAILS.md`
- **Test scenarios:** `docs/llm-integration/TEST_SCENARIOS.md`
- **Project docs:** `CLAUDE.md`
- **libclang API:** https://libclang.readthedocs.io/

## Questions or Issues?

If you encounter issues during implementation:

1. Check this guide's Troubleshooting section
2. Review IMPLEMENTATION_DETAILS.md for technical specifics
3. Check existing similar code in cpp_analyzer.py
4. Test with small example first before large project
5. Use diagnostic scripts to understand what's happening

## Success Checklist

Phase 1 (Line Ranges):
- [ ] SymbolInfo has new fields
- [ ] Schema updated and versioned
- [ ] Line ranges extracted correctly
- [ ] get_files_containing_symbol implemented
- [ ] All tests pass
- [ ] Integration test successful
- [ ] Performance acceptable
- [ ] Documentation updated

Phase 2 (Documentation):
- [ ] Brief and doc_comment extracted
- [ ] Schema updated
- [ ] Tool outputs include docs
- [ ] Tests pass
- [ ] Documentation updated

Phase 3 (Includes):
- [ ] Includes tracked
- [ ] get_file_includes implemented
- [ ] Tests pass
- [ ] Documentation updated

**Ready to start? Begin with Phase 1, Step 1!**
