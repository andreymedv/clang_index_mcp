# macOS Testing Notes

> **Note:** This document covers macOS-specific testing issues. For general testing documentation, see [TESTING.md](TESTING.md).

## libclang Configuration on macOS

On macOS (especially M1/M2 systems), the HTTP and SSE transport tests may fail with:

```
Exception: library file must be set before before using any other functionalities in libclang.
```

## Why This Happens

The error occurs because:

1. Tests import `mcp_server.cpp_mcp_server` which triggers module-level libclang initialization
2. The libclang library path detection may fail on macOS if:
   - libclang is not installed
   - It's installed in a non-standard location
   - Homebrew paths are not in the expected locations

## Solution

The HTTP/SSE transport tests now use a **mock MCP server** instead of the real one. This:

- Avoids libclang initialization entirely for transport tests
- Tests only the HTTP/SSE protocol layer, not the C++ analyzer
- Works on all platforms without requiring libclang

## Installing libclang on macOS

If you want to run the full integration tests with C++ analysis:

### Option 1: Homebrew (Recommended for M1/M2)

```bash
# Install LLVM via Homebrew
brew install llvm

# libclang will be at:
# /opt/homebrew/opt/llvm/lib/libclang.dylib  (M1/M2)
# /usr/local/opt/llvm/lib/libclang.dylib     (Intel)
```

### Option 2: Official LLVM

Download from https://releases.llvm.org/ and install to `/usr/local/opt/llvm`

### Option 3: Xcode Command Line Tools

```bash
xcode-select --install
# libclang will be at:
# /Library/Developer/CommandLineTools/usr/lib/libclang.dylib
```

## Verifying libclang Installation

```bash
# Check if libclang is found
python3 -c "
from clang.cindex import Config
import os

# Try common macOS paths
paths = [
    '/opt/homebrew/opt/llvm/lib/libclang.dylib',  # M1/M2
    '/usr/local/opt/llvm/lib/libclang.dylib',      # Intel
    '/Library/Developer/CommandLineTools/usr/lib/libclang.dylib',  # Xcode
]

for path in paths:
    if os.path.exists(path):
        print(f'Found: {path}')
        Config.set_library_file(path)
        print('✓ libclang configured successfully')
        break
else:
    print('✗ libclang not found in standard locations')
"
```

## Running Tests on macOS

### HTTP/SSE Transport Tests (No libclang required)

```bash
pytest tests/test_http_transport.py -v
pytest tests/test_sse_transport.py -v
pytest tests/test_transport_integration.py -v
```

These tests use mock servers and don't require libclang.

### Full Integration Tests (Requires libclang)

```bash
# Install libclang first (see above)
pytest tests/ -v
```

## Troubleshooting

### Test still fails with libclang error

If you see libclang errors even after the fix:

1. **Clear Python cache**:
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} +
   find . -type f -name "*.pyc" -delete
   ```

2. **Reinstall the package**:
   ```bash
   pip uninstall clang-index-mcp
   pip install -e .
   ```

3. **Check which libclang is being used**:
   ```bash
   python3 -m mcp_server.cpp_mcp_server --help 2>&1 | grep libclang
   ```

### Server won't start with "library file must be set"

This means libclang is not installed or not found. See installation instructions above.

### Homebrew libclang not found on M1/M2

Ensure you're using the ARM64 native version of Homebrew:

```bash
# Check Homebrew architecture
brew --prefix
# Should output: /opt/homebrew (for M1/M2)
# NOT: /usr/local (that's Intel)

# If wrong, reinstall Homebrew:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Platform-Specific Notes

### M1/M2 (Apple Silicon)

- Use native ARM64 Homebrew (`/opt/homebrew`)
- libclang path: `/opt/homebrew/opt/llvm/lib/libclang.dylib`
- May need Rosetta 2 for some Python packages

### Intel Mac

- Use standard Homebrew (`/usr/local`)
- libclang path: `/usr/local/opt/llvm/lib/libclang.dylib`

### macOS Catalina or earlier

- Xcode Command Line Tools path may differ
- Check: `/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib`

## Additional Resources

- [libclang Python bindings](https://pypi.org/project/libclang/)
- [LLVM downloads](https://releases.llvm.org/)
- [Homebrew LLVM formula](https://formulae.brew.sh/formula/llvm)
