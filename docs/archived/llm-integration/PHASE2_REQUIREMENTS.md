# Phase 2: Documentation Extraction - Comprehensive Requirements

## Overview

Phase 2 adds **documentation extraction** capabilities to enable LLMs to understand symbol purpose without reading source files. This significantly reduces filesystem access and improves search relevance.

**Key Features:**
1. **Brief Descriptions**: Extract first line/sentence of documentation comments
2. **Full Documentation**: Extract complete documentation comments (Doxygen, JavaDoc-style)
3. **Enhanced Search**: Include documentation in search results for better relevance
4. **Tool Integration**: Add documentation fields to all MCP tool outputs

## Functional Requirements

### FR-1: Brief Comment Extraction

**Requirement:** Extract and store brief descriptions (first line/sentence) for all indexed symbols.

**Acceptance Criteria:**
- FR-1.1: Use `cursor.brief_comment` API from libclang
- FR-1.2: If `brief_comment` unavailable, extract first meaningful line from raw comment
- FR-1.3: Brief should be a single line, max 200 characters
- FR-1.4: Strip comment markers (///, /**, //, etc.)
- FR-1.5: Handle both single-line (//) and multi-line (/* */) comments
- FR-1.6: Store as TEXT in SQLite, NULL if unavailable

**Example:**
```cpp
/// Parses C++ source files and extracts symbols
class Parser {
    // ...
};
```

Expected brief: `"Parses C++ source files and extracts symbols"`

### FR-2: Full Documentation Comment Extraction

**Requirement:** Extract and store complete documentation comments for all indexed symbols.

**Acceptance Criteria:**
- FR-2.1: Use `cursor.raw_comment` API from libclang
- FR-2.2: Preserve comment structure (Doxygen tags, paragraphs, etc.)
- FR-2.3: Store raw comment text with minimal processing
- FR-2.4: Max length: 4000 characters (truncate if longer with "..." suffix)
- FR-2.5: Store as TEXT in SQLite, NULL if unavailable
- FR-2.6: Include both documentation above symbol and inline comments if available

**Example:**
```cpp
/**
 * @brief Parses C++ source files and extracts symbols
 *
 * This class provides comprehensive C++ parsing using libclang.
 * It supports:
 * - Classes and structs
 * - Functions and methods
 * - Template specializations
 *
 * @see SymbolInfo for result structure
 * @note Thread-safe for concurrent parsing
 */
class Parser {
    // ...
};
```

Expected doc_comment: Full comment text preserved with formatting

### FR-3: Comment Type Support

**Requirement:** Support multiple C++ comment styles and documentation formats.

**Acceptance Criteria:**
- FR-3.1: Doxygen-style comments (///, /**...*/)
- FR-3.2: JavaDoc-style comments (/**...*/)
- FR-3.3: Qt-style comments (/*!, //!)
- FR-3.4: Standard C++ comments (//, /*...*/) as fallback
- FR-3.5: Extract comments immediately preceding symbol declaration
- FR-3.6: Extract inline comments after symbol declaration (where applicable)

**Comment Styles:**
```cpp
/// Doxygen single-line
class A {};

/**
 * Doxygen multi-line
 */
class B {};

/*! Qt-style
 *  documentation
 */
class C {};

// Standard comment (extracted as fallback)
class D {};
```

### FR-4: Fallback Documentation Extraction

**Requirement:** When libclang's comment APIs return NULL, attempt manual extraction.

**Acceptance Criteria:**
- FR-4.1: If `brief_comment` is NULL, check `raw_comment`
- FR-4.2: If `raw_comment` is NULL, no further extraction (brief and doc_comment remain NULL)
- FR-4.3: Parse raw_comment to extract brief if libclang didn't provide it
- FR-4.4: Log when fallback extraction is used (debug level)
- FR-4.5: Gracefully handle missing documentation (NULL values acceptable)

### FR-5: Tool Output Updates

**Requirement:** Include documentation fields in all MCP tool responses.

**Acceptance Criteria:**
- FR-5.1: `get_class_info` includes `brief` and `doc_comment`
- FR-5.2: `get_function_info` includes `brief` and `doc_comment`
- FR-5.3: `search_classes` includes `brief` for each result
- FR-5.4: `search_functions` includes `brief` for each result
- FR-5.5: Method info in `get_class_info` includes `brief` for each method
- FR-5.6: Documentation fields are optional (may be NULL/omitted if unavailable)

**JSON Schema Addition:**
```json
{
  "brief": "Parses C++ source files and extracts symbols",
  "doc_comment": "Full documentation comment text..."
}
```

### FR-6: Enhanced Search Integration (Optional)

**Requirement:** Allow searching symbols by documentation content.

**Acceptance Criteria:**
- FR-6.1: Add optional `search_in_docs` parameter to search tools
- FR-6.2: When enabled, search both symbol names AND documentation
- FR-6.3: Use SQLite FTS5 for efficient documentation search
- FR-6.4: Rank results by relevance (name match > brief match > doc match)
- FR-6.5: Default: `search_in_docs=false` (backward compatible)

**Note:** This is an optional enhancement that can be deferred if time-constrained.

## Non-Functional Requirements

### NFR-1: Performance

**Requirement:** Documentation extraction must not significantly impact indexing performance.

**Acceptance Criteria:**
- NFR-1.1: Indexing time increase must be <5% compared to Phase 1
- NFR-1.2: Documentation extraction overhead target: <2% (data already available from libclang)
- NFR-1.3: No additional file I/O required
- NFR-1.4: No memory usage increase >10%

**Rationale:** Comment data is already parsed by libclang, extraction is nearly free.

### NFR-2: Storage Efficiency

**Requirement:** SQLite schema changes must minimize storage overhead.

**Acceptance Criteria:**
- NFR-2.1: Brief stored as TEXT (average ~50-100 bytes per symbol)
- NFR-2.2: Doc comment stored as TEXT (average ~200-500 bytes per symbol)
- NFR-2.3: NULL values use minimal storage (SQLite optimizes NULL columns)
- NFR-2.4: For 100K symbols: ~60MB total increase (worst case)
- NFR-2.5: FTS5 index (if implemented) adds ~30% overhead on doc columns

### NFR-3: Backward Compatibility

**Requirement:** Changes must not break existing functionality.

**Acceptance Criteria:**
- NFR-3.1: All existing tests must pass
- NFR-3.2: Schema version incremented (5 → 6)
- NFR-3.3: Old caches automatically invalidated and recreated
- NFR-3.4: New fields are optional (NULL allowed in database)
- NFR-3.5: Existing tools continue to work if new fields not present
- NFR-3.6: JSON output remains backward compatible (new optional fields)

### NFR-4: Code Quality

**Requirement:** Implementation must follow project standards.

**Acceptance Criteria:**
- NFR-4.1: Pass `make lint` (flake8)
- NFR-4.2: Pass `make format-check` (black formatting)
- NFR-4.3: Type hints added for new methods
- NFR-4.4: Docstrings added for new public methods
- NFR-4.5: Error handling for missing/unavailable documentation
- NFR-4.6: Debug logging for documentation extraction process

## Data Model Changes

### SymbolInfo Dataclass Extensions

```python
@dataclass
class SymbolInfo:
    # ... existing fields from Phase 1 ...

    # New fields (all optional):
    brief: Optional[str] = None          # Brief description (first line)
    doc_comment: Optional[str] = None    # Full documentation comment
```

### SQLite Schema Changes

**Version:** 5 → 6

**New Columns in `symbols` table:**
- `brief TEXT` - Brief description (first line of documentation)
- `doc_comment TEXT` - Full documentation comment (up to 4000 chars)

**Optional: FTS5 Virtual Table for Documentation Search**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_docs_fts USING fts5(
    qualified_name,
    brief,
    doc_comment,
    content=symbols,
    content_rowid=id
);
```

**Note:** FTS5 table is optional and can be added in a later iteration if documentation search is needed.

## Implementation Constraints

### IC-1: libclang API Usage

**Constraint:** Must use standard libclang comment APIs only.

**Required APIs:**
- `cursor.brief_comment` - Brief description (may be NULL)
- `cursor.raw_comment` - Full comment text (may be NULL)

**Validation:** Test that API calls work across libclang versions 14-18.

### IC-2: Multi-process Safety

**Constraint:** Changes must be safe in multi-process parallel parsing.

**Requirements:**
- No shared state modified during documentation extraction
- SymbolInfo objects remain immutable after creation
- SQLite writes batched at end of indexing (existing behavior)

### IC-3: Error Resilience

**Constraint:** Missing documentation must not cause indexing failure.

**Requirements:**
- Gracefully handle cursors without comments (brief/doc_comment → NULL)
- Handle libclang exceptions when accessing comment APIs
- Log warnings for unexpected errors (debug level only)
- NULL values allowed in database and JSON output

### IC-4: Character Encoding

**Constraint:** Properly handle UTF-8 and special characters in comments.

**Requirements:**
- Store documentation as UTF-8 in SQLite
- Preserve Unicode characters in comments
- Handle non-ASCII characters correctly
- Escape special characters in JSON output

## Edge Cases to Handle

### EC-1: No Documentation

**Case:** Symbol has no documentation comment.

**Handling:** `brief` and `doc_comment` both NULL. No error, no warning.

### EC-2: Malformed Documentation

**Case:** Comment exists but is not properly formatted (missing closing marker, etc.).

**Handling:** libclang's parser handles this. Extract whatever is available. Log at debug level if extraction fails.

### EC-3: Very Long Documentation

**Case:** Documentation comment exceeds 4000 characters.

**Handling:** Truncate at 4000 characters, append "..." to indicate truncation. Log truncation at debug level.

### EC-4: Special Characters in Comments

**Case:** Documentation contains special characters: `<`, `>`, `&`, quotes, etc.

**Handling:** Store as-is in database. JSON encoder will properly escape when returning results.

### EC-5: Multi-line Brief

**Case:** `brief_comment` spans multiple lines (rare but possible).

**Handling:**
- Take only first line
- If first line empty, check subsequent lines
- Max length 200 characters
- Join with spaces if necessary

### EC-6: Inline vs. Preceding Comments

**Case:** Symbol has both preceding documentation comment and inline comment.

**Handling:** libclang's `raw_comment` returns the documentation comment (typically the preceding one). Inline comments are generally ignored by libclang's comment extraction.

### EC-7: Template Specializations

**Case:** Template and specializations may have different documentation.

**Handling:** Extract documentation separately for each (primary template and each specialization). Each gets its own `brief` and `doc_comment`.

### EC-8: Inherited Documentation

**Case:** Method overrides base class method with documentation.

**Handling:** Extract documentation only from the current symbol. Do NOT inherit from base class (Phase 2 scope limitation). May be added in Phase 4+.

### EC-9: Doxygen @brief Tag

**Case:** Comment has explicit `@brief` tag.

**Handling:** libclang's `brief_comment` should extract this automatically. If not, fallback extraction should parse first line after `@brief`.

## Testing Requirements

### Unit Tests

1. **Test Documentation Extraction:**
   - Extract brief from single-line comment
   - Extract brief from multi-line comment
   - Extract full doc comment (Doxygen-style)
   - Extract full doc comment (JavaDoc-style)
   - Handle missing documentation (NULL values)
   - Handle very long documentation (truncation)
   - Handle special characters in comments

2. **Test Comment Parsing:**
   - Doxygen /// style
   - Doxygen /** */ style
   - Qt /*! */ style
   - Standard // and /* */ as fallback
   - Mixed comment styles in same file

3. **Test Fallback Logic:**
   - When `brief_comment` is NULL but `raw_comment` exists
   - Extract first meaningful line from raw comment
   - Handle both comment types being NULL

### Integration Tests

1. **Test Tool Outputs:**
   - `get_class_info` includes brief and doc_comment
   - `get_function_info` includes brief and doc_comment
   - `search_classes` includes brief in results
   - `search_functions` includes brief in results
   - NULL documentation handled gracefully

2. **Test SQLite Schema:**
   - Database auto-recreates on version 6
   - New columns exist and accept NULL
   - Documentation stored and retrieved correctly
   - UTF-8 encoding preserved

3. **Test End-to-End:**
   - Index project with documented symbols
   - Verify documentation extracted for all symbols
   - Query symbols and verify documentation returned
   - Test with real-world project (e.g., sample with Doxygen docs)

### Performance Tests

1. **Indexing Performance:**
   - Measure indexing time with vs without documentation extraction
   - Verify <5% slowdown
   - Test on large project (1000+ files)

2. **Storage Impact:**
   - Measure cache size increase
   - Verify within expected bounds (~60MB for 100K symbols)

3. **Query Performance:**
   - Verify query times unchanged with new fields
   - Test retrieval of large documentation comments

## Success Criteria

Phase 2 is complete when:

1. ✅ All functional requirements met
2. ✅ All non-functional requirements met
3. ✅ All existing tests pass
4. ✅ New tests added and passing (min 80% coverage for new code)
5. ✅ Documentation updated (CLAUDE.md, README.md)
6. ✅ Performance benchmarks show <5% indexing slowdown
7. ✅ Integration test with example project successful
8. ✅ Code review completed
9. ✅ User approval obtained

## Completion Status

**Status:** ✅ **COMPLETE** (Merged to main: 2025-12-08)

**Merged PR:** #47 (feature/phase2-test-suite-and-docs)
**Verification:** See `PHASE2_CONSISTENCY_VERIFICATION.md`

**Actual Results:**
- ✅ 54/54 tests passing (100% pass rate)
- ✅ Schema version: 7.0
- ✅ Implementation: `cpp_analyzer.py:843-888` (_extract_documentation)
- ✅ Data model: `symbol_info.py` with `brief` and `doc_comment` fields
- ✅ MCP tools: All tools return documentation fields
- ✅ Performance: Documentation extraction uses libclang APIs (minimal overhead)
- ✅ All consistency checks passed

## Dependencies

- libclang 14+ with comment APIs (already required)
- SQLite 3.35+ (already required)
- Python 3.10+ (already required)

## Risk Mitigation

**Risk 1:** libclang comment APIs may not work reliably across all versions.

**Mitigation:** Extensive testing across libclang 14-18. Fallback to NULL if API fails. Document known limitations.

**Risk 2:** Documentation extraction may slow indexing more than estimated.

**Mitigation:** Profile early. Comment data is already parsed by libclang, so extraction should be nearly free. If needed, make extraction optional via config.

**Risk 3:** Very long or malformed comments may cause issues.

**Mitigation:** Truncate at 4000 chars. Handle exceptions gracefully. Log at debug level only.

**Risk 4:** UTF-8 encoding issues with special characters.

**Mitigation:** Use proper UTF-8 encoding throughout. Test with non-ASCII comments. JSON encoder handles escaping.

## Implementation Plan

### Step 1: Data Model Updates
1. Update `SymbolInfo` dataclass (symbol_info.py)
2. Update SQLite schema (schema.sql, increment version to 6)
3. Update `CURRENT_SCHEMA_VERSION` in sqlite_cache_backend.py

### Step 2: Documentation Extraction
1. Modify `_process_cursor()` in cpp_analyzer.py
2. Extract brief via `cursor.brief_comment`
3. Extract doc_comment via `cursor.raw_comment`
4. Implement fallback extraction from raw_comment
5. Add truncation logic for long comments
6. Add error handling and debug logging

### Step 3: Storage Integration
1. Update `_symbol_to_dict()` in sqlite_cache_backend.py
2. Update `_dict_to_symbol()` to handle new fields
3. Update INSERT/UPDATE queries to include new columns
4. Test NULL handling

### Step 4: Tool Output Updates
1. Update `get_class_info` in cpp_mcp_server.py
2. Update `get_function_info` in cpp_mcp_server.py
3. Update `search_classes` in cpp_mcp_server.py
4. Update `search_functions` in cpp_mcp_server.py
5. Ensure JSON serialization handles NULL values

### Step 5: Testing
1. Write unit tests for extraction logic
2. Write integration tests for tool outputs
3. Write performance tests
4. Test with real-world project
5. Run regression tests

### Step 6: Documentation
1. Update CLAUDE.md with Phase 2 features
2. Update tool descriptions in cpp_mcp_server.py
3. Add examples to documentation
4. Update README if needed

## Future Enhancements (Out of Scope for Phase 2)

- Documentation search via FTS5 (`search_in_docs` parameter)
- Inherited documentation from base classes
- Cross-reference extraction (@see, @ref tags)
- Parameter documentation extraction (@param tags)
- Return value documentation (@return tags)
- Code example extraction from comments
- External documentation links

## References

- LLM Integration Strategy: `docs/LLM_INTEGRATION_STRATEGY.md`
- Implementation Details: `../llm-integration/IMPLEMENTATION_DETAILS.md`
- Phase 1 Requirements: `../llm-integration/PHASE1_REQUIREMENTS.md`
- libclang Comment APIs: https://libclang.readthedocs.io/
- Doxygen Documentation: https://www.doxygen.nl/manual/docblocks.html
