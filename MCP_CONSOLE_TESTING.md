# MCP Server Console Testing Guide

This guide explains how to test the C++ MCP Server with a real codebase from the console.

## Quick Start

### Using the Test Script (Easiest Method)

```bash
# 1. Activate the virtual environment
source mcp_env/bin/activate  # Linux/macOS
# or
mcp_env\Scripts\activate  # Windows

# 2. Run the test script with your C++ project path
python scripts/test_mcp_console.py /path/to/your/cpp/project
```

The test script will automatically:
1. **Configure** - Set up the analyzer with your project path
2. **Analyze** - Index all C++ files in the project
3. **Query** - Perform various queries to test functionality:
   - Get server status
   - Search for classes
   - Search for functions
   - Get detailed class information
   - Get function signatures
   - Get class hierarchies
   - Find function callers
   - Find function callees

## Testing Workflow

The MCP server workflow consists of three main steps:

### 1. Configure - Set Project Directory

Before you can analyze code, you must tell the server where your C++ project is located:

```python
from mcp_server.cpp_analyzer import CppAnalyzer

analyzer = CppAnalyzer("/path/to/your/cpp/project")
```

**Expected output:**
- Confirmation that the project directory is set
- Initial validation that the path exists and is a directory

### 2. Analyze - Index the Project

The server indexes all C++ files in your project to build search indexes:

```python
indexed_count = analyzer.index_project(force=False, include_dependencies=True)
print(f"Indexed {indexed_count} C++ files")
```

**Parameters:**
- `force`: If True, re-index even if cache exists (default: False)
- `include_dependencies`: Include third-party dependencies like vcpkg libraries (default: True)

**Expected output:**
- Number of files found
- Parsing progress
- Number of classes and functions indexed
- Time taken to complete

**Note:** For large codebases (1000+ files), this may take several minutes on first run. Subsequent runs will be much faster due to caching.

### 3. Query - Perform Requests

Once indexed, you can query the codebase using various tools:

#### Get List of Classes

```python
# Search all classes (pattern: '.*' matches everything)
classes = analyzer.search_classes(".*", project_only=True)

# Search classes by pattern
game_classes = analyzer.search_classes("Game.*", project_only=True)
actor_classes = analyzer.search_classes(".*Actor", project_only=True)
```

**Parameters:**
- `pattern`: Regular expression pattern to match class names
- `project_only`: If True, only search project files (exclude dependencies)

**Expected output:**
```json
[
  {
    "name": "GameObject",
    "kind": "CLASS_DECL",
    "file": "/path/to/project/src/GameObject.h",
    "line": 10,
    "column": 7,
    "is_project": true
  },
  ...
]
```

#### Get List of Functions

```python
# Search all functions
functions = analyzer.search_functions(".*", project_only=True)

# Search functions by pattern
update_functions = analyzer.search_functions(".*Update.*", project_only=True)

# Search methods in a specific class
class_methods = analyzer.search_functions(".*", project_only=True, class_name="GameObject")
```

**Expected output:**
```json
[
  {
    "name": "Update",
    "kind": "CXX_METHOD",
    "file": "/path/to/project/src/GameObject.cpp",
    "line": 25,
    "column": 6,
    "signature": "void (float)",
    "is_project": true
  },
  ...
]
```

#### Get Detailed Class Information

```python
class_info = analyzer.get_class_info("GameObject")
```

**Expected output:**
```json
{
  "name": "GameObject",
  "kind": "CLASS_DECL",
  "file": "/path/to/project/src/GameObject.h",
  "line": 10,
  "methods": [
    {
      "name": "Update",
      "signature": "void (float)",
      "line": 15,
      "access": "public"
    },
    ...
  ],
  "members": [
    {
      "name": "position",
      "type": "Vector3",
      "line": 20,
      "access": "private"
    },
    ...
  ],
  "base_classes": ["Component", "IUpdatable"]
}
```

#### Get Function Signatures

```python
signatures = analyzer.get_function_signature("Update")
```

**Expected output:**
```json
[
  {
    "name": "Update",
    "file": "/path/to/project/src/GameObject.cpp",
    "line": 25,
    "signature": "void (float)",
    "return_type": "void",
    "parameters": [
      {
        "name": "deltaTime",
        "type": "float"
      }
    ]
  },
  ...
]
```

#### Get Class Hierarchy

```python
hierarchy = analyzer.get_class_hierarchy("GameObject")
```

**Expected output:**
```json
{
  "name": "GameObject",
  "file": "/path/to/project/src/GameObject.h",
  "line": 10,
  "base_classes": ["Component", "IUpdatable"],
  "derived_classes": [
    {
      "name": "PlayerCharacter",
      "file": "/path/to/project/src/Player.h",
      "line": 5
    },
    ...
  ]
}
```

#### Find Function Callers

```python
callers = analyzer.find_callers("Update")
```

**Expected output:**
```json
[
  {
    "name": "GameLoop",
    "file": "/path/to/project/src/Engine.cpp",
    "line": 100,
    "kind": "FUNCTION_DECL"
  },
  ...
]
```

#### Find Function Callees

```python
callees = analyzer.find_callees("Update")
```

**Expected output:**
```json
[
  {
    "name": "UpdatePhysics",
    "file": "/path/to/project/src/Physics.cpp",
    "line": 50,
    "kind": "FUNCTION_DECL"
  },
  ...
]
```

## Available Tools

The MCP server provides these tools:

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `set_project_directory` | Set the C++ project path | `project_path` (absolute path) |
| `search_classes` | Find classes by name pattern | `pattern`, `project_only` |
| `search_functions` | Find functions by name pattern | `pattern`, `project_only`, `class_name` |
| `get_class_info` | Get detailed class information | `class_name` |
| `get_function_signature` | Get function signatures | `function_name`, `class_name` |
| `search_symbols` | Search all symbols | `pattern`, `project_only`, `symbol_types` |
| `find_in_file` | Search symbols in a specific file | `file_path`, `pattern` |
| `get_class_hierarchy` | Get inheritance hierarchy | `class_name` |
| `get_derived_classes` | Find derived classes | `class_name`, `project_only` |
| `find_callers` | Find functions that call a function | `function_name`, `class_name` |
| `find_callees` | Find functions called by a function | `function_name`, `class_name` |
| `get_call_path` | Find call paths between functions | `from_function`, `to_function`, `max_depth` |
| `get_server_status` | Get server status and statistics | None |
| `refresh_project` | Manually refresh/re-parse files | None |

## Example Test Sequence

Here's a complete example of testing with a real codebase:

```bash
# 1. Activate environment
source mcp_env/bin/activate

# 2. Run the test script with a C++ project
# Example with a game engine project:
python scripts/test_mcp_console.py ~/MyGameEngine

# Example with LLVM/Clang project (large codebase):
python scripts/test_mcp_console.py /usr/src/llvm-project/clang

# Example with your own project:
python scripts/test_mcp_console.py /home/user/my-cpp-project
```

## Testing with Different Codebases

### Small Projects (< 100 files)
- Indexing: < 10 seconds
- Good for initial testing and validation

### Medium Projects (100-1000 files)
- Indexing: 10-60 seconds
- Typical application codebases

### Large Projects (1000+ files)
- Indexing: 1-10 minutes (first time)
- Examples: Game engines, LLVM, Chromium
- Subsequent runs are much faster due to caching

## Troubleshooting

### Issue: "libclang not found"
**Solution:**
```bash
# Run the setup script
./server_setup.sh  # Linux/macOS
# or
server_setup.bat  # Windows
```

### Issue: "No C++ files found"
**Solution:**
- Verify the project path is correct
- Check that the directory contains `.cpp`, `.h`, `.hpp` files
- The server excludes common directories like `build/`, `vcpkg_installed/`, `.git/`

### Issue: Parsing takes too long
**Solution:**
- First run on large projects will be slow
- Use `project_only=True` to exclude dependencies
- Subsequent runs use cached results and are much faster

### Issue: Classes/functions not found
**Solution:**
- Make sure indexing completed successfully
- Check if files are in excluded directories
- Verify the search pattern is correct (use `".*"` to match all)

## Advanced: Direct JSON-RPC Testing

For advanced users who want to test the MCP protocol directly:

```bash
# Start the server in stdio mode
python -m mcp_server.cpp_mcp_server
```

Then send JSON-RPC messages via stdin. Example messages are in `docs/mcp_protocol_examples.json`.

## Next Steps

After console testing is successful:

1. **Integrate with Claude Desktop** - See `README.md` for configuration
2. **Create custom queries** - Modify the test script for your specific needs
3. **Use in CI/CD** - Automate code analysis in your build pipeline
