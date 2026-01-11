# C++ MCP Server - Known Limitations

**Last Updated:** 2026-01-11
**Validation Status:** Based on comprehensive testing (see VALIDATION_TEST_RESULTS.md)

This document describes the known limitations of the C++ MCP server, their impact, and available workarounds.

---

## Template Handling Limitations

### 1. Template Name Disambiguation ⚠️

**Status:** PARTIAL - Templates are indexed but cannot be distinguished by name alone

**Description:**
Template definitions and their specializations all share the same `name` and `qualified_name` in the index. You cannot search for specific template specializations by their complete name (e.g., `Container<int>`).

**Example:**
```cpp
template<typename T>
class Container { };

template<> class Container<int> { };        // Explicit specialization
template<typename T> class Container<T*> { }; // Partial specialization
```

All three are stored with:
- `name`: `"Container"`
- `qualified_name`: `"Container"`
- Distinguished only by `kind` field: `class_template`, `class`, `partial_specialization`

**Impact:**
- `get_class_info("Container")` returns arbitrary match (usually template base)
- `get_class_info("Container<int>")` will not find the specialization
- `search_classes({"pattern": "Container"})` returns all variants without distinction
- Cannot query derived classes of a specific specialization

**Workaround:**
1. Use `search_classes()` and filter results by `kind` field
2. Check `line` field to distinguish different variants
3. Query derived classes to see which specializations are actually used

**Related Issue:** #85 (Template Information Tracking) - P2 priority

**Example Workaround:**
```python
# Find template definition specifically
results = search_classes({"pattern": "Container"})
template_def = [r for r in results if r["kind"] == "class_template"][0]

# Find all specializations
specializations = [r for r in results if r["kind"] in ["class", "partial_specialization"]]
```

---

### 2. Template-Based Transitive Inheritance ❌

**Status:** NOT SUPPORTED - Inheritance through template parameter substitution is not detected

**Description:**
When a template class inherits from its template parameter (common in CRTP patterns and mixin-based inheritance), the analyzer does not detect transitive inheritance relationships.

**Example:**
```cpp
class IInterface { virtual void execute() = 0; };

template<typename T>
class ImplementationBase : public T { };

class ConcreteImpl : public ImplementationBase<IInterface> { };
```

**Current Behavior:**
- `get_derived_classes("IInterface")` returns `[]` (empty)
- Direct inheritance is captured: `ConcreteImpl` → `ImplementationBase<IInterface>`
- But `ImplementationBase<IInterface>` → `IInterface` link is not established

**What's Stored:**
```sql
-- ImplementationBase base_classes: ["type-parameter-0-0"]  (template parameter, not IInterface)
-- ConcreteImpl base_classes: ["ImplementationBase<IInterface>"]
-- No transitive link: IInterface ← ImplementationBase<IInterface> ← ConcreteImpl
```

**Impact:**
- Incomplete inheritance hierarchies for template-heavy codebases
- CRTP patterns invisible to analysis tools
- Mixin-based inheritance not detected
- Interface discovery incomplete

**Workaround:**
Manual code inspection or search for template base class name to find potential derivations.

**Related Issues:**
- **Prerequisite:** #85 (Template Information Tracking) - P2
- **Future:** New issue needed - "Template-Based Transitive Inheritance Detection"
  - Effort: 2-3 weeks
  - Complexity: HIGH
  - Requires template parameter substitution analysis

---

## Performance Considerations

### 4. Large Template-Heavy Projects

**Description:**
Projects with extensive template usage may experience:
- Longer indexing times (templates create multiple AST nodes)
- Larger SQLite databases (each specialization stored separately)
- More complex query results (multiple template variants)

**Recommendations:**
- Use `compile_commands.json` for accurate template parsing
- Consider excluding generated template code (e.g., `exclude_patterns: ["*_autogen.h"]`)
- Monitor cache size in `.mcp_cache/` directory

---

## Feature Support Status

### ✅ Fully Supported
- Qualified name pattern matching (Phase 2)
- Namespace filtering (`namespace` parameter)
- Template indexing (definitions, specializations)
- Template argument qualification (preserves full namespace paths)
- Direct inheritance tracking
- Call graph analysis
- Documentation extraction (Phase 2)

### ⚠️ Partial Support
- Template name disambiguation (requires metadata tracking)

### ❌ Not Supported
- Template-based transitive inheritance (CRTP patterns)
- Template parameter tracking
- Template specialization discovery by base name
- Template metadata in search results

---

## Workarounds Summary

### For Template Searches

**Problem:** Cannot find template by base name
**Workaround:**
```python
# Instead of: get_class_info("TemplateClass")
# Use search and filter:
results = search_classes({"pattern": "TemplateClass"})
template_def = [r for r in results if r["kind"] == "class_template"]
specializations = [r for r in results if r["kind"] in ["class", "partial_specialization"]]
```

### For Inheritance Queries

**Problem:** Template-based inheritance not detected
**Workaround:**
```python
# Find classes using the template directly:
search_classes({"pattern": ""})  # Empty pattern = all classes
# Filter results where base_classes contains template name
[c for c in results if any("TemplateBase" in base for base in c.get("base_classes", []))]
```

### For Namespace Disambiguation

**Problem:** Multiple classes with same name
**Solution:** ✅ Use namespace parameter (fully supported)
```python
# Filter by exact namespace:
search_classes({"pattern": "View", "namespace": "ui"})

# Or use qualified pattern (suffix match):
search_classes({"pattern": "ui::View"})
```

---

## Future Improvements

### Issue #85: Template Information Tracking (P2)
**Planned Features:**
- `is_template` flag on symbols
- `template_parameters` field (e.g., `["T"]`, `["typename T", "int N"]`)
- Specialized names with arguments (e.g., `"Container<int>"`)
- Template-aware search functionality

**Estimated Effort:** 3-5 weeks
**Status:** Open (beads ID: cplusplus_mcp-2an)

### Template-Based Transitive Inheritance (Future)
**Planned Features:**
- Template parameter substitution analysis
- Transitive inheritance through template specializations
- Complete CRTP pattern detection

**Dependencies:** Issue #85
**Estimated Effort:** 2-3 weeks
**Status:** Planned (not yet created)

---

## Testing and Validation

All limitations documented here have been validated through comprehensive testing:
- **Test Project:** `examples/template_test/`
- **Test Cases:** TC1-TC6 (see VALIDATION_TEST_RESULTS.md)
- **Validation Date:** 2026-01-10 (initial), 2026-01-11 (TC5 completed)

**Key Refutations:**
- ✅ Qualified names DO work (Observation #2 refuted - TC1)
- ✅ Namespace filtering IS available (Observation #3 refuted - TC2)
- ✅ Template argument qualification IS preserved (Observation #6 refuted - TC5)

**Confirmed Limitations:**
- ⚠️ Template name disambiguation (Observation #5 - TC3)
- ❌ Template-based transitive inheritance (Observation #4 - TC4)

See `docs/MANUAL_TESTING_OBSERVATIONS.md` for detailed testing history.

---

## Reporting Issues

If you encounter behavior not documented here:
1. Check `docs/MANUAL_TESTING_OBSERVATIONS.md` for known observations
2. Verify with a minimal test case in `examples/template_test/`
3. Report at: https://github.com/andreymedv/cplusplus_mcp/issues

---

## Related Documentation

- **Validation Results:** `VALIDATION_TEST_RESULTS.md`
- **Manual Testing:** `docs/MANUAL_TESTING_OBSERVATIONS.md`
- **Next Steps:** `NEXT_STEPS.md`
- **User Guide:** `README.md`
- **Development Guide:** `CLAUDE.md`
