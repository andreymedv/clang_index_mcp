# Issue #003: macOS libclang Discovery - Hardcoded Paths Don't Match System Installations

**Status:** ✅ FIXED
**Priority:** MEDIUM
**Type:** Bug - Platform Compatibility
**Affects:** macOS users with Xcode CLT or Homebrew LLVM
**Date Identified:** 2025-12-25
**Date Resolved:** 2025-12-26
**Fix Commit:** 0ca96eb

## Summary

MCP server failed to find system-installed libclang on macOS and fell back to downloading bundled version, despite libclang being available via Xcode Command Line Tools or Homebrew.

**RESOLUTION:** Implemented hybrid discovery approach with LIBCLANG_PATH support, xcrun smart discovery, and expanded system paths. Server now finds system libclang automatically on macOS.

## Observed System Paths (Apple Silicon M1)

**Available but not detected:**
- `/Library/Developer/CommandLineTools/usr/lib/libclang.dylib` (Xcode CLT)
- `/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib` (Homebrew)

## Root Cause

Hardcoded search paths don't include:
- Xcode Command Line Tools location
- Homebrew Apple Silicon paths with version globs
- Smart discovery using system tools

## Impact

- Unnecessary downloads (~100MB)
- Version mismatch with user's compiler
- Disk space waste (duplicate installations)
- Suboptimal compatibility

## Detailed Analysis

See [MACOS_LIBCLANG_DISCOVERY.md](../MACOS_LIBCLANG_DISCOVERY.md) for comprehensive analysis including:
- Complete root cause analysis
- 3 solution approaches (hardcoded, smart discovery, hybrid)
- Implementation code samples
- Testing procedures
- User workarounds

## Recommended Solution

**Hybrid approach:**
1. Check `LIBCLANG_PATH` environment variable (user override)
2. Try smart discovery (`xcrun`, `brew --prefix llvm`, `which clang`)
3. Search expanded hardcoded paths (including Xcode CLT and Homebrew)
4. Fall back to bundled download (last resort)

**Critical paths to add:**
```python
"/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",  # Xcode CLT
"/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib",              # Homebrew Apple Silicon (glob)
"/opt/homebrew/lib/libclang.dylib",                            # Homebrew symlink
```

## Workaround

Set environment variable:
```bash
export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib
```

---

## Resolution

**Date Fixed:** 2025-12-26
**Fix Implemented:** mcp_server/cpp_mcp_server.py - `find_and_configure_libclang()`

**Implementation:** Hybrid discovery approach with 4-step search:

1. **LIBCLANG_PATH environment variable** (user override)
   - Highest priority, allows manual override
   - Example: `export LIBCLANG_PATH=/path/to/libclang.dylib`

2. **Smart discovery using xcrun** (macOS)
   - Runs `xcrun --find clang` to locate Xcode Command Line Tools
   - Derives libclang path from clang location
   - Timeout protection (5 seconds)

3. **Expanded system path search:**
   - `/Library/Developer/CommandLineTools/usr/lib/libclang.dylib` (Xcode CLT)
   - `/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib` (Homebrew ARM64)
   - `/opt/homebrew/lib/libclang.dylib` (Homebrew symlink)
   - `/usr/local/Cellar/llvm/*/lib/libclang.dylib` (Homebrew Intel)
   - `/opt/local/libexec/llvm-*/lib/libclang.dylib` (MacPorts)
   - Glob patterns sorted to prefer latest versions

4. **Bundled libraries** (last resort fallback)

**Validation:**
- ✅ All required macOS paths present in search list
- ✅ Search order correct (env → smart → system → bundled)
- ✅ xcrun smart discovery implemented
- ✅ LIBCLANG_PATH environment variable supported
- ✅ 4/4 automated tests pass

**See:** test_issue_003_fix.py for validation tests

---

## Related

- Originally documented as Issue #9 in manual test observations
- Affects both Apple Silicon and Intel Macs
- Related to `scripts/download_libclang.py` and `mcp_server/cpp_analyzer.py`

---

**Reported:** 2025-12-25
**Resolved:** 2025-12-26
**Documentation:** [MACOS_LIBCLANG_DISCOVERY.md](../MACOS_LIBCLANG_DISCOVERY.md)
**Platform:** macOS (both Apple Silicon and Intel)
