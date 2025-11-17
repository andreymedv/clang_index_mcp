# Troubleshooting Guide

## Performance Issues

### Slow Analysis on Multi-Core Systems

**Symptom**: Analysis is slow despite having multiple CPU cores, low CPU utilization (e.g., 200% on an 8-core/16-thread system)

**Diagnosis**:
```bash
# Check if GIL is the bottleneck
python scripts/diagnose_gil.py /path/to/project
```

If ProcessPoolExecutor shows **1.5x+ speedup**, Python's GIL is limiting parallelism.

**Solution**:
- ProcessPoolExecutor is now **enabled by default** (bypasses GIL)
- Verify it's enabled: Check startup logs for "Concurrency mode: ProcessPool (GIL bypass)"
- If using ThreadPool, remove `CPP_ANALYZER_USE_THREADS=true` environment variable

**Expected Results**:
- CPU utilization should reach 80-100% on multi-core systems
- 6-7x speedup compared to single-threaded on 4+ core systems

### Slow compile_commands.json Loading

**Symptom**: Server takes several seconds to start with large `compile_commands.json` files (40MB+, 1000+ entries)

**Diagnosis**:
```bash
# Check loading time in startup logs
# Look for: "Parsing compile_commands.json (X.X MB)..."
```

**Solutions**:

1. **Install orjson for faster JSON parsing** (3-5x speedup):
   ```bash
   pip install orjson
   ```

2. **Use binary cache** (10-100x speedup on subsequent starts):
   - Cache is automatic, stored in `.clang_index/compile_commands.cache`
   - First load: parses JSON, saves cache
   - Subsequent loads: loads from cache (~0.1s instead of seconds)
   - Cache auto-invalidates when `compile_commands.json` changes

**Expected Results**:
- First load: 1-10s depending on file size and orjson
- Subsequent loads: ~0.1s (cache hit)

### Profile Analysis Performance

**Tool**: `scripts/profile_analysis.py`

**Usage**:
```bash
python scripts/profile_analysis.py /path/to/project
```

**Output**:
- Time spent in libclang parsing
- Time spent in AST traversal
- Lock wait time
- Cache operations
- Percentage breakdown

**Interpreting Results**:
- High lock wait time → ProcessPool should help (should be enabled by default)
- High libclang parse time → Normal for complex code
- High cache operations → Check disk I/O speed

## compile_commands.json Issues

### All Files Failing to Parse

If all files are failing with "Error parsing translation unit", follow these steps:

### Step 1: Pull Latest Changes
```bash
cd /Users/andrey/repos/clang_index_mcp
git pull origin claude/mcp-compile-commands-support-01G3N5zhaQbrphNoYJ4aQBBh
```

### Step 2: Run Diagnostic Script
```bash
python scripts/diagnose_compile_commands.py /Users/andrey/repos/llama.cpp
```

Check the output:
- **"Extracted N arguments"** - Should show arguments WITHOUT the compiler path
- **First argument** - Should start with `-` (like `-DGGML_BUILD`), NOT `/` (like `/usr/bin/cc`)

### Step 3: Check libclang Diagnostics

If arguments look correct but parsing still fails, get detailed libclang error messages:

```bash
python scripts/view_parse_errors.py /Users/andrey/repos/llama.cpp --summary
```

Look for actual error messages from libclang (not just "Error parsing translation unit").

### Step 4: Enable Detailed Diagnostics

Create a test script to see libclang's actual diagnostics:

```python
#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, '/Users/andrey/repos/clang_index_mcp')

from mcp_server.cpp_analyzer import CppAnalyzer
import clang.cindex

# Create analyzer
analyzer = CppAnalyzer('/Users/andrey/repos/llama.cpp')

# Get first file from compile_commands
files = analyzer.compile_commands_manager.get_all_files()
test_file = files[0]

print(f"Testing: {test_file}")

# Get compile args
args = analyzer.compile_commands_manager.get_compile_args_with_fallback(Path(test_file))
print(f"\nFirst 5 args:")
for i, arg in enumerate(args[:5]):
    print(f"  [{i}] {arg}")

# Try to parse
index = clang.cindex.Index.create()
tu = index.parse(
    test_file,
    args=args,
    options=clang.cindex.TranslationUnit.PARSE_INCOMPLETE |
           clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
)

if tu:
    print(f"\n✅ Parsed successfully!")
    print(f"Diagnostics: {len(list(tu.diagnostics))}")

    # Show diagnostics
    for i, diag in enumerate(tu.diagnostics[:5]):
        print(f"\n[{i+1}] {diag.severity}: {diag.spelling}")
        if diag.location.file:
            print(f"    {diag.location.file}:{diag.location.line}:{diag.location.column}")
else:
    print("❌ Failed to parse!")
```

Save this as `test_libclang.py` and run it to see what libclang is actually reporting.

## Common Issues

### Issue 1: Compiler Path Not Stripped
**Symptom**: First argument is `/usr/bin/cc` or similar
**Fix**: Already fixed in latest commit `d93d66e`
**Action**: Pull latest changes

### Issue 2: libclang Version Mismatch
**Symptom**: Parse errors even with correct arguments
**Fix**: Check libclang version
```bash
python3 -c "import clang.cindex; print(clang.cindex.conf.lib.clang_getClangVersion())"
```

### Issue 3: Missing System Headers
**Symptom**: Errors about missing standard library headers
**Fix**: libclang might not find system headers automatically on macOS
**Action**: Add explicit include paths for system headers

### Issue 4: Unsupported Compiler Flags
**Symptom**: Specific files fail with certain flags
**Fix**: Some GCC-specific flags might not be supported by libclang
**Action**: Filter out unsupported flags or use `-Wno-unknown-warning-option`

### Issue 5: macOS SDK Header Not Found (stdbool.h, stdio.h, etc.)
**Symptom**: Errors like `'stdbool.h' file not found` on macOS
**Root Cause**: libclang version doesn't match the macOS SDK version
**Diagnosis**: Run `python scripts/diagnose_libclang.py` to check compatibility
**Fixes**:

#### Option 1: Use System libclang (Recommended)
```bash
# Find system libclang
find /Library/Developer -name "libclang.dylib" 2>/dev/null

# Set environment variable before running
export LIBCLANG_PATH=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib
```

#### Option 2: Install Matching libclang Version
```bash
# Check your system clang version
clang --version
# Example output: Apple clang version 14.0.0

# Install matching libclang
pip install libclang==14.0.0
```

#### Option 3: Add Resource Directory
```bash
# Find resource directory
clang -print-resource-dir
# Example: /Library/Developer/CommandLineTools/usr/lib/clang/14.0.0

# Add to .cpp-analyzer-config.json
{
  "compile_commands": {
    "fallback_args": [
      "-resource-dir", "/Library/Developer/CommandLineTools/usr/lib/clang/14.0.0",
      "-nostdinc++",
      "-isystem", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1",
      "-isystem", "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include"
    ]
  }
}
```

#### Option 4: Update Command Line Tools
```bash
# Update to latest version
softwareupdate --install --all

# Or reinstall
sudo rm -rf /Library/Developer/CommandLineTools
xcode-select --install
```

## Getting Help

If none of the above helps, please provide:
1. Output from `scripts/diagnose_compile_commands.py`
2. Output from `scripts/diagnose_libclang.py` (for macOS header issues)
3. Output from `scripts/view_parse_errors.py -l 1 -v`
4. First 10 compilation arguments being passed to libclang
5. Your libclang version and system compiler version
