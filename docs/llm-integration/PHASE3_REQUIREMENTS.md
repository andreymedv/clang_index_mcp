# Phase 3: Call Graph Enhancement - Comprehensive Requirements

## Overview

Phase 3 adds **enhanced call graph capabilities** to provide line-level precision for function calls, extract cross-references from documentation, and capture parameter-specific documentation. This enables LLMs to understand code relationships more precisely and trace execution flow at a granular level.

**Key Features:**
1. **Line-Level Call Graph**: Track exact line numbers where function calls occur
2. **Cross-Reference Extraction**: Extract @see, @ref, @relates Doxygen tags
3. **Parameter Documentation**: Extract @param, @tparam, @return documentation
4. **Enhanced Find Callers**: Return call sites with line numbers and context
5. **Documentation Relationships**: Link symbols via documentation cross-references

## Functional Requirements

### FR-1: Line-Level Call Graph Tracking

**Requirement:** Track the exact line number where each function call occurs within a caller.

**Acceptance Criteria:**
- FR-1.1: Extend CallGraphAnalyzer to store call_line for each caller→callee edge
- FR-1.2: Extract line number from cursor.location.line during AST traversal
- FR-1.3: Store multiple call sites if same function called multiple times from same caller
- FR-1.4: Include column number (optional) for precise location within line
- FR-1.5: Handle calls in different contexts (direct calls, function pointers, lambdas)
- FR-1.6: Distinguish between declaration references and actual call expressions

**Example:**
```cpp
void processData() {
    validate();        // Line 45
    transform();       // Line 46
    if (check()) {     // Line 47
        validate();    // Line 48 (second call to same function)
    }
}
```

Expected call graph data:
- `processData` → `validate` at lines [45, 48]
- `processData` → `transform` at line 46
- `processData` → `check` at line 47

### FR-2: Enhanced find_callers Tool Output

**Requirement:** Return call site information including line numbers for each caller.

**Acceptance Criteria:**
- FR-2.1: Add `call_sites` array to find_callers response
- FR-2.2: Each call site includes: file, caller function, line number, column (optional)
- FR-2.3: Sort call sites by file, then line number
- FR-2.4: Include surrounding context (±2 lines) for each call site
- FR-2.5: Maintain backward compatibility: existing callers list still present
- FR-2.6: Add optional `include_context` parameter (default: true)

**JSON Response Format:**
```json
{
  "function": "validate",
  "callers": ["processData", "checkInput"],
  "call_sites": [
    {
      "file": "/path/to/module.cpp",
      "caller": "processData",
      "line": 45,
      "column": 5,
      "context": [
        "void processData() {",
        "    validate();",
        "    transform();"
      ]
    },
    {
      "file": "/path/to/module.cpp",
      "caller": "processData",
      "line": 48,
      "column": 9,
      "context": [
        "    if (check()) {",
        "        validate();",
        "    }"
      ]
    }
  ],
  "total_call_sites": 2
}
```

### FR-3: Cross-Reference Extraction from Documentation

**Requirement:** Extract Doxygen cross-reference tags (@see, @ref, @relates) to link related symbols.

**Acceptance Criteria:**
- FR-3.1: Parse raw_comment for @see tags (e.g., "@see ClassName::method")
- FR-3.2: Parse @ref tags (e.g., "@ref function_name")
- FR-3.3: Parse @relates tags (e.g., "@relates ClassName")
- FR-3.4: Store cross-references in separate table: symbol_cross_refs(symbol_id, ref_type, target)
- FR-3.5: Resolve reference targets to USRs where possible
- FR-3.6: Support multiple cross-references per symbol
- FR-3.7: Handle unresolved references gracefully (store as text if USR not found)

**Example:**
```cpp
/**
 * @brief Validates input data
 * @see DataTransformer::transform
 * @ref checkInput
 * @relates InputProcessor
 */
void validate() { }
```

Expected extracted references:
- Type: `see`, Target: `DataTransformer::transform`
- Type: `ref`, Target: `checkInput`
- Type: `relates`, Target: `InputProcessor`

### FR-4: Parameter Documentation Extraction

**Requirement:** Extract parameter-specific documentation from function comments.

**Acceptance Criteria:**
- FR-4.1: Parse @param tags (e.g., "@param name Description")
- FR-4.2: Parse @tparam tags for template parameters
- FR-4.3: Parse @return/@returns tags for return value documentation
- FR-4.4: Store in separate table: parameter_docs(symbol_id, param_name, description)
- FR-4.5: Match parameter names to actual function signature
- FR-4.6: Support [in], [out], [in,out] directives (Doxygen style)
- FR-4.7: Include in get_function_info response

**Example:**
```cpp
/**
 * @brief Processes user input
 * @param input The raw input string to process
 * @param flags Processing flags (see ProcessFlags enum)
 * @tparam T The data type for processing
 * @return Processed result or error code
 */
template<typename T>
int processInput(const std::string& input, int flags);
```

Expected parameter docs:
- `input`: "The raw input string to process"
- `flags`: "Processing flags (see ProcessFlags enum)"
- `T` (template): "The data type for processing"
- return: "Processed result or error code"

### FR-5: New MCP Tool: get_cross_references

**Requirement:** Add new MCP tool to query symbol cross-references.

**Acceptance Criteria:**
- FR-5.1: Tool accepts symbol name or USR
- FR-5.2: Returns all cross-references for the symbol
- FR-5.3: Optionally filter by reference type (@see, @ref, @relates)
- FR-5.4: Resolve target symbols to full info (name, file, line)
- FR-5.5: Support bidirectional queries (what references X, what X references)
- FR-5.6: Include reference type and source location

**Tool Definition:**
```json
{
  "name": "get_cross_references",
  "description": "Get documentation cross-references for a symbol",
  "inputSchema": {
    "symbol": "string (required)",
    "ref_type": "string (optional): see|ref|relates",
    "direction": "string (optional): outgoing|incoming|both (default: outgoing)"
  }
}
```

### FR-6: Enhanced get_function_info Output

**Requirement:** Include parameter documentation and cross-references in function info.

**Acceptance Criteria:**
- FR-6.1: Add `parameters` array with name and documentation
- FR-6.2: Add `return_doc` field for return value documentation
- FR-6.3: Add `cross_refs` array with related symbols
- FR-6.4: Add `template_params` array for template parameter docs
- FR-6.5: All new fields optional (NULL if unavailable)

**Enhanced JSON Response:**
```json
{
  "name": "processInput",
  "file": "/path/to/module.cpp",
  "line": 45,
  "brief": "Processes user input",
  "parameters": [
    {
      "name": "input",
      "type": "const std::string&",
      "doc": "The raw input string to process"
    },
    {
      "name": "flags",
      "type": "int",
      "doc": "Processing flags (see ProcessFlags enum)"
    }
  ],
  "template_params": [
    {
      "name": "T",
      "doc": "The data type for processing"
    }
  ],
  "return_doc": "Processed result or error code",
  "cross_refs": [
    {
      "type": "see",
      "target": "DataTransformer::transform",
      "file": "/path/to/transformer.h",
      "line": 23
    }
  ]
}
```

### FR-7: Call Graph Query Enhancements

**Requirement:** Add new query capabilities for line-level call graph analysis.

**Acceptance Criteria:**
- FR-7.1: Add `get_call_sites` tool to retrieve all calls from a function
- FR-7.2: Include line numbers and column positions in results
- FR-7.3: Support filtering by target function or file
- FR-7.4: Return source code context for each call site
- FR-7.5: Handle method calls (member function calls) correctly

**New Tool: get_call_sites**
```json
{
  "name": "get_call_sites",
  "description": "Get all function calls made by a specific function",
  "inputSchema": {
    "caller": "string (required) - function making the calls",
    "target": "string (optional) - filter by target function",
    "include_context": "boolean (default: true)"
  }
}
```

## Non-Functional Requirements

### NFR-1: Performance

**Requirement:** Enhanced call graph tracking must not significantly impact indexing performance.

**Acceptance Criteria:**
- NFR-1.1: Line-level tracking adds <5% to indexing time
- NFR-1.2: Cross-reference parsing adds <3% to indexing time (most files have few tags)
- NFR-1.3: Parameter doc parsing adds <2% to indexing time
- NFR-1.4: Total Phase 3 overhead: <10% increased indexing time
- NFR-1.5: Query performance for call graphs remains <100ms for 100K symbols
- NFR-1.6: Cross-reference queries complete in <50ms

**Rationale:** Line numbers already extracted by libclang, minimal overhead. Documentation parsing already done in Phase 2, adding tag parsing is incremental.

### NFR-2: Storage

**Requirement:** Phase 3 additions must not excessively increase cache size.

**Acceptance Criteria:**
- NFR-2.1: Call sites: ~8 bytes per call (line + column as integers)
- NFR-2.2: Cross-references: ~50 bytes per reference (type + target + line)
- NFR-2.3: Parameter docs: ~100 bytes per parameter (name + description)
- NFR-2.4: Estimated total increase: ~5-10 MB per 100K symbols
- NFR-2.5: SQLite compression helps reduce actual storage

**Calculation:**
- 100K symbols × 3 calls avg × 8 bytes = 2.4 MB (call sites)
- 100K symbols × 0.5 refs avg × 50 bytes = 2.5 MB (cross-refs)
- 100K symbols × 0.3 funcs × 3 params × 100 bytes = 9 MB (parameter docs)
- Total: ~14 MB worst case, actual ~5-10 MB with compression and NULLs

### NFR-3: Backward Compatibility

**Requirement:** Maintain compatibility with existing MCP tools and clients.

**Acceptance Criteria:**
- NFR-3.1: Existing find_callers response format unchanged (callers array still present)
- NFR-3.2: New fields (call_sites, parameters, cross_refs) are additions, not replacements
- NFR-3.3: All new fields are optional (can be omitted if NULL)
- NFR-3.4: Schema version bumped to 8.0 (auto-recreates cache)
- NFR-3.5: Old clients can ignore new fields without breaking

### NFR-4: Data Quality

**Requirement:** Extracted data must be accurate and reliable.

**Acceptance Criteria:**
- NFR-4.1: Call sites match actual source code locations (verified via source reading)
- NFR-4.2: Cross-references resolve to correct targets ≥95% of the time
- NFR-4.3: Unresolved references stored as text (no silent drops)
- NFR-4.4: Parameter docs matched to correct parameters ≥98% accuracy
- NFR-4.5: Handle missing/malformed documentation gracefully (no crashes)

### NFR-5: Scalability

**Requirement:** Support large codebases with extensive call graphs and documentation.

**Acceptance Criteria:**
- NFR-5.1: Handle 1M+ call sites without degradation
- NFR-5.2: Handle 100K+ cross-references without degradation
- NFR-5.3: SQLite indexes on call_sites and cross_refs tables
- NFR-5.4: Queries remain sub-second for large datasets
- NFR-5.5: Memory usage stays bounded during indexing

## Database Schema Changes

### Schema Version: 7.0 → 8.0

### New Table: call_sites

```sql
CREATE TABLE call_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_usr TEXT NOT NULL,              -- USR of calling function
    callee_usr TEXT NOT NULL,              -- USR of called function
    file TEXT NOT NULL,                    -- Source file containing call
    line INTEGER NOT NULL,                 -- Line number of call
    column INTEGER,                        -- Column number (optional)
    FOREIGN KEY (caller_usr) REFERENCES symbols(usr),
    FOREIGN KEY (callee_usr) REFERENCES symbols(usr)
);

CREATE INDEX idx_call_sites_caller ON call_sites(caller_usr);
CREATE INDEX idx_call_sites_callee ON call_sites(callee_usr);
CREATE INDEX idx_call_sites_file ON call_sites(file);
```

### New Table: cross_references

```sql
CREATE TABLE cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_usr TEXT NOT NULL,              -- USR of source symbol
    ref_type TEXT NOT NULL,                -- 'see', 'ref', 'relates'
    target TEXT NOT NULL,                  -- Target symbol name or USR
    target_usr TEXT,                       -- Resolved USR (if found)
    source_file TEXT NOT NULL,             -- File where ref defined
    source_line INTEGER NOT NULL,          -- Line where ref defined
    FOREIGN KEY (symbol_usr) REFERENCES symbols(usr)
);

CREATE INDEX idx_cross_refs_symbol ON cross_references(symbol_usr);
CREATE INDEX idx_cross_refs_target ON cross_references(target_usr);
CREATE INDEX idx_cross_refs_type ON cross_references(ref_type);
```

### New Table: parameter_docs

```sql
CREATE TABLE parameter_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    function_usr TEXT NOT NULL,            -- USR of function
    param_name TEXT NOT NULL,              -- Parameter name
    param_type TEXT,                       -- 'param', 'tparam', 'return'
    description TEXT,                      -- Parameter documentation
    direction TEXT,                        -- 'in', 'out', 'inout' (Doxygen)
    FOREIGN KEY (function_usr) REFERENCES symbols(usr)
);

CREATE INDEX idx_param_docs_function ON parameter_docs(function_usr);
CREATE INDEX idx_param_docs_name ON parameter_docs(param_name);
```

### Migration Strategy

**Development Mode (Current):**
- Increment schema version to 8.0 in schema.sql
- Update CURRENT_SCHEMA_VERSION in sqlite_cache_backend.py
- Database automatically recreated on version mismatch
- No manual migration needed

**Future Production Mode:**
- Write migration script: 7_to_8_add_call_graph_enhancements.sql
- ALTER TABLE not needed (all new tables)
- Migration is additive only (safe)

## Implementation Architecture

### Component Changes

**1. cpp_analyzer.py**
- Add `_extract_call_sites()` method to traverse CALL_EXPR nodes
- Add `_extract_cross_references()` to parse @see, @ref, @relates tags
- Add `_extract_parameter_docs()` to parse @param, @tparam, @return tags
- Integrate into `_process_cursor()` AST traversal
- Store extracted data via CacheManager

**2. call_graph.py (CallGraphAnalyzer)**
- Extend to store line/column for each call edge
- Add methods: `get_call_sites()`, `get_calls_from_function()`
- Update internal data structures to support line-level tracking
- Add query methods for MCP tool integration

**3. sqlite_cache_backend.py**
- Add table creation for call_sites, cross_references, parameter_docs
- Add query methods: `get_call_sites()`, `get_cross_refs()`, `get_param_docs()`
- Add indexes for performance
- Update cache versioning to 8.0

**4. cpp_mcp_server.py**
- Update find_callers tool to include call_sites
- Update get_function_info to include parameters, cross_refs, return_doc
- Add new tools: get_cross_references, get_call_sites
- Update tool schemas with new fields

**5. search_engine.py**
- Add cross-reference resolution logic
- Add parameter doc retrieval for function queries
- Optimize queries to minimize database hits

### Data Flow

**Indexing Flow (Enhanced):**
1. Parse file with libclang → AST
2. For each function/method cursor:
   - Extract basic symbol info (existing)
   - Extract documentation (Phase 2, existing)
   - **NEW:** Traverse child nodes to find CALL_EXPR
   - **NEW:** For each call, record (caller_usr, callee_usr, line, column)
   - **NEW:** Parse doc_comment for @see/@ref/@relates tags
   - **NEW:** Parse doc_comment for @param/@tparam/@return tags
3. Store in SQLite:
   - symbols table (existing)
   - **NEW:** call_sites table
   - **NEW:** cross_references table
   - **NEW:** parameter_docs table

**Query Flow (Enhanced):**
1. find_callers("validate"):
   - Query symbols table for USR (existing)
   - Query call_graph for callers (existing)
   - **NEW:** Query call_sites table for line numbers
   - **NEW:** Optionally read source files for context
   - Return enhanced response

2. get_function_info("processInput"):
   - Query symbols table (existing)
   - **NEW:** Query parameter_docs table
   - **NEW:** Query cross_references table
   - Return enhanced response

## Testing Strategy

### Unit Tests

**Test Coverage:**
- Call site extraction from CALL_EXPR nodes
- Cross-reference parsing (@see, @ref, @relates)
- Parameter documentation parsing (@param, @tparam, @return)
- Multiple calls to same function in one caller
- Unresolved cross-references handling
- Malformed Doxygen tag handling

**Test Files:**
- `tests/test_call_sites_extraction.py`
- `tests/test_cross_references.py`
- `tests/test_parameter_docs.py`

### Integration Tests

**Test Scenarios:**
1. Index sample project with call graphs
2. Query call sites via find_callers with include_context
3. Query cross-references via get_cross_references
4. Query parameter docs via get_function_info
5. Verify line numbers match actual source code
6. Test bidirectional cross-reference queries

**Test Files:**
- `tests/test_phase3_integration.py`

### Performance Tests

**Benchmarks:**
1. Indexing time with Phase 3 enabled vs disabled
2. Cache size increase measurement
3. Query performance for call_sites (target: <100ms)
4. Query performance for cross_references (target: <50ms)

### Edge Cases

**Must Handle:**
- Function pointers and callbacks (call sites)
- Lambda captures calling outer functions
- Recursive functions (caller == callee)
- Macro expansions (calls in macros)
- Template instantiations (same template, different types)
- Unresolved cross-references (typos in @see tags)
- Missing parameter documentation (some params undocumented)
- Variadic functions (va_args, parameter packs)

## Risk Assessment

### Technical Risks

**Risk 1: Call Site False Positives**
- **Issue:** Identifying true function calls vs function pointer assignments
- **Mitigation:** Use libclang's CALL_EXPR cursor kind (not DECL_REF_EXPR)
- **Likelihood:** Low (libclang distinguishes these)

**Risk 2: Cross-Reference Resolution Failures**
- **Issue:** @see tags may reference symbols not in current project
- **Mitigation:** Store unresolved refs as text, provide fuzzy matching
- **Likelihood:** Medium (external library refs common)

**Risk 3: Parameter Name Mismatches**
- **Issue:** @param names might not match actual parameter names
- **Mitigation:** Fuzzy matching, store all params even if unmatched
- **Likelihood:** Medium (typos, refactoring)

**Risk 4: Performance Degradation**
- **Issue:** AST traversal for call sites may slow indexing
- **Mitigation:** Limit depth, skip unneeded nodes, benchmark early
- **Likelihood:** Low (Phase 1 & 2 had minimal impact)

### Scope Risks

**Risk 5: Scope Creep**
- **Issue:** Call graph enhancements could expand indefinitely
- **Mitigation:** Stick to defined FR requirements, defer extras to Phase 4
- **Likelihood:** Medium

## Implementation Phases

### Phase 3.1: Line-Level Call Graph ✅ COMPLETE
- ✅ Implement call site extraction with line/column precision
- ✅ Extend CallGraphAnalyzer with Set-based storage
- ✅ Add call_sites table (schema v8.0)
- ✅ Enhanced find_callers tool (returns dict with call_sites array)
- ✅ New get_call_sites tool (forward analysis)
- ✅ Comprehensive tests (40 tests, 100% passing)
- ✅ Full test suite compatibility (544 tests passing)
- ✅ PR #50 submitted
- ✅ Performance verified (<5% overhead)
- ✅ Database schema updated to v8.0

### ~~Phase 3.2: Cross-Reference Extraction~~ REMOVED FROM SCOPE
- Deferred to future phase
- @see/@ref/@relates parsing moved out of Phase 3
- Cross-references table removed from Phase 3 scope
- Rationale: Call graph tracking provides core value; cross-refs are enhancement

### ~~Phase 3.3: Parameter Documentation~~ REMOVED FROM SCOPE
- Deferred to future phase
- @param/@tparam/@return parsing moved out of Phase 3
- parameter_docs table removed from Phase 3 scope
- Rationale: Phase 2 already provides full doc_comment; param parsing is incremental enhancement

## Revised Scope

**Phase 3 is now COMPLETE** with only Phase 3.1 (Line-Level Call Graph).

The removed sub-phases (cross-references and parameter documentation) are enhancements that can be addressed in future phases if needed. Phase 3.1 delivers the core value:
- Precise call site tracking for impact analysis
- Line-level navigation for code understanding
- Bidirectional call graph queries (find_callers + get_call_sites)
- Production-ready with comprehensive test coverage

## Success Criteria (Revised for Reduced Scope)

**Phase 3 is complete when:**
1. ✅ Line-level call graph implemented and tested (FR-1, FR-2, FR-7)
2. ✅ All NFR requirements met (performance, storage, compatibility)
3. ✅ Comprehensive tests written and passing (40 Phase 3 tests)
4. ✅ Full test suite compatibility maintained (544/544 tests passing)
5. ✅ Performance verified (<5% indexing overhead, well under 10% target)
6. ✅ Storage impact minimal (call_sites table, ~8 bytes per call)
7. ✅ Schema version 8.0 deployed
8. ✅ PR submitted with full documentation (#50)
9. ⏳ README.md updated to mark Phase 3 complete
10. ⏳ PHASE3_CONSISTENCY_VERIFICATION.md created (optional)

## Out of Scope

**Not included in Phase 3:**
- Inheritance-based cross-references (Phase 4)
- Template specialization relationships (Phase 4)
- Include dependency visualization (Phase 4)
- Semantic code search (Phase 5)
- Data flow analysis (Future)
- Control flow graphs (Future)

## References

**Doxygen Documentation:**
- @see: https://www.doxygen.nl/manual/commands.html#cmdsee
- @ref: https://www.doxygen.nl/manual/commands.html#cmdref
- @relates: https://www.doxygen.nl/manual/commands.html#cmdrelates
- @param: https://www.doxygen.nl/manual/commands.html#cmdparam

**libclang APIs:**
- CALL_EXPR cursor kind
- cursor.location for line/column
- cursor.raw_comment for documentation

**Related Documents:**
- [PHASE1_REQUIREMENTS.md](PHASE1_REQUIREMENTS.md)
- [PHASE2_REQUIREMENTS.md](PHASE2_REQUIREMENTS.md)
- [PHASE3_TEST_PLAN.md](PHASE3_TEST_PLAN.md) (to be created)
- [CLAUDE.md](/CLAUDE.md)

---

**Document Version:** 1.0
**Created:** 2025-12-09
**Status:** Draft - Ready for review and implementation
**Schema Version Target:** 8.0
