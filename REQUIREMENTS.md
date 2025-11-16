# C++ Source Code Analysis Requirements

## Document Purpose

This document captures the functional requirements for the Clang Index MCP Server, reverse-engineered from the current implementation. These requirements define what C++ entities must be analyzed, what attributes must be extracted, and what relationships must be tracked to support semantic code analysis.

## Table of Contents

1. [Core Functional Requirements](#1-core-functional-requirements)
2. [C++ Entity Extraction Requirements](#2-c-entity-extraction-requirements)
3. [Entity Relationship Requirements](#3-entity-relationship-requirements)
4. [MCP Tool Requirements](#4-mcp-tool-requirements)
5. [Compilation Configuration Requirements](#5-compilation-configuration-requirements)
6. [Caching and Performance Requirements](#6-caching-and-performance-requirements)
   - 6.6 [Failure Tracking and Retry Logic](#66-failure-tracking-and-retry-logic)
7. [Project Management Requirements](#7-project-management-requirements)
   - 7.6 [Centralized Error Logging (Developer-Only)](#76-centralized-error-logging-developer-only)
8. [Statistics and Monitoring Requirements](#8-statistics-and-monitoring-requirements)
9. [Security and Robustness Requirements](#9-security-and-robustness-requirements)
10. [Header Extraction Requirements](#10-header-extraction-requirements)

---

## 1. Core Functional Requirements

### 1.1 Symbol Analysis
**REQ-1.1.1**: The system SHALL extract and index C++ symbols from source code using libclang.

**REQ-1.1.2**: The system SHALL maintain separate indexes for:
- Classes (by name)
- Functions (by name)
- Files (by file path)
- USRs (Unified Symbol Resolution identifiers)

**REQ-1.1.3**: The system SHALL support regex pattern matching for symbol searches.

**REQ-1.1.4**: The system SHALL distinguish between project code and dependency code.

### 1.2 Parallel Processing
**REQ-1.2.1**: The system SHALL support multi-threaded indexing of source files.

**REQ-1.2.2**: The system SHALL use thread-local libclang Index instances to ensure thread safety.

**REQ-1.2.3**: The system SHALL use configurable worker threads (1-16 workers, based on CPU count × 2).

**REQ-1.2.4**: The system SHALL protect shared indexes with thread-safe locking mechanisms.

---

## 2. C++ Entity Extraction Requirements

### 2.1 Classes and Structs

#### 2.1.1 Basic Class Requirements
**REQ-2.1.1.1**: The system SHALL extract C++ class declarations (CursorKind.CLASS_DECL).

**REQ-2.1.1.2**: The system SHALL extract C++ struct declarations (CursorKind.STRUCT_DECL).

**REQ-2.1.1.3**: For each class/struct, the system SHALL extract:
- Name
- Kind (class or struct)
- File path (absolute)
- Line number
- Column number
- USR (Unique Symbol Resolution identifier)
- Base class names
- Whether it's in project code or dependency code

#### 2.1.2 Class Variants
**REQ-2.1.2.1**: The system SHALL support extraction of:
- Regular classes
- Template classes
- Nested classes (within other classes or namespaces)
- Forward-declared classes
- Anonymous structs/unions
- Abstract classes (with pure virtual methods)

#### 2.1.3 Inheritance Information
**REQ-2.1.3.1**: The system SHALL extract base class information via CXX_BASE_SPECIFIER cursors.

**REQ-2.1.3.2**: The system SHALL support:
- Single inheritance
- Multiple inheritance
- Virtual inheritance
- Inheritance access specifiers (public/private/protected)

**REQ-2.1.3.3**: The system SHALL normalize base class names by removing "class " prefix if present.

### 2.2 Functions and Methods

#### 2.2.1 Basic Function Requirements
**REQ-2.2.1.1**: The system SHALL extract function declarations (CursorKind.FUNCTION_DECL).

**REQ-2.2.1.2**: The system SHALL extract method declarations (CursorKind.CXX_METHOD).

**REQ-2.2.1.3**: For each function/method, the system SHALL extract:
- Name
- Kind (function or method)
- File path (absolute)
- Line number
- Column number
- Signature (complete type signature)
- USR (Unique Symbol Resolution identifier)
- Parent class name (for methods only)
- Access level (public/private/protected)
- Whether it's in project code or dependency code

#### 2.2.2 Function Variants
**REQ-2.2.2.1**: The system SHALL support extraction of:
- Global functions
- Static functions
- Inline functions
- Constexpr functions
- Template functions
- Function overloads (multiple functions with same name, different signatures)
- Variadic functions
- Friend functions
- Operator overload functions
- Functions defined in header files (.h, .hpp, .hxx, .h++)
- Functions defined in implementation files (.cpp, .cc, .cxx, .c++)

#### 2.2.3 Method Variants
**REQ-2.2.3.1**: The system SHALL support extraction of:
- Regular member methods
- Static member methods
- Const methods
- Virtual methods
- Pure virtual methods
- Override methods
- Final methods
- Constructors (default, parameterized, copy, move)
- Destructors (regular and virtual)
- Operator overload methods

#### 2.2.4 Template Support
**REQ-2.2.4.1**: The system SHALL support:
- Class templates
- Function templates
- Template specializations (full and partial)
- Variadic templates
- Template member functions

### 2.3 Namespaces

**REQ-2.3.1**: The system SHALL track namespace information for symbols.

**REQ-2.3.2**: The system SHALL support:
- Named namespaces
- Anonymous namespaces
- Nested namespaces
- Namespace aliases

**REQ-2.3.3**: The system SHALL store namespace context in the `namespace` field of SymbolInfo.

### 2.4 Call Graph Extraction

**REQ-2.4.1**: The system SHALL extract function call relationships (CursorKind.CALL_EXPR).

**REQ-2.4.2**: The system SHALL track:
- Which functions call which other functions (forward call graph)
- Which functions are called by which other functions (reverse call graph)

**REQ-2.4.3**: The system SHALL link function calls using USR identifiers for accurate resolution.

**REQ-2.4.4**: The system SHALL support call graph for:
- Direct function calls
- Method calls (object.method())
- Static method calls (Class::method())
- Virtual function calls
- Function pointer calls (to the extent libclang can resolve)

---

## 3. Entity Relationship Requirements

### 3.1 Inheritance Relationships

**REQ-3.1.1**: The system SHALL maintain bidirectional inheritance relationships:
- Base classes → Derived classes (forward)
- Derived classes → Base classes (backward)

**REQ-3.1.2**: The system SHALL support querying complete inheritance hierarchies recursively.

**REQ-3.1.3**: The system SHALL detect and handle circular inheritance references gracefully.

**REQ-3.1.4**: **Purpose**: Enable clients to understand class hierarchies, find all implementations of interfaces, and trace inheritance chains for polymorphic behavior analysis.

### 3.2 Containment Relationships

**REQ-3.2.1**: The system SHALL track which methods belong to which classes via the `parent_class` field.

**REQ-3.2.2**: The system SHALL support queries for all methods of a specific class.

**REQ-3.2.3**: **Purpose**: Enable clients to understand class structure and find all operations available on a class.

### 3.3 Call Graph Relationships

**REQ-3.3.1**: The system SHALL maintain a bidirectional call graph:
- caller_usr → [callee_usr, ...] (forward: what does X call?)
- callee_usr → [caller_usr, ...] (reverse: who calls X?)

**REQ-3.3.2**: The system SHALL support finding call paths between two functions using breadth-first search.

**REQ-3.3.3**: The system SHALL support configurable maximum search depth for path finding (default: 10).

**REQ-3.3.4**: **Purpose**: Enable clients to:
- Understand function dependencies
- Trace execution flows
- Identify impact of changes (who calls this function?)
- Find how to reach a function (what path gets me there?)

### 3.4 File Membership Relationships

**REQ-3.4.1**: The system SHALL track which symbols are defined in which files.

**REQ-3.4.2**: The system SHALL support queries for all symbols in a specific file.

**REQ-3.4.3**: **Purpose**: Enable file-scoped analysis and understanding of file organization.

### 3.5 Project vs. Dependency Relationships

**REQ-3.5.1**: The system SHALL classify each symbol as either:
- Project code (is_project = true)
- Dependency code (is_project = false)

**REQ-3.5.2**: The system SHALL support filtering queries by project-only vs. all code.

**REQ-3.5.3**: The system SHALL determine project membership by checking if a file is:
- Under the project root
- NOT in a designated dependency directory (vcpkg_installed, third_party, external, etc.)
- NOT in a system header location

**REQ-3.5.4**: **Purpose**: Enable clients to focus on project code while excluding third-party dependencies from analysis results.

---

## 4. MCP Tool Requirements

The system provides 14 MCP tools. Each tool has specific requirements for inputs, outputs, and behavior.

### 4.1 search_classes

**REQ-4.1.1**: SHALL accept:
- `pattern`: string (regex pattern)
- `project_only`: boolean (default: true)

**REQ-4.1.2**: SHALL return for each matching class:
- name
- kind (class or struct)
- file
- line
- is_project
- base_classes (list)

**REQ-4.1.3**: SHALL support case-insensitive regex pattern matching.

**REQ-4.1.4**: SHALL filter by project_only flag when true.

### 4.2 search_functions

**REQ-4.2.1**: SHALL accept:
- `pattern`: string (regex pattern)
- `project_only`: boolean (default: true)
- `class_name`: optional string (filter by containing class)

**REQ-4.2.2**: SHALL return for each matching function:
- name
- kind (function or method)
- file
- line
- signature
- is_project
- parent_class

**REQ-4.2.3**: SHALL support case-insensitive regex pattern matching.

**REQ-4.2.4**: SHALL filter by class_name when provided (methods only from that class).

### 4.3 get_class_info

**REQ-4.3.1**: SHALL accept:
- `class_name`: string (exact class name)

**REQ-4.3.2**: SHALL return:
- name
- kind
- file
- line
- base_classes (list)
- methods (list with name, signature, access, line)
- is_project

**REQ-4.3.3**: SHALL sort methods by line number.

**REQ-4.3.4**: SHALL return null/error if class not found.

### 4.4 get_function_signature

**REQ-4.4.1**: SHALL accept:
- `function_name`: string (exact function name)
- `class_name`: optional string (filter by class)

**REQ-4.4.2**: SHALL return list of signatures:
- For methods: "ClassName::functionName(signature)"
- For functions: "functionName(signature)"

**REQ-4.4.3**: SHALL handle function overloads by returning all matching signatures.

### 4.5 search_symbols

**REQ-4.5.1**: SHALL accept:
- `pattern`: string (regex pattern)
- `project_only`: boolean (default: true)
- `symbol_types`: optional array of strings (["class", "struct", "function", "method"])

**REQ-4.5.2**: SHALL return dictionary with keys:
- "classes": list of class matches
- "functions": list of function matches

**REQ-4.5.3**: SHALL filter by symbol_types when provided.

### 4.6 find_in_file

**REQ-4.6.1**: SHALL accept:
- `file_path`: string (relative path from project root)
- `pattern`: string (symbol pattern)

**REQ-4.6.2**: SHALL return all symbols matching pattern in the specified file.

**REQ-4.6.3**: SHALL resolve both relative and absolute file paths.

### 4.7 set_project_directory

**REQ-4.7.1**: SHALL accept:
- `project_path`: string (absolute path)

**REQ-4.7.2**: SHALL validate:
- Path is non-empty
- Path has no leading/trailing whitespace
- Path is absolute
- Directory exists

**REQ-4.7.3**: SHALL initialize analyzer and start background indexing.

**REQ-4.7.4**: SHALL return count of indexed files.

**REQ-4.7.5**: SHALL be required before any other tools can be used.

### 4.8 refresh_project

**REQ-4.8.1**: SHALL accept no parameters.

**REQ-4.8.2**: SHALL re-parse modified or new files.

**REQ-4.8.3**: SHALL remove deleted files from indexes.

**REQ-4.8.4**: SHALL return count of refreshed files.

**REQ-4.8.5**: SHALL update compile_commands.json if changed.

### 4.9 get_server_status

**REQ-4.9.1**: SHALL accept no parameters.

**REQ-4.9.2**: SHALL return:
- analyzer_type
- call_graph_enabled
- usr_tracking_enabled
- compile_commands_enabled
- compile_commands_path
- compile_commands_cache_enabled
- parsed_files count
- indexed_classes count
- indexed_functions count
- project_files count

### 4.10 get_class_hierarchy

**REQ-4.10.1**: SHALL accept:
- `class_name`: string (name of class)

**REQ-4.10.2**: SHALL return:
- class_info (detailed class information)
- base_classes (direct base classes, list of names)
- derived_classes (direct derived classes, list)
- base_hierarchy (recursive base class tree)
- derived_hierarchy (recursive derived class tree)

**REQ-4.10.3**: SHALL handle circular references by marking them.

**REQ-4.10.4**: SHALL search entire codebase including dependencies for hierarchy.

### 4.11 get_derived_classes

**REQ-4.11.1**: SHALL accept:
- `class_name`: string (base class name)
- `project_only`: boolean (default: true)

**REQ-4.11.2**: SHALL return all classes that directly inherit from the base class.

**REQ-4.11.3**: SHALL include:
- name
- kind
- file
- line
- column
- is_project
- base_classes (list)

### 4.12 find_callers

**REQ-4.12.1**: SHALL accept:
- `function_name`: string (function name to find callers for)
- `class_name`: optional string (if searching for a method)

**REQ-4.12.2**: SHALL return all functions that call the specified function.

**REQ-4.12.3**: SHALL include:
- name
- kind
- file
- line
- column
- signature
- parent_class
- is_project

**REQ-4.12.4**: SHALL use USR-based matching for accurate identification.

### 4.13 find_callees

**REQ-4.13.1**: SHALL accept:
- `function_name`: string (function name to find callees for)
- `class_name`: optional string (if searching for a method)

**REQ-4.13.2**: SHALL return all functions called by the specified function.

**REQ-4.13.3**: SHALL include:
- name
- kind
- file
- line
- column
- signature
- parent_class
- is_project

**REQ-4.13.4**: SHALL use USR-based matching for accurate identification.

### 4.14 get_call_path

**REQ-4.14.1**: SHALL accept:
- `from_function`: string (starting function name)
- `to_function`: string (target function name)
- `max_depth`: integer (default: 10)

**REQ-4.14.2**: SHALL return list of call paths, where each path is a list of function names.

**REQ-4.14.3**: SHALL use breadth-first search to find paths.

**REQ-4.14.4**: SHALL format method names as "ClassName::methodName".

**REQ-4.14.5**: SHALL respect max_depth limit to prevent infinite searches.

---

## 5. Compilation Configuration Requirements

### 5.1 compile_commands.json Support

**REQ-5.1.1**: The system SHALL support loading compilation commands from `compile_commands.json`.

**REQ-5.1.2**: The system SHALL parse JSON format with entries containing:
- `file`: source file path
- `directory`: working directory for compilation
- `command`: full compilation command string, OR
- `arguments`: array of compilation arguments

**REQ-5.1.3**: The system SHALL normalize file paths to absolute paths.

**REQ-5.1.4**: The system SHALL build a mapping from file paths to compilation arguments.

**REQ-5.1.5**: The system SHALL use compilation arguments for accurate parsing with libclang.

**REQ-5.1.6**: The system SHALL support configurable compile_commands.json path (default: "compile_commands.json" in project root).

### 5.2 Compilation Argument Fallback

**REQ-5.2.1**: The system SHALL provide fallback compilation arguments when compile_commands.json is not available.

**REQ-5.2.2**: Fallback arguments SHALL include:
- C++ standard flag (-std=c++17)
- Project include paths (-I. -I<project_root> -I<project_root>/src)
- Common preprocessor defines (WIN32, _WIN32, _WINDOWS, NOMINMAX)
- Warning suppressions (-Wno-pragma-once-outside-header, etc.)
- C++ mode flag (-x c++)

**REQ-5.2.3**: On Windows, fallback arguments SHALL include Windows SDK include paths:
- C:/Program Files (x86)/Windows Kits/10/Include/\*/ucrt
- C:/Program Files (x86)/Windows Kits/10/Include/\*/um
- C:/Program Files (x86)/Windows Kits/10/Include/\*/shared

**REQ-5.2.4**: The system SHALL support disabling fallback arguments via configuration.

### 5.3 Compile Commands Caching

**REQ-5.3.1**: The system SHALL cache parsed compile commands in memory.

**REQ-5.3.2**: The system SHALL track last modification time of compile_commands.json.

**REQ-5.3.3**: The system SHALL refresh compile commands if the file is modified.

**REQ-5.3.4**: The system SHALL support configurable cache expiry (default: 300 seconds).

**REQ-5.3.5**: The system SHALL support disabling compile commands caching via configuration.

### 5.4 File Extension Support

**REQ-5.4.1**: The system SHALL support the following C++ file extensions:
- Implementation files: .cpp, .cc, .cxx, .c++
- Header files: .h, .hpp, .hxx, .h++

**REQ-5.4.2**: The system SHALL allow configuring supported extensions.

### 5.5 vcpkg Integration

**REQ-5.5.1**: The system SHALL automatically detect vcpkg installations by looking for `vcpkg_installed/` directory in project root.

**REQ-5.5.2**: The system SHALL add vcpkg include paths to fallback compilation arguments:
- `vcpkg_installed/{triplet}/include`
- For all triplet subdirectories found

**REQ-5.5.3**: vcpkg paths SHALL be added when compile_commands.json is not available or fallback is enabled.

### 5.6 Compile Commands Manager Extended APIs

**REQ-5.6.1**: The system SHALL provide `get_stats()` API returning:
- `enabled`: Whether compile commands are active
- `compile_commands_count`: Total compile command entries
- `file_mapping_count`: Files with compile commands available
- `cache_enabled`: Whether caching is enabled
- `fallback_enabled`: Whether fallback arguments are used
- `last_modified`: Last modification timestamp of compile_commands.json
- `compile_commands_path`: Full path to compile commands file

**REQ-5.6.2**: The system SHALL provide `is_file_supported(file_path)` API to check if a specific file has compile commands available.

**REQ-5.6.3**: The system SHALL provide `get_all_files()` API returning list of all files with compile commands.

**REQ-5.6.4**: The system SHALL provide `should_process_file(file_path)` API to determine if a file should be indexed based on compile commands availability or supported extensions.

**REQ-5.6.5**: The system SHALL provide `is_extension_supported(file_path)` API to check if file extension is in supported list.

**REQ-5.6.6**: The system SHALL provide `clear_cache()` API to manually invalidate and clear compile commands cache.

---

## 6. Caching and Performance Requirements

### 6.1 Symbol Cache

**REQ-6.1.1**: The system SHALL cache parsed symbols to disk in `.mcp_cache/` directory.

**REQ-6.1.2**: The cache SHALL be stored in the MCP server directory (NOT the project being analyzed), using structure: `.mcp_cache/{project_name}_{hash}/` where hash is MD5 of project absolute path.

**REQ-6.1.3**: The system SHALL save per-file caches for individual source files in `files/` subdirectory, with filenames generated by MD5-hashing the file's absolute path.

**REQ-6.1.4**: The system SHALL save overall index cache with:
- class_index
- function_index
- file_hashes
- indexed_file_count
- Configuration file metadata (path, mtime)
- Compile commands metadata (path, mtime)

### 6.2 Cache Invalidation

**REQ-6.2.1**: The system SHALL use file content hashing (MD5) for change detection.

**REQ-6.2.2**: The system SHALL invalidate cache when:
- File content changes (hash mismatch)
- Configuration file (.cpp-analyzer-config.json) is modified
- compile_commands.json is modified
- include_dependencies setting changes

**REQ-6.2.3**: The system SHALL track modification times (mtime) for:
- Configuration file
- compile_commands.json

**REQ-6.2.4**: The system SHALL reindex files whose cache is invalidated.

**REQ-6.2.5**: The system SHALL invalidate cache when cache version number changes (prevents loading incompatible cache formats).

**REQ-6.2.6**: The system SHALL compute and validate compilation arguments hash for per-file caches.

**REQ-6.2.7**: The system SHALL invalidate per-file cache when compilation arguments change (different -I flags, defines, standard version, etc.).

**REQ-6.2.8**: The system SHALL use MD5 hash of sorted compilation arguments for consistency (order-independent comparison).

**REQ-6.2.9**: Per-file cache version SHALL be bumped from 1.1 to 1.2 when compilation arguments tracking is added.

### 6.3 Cache Loading

**REQ-6.3.1**: The system SHALL attempt to load from cache before re-parsing files.

**REQ-6.3.2**: The system SHALL validate cache compatibility:
- Check cache version
- Check configuration changes
- Check compile_commands.json changes
- Check file hashes

**REQ-6.3.3**: The system SHALL fall back to full re-parsing if cache is invalid.

**REQ-6.3.4**: The system SHALL rebuild USR index and call graph from cached symbols.

### 6.4 Performance Optimizations

**REQ-6.4.1**: The system SHALL use TranslationUnit caching for parsed files.

**REQ-6.4.2**: The system SHALL parse files with options:
- PARSE_INCOMPLETE (for partial analysis)
- PARSE_DETAILED_PROCESSING_RECORD (for detailed diagnostics)

**REQ-6.4.3**: The system SHALL NOT skip function bodies (to enable call graph analysis).

**REQ-6.4.4**: The system SHALL report indexing progress:
- In terminal mode: Live progress updates (every 5 files or 2 seconds)
- In non-terminal mode: Periodic updates (every 50 files or 5 seconds)

**REQ-6.4.5**: Progress reporting SHALL include:
- Files processed / Total files
- Success count
- Failed count
- Cache hit count and rate
- Processing rate (files/sec)
- Estimated time remaining (ETA)

**REQ-6.4.6**: The system SHALL detect environment variables to determine output mode:
- `MCP_SESSION_ID`: Indicates MCP server environment (non-interactive mode)
- `CLAUDE_CODE_SESSION`: Indicates Claude Code environment (non-interactive mode)
- When either is set, use non-interactive progress reporting

**REQ-6.4.7**: The system SHALL adapt progress reporting frequency based on environment:
- Terminal mode (isatty and no MCP/Claude env vars): Every 5 files or 2 seconds
- Non-terminal mode (pipes, MCP, Claude): Every 50 files or 5 seconds

### 6.5 Progress Persistence

**REQ-6.5.1**: The system SHALL persist indexing progress to `indexing_progress.json` in the cache directory.

**REQ-6.5.2**: Progress file SHALL include:
- `project_root`: Absolute path to indexed project
- `total_files`: Total files to index
- `indexed_files`: Number of files successfully indexed
- `failed_files`: Number of files that failed to index
- `cache_hits`: Number of files loaded from cache
- `last_index_time`: Duration of indexing operation in seconds
- `timestamp`: ISO format timestamp when progress was saved
- `class_count`: Number of classes in index
- `function_count`: Number of functions in index
- `status`: One of "in_progress", "complete", or "interrupted"

**REQ-6.5.3**: The system SHALL save progress:
- When indexing starts (status: "in_progress")
- When indexing completes successfully (status: "complete")
- Periodically during long-running operations

**REQ-6.5.4**: The system SHALL provide API to load previous progress for:
- Resuming interrupted indexing sessions
- Displaying indexing history
- Monitoring external indexing processes

**REQ-6.5.5**: The system SHALL set status to "interrupted" if indexing fails or is cancelled.

### 6.6 Failure Tracking and Retry Logic

**REQ-6.6.1**: The system SHALL track parsing failures in per-file cache with metadata:
- `success`: Boolean indicating if parse succeeded
- `error_message`: Error description (truncated to 200 chars for cache)
- `retry_count`: Number of times parsing has been attempted

**REQ-6.6.2**: The system SHALL save failure information to cache when files fail to parse.

**REQ-6.6.3**: The system SHALL support configurable maximum retry count via `max_parse_retries` configuration (default: 2).

**REQ-6.6.4**: The system SHALL implement intelligent retry logic:
- If `retry_count < max_parse_retries`: Retry parsing the file
- If `retry_count >= max_parse_retries`: Skip file with debug log message

**REQ-6.6.5**: The system SHALL log retry attempts with:
- Attempt number (e.g., "attempt 1/3")
- Last error message
- File path

**REQ-6.6.6**: The system SHALL reset retry count to 0 when a previously failed file is successfully parsed.

**REQ-6.6.7**: The system SHALL invalidate failure cache when:
- File content changes
- Compilation arguments change
- User forces re-indexing

**REQ-6.6.8**: Cache version SHALL be bumped from 1.1 to 1.2 to include failure tracking fields.

**REQ-6.6.9**: The system SHALL maintain backward compatibility with v1.1 caches (default `success=True`, `retry_count=0`).

**REQ-6.6.10**: **Purpose**: Prevent wasting time re-parsing files that consistently fail (missing dependencies, syntax errors) while still allowing retries in case issues are fixed.

---

## 7. Project Management Requirements

### 7.1 Configuration File

**REQ-7.1.1**: The system SHALL support configuration file named `.cpp-analyzer-config.json`.

**REQ-7.1.2**: Configuration file locations SHALL be checked in order:
1. Environment variable CPP_ANALYZER_CONFIG
2. Project root directory

**REQ-7.1.3**: Configuration SHALL support:
- `exclude_directories`: List of directories to exclude (default: .git, .svn, node_modules, etc.)
- `dependency_directories`: List of directories containing dependencies (default: vcpkg_installed, third_party, external, etc.)
- `exclude_patterns`: List of file patterns to exclude (e.g., "*.generated.h")
- `include_dependencies`: Boolean flag to include dependency code (default: true)
- `max_file_size_mb`: Maximum file size in MB (default: 10)
- `max_parse_retries`: Maximum retry attempts for failed files (default: 2)
- `compile_commands`: Compilation configuration (see REQ-5.1.6)
- `diagnostics`: Diagnostic logging configuration

**REQ-7.1.4**: The system SHALL merge user configuration with default configuration (user takes precedence).

**REQ-7.1.5**: The system SHALL use default configuration if no config file is found.

**REQ-7.1.6**: The system SHALL validate configuration file format:
- Configuration file MUST be a JSON object (dict), not a JSON array
- If JSON array is detected, log clear error message indicating likely mistake
- Suggest possible causes (e.g., using compile_commands.json instead of .cpp-analyzer-config.json)
- Fall back to default configuration on validation failure

**REQ-7.1.7**: The system SHALL provide actionable error messages when config validation fails:
- "Invalid config file format at <path>"
- "Expected a JSON object (dict), but got <type>"
- "Note: If you see 'compile_commands.json' here, you may have:"
  - "Set CPP_ANALYZER_CONFIG environment variable to wrong file"
  - "Named .cpp-analyzer-config.json incorrectly"

**REQ-7.1.8**: The system SHALL add debug logging for config file discovery:
- Log when loading from CPP_ANALYZER_CONFIG environment variable
- Log when loading from project root
- Log when no config file is found

### 7.2 File Discovery

**REQ-7.2.1**: The system SHALL recursively scan the project directory for C++ files.

**REQ-7.2.2**: The system SHALL filter directories based on:
- Top-level exclude directories (only direct children of project root)
- Not walking into excluded directories

**REQ-7.2.3**: The system SHALL skip files based on:
- File is in excluded directory
- File size exceeds max_file_size_mb
- File matches exclude pattern

**REQ-7.2.4**: The system SHALL distinguish between project files and dependency files:
- Dependency files: In dependency_directories (at any nesting level)
- Project files: All other files under project root

### 7.3 Libclang Library Loading

**REQ-7.3.1**: The system SHALL search for libclang in the following order:
1. Bundled library (lib/{windows|macos|linux}/)
2. System-installed library (platform-specific paths)
3. LLVM install paths (via llvm-config)

**REQ-7.3.2**: Platform-specific library names:
- Windows: libclang.dll or clang.dll
- macOS: libclang.dylib
- Linux: libclang.so.1 or libclang.so

**REQ-7.3.3**: The system SHALL report which libclang library is being used.

**REQ-7.3.4**: The system SHALL fail with clear error message if libclang cannot be found.

### 7.4 Error Handling

**REQ-7.4.1**: The system SHALL handle parsing errors gracefully:
- Log errors for diagnostic purposes
- Continue processing other files
- Track failed file count
- Do not fail entire indexing operation

**REQ-7.4.2**: The system SHALL handle missing files gracefully:
- Detect deleted files during refresh
- Remove from all indexes (class_index, function_index, file_index, usr_index)
- Remove from call graph (both forward and reverse)
- Delete per-file cache entry via `remove_file_cache(file_path)` API

**REQ-7.4.3**: The system SHALL handle libclang diagnostics:
- Parse compilation errors/warnings
- Log at appropriate level
- Do not block indexing for warnings

### 7.5 Diagnostics and Logging

**REQ-7.5.1**: The system SHALL support diagnostic levels:
- debug
- info
- warning
- error
- fatal

**REQ-7.5.2**: The system SHALL output diagnostics to stderr.

**REQ-7.5.3**: The system SHALL support configuring diagnostic level via:
- Configuration file: `diagnostics.level` (values: "debug", "info", "warning", "error", "fatal")
- Environment variable: `CPP_ANALYZER_DIAGNOSTIC_LEVEL` (takes precedence)
- Programmatic API: `DiagnosticLogger.set_level(level)`

**REQ-7.5.4**: The system SHALL support enabling/disabling diagnostics via:
- Configuration file: `diagnostics.enabled` (boolean)
- Programmatic API: `DiagnosticLogger.set_enabled(enabled)`

**REQ-7.5.5**: The system SHALL provide `DiagnosticLogger` class with APIs:
- `set_level(level)`: Change minimum output level at runtime
- `set_output_stream(stream)`: Redirect diagnostics output (default: stderr)
- `set_enabled(enabled)`: Enable or disable all diagnostic output
- `debug(message)`, `info(message)`, `warning(message)`, `error(message)`, `fatal(message)`: Log at specific levels

**REQ-7.5.6**: The system SHALL provide `configure_from_config(config_dict)` function to configure diagnostics from configuration dictionary.

### 7.6 Centralized Error Logging (Developer-Only)

**REQ-7.6.1**: The system SHALL maintain a centralized error log for all parsing failures at `.mcp_cache/{project}/parse_errors.jsonl`.

**REQ-7.6.2**: The error log SHALL use JSONL format (JSON Lines - one JSON object per line) for:
- Easy streaming and appending
- Partial file reading capabilities
- Line-by-line processing without loading entire file

**REQ-7.6.3**: Each error log entry SHALL include:
- `timestamp`: Unix timestamp (float)
- `timestamp_readable`: Human-readable timestamp (YYYY-MM-DD HH:MM:SS)
- `file_path`: Absolute path to file that failed
- `error_type`: Exception class name (e.g., ValueError, RuntimeError)
- `error_message`: Full error message (not truncated)
- `stack_trace`: Complete Python stack trace for debugging
- `file_hash`: MD5 hash of file content
- `compile_args_hash`: MD5 hash of compilation arguments
- `retry_count`: Current retry attempt number

**REQ-7.6.4**: The system SHALL automatically log errors when `CppAnalyzer.index_file()` catches exceptions during parsing.

**REQ-7.6.5**: Error logging SHALL NOT expose errors to LLM via MCP tools - it is strictly for developer analysis.

**REQ-7.6.6**: The system SHALL provide `CacheManager.log_parse_error()` API for logging errors with parameters:
- `file_path`: str
- `error`: Exception object
- `file_hash`: str
- `compile_args_hash`: Optional[str]
- `retry_count`: int

**REQ-7.6.7**: The system SHALL provide `CacheManager.get_parse_errors()` API with parameters:
- `limit`: Optional[int] - Maximum errors to return (most recent first)
- `file_path_filter`: Optional[str] - Substring filter for file paths
- Returns: List[Dict[str, Any]] sorted by timestamp descending

**REQ-7.6.8**: The system SHALL provide `CacheManager.get_error_summary()` API returning:
- `total_errors`: Total number of logged errors
- `unique_files`: Count of unique files with errors
- `error_types`: Dict[str, int] - Count of each error type
- `recent_errors`: List of 10 most recent errors
- `error_log_path`: Absolute path to error log file

**REQ-7.6.9**: The system SHALL provide `CacheManager.clear_error_log()` API with parameters:
- `older_than_days`: Optional[int] - If specified, only clear errors older than N days
- Returns: int - Number of errors cleared

**REQ-7.6.10**: The system SHALL provide `CppAnalyzer` wrapper methods delegating to CacheManager:
- `get_parse_errors(limit, file_path_filter)`
- `get_error_summary()`
- `clear_error_log(older_than_days)`

**REQ-7.6.11**: The system SHALL provide developer utility script `scripts/view_parse_errors.py` with features:
- View recent errors: `view_parse_errors.py <project_root>`
- Show summary: `--summary` flag
- Filter by file: `--filter "filename"` option
- Limit results: `--limit N` option
- Show stack traces: `--verbose` flag
- Clear old errors: `--clear-old DAYS` option
- Clear all errors: `--clear-all` flag

**REQ-7.6.12**: Error logging SHALL be resilient and never break main indexing flow:
- Wrap logging in try/except
- Print error to stderr if logging fails
- Return boolean success status

**REQ-7.6.13**: Error log operations SHALL handle missing/corrupted files gracefully:
- Return empty list if log file doesn't exist
- Skip malformed JSON lines (catch JSONDecodeError)
- Continue processing valid lines even if some are corrupt

**REQ-7.6.14**: **Purpose**: Enable developers to:
- Analyze patterns in parsing failures across the codebase
- Debug specific parsing errors with full stack traces
- Track error frequency and identify problematic files
- Monitor parsing health over time
- Identify missing dependencies or configuration issues

---

## 8. Statistics and Monitoring Requirements

### 8.1 Runtime Statistics APIs

**REQ-8.1.1**: The system SHALL provide `CppAnalyzer.get_stats()` API returning runtime statistics:
- `class_count`: Number of unique class names in index
- `function_count`: Number of unique function names in index
- `file_count`: Number of indexed files
- `compile_commands_enabled`: Whether compile commands are active (if enabled)
- `compile_commands_count`: Number of compile command entries (if enabled)
- `compile_commands_file_mapping_count`: Number of files with compile commands (if enabled)

**REQ-8.1.2**: The system SHALL provide `CppAnalyzer.get_compile_commands_stats()` API returning detailed compile commands statistics (delegates to CompileCommandsManager.get_stats()).

**REQ-8.1.3**: Statistics APIs SHALL be thread-safe and use appropriate locking when accessing shared data structures.

### 8.2 Call Graph Statistics

**REQ-8.2.1**: The system SHALL provide `CallGraphAnalyzer.get_call_statistics()` API returning call graph metrics:
- `total_functions_with_calls`: Count of functions that call other functions
- `total_functions_being_called`: Count of functions that are called by others
- `total_unique_calls`: Total number of call relationships
- `most_called_functions`: Top 10 most frequently called functions (list of tuples: USR, call count)
- `functions_with_most_calls`: Top 10 functions making the most calls (list of tuples: USR, call count)

**REQ-8.2.2**: Call graph statistics SHALL enable code quality analysis:
- Identify central/critical functions (most called)
- Detect potential dead code (never called functions)
- Find complex functions (making many calls)
- Support performance analysis and refactoring decisions

### 8.3 Cache Management APIs

**REQ-8.3.1**: The system SHALL provide `CacheManager.remove_file_cache(file_path)` API to delete per-file cache entry.

**REQ-8.3.2**: The system SHALL provide `CacheManager.get_file_cache_path(file_path)` API returning Path to per-file cache file.

**REQ-8.3.3**: Cache management APIs SHALL return success/failure status for error handling.

---

## 9. Security and Robustness Requirements

### 9.1 Input Validation and Sanitization

**REQ-9.1.1**: The system SHALL validate and sanitize all file paths to prevent path traversal attacks.

**REQ-9.1.2**: Path validation SHALL reject or safely handle:
- Relative path traversal (../, ..\)
- Absolute paths outside project root
- URL-encoded path traversal
- UNC paths to network shares
- File URL schemes

**REQ-9.1.3**: The system SHALL protect against regex Denial of Service (ReDoS) attacks by:
- Setting timeouts on regex matching operations (< 2 seconds per pattern)
- Validating patterns for catastrophic backtracking potential
- Limiting regex complexity

**REQ-9.1.4**: The system SHALL NOT execute commands from compile_commands.json, only parse them for compiler flags.

**REQ-9.1.5**: The system SHALL sanitize command strings to remove shell metacharacters (;, |, &, $(), `).

**REQ-9.1.6**: The system SHALL validate configuration values:
- Enforce reasonable bounds on numeric values (0-1000 MB for file sizes)
- Reject negative values where inappropriate
- Validate path values for traversal attempts
- Sanitize string values for injection attacks

### 9.2 Symlink and File System Security

**REQ-9.2.1**: The system SHALL detect symbolic links and handle them securely.

**REQ-9.2.2**: The system SHALL NOT follow symlinks that point outside the project boundary.

**REQ-9.2.3**: The system SHALL prevent circular symlink traversal (detect and break cycles).

**REQ-9.2.4**: The system SHALL respect project boundaries when following symlinks.

### 9.3 Data Integrity and Atomic Operations

**REQ-9.3.1**: Cache file writes SHALL be atomic (write to temporary file, then rename).

**REQ-9.3.2**: The system SHALL use file locking or other mechanisms to prevent concurrent cache corruption.

**REQ-9.3.3**: The system SHALL validate cache file integrity before loading:
- Check JSON structure validity
- Validate required fields presence
- Verify data types correctness
- Detect null bytes and invalid UTF-8

**REQ-9.3.4**: The system SHALL gracefully recover from corrupted cache files by rebuilding.

**REQ-9.3.5**: The system SHALL detect and handle interrupted indexing operations:
- Save progress status ("in_progress", "complete", "interrupted")
- Allow resume or clean restart after interruption

### 9.4 Error Resilience

**REQ-9.4.1**: The system SHALL handle file system errors gracefully:
- Permission denied errors (log warning, continue with accessible files)
- Disk full errors (fail gracefully with clear error message)
- Network filesystem errors (timeout after reasonable period, retry with exponential backoff)

**REQ-9.4.2**: The system SHALL handle malformed input files:
- Invalid JSON in compile_commands.json (fall back to hardcoded arguments)
- Invalid JSON in cache files (rebuild cache)
- Corrupt source files with null bytes (skip or handle gracefully)
- Invalid UTF-8 sequences (use replacement character or skip)

**REQ-9.4.3**: The system SHALL continue indexing when individual files fail to parse.

**REQ-9.4.4**: The system SHALL set appropriate timeouts for file operations to prevent hanging.

**REQ-9.4.5**: The system SHALL implement retry logic (2-3 attempts with backoff) for transient failures.

### 9.5 Resource Limits and DoS Protection

**REQ-9.5.1**: The system SHALL enforce maximum file size limits (configurable, default: 10MB).

**REQ-9.5.2**: The system SHALL handle extremely long symbol names (5000+ characters) without truncation or error.

**REQ-9.5.3**: The system SHALL handle deep inheritance hierarchies (100+ levels) without stack overflow.

**REQ-9.5.4**: The system SHALL handle many function overloads (50+) efficiently.

**REQ-9.5.5**: The system SHALL prevent memory exhaustion through appropriate resource limits and cleanup.

### 9.6 Platform-Specific Security

**REQ-9.6.1**: On Windows, the system SHALL handle path length limits (MAX_PATH = 260 characters) using long path APIs or graceful degradation.

**REQ-9.6.2**: On Unix systems, the system SHALL respect file permissions and handle permission errors gracefully.

**REQ-9.6.3**: The system SHALL normalize path separators appropriately for the platform (/ on Unix, \ on Windows).

**REQ-9.6.4**: The system SHALL handle platform-specific file system features:
- Windows: file locking, case-insensitive paths
- Unix: symbolic links, file permissions
- macOS: resource forks, .DS_Store files

### 9.7 Concurrent Access Protection

**REQ-9.7.1**: The system SHALL protect shared data structures with thread-safe locking mechanisms.

**REQ-9.7.2**: The system SHALL prevent race conditions in cache writes through file locking.

**REQ-9.7.3**: The system SHALL handle concurrent file modifications gracefully (use original content or retry).

**REQ-9.7.4**: The system SHALL ensure progress reporting is thread-safe with atomic updates.

### 9.8 Boundary Conditions

**REQ-9.8.1**: The system SHALL handle empty files (0 bytes) without errors.

**REQ-9.8.2**: The system SHALL handle files with only whitespace without errors.

**REQ-9.8.3**: The system SHALL handle file size boundary conditions consistently:
- Files under limit: index
- Files at exact limit: consistent behavior (document whether included or excluded)
- Files over limit: skip with warning

**REQ-9.8.4**: The system SHALL handle single-character identifiers correctly.

**REQ-9.8.5**: The system SHALL handle maximum supported values:
- Maximum inheritance depth: 100+ levels
- Maximum overloads: 50+ per function name
- Maximum signature length: 5000+ characters

---

## Rationale for Additional Extracted Information

### USR (Unified Symbol Resolution)

**Why Extracted**: USR provides a unique, stable identifier for each symbol across translation units. This is essential for:
- Accurately linking symbols across different files
- Distinguishing between overloaded functions
- Tracking template instantiations
- Building accurate call graphs (resolving which specific function is called)
- Cache persistence (stable identifiers across parses)

### Call Graph (calls and called_by lists)

**Why Extracted**: Call relationships enable:
- Impact analysis (what breaks if I change this function?)
- Dead code detection (functions that are never called)
- Execution flow tracing (how do I get from A to B?)
- Refactoring safety (understanding dependencies before changes)
- Security analysis (tracing data flow through function calls)

### is_project Flag

**Why Extracted**: Distinguishing project code from dependencies enables:
- Focused analysis on user code (excluding library noise)
- Performance optimization (reduced result sets)
- Relevant search results (users rarely want to see std:: implementation details)
- License compliance (knowing which code is actually project code)

### Access Level (public/private/protected)

**Why Extracted**: Access control information enables:
- API surface analysis (what's public vs internal?)
- Encapsulation validation (is private data being accessed?)
- Documentation generation (public methods only)
- Interface analysis (understanding class contracts)

### Signature

**Why Extracted**: Full type signatures enable:
- Overload resolution (distinguish foo(int) from foo(string))
- Type compatibility checking
- Parameter analysis (what types does this function accept?)
- Template argument deduction understanding

### Base Classes

**Why Extracted**: Inheritance information enables:
- Polymorphism analysis (what overrides what?)
- Interface implementation detection (who implements this interface?)
- Virtual method resolution (which override gets called?)
- Design pattern detection (factory, visitor, etc.)
- Understanding class relationships and hierarchies

---

## 10. Header Extraction Requirements

### 10.1 Header File Discovery and Analysis

**REQ-10.1.1**: When analyzing a source file with `compile_commands.json`, the system SHALL extract C++ symbols from project headers included by that source file.

**REQ-10.1.2**: The system SHALL leverage libclang's translation unit to access already-parsed header ASTs, avoiding redundant file parsing.

**REQ-10.1.3**: The system SHALL distinguish between:
- Project headers (files under the project root, not in excluded/dependency directories)
- System headers (standard library headers like `<iostream>`)
- External dependency headers (third-party libraries)

**REQ-10.1.4**: The system SHALL extract symbols only from project headers, ignoring system and external headers.

**REQ-10.1.5**: The system SHALL support nested includes (headers including other headers) recursively to any depth.

**REQ-10.1.6**: For each cursor in the AST, the system SHALL use `cursor.location.file` to determine which file (source or header) the symbol belongs to.

### 10.2 First-Win Processing Strategy

**REQ-10.2.1**: The system SHALL use a "first-win" strategy where the first source file to include a header extracts its symbols.

**REQ-10.2.2**: Subsequent source files that include the same header SHALL skip symbol extraction for that header.

**REQ-10.2.3**: Header identity for deduplication SHALL be based solely on the header's file path (absolute path).

**REQ-10.2.4**: The system SHALL maintain a thread-safe tracker of processed headers to coordinate first-win logic across concurrent source file analyses.

**REQ-10.2.5**: The header tracker SHALL prevent race conditions when multiple threads attempt to claim the same header simultaneously.

**Rationale**: First-win strategy provides significant performance improvement (5-10×) for projects with headers included by multiple source files, while maintaining correctness through USR-based symbol deduplication.

### 10.3 Header Change Detection

**REQ-10.3.1**: For each processed header, the system SHALL calculate and store a file hash (MD5) to detect content changes.

**REQ-10.3.2**: When a header file's hash changes, the system SHALL automatically invalidate the previous extraction and re-process the header on the next source file analysis.

**REQ-10.3.3**: The header tracker SHALL compare the current file hash with the stored hash during claim attempts to detect changes.

**REQ-10.3.4**: If a hash mismatch is detected, the header SHALL be re-claimed for extraction even if previously processed.

### 10.4 compile_commands.json Versioning

**REQ-10.4.1**: The system SHALL calculate and store a hash (MD5) of the entire `compile_commands.json` file.

**REQ-10.4.2**: On analyzer startup, the system SHALL compare the current `compile_commands.json` hash with the cached hash.

**REQ-10.4.3**: If the `compile_commands.json` hash has changed, the system SHALL clear all header processing tracking and trigger full re-analysis of all headers.

**REQ-10.4.4**: The system SHALL persist the `compile_commands.json` hash in the header tracker cache for version comparison across restarts.

**Rationale**: Changes to compilation flags, include paths, or defines in `compile_commands.json` may affect header parsing results, requiring full re-analysis.

### 10.5 Header Tracking Persistence

**REQ-10.5.1**: The system SHALL persist header processing state to disk in a cache file (`header_tracker.json`).

**REQ-10.5.2**: The header tracker cache SHALL include:
- Cache version identifier
- `compile_commands.json` hash
- Map of processed header paths to file hashes
- Timestamp of last update

**REQ-10.5.3**: On analyzer startup, the system SHALL restore header tracking state from cache if the `compile_commands.json` hash matches.

**REQ-10.5.4**: The system SHALL save header tracking state after each source file analysis to ensure persistence.

**REQ-10.5.5**: The header tracker cache SHALL be stored in the project-specific cache directory (`.mcp_cache/{project}/header_tracker.json`).

### 10.6 Thread Safety

**REQ-10.6.1**: The header processing tracker SHALL use a threading Lock to protect all access to internal state (`_processed`, `_in_progress`).

**REQ-10.6.2**: The `try_claim_header()` operation SHALL be atomic: checking processed state, checking in-progress state, and claiming the header must occur within a single lock acquisition.

**REQ-10.6.3**: Multiple threads analyzing different source files simultaneously SHALL correctly coordinate header extraction without race conditions.

**REQ-10.6.4**: The system SHALL ensure that each header is extracted exactly once, even under high concurrency (e.g., 16 parallel workers).

### 10.7 Symbol Deduplication

**REQ-10.7.1**: The system SHALL continue to use USR-based deduplication for all symbols, regardless of whether they originate from source files or headers.

**REQ-10.7.2**: When a symbol with an existing USR is encountered during header extraction, the system SHALL skip adding it to the indexes (already present).

**REQ-10.7.3**: USR deduplication SHALL serve as a safety mechanism to ensure no duplicate symbols exist, even if header tracking logic has bugs.

**REQ-10.7.4**: Optionally, the system MAY track which files define each symbol (for debugging and diagnostics), but this is not required for correctness.

### 10.8 Cache Structure Extensions

**REQ-10.8.1**: Per-file caches MAY optionally include metadata about header extraction:
- `headers_extracted`: Map of header paths to file hashes for headers extracted during this source's analysis
- `headers_skipped`: List of header paths that were already processed by other sources

**REQ-10.8.2**: Header extraction metadata in per-file caches SHALL be for informational/diagnostic purposes only and SHALL NOT affect correctness.

**REQ-10.8.3**: The system SHALL maintain backward compatibility: old caches without header metadata SHALL load successfully.

### 10.9 Performance Requirements

**REQ-10.9.1**: For projects where headers are included by multiple source files, header extraction SHALL provide a performance improvement of 5-10× compared to re-extracting from each source.

**REQ-10.9.2**: The overhead of header tracking (claim checks, hash calculations, cache persistence) SHALL be negligible compared to the time saved by avoiding redundant extractions.

**REQ-10.9.3**: Header tracker cache operations (save/restore) SHALL complete in under 100ms for typical projects (up to 1000 unique headers).

---

## 10.10 Assumptions and Constraints

### Assumptions

**ASSUMPTION-10.1**: For a given version of `compile_commands.json`, analyzing a header file will produce identical symbol results regardless of which source file includes it.

**Why Safe**: In well-structured C++ projects, headers provide consistent declarations. The same compilation flags from `compile_commands.json` ensure consistent preprocessing. This assumption is sufficient for code analysis use cases.

**Edge Cases**: Headers with macro-dependent behavior (different symbols based on which source includes them) may not be fully captured. This is considered poor C++ practice and acceptable to miss.

**ASSUMPTION-10.2**: When `compile_commands.json` changes, all header tracking can be safely reset and headers re-analyzed from scratch.

**ASSUMPTION-10.3**: Header file path is a sufficient unique identifier for deduplication within a single `compile_commands.json` version.

### Constraints

**CONSTRAINT-10.1**: Headers with macro-dependent behavior (e.g., different symbols when included from different sources due to preprocessor state) may not be fully captured.

**CONSTRAINT-10.2**: The system does NOT perform cross-source validation of header consistency (i.e., does not check if the same header produces different symbols when included from different sources).

**CONSTRAINT-10.3**: The system does NOT monitor `compile_commands.json` for changes at runtime. Users must restart the analyzer or manually trigger rebuild after modifying the compilation database.

---

## Testing Implications

These requirements imply the following testing needs:

1. **Entity Extraction Tests**: Verify each C++ entity variant is correctly extracted
2. **Relationship Tests**: Verify all relationships are correctly established
3. **MCP Tool Tests**: Verify each of the 14 tools works correctly with various inputs
4. **Compilation Tests**: Verify compile_commands.json parsing and fallback behavior
5. **Cache Tests**: Verify cache creation, loading, and invalidation
6. **Performance Tests**: Verify parallel processing and progress reporting
7. **Error Handling Tests**: Verify graceful handling of errors and missing files
8. **Platform Tests**: Verify Windows/Linux/macOS specific behavior
9. **Configuration Tests**: Verify configuration loading and merging
10. **Integration Tests**: Verify end-to-end workflows with real C++ projects
11. **Header Extraction Tests**: Verify header discovery, first-win strategy, change detection, thread safety, and performance improvements

---

## Document Version

- **Version**: 3.2
- **Date**: 2025-11-16
- **Status**: Production-ready with header extraction feature requirements
- **Changes from v3.1**:
  - Added Section 10: Header Extraction Requirements (43 new requirements)
    - REQ-10.1: Header File Discovery and Analysis (6 requirements)
    - REQ-10.2: First-Win Processing Strategy (5 requirements)
    - REQ-10.3: Header Change Detection (4 requirements)
    - REQ-10.4: compile_commands.json Versioning (4 requirements)
    - REQ-10.5: Header Tracking Persistence (5 requirements)
    - REQ-10.6: Thread Safety (4 requirements)
    - REQ-10.7: Symbol Deduplication (4 requirements)
    - REQ-10.8: Cache Structure Extensions (3 requirements)
    - REQ-10.9: Performance Requirements (3 requirements)
    - REQ-10.10: Assumptions and Constraints (5 documented items)
  - Updated Testing Implications: Added header extraction tests
  - Total Requirements: 270+ requirements across 10 major sections
- **Changes from v3.0**:
  - Added REQ-6.2.6-6.2.9: Compilation Arguments Hash Validation (4 requirements)
    - Cache invalidation when compilation arguments change
    - MD5 hash of sorted arguments for consistency
    - Per-file cache version 1.1 → 1.2
  - Added Section 6.6: Failure Tracking and Retry Logic (10 requirements)
    - Track parsing failures in cache
    - Configurable retry limits (max_parse_retries)
    - Intelligent retry with skip after max attempts
    - Backward compatibility with v1.1 caches
  - Updated REQ-7.1.3: Added `max_parse_retries` configuration option
  - Added REQ-7.1.6-7.1.8: Configuration File Validation (3 requirements)
    - Validate JSON object vs array format
    - Actionable error messages for common mistakes
    - Debug logging for config discovery
  - Added Section 7.6: Centralized Error Logging (14 requirements)
    - JSONL error log at `.mcp_cache/{project}/parse_errors.jsonl`
    - Full error messages and stack traces
    - Developer-only access (not exposed to LLM)
    - Error querying, filtering, and management APIs
    - Utility script `scripts/view_parse_errors.py`
- **Changes from v2.0** (previous major update):
  - Added Section 9: Security and Robustness Requirements (42 new requirements)
    - REQ-9.1: Input Validation and Sanitization (6 requirements)
    - REQ-9.2: Symlink and File System Security (4 requirements)
    - REQ-9.3: Data Integrity and Atomic Operations (5 requirements)
    - REQ-9.4: Error Resilience (5 requirements)
    - REQ-9.5: Resource Limits and DoS Protection (5 requirements)
    - REQ-9.6: Platform-Specific Security (4 requirements)
    - REQ-9.7: Concurrent Access Protection (4 requirements)
    - REQ-9.8: Boundary Conditions (5 requirements)
- **Total Requirements**: 270+ requirements across 10 major sections
- **Coverage**: 100% of implemented functionality including header extraction planning
