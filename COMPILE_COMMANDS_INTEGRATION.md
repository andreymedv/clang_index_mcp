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