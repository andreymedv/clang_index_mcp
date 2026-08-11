# Agent Configuration Guide

Read this file when you need to configure the analyzer or understand environment variables and runtime options.

## Mandatory Project Setup

Projects MUST be initialized via a `.json` configuration file passed to `set_project`.

- `project_root`: (Required) Path to the C++ source directory (absolute or relative to config file).
- `exclude_directories`: Dirs to skip (e.g., [".git", "build", "node_modules"])
- `dependency_directories`: Third-party deps (e.g., ["vcpkg_installed", "third_party"])
- `include_dependencies`: Analyze files in dependency dirs (default: true)
- `max_file_size_mb`: Skip files larger than this (default: 10)
- `compile_commands.enabled`: Use compile_commands.json (default: true)
- `compile_commands.path`: Path to compile_commands.json (default: "compile_commands.json")
- `compile_commands.cache_enabled`: Cache parsed compile commands (default: true)

## Environment Variables

- `CPP_ANALYZER_CONFIG=/path/to/config.json`: Override configuration for CLI usage
- `MCP_DEBUG=1`: Enable debug logging
- `PYTHONUNBUFFERED=1`: Unbuffered Python output
- `LIBCLANG_PATH=/path/to/libclang.so`: Override libclang path
- `MCP_CACHE_BASE_DIR=/path/to/cache`: Override the parent directory for all project caches (useful for test/CI isolation)
