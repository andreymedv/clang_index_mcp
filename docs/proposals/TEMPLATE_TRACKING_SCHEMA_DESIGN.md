# Template Tracking Schema Design

**Status:** Design Complete
**Version:** 1.0
**Date:** 2026-01-16
**Related Tasks:** Task 2.1 (Design Schema Changes)

## Overview

This document defines the schema changes required to support template tracking in the C++ analyzer. The design adds fields to track:
- Whether a symbol is a template
- What kind of template it is
- Template parameters (for generic templates)
- Links to primary templates (for specializations)

## Schema Changes

### Version Bump

**Current:** 12.0
**New:** 13.0

Auto-recreation strategy: Schema version mismatch triggers automatic cache recreation (existing behavior).

### New Fields for `symbols` Table

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `is_template` | BOOLEAN | 0 | True for any template-related symbol |
| `template_kind` | TEXT | NULL | Type: 'class_template', 'function_template', 'partial_specialization', 'full_specialization' |
| `template_parameters` | TEXT | NULL | JSON array of template parameters (for generic templates) |
| `primary_template_usr` | TEXT | NULL | USR of primary template (for specializations) |

### Field Details

#### `is_template` (BOOLEAN)

Simple flag for quick filtering:
- `0` (False) - Not a template
- `1` (True) - Template or specialization

```sql
-- Query: Find all template-related symbols
SELECT * FROM symbols WHERE is_template = 1;
```

#### `template_kind` (TEXT)

Distinguishes between template types:

| Value | Description | Cursor Kind |
|-------|-------------|-------------|
| `'class_template'` | Generic class template | `CLASS_TEMPLATE` |
| `'function_template'` | Generic function template | `FUNCTION_TEMPLATE` |
| `'partial_specialization'` | Partial class template specialization | `CLASS_TEMPLATE_PARTIAL_SPECIALIZATION` |
| `'full_specialization'` | Explicit full specialization | `CLASS_DECL` or `FUNCTION_DECL` with template args |
| `NULL` | Not a template | Regular `CLASS_DECL`, `FUNCTION_DECL` |

```sql
-- Query: Find all generic class templates
SELECT * FROM symbols WHERE template_kind = 'class_template';

-- Query: Find all specializations
SELECT * FROM symbols WHERE template_kind IN ('partial_specialization', 'full_specialization');
```

#### `template_parameters` (TEXT, JSON)

JSON array of template parameters for **generic templates only**.

**Format:**
```json
[
  {"name": "T", "kind": "type"},
  {"name": "N", "kind": "non_type", "type": "int"},
  {"name": "Container", "kind": "template"}
]
```

**Parameter kinds:**
- `"type"` - Type parameter (`typename T`, `class T`)
- `"non_type"` - Non-type parameter (`int N`, `size_t Size`)
- `"template"` - Template template parameter (`template<typename> class Container`)

**Examples:**

| Template | `template_parameters` JSON |
|----------|---------------------------|
| `template<typename T>` | `[{"name": "T", "kind": "type"}]` |
| `template<typename K, typename V>` | `[{"name": "K", "kind": "type"}, {"name": "V", "kind": "type"}]` |
| `template<typename T, int N>` | `[{"name": "T", "kind": "type"}, {"name": "N", "kind": "non_type", "type": "int"}]` |
| `template<typename... Args>` | `[{"name": "Args", "kind": "type"}]` |
| Non-template | `NULL` |
| Specialization | `NULL` |

**Note:** Variadic templates (`Args...`) appear as a single parameter. Detecting variadic status requires additional libclang analysis (deferred to future work).

#### `primary_template_usr` (TEXT)

Links specializations to their primary template via USR.

| Symbol Type | `primary_template_usr` |
|-------------|------------------------|
| Generic template | `NULL` |
| Partial specialization | USR of generic template |
| Full specialization | USR of generic template |
| Non-template | `NULL` |

**USR Pattern Matching:**

Since Python bindings don't expose `specialized_cursor_template`, we derive the primary template USR from USR patterns:

| Pattern | Meaning | Example |
|---------|---------|---------|
| `c:@ST>...@Name` | Class template | `c:@ST>1#T@Container` |
| `c:@FT@>...Name` | Function template | `c:@FT@>1#Tmax#t0.0#S0_#S0_#` |
| `c:@S@Name>#...` | Class specialization | `c:@S@Container>#I` |
| `c:@SP>...@Name>#...` | Partial specialization | `c:@SP>1#T@Container>#*t0.0` |
| `c:@F@Name<#...` | Function specialization | `c:@F@max<#*I>#S0_#S0_#` |

**Linking Algorithm:**
1. For a specialization USR `c:@S@Container>#I`:
   - Extract base name: `Container`
   - Search for class template: `c:@ST>...@Container`
   - Set `primary_template_usr` to found USR

### Indexes

```sql
-- Index for is_template filtering
CREATE INDEX IF NOT EXISTS idx_symbol_is_template ON symbols(is_template);

-- Index for template_kind queries
CREATE INDEX IF NOT EXISTS idx_symbol_template_kind ON symbols(template_kind);

-- Index for primary template lookups (finding all specializations)
CREATE INDEX IF NOT EXISTS idx_symbol_primary_template ON symbols(primary_template_usr);

-- Composite index for common query: find template + its specializations
CREATE INDEX IF NOT EXISTS idx_template_name_kind ON symbols(name, template_kind);
```

### SQL Schema Addition

```sql
-- Changelog v13.0: Added template tracking fields (Template Search Support)

-- Add new columns to symbols table
ALTER TABLE symbols ADD COLUMN is_template BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE symbols ADD COLUMN template_kind TEXT DEFAULT NULL;
ALTER TABLE symbols ADD COLUMN template_parameters TEXT DEFAULT NULL;
ALTER TABLE symbols ADD COLUMN primary_template_usr TEXT DEFAULT NULL;

-- Indexes for template queries
CREATE INDEX IF NOT EXISTS idx_symbol_is_template ON symbols(is_template);
CREATE INDEX IF NOT EXISTS idx_symbol_template_kind ON symbols(template_kind);
CREATE INDEX IF NOT EXISTS idx_symbol_primary_template ON symbols(primary_template_usr);
CREATE INDEX IF NOT EXISTS idx_template_name_kind ON symbols(name, template_kind);
```

## SymbolInfo Dataclass Changes

```python
@dataclass
class SymbolInfo:
    # ... existing fields ...

    # Template tracking (Template Search Support)
    is_template: bool = False  # True for templates and specializations
    template_kind: Optional[str] = None  # 'class_template', 'function_template', etc.
    template_parameters: Optional[str] = None  # JSON array for generic templates
    primary_template_usr: Optional[str] = None  # USR of primary template for specializations
```

## Query Examples

### Find All Specializations of a Template

```sql
-- Given primary template USR 'c:@ST>1#T@Container'
SELECT * FROM symbols
WHERE primary_template_usr = 'c:@ST>1#T@Container';
```

### Find Template and All Related Symbols by Name

```sql
SELECT * FROM symbols
WHERE name = 'Container'
  AND (is_template = 1 OR template_kind IS NOT NULL)
ORDER BY template_kind;
```

### Find All Generic Class Templates

```sql
SELECT name, qualified_name, template_parameters
FROM symbols
WHERE template_kind = 'class_template';
```

### Find Classes Derived from Any Specialization

```sql
-- Find all symbols with base_classes containing 'Container'
SELECT * FROM symbols
WHERE base_classes LIKE '%Container%'
  AND kind = 'class';
```

## Relationship to Existing Fields

| Existing Field | Relationship |
|----------------|--------------|
| `is_template_specialization` | Subset of `is_template` (only explicit specializations) |
| `kind` | Extended: 'class' → may be 'class_template' in `template_kind` |

**Note:** `is_template_specialization` remains for backward compatibility. New code should use `template_kind = 'full_specialization'`.

## Migration Considerations

1. **Automatic recreation:** Schema version 13.0 triggers cache recreation
2. **Backward compatibility:** All new fields have defaults (0, NULL)
3. **Incremental adoption:** Implementation tasks can add fields incrementally
4. **No data migration needed:** Full re-index populates new fields

## Future Extensions (Deferred)

These are tracked separately and not included in v13.0:

- **`specialization_args`**: JSON array of template arguments for specializations (Task 3.5, optional)
- **`is_variadic`**: Boolean for variadic templates (`typename... Args`)
- **Template constraints**: C++20 concepts support
- **Default template arguments**: Track defaults for optional parameters

## Implementation Order

1. **Task 2.2:** Add columns to schema.sql, bump version to 13.0
2. **Task 3.1:** Implement `is_template` flag extraction
3. **Task 3.2:** Implement `template_parameters` extraction
4. **Task 3.3:** Implement `template_kind` detection
5. **Task 3.4:** Implement `primary_template_usr` linking

## Validation Criteria

After implementation:

```python
# Generic class template
assert symbol.is_template == True
assert symbol.template_kind == 'class_template'
assert json.loads(symbol.template_parameters) == [{"name": "T", "kind": "type"}]
assert symbol.primary_template_usr is None

# Full specialization
assert symbol.is_template == True
assert symbol.template_kind == 'full_specialization'
assert symbol.template_parameters is None
assert symbol.primary_template_usr == 'c:@ST>1#T@Container'

# Partial specialization
assert symbol.is_template == True
assert symbol.template_kind == 'partial_specialization'
assert json.loads(symbol.template_parameters) == [{"name": "T", "kind": "type"}]
assert symbol.primary_template_usr == 'c:@ST>1#T@Container'

# Non-template class
assert symbol.is_template == False
assert symbol.template_kind is None
assert symbol.template_parameters is None
assert symbol.primary_template_usr is None
```
