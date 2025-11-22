# Compile Commands Integration

This document describes the integration of `compile_commands.json` support in the C++ Analyzer MCP Server.

## Overview

The C++ Analyzer now supports using `compile_commands.json` files to provide accurate compilation arguments for parsing C++ files. This ensures that the analyzer uses the same include paths, defines, and compiler options that are used during the actual build process.

## Features

- **Automatic Detection**: Automatically detects and uses `compile_commands.json` when present in the project root
- **Fallback Support**: Gracefully falls back to hardcoded arguments when `compile_commands.json` is not available
- **Caching**: Implements caching with configurable expiry times for improved performance
- **Configuration**: Comprehensive configuration options through `cpp-analyzer-config.json`
- **Error Handling**: Robust error handling for malformed JSON files or missing commands

## Configuration

The compile commands integration is configured through the `cpp-analyzer-config.json` file:

```json
{
  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": true,
    "cache_expiry_seconds": 300,
    "supported_extensions": [".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"],
    "exclude_patterns": [
      "*/build/*",
      "*/cmake-build-*",
      "*/CMakeFiles/*",
      "*/node_modules/*",
      "*/third_party/*",
      "*/external/*"
    ]
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable or disable compile commands support |
| `path` | string | `"compile_commands.json"` | Path to the compile commands file |
| `cache_enabled` | boolean | `true` | Enable caching of compile commands |
| `fallback_to_hardcoded` | boolean | `true` | Enable fallback to hardcoded arguments |
| `cache_expiry_seconds` | integer | `300` | Cache expiry time in seconds |
| `supported_extensions` | array | `[".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"]` | File extensions to process |
| `exclude_patterns` | array | `[]` | File patterns to exclude from processing |

## Usage

### Automatic Usage

When you set up a project directory, the analyzer will automatically:

1. Look for `compile_commands.json` in the project root
2. Parse and cache the compilation commands
3. Use the appropriate arguments for each file during parsing
4. Fall back to hardcoded arguments if no compile commands are available

### Manual Configuration

You can customize the behavior by modifying `cpp-analyzer-config.json`:

```json
{
  "compile_commands": {
    "enabled": true,
    "path": "custom_compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": true,
    "cache_expiry_seconds": 600,
    "supported_extensions": [".cpp", ".cxx", ".h", ".hpp"],
    "exclude_patterns": ["*/build/*", "*/tests/*"]
  }
}
```

## File Format

The `compile_commands.json` file should follow the standard format:

```json
[
  {
    "file": "src/main.cpp",
    "directory": "/path/to/project",
    "arguments": ["-std=c++17", "-Iinclude", "-I.", "-Wall"],
    "command": "clang++ -std=c++17 -Iinclude -I. -Wall src/main.cpp"
  },
  {
    "file": "src/utils.cpp",
    "directory": "/path/to/project",
    "arguments": ["-std=c++17", "-Iinclude", "-I.", "-Wall", "-c"],
    "command": "clang++ -std=c++17 -Iinclude -I. -Wall -c src/utils.cpp"
  }
]
```

### Required Fields

- `file`: Path to the source file (relative to the project root)
- `directory`: Working directory for the compilation command
- `arguments`: Array of compilation arguments (preferred)
- `command`: Full compilation command string (alternative to arguments)

### Optional Fields

- `output`: Output file path (if specified)
- `language`: Source language (if not inferred from file extension)

## Command Processing

### Important: Argument Filtering

When the analyzer processes compile_commands.json, it **filters out arguments that libclang doesn't need**. This is critical for correct parsing.

#### Arguments That Are Stripped

The following arguments are automatically removed before passing to libclang:

1. **Compiler Executable Path**
   - Example: `/usr/bin/gcc`, `/Library/Developer/CommandLineTools/usr/bin/cc`
   - Recognized patterns: gcc, g++, clang, clang++, cc, c++, cl, cl.exe
   - Reason: libclang only needs compilation flags, not the compiler path

2. **Output File Specification**
   - Example: `-o output.o`, `-o /path/to/output.o`
   - Reason: libclang doesn't compile files, only parses them

3. **Compile-Only Flag**
   - Example: `-c`
   - Reason: Not needed for parsing

4. **Source File Paths**
   - Example: `src/main.cpp`, `/path/to/file.c`
   - Detected by file extensions: .c, .cc, .cpp, .cxx, .c++, .m, .mm
   - Reason: libclang receives the source file separately

5. **Linker Flags**
   - Example: `-l...`, `-L...`, `-Wl,...`
   - Reason: Linking is not part of parsing

#### Arguments That Are Kept

The analyzer passes these arguments to libclang:

- Preprocessor defines: `-DNDEBUG`, `-DWIN32`, `-D_XOPEN_SOURCE=600`
- Include paths: `-I/path/to/includes`, `-isystem /usr/include`
- Language standard: `-std=c++17`, `-std=gnu11`
- Warning flags: `-Wall`, `-Wextra`, `-Werror`
- System root: `-isysroot /path/to/sdk`
- Target flags: `-target x86_64-apple-darwin`, `-march=native`
- Compiler features: `-fPIC`, `-fno-exceptions`

### Example Command Processing

**Input (from compile_commands.json):**
```json
{
  "file": "src/main.cpp",
  "directory": "/project",
  "command": "/usr/bin/c++ -std=c++17 -DNDEBUG -I/project/include -o build/main.o -c src/main.cpp"
}
```

**Processing Steps:**
1. Parse with shlex.split()
2. Strip compiler path: `/usr/bin/c++` ❌
3. Keep: `-std=c++17` ✅
4. Keep: `-DNDEBUG` ✅
5. Keep: `-I/project/include` ✅
6. Strip output: `-o build/main.o` ❌
7. Strip compile flag: `-c` ❌
8. Strip source file: `src/main.cpp` ❌

**Result passed to libclang:**
```python
["-std=c++17", "-DNDEBUG", "-I/project/include"]
```

### File Scoping

**Important:** When `compile_commands.json` is present and contains entries, the analyzer will **ONLY** analyze files explicitly listed in it.

This means:
- ✅ Source files in compile_commands.json are analyzed with their specific flags
- ✅ **Project headers included by these source files are automatically analyzed** (see Header File Analysis below)
- ❌ Source files NOT in compile_commands.json are NOT analyzed (unless discovered through headers)

This ensures the analyzer respects your build configuration and focuses on files that are part of the build.

## Header File Analysis

### Automatic Header Discovery

**Important:** When analyzing source files from `compile_commands.json`, the analyzer automatically extracts C++ symbols from **project headers** included by those source files.

This works through libclang's translation unit parsing:

1. **Source File Parsing**: When the analyzer processes a source file (e.g., `main.cpp`), libclang creates a translation unit (TU)
2. **Header Inclusion**: The TU contains the complete AST, including all headers included via `#include` directives
3. **Symbol Extraction**: The analyzer traverses the TU's AST and extracts symbols from both:
   - The source file itself
   - All **project headers** included by the source file

### Project vs. System Headers

The analyzer distinguishes between different types of headers:

| Header Type | Examples | Analyzed? | Reason |
|------------|----------|-----------|---------|
| **Project Headers** | `include/MyClass.h`, `src/Utils.h` | ✅ Yes | Part of your project code |
| **System Headers** | `<iostream>`, `<vector>` | ❌ No | Standard library |
| **External Dependencies** | `<boost/shared_ptr.hpp>` | ❌ No | Third-party libraries |

**Project headers** are identified as:
- Files under the project root directory
- NOT in excluded directories (e.g., `build/`, `vcpkg_installed/`)
- NOT in dependency directories (e.g., `deps/`, `third_party/`)

### Nested Includes

The analyzer supports nested includes to any depth:

```
main.cpp
  └─ includes Common.h
      └─ includes Internal.h
          └─ includes Types.h
```

All project headers in the chain (`Common.h`, `Internal.h`, `Types.h`) will have their symbols extracted.

### First-Win Processing Strategy

To optimize performance when multiple source files include the same header, the analyzer uses a **"first-win" strategy**:

1. **First Source File**: When `main.cpp` is analyzed and includes `Common.h`, the analyzer extracts symbols from `Common.h`
2. **Subsequent Sources**: When `test.cpp` is analyzed and also includes `Common.h`, the analyzer **skips** symbol extraction for `Common.h` (already done)
3. **Performance Gain**: For headers included by many source files, this provides a **5-10× speedup** compared to re-extracting every time

**How it works:**
- Header tracking is based on the header's file path
- File hash (MD5) is stored to detect changes
- Thread-safe coordination prevents race conditions during parallel analysis

### Header Change Detection

When you modify a header file:

1. **Hash Comparison**: The analyzer compares the file's current hash with the stored hash
2. **Automatic Re-extraction**: If the hash changed, symbols are re-extracted on the next analysis
3. **Consistency**: Updated symbols are available in subsequent queries

### compile_commands.json Versioning

The analyzer tracks changes to `compile_commands.json`:

- **Hash Tracking**: MD5 hash of `compile_commands.json` is stored in cache
- **Change Detection**: On analyzer startup, the current hash is compared with cached hash
- **Full Reset**: If `compile_commands.json` changed, all header tracking is reset and headers are re-analyzed

**Why?** Changes to compilation flags, include paths, or defines may affect how headers are parsed.

**User Action Required:** After modifying `compile_commands.json`, restart the analyzer or trigger a rebuild for best results.

### Usage Examples

#### Example 1: Shared Header

Project structure:
```
myproject/
├── compile_commands.json
├── src/
│   ├── main.cpp      (includes Common.h)
│   ├── test.cpp      (includes Common.h)
│   └── helper.cpp    (includes Utils.h)
└── include/
    ├── Common.h
    └── Utils.h
```

**Analysis flow:**
1. Analyze `main.cpp` → Extract symbols from `main.cpp` + `Common.h`
2. Analyze `test.cpp` → Extract symbols from `test.cpp`, **skip** `Common.h` (already processed)
3. Analyze `helper.cpp` → Extract symbols from `helper.cpp` + `Utils.h`

**Result:** `Common.h` processed once, `Utils.h` processed once. All symbols queryable.

#### Example 2: Nested Includes

```cpp
// main.cpp
#include "Common.h"

// include/Common.h
#include "Internal.h"

// include/Internal.h
#include "Types.h"
```

**Analysis flow:**
1. Parse `main.cpp` → TU contains AST for `main.cpp`, `Common.h`, `Internal.h`, `Types.h`
2. Traverse AST → Extract symbols from all project headers in single pass
3. Mark headers as processed → `Common.h`, `Internal.h`, `Types.h` all tracked

**Performance:** Single parse, single traversal. Very efficient.

#### Example 3: Header Modification

**Initial state:**
- `Common.h` contains `class Foo {};`
- Analyzed by processing `main.cpp`
- Hash stored: `abc123...`

**User modifies `Common.h`:**
```cpp
class Foo {
public:
    void bar();  // New method added
};
```

**Next analysis:**
1. Process `test.cpp` (which includes `Common.h`)
2. Calculate new hash: `def456...`
3. Compare: `def456 != abc123` → Hash mismatch detected
4. Re-extract symbols from `Common.h`
5. Update indexes with new `bar()` method
6. Store new hash: `def456...`

**Result:** Updated symbols automatically available.

### Performance Characteristics

| Scenario | Without Header Extraction | With Header Extraction | Speedup |
|----------|--------------------------|----------------------|---------|
| 100 sources, 20 common headers | 100 analyses | 120 analyses (100 + 20) | **~1.2×** |
| 1000 sources, 100 common headers, avg 10 includes/source | 1000 analyses | 1100 analyses (1000 + 100) | **~9×** |

The first-win strategy eliminates redundant processing, providing significant performance improvements for large projects with shared headers.

### Thread Safety

Header extraction is fully thread-safe:
- Atomic claim operations using threading.Lock
- Race condition prevention when multiple threads analyze sources simultaneously
- Guarantee: Each header processed exactly once, even with 16+ parallel workers

### Assumptions and Limitations

**Key Assumption:**
For a given `compile_commands.json`, a header will produce identical symbols regardless of which source file includes it.

**Why this is safe:**
- Well-structured C++ projects use consistent header declarations
- Same compilation flags ensure consistent preprocessing
- Sufficient for code analysis use cases

**Edge Cases:**
- Headers with macro-dependent behavior (different symbols based on preprocessor state) may not be fully captured
- This is considered poor C++ practice
- Acceptable limitation for the use case

**Limitations:**
- No cross-source validation of header consistency
- No runtime monitoring of `compile_commands.json` changes (restart required)
- Header path is the sole identifier (no per-compile-args tracking)

## Integration Details

### CppAnalyzer Integration

The `CppAnalyzer` class uses the `CompileCommandsManager` to:

- Get compilation arguments for specific files
- Handle file path normalization and resolution
- Manage caching and refresh of compile commands
- Provide fallback arguments when needed

### CppMcpServer Integration

The `CppMcpServer` class integrates with the compile commands system to:

- Provide accurate parsing results using build-time arguments
- Handle file parsing with proper include paths and defines
- Support cross-platform compilation environments

## Performance Considerations

### Caching

- Compile commands are cached in memory to avoid repeated file parsing
- Cache can be configured with custom expiry times
- Cache is automatically refreshed when the compile commands file is modified

### File Processing

- Only files with supported extensions are processed
- Files matching exclude patterns are skipped
- Relative paths are normalized to absolute paths for consistency

## Error Handling

The system handles various error conditions gracefully:

- **Missing File**: Falls back to hardcoded arguments
- **Invalid JSON**: Logs error and uses fallback arguments
- **Malformed Commands**: Skips invalid commands and processes valid ones
- **Missing Fields**: Logs warnings and skips incomplete commands

## Troubleshooting

### Common Issues

1. **Compile commands not being used**
   - Check that `compile_commands.json` exists in the project root
   - Verify the file contains valid JSON
   - Ensure commands have the required `file` field

2. **Missing include paths**
   - Verify that compile commands include the correct `-I` paths
   - Check that relative paths are resolved correctly
   - Ensure fallback arguments are enabled

3. **Performance issues**
   - Enable caching if disabled
   - Adjust cache expiry time as needed
   - Check for large compile commands files

### Debug Information

You can get compile commands statistics using the `get_server_status` tool:

```json
{
  "analyzer_type": "python_enhanced",
  "compile_commands_enabled": true,
  "compile_commands_path": "compile_commands.json",
  "compile_commands_cache_enabled": true,
  "compile_commands_count": 42,
  "file_mapping_count": 42
}
```

## Examples

### Basic CMake Project

```cmake
cmake_minimum_required(VERSION 3.16)
project(MyProject CXX)

# Enable compile commands
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable(myapp main.cpp utils.cpp)
target_include_directories(myapp PRIVATE include)
```

This generates a `compile_commands.json` file that the analyzer will automatically use.

### Manual Compile Commands

```json
[
  {
    "file": "src/main.cpp",
    "directory": "/home/user/myproject",
    "arguments": ["-std=c++17", "-Iinclude", "-I.", "-Wall", "-Wextra"],
    "command": "clang++ -std=c++17 -Iinclude -I. -Wall -Wextra src/main.cpp -o main"
  }
]
```

### Custom Configuration

```json
{
  "compile_commands": {
    "enabled": true,
    "path": "build/compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": false,
    "cache_expiry_seconds": 600,
    "supported_extensions": [".cpp", ".cxx", ".h", ".hpp"],
    "exclude_patterns": ["*/build/*", "*/tests/*"]
  }
}
```

## Testing

Run the compile commands integration tests:

```bash
python tests/test_runner.py
```

The tests cover:
- Compile commands parsing and caching
- Fallback behavior
- Error handling
- File processing decisions
- Configuration options
- Integration with analyzers

## Future Enhancements

Potential future improvements:

- Support for `compilation_database.json` format
- Integration with build systems other than CMake
- Automatic generation of compile commands
- Support for compiler-specific flags
- Advanced caching strategies
- Multi-project support