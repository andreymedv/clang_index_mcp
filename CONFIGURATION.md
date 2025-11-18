# Configuration Guide

This document describes how to configure the C++ Analyzer MCP Server.

## Table of Contents

- [Configuration File Locations](#configuration-file-locations)
- [Configuration File Format](#configuration-file-format)
- [Configuration Options](#configuration-options)
  - [General Options](#general-options)
  - [Diagnostics Options](#diagnostics-options)
  - [Compile Commands Options](#compile-commands-options)
- [Environment Variables](#environment-variables)
- [Creating a Configuration File](#creating-a-configuration-file)
- [Configuration Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Quick Reference

All available configuration options:

| Category | Option | Type | Default | Description |
|----------|--------|------|---------|-------------|
| **General** | `exclude_directories` | array | *see docs* | Directories to skip |
| | `exclude_patterns` | array | `[]` | File patterns to exclude |
| | `dependency_directories` | array | *see docs* | Third-party code dirs |
| | `include_dependencies` | boolean | `true` | Analyze dependencies |
| | `max_file_size_mb` | number | `10` | Max file size (MB) |
| | `max_parse_retries` | number | `2` | Retry attempts for failed files |
| **Diagnostics** | `diagnostics.level` | string | `"info"` | Logging level |
| | `diagnostics.enabled` | boolean | `true` | Enable diagnostics |
| **Compile Commands** | `compile_commands.enabled` | boolean | `true` | Enable support |
| | `compile_commands.path` | string | `"compile_commands.json"` | File path |
| | `compile_commands.cache_enabled` | boolean | `true` | Enable caching |
| | `compile_commands.fallback_to_hardcoded` | boolean | `true` | Use defaults if missing |
| | `compile_commands.cache_expiry_seconds` | number | `300` | *(deprecated)* |
| | `compile_commands.supported_extensions` | array | *see docs* | File extensions |
| | `compile_commands.exclude_patterns` | array | `[]` | Exclude patterns |

**Environment Variables:**
- `CPP_ANALYZER_CONFIG` - Path to custom config file
- `CPP_ANALYZER_USE_THREADS` - Use ThreadPool instead of ProcessPool (not recommended)
- `CLANG_INDEX_USE_SQLITE` - Enable SQLite cache backend (default: 1)
- `CLANG_INDEX_CACHE_DIR` - Custom cache directory location

**Project Identity & Incremental Analysis:**
- Project identity is determined by the combination of source directory and config file path
- Different config file paths create separate cache directories (enabling multi-config workflows)
- Changing only file contents (not paths) preserves project identity and enables incremental analysis
- See [Incremental Analysis](#incremental-analysis) section below for details

---

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
  "max_parse_retries": 2,

  "diagnostics": {
    "level": "info",
    "enabled": true
  },

  "compile_commands": {
    "enabled": true,
    "path": "compile_commands.json",
    "cache_enabled": true,
    "fallback_to_hardcoded": true,
    "cache_expiry_seconds": 300,
    "supported_extensions": [
      ".cpp", ".cc", ".cxx", ".c++",
      ".h", ".hpp", ".hxx", ".h++"
    ],
    "exclude_patterns": []
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
| `max_parse_retries` | number | `2` | Maximum retry attempts for failed files |

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

### Diagnostics Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `diagnostics.level` | string | `"info"` | Logging level: `"debug"`, `"info"`, `"warning"`, `"error"`, `"fatal"` |
| `diagnostics.enabled` | boolean | `true` | Enable/disable diagnostic output |

**Diagnostic Levels**:
- `debug`: Verbose output including internal details
- `info`: General informational messages (default)
- `warning`: Warning messages for non-critical issues
- `error`: Error messages for failures
- `fatal`: Critical errors that stop execution

**Example**:
```json
{
  "diagnostics": {
    "level": "warning",
    "enabled": true
  }
}
```

### Compile Commands Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `compile_commands.enabled` | boolean | `true` | Enable compile_commands.json support |
| `compile_commands.path` | string | `"compile_commands.json"` | Path to compile_commands.json (relative to project root) |
| `compile_commands.cache_enabled` | boolean | `true` | Enable caching of compile commands |
| `compile_commands.fallback_to_hardcoded` | boolean | `true` | Use default args if compile_commands.json not found |
| `compile_commands.cache_expiry_seconds` | number | `300` | Cache expiry time in seconds (deprecated, binary cache used instead) |
| `compile_commands.supported_extensions` | array | See below | File extensions to analyze |
| `compile_commands.exclude_patterns` | array | `[]` | Patterns to exclude from compile_commands.json |

**Default supported_extensions**:
```json
[".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"]
```

**Notes**:
- `cache_expiry_seconds`: This setting is deprecated. The new binary cache (`.clang_index/compile_commands.cache`) is hash-validated and doesn't use time-based expiry.
- `supported_extensions`: Only files with these extensions will be analyzed from `compile_commands.json`
- `exclude_patterns`: Additional glob patterns to exclude files found in `compile_commands.json`

**Example**:
```json
{
  "compile_commands": {
    "enabled": true,
    "path": "build/compile_commands.json",
    "supported_extensions": [".cpp", ".cc", ".h", ".hpp"],
    "exclude_patterns": ["*_generated.cpp", "*/test/*"]
  }
}
```

For detailed information about compile_commands.json integration, see [COMPILE_COMMANDS_INTEGRATION.md](COMPILE_COMMANDS_INTEGRATION.md).

## Environment Variables

The analyzer supports several environment variables for runtime configuration:

### Performance Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CPP_ANALYZER_USE_THREADS` | boolean | `false` | Use ThreadPoolExecutor instead of ProcessPoolExecutor (not recommended) |

**CPP_ANALYZER_USE_THREADS**:
- **Default**: `false` (uses ProcessPoolExecutor for GIL bypass)
- **Set to `true`**: Uses ThreadPoolExecutor (legacy mode, slower)
- **Recommendation**: Keep default for best performance on multi-core systems

**Example**:
```bash
# Linux/macOS (not recommended - ProcessPool is faster)
export CPP_ANALYZER_USE_THREADS=true

# Windows (not recommended)
set CPP_ANALYZER_USE_THREADS=true
```

**Performance Impact**:
- ProcessPoolExecutor (default): 6-7x faster on 4+ core systems
- ThreadPoolExecutor (when enabled): Limited by Python's GIL

### Configuration File Path

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CPP_ANALYZER_CONFIG` | string | (none) | Path to custom configuration file |

**Example**:
```bash
# Linux/macOS
export CPP_ANALYZER_CONFIG="/path/to/my-custom-config.json"

# Windows
set CPP_ANALYZER_CONFIG=C:\path\to\my-custom-config.json
```

This is documented in detail in the "Configuration File Locations" section above.

### SQLite Cache Configuration (New in v3.0.0)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CLANG_INDEX_USE_SQLITE` | boolean/int | `1` | Enable SQLite cache backend (1=SQLite, 0=JSON) |
| `CLANG_INDEX_CACHE_DIR` | string | `.mcp_cache` | Custom cache directory location |

**CLANG_INDEX_USE_SQLITE**:
- **Default**: `1` (enabled - SQLite cache is used)
- **Set to `0` or `false`**: Falls back to legacy JSON cache
- **Recommendation**: Keep enabled for best performance
- **Auto-Migration**: When enabled, automatically migrates existing JSON cache to SQLite

**Performance with SQLite (vs JSON)**:
- 20x faster symbol searches (2-5ms vs 50ms)
- 2x faster startup (300ms vs 600ms for 100K symbols)
- 70% smaller disk usage (30MB vs 100MB for 100K symbols)
- Multi-process safe with WAL mode

**Example - Enable SQLite (default)**:
```bash
# Linux/macOS (SQLite is default, no configuration needed)
export CLANG_INDEX_USE_SQLITE=1

# Windows
set CLANG_INDEX_USE_SQLITE=1
```

**Example - Use Legacy JSON Cache**:
```bash
# Linux/macOS
export CLANG_INDEX_USE_SQLITE=0

# Windows
set CLANG_INDEX_USE_SQLITE=0
```

**CLANG_INDEX_CACHE_DIR**:
- **Default**: `.mcp_cache` (relative to project root)
- **Use Case**: Custom cache location (e.g., faster SSD, network storage)
- **Note**: Cache location must be on a local filesystem (not NFS)

**Example**:
```bash
# Linux/macOS
export CLANG_INDEX_CACHE_DIR="/fast/ssd/cache/my-project"

# Windows
set CLANG_INDEX_CACHE_DIR=D:\cache\my-project
```

**SQLite Cache Features**:
- **FTS5 Full-Text Search**: Lightning-fast prefix matching
- **Automatic Migration**: Seamless migration from JSON cache
- **Concurrent Access**: WAL mode for multi-process safety
- **Health Monitoring**: Built-in integrity checks
- **Database Maintenance**: Auto VACUUM, OPTIMIZE, ANALYZE

**Diagnostic Tools**:
```bash
# View cache statistics
python3 scripts/cache_stats.py

# Diagnose cache health
python3 scripts/diagnose_cache.py

# Manually migrate JSON → SQLite
python3 scripts/migrate_cache.py
```

**See Also**:
- [Migration Guide](docs/MIGRATION_GUIDE.md) - Detailed migration instructions
- [Troubleshooting](TROUBLESHOOTING.md) - SQLite-specific issues
- [Architecture](ANALYSIS_STORAGE_ARCHITECTURE.md) - Technical details

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

---

## Incremental Analysis

The analyzer supports intelligent incremental analysis that dramatically reduces re-analysis time when files change. Instead of re-analyzing the entire project, only affected files are re-parsed.

### How It Works

The incremental analysis system tracks:
- **File changes** (added, modified, deleted) via MD5 hashing
- **Header dependencies** via include graph traversal
- **Compilation changes** via per-entry diffing of `compile_commands.json`

When you refresh the project, the analyzer:
1. Detects which files have changed since last analysis
2. Identifies affected files (e.g., files that include a modified header)
3. Re-analyzes only those files, skipping unchanged code
4. Updates the cache with new results

### Performance Benefits

| Scenario | Full Re-analysis | Incremental Analysis | Speedup |
|----------|-----------------|---------------------|---------|
| Single file changed | 30-60s | <1s | **30-60x** |
| Header changed (10 dependents) | 30-60s | 3-5s | **6-10x** |
| No changes detected | 30-60s | <0.1s | **300-600x** |
| `compile_commands.json` changed (1 entry) | 30-60s | 1-2s | **15-30x** |

*Times based on a medium-sized project (~1000 files). Actual performance varies by project size.*

### Project Identity

Projects are uniquely identified by the combination of:
- **Source directory path** (absolute)
- **Configuration file path** (absolute, optional)

Different combinations create separate cache directories:

```bash
# Same source, no config → Same cache
/project + (no config) → cache: project_abc123def456

# Same source, different config → Different caches
/project + /project/config1.json → cache: project_111aaa222bbb
/project + /project/config2.json → cache: project_333ccc444ddd

# Different source, same config name → Different caches
/project1 + /project1/config.json → cache: project1_555eee666fff
/project2 + /project2/config.json → cache: project2_777ggg888hhh
```

This enables **multi-configuration workflows** where you can work with the same source code using different build configurations (Debug/Release, different compiler flags, etc.) without cache conflicts.

### MCP Tool Integration

#### `set_project_directory` Tool

When initializing a project, you can control incremental analysis behavior:

```json
{
  "project_path": "/path/to/project",
  "config_file": "/path/to/project/.cpp-analyzer-config.json",
  "auto_refresh": true
}
```

**Parameters:**
- `project_path` (required): Absolute path to project root
- `config_file` (optional): Path to configuration file for project identity
- `auto_refresh` (optional, default `true`): Automatically detect and re-analyze changes after loading cache

**With `auto_refresh=true` (recommended):**
- Loads cache if available
- Automatically detects changes since last analysis
- Re-analyzes only affected files
- Result: Project is always up-to-date with minimal delay

**With `auto_refresh=false`:**
- Loads cache as-is without checking for changes
- Faster startup (skips change detection)
- Use when you know files haven't changed

#### `refresh_project` Tool

Manually refresh the project to detect and re-analyze changes:

```json
{
  "incremental": true,
  "force_full": false
}
```

**Parameters:**
- `incremental` (optional, default `true`): Use incremental analysis
- `force_full` (optional, default `false`): Force full re-analysis of all files

**Modes:**

1. **Incremental (default)**:
   ```json
   {"incremental": true}
   ```
   - Detects changes since last analysis
   - Re-analyzes only affected files
   - Returns detailed change statistics
   - Recommended for regular use

2. **Full refresh**:
   ```json
   {"force_full": true}
   ```
   - Re-analyzes all files regardless of changes
   - Use after major configuration changes
   - Use to rebuild corrupted cache

**Response Format:**
```json
{
  "mode": "incremental",
  "files_analyzed": 5,
  "files_removed": 1,
  "elapsed_seconds": 2.34,
  "changes": {
    "compile_commands_changed": false,
    "added_files": 1,
    "modified_files": 2,
    "modified_headers": 1,
    "removed_files": 1,
    "total_changes": 5
  },
  "message": "Incremental refresh complete: Re-analyzed 5 files, removed 1 files in 2.34s"
}
```

### Change Detection

The analyzer detects several types of changes:

#### 1. Source File Changes
When a `.cpp` or `.cc` file is modified:
- **Only that file** is re-analyzed
- No cascade to other files (source files don't affect each other)

#### 2. Header File Changes
When a `.h`, `.hpp`, or `.hxx` file is modified:
- The analyzer finds all files that include it (directly or transitively)
- **All dependent files** are re-analyzed
- Uses dependency graph for efficient traversal

Example:
```
utils.h modified
  ├─ main.cpp includes utils.h → re-analyzed
  ├─ helper.cpp includes utils.h → re-analyzed
  └─ test.cpp (doesn't include utils.h) → skipped
```

#### 3. New Files Added
When new files appear in the project:
- Added files are analyzed
- If `compile_commands.json` is updated, only new entries are processed

#### 4. Files Deleted
When files are removed:
- Removed from cache
- Removed from dependency graph
- No re-analysis needed

#### 5. `compile_commands.json` Changes
When compilation database changes:
- Per-entry diff identifies which files have different compilation flags
- Only files with changed flags are re-analyzed
- Much faster than full project re-analysis

Example:
```json
// Before
{"file": "main.cpp", "arguments": ["-std=c++17"]}

// After (changed flags)
{"file": "main.cpp", "arguments": ["-std=c++20"]}
// → main.cpp re-analyzed

// File with unchanged flags → skipped
```

### Best Practices

1. **Use `auto_refresh=true`** (default) when initializing projects for automatic freshness
2. **Call `refresh_project`** after bulk file changes (git checkout, code generation, etc.)
3. **Use incremental mode** (default) for regular refreshes
4. **Use `force_full=true`** only when needed:
   - After major configuration changes
   - If cache appears corrupted
   - If you want to rebuild everything from scratch
5. **Leverage multi-config support** by using different config files for Debug/Release builds

### Troubleshooting

**"Changes not detected":**
- Ensure file modification times are updated
- Try `force_full=true` to force re-analysis
- Check that files are within the project directory

**"Too many files re-analyzed":**
- Common headers may trigger widespread re-analysis
- Consider excluding frequently-changing generated headers
- Use `exclude_patterns` in config to skip certain files

**"Cache seems stale":**
- Use `auto_refresh=true` or call `refresh_project`
- As a last resort, delete `.mcp_cache` directory and re-initialize

### Related Documentation

- **Design**: See [docs/INCREMENTAL_ANALYSIS_DESIGN.md](docs/INCREMENTAL_ANALYSIS_DESIGN.md) for architecture details
- **Implementation**: See [docs/INCREMENTAL_ANALYSIS_IMPLEMENTATION_CHECKLIST.md](docs/INCREMENTAL_ANALYSIS_IMPLEMENTATION_CHECKLIST.md) for implementation status
- **Cache Backend**: See [SQLite Cache Configuration](#sqlite-cache-configuration-new-in-v300) section above
