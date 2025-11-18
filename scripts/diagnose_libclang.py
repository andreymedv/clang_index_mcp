#!/usr/bin/env python3
"""
Diagnostic script to check libclang and system header compatibility.

This helps diagnose issues where libclang can't find system headers on macOS.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import clang.cindex
import subprocess
import platform


def check_libclang_version():
    """Check the version of libclang being used."""
    print("=" * 70)
    print("LIBCLANG VERSION")
    print("=" * 70)

    version = clang.cindex.conf.lib.clang_getClangVersion()
    version_str = version.spelling if hasattr(version, 'spelling') else str(version)
    print(f"libclang version: {version_str}")

    # Get the library path
    lib_path = clang.cindex.conf.lib._name if hasattr(clang.cindex.conf.lib, '_name') else "unknown"
    print(f"libclang library: {lib_path}")

    return version_str


def check_system_compiler():
    """Check the system compiler version."""
    print("\n" + "=" * 70)
    print("SYSTEM COMPILER")
    print("=" * 70)

    if platform.system() == "Darwin":
        try:
            result = subprocess.run(['clang', '--version'], capture_output=True, text=True)
            print(result.stdout)
        except FileNotFoundError:
            print("clang not found in PATH")
    elif platform.system() == "Linux":
        try:
            result = subprocess.run(['gcc', '--version'], capture_output=True, text=True)
            print(result.stdout.split('\n')[0])
        except FileNotFoundError:
            print("gcc not found in PATH")


def check_sdk_paths():
    """Check for available SDKs on macOS."""
    if platform.system() != "Darwin":
        return

    print("\n" + "=" * 70)
    print("MACOS SDK PATHS")
    print("=" * 70)

    sdk_base = Path("/Library/Developer/CommandLineTools/SDKs")
    if sdk_base.exists():
        sdks = sorted(sdk_base.glob("MacOSX*.sdk"))
        for sdk in sdks:
            print(f"  {sdk.name}")
            # Check for stdbool.h
            stdbool_paths = [
                sdk / "usr/include/stdbool.h",
                sdk / "usr/include/c++/v1/stdbool.h",
            ]
            for path in stdbool_paths:
                if path.exists():
                    print(f"    [OK] {path.relative_to(sdk)}")
                else:
                    print(f"    [X] {path.relative_to(sdk)} (not found)")
    else:
        print(f"SDK directory not found: {sdk_base}")


def test_simple_parse():
    """Test parsing a simple C++ file."""
    print("\n" + "=" * 70)
    print("SIMPLE PARSE TEST")
    print("=" * 70)

    # Create a simple test file
    test_code = """
#include <stdbool.h>
#include <stdio.h>

int main() {
    bool b = true;
    return 0;
}
"""

    # Try to parse with default arguments
    index = clang.cindex.Index.create()

    # Create temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
        f.write(test_code)
        temp_path = f.name

    try:
        # Try parsing without any arguments
        print("Testing parse without extra arguments...")
        tu = index.parse(temp_path, args=[])

        if tu and tu.diagnostics:
            print(f"Diagnostics ({len(list(tu.diagnostics))}):")
            for d in tu.diagnostics:
                print(f"  {d.severity}: {d.spelling}")
                if d.location.file:
                    print(f"    {d.location.file}:{d.location.line}:{d.location.column}")
        else:
            print("[OK] Parsed successfully without errors!")

    except Exception as e:
        print(f"[X] Parse failed: {e}")
    finally:
        Path(temp_path).unlink()


def suggest_solutions():
    """Suggest solutions for macOS SDK issues."""
    if platform.system() != "Darwin":
        return

    print("\n" + "=" * 70)
    print("SOLUTIONS FOR MACOS SDK ISSUES")
    print("=" * 70)

    print("""
If libclang can't find system headers (like stdbool.h), try these solutions:

1. Install Xcode Command Line Tools (if not already installed):
   xcode-select --install

2. Update to the latest Xcode Command Line Tools:
   softwareupdate --install --all

3. Use the system libclang instead of the pip-installed one:
   - Find system libclang: find /Library/Developer -name "libclang.dylib" 2>/dev/null
   - Set LIBCLANG_PATH environment variable:
     export LIBCLANG_PATH=/path/to/libclang.dylib

4. Add resource directory to compilation arguments:
   - Find resource dir: clang -print-resource-dir
   - Add to your .cpp-analyzer-config.json:
     {
       "compile_commands": {
         "fallback_args": [
           "-resource-dir", "/path/to/resource/dir",
           ...other args...
         ]
       }
     }

5. Use matching SDK version:
   - Run: xcrun --show-sdk-path
   - Ensure compile_commands.json uses the same SDK path

6. Install compatible libclang version:
   - Check your Xcode/CLT version: clang --version
   - Install matching libclang version via pip
   - Example: pip install libclang==14.0.0  (match your clang version)
""")


def main():
    print("\n" + "=" * 70)
    print("LIBCLANG SYSTEM HEADER DIAGNOSTIC")
    print("=" * 70)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")

    check_libclang_version()
    check_system_compiler()

    if platform.system() == "Darwin":
        check_sdk_paths()
        test_simple_parse()
        suggest_solutions()

    print("\n" + "=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
