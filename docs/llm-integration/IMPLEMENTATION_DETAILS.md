# Implementation Details for LLM Integration Enhancements

This document provides technical implementation details for the enhancements described in `LLM_INTEGRATION_STRATEGY.md`.

## Phase 1: Line Ranges Implementation

### 1.1 Update SymbolInfo Dataclass

**File:** `mcp_server/symbol_info.py`

**Changes:**
```python
@dataclass
class SymbolInfo:
    # Existing fields...
    line: int
    column: int

    # NEW: Line ranges for implementation
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    # NEW: Header declaration location (if separate from implementation)
    header_file: Optional[str] = None
    header_line: Optional[int] = None
    header_start_line: Optional[int] = None
    header_end_line: Optional[int] = None
```

### 1.2 Update SQLite Schema

**File:** `mcp_server/schema.sql`

**Changes:**
```sql
-- Update version
PRAGMA user_version = 5;  -- Increment from current version 4

-- Add new columns to symbols table
ALTER TABLE symbols ADD COLUMN start_line INTEGER;
ALTER TABLE symbols ADD COLUMN end_line INTEGER;
ALTER TABLE symbols ADD COLUMN header_file TEXT;
ALTER TABLE symbols ADD COLUMN header_line INTEGER;
ALTER TABLE symbols ADD COLUMN header_start_line INTEGER;
ALTER TABLE symbols ADD COLUMN header_end_line INTEGER;

-- Index for efficient range queries
CREATE INDEX IF NOT EXISTS idx_symbols_range ON symbols(file, start_line, end_line);
```

**Note:** Since we auto-recreate on version mismatch in dev mode, just increment version number and the database will rebuild automatically.

**File:** `mcp_server/sqlite_cache_backend.py`

**Changes:**
```python
# Update schema version constant
CURRENT_SCHEMA_VERSION = 5  # Was 4
```

### 1.3 Extract Line Ranges During Parsing

**File:** `mcp_server/cpp_analyzer.py`

**Function:** `_process_cursor(cursor, file_path, source_file_path)`

**Changes:**
```python
def _process_cursor(cursor, file_path, source_file_path):
    # Existing location extraction...
    location = cursor.location
    line = location.line
    column = location.column

    # NEW: Extract line ranges
    extent = cursor.extent
    start_line = extent.start.line if extent.start.file else line
    end_line = extent.end.line if extent.end.file else line

    # NEW: For declarations, check if definition exists elsewhere
    header_file = None
    header_line = None
    header_start_line = None
    header_end_line = None

    # If this is a declaration in a header, try to find definition
    definition_cursor = cursor.get_definition()
    if definition_cursor and definition_cursor != cursor:
        # This is a declaration, definition is elsewhere
        if cursor.location.file and cursor.location.file.name.endswith(('.h', '.hpp', '.hxx')):
            # Current cursor is in header (declaration)
            header_file = str(Path(cursor.location.file.name).resolve())
            header_line = cursor.location.line
            header_start_line = start_line
            header_end_line = end_line

            # Update main location to definition
            def_location = definition_cursor.location
            file_path = str(Path(def_location.file.name).resolve())
            line = def_location.line
            column = def_location.column

            def_extent = definition_cursor.extent
            start_line = def_extent.start.line if def_extent.start.file else line
            end_line = def_extent.end.line if def_extent.end.file else line

    # Create SymbolInfo with new fields
    info = SymbolInfo(
        name=cursor.spelling,
        qualified_name=get_qualified_name(cursor),
        kind=kind,
        file=file_path,
        line=line,
        column=column,
        start_line=start_line,         # NEW
        end_line=end_line,             # NEW
        header_file=header_file,       # NEW
        header_line=header_line,       # NEW
        header_start_line=header_start_line,  # NEW
        header_end_line=header_end_line,      # NEW
        # ... other fields
    )
```

### 1.4 Update Tool Outputs

**File:** `mcp_server/cpp_mcp_server.py`

**Tools to update:**
- `get_class_info`
- `get_function_info`
- `search_classes`
- `search_functions`
- All tools that return symbol information

**Example for `get_class_info`:**
```python
result = {
    "name": class_info.name,
    "qualified_name": class_info.qualified_name,
    "file": class_info.file,
    "line": class_info.line,
    "start_line": class_info.start_line,           # NEW
    "end_line": class_info.end_line,               # NEW
    "header_file": class_info.header_file,         # NEW
    "header_line": class_info.header_line,         # NEW
    "header_start_line": class_info.header_start_line,  # NEW
    "header_end_line": class_info.header_end_line,      # NEW
    # ... rest of fields
}
```

### 1.5 Add get_files_containing_symbol Tool

**File:** `mcp_server/cpp_mcp_server.py`

**Add to `list_tools()`:**
```python
{
    "name": "get_files_containing_symbol",
    "description": "Get list of all files that reference or use a symbol. "
                   "Useful for targeted code search with other MCP tools. "
                   "Returns only files, not specific locations.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "symbol_name": {
                "type": "string",
                "description": "Name of the symbol (class, function, etc.)"
            },
            "symbol_kind": {
                "type": "string",
                "enum": ["class", "function", "method"],
                "description": "Type of symbol (optional, for disambiguation)"
            },
            "project_only": {
                "type": "boolean",
                "default": True,
                "description": "Exclude system/dependency files"
            }
        },
        "required": ["symbol_name"]
    }
}
```

**Add to `call_tool()`:**
```python
elif name == "get_files_containing_symbol":
    symbol_name = arguments["symbol_name"]
    symbol_kind = arguments.get("symbol_kind")
    project_only = arguments.get("project_only", True)

    result = await analyzer.get_files_containing_symbol(
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
        project_only=project_only
    )

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
```

**File:** `mcp_server/cpp_analyzer.py`

**Add method:**
```python
async def get_files_containing_symbol(
    self,
    symbol_name: str,
    symbol_kind: Optional[str] = None,
    project_only: bool = True
) -> dict:
    """
    Get all files that contain references to a symbol.

    Combines:
    1. File where symbol is defined
    2. Files that call/use the symbol (from call graph)
    3. Files that reference the symbol (from symbol index)

    Returns:
        {
            "symbol": symbol_name,
            "kind": kind,
            "files": [list of file paths],
            "total_references": count
        }
    """
    await self._ensure_indexing_complete()

    files = set()
    total_refs = 0
    kind = None

    # 1. Find where symbol is defined
    if symbol_kind == "class" or not symbol_kind:
        for qname, info in self.class_index.items():
            if info.name == symbol_name:
                files.add(info.file)
                if info.header_file:
                    files.add(info.header_file)
                kind = "class"
                break

    if symbol_kind == "function" or not symbol_kind:
        for qname, info in self.function_index.items():
            if info.name == symbol_name:
                files.add(info.file)
                if info.header_file:
                    files.add(info.header_file)
                kind = "function"
                # Don't break - could be overloaded

    # 2. Find callers (from call graph)
    if kind == "function" or not kind:
        caller_functions = await self.find_callers(symbol_name)
        for caller in caller_functions.get("callers", []):
            files.add(caller["file"])
            total_refs += 1

    # 3. Find references via symbol search
    search_results = await self.search_engine.search_symbols(
        pattern=f"^{re.escape(symbol_name)}$",
        kind=symbol_kind,
        project_only=project_only
    )
    for result in search_results:
        files.add(result["file"])

    # Filter out dependency files if project_only
    if project_only:
        files = self._filter_project_files(files)

    return {
        "symbol": symbol_name,
        "kind": kind,
        "files": sorted(list(files)),
        "total_references": total_refs or len(search_results)
    }
```

## Phase 2: Documentation Extraction

### 2.1 Update SymbolInfo Dataclass

**File:** `mcp_server/symbol_info.py`

**Changes:**
```python
@dataclass
class SymbolInfo:
    # ... existing fields

    # NEW: Documentation
    brief: Optional[str] = None          # Brief description (first line)
    doc_comment: Optional[str] = None    # Full documentation comment
```

### 2.2 Update SQLite Schema

**File:** `mcp_server/schema.sql`

**Changes:**
```sql
-- Add documentation columns
ALTER TABLE symbols ADD COLUMN brief TEXT;
ALTER TABLE symbols ADD COLUMN doc_comment TEXT;

-- FTS5 index for documentation search (optional, for future features)
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_docs_fts USING fts5(
    qualified_name,
    brief,
    doc_comment,
    content=symbols,
    content_rowid=id
);
```

### 2.3 Extract Documentation During Parsing

**File:** `mcp_server/cpp_analyzer.py`

**Function:** `_process_cursor(cursor, file_path, source_file_path)`

**Changes:**
```python
def _process_cursor(cursor, file_path, source_file_path):
    # ... existing extraction code

    # NEW: Extract documentation
    brief = None
    doc_comment = None

    try:
        # Get brief comment (first line/sentence)
        brief_comment = cursor.brief_comment
        if brief_comment:
            brief = brief_comment.strip()

        # Get full raw comment (includes all comment text)
        raw_comment = cursor.raw_comment
        if raw_comment:
            doc_comment = raw_comment.strip()

            # If no brief but have raw, extract first line
            if not brief and doc_comment:
                lines = doc_comment.split('\n')
                for line in lines:
                    # Skip comment markers
                    cleaned = line.strip().lstrip('/*!/').strip()
                    if cleaned:
                        brief = cleaned
                        break
    except Exception as e:
        # Documentation extraction is best-effort
        self.logger.debug(f"Could not extract doc for {cursor.spelling}: {e}")

    info = SymbolInfo(
        # ... existing fields
        brief=brief,
        doc_comment=doc_comment,
    )
```

### 2.4 Include Documentation in Tool Outputs

Update all tool outputs to include `brief` and optionally `doc_comment` fields.

## Phase 3: Include Dependencies

### 3.1 Add get_file_includes Tool

**File:** `mcp_server/cpp_mcp_server.py`

**Tool definition:**
```python
{
    "name": "get_file_includes",
    "description": "Get all #include directives for a file. "
                   "Returns both project includes and system includes.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file (relative or absolute)"
            },
            "include_system": {
                "type": "boolean",
                "default": True,
                "description": "Include system headers (<...>)"
            },
            "transitive": {
                "type": "boolean",
                "default": False,
                "description": "Include transitive dependencies (headers included by included headers)"
            }
        },
        "required": ["file_path"]
    }
}
```

**Implementation approach:**

Option A: Store during indexing (space overhead)
- Extract includes via `translation_unit.get_includes()` during parsing
- Store in SQLite (new table: file_includes)
- Fast queries, but increases cache size

Option B: Compute on-demand (CPU overhead)
- Parse file when requested
- Use existing libclang infrastructure
- Slower queries, but no storage overhead

**Recommendation:** Option A (store during indexing) - includes are relatively small and very useful.

### 3.2 Schema for Include Storage

**File:** `mcp_server/schema.sql`

**New table:**
```sql
CREATE TABLE IF NOT EXISTS file_includes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    included_file TEXT NOT NULL,
    is_system BOOLEAN NOT NULL,
    line_number INTEGER,
    UNIQUE(source_file, included_file)
);

CREATE INDEX IF NOT EXISTS idx_file_includes_source ON file_includes(source_file);
CREATE INDEX IF NOT EXISTS idx_file_includes_included ON file_includes(included_file);
```

## Phase 4: Template and Type Details

### 4.1 Extract Template Parameters

**File:** `mcp_server/cpp_analyzer.py`

**Add to class processing:**
```python
def _process_class(cursor):
    # ... existing code

    # NEW: Extract template parameters
    template_params = []
    if cursor.kind == CursorKind.CLASS_TEMPLATE:
        # Iterate over template parameters
        for child in cursor.get_children():
            if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                param_name = child.spelling
                default = None
                # Check for default argument
                for token in child.get_tokens():
                    if token.spelling == '=':
                        # Default value follows
                        default = ''.join([t.spelling for t in child.get_tokens()
                                          if t.location.offset > token.location.offset])
                        break

                if default:
                    template_params.append(f"typename {param_name} = {default}")
                else:
                    template_params.append(f"typename {param_name}")
            elif child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                # Non-type parameter (e.g., int N)
                param_type = child.type.spelling
                param_name = child.spelling
                template_params.append(f"{param_type} {param_name}")

    # Add to SymbolInfo
    info.template_parameters = template_params if template_params else None
```

### 4.2 Extract Member Types

**Add to member extraction:**
```python
def _extract_member_info(cursor):
    return {
        "name": cursor.spelling,
        "type": cursor.type.spelling,  # NEW: Was missing
        "access": get_access_specifier(cursor),
        "is_static": cursor.is_static_method(),
        "is_mutable": cursor.is_mutable_field() if hasattr(cursor, 'is_mutable_field') else False
    }
```

## Testing Checklist

### Phase 1 Testing
- [ ] Line ranges extracted correctly for classes
- [ ] Line ranges extracted correctly for functions
- [ ] Header file locations tracked for split declarations
- [ ] get_files_containing_symbol returns all relevant files
- [ ] get_files_containing_symbol filters dependencies correctly
- [ ] Schema migration works (auto-recreate)
- [ ] Performance impact acceptable (<10% indexing slowdown)

### Phase 2 Testing
- [ ] Brief comments extracted from Doxygen-style comments
- [ ] Full doc comments stored
- [ ] Documentation included in search results
- [ ] Missing documentation handled gracefully (None/null)
- [ ] Special comment formats handled (///, //!, /*!, etc.)

### Phase 3 Testing
- [ ] get_file_includes returns all includes
- [ ] System includes filtered correctly
- [ ] Transitive includes computed correctly (if implemented)
- [ ] Include paths returned

### Phase 4 Testing
- [ ] Template parameters extracted for class templates
- [ ] Template parameters extracted for function templates
- [ ] Default template arguments captured
- [ ] Member types extracted correctly
- [ ] Complex types handled (nested templates, pointers, etc.)

## Performance Considerations

### Indexing Time Impact

**Estimated overhead per enhancement:**
- Line ranges: +5% (already have extent, just need to extract)
- Documentation: +10% (requires comment parsing)
- Includes: +15% (requires include traversal)
- Types: +5% (type info already available)

**Total estimated overhead:** 30-35% indexing time increase

**Mitigation:**
- Most overhead is one-time (during initial indexing)
- Incremental refresh not significantly affected
- Cache makes subsequent loads instant

### Storage Impact

**Estimated size increase:**
- Line ranges: +8 bytes per symbol (~10% increase)
- Documentation: +100-500 bytes per symbol (highly variable)
- Includes: +50 bytes per include (could be significant for large projects)
- Types: +50-100 bytes per symbol (~15% increase)

**Total estimated increase:** 40-80% cache size

**For typical project (10K symbols):**
- Current: ~5-10 MB
- With enhancements: ~7-18 MB

Still very manageable.

## Rollout Strategy

1. **Implement Phase 1** (line ranges + file lists)
2. **Test with real project** (e.g., nlohmann/json ~20K LOC)
3. **Measure impact** (indexing time, cache size, query performance)
4. **If successful, proceed to Phase 2**
5. **Iterate based on feedback**

## Compatibility

### Backward Compatibility
- Schema version increment triggers auto-recreate (dev mode)
- Old caches automatically invalidated
- No migration code needed

### Forward Compatibility
- All new fields optional (None/null allowed)
- Existing tools continue to work
- New tools are additive

## Future Optimizations

### Lazy Loading
- Store documentation separately, load on-demand
- Reduce memory footprint for large projects

### Compression
- Compress doc_comment field in SQLite
- Could reduce storage by 50-70% for documentation

### Caching Strategies
- Cache get_files_containing_symbol results
- TTL-based cache for frequently accessed data

### Parallel Extraction
- Extract documentation in parallel with symbol extraction
- Already using ProcessPoolExecutor, so architecture supports it
