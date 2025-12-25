# Issue #003: macOS libclang Discovery - Hardcoded Paths Don't Match System Installations

**Status:** 🟡 Open
**Priority:** MEDIUM
**Type:** Bug - Platform Compatibility
**Affects:** macOS users with Xcode CLT or Homebrew LLVM

## Summary

MCP server fails to find system-installed libclang on macOS and falls back to downloading bundled version, despite libclang being available via Xcode Command Line Tools or Homebrew.

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

## Related

- Originally documented as Issue #9 in manual test observations
- Affects both Apple Silicon and Intel Macs
- Related to `scripts/download_libclang.py` and `mcp_server/cpp_analyzer.py`

---

**Reported:** 2025-12-25
**Documentation:** [MACOS_LIBCLANG_DISCOVERY.md](../MACOS_LIBCLANG_DISCOVERY.md)
**Platform:** macOS (both Apple Silicon and Intel)
