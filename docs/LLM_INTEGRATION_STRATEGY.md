# LLM Integration Strategy for C++ MCP Server

## Overview

This document outlines the strategy for optimizing the C++ MCP server for LLM coding agents. The key insight is that we should focus on **C++ semantic analysis** (our unique capability) and provide **bridging data** that enables LLM agents to effectively orchestrate our tools with other specialized MCP servers.

## Core Philosophy: Semantic Core + Tool Ecosystem

```
┌─────────────────────────────────────────────────────┐
│              LLM Coding Agent (Claude)              │
└──────────────────────┬──────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
┌────────────────┐ ┌──────────┐ ┌──────────┐
│ cpp-analyzer   │ │filesystem│ │ ripgrep  │
│   (semantic)   │ │ (source) │ │ (search) │
└────────────────┘ └──────────┘ └──────────┘
         │
         │ Provides:
         │ • File paths
         │ • Line ranges
         │ • Symbol metadata
         │ • Relationships
         │
         └─────► Enables other tools to operate precisely
```

### Our Unique Responsibility

**What ONLY we can provide (via libclang AST parsing):**
- Symbol resolution (classes, functions, namespaces, templates)
- Type system understanding (C++ types, templates, type relationships)
- Inheritance hierarchies (base classes, derived classes, virtual methods)
- Call graphs (function caller/callee relationships)
- Overload resolution
- Namespace/scope resolution
- C++ attributes (const, static, virtual, pure virtual, constexpr)
- Compile semantics (using compile_commands.json)
- Cross-reference (USR-based symbol identity)

**What we should NOT reimplement:**
- Reading/writing source files → Use filesystem MCP servers
- Full-text search → Use ripgrep/grep MCP servers
- File system operations → Use filesystem MCP servers
- Git operations → Use git MCP servers
- General documentation rendering → Use web fetch servers

## Gap Analysis

### Current State

**What we extract and store:**
- ✅ Symbol metadata (name, qualified_name, kind)
- ✅ Location (file path, line number, column number)
- ✅ Function info (signature, return type)
- ✅ Class info (base classes, methods, members, access specifiers)
- ✅ Attributes (static, virtual, const, pure_virtual)
- ✅ Relationships (call graph, inheritance)
- ✅ USR (unique symbol identifiers)

**Critical missing information for LLM agents:**
- ❌ Line ranges (start_line, end_line) - only have single line number
- ❌ Files containing symbol references - can't narrow down search
- ❌ Documentation/comments - no docstrings or brief descriptions
- ❌ Header file locations - only have implementation file
- ❌ Member variable types - only have names
- ❌ Template parameters - incomplete type information
- ❌ Include dependencies - what headers a file needs

### Integration with Existing MCP Servers

#### 1. Filesystem Server (`@modelcontextprotocol/server-filesystem`)

**What it provides:**
- Read file contents
- Write/edit files
- List directories

**How we enable it:**
- ✅ Already provide: File paths
- ✅ Already provide: Line numbers
- ❌ Missing: Line ranges (start_line, end_line) for complete symbol definitions

**Ideal workflow:**
```
1. LLM: mcp__cpp-analyzer__get_class_info("Parser")
   → {file: "src/parser.cpp", start_line: 45, end_line: 120}

2. LLM: mcp__filesystem__read_file("src/parser.cpp",
                                   start_line=45, end_line=120)
   → Returns: exact class definition
```

#### 2. Ripgrep/Search Server (`@modelcontextprotocol/server-ripgrep`)

**What it provides:**
- Full-text regex search
- Context lines around matches
- Multiple file search

**How we enable it:**
- ✅ Already provide: File paths for known symbols
- ❌ Missing: List of files that reference a symbol (for targeted search)

**Ideal workflow:**
```
1. LLM: mcp__cpp-analyzer__get_files_containing_symbol("validate")
   → ["src/validator.cpp", "src/parser.cpp", "tests/test_validator.cpp"]

2. LLM: mcp__ripgrep__search(pattern="validate\\(",
                             files=["src/validator.cpp", ...])
   → Returns: usage sites with context (only 3 files instead of 10,000)
```

#### 3. Git Server

**What it provides:**
- Git blame
- File history
- Commit information

**How we enable it:**
- ✅ Already provide: File paths
- ✅ Works out of the box (no changes needed)

#### 4. Web/Documentation Servers

**What it provides:**
- Fetch external documentation
- API reference lookup

**How we enable it:**
- ❌ Missing: Documentation URLs from comments
- ❌ Missing: C++ standard library symbol → cppreference.com mapping

## Bridging Data Requirements

To enable effective LLM agent orchestration, we need to add the following "bridging data":

### Priority 1: Line Ranges (CRITICAL)

**Current:** Only return single line number (definition line)
**Need:** Return complete line ranges for symbol definitions

**Example enhancement:**
```json
{
  "name": "Parser",
  "file": "src/parser.cpp",
  "line": 45,                    // ✅ Already have
  "start_line": 45,              // 🔧 ADD
  "end_line": 120,               // 🔧 ADD
  "header_file": "include/parser.h",  // 🔧 ADD
  "header_line": 12,             // 🔧 ADD
  "header_start_line": 12,       // 🔧 ADD
  "header_end_line": 25          // 🔧 ADD
}
```

**Why critical:**
- Filesystem server can read precise byte ranges
- LLM knows exactly what to extract
- Enables efficient source code retrieval
- Reduces context window waste

**Implementation:**
- Available from libclang: `cursor.extent.start.line`, `cursor.extent.end.line`
- Add to `SymbolInfo` dataclass (mcp_server/symbol_info.py)
- Update SQLite schema (mcp_server/schema.sql)
- Update extraction logic (mcp_server/cpp_analyzer.py:_process_cursor)

**Affected tools:**
- `get_class_info`
- `get_function_info`
- `search_classes`
- `search_functions`
- All tools returning symbol information

### Priority 2: File Lists for Targeted Search (CRITICAL)

**New tool:** `get_files_containing_symbol`

**Purpose:** Return all files that reference/use a symbol (not just where it's defined)

**Signature:**
```python
get_files_containing_symbol(
    symbol_name: str,
    symbol_kind: Optional[str] = None,  # "class", "function", "method"
    project_only: bool = True
) -> list[str]
```

**Returns:**
```json
{
  "symbol": "validate",
  "files": [
    "src/validator.cpp",
    "src/parser.cpp",
    "tests/test_validator.cpp"
  ],
  "total_references": 47
}
```

**Why critical:**
- Narrow down search space for grep/search tools by 100-1000x
- LLM can do targeted full-text search instead of grepping entire codebase
- Performance: search 3 files instead of 10,000

**Implementation:**
- Use existing call graph data (already tracks references)
- Add file tracking during indexing
- Simple SQL query on existing data structure
- Low implementation cost, high value

### Priority 3: Documentation Extraction (HIGH)

**Enhance existing tools** to include brief documentation

**Example enhancement:**
```json
{
  "name": "Parser::parse",
  "signature": "bool parse(const std::string& input)",
  "brief": "Parses input string and builds AST",              // 🔧 ADD
  "doc_comment": "/// Parses input string and builds AST\n/// @param input The source code to parse\n/// @return true on success"  // 🔧 ADD
}
```

**Why valuable:**
- LLM understands purpose without reading full source
- Can answer many questions from metadata alone
- Reduces need for filesystem access
- Improves search result relevance

**Implementation:**
- libclang provides: `cursor.brief_comment`, `cursor.raw_comment`
- Extract during `_process_cursor()`
- Store in SQLite (add columns: brief TEXT, doc_comment TEXT)
- Include in search results and info queries

**Affected tools:**
- All tools returning symbol information
- Especially valuable for search results

### Priority 4: Include/Dependency Information (MEDIUM)

**New tool:** `get_file_includes`

**Purpose:** Show what headers a file includes (direct and transitive)

**Signature:**
```python
get_file_includes(
    file_path: str,
    include_system: bool = True,
    transitive: bool = False
) -> dict
```

**Returns:**
```json
{
  "file": "src/parser.cpp",
  "direct_includes": [
    "parser.h",
    "ast.h",
    "lexer.h"
  ],
  "system_includes": [
    "<vector>",
    "<string>",
    "<memory>"
  ],
  "include_paths": [
    "/usr/include",
    "/usr/local/include",
    "include/"
  ]
}
```

**Why useful:**
- Filesystem server knows which files to read for dependencies
- Understanding module boundaries
- Resolving missing includes
- Dependency analysis

**Implementation:**
- libclang provides: `translation_unit.get_includes()`
- HeaderTracker already has this data (could expose it)
- Relatively easy to add

### Priority 5: Template and Type Details (MEDIUM)

**Enhance `get_class_info` and `get_function_info`:**

**Example enhancement:**
```json
{
  "name": "SmartPointer",
  "template_parameters": [                           // 🔧 ADD
    "typename T",
    "typename Deleter = std::default_delete<T>"
  ],
  "members": [
    {
      "name": "ptr_",
      "type": "T*",                                  // 🔧 ADD (currently only name)
      "access": "private"
    },
    {
      "name": "deleter_",
      "type": "Deleter",                             // 🔧 ADD
      "access": "private"
    }
  ]
}
```

**Why useful:**
- Understanding template instantiations
- Type-based queries
- Complete class understanding
- Better code generation

**Implementation:**
- libclang provides: `cursor.get_template_kind()`, `cursor.type`
- Parse member types from `cursor.type.spelling`
- Template parameters from specialized cursor methods
- Moderate implementation complexity

### Priority 6: Standard Library Mapping (LOW, nice-to-have)

**New tool:** `get_stdlib_reference`

**Purpose:** Map C++ standard library symbols to cppreference.com URLs

**Signature:**
```python
get_stdlib_reference(symbol_name: str) -> Optional[dict]
```

**Returns:**
```json
{
  "symbol": "std::vector",
  "is_stdlib": true,
  "cppreference_url": "https://en.cppreference.com/w/cpp/container/vector",
  "header": "<vector>",
  "since": "C++98",
  "brief": "Dynamic contiguous array"
}
```

**Why useful:**
- Link to authoritative documentation
- Web fetch servers can retrieve official docs
- Better than trying to extract stdlib info from system headers

**Implementation:**
- Maintain static mapping (JSON file) of stdlib symbols → metadata
- ~500-1000 most common symbols would cover 95% of usage
- Detect stdlib symbols during indexing (namespace starts with "std::")
- Low maintenance burden

## Implementation Plan

### Phase 1: Critical Bridging Data (Implement First)

**Goal:** Enable filesystem server to retrieve exact code ranges

**Tasks:**
1. Add line range fields to SymbolInfo dataclass
   - `start_line`, `end_line` for implementation
   - `header_file`, `header_start_line`, `header_end_line` for declarations
2. Update SQLite schema (increment version, auto-recreate in dev mode)
   - Add columns: start_line, end_line, header_file, header_start_line, header_end_line
3. Extract line ranges during parsing
   - Use `cursor.extent.start.line`, `cursor.extent.end.line`
   - Track both declaration and definition locations
4. Update all tool outputs to include line ranges
5. Add `get_files_containing_symbol` tool
   - Query call graph and reference data
   - Return list of files

**Estimated effort:** 1-2 days
**Impact:** HIGH - Unlocks efficient filesystem integration

### Phase 2: Documentation Extraction (Implement Second)

**Goal:** LLM can understand symbol purpose without reading source

**Tasks:**
1. Extract brief comments and full doc comments
   - Use `cursor.brief_comment`, `cursor.raw_comment`
2. Update SQLite schema
   - Add columns: brief TEXT, doc_comment TEXT
3. Update tool outputs to include documentation
4. Enhance search results with brief descriptions

**Estimated effort:** 1 day
**Impact:** MEDIUM-HIGH - Reduces filesystem access, improves search

### Phase 3: Dependencies (Implement Third)

**Goal:** Expose include/dependency information

**Tasks:**
1. Add `get_file_includes` tool
2. Expose HeaderTracker data via MCP
3. Extract include information during parsing
4. Store or compute on-demand (TBD based on performance)

**Estimated effort:** 1-2 days
**Impact:** MEDIUM - Better project structure understanding

### Phase 4: Type Details (Optional Enhancement)

**Goal:** More complete C++ type information

**Tasks:**
1. Extract template parameters
2. Extract member variable types
3. Enhanced type queries
4. Update schema and tool outputs

**Estimated effort:** 2-3 days
**Impact:** MEDIUM - More complete C++ understanding

### Phase 5: External Integration (Nice-to-have)

**Goal:** Connect to external documentation

**Tasks:**
1. Create stdlib symbol mapping (JSON file)
2. Add `get_stdlib_reference` tool
3. Detect stdlib symbols during indexing
4. Optional: Extract doc URLs from comments

**Estimated effort:** 1 day
**Impact:** LOW-MEDIUM - Convenience feature

## Example: Complete LLM Workflow

**User task:** "Show me the HttpRequest class and explain how to use it"

**LLM orchestration with enhanced tools:**

```python
# Step 1: Get semantic info from cpp-analyzer (with bridging data)
class_info = mcp__cpp_analyzer__get_class_info("HttpRequest")

# Returns:
{
  "name": "HttpRequest",
  "qualified_name": "network::HttpRequest",
  "file": "src/network/request.cpp",
  "start_line": 23,              # 🔧 NEW
  "end_line": 87,                # 🔧 NEW
  "header_file": "include/network/request.h",  # 🔧 NEW
  "header_start_line": 15,       # 🔧 NEW
  "header_end_line": 45,         # 🔧 NEW
  "brief": "Represents an HTTP request with headers and body",  # 🔧 NEW
  "base_classes": ["network::Request"],
  "methods": [
    {
      "name": "send",
      "start_line": 50,          # 🔧 NEW
      "end_line": 57,            # 🔧 NEW
      "signature": "bool send(const std::string& url)",
      "brief": "Sends the HTTP request to specified URL"  # 🔧 NEW
    }
  ],
  "members": [
    {
      "name": "url_",
      "type": "std::string",     # 🔧 NEW
      "access": "private"
    }
  ]
}

# Step 2: Read header file (interface) from filesystem with exact range
header_code = mcp__filesystem__read_file(
    path=class_info["header_file"],
    start_line=class_info["header_start_line"],
    end_line=class_info["header_end_line"]
)

# Step 3: Find usage examples with targeted ripgrep
usage_files = mcp__cpp_analyzer__get_files_containing_symbol(
    symbol_name="HttpRequest",
    symbol_kind="class"
)
# Returns: ["src/client.cpp", "tests/test_http.cpp", "examples/simple.cpp"]

# Step 4: Search for usage patterns in only those 3 files
examples = mcp__ripgrep__search(
    pattern="HttpRequest.*send",
    files=usage_files,
    context_lines=5
)

# Step 5: Present comprehensive answer to user
"""
The HttpRequest class represents an HTTP request with headers and body.

Class definition (from include/network/request.h:15-45):
[Shows exact header_code]

It inherits from network::Request and provides these key methods:
- send(url): Sends the HTTP request to specified URL

Here are usage examples from the codebase:

Example 1 (from src/client.cpp):
[Shows example with context from ripgrep]

Example 2 (from examples/simple.cpp):
[Shows example with context from ripgrep]
"""
```

**Key improvements with bridging data:**
- ✅ Exact line ranges → No wasted context reading entire files
- ✅ File lists → Ripgrep searches 3 files instead of 10,000 (1000x faster)
- ✅ Brief descriptions → LLM understands purpose immediately
- ✅ Member types → Complete class understanding
- ✅ Targeted search → Precise results without manual parsing

**Without bridging data (current state):**
- ❌ Would need to read entire src/network/request.cpp (~1000 lines)
- ❌ Would need to grep entire codebase (10,000+ files)
- ❌ Would need to manually find class boundaries
- ❌ No immediate understanding of class purpose
- ❌ Missing member type information

## Testing Strategy

### Phase 1: Manual Testing
1. Configure cpp-analyzer MCP server in Claude Desktop
2. Index a test project (e.g., spdlog, nlohmann/json)
3. Test realistic LLM workflows:
   - "Show me the Parser class"
   - "Where is validate() called?"
   - "Help me understand how to use AsyncLogger"
   - "Find all places that need updating if I change this API"
4. Document: What works? What's missing? What's awkward?

### Phase 2: Integration Testing
1. Add filesystem MCP server to Claude Desktop
2. Test combined workflows
3. Measure effectiveness improvement
4. Identify remaining gaps

### Phase 3: Performance Testing
1. Large codebases (100K+ LOC)
2. Time to first result
3. Context window usage
4. Query response times

## Success Metrics

**Quantitative:**
- Filesystem reads: Target <10 file reads for typical "explain class" query
- Search scope: Target <1% of files searched (vs 100% with blind grep)
- Context efficiency: Target 90% reduction in irrelevant context
- Query latency: Target <100ms for metadata queries

**Qualitative:**
- LLM can answer "explain this class" without reading source
- LLM can find usage examples efficiently
- LLM can perform impact analysis
- LLM can assist with refactoring tasks

## Open Questions

1. **Line ranges for header-only classes:** Should we treat header and implementation as same range?
2. **Transitive dependencies:** Do we need to track transitive includes?
3. **Performance:** Will adding documentation storage significantly increase cache size?
4. **Stdlib detection:** Should we auto-detect stdlib symbols or require explicit configuration?
5. **Hot reload:** Should we support MCP server hot-reload during development?

## Future Considerations

### Advanced Features (Beyond Initial Scope)
- Code smell detection (long functions, high coupling)
- Refactoring suggestions
- Dead code detection
- Semantic diff (beyond line-based diff)
- Cross-project symbol lookup
- ABI compatibility analysis

### Integration with Other Ecosystems
- CMake integration (target dependencies)
- Build system integration (Bazel, Meson)
- IDE integration (LSP-like features)
- CI/CD integration (PR analysis)

## Conclusion

By focusing on **C++ semantic analysis** and providing **precise bridging data**, we enable LLM agents to effectively orchestrate multiple MCP servers. This composable architecture allows each tool to do what it does best:

- **cpp-analyzer:** C++ semantics, relationships, type system
- **filesystem:** Source code reading/writing
- **ripgrep:** Full-text search with context
- **git:** Version control operations
- **web:** External documentation

The critical missing pieces are **line ranges** and **file lists**, which unlock efficient integration with other tools. Documentation extraction and type details provide further refinement.

**Recommended next action:** Implement Phase 1 (line ranges + get_files_containing_symbol) and test with a real-world C++ project.
