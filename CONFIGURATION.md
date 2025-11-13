# Configuration Guide

This document describes how to configure the C++ Analyzer MCP Server.

## Configuration File Locations

The analyzer looks for configuration files in the following locations (in priority order):

### 1. Environment Variable (Highest Priority)
Set the `CPP_ANALYZER_CONFIG` environment variable to point to a custom config file:

```bash
# Linux/macOS
export CPP_ANALYZER_CONFIG="/path/to/my-custom-config.json"

# Windows
set CPP_ANALYZER_CONFIG=C:\path\to\my-custom-config.json
```

### 2. Project-Specific Configuration
Place `cpp-analyzer-config.json` in your C++ project root directory (the directory you're analyzing):

```
/path/to/your/cpp/project/
├── cpp-analyzer-config.json    ← Project-specific config
├── src/
├── include/
└── compile_commands.json
```

**Use case**: Different settings for each C++ project you analyze.

### 3. User Configuration Directory
Place `cpp-analyzer-config.json` in your user config directory:

**Linux/macOS**: `~/.config/cpp-analyzer/cpp-analyzer-config.json`

**Windows**: `%APPDATA%\cpp-analyzer\cpp-analyzer-config.json`

**Use case**: Global settings that apply to all projects you analyze.

### 4. Package Installation Directory (Backward Compatibility)
The analyzer will also check the MCP server installation directory, but this is **not recommended** for packaged installations.

## Configuration File Format

```json
{
  "_comment": "C++ Analyzer configuration file",

  "exclude_directories": [
    ".git",
    ".svn",
    "node_modules",
    "build",
    "Build",
    "ThirdParty",
    "Intermediate",
    "Binaries"
  ],

  "exclude_patterns": [
    "*.generated.h",
    "*.generated.cpp",
    "*_test.cpp"
  ],

  "dependency_directories": [
    "vcpkg_installed",
    "third_party",
    "external"
  ],

  "include_dependencies": true,
  "max_file_size_mb": 10,

  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": true,
    "cache_expiry_seconds": 300
  }
}
```

## Configuration Options

### General Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `exclude_directories` | array | See below | Directories to skip during scanning |
| `exclude_patterns` | array | `[]` | File patterns to exclude (glob patterns) |
| `dependency_directories` | array | See below | Directories containing third-party code |
| `include_dependencies` | boolean | `true` | Whether to analyze dependency files |
| `max_file_size_mb` | number | `10` | Maximum file size to analyze (MB) |

**Default exclude_directories**:
```json
[".git", ".svn", ".hg", "node_modules", "__pycache__", ".pytest_cache",
 ".vs", ".vscode", ".idea", "CMakeFiles", "CMakeCache.txt"]
```

**Default dependency_directories**:
```json
["vcpkg_installed", "third_party", "ThirdParty", "external",
 "External", "vendor", "dependencies", "packages"]
```

### Compile Commands Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `compile_commands.enabled` | boolean | `true` | Enable compile_commands.json support |
| `compile_commands.path` | string | `"compile_commands.json"` | Path to compile_commands.json (relative to project root) |
| `compile_commands.cache_enabled` | boolean | `true` | Enable caching of compile commands |
| `compile_commands.fallback_to_hardcoded` | boolean | `true` | Use default args if compile_commands.json not found |
| `compile_commands.cache_expiry_seconds` | number | `300` | Cache expiry time in seconds |

For detailed information about compile_commands.json integration, see [COMPILE_COMMANDS_INTEGRATION.md](COMPILE_COMMANDS_INTEGRATION.md).

## Creating a Configuration File

### Method 1: Manually Create

Create `cpp-analyzer-config.json` in one of the locations above with your desired settings.

### Method 2: Using Python API

```python
from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
from pathlib import Path

config = CppAnalyzerConfig(Path("/path/to/your/project"))

# Create in user config directory (recommended for packaged installations)
config.create_example_config(location='user')

# Create in project root (recommended for project-specific settings)
config.create_example_config(location='project')
```

## Configuration Priority Examples

### Example 1: Global User Settings
Create `~/.config/cpp-analyzer/cpp-analyzer-config.json`:

```json
{
  "include_dependencies": false,
  "max_file_size_mb": 5,
  "compile_commands": {
    "enabled": true,
    "path": "build/compile_commands.json"
  }
}
```

This applies to all projects unless overridden.

### Example 2: Project-Specific Override
Create `/path/to/my/project/cpp-analyzer-config.json`:

```json
{
  "include_dependencies": true,
  "compile_commands": {
    "path": "cmake-build-debug/compile_commands.json"
  }
}
```

This overrides the user config for this specific project.

### Example 3: Environment Variable Override
```bash
# Point to a custom config for this session
export CPP_ANALYZER_CONFIG="/tmp/special-config.json"

# Run your analysis
# The analyzer will use /tmp/special-config.json
```

This takes precedence over both user and project configs.

## Recommendations for Packaged Distribution

When distributing the C++ Analyzer as a Python package (e.g., via pip):

1. **Users should use**:
   - User config directory: `~/.config/cpp-analyzer/cpp-analyzer-config.json`
   - Or project-specific configs in each C++ project root

2. **Package maintainers should**:
   - Include sensible defaults in the code
   - Document config file locations in README
   - Provide example configs in documentation
   - **Do NOT** require users to modify files in site-packages

3. **Environment variable approach**:
   - Useful for CI/CD pipelines
   - Useful for temporary config changes
   - Useful for testing different configurations

## Troubleshooting

### Config File Not Found
If you see "No config file found, using defaults", the analyzer will print suggested locations:

```
No config file found, using defaults
You can create a config file at one of these locations:
  - Project: /path/to/your/project/cpp-analyzer-config.json
  - User:    ~/.config/cpp-analyzer/cpp-analyzer-config.json
  - Env var: CPP_ANALYZER_CONFIG=<path>
```

### Config File Not Loaded
Check:
1. File exists at one of the search locations
2. File contains valid JSON
3. File has read permissions
4. Check stderr output for error messages

### Which Config is Being Used?
The analyzer prints which config file is loaded:

```
Loaded config from: ~/.config/cpp-analyzer/cpp-analyzer-config.json
```

If no message appears, defaults are being used.

## Migration Guide

### From Package-Local Config
If you previously had `cpp-analyzer-config.json` in the package directory:

1. Copy it to `~/.config/cpp-analyzer/cpp-analyzer-config.json`
2. Or copy it to your project root
3. Remove the old file from the package directory (optional)

The package-local config will still work for backward compatibility, but user/project configs are recommended.
