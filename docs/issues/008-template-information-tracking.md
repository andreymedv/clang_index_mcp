# [008] Template Information Tracking

**GitHub Issue:** [#85](https://github.com/andreymedv/clang_index_mcp/issues/85)
**Category:** Feature
**Priority:** Medium
**Status:** Proposed
**Date Identified:** 2025-12-27
**Estimated Effort:** Requires investigation (3-5 weeks estimate)
**Complexity:** Complex

---

## Problem Statement

The MCP server does not expose whether functions or classes are templates, nor does it track template specializations. This causes LLMs to misinterpret template code as regular overloaded functions or multiple unrelated classes.

### Current Behavior

When querying for a function or class:
- No indication whether it's a template
- Template parameters are not exposed
- Template specializations are invisible or confused with overloads
- Cannot distinguish between:
  - `template<typename T> void foo(T)` (template function)
  - `void foo(int)` + `void foo(double)` (overloaded functions)
- Cannot distinguish between:
  - `template<typename T> class Container` (class template)
  - `class IntContainer` + `class DoubleContainer` (separate classes)

### Expected/Desired Behavior

The system should:
1. **Indicate template status**: Mark symbols as templates in responses
2. **Expose template parameters**: Return template parameter lists
3. **Track specializations**: Link specializations to primary template
4. **Distinguish from overloads**: Clear differentiation between template instantiations and overloads
5. **Support all template types**:
   - Function templates
   - Class templates
   - Partial specializations
   - Full specializations
   - Variable templates (C++14)
   - Alias templates (related to issue #007)

---

## Impact Assessment

**User Impact:**
- **High**: Discovered in real-world codebase with widely-used template functions
- LLMs provide incorrect analysis (suggesting overloads instead of template specializations)
- Cannot understand generic programming patterns
- Code comprehension severely impaired for template-heavy codebases

**Development Impact:**
- Requires symbol extraction logic changes to capture template information
- Database schema additions for template metadata
- MCP tool response format changes (non-breaking if additive)
- Complex testing requirements (templates are intricate)

**Business Impact:**
- Adoption blocker for modern C++ codebases (templates are fundamental)
- Cannot provide value for template-heavy libraries (STL, Boost, etc.)
- Essential for understanding generic programming in C++

---

## Real-World Examples

### Example 1: Template Function Confusion

```cpp
// Primary template
template<typename T>
void process(T value) {
    // generic implementation
}

// Full specialization for int
template<>
void process<int>(int value) {
    // optimized for int
}

// Full specialization for std::string
template<>
void process<std::string>(std::string value) {
    // string-specific handling
}
```

**Current problem**: LLM sees three separate `process` functions and treats them as overloads, not understanding:
- There's a primary template
- The other two are specializations of that template
- How to find the generic implementation vs. specialized versions

### Example 2: Class Template with Partial Specialization

```cpp
// Primary template
template<typename T, typename U>
class Pair {
    T first;
    U second;
};

// Partial specialization: both types same
template<typename T>
class Pair<T, T> {
    // optimized for identical types
};

// Full specialization
template<>
class Pair<int, int> {
    // specialized for int pairs
};
```

**Current problem**: LLM sees multiple `Pair` classes with no understanding of template relationships.

### Example 3: Default Template Arguments

```cpp
template<typename T, typename Allocator = std::allocator<T>>
class Vector {
    // ...
};
```

**Current problem**: Default template arguments are invisible, affecting understanding of how the template is used.

### Example 4: Variadic Templates

```cpp
template<typename... Args>
void log(Args... args) {
    // variadic template
}
```

**Current problem**: No indication that this accepts variable number of template parameters.

---

## Proposed Solutions

### Investigation Required First

⚠️ **Before proposing detailed solutions, we need to investigate:**

1. **libclang Capabilities**
   - How to detect template declarations vs. instantiations?
   - Can we extract template parameter lists?
   - How to identify specializations and link them to primary template?
   - What information is available for partial vs. full specializations?
   - Can we detect explicit vs. implicit instantiations?

2. **Requirements Clarification**
   - What level of template detail do LLMs need?
   - Should we track implicit instantiations or only explicit specializations?
   - How to represent template parameters in responses?
   - How to handle template template parameters?
   - Should we track where templates are instantiated?

3. **Schema Design**
   - Extend `symbols` table with template fields?
   - New `template_specializations` table?
   - How to represent template parameter constraints (C++20 concepts)?
   - How to link specializations to primary templates?

4. **Scope Boundaries**
   - Function templates vs. class templates vs. variable templates
   - Partial vs. full specializations
   - Variadic templates
   - Dependent names and SFINAE
   - Template metaprogramming constructs

### Placeholder Solution Sketch (Pending Investigation)

**Option 1: Extend `symbols` Table with Template Fields**

**Concept**: Add template-specific columns to symbols table

**Potential Schema Changes**:
```sql
ALTER TABLE symbols ADD COLUMN is_template BOOLEAN DEFAULT 0;
ALTER TABLE symbols ADD COLUMN template_params TEXT DEFAULT NULL;  -- JSON array
ALTER TABLE symbols ADD COLUMN template_kind TEXT DEFAULT NULL;  -- 'primary', 'full_spec', 'partial_spec'
ALTER TABLE symbols ADD COLUMN primary_template_usr TEXT DEFAULT NULL;  -- Link to primary template
```

**Example JSON for template_params**:
```json
[
  {"name": "T", "kind": "typename", "has_default": false},
  {"name": "Allocator", "kind": "typename", "has_default": true, "default": "std::allocator<T>"}
]
```

**Pros:**
- All symbol information in one place
- Existing queries continue to work
- Additive change (backward compatible for responses)

**Cons:**
- Adds complexity to symbols table
- NULL values for non-template symbols
- Limited flexibility for complex template relationships

**Estimated Effort:** TBD after investigation
**Risk Level:** Medium

---

**Option 2: Dedicated `templates` and `template_specializations` Tables**

**Concept**: Separate tables for template metadata

**Potential Schema**:
```sql
CREATE TABLE templates (
    template_usr TEXT PRIMARY KEY,
    symbol_usr TEXT NOT NULL,  -- FK to symbols
    template_kind TEXT NOT NULL,  -- 'function', 'class', 'variable', 'alias'
    template_params TEXT NOT NULL,  -- JSON array
    is_variadic BOOLEAN DEFAULT 0,
    FOREIGN KEY (symbol_usr) REFERENCES symbols(usr)
);

CREATE TABLE template_specializations (
    spec_usr TEXT PRIMARY KEY,
    primary_usr TEXT NOT NULL,  -- FK to templates
    specialization_kind TEXT NOT NULL,  -- 'full', 'partial'
    specialization_args TEXT DEFAULT NULL,  -- JSON array (for partial spec)
    FOREIGN KEY (primary_usr) REFERENCES templates(template_usr)
);
```

**Pros:**
- Clean separation of concerns
- Flexible for complex template relationships
- Doesn't bloat symbols table

**Cons:**
- More complex queries (multiple joins)
- More tables to maintain
- Potentially slower queries

**Estimated Effort:** TBD after investigation
**Risk Level:** High

---

## Recommended Approach

**Status**: Requires investigation before recommendation can be made.

**Investigation Plan:**
1. **Phase 1** (1 week): libclang capability analysis
   - Test template detection capabilities
   - Determine what template information is extractable
   - Identify cursor kinds and APIs for templates
   - Test with complex template scenarios

2. **Phase 2** (1 week): Scope definition
   - Define what template features to support in v1
   - Prioritize: function templates, class templates, basic specializations
   - Defer: template metaprogramming, SFINAE, concepts (C++20)

3. **Phase 3** (1 week): Schema design
   - Choose between Option 1 vs. Option 2 based on findings
   - Design JSON format for template parameters
   - Plan for future extensibility

4. **Phase 4** (1-2 weeks): Prototype and testing
   - Implement prototype with small test cases
   - Test with real-world template code
   - Validate performance impact

5. **Phase 5** (1 week): MCP tool design
   - Design how template info appears in tool responses
   - Consider backward compatibility
   - Plan for new template-specific tools if needed

---

## Decision Log

**2025-12-27**: Initial identification
- **Decision**: Record as feature request, defer implementation pending investigation
- **Rationale**: Discovered during manual testing; LLM confused template specializations with function overloads; significant impact on understanding modern C++ code
- **Next Steps**:
  1. Create detailed investigation plan
  2. Analyze libclang template detection capabilities
  3. Define minimum viable template support scope

---

## Implementation Notes

### Dependencies

**Technical Dependencies:**
- libclang template AST capabilities (to be investigated)
- Database schema changes (may require version bump)
- JSON serialization for template parameter representation

**Logical Dependencies:**
- May interact with [007] Type Alias Tracking (template aliases)
- None otherwise

### Risks

1. **Risk: Template complexity is vast, scope creep likely**
   - **Mitigation**: Define strict scope for v1 (basic templates only), defer advanced features

2. **Risk: Partial specialization matching logic is complex**
   - **Mitigation**: May need to defer partial specializations to later phase

3. **Risk: libclang may not provide all needed template information**
   - **Mitigation**: Early investigation to validate feasibility

4. **Risk: Template metaprogramming detection may be impossible or impractical**
   - **Mitigation**: Focus on explicit templates, not compile-time computed types

5. **Risk: Performance impact of additional parsing**
   - **Mitigation**: Benchmark during prototype phase

### Testing Requirements

- Unit tests for template detection from AST
- Integration tests with complex template code:
  - Function templates with specializations
  - Class templates with partial/full specializations
  - Variadic templates
  - Templates with default arguments
  - Nested templates
  - Template template parameters
- Performance tests on template-heavy codebases
- Regression tests to ensure non-template code unaffected

### Migration/Compatibility

- **Schema Change**: May require database version bump (depends on chosen option)
- **MCP Response Format**: Additive changes (backward compatible if new fields added)
- **Migration Strategy**: Cache auto-recreation if schema changes

---

## References

**Related Documentation:**
- [CLAUDE.md](../../CLAUDE.md) - Development guide
- [ANALYSIS_STORAGE_ARCHITECTURE.md](../ANALYSIS_STORAGE_ARCHITECTURE.md) - Database architecture

**Code References:**
- `mcp_server/cpp_analyzer.py:_process_cursor()` - Symbol extraction (needs template detection)
- `mcp_server/symbol_info.py` - SymbolInfo class (may need template fields)
- `mcp_server/schema.sql` - Database schema (needs template support)

**External Resources:**
- [libclang AST documentation](https://clang.llvm.org/doxygen/group__CINDEX.html)
- [libclang template cursor kinds](https://clang.llvm.org/doxygen/group__CINDEX.html#ga6c1b33c8e5ef7da43d89e8b689c80932)
- C++ standard: templates and specialization

**Related Issues:**
- [007] Type Alias Tracking ([#84](https://github.com/andreymedv/clang_index_mcp/issues/84)) - template aliases overlap with this feature

---

## Next Steps

1. **Immediate**: Create investigation task for libclang template capabilities
2. **Short-term** (before implementation):
   - Complete investigation phases 1-5
   - Update this document with findings
   - Create detailed implementation plan with scope clearly defined
3. **Long-term**: Implementation only after investigation, scoping, and design approval

**Trigger Conditions** (when to revisit):
- User reports additional cases where template information is critical
- Investigation phase completes with positive findings
- Schema v9.0 planning begins (opportunity to bundle with issue #007)

**Owner** (if assigned): TBD

---

## Notes

- Identified during manual testing on CloudOffice codebase
- LLM confused template function with multiple specializations as function overloads
- Templates are fundamental to modern C++ - this feature is essential for proper C++ code understanding
- This is a **medium-high priority** feature for modern C++ codebase support
- Complexity is HIGH due to template intricacy in C++

---

## Open Questions

1. Should we track implicit template instantiations or only explicit ones?
2. How to handle SFINAE (Substitution Failure Is Not An Error)?
3. Should we support C++20 concepts in template constraints?
4. How to represent template template parameters?
5. Should we track where templates are instantiated (usage sites)?
6. How to handle variadic template parameter packs?
7. What level of detail is useful for LLMs vs. overwhelming?
