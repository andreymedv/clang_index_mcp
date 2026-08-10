# Agent Command Reference

Detailed command reference for working with this repository. Read this file when you need setup instructions, a full list of make targets, or debugging commands.

## Setup

```bash
# Initial setup (creates venv, installs deps, downloads libclang)
./server_setup.sh              # Linux/macOS
server_setup.bat                # Windows

# Activate virtual environment
source mcp_env/bin/activate     # Linux/macOS
mcp_env\Scripts\activate        # Windows

# Install dev dependencies
make install-dev

# Verify installation
python scripts/test_installation.py
```

## Testing

```bash
make test                       # Run all tests with pytest (never run multiple pytest processes simultaneously — SQLite cache conflicts)
make test-coverage              # Run tests with coverage report (htmlcov/)
make test-compile-commands      # Run compile_commands integration tests (tests/test_runner.py)
make test-installation          # Test installation and basic functionality

# Run specific tests
pytest tests/test_analyzer_integration.py
pytest tests/test_compile_commands_manager.py::test_specific
pytest -v -s                    # Verbose with print statements
```

> **Note for AI assistants:** `make test` runs the full pytest suite. Its duration is host-dependent and can be long enough to exceed default command/tool timeouts. Run it as a background task if needed, and consult the local agent memory for host-specific timeout and agent-harness instructions.

## Code Quality

```bash
make lint                       # Run flake8 (max-line-length=100)
make format                     # Format code with black (line-length=100)
make format-check               # Check formatting without changes
make type-check                 # Run mypy type checking
make check                      # Run all checks (format, lint, type)
```

## Running the Server

```bash
make run                        # Run MCP server (stdio transport)
make dev                        # Run with MCP_DEBUG=1 and PYTHONUNBUFFERED=1

# Alternative transport protocols
python -m clang_index_mcp                                        # stdio (default)
python -m clang_index_mcp --transport http --port 8000           # HTTP
python -m clang_index_mcp --transport sse --port 8000            # SSE
```

## Testing and Debugging

**Automated Testing (Recommended):**

Use the `/test-mcp` skill for automated MCP server testing:

```bash
# Quick smoke test
/test-mcp test=basic-indexing tier=1

# Test incremental analysis
/test-mcp test=incremental-refresh tier=1

# Run custom YAML scenario
/test-mcp test=custom scenario=my-test.yaml tier=1

# Run pytest suite
/test-mcp pytest
```

**Documentation:**
- [User Guide](docs/testing/TEST_MCP_USER_GUIDE.md) - Complete usage guide
- [Command Reference](docs/testing/TEST_MCP_COMMAND_REFERENCE.md) - All commands
- [FAQ](docs/testing/TEST_MCP_FAQ.md) - Troubleshooting
- [Development Docs](docs/testing/MCP_TESTING_SKILL.md) - Technical specification

**Manual Testing (Advanced):**

For low-level debugging or when automated testing isn't suitable, use SSE transport with curl:

```bash
# Start SSE server
MCP_DEBUG=1 PYTHONUNBUFFERED=1 python -m clang_index_mcp --transport sse --port 8000

# Call MCP tool
curl -s -X POST http://localhost:8000/mcp/v1/tools/call \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{...}}' | jq
```

See [docs/testing/CLAUDE_TESTING_GUIDE.md](docs/testing/CLAUDE_TESTING_GUIDE.md) for detailed manual testing approaches.

## Building and Distribution

```bash
make build                      # Build both wheel and source distributions
make build-wheel                # Build wheel only (dist/clang_index_mcp-*.whl)
make install-wheel              # Build and install wheel locally
make install-editable           # Install in editable mode (recommended for dev)

# After install-editable or install-wheel, you can run:
clang-index-mcp                 # Entry point script (equivalent to python -m clang_index_mcp)
```

## Maintenance

```bash
make clean                      # Clean cache and build artifacts
make clean-cache                # Clean only .mcp_cache/
make clean-all                  # Clean everything including mcp_env/
make download-libclang          # Download libclang binary for platform
```

## Shortcuts

```bash
make t                          # test
make tc                         # test-coverage
make l                          # lint
make f                          # format
make c                          # clean
make r                          # run
make b                          # build
make ie                         # install-editable
```
