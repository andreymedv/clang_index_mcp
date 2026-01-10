# Qualified Names Support - Migration Guide

This guide helps you understand and adopt the Qualified Names Support features added in Phases 1-3.

## Overview

The qualified names support enhancement adds powerful namespace-aware search capabilities to the C++ MCP server. These features help disambiguate symbols across namespaces, making it easier for LLMs to navigate complex C++ codebases.

**Phases:**
- **Phase 1**: Basic qualified name storage and extraction
- **Phase 2**: Pattern matching for qualified names
- **Phase 3**: Overload metadata (template specialization detection)
- **Phase 4**: Testing and documentation (this guide)

---

## What's New

### 1. Qualified Name Fields (Phase 1)

All search results now include two new fields:

- **`qualified_name`**: Fully qualified symbol name with namespaces/classes
  - Examples: `"app::ui::View"`, `"std::vector"`, `"Database::Connection::open"`

- **`namespace`**: Namespace and class portion only (excluding symbol name)
  - Examples: `"app::ui"`, `"std"`, `"Database::Connection"`

**Example Response:**
```json
{
  "name": "View",
  "qualified_name": "app::ui::View",
  "namespace": "app::ui",
  "kind": "class",
  "file": "/path/to/view.h",
  "line": 42
}
```

### 2. Qualified Pattern Matching (Phase 2)

Pattern parameters now support four matching modes:

#### Mode 1: Unqualified (No `::`)
```python
search_classes("View")
# Matches: View, app::View, app::ui::View, legacy::View
```

#### Mode 2: Qualified Suffix (With `::`, no leading `::`)
```python
search_classes("ui::View")
# Matches: app::ui::View, legacy::ui::View
# Does NOT match: myui::View (component boundaries respected)
```

#### Mode 3: Exact Match (Leading `::`)
```python
search_classes("::View")
# Matches ONLY: View (global namespace)
# Does NOT match: app::View, ns::View
```

#### Mode 4: Regex Patterns
```python
search_classes("app::.*::View")
# Uses regex fullmatch semantics
# Matches: app::core::View, app::ui::View
# Does NOT match: app::View (no middle component)
```

### 3. Template Specialization Metadata (Phase 3)

All search results now include:

- **`is_template_specialization`**: Boolean indicating if symbol is a template specialization

**Use Case:** Distinguish between:
- Generic templates: `template<typename T> void foo(T)` → `is_template_specialization: false`
- Specializations: `template<> void foo<int>(int)` → `is_template_specialization: true`
- Regular overloads: `void foo(double)` → `is_template_specialization: false`

**Example Response:**
```json
{
  "name": "process",
  "qualified_name": "app::process",
  "signature": "void (int)",
  "is_template_specialization": true
}
```

---

## Migration Steps

### Step 1: No Changes Required (Backward Compatible)

The qualified names features are **100% backward compatible**. Existing code continues to work unchanged:

```python
# This still works exactly as before
results = analyzer.search_classes("MyClass")
```

### Step 2: Adopt Qualified Patterns (Optional, Recommended)

Use qualified patterns when you need disambiguation:

**Before (ambiguous):**
```python
# Returns ALL View classes across all namespaces
results = analyzer.search_classes("View")
# Problem: 10+ results from different namespaces
```

**After (precise):**
```python
# Returns only ui::View (suffix match)
results = analyzer.search_classes("ui::View")
# Result: 1-2 results (app::ui::View, legacy::ui::View)

# Or use exact match for global namespace
results = analyzer.search_classes("::View")
# Result: 1 result (global View only)
```

### Step 3: Use Qualified Names in Results (Recommended)

Display qualified names to users for clarity:

**Before:**
```python
for result in results:
    print(f"Found: {result['name']} in {result['file']}")
# Output: Found: View in /path/to/view.h
# Problem: Which View? Global or namespaced?
```

**After:**
```python
for result in results:
    print(f"Found: {result['qualified_name']} in {result['file']}")
# Output: Found: app::ui::View in /path/to/view.h
# Clear: This is the ui::View from app namespace
```

### Step 4: Filter by Namespace (Recommended)

Use the `namespace` field for namespace-based filtering:

```python
# Get all classes in the 'app::ui' namespace
results = analyzer.search_classes("")  # Empty pattern = match all
ui_classes = [r for r in results if r['namespace'] == 'app::ui']
```

### Step 5: Detect Template Specializations (Optional)

Use `is_template_specialization` when working with templates:

```python
results = analyzer.search_functions("process")

# Separate generic from specialized
generic = [r for r in results if not r['is_template_specialization']]
specialized = [r for r in results if r['is_template_specialization']]

print(f"Generic templates: {len(generic)}")
print(f"Specializations: {len(specialized)}")
```

---

## Pattern Matching Guide

### When to Use Each Mode

| Use Case | Pattern Mode | Example |
|----------|--------------|---------|
| Find all instances of a symbol | Unqualified | `"View"` |
| Narrow down by namespace | Qualified suffix | `"ui::View"` |
| Only global namespace | Exact match | `"::View"` |
| Complex filtering | Regex | `"app::.*::View"` |
| Find symbol in specific file | Unqualified + file_name | `search_classes("View", file_name="view.h")` |

### Pattern Matching Examples

**Scenario 1: Find specific namespaced class**
```python
# You know the class is in the 'network' namespace
results = analyzer.search_classes("network::Client")
# Returns: app::network::Client, legacy::network::Client
```

**Scenario 2: Avoid wrong namespace**
```python
# User asks: "Find the ui::View class, not the test::View"
results = analyzer.search_classes("ui::View")
# Does NOT match test::View, test::ui::View
```

**Scenario 3: Find all global symbols**
```python
# Find only symbols in global namespace (no namespace)
results = analyzer.search_classes("::Config")
# Returns only: Config (global)
# Excludes: app::Config, test::Config
```

**Scenario 4: Find methods in specific class**
```python
# Find save() method in Database class
results = analyzer.search_functions("Database::save")
# Returns: app::Database::save, etc.
```

**Scenario 5: Complex pattern matching**
```python
# Find all View classes in app:: namespace (any sub-namespace)
results = analyzer.search_classes("app::.*::View")
# Returns: app::ui::View, app::core::View, app::legacy::ui::View
```

---

## Performance

All qualified pattern searches complete in **<100ms** for typical codebases (tested with 1000+ classes):

| Operation | Performance | Notes |
|-----------|-------------|-------|
| Unqualified search | ~1-3ms | Fastest |
| Qualified suffix | ~1-3ms | Same as unqualified |
| Exact match | ~0-1ms | Fastest (early filtering) |
| Regex pattern | ~1-10ms | Slightly slower but still fast |
| Empty pattern (all) | ~1-3ms | Returns all symbols |

See `tests/test_qualified_name_performance.py` for benchmarks.

---

## Common Use Cases

### Use Case 1: Disambiguating Common Names

**Problem:** Many projects have multiple `Config`, `Manager`, `View` classes.

**Solution:**
```python
# Instead of: search_classes("Config")
# which returns 10+ results, use:
results = analyzer.search_classes("app::Config")
# Returns only app namespace Config classes
```

### Use Case 2: Finding Methods in Specific Classes

**Problem:** Finding `save()` method returns 50+ results from different classes.

**Solution:**
```python
# Search with class qualification
results = analyzer.search_functions("Database::save")
# Returns only Database::save methods, not User::save, etc.
```

### Use Case 3: Template Overload Analysis

**Problem:** Need to understand template specializations vs generic templates.

**Solution:**
```python
results = analyzer.search_functions("process")

for result in results:
    if result['is_template_specialization']:
        print(f"Specialization: {result['qualified_name']} {result['signature']}")
    else:
        print(f"Generic: {result['qualified_name']} {result['signature']}")
```

### Use Case 4: Namespace-Aware Code Navigation

**Problem:** LLM suggests wrong class from wrong namespace.

**Solution:**
```python
# User context: "Working in app::ui namespace"
# Search with namespace context
results = analyzer.search_classes("ui::Widget")
# Automatically filters to ui namespace
```

---

## Troubleshooting

### Q: My qualified pattern doesn't match anything

**A:** Check for these common issues:

1. **Leading colons**: `"::View"` only matches global namespace. Remove `::` prefix for suffix matching.
2. **Full path required**: `"View"` != `"ui::View"`. Use suffix mode: `"ui::View"`.
3. **Typos in namespace**: `"appp::View"` won't match `"app::View"`.
4. **Case sensitivity**: Patterns are case-insensitive: `"APP::view"` matches `"app::View"`.

### Q: Template functions not found

**A:** libclang may not index template function declarations without instantiations. This is a known limitation. Try:

1. Instantiate the template explicitly in your code
2. Use template specializations (these ARE indexed)
3. Search for template usage sites instead

### Q: Pattern matches too many results

**A:** Make your pattern more specific:

```python
# Too broad
search_classes("View")  # 50+ results

# Better
search_classes("ui::View")  # 5 results

# Most specific
search_classes("app::ui::View")  # 1-2 results
```

### Q: How do I know what namespaces exist?

**A:** Search with empty pattern and group by namespace:

```python
results = analyzer.search_classes("")
namespaces = set(r['namespace'] for r in results)
print("Available namespaces:", namespaces)
```

---

## API Reference

### New Response Fields

All search methods (`search_classes`, `search_functions`, `search_symbols`, `find_in_file`) now return:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `qualified_name` | string | Fully qualified symbol name | `"app::ui::View"` |
| `namespace` | string | Namespace portion only | `"app::ui"` |
| `is_template_specialization` | boolean | True if template specialization | `true` for `foo<int>` |

### Pattern Parameter Syntax

All search methods support these pattern syntaxes:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `"Symbol"` | Unqualified (any namespace) | `"View"` |
| `"ns::Symbol"` | Qualified suffix match | `"ui::View"` |
| `"::Symbol"` | Exact (global namespace only) | `"::Config"` |
| `"ns::.*::Symbol"` | Regex pattern | `"app::.*::View"` |
| `""` | Match all (useful with file_name) | `""` |

### Affected MCP Tools

**Updated tools (return qualified_name, namespace, is_template_specialization):**
- `search_classes`
- `search_functions`
- `search_symbols`
- `find_in_file`
- `get_class_info` (in method results)

**Unchanged tools:**
- `set_project_directory`
- `refresh_project`
- `get_indexing_status`
- `wait_for_indexing`
- `find_callers` / `find_callees`

---

## Best Practices

1. **Start broad, then narrow**: Begin with unqualified search, then use qualified patterns if too many results.

2. **Display qualified names**: Always show `qualified_name` to users, not just `name`.

3. **Use qualified patterns for disambiguation**: When user mentions namespace context, use qualified patterns.

4. **Empty pattern + file filter**: Use `pattern=""` with `file_name` to get all symbols in a file.

5. **Leverage namespace field**: Filter results by namespace in post-processing if needed.

6. **Check is_template_specialization**: When analyzing templates, distinguish specializations from generics.

---

## Additional Resources

- **Implementation Plan**: `docs/proposals/IMPLEMENTATION_PLAN.md`
- **Integration Tests**: `tests/test_qualified_name_integration.py`
- **Performance Benchmarks**: `tests/test_qualified_name_performance.py`
- **Pattern Matching Tests**: `tests/test_qualified_search.py`
- **Original Proposal**: See implementation plan Phase 1-3 sections

---

## Questions?

If you encounter issues or have questions about qualified names support:

1. Check the troubleshooting section above
2. Review the test files for examples
3. Open an issue on GitHub with your use case

**Schema Version**: 10.1 (includes qualified names + template specialization support)
