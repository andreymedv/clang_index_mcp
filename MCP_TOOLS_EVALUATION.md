# C++ MCP Server Tools Evaluation
## Comprehensive Analysis for LLM Agent Usage

**Date:** 2025-11-18
**Branch:** origin/compile_commands-support
**Evaluator:** Claude Code Agent

---

## Executive Summary

This MCP (Model Context Protocol) server provides **16 specialized tools** for semantic C++ code analysis using libclang. The server offers significant advantages over default agent tools (Grep, Glob, Read) by providing **AST-level understanding** of C++ code rather than text-based pattern matching.

**Key Advantages:**
- **Semantic Understanding**: Parses C++ code using libclang's AST, understanding language constructs
- **Relationship Mapping**: Tracks inheritance hierarchies and call graphs automatically
- **Accuracy**: Eliminates false positives from text-based searches (e.g., finds actual class definitions, not comments mentioning class names)
- **Performance**: Pre-indexed cache enables instant queries vs. repeated file system scans
- **Compile-Aware**: Uses `compile_commands.json` for accurate parsing with project-specific compiler flags

**Most Valuable Tools (High Frequency Use):**
1. `search_classes` - Locate class/struct definitions
2. `search_functions` - Find functions and methods
3. `get_class_info` - Inspect class structure and API
4. `search_symbols` - Unified search across symbol types
5. `get_class_hierarchy` - Understand inheritance relationships

---

## Tool-by-Tool Analysis

### 1. search_classes

**Purpose:** Search for C++ class and struct definitions by name pattern with regex support.

**Best Used For:**
- Locating where a class is defined in large codebases
- Finding all classes matching a naming pattern (e.g., `.*Manager`, `I.*` for interfaces)
- Discovering related classes by partial name matching
- Understanding project structure through class discovery

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep/Glob) |
|--------|----------|---------------------|
| **Accuracy** | Returns only actual class definitions | Returns comments, strings, forward declarations |
| **Metadata** | Provides file, line, kind (CLASS_DECL/STRUCT_DECL), base classes | Raw text matches only |
| **Performance** | Instant query on pre-indexed data | Must scan all files each time |
| **Project Filtering** | `project_only` flag excludes dependencies | Requires complex path exclusions |
| **False Positives** | None - AST-verified class definitions | High - matches any text occurrence |

**Example Output:**
```json
{
  "results": [
    {
      "name": "GameObject",
      "kind": "CLASS_DECL",
      "file": "/project/src/engine/GameObject.h",
      "line": 25,
      "is_project": true,
      "base_classes": ["Entity", "IUpdatable"]
    }
  ],
  "metadata": {
    "status": "indexed",
    "complete": true
  }
}
```

**Frequency Assessment:** **VERY HIGH** - Essential for navigating C++ codebases where class discovery is fundamental.

---

### 2. search_functions

**Purpose:** Search for C++ functions and methods by name pattern across the codebase.

**Best Used For:**
- Finding where a function is implemented
- Discovering all methods matching a pattern (e.g., `get.*`, `on.*Event`)
- Locating both standalone functions and class methods
- API discovery and understanding

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep) |
|--------|----------|----------------|
| **Accuracy** | Returns actual function definitions/declarations | Matches function calls, comments, strings |
| **Signature** | Includes full signature with parameter types | Text-only, must parse manually |
| **Context** | Shows parent class for methods | Requires reading surrounding code |
| **Kind Detection** | Distinguishes FUNCTION_DECL/CXX_METHOD/CONSTRUCTOR/DESTRUCTOR | Cannot distinguish programmatically |
| **Filtering** | `class_name` parameter to scope to specific class | Complex regex patterns needed |

**Example Output:**
```json
{
  "results": [
    {
      "name": "update",
      "kind": "CXX_METHOD",
      "file": "/project/src/Player.cpp",
      "line": 142,
      "signature": "void update(float deltaTime)",
      "parent_class": "Player",
      "is_project": true
    }
  ]
}
```

**Frequency Assessment:** **VERY HIGH** - Functions are the primary unit of work in C++; constant need to locate and understand them.

---

### 3. get_class_info

**Purpose:** Get comprehensive information about a specific class including all methods, base classes, and location.

**Best Used For:**
- Understanding a class's complete API surface
- Reviewing all methods available in a class
- Checking inheritance relationships
- Generating documentation or summaries

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Read + Manual Parsing) |
|--------|----------|----------------------------------|
| **Completeness** | All methods aggregated automatically | Must read entire file, parse manually |
| **Sorted Output** | Methods sorted by line number | Appears in file order only |
| **Access Levels** | Includes all public/private/protected | Must parse access specifiers manually |
| **Inheritance** | Base classes listed explicitly | Must search for class declaration |
| **Multi-file** | Aggregates from header and implementation | Must locate and read multiple files |

**Example Output:**
```json
{
  "name": "Renderer",
  "kind": "CLASS_DECL",
  "file": "/project/include/Renderer.h",
  "line": 18,
  "base_classes": ["IRenderer", "Component"],
  "methods": [
    {
      "name": "Renderer",
      "kind": "CONSTRUCTOR",
      "signature": "Renderer()",
      "line": 22
    },
    {
      "name": "render",
      "kind": "CXX_METHOD",
      "signature": "void render(const Scene& scene)",
      "line": 35
    }
  ],
  "members": [],
  "is_project": true
}
```

**Note:** Current limitation - member variables are not indexed (will be empty array).

**Frequency Assessment:** **HIGH** - Frequent need when working with unfamiliar classes or designing interactions.

---

### 4. get_function_signature

**Purpose:** Get formatted signature strings for functions, showing parameter types and class scope.

**Best Used For:**
- Quick lookup of function parameters
- Understanding overload variations
- Generating function call templates
- Documentation generation

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep + Manual Parsing) |
|--------|----------|----------------------------------|
| **Format** | Formatted as `ClassName::functionName(type1, type2)` | Raw code requiring parsing |
| **Overloads** | Returns all overloads automatically | Must find and parse each |
| **Class Scope** | Shows class qualifier if method | Must determine from context |
| **Speed** | Instant indexed lookup | Must scan files and parse |

**Example Output:**
```json
{
  "results": [
    "Player::setPosition(float x, float y)",
    "Player::setPosition(const Vector2& pos)"
  ]
}
```

**Limitation:** Does NOT include return types (only parameters and name).

**Frequency Assessment:** **MEDIUM-HIGH** - Useful for understanding how to call functions, but less critical than search tools.

---

### 5. search_symbols

**Purpose:** Unified search across multiple symbol types (classes, structs, functions, methods) with a single query.

**Best Used For:**
- General symbol discovery when type is unknown
- Finding all symbols matching a pattern regardless of type
- Reducing tool calls by searching multiple categories at once
- Exploratory codebase navigation

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep) |
|--------|----------|----------------|
| **Organization** | Results grouped by type (classes, functions) | Flat unorganized list |
| **Efficiency** | Single query vs. multiple searches | Must run multiple greps |
| **Type Filtering** | `symbol_types` array to filter categories | Requires complex regex patterns |
| **Context** | Full metadata for each symbol type | Text matches only |

**Example Output:**
```json
{
  "results": {
    "classes": [
      {"name": "GameManager", "kind": "CLASS_DECL", "file": "...", "line": 10}
    ],
    "functions": [
      {"name": "gameLoop", "kind": "FUNCTION_DECL", "file": "...", "line": 45},
      {"name": "GameState::gameOver", "kind": "CXX_METHOD", "file": "...", "line": 78}
    ]
  }
}
```

**Frequency Assessment:** **MEDIUM** - Useful for exploratory searches, but often you know whether you're looking for a class or function.

---

### 6. find_in_file

**Purpose:** Search for C++ symbols within a specific source file.

**Best Used For:**
- Exploring contents of a specific file
- Verifying what symbols are defined in a file
- Scoped searches when file location is known
- Understanding file organization

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Read + Manual Search) |
|--------|----------|--------------------------------|
| **Path Matching** | Accepts absolute, relative, or partial paths | Requires exact path |
| **Symbol Focus** | Returns only class/function definitions | Returns all text, requires parsing |
| **Structured Output** | JSON with metadata | Raw text |
| **Pattern Matching** | Regex support for symbol names | Manual text search |

**Example Use Case:**
```
find_in_file(file_path="Player.cpp", pattern=".*")
// Returns all classes/functions defined in Player.cpp
```

**Frequency Assessment:** **LOW-MEDIUM** - Less common than global searches; mainly when file is already known.

---

### 7. set_project_directory

**Purpose:** Initialize the analyzer with a C++ project directory. **REQUIRED FIRST STEP** before using any other tools.

**Best Used For:**
- Project initialization
- Switching between different C++ projects
- Setting up multi-configuration workflows (Debug/Release)
- Starting a new analysis session

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Manual Navigation) |
|--------|----------|------------------------------|
| **Indexing** | Automatic AST parsing and caching | No indexing, repeated file scans |
| **Incremental Analysis** | Auto-detects changed files on reload | Full re-scan every time |
| **Configuration** | Respects `compile_commands.json` | No build configuration awareness |
| **Performance** | One-time indexing, instant queries after | Slow repeated operations |
| **Multi-Config** | Different configs create separate caches | No configuration separation |

**Important Parameters:**
- `project_path`: Absolute path to C++ project root (required)
- `config_file`: Optional path to `.cpp-analyzer-config.json` for custom settings
- `auto_refresh`: Default true, automatically detects and re-indexes changed files

**Example Usage:**
```json
{
  "project_path": "/home/user/my-cpp-project",
  "config_file": "/home/user/my-cpp-project/.cpp-analyzer-config.json",
  "auto_refresh": true
}
```

**Performance Note:** Initial indexing can take minutes for large projects (thousands of files), but creates persistent cache for instant subsequent queries.

**Frequency Assessment:** **MEDIUM** - Called once per project session, but critical for enabling all other tools.

---

### 8. refresh_project

**Purpose:** Manually refresh the project index to detect and re-parse modified, added, or deleted files.

**Best Used For:**
- After editing C++ source files
- After git operations (checkout, pull, merge)
- After build system changes
- When cache seems stale or incorrect

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Re-initialization) |
|--------|----------|------------------------------|
| **Incremental** | Analyzes only changed files (30-300x faster) | Full re-scan required |
| **Change Detection** | MD5 hashing and dependency tracking | No automatic detection |
| **Dependency Cascade** | Re-analyzes files including modified headers | Cannot track header dependencies |
| **Statistics** | Detailed report of changes and time | No feedback |

**Modes:**
- **Incremental** (default): Only changed files (seconds)
- **Full** (`force_full=true`): All files (minutes)

**Example Output:**
```json
{
  "mode": "incremental",
  "files_analyzed": 5,
  "files_removed": 1,
  "elapsed_seconds": 2.3,
  "changes": {
    "compile_commands_changed": false,
    "added_files": 1,
    "modified_files": 3,
    "modified_headers": 1,
    "removed_files": 1,
    "total_changes": 6
  },
  "message": "Incremental refresh complete: Re-analyzed 5 files, removed 1 files in 2.30s"
}
```

**Performance Comparison:**
| Scenario | Full Re-analysis | Incremental | Speedup |
|----------|-----------------|-------------|---------|
| Single file changed | 30-60s | <1s | 30-60x |
| Header + 10 dependents | 30-60s | 3-5s | 6-10x |
| No changes | 30-60s | <0.1s | 300-600x |

**Frequency Assessment:** **MEDIUM** - Not needed constantly, but important after code modifications or git operations.

---

### 9. get_server_status

**Purpose:** Get diagnostic information about the MCP server state and index statistics.

**Best Used For:**
- Verifying server is working correctly
- Checking if indexing is complete
- Debugging configuration issues
- Understanding cache state

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (N/A) |
|--------|----------|---------------|
| **Server Health** | Shows analyzer type, enabled features | Not available |
| **Statistics** | Counts of parsed files, indexed symbols | Would require manual counting |
| **Configuration** | Shows compile_commands status | Would require reading config files |
| **Diagnostics** | Single query for all status info | Multiple file reads needed |

**Example Output:**
```json
{
  "analyzer_type": "python_enhanced",
  "call_graph_enabled": true,
  "usr_tracking_enabled": true,
  "compile_commands_enabled": true,
  "compile_commands_path": "/project/compile_commands.json",
  "compile_commands_cache_enabled": true,
  "parsed_files": 1247,
  "indexed_classes": 342,
  "indexed_functions": 1856,
  "project_files": 1247
}
```

**Frequency Assessment:** **LOW** - Mainly for debugging or verification, not regular workflow.

---

### 10. get_indexing_status

**Purpose:** Get real-time status of project indexing with progress information.

**Best Used For:**
- Monitoring indexing progress on large projects
- Determining if queries will return complete results
- Checking ETA for indexing completion
- Understanding current analyzer state

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (N/A) |
|--------|----------|---------------|
| **Real-time Progress** | Live percentage, file counts, ETA | Not available |
| **State Awareness** | Shows state: uninitialized/indexing/indexed/refreshing/error | No state tracking |
| **Completeness** | Indicates if query results will be partial | No way to know |
| **Current File** | Shows which file is being processed | Not visible |

**Example Output:**
```json
{
  "state": "indexing",
  "progress": {
    "indexed_files": 523,
    "total_files": 1247,
    "failed_files": 3,
    "completion_percentage": 41.9,
    "current_file": "/project/src/rendering/Shader.cpp",
    "eta_seconds": 87.5
  },
  "can_query": true,
  "results_complete": false,
  "message": "Indexing in progress (41.9% complete). Queries will return partial results."
}
```

**States:**
- `uninitialized`: No project set
- `initializing`: Preparing to index
- `indexing`: Currently indexing
- `indexed`: Indexing complete
- `refreshing`: Re-indexing changed files
- `error`: Indexing failed

**Frequency Assessment:** **MEDIUM** - Important when working with large projects to avoid waiting for partial results.

---

### 11. wait_for_indexing

**Purpose:** Block until indexing completes or timeout is reached.

**Best Used For:**
- Ensuring complete results before critical queries
- Synchronizing workflow on large project initialization
- Avoiding partial results when completeness is required
- Automated scripts requiring full index

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Polling) |
|--------|----------|-------------------|
| **Blocking** | Efficient wait with timeout | Would require manual polling loop |
| **Status** | Returns completion status and counts | No feedback |
| **Timeout** | Configurable timeout (default 60s) | Would need custom timer |
| **Use Case** | Clean synchronization primitive | Awkward to implement manually |

**Example Usage:**
```json
{
  "timeout": 120.0  // Wait up to 2 minutes
}
```

**Example Output:**
```json
{
  "text": "Indexing complete! Indexed 1247 files successfully (3 failed)."
}
```

**Timeout Response:**
```json
{
  "text": "Timeout waiting for indexing (waited 120s). Use 'get_indexing_status' to check progress."
}
```

**Frequency Assessment:** **LOW-MEDIUM** - Used strategically when complete results are critical, not in every workflow.

---

### 12. get_class_hierarchy

**Purpose:** Get complete bidirectional inheritance hierarchy (ancestors AND descendants) for a C++ class.

**Best Used For:**
- Understanding complete class inheritance trees
- Finding all subclasses of a base class (transitive closure)
- Analyzing polymorphic relationships
- Design pattern analysis (e.g., Strategy, Template Method)
- Impact analysis for base class changes

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Manual Exploration) |
|--------|----------|-------------------------------|
| **Completeness** | Recursive traversal to all ancestors/descendants | Must manually trace inheritance |
| **Bidirectional** | Shows both parents and children | Would require multiple queries |
| **Transitive** | Includes indirect relationships (grandchildren, etc.) | Easy to miss indirect relationships |
| **Structure** | Organized hierarchical structure | Flat, unorganized data |
| **Speed** | Instant query on pre-built graph | Must read and parse multiple files |

**Example Output:**
```json
{
  "name": "Sprite",
  "base_hierarchy": [
    "Sprite -> Drawable -> Object"
  ],
  "derived_hierarchy": [
    "Sprite -> AnimatedSprite",
    "Sprite -> AnimatedSprite -> CharacterSprite",
    "Sprite -> TiledSprite"
  ],
  "class_info": {
    "name": "Sprite",
    "kind": "CLASS_DECL",
    "file": "/project/src/graphics/Sprite.h",
    "line": 15
  },
  "direct_base_classes": ["Drawable"],
  "direct_derived_classes": ["AnimatedSprite", "TiledSprite"]
}
```

**vs. get_derived_classes:**
- `get_derived_classes`: Only DIRECT children (one level)
- `get_class_hierarchy`: COMPLETE tree (all levels, both directions)

**Frequency Assessment:** **MEDIUM-HIGH** - Critical for understanding OOP design in C++ projects with inheritance.

---

### 13. get_derived_classes

**Purpose:** Get a flat list of classes that DIRECTLY inherit from a specified base class (immediate children only, one level).

**Best Used For:**
- Finding immediate subclasses
- Listing concrete implementations of an interface
- Quick one-level relationship check
- When you only need direct children, not full tree

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep) |
|--------|----------|----------------|
| **Accuracy** | Verifies actual inheritance via AST | Text search for `: BaseClass` is error-prone |
| **Project Filtering** | `project_only` excludes dependencies | Complex path patterns needed |
| **Metadata** | Full class info with file/line | Text matches only |
| **Speed** | Indexed query | Must scan all files |

**IMPORTANT WARNING:** This tool returns ONLY direct children (one level). For "all classes that inherit from X" including grandchildren, use `get_class_hierarchy` instead.

**Example:**
```
// If hierarchy is: Entity -> Character -> Player
get_derived_classes("Entity")  // Returns only [Character]
get_class_hierarchy("Entity")  // Returns [Character, Player]
```

**Example Output:**
```json
{
  "results": [
    {
      "name": "Button",
      "kind": "CLASS_DECL",
      "file": "/project/src/ui/Button.h",
      "line": 12,
      "column": 7,
      "is_project": true,
      "base_classes": ["Widget"]
    },
    {
      "name": "Label",
      "kind": "CLASS_DECL",
      "file": "/project/src/ui/Label.h",
      "line": 8,
      "column": 7,
      "is_project": true,
      "base_classes": ["Widget"]
    }
  ]
}
```

**Frequency Assessment:** **MEDIUM** - Useful for specific one-level queries, but `get_class_hierarchy` is often more useful.

---

### 14. find_callers

**Purpose:** Find all functions/methods that call (invoke) a specific target function through call graph analysis.

**Best Used For:**
- Impact analysis: "What breaks if I change this function?"
- Dependency analysis: "Which functions depend on this?"
- Refactoring planning: "Where is this function used?"
- Understanding function usage patterns
- Dead code detection (no callers = potentially unused)

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Grep) |
|--------|----------|----------------|
| **Accuracy** | AST-verified function calls | Text matches include comments, strings |
| **Call Graph** | Uses pre-built call graph | Must search all files |
| **Context** | Returns caller function metadata | Only text matches |
| **Scope** | `class_name` parameter to disambiguate | Complex patterns for scoping |
| **Performance** | Indexed graph query | Slow file scanning |

**IMPORTANT LIMITATION:** The `line` and `column` fields indicate where the CALLER FUNCTION IS DEFINED, not where the call happens. To find exact call site line numbers:
1. Use this tool to get caller function names and files
2. Read those files or use text search to find the specific call lines

**Example Output:**
```json
{
  "results": [
    {
      "name": "initialize",
      "kind": "CXX_METHOD",
      "file": "/project/src/Game.cpp",
      "line": 45,  // Line where initialize() is DEFINED
      "column": 6,
      "signature": "void initialize()",
      "parent_class": "Game",
      "is_project": true
    }
  ]
}
```

**Example Use Cases:**
- `find_callers("loadTexture")` - What uses this loader?
- `find_callers("update", "Player")` - What calls Player::update()?

**Frequency Assessment:** **MEDIUM-HIGH** - Essential for refactoring and impact analysis in C++ projects.

---

### 15. find_callees

**Purpose:** Find all functions/methods that are called (invoked) by a specific source function. Inverse of `find_callers`.

**Best Used For:**
- Understanding function dependencies: "What does this function rely on?"
- Analyzing code flow: "What execution path does this follow?"
- Mapping execution sequences
- Complexity analysis: "How many functions does this call?"
- Identifying coupling and code smells

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Read + Manual Analysis) |
|--------|----------|-----------------------------------|
| **Completeness** | Finds all function calls via AST | Must manually parse function body |
| **Accuracy** | Verifies actual function calls | Can miss template/macro calls |
| **Metadata** | Full info about each callee | Only text, must look up separately |
| **Speed** | Indexed call graph | Must read and parse manually |

**IMPORTANT LIMITATION:** Like `find_callers`, the `line` and `column` indicate where the CALLEE is DEFINED, not where it's called within the source function.

**Example Output:**
```json
{
  "results": [
    {
      "name": "loadAsset",
      "kind": "FUNCTION_DECL",
      "file": "/project/src/AssetManager.cpp",
      "line": 78,  // Where loadAsset() is DEFINED
      "signature": "Asset* loadAsset(const std::string& path)",
      "is_project": true
    },
    {
      "name": "logError",
      "kind": "FUNCTION_DECL",
      "file": "/project/src/Logger.cpp",
      "line": 23,
      "signature": "void logError(const std::string& message)",
      "is_project": true
    }
  ]
}
```

**Example Use Cases:**
- `find_callees("main")` - What does main() call?
- `find_callees("render", "Renderer")` - What does Renderer::render() depend on?

**Frequency Assessment:** **MEDIUM** - Useful for understanding code flow, less frequent than `find_callers`.

---

### 16. get_call_path

**Purpose:** Find execution paths through the call graph from a starting function to a target function using BFS (Breadth-First Search).

**Best Used For:**
- Understanding how function A can reach function B
- Analyzing execution flows and code paths
- Debugging: "How does execution get from main() to this function?"
- Architecture analysis: "What are the call chains between components?"
- Finding indirect dependencies

**Benefits vs Default Tools:**
| Aspect | MCP Tool | Default (Manual Tracing) |
|--------|----------|---------------------------|
| **Pathfinding** | Automatic BFS through call graph | Must manually trace calls |
| **Multiple Paths** | Finds ALL paths up to max_depth | Easy to miss alternate paths |
| **Bounded Search** | `max_depth` prevents infinite exploration | No automatic bounds |
| **Structured Output** | Clear path sequences | Unstructured notes |

**WARNING:** In highly connected codebases, can return hundreds or thousands of paths. Use `max_depth` conservatively (5-15 recommended).

**Example Output:**
```json
{
  "paths": [
    ["main", "runGame", "update", "updatePlayer", "processInput"],
    ["main", "runGame", "handleEvents", "onKeyPress", "processInput"],
    ["main", "initialize", "setupInputHandlers", "processInput"]
  ]
}
```

**Example Use Cases:**
- `get_call_path("main", "loadTexture", max_depth=10)` - How does main reach texture loading?
- `get_call_path("onUserClick", "saveFile", max_depth=5)` - What's the path from click to save?

**Performance Considerations:**
| max_depth | Small Codebase | Large Codebase |
|-----------|----------------|----------------|
| 5 | <100ms | ~1s |
| 10 | ~500ms | 5-10s |
| 15 | 1-2s | 30s+ (avoid) |

**Frequency Assessment:** **LOW-MEDIUM** - Specialized use for debugging and architecture analysis, not everyday workflow.

---

## Comparison with Default Agent Tools

### Text-Based Search (Grep) vs Semantic Search (MCP Tools)

| Feature | Grep/Text Search | MCP Semantic Search |
|---------|------------------|---------------------|
| **Accuracy** | High false positive rate | AST-verified, no false positives |
| **Context** | No structural understanding | Full language semantics |
| **Relationships** | Cannot detect inheritance/calls | Built-in relationship tracking |
| **Speed** | Must scan files repeatedly | Instant queries on indexed data |
| **Filtering** | Complex regex patterns needed | Simple parameters (project_only, class_name) |
| **Metadata** | Only line numbers | File, line, kind, signature, parent class |
| **Maintenance** | No state, always fresh | Requires refresh after edits |

**Example Comparison:**
```bash
# Grep: Find class "Player"
grep -r "class Player" .
# Results: Comments, strings, "class PlayerManager", "// Player class", etc.

# MCP: Find class "Player"
search_classes(pattern="Player")
# Results: Only actual class definition with file:line, base classes
```

### File Browsing (Read) vs Class Inspection (get_class_info)

| Feature | Read File | get_class_info |
|---------|-----------|----------------|
| **Scope** | Single file content | Aggregates from all files |
| **Parsing** | Manual interpretation | Pre-parsed structure |
| **Methods** | Mixed with other code | Extracted and sorted |
| **Inheritance** | Must find base class list | Automatically provided |
| **Cross-file** | One file at a time | Aggregates header + implementation |

### File Pattern Matching (Glob) vs Symbol Discovery (search_*)

| Feature | Glob | search_classes/functions |
|---------|------|--------------------------|
| **Target** | File names/paths | Symbol names |
| **Result Type** | File paths | Symbol definitions with metadata |
| **Use Case** | "Find files matching *.cpp" | "Find classes matching *Manager" |
| **Filtering** | Path patterns only | Semantic filters (project_only) |

---

## Frequently Used Tools (Priority Ranking)

### Tier 1: Essential Daily Use (Very High Frequency)

1. **search_classes** - Fundamental for C++ navigation
2. **search_functions** - Constant need to locate implementations
3. **get_class_info** - Understanding class APIs
4. **search_symbols** - Efficient exploratory searches

**Rationale:** These cover 80% of code exploration needs in C++ projects.

### Tier 2: Regular Use (High Frequency)

5. **get_class_hierarchy** - Critical for OOP design understanding
6. **find_callers** - Essential for refactoring and impact analysis
7. **get_function_signature** - Quick parameter lookup

**Rationale:** Used multiple times per session when working with inheritance or dependencies.

### Tier 3: Situational Use (Medium Frequency)

8. **set_project_directory** - Once per project/session
9. **refresh_project** - After code changes or git operations
10. **get_indexing_status** - Monitoring large project indexing
11. **get_derived_classes** - When only direct children needed
12. **find_callees** - Understanding function dependencies

**Rationale:** Important for workflow management and specific analysis tasks.

### Tier 4: Specialized Use (Low-Medium Frequency)

13. **wait_for_indexing** - Synchronization when needed
14. **get_call_path** - Debugging and architecture analysis
15. **find_in_file** - When file is already known
16. **get_server_status** - Debugging and verification

**Rationale:** Valuable for specific scenarios but not routine workflow.

---

## Use Case Examples

### Use Case 1: Understanding a New Codebase

**Scenario:** You're assigned to work on an unfamiliar C++ game engine.

**Workflow:**
```python
# 1. Initialize project
set_project_directory(project_path="/path/to/game-engine")
wait_for_indexing(timeout=120)

# 2. Discover main classes
search_classes(pattern=".*Engine")
# Found: GameEngine, RenderEngine, PhysicsEngine, AudioEngine

# 3. Understand architecture
get_class_hierarchy("GameEngine")
# Shows: GameEngine -> Application -> IUpdateable
#        GameEngine has children: EditorEngine, RuntimeEngine

# 4. Explore main class API
get_class_info("GameEngine")
# Shows all methods: initialize(), update(), render(), shutdown()

# 5. Understand initialization flow
find_callees("initialize", "GameEngine")
# Shows: initialize() calls loadConfig(), setupRenderer(), startPhysics()
```

**Tools Used:** 5 tools, complete understanding in minutes vs. hours of manual exploration.

---

### Use Case 2: Refactoring a Function

**Scenario:** Need to change the signature of `loadTexture()` function.

**Workflow:**
```python
# 1. Find all implementations
search_functions(pattern="loadTexture")
# Found 2 overloads in TextureManager class

# 2. Check exact signatures
get_function_signature("loadTexture", "TextureManager")
# Returns: ["TextureManager::loadTexture(const std::string& path)",
#           "TextureManager::loadTexture(int textureId)"]

# 3. Impact analysis: Find all callers
find_callers("loadTexture", "TextureManager")
# Found 23 callers across 15 files

# 4. Review caller implementations
# Read each file and update call sites
```

**Tools Used:** 3 tools, instant impact analysis vs. error-prone text search.

---

### Use Case 3: Implementing Polymorphism

**Scenario:** Need to add a new enemy type to a game using inheritance.

**Workflow:**
```python
# 1. Find the base class
search_classes(pattern="Enemy")
# Found: Enemy (base class)

# 2. See what methods to override
get_class_info("Enemy")
# Shows virtual methods: update(), render(), takeDamage(), onDeath()

# 3. Find existing implementations for reference
get_derived_classes("Enemy", project_only=True)
# Found: ZombieEnemy, FlyingEnemy, BossEnemy

# 4. Study an example implementation
get_class_info("ZombieEnemy")
# Shows which methods are overridden

# 5. Understand the full hierarchy
get_class_hierarchy("Enemy")
# Shows complete inheritance tree
```

**Tools Used:** 4 tools, clear understanding of polymorphic design.

---

### Use Case 4: Debugging a Call Chain

**Scenario:** Function `saveSettings()` is being called unexpectedly; need to find the source.

**Workflow:**
```python
# 1. Find all callers
find_callers("saveSettings")
# Found: onExit(), onConfigChange(), autoSaveTimer()

# 2. Trace backwards from suspect caller
find_callers("onConfigChange")
# Found: applyGraphicsSettings(), applyAudioSettings()

# 3. Find all paths from entry point
get_call_path("main", "saveSettings", max_depth=10)
# Shows all execution paths leading to saveSettings()
```

**Tools Used:** 3 tools, quick root cause identification.

---

### Use Case 5: Maintaining Code After Changes

**Scenario:** Just merged a feature branch with 50 file changes.

**Workflow:**
```python
# 1. Refresh index to detect changes
refresh_project(incremental=True)
# Output: "Re-analyzed 52 files in 3.2s"

# 2. Verify new classes were indexed
search_classes(pattern="FeatureX.*")
# Finds newly added classes

# 3. Check integration points
find_callers("FeatureXManager::initialize")
# Verify new feature is properly integrated
```

**Tools Used:** 3 tools, fast validation of merged changes.

---

## Recommendations

### For LLM Agents (Claude Code)

**DO:**
- ✅ Use `search_classes` and `search_functions` as first choice for C++ symbol discovery
- ✅ Call `set_project_directory` immediately when starting work on a C++ project
- ✅ Use `get_class_info` instead of reading entire files when you need class structure
- ✅ Use `get_class_hierarchy` for inheritance questions (not `get_derived_classes`)
- ✅ Call `refresh_project` after the user makes code changes
- ✅ Check `get_indexing_status` before running queries on large projects
- ✅ Prefer semantic MCP tools over Grep/Glob for C++ code analysis

**DON'T:**
- ❌ Don't use Grep to find class definitions when `search_classes` is available
- ❌ Don't manually parse function signatures when `get_function_signature` exists
- ❌ Don't trace inheritance manually when `get_class_hierarchy` provides it
- ❌ Don't forget to set project directory before using other tools
- ❌ Don't use `get_derived_classes` when you need all subclasses (use `get_class_hierarchy`)

### Configuration Recommendations

**For Best Performance:**
```json
{
  "compile_commands": {
    "enabled": true,
    "path": "build/compile_commands.json",
    "cache_enabled": true
  },
  "exclude_directories": [".git", "build", "third_party"],
  "include_dependencies": false,  // Faster indexing, focus on project code
  "max_file_size_mb": 10
}
```

**For Comprehensive Analysis:**
```json
{
  "compile_commands": {
    "enabled": true
  },
  "include_dependencies": true,  // Index third-party code too
  "exclude_directories": [".git", "build"]
}
```

### Performance Tips

1. **Use `project_only=True`** (default) to exclude dependencies for faster queries
2. **Set `max_depth` conservatively** in `get_call_path` (5-10 for large projects)
3. **Use `wait_for_indexing`** strategically, not on every query
4. **Prefer `incremental` refresh** over full refresh (30-300x faster)
5. **Enable `compile_commands.json`** for accurate parsing

---

## Conclusion

The C++ MCP Server provides a **semantic code analysis layer** that fundamentally changes how LLM agents interact with C++ codebases. By understanding code structure through AST parsing rather than text matching, it enables:

- **Faster** code navigation (indexed queries vs. file scanning)
- **More accurate** results (no false positives from text matches)
- **Deeper understanding** (relationships, hierarchies, call graphs)
- **Better UX** for users (structured, metadata-rich responses)

**Most Impactful Tools:**
1. `search_classes` - Essential symbol discovery
2. `search_functions` - Core workflow tool
3. `get_class_info` - Efficient API understanding
4. `get_class_hierarchy` - OOP design comprehension
5. `find_callers` - Refactoring and impact analysis

**Recommendation:** LLM agents should **default to using these MCP tools** for all C++ code analysis tasks, falling back to Grep/Read only when necessary (e.g., searching in non-C++ files, looking for string literals, or when MCP server is unavailable).

---

**Document Version:** 1.0
**Generated:** 2025-11-18
**Branch:** origin/compile_commands-support
