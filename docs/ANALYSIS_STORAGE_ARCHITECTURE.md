# MCP Server Analysis Storage Architecture

> **Note**: This document describes the analysis storage architecture. The current implementation uses **SQLite exclusively** for cache storage. Legacy JSON cache sections (1-10) are retained for historical reference only. For current architecture details, see [Section 11: SQLite Cache Backend Architecture](#sqlite-cache-backend-architecture-v300).

## Table of Contents
1. [Overview](#overview)
2. [SQLite Cache Backend Architecture](#sqlite-cache-backend-architecture-v300) ⭐ **Current Implementation**
3. [Legacy Architecture](#legacy-architecture-historical) (Historical reference)

---

## Overview

The MCP (Model Context Protocol) server for C++ code analysis uses a high-performance SQLite storage system:
- **In-memory indexes** for fast queries
- **SQLite database** for persistent cache across sessions
- **FTS5 full-text search** for lightning-fast symbol lookup
- **WAL mode** for concurrent multi-process access
- **Project-isolated storage** to support multiple codebases

**Current Storage Backend**: SQLite (v3.0.0+)
**Performance**: 2-5ms symbol searches, 70% smaller disk usage, multi-process safe

For detailed SQLite architecture, **jump to [Section 11: SQLite Cache Backend Architecture](#sqlite-cache-backend-architecture-v300)**.

---

## Legacy Architecture (Historical)

> **⚠️ Historical Reference Only**: The following sections (1-10) describe the legacy JSON cache architecture. This approach is no longer supported. They are retained for historical context and understanding the evolution of the system.

### Storage Mechanism

### In-Memory Data Structures

The system maintains four primary indexes in memory, defined in `CppAnalyzer` class:

**Location**: `mcp_server/cpp_analyzer.py:54-59`

```python
self.class_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
self.function_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
self.file_index: Dict[str, List[SymbolInfo]] = defaultdict(list)
self.usr_index: Dict[str, SymbolInfo] = {}  # USR to symbol mapping
```

#### Index Descriptions:

1. **`class_index`**: Maps class/struct names to their SymbolInfo objects
   - Key: Class name (string)
   - Value: List of SymbolInfo (handles overloading/multiple definitions)

2. **`function_index`**: Maps function/method names to their SymbolInfo objects
   - Key: Function name (string)
   - Value: List of SymbolInfo

3. **`file_index`**: Maps file paths to all symbols defined in that file
   - Key: File path (string)
   - Value: List of SymbolInfo

4. **`usr_index`**: Maps Unified Symbol Resolution IDs to unique symbols
   - Key: USR (unique identifier from libclang)
   - Value: Single SymbolInfo

### SymbolInfo Structure

**Location**: `mcp_server/symbol_info.py:8-42`

Each analyzed symbol is represented by a `SymbolInfo` object containing:

```python
@dataclass
class SymbolInfo:
    name: str                    # Symbol name
    kind: str                    # "class", "struct", "function", "method"
    file: str                    # Source file path
    line: int                    # Line number
    column: int                  # Column number
    signature: str               # Function signature (for functions/methods)
    is_project: bool = True      # True for project code, False for dependencies
    parent_class: str = ""       # For methods: parent class name
    base_classes: List[str] = field(default_factory=list)  # Inheritance chain
    usr: str = ""                # Unified Symbol Resolution (unique ID)
    calls: List[str] = field(default_factory=list)         # USRs of called functions
    called_by: List[str] = field(default_factory=list)     # USRs of callers
```

### File-Based Cache

The system implements a **two-level caching strategy**:

#### 1. Global Cache (`cache_info.json`)
Stores the entire project index including:
- All class_index entries
- All function_index entries
- File hashes for freshness checking
- Metadata (version, settings, indexed file count)

**Location**: `mcp_server/cache_manager.py:41-77` (`save_cache()` method)

#### 2. Per-File Cache (`files/{hash}.json`)
Stores symbols for individual files:
- File path
- Content hash (MD5)
- Last modification timestamp
- List of symbols defined in the file

**Location**: `mcp_server/cache_manager.py:114-140` (`save_file_cache()` method)

---

## Storage Location

### Cache Directory Structure

**Base Location**: `.mcp_cache/` (relative to MCP server root directory)

**Full Structure**:
```
.mcp_cache/
└── {project_name}_{project_hash}/
    ├── cache_info.json              # Global project index
    ├── indexing_progress.json       # Progress tracking metadata
    └── files/
        ├── {file_hash_1}.json       # Per-file symbol cache
        ├── {file_hash_2}.json
        └── ...
```

### Path Resolution Logic

**Location**: `mcp_server/cache_manager.py:22-31`

```python
def _get_cache_dir(self) -> Path:
    """Get cache directory for this project"""
    # Use the MCP server directory for cache, not the project being analyzed
    mcp_server_root = Path(__file__).parent.parent  # Go up from mcp_server/cache_manager.py to root
    cache_base = mcp_server_root / ".mcp_cache"

    # Create unique cache dir based on project path hash
    project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:8]
    cache_dir = cache_base / f"{self.project_root.name}_{project_hash}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
```

### Example

For a project located at `/home/user/my_cpp_project`:
- **Project name**: `my_cpp_project`
- **Path hash**: `a1b2c3d4` (first 8 chars of MD5)
- **Cache directory**: `/home/user/clang_index_mcp/.mcp_cache/my_cpp_project_a1b2c3d4/`

### Storage Location Properties

1. **Predefined Base**: `.mcp_cache/` is hardcoded relative to MCP server installation
2. **Project-Specific Subdirectories**: Each project gets its own subdirectory
3. **Path-Based Hashing**: MD5 hash ensures unique directories for projects with same name
4. **Automatic Creation**: Directories are created automatically on first use

---

## Responsible Classes and Methods

### CacheManager Class
**File**: `mcp_server/cache_manager.py`

Primary responsibility: Persist and restore analysis results to/from disk

#### Storage Operations

##### 1. `save_cache()` (lines 41-77)
**Purpose**: Save the complete project index to disk

**Stores**:
- `class_index`: All class/struct definitions
- `function_index`: All function/method definitions
- `file_hashes`: MD5 hashes for each indexed file
- `indexed_file_count`: Total number of files processed
- `version`: Cache format version ("2.0")
- `index_dependencies`: Configuration flag

**Process**:
```python
cache_data = {
    "version": "2.0",
    "indexed_file_count": self.analyzer.indexed_file_count,
    "index_dependencies": self.analyzer.index_dependencies,
    "file_hashes": self.analyzer.file_hashes,
    "class_index": {
        name: [s.to_dict() for s in symbols]
        for name, symbols in self.analyzer.class_index.items()
    },
    "function_index": {
        name: [s.to_dict() for s in symbols]
        for name, symbols in self.analyzer.function_index.items()
    }
}
```

##### 2. `save_file_cache()` (lines 114-140)
**Purpose**: Save symbols for a single file

**Location**: `.mcp_cache/{project}/files/{MD5(file_path)}.json`

**Stores**:
- `file_path`: Absolute path to the source file
- `file_hash`: MD5 hash of file contents
- `timestamp`: When the cache was created
- `symbols`: List of SymbolInfo objects as dictionaries

**Cache Key Generation** (line 121):
```python
file_hash = hashlib.md5(file_path.encode()).hexdigest()
cache_file = self.cache_dir / "files" / f"{file_hash}.json"
```

##### 3. `save_progress()` (lines 177-200)
**Purpose**: Save indexing progress for resumability

**File**: `indexing_progress.json`

**Stores**:
- `total_files`: Number of files to index
- `indexed_files`: Number of files completed
- `last_updated`: Timestamp
- `status`: "in_progress" or "completed"

#### Load Operations

##### 4. `load_cache()` (lines 79-106)
**Purpose**: Restore the complete project index from disk

**Validation**:
- Checks cache version compatibility
- Verifies `index_dependencies` setting matches
- Returns `None` if validation fails (triggers full re-index)

**Restores**:
- All indexes (class_index, function_index)
- File hashes for freshness tracking
- Indexed file count

##### 5. `load_file_cache()` (lines 142-164)
**Purpose**: Load cached symbols for a specific file

**Validation**:
- Compares stored `file_hash` with current file hash
- Returns `None` if hash mismatch (file was modified)

**Returns**: List of SymbolInfo objects or None

#### Delete Operations

##### 6. `remove_file_cache()` (lines 166-175)
**Purpose**: Delete per-file cache when file is removed or invalidated

**Called by**: `CppAnalyzer._remove_file_from_indexes()`

**Process**:
```python
file_hash = hashlib.md5(file_path.encode()).hexdigest()
cache_file = self.cache_dir / "files" / f"{file_hash}.json"
if cache_file.exists():
    cache_file.unlink()
```

---

### CppAnalyzer Class
**File**: `mcp_server/cpp_analyzer.py`

Primary responsibility: Analyze source code and maintain indexes

#### Core Indexing Operations

##### 1. `index_project()` (lines 398-524)
**Purpose**: Index entire project (main entry point)

**Process**:
1. Initialize structures (line 406)
2. Load global cache if available (line 406)
3. Discover C++ files via FileScanner (line 415)
4. Process files in parallel using ThreadPoolExecutor (line 438)
5. Build call graph (line 512)
6. Save cache and progress (lines 521-522)

**Thread Safety**: Uses `max_workers` threads (configurable, default 4)

##### 2. `index_file()` (lines 254-396)
**Purpose**: Index a single source file

**Flow**:
```
Calculate file hash (line 262)
    ↓
Check per-file cache (line 266)
    ↓
If cache valid → Load from cache (lines 268-302)
    ↓
If cache miss → Parse with libclang (line 329)
    ↓
Process AST via _process_cursor() (line 363)
    ↓
Update all indexes (lines 344-357)
    ↓
Save per-file cache (line 384)
```

**Cache Hit Optimization** (lines 268-302):
- Loads pre-analyzed symbols from disk
- Updates in-memory indexes directly
- Skips expensive libclang parsing
- ~100x faster than re-parsing

##### 3. `_process_cursor()` (lines 161-252)
**Purpose**: Recursively process libclang AST nodes

**Detects**:
- Classes and structs (line 171)
- Functions and methods (line 204)
- Function calls (line 248)
- Inheritance relationships (line 178)

**Thread-Safe Updates** (lines 188-196, 225-233):
```python
with self.index_lock:
    self.class_index[symbol.name].append(symbol)
    self.usr_index[symbol.usr] = symbol
    self.file_index[symbol.file].append(symbol)
```

##### 4. `refresh_if_needed()` (lines 652-708)
**Purpose**: Incremental update of modified/new/deleted files

**Detection**:
- **Deleted files** (line 668): Files in cache but not on disk
- **Modified files** (line 687): Files with hash mismatch
- **New files** (line 696): Files on disk but not in cache

**Actions**:
- Remove deleted files from indexes (line 673)
- Re-index modified files (line 691)
- Index new files (line 700)

##### 5. `_remove_file_from_indexes()` (lines 710-749)
**Purpose**: Remove all symbols from a deleted file

**Updates**:
- `class_index`: Remove symbols from this file
- `function_index`: Remove symbols from this file
- `file_index`: Delete file entry entirely
- `usr_index`: Remove USRs for deleted symbols
- `call_graph_analyzer`: Remove call relationships
- `file_hashes`: Remove hash entry

**Thread Safety**: Uses `self.index_lock` (line 719)

---

### SearchEngine Class
**File**: `mcp_server/search_engine.py`

Primary responsibility: Query and retrieve analysis results

#### Query Operations

##### 1. `search_classes()` (lines 21-39)
**Purpose**: Find classes matching a pattern

**Parameters**:
- `pattern`: Regex pattern for class name
- `project_only`: Filter to project code only (exclude dependencies)

**Returns**: List of matching SymbolInfo objects

**Implementation**:
```python
results = []
for name, symbols in self.analyzer.class_index.items():
    if re.search(pattern, name, re.IGNORECASE):
        for symbol in symbols:
            if not project_only or symbol.is_project:
                results.append(symbol)
```

##### 2. `search_functions()` (lines 41-65)
**Purpose**: Find functions/methods matching criteria

**Parameters**:
- `pattern`: Regex pattern for function name
- `class_name`: Filter to specific class (optional)
- `project_only`: Filter to project code only

**Special Handling**:
- Can search within specific class (line 49)
- Supports method lookup via `parent_class` attribute

##### 3. `get_class_info()` (lines 88-117)
**Purpose**: Get detailed information about a specific class

**Returns**:
- Class definition location
- All methods in the class
- Base classes (inheritance)
- Derived classes (classes that inherit from this one)

**Method Lookup** (line 99):
```python
methods = [
    s for s in self.analyzer.function_index.get(name, [])
    if s.parent_class == class_name
]
```

##### 4. `get_symbols_in_file()` (lines 84-86)
**Purpose**: Get all symbols defined in a specific file

**Direct Access**:
```python
return self.analyzer.file_index.get(file_path, [])
```

---

### CompileCommandsManager Class
**File**: `mcp_server/compile_commands_manager.py`

**Purpose**: Manage compilation flags for accurate parsing

**Key Methods**:
- `load_compile_commands()` (lines 69-105): Load `compile_commands.json`
- `get_compile_args_with_fallback()` (lines 164-205): Get flags for a file

**Integration**: Provides compile flags to libclang parser for accurate AST generation

---

## Multi-Codebase Handling

### Separate Storage Per Project

The system uses **completely isolated storage** for each codebase with **no sharing** between projects.

### Project Isolation Mechanism

#### 1. Unique Cache Directories

**Implementation**: `mcp_server/cache_manager.py:22-31`

```python
def _get_cache_dir(self) -> Path:
    """Get cache directory for this project"""
    # Use the MCP server directory for cache, not the project being analyzed
    mcp_server_root = Path(__file__).parent.parent  # Go up from mcp_server/cache_manager.py to root
    cache_base = mcp_server_root / ".mcp_cache"

    # Create unique cache dir based on project path hash
    project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:8]
    cache_dir = cache_base / f"{self.project_root.name}_{project_hash}"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
```

**Hash Generation**:
- Input: Full absolute path to project directory
- Algorithm: MD5 hash
- Output: First 8 characters of hash (e.g., `a1b2c3d4`)
- Collision probability: ~1 in 4 billion for different paths

#### 2. Examples of Multi-Project Storage

```
.mcp_cache/
├── my_cpp_project_a1b2c3d4/
│   ├── cache_info.json
│   ├── indexing_progress.json
│   └── files/
│       ├── abc123.json
│       └── def456.json
│
├── another_project_e5f6g7h8/
│   ├── cache_info.json
│   ├── indexing_progress.json
│   └── files/
│       ├── ghi789.json
│       └── jkl012.json
│
└── my_cpp_project_i9j0k1l2/    # Same name, different path
    ├── cache_info.json
    └── ...
```

### MCP Server Project Management

**File**: `mcp_server/cpp_mcp_server.py`

#### Global Analyzer Instance (lines 143-149)

```python
# Global state
analyzer: CppAnalyzer | None = None
analyzer_initialized = False
```

**Single-Project Design**: Only one analyzer instance exists at a time

#### Project Switching (lines 424-432)

**Tool**: `set_project_directory`

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global analyzer, analyzer_initialized

    if name == "set_project_directory":
        project_path = arguments["project_path"]
        analyzer = CppAnalyzer(project_path)  # Creates new instance
        analyzer_initialized = True
        # Previous analyzer is garbage collected
```

**Behavior**:
1. Creating new `CppAnalyzer` replaces the old one
2. Previous analyzer is dereferenced and garbage collected
3. All in-memory indexes are lost
4. Next query loads from the new project's cache

### Multi-Codebase Properties

#### ✅ **What Works**:
- **Persistent storage**: Each project maintains its own cache indefinitely
- **No conflicts**: Different projects cannot interfere with each other
- **Name collisions**: Projects with same name but different paths are distinguished by hash
- **Sequential switching**: Can switch between projects by calling `set_project_directory`

#### ❌ **Limitations**:
- **No simultaneous access**: Cannot query multiple projects at once
- **State loss on switch**: Switching projects discards in-memory indexes of previous project
- **Re-load overhead**: Switching back to a previous project requires loading from cache
- **Single MCP server instance**: Each server instance handles one project at a time

### Storage Behavior Summary

| Scenario | Storage Behavior |
|----------|------------------|
| **First project indexed** | Creates `.mcp_cache/project1_hash1/` |
| **Second project indexed** | Creates `.mcp_cache/project2_hash2/` (separate) |
| **Switch to project1** | Loads from `.mcp_cache/project1_hash1/` (preserved) |
| **Same name, different path** | Creates `.mcp_cache/project_hash3/` (unique hash) |
| **Delete project directory** | Cache remains in `.mcp_cache/` (manual cleanup needed) |

### Design Rationale

**Why separate storage?**
1. **Isolation**: No symbol name conflicts between projects
2. **Cache validity**: File paths are absolute, cache is project-specific
3. **Performance**: Loading full multi-project index would be slow
4. **Simplicity**: Clear ownership and lifecycle management

**Why single active project?**
1. **Memory efficiency**: Full indexes for large projects can be GBs
2. **MCP protocol design**: Tools operate in single-project context
3. **Simplification**: No need for project-prefix in queries

---

## Complete Data Flow

### Phase 1: Analysis

```
┌─────────────────────────────────────────────────────────────┐
│                  INITIAL PROJECT INDEXING                   │
│             CppAnalyzer.index_project() [398]               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Check Global Cache                                       │
│    CacheManager.load_cache() [79]                           │
│    ├─ If valid: Load entire project index                   │
│    │   └─ Skip to Phase 2                                   │
│    └─ If invalid/missing: Continue to file discovery        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Discover Source Files                                    │
│    FileScanner.find_cpp_files() [415]                       │
│    ├─ Recursively search project directory                  │
│    ├─ Filter by extensions: .cpp, .cc, .cxx, .h, .hpp       │
│    └─ Exclude: build/, .git/, third_party/, etc.            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Parallel Processing                                      │
│    ThreadPoolExecutor [438]                                 │
│    ├─ Workers: 4 (default, configurable)                    │
│    ├─ Each worker processes files independently             │
│    └─ Thread-local libclang Index per worker                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
          ┌───────────────────┴───────────────────┐
          │                                       │
          ▼                                       ▼
┌─────────────────────┐               ┌─────────────────────┐
│   Thread 1          │               │   Thread 2          │
│   index_file()      │               │   index_file()      │
└─────────────────────┘               └─────────────────────┘
          │                                       │
          └───────────────────┬───────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   PER-FILE PROCESSING                       │
│                CppAnalyzer.index_file() [254]               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Calculate File Hash                                      │
│    _get_file_hash() [262]                                   │
│    └─ MD5 of file contents                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Check Per-File Cache                                     │
│    CacheManager.load_file_cache() [266]                     │
│    ├─ Load: files/{MD5(filepath)}.json                      │
│    ├─ Validate: Compare file_hash                           │
│    └─ If valid: Return cached symbols                       │
└─────────────────────────────────────────────────────────────┘
                │                             │
                │ Cache Hit                   │ Cache Miss
                ▼                             ▼
    ┌─────────────────────┐     ┌─────────────────────────────┐
    │ Use Cached Symbols  │     │ 3. Parse with Libclang      │
    │ [268-302]           │     │    index.parse() [329]      │
    │ ├─ SymbolInfo.      │     │    ├─ Get compile args      │
    │ │  from_dict()      │     │    ├─ Create Translation    │
    │ └─ Skip parsing     │     │    │   Unit                  │
    │    (~100x faster)   │     │    └─ Generate AST          │
    └─────────────────────┘     └─────────────────────────────┘
                │                             │
                │                             ▼
                │               ┌─────────────────────────────┐
                │               │ 4. Process AST              │
                │               │    _process_cursor() [363]  │
                │               │    ├─ Recursive traversal   │
                │               │    ├─ Detect classes [171]  │
                │               │    ├─ Detect functions [204]│
                │               │    ├─ Track calls [248]     │
                │               │    └─ Create SymbolInfo     │
                │               └─────────────────────────────┘
                │                             │
                └──────────────┬──────────────┘
                               │
                               ▼
```

### Phase 2: Storage

```
┌─────────────────────────────────────────────────────────────┐
│                    IN-MEMORY STORAGE                        │
│                  (Thread-Safe with Locks)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Update Indexes [188-196, 225-233]                           │
│                                                              │
│ with self.index_lock:                                       │
│                                                              │
│   1. class_index[symbol.name].append(symbol)                │
│      └─ Key: "MyClass" → [SymbolInfo, SymbolInfo, ...]      │
│                                                              │
│   2. function_index[symbol.name].append(symbol)             │
│      └─ Key: "myFunction" → [SymbolInfo, ...]               │
│                                                              │
│   3. file_index[symbol.file].append(symbol)                 │
│      └─ Key: "/path/to/file.cpp" → [SymbolInfo, ...]        │
│                                                              │
│   4. usr_index[symbol.usr] = symbol                         │
│      └─ Key: "c:@N@ns@C@MyClass" → SymbolInfo               │
│                                                              │
│   5. call_graph_analyzer.add_call(caller_usr, callee_usr)   │
│      └─ Updates: symbol.calls, symbol.called_by             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     DISK PERSISTENCE                        │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
      ┌──────────────────────┐  ┌──────────────────────┐
      │  Per-File Cache      │  │  Global Cache        │
      │  [After each file]   │  │  [After all files]   │
      └──────────────────────┘  └──────────────────────┘
                    │                   │
                    ▼                   ▼
┌─────────────────────────────┐ ┌─────────────────────────────┐
│ CacheManager.               │ │ CacheManager.               │
│ save_file_cache() [384]     │ │ save_cache() [521]          │
│                             │ │                             │
│ Location:                   │ │ Location:                   │
│ .mcp_cache/{project}/       │ │ .mcp_cache/{project}/       │
│   files/{hash}.json         │ │   cache_info.json           │
│                             │ │                             │
│ Contains:                   │ │ Contains:                   │
│ ├─ file_path                │ │ ├─ version: "2.0"           │
│ ├─ file_hash (MD5)          │ │ ├─ indexed_file_count       │
│ ├─ timestamp                │ │ ├─ index_dependencies       │
│ └─ symbols: [               │ │ ├─ file_hashes: {}          │
│      {name, kind, ...},     │ │ ├─ class_index: {}          │
│      ...                    │ │ └─ function_index: {}       │
│    ]                        │ │                             │
└─────────────────────────────┘ └─────────────────────────────┘
                    │                   │
                    └─────────┬─────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │ Progress Tracking      │
                 │ save_progress() [522]  │
                 │                        │
                 │ indexing_progress.json │
                 └────────────────────────┘
```

### Phase 3: Retrieval

```
┌─────────────────────────────────────────────────────────────┐
│                      CLIENT REQUEST                         │
│              (via Model Context Protocol)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Server: call_tool() [404-536]                           │
│ File: cpp_mcp_server.py                                     │
│                                                              │
│ Available Tools:                                            │
│ ├─ search_classes                                           │
│ ├─ search_functions                                         │
│ ├─ get_class_info                                           │
│ ├─ get_function_info                                        │
│ ├─ get_symbols_in_file                                      │
│ ├─ search_call_chain                                        │
│ └─ ...                                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ SearchEngine Dispatch                                       │
│ File: search_engine.py                                      │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│ search_classes  │ │ search_functions │ │ get_class_info  │
│ [21-39]         │ │ [41-65]          │ │ [88-117]        │
└─────────────────┘ └──────────────────┘ └─────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│            ACCESS IN-MEMORY INDEXES                          │
│                                                              │
│  Query: "search for class 'Vector'"                         │
│  ├─ Iterate: analyzer.class_index.items()                   │
│  ├─ Match: re.search("Vector", name, re.IGNORECASE)         │
│  ├─ Filter: if project_only and symbol.is_project           │
│  └─ Collect: results.append(symbol)                         │
│                                                              │
│  Time Complexity: O(n) where n = number of classes          │
│  Memory Access: Direct dictionary lookup                    │
│  No Disk I/O: All data is in RAM                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Serialize Results                                           │
│                                                              │
│ for symbol in results:                                      │
│     result_dict = symbol.to_dict()                          │
│     # {                                                     │
│     #   "name": "Vector",                                   │
│     #   "kind": "class",                                    │
│     #   "file": "/path/to/vector.h",                        │
│     #   "line": 42,                                         │
│     #   ...                                                 │
│     # }                                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Return to Client                                            │
│                                                              │
│ return [                                                    │
│     TextContent(                                            │
│         type="text",                                        │
│         text=json.dumps(results, indent=2)                  │
│     )                                                       │
│ ]                                                           │
└─────────────────────────────────────────────────────────────┘
```

### Phase 4: Incremental Updates

```
┌─────────────────────────────────────────────────────────────┐
│                  REFRESH TRIGGER                            │
│         (File modification detected by IDE/watcher)         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ CppAnalyzer.refresh_if_needed() [652-708]                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Detect Deleted Files [668-678]                           │
│                                                              │
│    cached_files = set(analyzer.file_index.keys())           │
│    current_files = set(scanner.find_cpp_files())            │
│    deleted = cached_files - current_files                   │
│                                                              │
│    for file in deleted:                                     │
│        _remove_file_from_indexes(file)                      │
│        cache_manager.remove_file_cache(file)                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Detect Modified Files [680-694]                          │
│                                                              │
│    for file in current_files:                               │
│        old_hash = file_hashes.get(file)                     │
│        new_hash = _get_file_hash(file)                      │
│        if old_hash != new_hash:                             │
│            modified.add(file)                               │
│                                                              │
│    for file in modified:                                    │
│        index_file(file)  # Re-analyze                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Detect New Files [696-706]                               │
│                                                              │
│    new_files = current_files - cached_files                 │
│                                                              │
│    for file in new_files:                                   │
│        index_file(file)                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Save Updated Cache                                       │
│                                                              │
│    cache_manager.save_cache()                               │
└─────────────────────────────────────────────────────────────┘
```

### File Removal Details

```
┌─────────────────────────────────────────────────────────────┐
│ CppAnalyzer._remove_file_from_indexes() [710-749]           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Get all symbols in file                                  │
│    symbols = file_index[file_path]                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Remove from indexes (with lock)                          │
│                                                              │
│    with self.index_lock:                                    │
│        for symbol in symbols:                               │
│            class_index[symbol.name].remove(symbol)          │
│            function_index[symbol.name].remove(symbol)       │
│            usr_index.pop(symbol.usr)                        │
│            call_graph_analyzer.remove_symbol(symbol.usr)    │
│                                                              │
│        file_index.pop(file_path)                            │
│        file_hashes.pop(file_path)                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Remove per-file cache                                    │
│    cache_manager.remove_file_cache(file_path)               │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Architectural Insights

### 1. Hybrid Caching Strategy

**Two-Level Design**:
- **Global cache**: Fast startup for unchanged projects
- **Per-file cache**: Incremental updates without full re-index

**Benefits**:
- Large projects (1000+ files) can load in seconds
- Modified files re-indexed individually (~1-2s per file)
- Unchanged files skip parsing entirely

**Trade-off**: Disk space (~1-5MB per 1000 files) for time savings

### 2. Thread-Safe Concurrent Processing

**Concurrency Model**:
- ThreadPoolExecutor with configurable workers (default 4)
- Thread-local libclang Index instances (not thread-safe)
- Shared indexes protected by `threading.Lock`

**Performance Impact**:
- 4x speedup on quad-core systems
- Scales with CPU core count
- Lock contention minimal (fast in-memory operations)

**Code Pattern**:
```python
# Thread-unsafe: libclang Index
index = clang.cindex.Index.create()  # Per-thread

# Thread-safe: Shared indexes
with self.index_lock:
    self.class_index[name].append(symbol)
```

### 3. Project Isolation via Hashing

**Collision Resistance**:
- MD5 hash of full project path
- 8-character prefix = 4 billion unique values
- Birthday paradox: ~77,000 projects before 50% collision

**Path Sensitivity**:
- `/home/user/project` ≠ `/home/other/project` (different hashes)
- Symbolic links: Resolved to real path before hashing

**Limitation**: Moving project directory invalidates cache (different hash)

### 4. Incremental Update Efficiency

**Hash-Based Change Detection**:
- MD5 of file contents (not modification time)
- Resistant to spurious changes (timestamp updates)
- Detects actual content modifications

**Update Granularity**:
- File-level (not line-level or function-level)
- Any change triggers full file re-index
- Trade-off: Simplicity vs fine-grained updates

**Typical Scenario**:
- Developer changes 1 file in 1000-file project
- Re-index time: 1-2 seconds
- Without caching: 30-60 seconds

### 5. Call Graph Integration

**Bidirectional Tracking**:
```python
# Function A calls Function B
A.calls.append(B.usr)        # Forward edge
B.called_by.append(A.usr)    # Backward edge
```

**Use Cases**:
- Find all callers of a function (impact analysis)
- Find all callees from a function (dependency analysis)
- Build full call chains

**Persistence**: Stored in cache, survives server restarts

### 6. Dependency Management

**Project vs Dependency Code**:
- `is_project` flag on each SymbolInfo
- `FileScanner` filters based on directory patterns
- Configurable via `index_dependencies` setting

**Excluded Paths** (default):
```python
DEPENDENCY_DIRS = [
    "build", "cmake-build", ".git", "third_party",
    "external", "vendor", "node_modules"
]
```

**Query Filtering**:
```python
search_classes(pattern, project_only=True)
# Returns only symbols with is_project=True
```

### 7. Cache Invalidation Strategy

**Invalidation Triggers**:
1. **Cache version mismatch**: Format changed → Full re-index
2. **Setting change**: `index_dependencies` toggled → Full re-index
3. **File hash mismatch**: Content changed → Re-index file
4. **File deleted**: Remove from indexes + delete cache

**No Automatic Expiry**: Cache persists indefinitely until invalidated

**Manual Cleanup**: Delete `.mcp_cache/{project}/` directory

### 8. Error Resilience

**Graceful Degradation**:
- Cache load failure → Fall back to full indexing
- Single file parse error → Log + continue with remaining files
- Missing compile_commands.json → Use default flags

**Example**:
```python
try:
    cached_data = self.cache_manager.load_cache()
except Exception as e:
    print(f"Cache load failed: {e}, re-indexing")
    cached_data = None
```

### 9. Memory Efficiency

**In-Memory Footprint**:
- ~1KB per symbol (SymbolInfo object)
- 10,000 symbols ≈ 10MB RAM
- Indexes: Additional ~2x overhead (multiple references)

**Typical Project**:
- 100K lines of C++ ≈ 5000 symbols ≈ 5MB RAM
- 1M lines ≈ 50,000 symbols ≈ 50MB RAM

**Optimization**: USR-based deduplication prevents duplicate storage

### 10. Scalability Limits

**Current Architecture**:
- ✅ Projects up to ~100K files (tested)
- ✅ Parallel indexing scales with CPU cores
- ⚠️ Single project per server instance
- ⚠️ Full indexes loaded into RAM

**Bottlenecks**:
- Large projects: Initial indexing time (minutes)
- Memory: Grows linearly with symbol count
- Disk: Cache size grows with project size

**Implemented in v3.0.0**:
- ✅ SQLite database backend for 20x faster searches
- ✅ FTS5 full-text search with prefix matching
- ✅ Automatic JSON→SQLite migration
- ✅ WAL mode for concurrent multi-process access

**Future Improvements**:
- Lazy loading of symbols (on-demand from SQLite)
- Multi-project support in single server

---

## SQLite Cache Backend Architecture (v3.0.0+)

The analyzer uses a high-performance SQLite cache backend for optimal performance on large projects.

### 11. SQLite Backend Overview

**Key Features**:
- **FTS5 Full-Text Search**: 2-5ms searches for 100K symbols
- **Compact Storage**: Efficient disk usage with automatic maintenance
- **Concurrent Access**: WAL mode enables safe multi-process reads during writes
- **Health Monitoring**: Built-in integrity checks and diagnostics

**Architecture Components**:
```
mcp_server/
├── cache_backend.py              # Protocol/interface definition
├── sqlite_cache_backend.py       # SQLite implementation
├── cache_manager.py              # Cache coordinator
├── error_tracking.py             # Error monitoring and recovery
├── schema.sql                    # Database schema with FTS5
├── schema_migrations.py          # Schema version management
└── migrations/
    └── 001_initial_schema.sql    # Migration scripts
```

### 12. Database Schema Design

**Core Tables**:

```sql
-- Main symbol storage
CREATE TABLE symbols (
    usr TEXT PRIMARY KEY,           -- Unified Symbol Resolution ID (unique)
    name TEXT NOT NULL,             -- Symbol name (indexed for search)
    kind TEXT NOT NULL,             -- class, function, method, etc.
    file TEXT NOT NULL,             -- Source file path
    line INTEGER,                   -- Line number
    column INTEGER,                 -- Column number
    signature TEXT,                 -- Function signature or member type
    is_project BOOLEAN,             -- Project vs dependency symbol
    namespace TEXT,                 -- C++ namespace
    access TEXT,                    -- public, private, protected
    parent_class TEXT,              -- For methods/members
    base_classes TEXT,              -- JSON array of base classes
    calls TEXT,                     -- JSON array of called USRs
    called_by TEXT,                 -- JSON array of caller USRs
    created_at REAL,                -- Unix timestamp
    updated_at REAL                 -- Unix timestamp
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    usr UNINDEXED,                 -- Don't index USR (used for JOIN only)
    name,                          -- Full-text indexed name
    content='symbols',             -- Backed by symbols table
    content_rowid='rowid'          -- Link to symbols.rowid
);

-- File metadata tracking
CREATE TABLE file_metadata (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,        -- MD5 hash of file contents
    compile_args_hash TEXT,         -- Hash of compilation arguments
    indexed_at REAL NOT NULL,       -- Unix timestamp
    symbol_count INTEGER            -- Number of symbols in file
);

-- Cache metadata (configuration, timestamps, etc.)
CREATE TABLE cache_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Schema version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);
```

**Indexes for Performance**:
```sql
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_kind ON symbols(kind);
CREATE INDEX idx_symbols_file ON symbols(file);
CREATE INDEX idx_symbols_parent_class ON symbols(parent_class);
CREATE INDEX idx_symbols_namespace ON symbols(namespace);
CREATE INDEX idx_symbols_project ON symbols(is_project);
CREATE INDEX idx_symbols_name_kind_project ON symbols(name, kind, is_project);
CREATE INDEX idx_symbols_updated_at ON symbols(updated_at);
CREATE INDEX idx_file_metadata_indexed_at ON file_metadata(indexed_at);
```

### 13. FTS5 Full-Text Search

**Why FTS5?**:
- **20x faster** than LIKE queries for symbol search
- **Prefix matching**: Supports patterns like "Vec*" to find "Vector", "VectorIterator", etc.
- **Ranking**: Results sorted by relevance
- **Tokenization**: Handles CamelCase and snake_case correctly

**FTS5 Triggers**:
Automatic synchronization between `symbols` and `symbols_fts` tables:

```sql
-- Insert trigger
CREATE TRIGGER symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, usr, name)
    VALUES (new.rowid, new.usr, new.name);
END;

-- Update trigger
CREATE TRIGGER symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, usr, name)
    VALUES('delete', old.rowid, old.usr, old.name);
    INSERT INTO symbols_fts(rowid, usr, name)
    VALUES (new.rowid, new.usr, new.name);
END;

-- Delete trigger
CREATE TRIGGER symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, usr, name)
    VALUES('delete', old.rowid, old.usr, old.name);
END;
```

**Search Performance**:
```python
# FTS5 search: 2-5ms for 100K symbols
results = backend.search_symbols_fts("Vector*", kind="class")

# Equivalent LIKE search: 50ms
results = backend.search_symbols_regex("^Vector", kind="class")
```

### 14. WAL Mode for Concurrency

**Write-Ahead Logging (WAL)**:
- **Readers don't block writers**: Multiple processes can read while one writes
- **Writers don't block readers**: Write transactions don't lock the database
- **Crash recovery**: Unflushed writes recovered from WAL file
- **Performance**: Faster commits (no need to flush entire database)

**Configuration**:
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;        -- 64MB cache
PRAGMA mmap_size = 268435456;      -- 256MB memory-mapped I/O
PRAGMA temp_store = MEMORY;        -- Temp tables in memory
```

**Lock Handling**:
```python
# Busy handler with exponential backoff
def _busy_handler(self, retry_count: int) -> bool:
    if retry_count < 20:
        sleep_time = 0.001 * (2 ** min(retry_count, 10))
        time.sleep(sleep_time)
        return True  # Retry
    return False  # Give up after 20 retries
```

### 15. Schema Migration System

**Version Tracking**:
- Each schema version stored in `schema_version` table
- Migration scripts in `mcp_server/migrations/` directory
- Forward-only migrations (no downgrades)
- Transaction-based (all-or-nothing)

**Migration Flow**:
1. Check current schema version
2. Compare with `SqliteCacheBackend.CURRENT_SCHEMA_VERSION`
3. Apply pending migrations in order
4. Update `schema_version` table
5. Log completion

**Example Migration**:
```sql
-- migrations/002_add_comment_field.sql
BEGIN TRANSACTION;

-- Add new column
ALTER TABLE symbols ADD COLUMN comment TEXT;

-- Update schema version
INSERT INTO schema_version (version, applied_at)
VALUES (2, strftime('%s', 'now'));

COMMIT;
```

### 16. Automatic JSON→SQLite Migration

**Migration Triggers**:
- First use with `CLANG_INDEX_USE_SQLITE=1` (default)
- Presence of `cache_info.json` and absence of `cache.db`
- No `.migrated_to_sqlite` marker file

**Migration Process**:
```
1. Check: should_migrate() → bool
   ├─ JSON cache exists?
   ├─ SQLite cache doesn't exist?
   └─ No migration marker?

2. Backup: create_migration_backup()
   └─ Copy entire cache to backup_YYYYMMDD_HHMMSS/

3. Migrate: migrate_json_to_sqlite()
   ├─ Load JSON cache_info.json
   ├─ Extract symbols from class_index + function_index
   ├─ Deduplicate (same symbol in both indexes)
   ├─ Batch insert into SQLite (10,000+ symbols/sec)
   ├─ Migrate file_hashes → file_metadata
   └─ Migrate cache metadata

4. Verify: verify_migration()
   ├─ Symbol count match?
   ├─ Random sample verification (100 symbols)
   └─ Metadata verification

5. Mark: create_migration_marker()
   └─ Write .migrated_to_sqlite marker file
```

**Performance**:
- 10K symbols: ~1 second
- 50K symbols: ~3 seconds
- 100K symbols: ~5 seconds

### 17. Error Handling and Recovery

**Error Tracking**:
```python
class ErrorTracker:
    """Track errors and trigger fallback to JSON if needed."""
    def __init__(self, error_rate_threshold: float = 0.05,
                 window_seconds: int = 300):
        self.error_rate_threshold = error_rate_threshold  # 5%
        self.window_seconds = window_seconds              # 5 minutes
        self.errors: List[ErrorRecord] = []
```

**Error Types and Responses**:
1. **DatabaseLocked**: Retry with exponential backoff
2. **DatabaseCorrupt**: Attempt repair with VACUUM, restore from backup
3. **DiskFull**: Clear cache, notify user
4. **PermissionError**: Clear cache, fall back to JSON
5. **HighErrorRate** (>5%): Automatically fall back to JSON

**Recovery Mechanisms**:
```python
class RecoveryManager:
    def backup_database(self) -> Path:
        """Create timestamped backup."""

    def restore_from_backup(self, backup_path: Path) -> bool:
        """Restore from backup."""

    def attempt_repair(self) -> bool:
        """Try VACUUM and integrity check."""

    def clear_cache(self) -> bool:
        """Delete corrupted cache (last resort)."""
```

### 18. Database Maintenance

**Automatic Maintenance**:
```python
def auto_maintenance(self, vacuum_threshold_mb: float = 100.0,
                    vacuum_min_waste_mb: float = 10.0) -> Dict[str, Any]:
    """Run automatic maintenance based on database health."""

    # Always run ANALYZE (fast, updates query planner stats)
    self.analyze()

    # Always run OPTIMIZE (rebuilds FTS5 indexes)
    self.optimize()

    # Conditionally run VACUUM (reclaims space from deletions)
    if db_size > threshold and wasted_space > min_waste:
        self.vacuum()
```

**Operations**:
- **VACUUM**: Rebuild database, reclaim deleted space, defragment
- **OPTIMIZE**: Rebuild FTS5 indexes for optimal search performance
- **ANALYZE**: Update query planner statistics for better query plans

**When to Run**:
- **ANALYZE**: After bulk inserts/updates
- **OPTIMIZE**: After large symbol additions
- **VACUUM**: After many deletions, or periodically (e.g., weekly)

### 19. Health Monitoring

**Diagnostic Checks**:
```python
def get_health_status(self) -> Dict[str, Any]:
    """Comprehensive health checks."""
    return {
        'status': 'healthy' | 'warning' | 'error',
        'checks': {
            'integrity': {...},      # PRAGMA integrity_check
            'size': {...},           # Database size analysis
            'fts_index': {...},      # FTS5 count vs symbols count
            'wal_mode': {...},       # WAL mode verification
            'tables': {...}          # Table row counts
        },
        'warnings': [...],           # Non-critical issues
        'errors': [...]              # Critical issues
    }
```

**Monitoring Tools**:
- `cache_stats.py`: Statistics (size, symbols, performance)
- `diagnose_cache.py`: Health checks with recommendations
- `migrate_cache.py`: Manual migration and verification

### 20. Performance Comparison

**Benchmarks (100K symbols)**:

| Operation | JSON Cache | SQLite Cache | Speedup |
|-----------|-----------|--------------|---------|
| Cold startup | 600ms | 300ms | **2x** |
| Warm startup | 400ms | 80ms | **5x** |
| Symbol search (name) | 50ms | 2-5ms | **20x** |
| Symbol search (regex) | 100ms | 10ms | **10x** |
| Bulk insert (10K) | 5s | 0.9s | **5.5x** |
| File-level update | 200ms | 50ms | **4x** |
| Disk usage | 100MB | 30MB | **70% smaller** |

**Memory Usage**:
- JSON: All symbols loaded into RAM (~1MB per 1K symbols)
- SQLite: Minimal RAM usage (queries use indexes, not full scan)

### 21. Scalability Improvements

**With SQLite Backend**:
- ✅ Projects up to 1M+ symbols (tested with 500K)
- ✅ Constant-time lookups with indexes (vs linear scan)
- ✅ Memory-efficient (symbols not all loaded into RAM)
- ✅ Multi-process safe with WAL mode
- ✅ Faster incremental updates (file-level granularity)

**Bottlenecks Eliminated**:
- ❌ JSON parsing overhead (replaced with SQL queries)
- ❌ Full cache loaded into RAM (replaced with indexed lookups)
- ❌ Linear search for symbols (replaced with FTS5 + indexes)
- ❌ Concurrent access blocked (replaced with WAL mode)

**Remaining Bottlenecks**:
- Initial indexing still takes time (minutes for very large projects)
- Depends on disk I/O speed (but SSD-optimized with mmap)

---

## Summary

The MCP server implements a sophisticated, production-ready code analysis system with:

1. **High-Performance Storage**: SQLite backend with FTS5 full-text search (v3.0.0+) or legacy JSON cache
2. **Lightning-Fast Search**: 2-5ms symbol searches for 100K symbols (20x faster than JSON)
3. **Concurrent Access**: WAL mode enables safe multi-process reads during writes
4. **Automatic Migration**: Seamless JSON→SQLite migration on first use
5. **Project Isolation**: Hash-based separate storage for multiple codebases
6. **Thread-Safe Operations**: Concurrent file processing with lock-protected shared state
7. **Comprehensive Indexing**: Classes, functions, files, USRs, and call graphs with full-text search
8. **Incremental Updates**: Hash-based change detection for minimal re-work
9. **Query Flexibility**: FTS5 prefix matching, regex search, class filtering, project-only modes
10. **Resilient Design**: Error tracking, automatic recovery, graceful fallback to JSON
11. **Health Monitoring**: Built-in diagnostics, integrity checks, and maintenance tools

The system is optimized for developer productivity, providing **sub-5ms queries** on large codebases (100K+ symbols) while maintaining data consistency across sessions and supporting concurrent multi-process access.
