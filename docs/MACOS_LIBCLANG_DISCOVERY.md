# Issue: macOS libclang Discovery - Hardcoded Paths Don't Match System Installations

**Status:** 🔴 **OPEN**
**Date Reported:** 2025-12-25
**Platform:** macOS (Apple Silicon M1)
**Severity:** Medium - Server falls back to download instead of using system libclang
**Impact:** Unnecessary downloads, version mismatches, disk space waste

## Observed Behavior

The MCP server fails to find system-installed libclang on macOS and falls back to downloading bundled version, despite libclang being available on the system.

## System Configuration

**Platform:** macOS (Apple Silicon M1)

**Available libclang installations:**
1. **Xcode Command Line Tools:**
   ```
   /Library/Developer/CommandLineTools/usr/lib/libclang.dylib
   ```

2. **Homebrew (Apple Silicon):**
   ```
   /opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib
   ```

Both installations are valid and functional, but server doesn't detect them.

## Root Cause

**Hardcoded search paths don't match actual system locations**

The current implementation likely searches:
- `/usr/local/lib/libclang.dylib` (Intel Homebrew)
- `/usr/lib/libclang.dylib` (system location)
- `lib/macos/lib/libclang.dylib` (bundled fallback)

**Missing:**
- ❌ `/Library/Developer/CommandLineTools/usr/lib/` (Xcode CLT)
- ❌ `/opt/homebrew/Cellar/llvm/*/lib/` (Apple Silicon Homebrew with version glob)
- ❌ `/opt/homebrew/lib/` (Homebrew symlink location)

## Impact

### Current Behavior (Suboptimal)
1. Server starts up
2. Searches hardcoded paths
3. Doesn't find system libclang
4. Downloads bundled libclang to `lib/macos/lib/libclang.dylib`
5. Uses downloaded version

### Issues with Current Approach
- **Unnecessary downloads:** User already has libclang (2 copies!)
- **Version mismatch:** Bundled version may differ from user's compiler
- **Disk space waste:** Duplicate libclang installation (~100MB+)
- **Maintenance overhead:** Need to keep bundled version updated
- **Compatibility issues:** System libclang guaranteed compatible with user's toolchain

### Desired Behavior
1. Server starts up
2. **Finds system libclang** via smart discovery
3. Uses system version (matches user's compiler)
4. No download needed

## Technical Details

### Code Location
Likely in `scripts/download_libclang.py` or `mcp_server/cpp_analyzer.py` during initialization.

### Current Search Order (Estimated)
```python
SEARCH_PATHS = [
    "/usr/local/lib/libclang.dylib",  # Intel Homebrew
    "/usr/lib/libclang.dylib",        # System (rare on macOS)
    "lib/macos/lib/libclang.dylib",   # Bundled
]
```

### Recommended Search Order
```python
MACOS_SEARCH_PATHS = [
    # 1. Xcode Command Line Tools (most common, official)
    "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",

    # 2. Homebrew Apple Silicon (versioned, use glob)
    "/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib",
    "/opt/homebrew/lib/libclang.dylib",  # Symlink

    # 3. Homebrew Intel
    "/usr/local/Cellar/llvm/*/lib/libclang.dylib",
    "/usr/local/lib/libclang.dylib",

    # 4. MacPorts
    "/opt/local/libexec/llvm-*/lib/libclang.dylib",

    # 5. System (rare)
    "/usr/lib/libclang.dylib",

    # 6. Bundled (last resort)
    "lib/macos/lib/libclang.dylib",
]
```

## Recommended Solutions

### Option 1: Expand Hardcoded Search Paths (Quick Fix)

**Add missing paths to search list:**

```python
import glob
import os

def find_libclang_macos():
    """Find libclang on macOS with comprehensive search."""
    search_paths = [
        # Xcode Command Line Tools
        "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",

        # Homebrew Apple Silicon
        "/opt/homebrew/lib/libclang.dylib",

        # Homebrew Intel
        "/usr/local/lib/libclang.dylib",
    ]

    # Search versioned Homebrew installations
    search_globs = [
        "/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib",
        "/usr/local/Cellar/llvm/*/lib/libclang.dylib",
        "/opt/local/libexec/llvm-*/lib/libclang.dylib",
    ]

    # Try direct paths first
    for path in search_paths:
        if os.path.exists(path):
            return path

    # Try glob patterns (get latest version)
    for pattern in search_globs:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]  # Latest version

    return None
```

**Pros:**
- Quick to implement
- No external dependencies
- Covers all common installation locations

**Cons:**
- Still hardcoded (won't catch unusual installations)
- Glob patterns may be slow with many versions

### Option 2: Smart Discovery Using System Tools (BEST)

**Use system tools to locate libclang:**

```python
import subprocess
import os

def discover_libclang_macos():
    """Discover libclang using system tools."""

    # Method 1: Use xcrun to find Xcode tools
    try:
        result = subprocess.run(
            ["xcrun", "--show-sdk-path"],
            capture_output=True, text=True, check=True
        )
        sdk_path = result.stdout.strip()
        # Derive lib path from SDK path
        lib_path = sdk_path.replace("/SDKs/", "/usr/lib/")
        clang_path = os.path.join(lib_path, "libclang.dylib")
        if os.path.exists(clang_path):
            return clang_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Method 2: Use brew to find Homebrew LLVM
    try:
        result = subprocess.run(
            ["brew", "--prefix", "llvm"],
            capture_output=True, text=True, check=True
        )
        brew_prefix = result.stdout.strip()
        clang_path = os.path.join(brew_prefix, "lib", "libclang.dylib")
        if os.path.exists(clang_path):
            return clang_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Method 3: Use llvm-config if available
    try:
        result = subprocess.run(
            ["llvm-config", "--libdir"],
            capture_output=True, text=True, check=True
        )
        lib_dir = result.stdout.strip()
        clang_path = os.path.join(lib_dir, "libclang.dylib")
        if os.path.exists(clang_path):
            return clang_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Method 4: Derive from clang binary location
    try:
        result = subprocess.run(
            ["which", "clang"],
            capture_output=True, text=True, check=True
        )
        clang_bin = result.stdout.strip()
        # /usr/bin/clang -> /usr/lib/libclang.dylib
        # /opt/homebrew/bin/clang -> /opt/homebrew/lib/libclang.dylib
        lib_dir = os.path.join(os.path.dirname(os.path.dirname(clang_bin)), "lib")
        clang_path = os.path.join(lib_dir, "libclang.dylib")
        if os.path.exists(clang_path):
            return clang_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return None
```

**Pros:**
- Works with any installation
- No hardcoded paths
- Finds exact version user is using
- Future-proof

**Cons:**
- Requires external tools (xcrun, brew, which)
- Slightly slower (subprocess calls)
- Tools may not be available in all environments

### Option 3: Hybrid Approach (RECOMMENDED)

**Combine both methods:**

```python
def find_libclang_macos():
    """Find libclang using smart discovery + fallback search."""

    # Priority 1: LIBCLANG_PATH environment variable (user override)
    env_path = os.environ.get("LIBCLANG_PATH")
    if env_path and os.path.exists(env_path):
        logger.info(f"Using LIBCLANG_PATH: {env_path}")
        return env_path

    # Priority 2: Smart discovery (best match)
    discovered = discover_libclang_macos()
    if discovered:
        logger.info(f"Discovered libclang: {discovered}")
        return discovered

    # Priority 3: Hardcoded common paths
    found = search_hardcoded_paths_macos()
    if found:
        logger.info(f"Found libclang at: {found}")
        return found

    # Priority 4: Bundled version (last resort)
    bundled = "lib/macos/lib/libclang.dylib"
    if os.path.exists(bundled):
        logger.warning(f"Using bundled libclang: {bundled}")
        return bundled

    # Not found - will trigger download
    logger.warning("libclang not found, will download")
    return None
```

**Pros:**
- Best of both worlds
- Fast (tries smart discovery first)
- Reliable fallback
- User can override with env var

**Cons:**
- Slightly more complex

## Implementation Plan

### Immediate (Workaround)
1. ✅ **Document issue** (this file)
2. 🔲 **Document workaround** for users:
   ```bash
   # Set environment variable
   export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib
   # Or
   export LIBCLANG_PATH=/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib
   ```

### Short Term (Fix)
1. 🔲 **Implement Option 3** (Hybrid approach)
2. 🔲 **Add Xcode Command Line Tools path** to search list
3. 🔲 **Add Homebrew glob patterns** for versioned installations
4. 🔲 **Test on multiple macOS configurations:**
   - Apple Silicon with CLT only
   - Apple Silicon with Homebrew
   - Intel Mac with Homebrew
   - macOS without any LLVM installed (should download)

### Long Term (Enhancement)
1. 🔲 **Add configuration file support:**
   ```json
   // cpp-analyzer-config.json
   {
     "libclang": {
       "path": "/opt/homebrew/Cellar/llvm/21.1.7/lib/libclang.dylib",
       "prefer_system": true
     }
   }
   ```
2. 🔲 **Add --libclang-path CLI option**
3. 🔲 **Add version validation:**
   - Check libclang version
   - Warn if version too old/new
4. 🔲 **Improve diagnostics:**
   - Log all search attempts
   - Show which method succeeded
   - Warn if using bundled vs system

## Testing

### Verify Issue
```bash
# Check what libclang server will use
python -c "
from clang.cindex import Config
print(Config.library_file)
"

# Check if system libclang exists
ls -la /Library/Developer/CommandLineTools/usr/lib/libclang.dylib
ls -la /opt/homebrew/Cellar/llvm/*/lib/libclang.dylib
```

### Test Fix
After implementing solution:
```bash
# Should use system libclang (not bundled)
python -m mcp_server.cpp_mcp_server --help
# Check logs for "Discovered libclang: /Library/Developer/..."

# Should not download
ls lib/macos/lib/libclang.dylib
# Should not exist if system version found
```

## Workaround for Users

Until fixed, users can set environment variable:

```bash
# Option 1: Xcode Command Line Tools
export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib

# Option 2: Homebrew (find your version)
export LIBCLANG_PATH=$(ls -d /opt/homebrew/Cellar/llvm/*/lib/libclang.dylib | tail -1)

# Add to shell profile for persistence
echo 'export LIBCLANG_PATH=/Library/Developer/CommandLineTools/usr/lib/libclang.dylib' >> ~/.zshrc
```

## Related

- **Issue #9:** Originally documented in MANUAL_TEST_OBSERVATIONS (Issue #9)
  - See `docs/archived/MANUAL_TEST_OBSERVATIONS_DETAILED.md` lines 712-950
- **Original observation:** macOS with Homebrew/Xcode installations
- **Code location:** `scripts/download_libclang.py`, `mcp_server/cpp_analyzer.py`

## References

- **macOS libclang locations:**
  - Xcode CLT: `/Library/Developer/CommandLineTools/usr/lib/`
  - Homebrew Apple Silicon: `/opt/homebrew/Cellar/llvm/*/lib/`
  - Homebrew Intel: `/usr/local/Cellar/llvm/*/lib/`
- **Discovery tools:**
  - `xcrun --show-sdk-path` - Find Xcode SDK
  - `brew --prefix llvm` - Find Homebrew LLVM
  - `llvm-config --libdir` - Find LLVM lib directory
  - `which clang` - Find clang binary

---

**Last Updated:** 2025-12-25
**Priority:** MEDIUM
**Platforms Affected:** macOS (all versions, both Intel and Apple Silicon)
**Recommended Solution:** Hybrid approach (smart discovery + hardcoded fallback)
