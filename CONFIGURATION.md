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

**Use case**: Temporary overrides, CI/CD pipelines, or testing different configurations.

### 2. Project-Specific Configuration
Place `.cpp-analyzer-config.json` (note the leading dot) in your C++ project root directory:

```
/path/to/your/cpp/project/
├── .cpp-analyzer-config.json    ← Project-specific config (hidden on Unix)
├── src/
├── include/
└── compile_commands.json
```

**Use case**: Per-project settings that persist with your codebase.

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

Create `.cpp-analyzer-config.json` in your project root with your desired settings.

### Method 2: Using Python API

```python
from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
from pathlib import Path

config = CppAnalyzerConfig(Path("/path/to/your/project"))

# Create in project root (recommended)
config.create_example_config(location='project')

# Or create at a custom path
config.create_example_config(location='path')
```

## Configuration Priority Examples

### Example 1: Project-Specific Settings

Create `/path/to/my/project/.cpp-analyzer-config.json`:

```json
{
  "include_dependencies": false,
  "compile_commands": {
    "path": "build/compile_commands.json"
  }
}
```

This configuration applies only to this specific project.

### Example 2: Environment Variable Override

```bash
# Create a custom config file
cat > /tmp/special-config.json << 'EOF'
{
  "include_dependencies": true,
  "max_file_size_mb": 20,
  "compile_commands": {
    "path": "cmake-build-debug/compile_commands.json"
  }
}
EOF

# Use it for this session
export CPP_ANALYZER_CONFIG="/tmp/special-config.json"

# Run your analysis - the analyzer will use /tmp/special-config.json
```

This takes precedence over project-specific config.

### Example 3: Different Configs for Different Build Types

```bash
# For debug builds
export CPP_ANALYZER_CONFIG="$PWD/.cpp-analyzer-debug.json"

# For release builds
export CPP_ANALYZER_CONFIG="$PWD/.cpp-analyzer-release.json"
```

## Recommendations

### For Package Distribution

When distributing as a Python package:

1. **Include in .gitignore** (optional):
   ```gitignore
   # Optionally ignore the config if it's machine-specific
   .cpp-analyzer-config.json
   ```

2. **Include example config in repo**:
   ```
   .cpp-analyzer-config.json.example
   ```

   Users can copy and customize:
   ```bash
   cp .cpp-analyzer-config.json.example .cpp-analyzer-config.json
   ```

3. **Document in README**:
   - Recommended config location (project root)
   - Example configuration
   - Common settings for your project

### For Version Control

**Option A: Commit the config** (recommended if settings are project-wide)
- Add `.cpp-analyzer-config.json` to git
- Everyone on the team uses the same settings
- Consistent analysis results

**Option B: Don't commit** (if settings are machine-specific)
- Add to `.gitignore`
- Provide `.cpp-analyzer-config.json.example`
- Each developer customizes locally

### For CI/CD

Use environment variable for build-specific settings:

```yaml
# GitHub Actions example
- name: Analyze C++ code
  env:
    CPP_ANALYZER_CONFIG: ${{ github.workspace }}/.ci/cpp-analyzer-ci.json
  run: |
    python -m mcp_server.cpp_analyzer
```

## Troubleshooting

### Config File Not Found

If you see "No config file found, using defaults":

```
No config file found, using defaults
You can create a config file at:
  - Project: /path/to/your/project/.cpp-analyzer-config.json
  - Or set:  CPP_ANALYZER_CONFIG=<path>
```

**Solution**: Create `.cpp-analyzer-config.json` in your project root or set the environment variable.

### Config File Not Loaded

Check:
1. File exists at the expected location
2. Filename is exactly `.cpp-analyzer-config.json` (with leading dot)
3. File contains valid JSON
4. File has read permissions
5. Check stderr output for error messages

### Which Config is Being Used?

The analyzer prints which config file is loaded:

```
Loaded config from: /path/to/your/project/.cpp-analyzer-config.json
```

If no message appears, defaults are being used.

### Hidden File on Unix

The leading dot makes the file hidden on Unix-like systems. To view it:

```bash
# List hidden files
ls -la

# Edit with your preferred editor
nano .cpp-analyzer-config.json
vim .cpp-analyzer-config.json
```

## Examples

### Minimal Config

```json
{
  "compile_commands": {
    "path": "build/compile_commands.json"
  }
}
```

### Unreal Engine Project

```json
{
  "exclude_directories": [
    ".git",
    "Intermediate",
    "Binaries",
    "DerivedDataCache",
    "Saved"
  ],
  "dependency_directories": [
    "ThirdParty",
    "Plugins"
  ],
  "exclude_patterns": [
    "*.generated.h",
    "*.generated.cpp"
  ],
  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json"
  }
}
```

### CMake Project

```json
{
  "exclude_directories": [
    ".git",
    "build",
    "cmake-build-debug",
    "cmake-build-release"
  ],
  "compile_commands": {
    "enabled": true,
    "path": "build/compile_commands.json"
  }
}
```

### Large Codebase (Performance Tuning)

```json
{
  "include_dependencies": false,
  "max_file_size_mb": 5,
  "exclude_patterns": [
    "*_test.cpp",
    "*_benchmark.cpp",
    "*/tests/*"
  ],
  "compile_commands": {
    "enabled": true,
    "cache_enabled": true,
    "cache_expiry_seconds": 600
  }
}
```
