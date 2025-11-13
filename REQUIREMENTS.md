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
7. [Project Management Requirements](#7-project-management-requirements)

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

The system provides 13 MCP tools. Each tool has specific requirements for inputs, outputs, and behavior.

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

### 4.13 get_call_path

**REQ-4.13.1**: SHALL accept:
- `from_function`: string (starting function name)
- `to_function`: string (target function name)
- `max_depth`: integer (default: 10)

**REQ-4.13.2**: SHALL return list of call paths, where each path is a list of function names.

**REQ-4.13.3**: SHALL use breadth-first search to find paths.

**REQ-4.13.4**: SHALL format method names as "ClassName::methodName".

**REQ-4.13.5**: SHALL respect max_depth limit to prevent infinite searches.

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

---

## 6. Caching and Performance Requirements

### 6.1 Symbol Cache

**REQ-6.1.1**: The system SHALL cache parsed symbols to disk in `.mcp_cache/` directory.

**REQ-6.1.2**: The cache directory structure SHALL be: `.mcp_cache/{project_name}_{hash}/`

**REQ-6.1.3**: The system SHALL save per-file caches for individual source files.

**REQ-6.1.4**: The system SHALL save overall index cache with:
- class_index
- function_index
- file_hashes
- indexed_file_count
- Configuration file metadata (path, mtime)
- Compile commands metadata (path, mtime)

### 6.2 Cache Invalidation

**REQ-6.2.1**: The system SHALL use file content hashing (SHA-256) for change detection.

**REQ-6.2.2**: The system SHALL invalidate cache when:
- File content changes (hash mismatch)
- Configuration file (.cpp-analyzer-config.json) is modified
- compile_commands.json is modified
- include_dependencies setting changes

**REQ-6.2.3**: The system SHALL track modification times (mtime) for:
- Configuration file
- compile_commands.json

**REQ-6.2.4**: The system SHALL reindex files whose cache is invalidated.

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
- `compile_commands`: Compilation configuration (see REQ-5.1.6)
- `diagnostics`: Diagnostic logging configuration

**REQ-7.1.4**: The system SHALL merge user configuration with default configuration (user takes precedence).

**REQ-7.1.5**: The system SHALL use default configuration if no config file is found.

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
- Remove from indexes
- Clean up per-file cache

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

**REQ-7.5.3**: The system SHALL support configuring diagnostic level via configuration.

**REQ-7.5.4**: The system SHALL support enabling/disabling diagnostics via configuration.

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

## Testing Implications

These requirements imply the following testing needs:

1. **Entity Extraction Tests**: Verify each C++ entity variant is correctly extracted
2. **Relationship Tests**: Verify all relationships are correctly established
3. **MCP Tool Tests**: Verify each of the 13 tools works correctly with various inputs
4. **Compilation Tests**: Verify compile_commands.json parsing and fallback behavior
5. **Cache Tests**: Verify cache creation, loading, and invalidation
6. **Performance Tests**: Verify parallel processing and progress reporting
7. **Error Handling Tests**: Verify graceful handling of errors and missing files
8. **Platform Tests**: Verify Windows/Linux/macOS specific behavior
9. **Configuration Tests**: Verify configuration loading and merging
10. **Integration Tests**: Verify end-to-end workflows with real C++ projects

---

## Document Version

- **Version**: 1.0
- **Date**: 2025-11-13
- **Status**: Initial requirements capture from implementation analysis
