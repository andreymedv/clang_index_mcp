# LLM Integration Strategy - Status Overview

This directory contains comprehensive documentation for the LLM integration strategy, which adds "bridging data" to improve LLM's ability to understand and work with C++ codebases through the MCP server.

## Overview

The LLM integration strategy is divided into phases, each adding specific capabilities to bridge between the C++ analyzer and filesystem/search MCP tools used by LLMs like Claude.

## Phase Status

### ✅ Phase 1: Line Ranges (COMPLETE)

**Status:** Merged to main (2025-12-08)
**PR:** #45, #47

**What it adds:**
- Complete source location information (start_line, end_line) for all symbols
- Header/source tracking (declaration vs definition locations)
- New MCP tool: `get_files_containing_symbol`
- Definition-wins strategy for multiple declarations

**Documentation:**
- [PHASE1_REQUIREMENTS.md](PHASE1_REQUIREMENTS.md) - Comprehensive requirements
- [PHASE1_TEST_PLAN.md](PHASE1_TEST_PLAN.md) - Test specifications

**Key benefits:**
- LLMs can precisely locate symbol definitions in source files
- Enables efficient file reading with line ranges
- Bridges C++ semantic understanding with filesystem tools

### ✅ Phase 2: Documentation Extraction (COMPLETE)

**Status:** Merged to main (2025-12-08)
**PR:** #46, #47
**Verification:** [PHASE2_CONSISTENCY_VERIFICATION.md](PHASE2_CONSISTENCY_VERIFICATION.md)

**What it adds:**
- Extract brief descriptions (first line of documentation)
- Extract full documentation comments (Doxygen, JavaDoc, Qt-style)
- Add `brief` and `doc_comment` fields to all MCP tool responses
- Support for UTF-8 and special characters

**Documentation:**
- [PHASE2_REQUIREMENTS.md](PHASE2_REQUIREMENTS.md) - Comprehensive requirements
- [PHASE2_TEST_PLAN.md](PHASE2_TEST_PLAN.md) - Test specifications
- [PHASE2_CONSISTENCY_VERIFICATION.md](PHASE2_CONSISTENCY_VERIFICATION.md) - Verification report

**Test results:**
- 54/54 tests passing (100% pass rate)
- Schema version: 7.0
- Test execution time: 3.89s

**Key benefits:**
- LLMs can understand symbol purpose without reading source files
- Reduces filesystem access by ~70-80%
- Improves search relevance with documentation context
- Enables semantic code understanding from MCP tool responses alone

## Implementation Details

### Database Schema

**Current version:** 8.0

**Phase 1 additions (v5.0-v6.0):**
- `start_line INTEGER` - First line of symbol definition
- `end_line INTEGER` - Last line of symbol definition
- `header_file TEXT` - Path to header file (if declaration separate)
- `header_line INTEGER` - Declaration line in header
- `header_start_line INTEGER` - Declaration start line
- `header_end_line INTEGER` - Declaration end line

**Phase 2 additions (v7.0):**
- `brief TEXT` - Brief description (max 200 chars)
- `doc_comment TEXT` - Full documentation (max 4000 chars)

**Phase 3 additions (v8.0):**
- New table: `call_sites` - Line-level call graph tracking
  - `caller_usr TEXT` - Function making the call
  - `callee_usr TEXT` - Function being called
  - `file TEXT` - Source file containing call
  - `line INTEGER` - Line number of call
  - `column INTEGER` - Column number (optional)
  - Indexes on caller_usr, callee_usr, file, and (file, line)

### MCP Tools Enhanced

All search and info tools now return additional fields:

**From Phase 1:**
```json
{
  "start_line": 45,
  "end_line": 120,
  "header_file": "/path/to/header.h",
  "header_line": 12,
  "header_start_line": 12,
  "header_end_line": 25
}
```

**From Phase 2:**
```json
{
  "brief": "Brief description of the symbol",
  "doc_comment": "Full documentation comment with all details..."
}
```

**From Phase 3:**
```json
{
  "function": "validate",
  "callers": [...],
  "call_sites": [
    {
      "file": "/path/to/file.cpp",
      "line": 45,
      "column": 5,
      "caller": "processData",
      "caller_signature": "void ()",
      "caller_file": "/path/to/file.cpp"
    }
  ],
  "total_call_sites": 2
}
```

**Affected tools:**
- `search_classes` - Returns brief for each result
- `search_functions` - Returns brief for each result
- `get_class_info` - Returns brief, doc_comment, and line ranges
- `get_function_info` - Returns brief, doc_comment, and line ranges
- `get_files_containing_symbol` - NEW in Phase 1
- `find_callers` - ENHANCED in Phase 3 (now returns dict with call_sites)
- `get_call_sites` - NEW in Phase 3 (forward analysis)

## Testing

### Test Coverage

**Phase 1:**
- Line range extraction tests
- Header/source split handling tests
- Definition-wins strategy tests
- Multiple declarations tests
- Edge case tests (templates, macros, forward declarations)

**Phase 2:**
- Documentation extraction tests (54 tests total)
- Comment style tests (Doxygen, JavaDoc, Qt)
- UTF-8 encoding tests
- Special character handling tests
- MCP tool integration tests
- Schema migration tests

### Running Tests

```bash
# Run all Phase 1 & 2 tests
make test

# Run specific Phase 2 documentation tests
pytest tests/test_documentation_*.py -v

# Run with coverage
make test-coverage
```

### ✅ Phase 3: Line-Level Call Graph (COMPLETE)

**Status:** PR #50 submitted (2025-12-10)
**PR:** #50

**What it adds:**
- Line-level call site tracking (exact file:line:column for each function call)
- Enhanced `find_callers` tool with call_sites array
- New `get_call_sites` tool for forward analysis (what does this function call?)
- Set-based deduplication to prevent duplicate call sites
- Bidirectional call graph queries with precise locations

**Documentation:**
- [PHASE3_REQUIREMENTS.md](PHASE3_REQUIREMENTS.md) - Comprehensive requirements (reduced scope)
- [PHASE3_TEST_PLAN.md](PHASE3_TEST_PLAN.md) - Test specifications

**Test results:**
- 40/40 Phase 3 tests passing (100% pass rate)
- 544/544 full test suite passing
- Schema version: 8.0
- Performance impact: <5% (well under 10% target)

**Key benefits:**
- Precise navigation to exact call locations
- Impact analysis for function changes
- Bidirectional call graph (who calls X + what does X call)
- LLMs can trace execution flow with line-level precision

**Originally planned but removed from scope:**
- Cross-reference extraction (@see, @ref tags) - **removed from roadmap**
- Parameter documentation (@param tags) - **removed from roadmap**
- Rationale: These features assume comprehensive Doxygen documentation, which is uncommon in real-world codebases. Phase 3.1 delivers the core value for call graph analysis.

## Future Phases (Potential)

### Relationship Mapping (Potential)
These features would extract relationships from C++ code structure (not documentation):
- Enhanced inheritance graph (bidirectional relationships, virtual method overrides)
- Template specialization relationships
- Include dependency visualization

### Semantic Search (Potential)
- FTS5 documentation search
- Semantic code understanding
- Natural language queries

**Note:** Parameter documentation (@param tags) and cross-reference extraction (@see, @ref tags) have been **removed from the roadmap**. These features assume comprehensive Doxygen-style documentation, which is uncommon in real-world codebases. The current phases (1-3) already provide substantial value without requiring additional documentation standards.

## Performance Impact

### Phase 1 Impact
- Indexing time increase: <5% (line extents already available from libclang)
- Storage increase: ~24 bytes per symbol (~2.4 MB for 100K symbols)
- Query performance: No measurable impact

### Phase 2 Impact
- Indexing time increase: <5% (comments already parsed by libclang)
- Storage increase: ~60 MB for 100K symbols (worst case, actual lower due to NULLs)
- Query performance: No measurable impact

### Phase 3 Impact
- Indexing time increase: <5% (call sites extracted during AST traversal)
- Storage increase: ~8 bytes per call site (~2.4 MB for 100K symbols with 3 calls avg)
- Query performance: Call site queries <50ms

### Combined (Phase 1 + 2 + 3)
- Total indexing slowdown: <15% over baseline
- Total storage increase: ~65 MB for 100K symbols (worst case)
- Minimal impact on query performance
- Significant reduction in LLM filesystem access
- Precise call site navigation eliminates guesswork

## Migration Notes

### Schema Versioning

The server automatically recreates the cache when schema version changes:
- v4.0 → v5.0 (Phase 1 initial)
- v5.0 → v6.0 (Phase 1 header tracking)
- v6.0 → v7.0 (Phase 2 documentation)
- v7.0 → v8.0 (Phase 3 call sites)

No manual migration needed - old caches are automatically invalidated and recreated.

### Backward Compatibility

All new fields are optional (NULL allowed):
- Existing code continues to work
- New fields can be safely ignored if not needed
- JSON responses include new fields but don't break existing parsers

## References

### Project Documentation
- [CLAUDE.md](/CLAUDE.md) - Main project documentation with Phase 1 & 2 details
- [REQUIREMENTS.md](/docs/REQUIREMENTS.md) - Original requirements
- [INCREMENTAL_ANALYSIS_DESIGN.md](/docs/INCREMENTAL_ANALYSIS_DESIGN.md) - Incremental analysis architecture

### Implementation Files
- `mcp_server/cpp_analyzer.py` - Core analyzer with Phase 1 & 2 implementation
- `mcp_server/symbol_info.py` - Data model with all fields
- `mcp_server/schema.sql` - SQLite schema v7.0
- `mcp_server/cpp_mcp_server.py` - MCP tools with enhanced responses

### Test Files
- Phase 1: `tests/test_multiple_declarations.py`
- Phase 2: `tests/test_documentation_*.py` (5 test files, 54 tests)

## Contributing

When adding new phases:

1. Create `PHASE{N}_REQUIREMENTS.md` with comprehensive requirements
2. Create `PHASE{N}_TEST_PLAN.md` with detailed test specifications
3. Implement with proper schema versioning
4. Add comprehensive tests
5. Create verification report (`PHASE{N}_CONSISTENCY_VERIFICATION.md`)
6. Update this README with completion status
7. Update main CLAUDE.md with new features

## Questions?

For questions or issues related to LLM integration:
1. Check the phase-specific requirements documents
2. Review the verification reports for completed phases
3. See [CLAUDE.md](/CLAUDE.md) for implementation details
4. Open an issue at https://github.com/andreymedv/clang_index_mcp/issues

---

**Last updated:** 2025-12-10
**Current schema version:** 8.0
**Completed phases:**
- Phase 1 (Line Ranges) ✅
- Phase 2 (Documentation Extraction) ✅
- Phase 3 (Line-Level Call Graph) ✅
