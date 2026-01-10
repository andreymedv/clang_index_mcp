# Template Class Search and Specialization Discovery - Investigation Results

**Issue:** [#99](https://github.com/andreymedv/cplusplus_mcp/issues/99)
**Date:** 2026-01-10
**Status:** Investigation Complete - Ready for Implementation

## Executive Summary

Template classes cannot be found by their base name in the current implementation. Users must specify exact specializations (e.g., `Container<int>` instead of `Container`), making template-based architectures difficult to explore. This investigation confirms the root cause and proposes solutions.

## Investigation Findings

### 1. How libclang Represents Templates

We created a test project with comprehensive template scenarios and analyzed the libclang AST representation:

**Generic Template Definitions** → `CLASS_TEMPLATE` cursor kind
```
Container (line 10)
  Kind: CLASS_TEMPLATE
  Spelling: Container
  Display Name: Container<T>
  USR: c:@ST>1#T@Container
```

**Explicit Full Specializations** → `CLASS_DECL` cursor kind (NOT CLASS_TEMPLATE!)
```
Container<int> (line 26)
  Kind: CLASS_DECL
  Spelling: Container
  Display Name: Container<int>
  USR: c:@S@Container>#I
```

**Partial Specializations** → `CLASS_TEMPLATE_PARTIAL_SPECIALIZATION` cursor kind
```
Container<T*> (line 95)
  Kind: CLASS_TEMPLATE_PARTIAL_SPECIALIZATION
  Spelling: Container
  Display Name: Container<T *>
  USR: c:@SP>1#T@Container>#*t0.0
```

**Implicit Specializations** → NOT visible as top-level AST entities!
- `Container<double>`, `Container<char*>` only appear as type references
- Not represented as separate CLASS_DECL cursors

**Critical Observation:**
- Both templates and specializations have the SAME `spelling` ("Container")
- But different `displayname` (`Container<T>` vs `Container<int>`)
- Different USR formats distinguish them

### 2. Current Indexing Behavior

**What's Indexed:**
```
Container → Only Container<int> (USR: c:@S@Container>#I)
Pair → Only Pair<int, int> (USR: c:@S@Pair>#I#I)
max → Only int* specialization
```

**What's Missing:**
```
❌ Generic templates: Container<T>, Pair<K,V>, Base<Derived>, Tuple<Args>
❌ Partial specializations: Container<T*>
❌ Implicit specializations: Container<double>, Container<char*>
```

**Search Results:**
- `search_classes("Container")` → Only finds `Container<int>` specialization
- `search_classes("Container.*")` → Only finds `Container<int>` (regex doesn't help)
- No way to discover the generic template or other specializations

### 3. Root Cause Analysis

**File:** `mcp_server/cpp_analyzer.py:1307-1365`

Currently processed cursor kinds:
```python
# Line 1307: Classes and structs
if kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL):
    # Process explicit specializations only

# Line 1365: Functions and methods
elif kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
    # Process explicit specializations only
```

**NOT processed:**
```python
❌ CursorKind.CLASS_TEMPLATE (generic template class definitions)
❌ CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION (partial specializations)
❌ CursorKind.FUNCTION_TEMPLATE (generic template functions)
```

**Explicit Skip:**
Line 1227-1228 in `_is_template_specialization()`:
```python
if kind == CursorKind.FUNCTION_TEMPLATE:
    return False  # Generic templates are not specializations
```

This function is checking if something IS a specialization, but templates themselves are being completely ignored by the cursor processing logic.

## USR Format Analysis

Understanding USR patterns is critical for linking templates to specializations:

```
Generic Template:              c:@ST>1#T@Container
Explicit Specialization (int): c:@S@Container>#I
Explicit Specialization (int,int): c:@S@Pair>#I#I
Partial Specialization (T*):   c:@SP>1#T@Container>#*t0.0
```

**Pattern:**
- `c:@ST>` = Template class
- `c:@S@` = Regular class (including explicit template specializations)
- `c:@SP>` = Partial template specialization
- After class name: `>#I` = template argument (int), `>#*t0.0` = pointer type

## Proposed Solutions

### Option A: Automatic Specialization Aggregation (RECOMMENDED)

**Approach:**
1. Index CLASS_TEMPLATE and CLASS_TEMPLATE_PARTIAL_SPECIALIZATION cursors
2. Store them with `kind="class_template"` and `kind="partial_specialization"`
3. When searching by base name:
   - Find template definition (if exists)
   - Find all specializations (query USR patterns)
   - Aggregate results
4. `get_derived_classes("Container")` aggregates across ALL specializations

**Pros:**
- Encapsulates complexity in the server
- Saves LLM tokens (single query gets everything)
- Matches user mental model

**Cons:**
- Requires template→specialization linkage logic
- More complex implementation

**Implementation Steps:**
1. Add template cursor kinds to `_process_cursor()` (cpp_analyzer.py:1307)
2. Store templates with distinct `kind` values
3. Implement `_find_template_specializations(base_name)` helper
4. Modify search functions to aggregate template results
5. Update `get_derived_classes()` to query all specializations

### Option B: New Tool `get_template_specializations()`

**Approach:**
1. Index templates as in Option A
2. Add new MCP tool: `get_template_specializations(template_name)`
3. LLM discovers specializations, then queries each separately

**Pros:**
- Simpler to implement
- Clear separation of concerns

**Cons:**
- LLM must orchestrate multiple queries
- Higher token usage
- More API calls

### Option C: Flag `include_template_specializations=true`

**Approach:**
1. Add optional flag to existing tools
2. When enabled, aggregate template results

**Pros:**
- Backward compatible
- Opt-in behavior

**Cons:**
- Adds complexity to every tool signature
- Inconsistent with other search behavior

## Recommended Implementation: Option A

**Rationale:**
1. **User Experience:** Matches how developers think about templates
2. **Token Efficiency:** Single query instead of multiple round-trips
3. **Consistency:** Similar to how we handle other symbol relationships
4. **LLM Friendliness:** Less orchestration burden on the model

## Scope for v1 Implementation

### ✅ In Scope (v1)

**Generic Template Definitions:**
- `template<typename T> class Container`
- Store as `kind="class_template"`
- Index with base name "Container"

**Explicit Full Specializations:**
- `template<> class Container<int>`
- Already indexed as `kind="class"`
- Link to generic template via USR pattern matching

**Partial Specializations:**
- `template<typename T> class Container<T*>`
- Store as `kind="partial_specialization"`
- Link to generic template via USR

**Template Functions:**
- `template<typename T> T max(T a, T b)`
- Store as `kind="function_template"`
- Explicit specializations already indexed

### ⚠️ Deferred (Future Work)

**Implicit Specializations:**
- `Container<double>` from usage/instantiation
- Not visible as top-level AST cursors in libclang
- Would require deep analysis of types throughout codebase
- **Decision:** Defer to future enhancement

**Advanced Template Features:**
- Variadic templates (e.g., `Tuple<Args...>`)
- SFINAE patterns
- C++20 concepts
- Template template parameters
- **Decision:** Support basic indexing, defer advanced analysis

**Template Argument Tracking:**
- Detailed template parameter information
- Constraint tracking
- Default arguments
- **Decision:** Defer to Issue #85 (Template Information Tracking)

## Implementation Plan

### Phase 1: Index Template Definitions (2-3 days)

**File:** `mcp_server/cpp_analyzer.py`

1. **Add template cursor kinds to _process_cursor()** (line ~1307)
   ```python
   # Process templates
   elif kind == CursorKind.CLASS_TEMPLATE:
       # Extract and store template definition
   elif kind == CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION:
       # Extract and store partial specialization
   elif kind == CursorKind.FUNCTION_TEMPLATE:
       # Extract and store function template
   ```

2. **Extract template information:**
   - Use `cursor.spelling` for base name
   - Use `cursor.displayname` for full template signature
   - Use `cursor.get_usr()` for unique identification
   - Store template parameter count/names (basic)

3. **Update symbol storage:**
   - Add `kind` values: "class_template", "partial_specialization", "function_template"
   - No schema changes needed (symbols table already supports any `kind` value)

4. **Test with template_test_project:**
   - Verify all templates are indexed
   - Check USR formats
   - Confirm search finds templates

### Phase 2: Template→Specialization Linkage (3-4 days)

**File:** `mcp_server/cpp_analyzer.py`

1. **Implement USR pattern matching:**
   ```python
   def _find_template_specializations(self, template_usr: str) -> List[str]:
       """Find all specializations of a template by USR pattern."""
       # Template USR: c:@ST>1#T@Container
       # Specialization USR: c:@S@Container>#I
       # Extract base pattern and search
   ```

2. **Add template metadata to SymbolInfo:**
   - `template_base_usr`: USR of generic template (for specializations)
   - `is_template`: Boolean flag
   - `template_params`: Basic parameter info (optional)

3. **Update search methods:**
   - Modify `search_classes()` to include templates
   - Aggregate template + specializations in results
   - Mark which results are templates vs specializations

### Phase 3: Derived Classes Aggregation (2 days)

**File:** `mcp_server/cpp_analyzer.py`

1. **Update `get_derived_classes()`:**
   ```python
   def get_derived_classes(self, class_name: str):
       # Check if class_name is a template
       template_info = self._find_template(class_name)
       if template_info:
           # Find all specializations
           specializations = self._find_template_specializations(...)
           # Get derived classes for EACH specialization
           # Aggregate results
       else:
           # Existing logic for non-templates
   ```

2. **Handle CRTP patterns:**
   - Classes derived from `Base<DerivedA>` should appear when querying "Base"
   - This enables Issue #4 (Class Search Substring Matching) use case

### Phase 4: Testing & Documentation (2 days)

1. **Write comprehensive tests:**
   - Test template indexing
   - Test specialization discovery
   - Test search aggregation
   - Test derived class queries with templates

2. **Update documentation:**
   - Tool descriptions mention template support
   - Examples with template classes
   - USR format documentation

3. **Run validation test plan TC3**

**Total Estimated Effort:** 9-11 days

## Validation Criteria

### Test Cases

**TC1: Index Generic Templates**
```python
analyzer.index_project()
templates = analyzer.search_classes("Container")
assert any(t['kind'] == 'class_template' for t in templates)
```

**TC2: Find Explicit Specializations**
```python
results = analyzer._find_template_specializations("c:@ST>1#T@Container")
assert "c:@S@Container>#I" in [r['usr'] for r in results]
```

**TC3: Aggregated Search**
```python
results = analyzer.search_classes("Container")
# Should include: Container<T>, Container<int>, Container<T*>, etc.
assert len(results) >= 3
```

**TC4: Derived Classes Across Specializations**
```python
derived = analyzer.get_derived_classes("Container")
# Should include: IntContainer, DoubleContainer (from different specializations)
assert "IntContainer" in [d['name'] for d in derived]
assert "DoubleContainer" in [d['name'] for d in derived]
```

**TC5: Template Functions**
```python
results = analyzer.search_functions("max")
assert any(f['kind'] == 'function_template' for f in results)
```

## Next Steps

1. ✅ Investigation complete
2. ⏭ Review findings with team
3. ⏭ Approve Option A approach
4. ⏭ Create implementation branch: `feature/template-search`
5. ⏭ Begin Phase 1 implementation
6. ⏭ Coordinate with Issue #85 (Template Information Tracking) for Phase 2

## Related Issues

- **#85: Template Information Tracking** - Broader template metadata (params, constraints, etc.)
- **#98: Qualified Names Support** - Similar pattern matching issues
- **#4: Class Search Substring Matching** - Will benefit from template support for CRTP

## Files Modified (Estimated)

- `mcp_server/cpp_analyzer.py` - Core implementation
- `mcp_server/symbol_info.py` - Template metadata fields
- `tests/test_analyzer_integration.py` - Template search tests
- `tests/fixtures/template_test_project/` - Test data (already created)
- `docs/MCP_TOOLS.md` - Documentation updates

## References

- Test project: `tests/fixtures/template_test_project/`
- Investigation script: `scripts/investigate_template_representation.py`
- Analysis script: `scripts/analyze_template_indexing.py`
- libclang cursor analysis output: `/tmp/template_libclang_analysis.txt`
