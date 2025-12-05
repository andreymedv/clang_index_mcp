# Phase 1: Line Ranges - Comprehensive Requirements

## Overview

Phase 1 adds critical "bridging data" to enable efficient integration with filesystem and search MCP servers. The two main features are:

1. **Line Ranges**: Complete source location information (start/end lines) for all symbols
2. **File Lists**: New tool to find all files that reference a symbol

## Functional Requirements

### FR-1: Line Range Extraction

**Requirement:** Extract and store complete line ranges for all indexed symbols.

**Acceptance Criteria:**
- FR-1.1: Every symbol (class, function, method, etc.) must have `start_line` and `end_line` fields
- FR-1.2: Line ranges must span the complete symbol definition (from first line to last line including body)
- FR-1.3: For invalid/unavailable extents, fall back to single line number
- FR-1.4: Line ranges must be 1-indexed (matching source file line numbers)

**Example:**
```cpp
// File: example.cpp, lines 10-25
class Example {     // start_line: 10
public:
    void method();
};                  // end_line: 14
```

Expected: `start_line=10, end_line=14`

### FR-2: Header/Implementation Tracking

**Requirement:** Track separate locations for declarations (headers) and definitions (source files).

**Acceptance Criteria:**
- FR-2.1: When a symbol is declared in a header and defined in a source file, store both locations
- FR-2.2: Header location fields: `header_file`, `header_line`, `header_start_line`, `header_end_line`
- FR-2.3: Primary location (file, line, start_line, end_line) should point to the definition when available
- FR-2.4: For header-only symbols (templates, inline), header fields should be populated
- FR-2.5: Header file paths must be absolute and normalized

**Example:**
```cpp
// include/parser.h (lines 15-25)
class Parser {
    void parse();
};

// src/parser.cpp (lines 50-70)
void Parser::parse() {
    // implementation
}
```

Expected symbol info:
- `file="src/parser.cpp"`, `start_line=50`, `end_line=70` (definition)
- `header_file="include/parser.h"`, `header_start_line=15`, `header_end_line=25` (declaration)

### FR-3: Declaration vs Definition Handling

**Requirement:** Correctly identify and prioritize definitions over declarations.

**Acceptance Criteria:**
- FR-3.1: Use `cursor.get_definition()` to find definition location
- FR-3.2: If cursor is a declaration and definition exists elsewhere, use definition as primary location
- FR-3.3: Store declaration location in header fields
- FR-3.4: For forward declarations with no definition, store declaration as primary location

### FR-4: Tool Output Updates

**Requirement:** Include line range fields in all MCP tool responses.

**Acceptance Criteria:**
- FR-4.1: `get_class_info` includes all line range fields
- FR-4.2: `get_function_info` includes all line range fields
- FR-4.3: `search_classes` includes all line range fields for each result
- FR-4.4: `search_functions` includes all line range fields for each result
- FR-4.5: `find_callees` and `find_callers` include line ranges for function references
- FR-4.6: All other tools returning symbol information include line ranges

**JSON Schema Addition:**
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

### FR-5: get_files_containing_symbol Tool

**Requirement:** New MCP tool to return list of files that reference a symbol.

**Acceptance Criteria:**
- FR-5.1: Tool name: `get_files_containing_symbol`
- FR-5.2: Required parameter: `symbol_name` (string)
- FR-5.3: Optional parameter: `symbol_kind` (enum: "class", "function", "method")
- FR-5.4: Optional parameter: `project_only` (boolean, default: true)
- FR-5.5: Returns JSON with: `symbol`, `kind`, `files` (array), `total_references` (int)
- FR-5.6: File list includes:
  - File where symbol is defined
  - Header file where symbol is declared (if separate)
  - Files that call/reference the symbol
- FR-5.7: Files must be absolute paths, sorted alphabetically
- FR-5.8: Duplicate files removed
- FR-5.9: When `project_only=true`, exclude dependency directories

**Expected Response Schema:**
```json
{
  "symbol": "Parser",
  "kind": "class",
  "files": [
    "/path/to/include/parser.h",
    "/path/to/src/parser.cpp",
    "/path/to/src/main.cpp",
    "/path/to/tests/test_parser.cpp"
  ],
  "total_references": 15
}
```

## Non-Functional Requirements

### NFR-1: Performance

**Requirement:** Line range extraction must not significantly degrade indexing performance.

**Acceptance Criteria:**
- NFR-1.1: Indexing time increase must be <10% compared to baseline
- NFR-1.2: Line range extraction overhead target: <5% (data already available from libclang)
- NFR-1.3: `get_files_containing_symbol` query must complete in <100ms for typical projects
- NFR-1.4: No memory usage increase >20%

**Rationale:** Line extents are already retrieved by libclang, extraction is nearly free.

### NFR-2: Storage Efficiency

**Requirement:** SQLite schema changes must minimize storage overhead.

**Acceptance Criteria:**
- NFR-2.1: New integer columns for line numbers (4 bytes each)
- NFR-2.2: Total storage increase per symbol: ~24 bytes (6 integers)
- NFR-2.3: For 100K symbols: ~2.4 MB increase
- NFR-2.4: SQLite indexes must be created for efficient range queries

### NFR-3: Backward Compatibility

**Requirement:** Changes must not break existing functionality.

**Acceptance Criteria:**
- NFR-3.1: All existing tests must pass
- NFR-3.2: Schema version incremented (4 → 5)
- NFR-3.3: Old caches automatically invalidated and recreated
- NFR-3.4: New fields are optional (NULL allowed in database)
- NFR-3.5: Existing tools continue to work if new fields not present

### NFR-4: Code Quality

**Requirement:** Implementation must follow project standards.

**Acceptance Criteria:**
- NFR-4.1: Pass `make lint` (flake8)
- NFR-4.2: Pass `make format-check` (black formatting)
- NFR-4.3: Type hints added for new methods
- NFR-4.4: Docstrings added for new public methods
- NFR-4.5: Error handling for missing/invalid line ranges

## Data Model Changes

### SymbolInfo Dataclass Extensions

```python
@dataclass
class SymbolInfo:
    # ... existing fields ...

    # New fields (all optional):
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    header_file: Optional[str] = None
    header_line: Optional[int] = None
    header_start_line: Optional[int] = None
    header_end_line: Optional[int] = None
```

### SQLite Schema Changes

**Version:** 4 → 5

**New Columns in `symbols` table:**
- `start_line INTEGER` - First line of symbol definition
- `end_line INTEGER` - Last line of symbol definition
- `header_file TEXT` - Path to header file (if declaration separate)
- `header_line INTEGER` - Declaration line in header
- `header_start_line INTEGER` - Declaration start line
- `header_end_line INTEGER` - Declaration end line

**New Index:**
- `idx_symbols_range` on `(file, start_line, end_line)` for efficient range queries

## Implementation Constraints

### IC-1: libclang API Usage

**Constraint:** Must use standard libclang API only.

**Required APIs:**
- `cursor.extent` - Token extent for line ranges
- `cursor.extent.start.line` - Start line
- `cursor.extent.end.line` - End line
- `cursor.get_definition()` - Find definition from declaration
- `cursor.location.file.name` - File path

**Validation:** Test that API calls work across libclang versions 14-18.

### IC-2: Multi-process Safety

**Constraint:** Changes must be safe in multi-process parallel parsing.

**Requirements:**
- No shared state modified during line range extraction
- SymbolInfo objects are immutable after creation
- SQLite writes batched at end of indexing

### IC-3: Error Resilience

**Constraint:** Missing line range data must not cause indexing failure.

**Requirements:**
- Gracefully handle cursors without valid extent
- Fall back to single line number if extent unavailable
- Log warnings but continue processing
- NULL values allowed in database

## Edge Cases to Handle

### EC-1: Macros and Preprocessor

**Case:** Macro-defined symbols may have unusual extents.

**Handling:** Extract extent as-is, may span macro definition. Document this behavior.

### EC-2: Template Specializations

**Case:** Template specializations may have multiple definitions.

**Handling:** Store extent for each specialization separately. Primary template may have header-only definition.

### EC-3: Forward Declarations

**Case:** Forward declaration with no definition in project.

**Handling:** Store declaration location as primary location. Header fields remain NULL.

### EC-4: Inline Functions

**Case:** Inline function defined in header.

**Handling:** Primary location is header. Header fields may duplicate primary location (acceptable).

### EC-5: Header-only Libraries

**Case:** Entire codebase in headers (e.g., template libraries).

**Handling:** Header fields populated, primary location also points to header. No separate definition.

### EC-6: Multi-line Declarations

**Case:** Function declaration spans multiple lines.

```cpp
virtual std::shared_ptr<Parser>
createParser(
    const std::string& input,
    const Options& opts
) override;
```

**Handling:** `start_line` and `end_line` correctly span all lines.

### EC-7: System Headers

**Case:** Symbol definition in system header (e.g., `/usr/include/`).

**Handling:** Store full path. Filter using `project_only` flag in queries.

## Testing Requirements

See `PHASE1_TEST_PLAN.md` for detailed test specifications.

**Summary:**
- Unit tests for line range extraction
- Integration tests for tool outputs
- Edge case tests (templates, macros, forward declarations)
- Performance regression tests
- Real-world project validation

## Success Criteria

Phase 1 is complete when:

1. ✅ All functional requirements met
2. ✅ All non-functional requirements met
3. ✅ All existing tests pass
4. ✅ New tests added and passing
5. ✅ Documentation updated (CLAUDE.md, README.md)
6. ✅ Performance benchmarks show <10% indexing slowdown
7. ✅ Integration test with example project successful
8. ✅ Code review completed
9. ✅ User approval obtained

## Dependencies

- libclang 14+ (already required)
- SQLite 3.35+ with FTS5 (already required)
- Python 3.10+ (already required)

## Risk Mitigation

**Risk 1:** Line ranges may be incorrect for complex C++ constructs.

**Mitigation:** Extensive edge case testing. Document known limitations.

**Risk 2:** Performance impact greater than estimated.

**Mitigation:** Profile early. Optimize hot paths if needed. Consider making extraction optional via config.

**Risk 3:** libclang may not provide extents for some symbols.

**Mitigation:** Fallback to single line number. Mark as best-effort feature.

## Future Enhancements (Out of Scope for Phase 1)

- Column ranges (start_column, end_column)
- Byte offsets for precise file reading
- Multiple definition locations (overloads, specializations)
- Incremental update optimization
- Caching of frequently queried file lists

## References

- LLM Integration Strategy: `docs/LLM_INTEGRATION_STRATEGY.md`
- Implementation Details: `docs/llm-integration/IMPLEMENTATION_DETAILS.md`
- libclang API: https://libclang.readthedocs.io/
- SQLite FTS5: https://www.sqlite.org/fts5.html
