#!/usr/bin/env python3
"""
Clang Installation Diagnostic and Auto-Fix Script

This script diagnoses common libclang installation issues and attempts to fix them.

Usage:
    python3 scripts/diagnose_clang.py
    python3 scripts/diagnose_clang.py --fix
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_success(msg):
    print(f"{Colors.GREEN}[OK]{Colors.END} {msg}")


def print_error(msg):
    print(f"{Colors.RED}[X]{Colors.END} {msg}")


def print_warning(msg):
    print(f"{Colors.YELLOW}[WARNING]{Colors.END} {msg}")


def print_info(msg):
    print(f"{Colors.BLUE}[INFO]{Colors.END} {msg}")


def print_section(title):
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{title}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}")


def check_python_version():
    """Check Python version compatibility"""
    print_section("Checking Python Version")

    version = sys.version_info
    print_info(f"Python version: {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print_error("Python 3.8+ required")
        return False

    print_success("Python version is compatible")
    return True


def check_libclang_package():
    """Check if libclang Python package is installed"""
    print_section("Checking libclang Python Package")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "libclang"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # Parse version
            for line in result.stdout.split('\n'):
                if line.startswith('Version:'):
                    version = line.split(':')[1].strip()
                    print_success(f"libclang package installed: {version}")

                    # Check version
                    major_version = int(version.split('.')[0])
                    if major_version < 16:
                        print_warning(f"libclang {version} is old, recommend 16.0.0+")
                        return "outdated"
                    return True

        print_error("libclang package not installed")
        return False

    except Exception as e:
        print_error(f"Error checking libclang package: {e}")
        return False


def check_clang_import():
    """Try importing clang.cindex"""
    print_section("Testing clang.cindex Import")

    try:
        import clang.cindex
        print_success("Successfully imported clang.cindex")

        # Try to get library path
        try:
            lib_path = clang.cindex.conf.lib
            if lib_path:
                print_info(f"Library path: {lib_path}")

                # Check if library file exists
                if hasattr(lib_path, '_name'):
                    lib_file = lib_path._name
                    if os.path.exists(lib_file):
                        print_success(f"Library file exists: {lib_file}")
                        return True
                    else:
                        print_error(f"Library file not found: {lib_file}")
                        return "lib_missing"
            else:
                print_warning("Could not determine library path")

        except Exception as e:
            print_warning(f"Could not check library path: {e}")

        return True

    except ImportError as e:
        print_error(f"Import failed: {e}")
        return False
    except Exception as e:
        print_error(f"Unexpected error during import: {e}")
        return False


def check_libclang_library():
    """Check for libclang shared library"""
    print_section("Checking libclang Shared Library")

    try:
        import clang.cindex

        # Try to create an Index (this actually loads the library)
        try:
            index = clang.cindex.Index.create()
            print_success("Successfully created clang Index (library loaded)")
            return True
        except Exception as e:
            print_error(f"Failed to create Index: {e}")

            # Check common library locations
            print_info("Searching for libclang library...")

            search_paths = [
                "/usr/lib",
                "/usr/lib/x86_64-linux-gnu",
                "/usr/local/lib",
                "/usr/lib/llvm-*/lib",
                str(Path(sys.executable).parent.parent / "lib"),
            ]

            for path in search_paths:
                from glob import glob
                matches = glob(f"{path}/**/libclang.so*", recursive=True)
                if matches:
                    print_info(f"Found libclang at: {matches[0]}")
                    return "found_but_not_loaded"

            print_warning("libclang library not found in standard locations")
            return False

    except ImportError:
        print_error("Cannot import clang.cindex to check library")
        return False


def check_system_clang():
    """Check for system-installed clang"""
    print_section("Checking System Clang Installation")

    try:
        result = subprocess.run(
            ["clang", "--version"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print_success(f"System clang found: {version_line}")
            return True
        else:
            print_warning("System clang not found (not required, but can help)")
            return False

    except FileNotFoundError:
        print_warning("System clang not found (not required)")
        return False


def install_libclang(force=False):
    """Install or reinstall libclang"""
    print_section("Installing libclang")

    try:
        if force:
            print_info("Uninstalling existing libclang...")
            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "libclang"],
                check=False
            )

        print_info("Installing libclang>=16.0.0...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "libclang>=16.0.0"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print_success("libclang installed successfully")
            return True
        else:
            print_error(f"Installation failed: {result.stderr}")
            return False

    except Exception as e:
        print_error(f"Error during installation: {e}")
        return False


def provide_manual_solutions():
    """Print manual solution steps"""
    print_section("Manual Solutions for Common Issues")

    print("""
1. ISSUE: ImportError when importing clang.cindex
   SOLUTION:
   - Reinstall libclang: pip install --force-reinstall libclang
   - Try specific version: pip install libclang==18.1.1

2. ISSUE: Library not found error
   SOLUTION (Linux):
   - Install system packages: sudo apt-get install libclang-dev
   - Or: sudo apt-get install llvm

   SOLUTION (macOS):
   - Install via Homebrew: brew install llvm
   - Set path: export LIBCLANG_PATH=/opt/homebrew/opt/llvm/lib/libclang.dylib

   SOLUTION (Windows):
   - Download LLVM from: https://github.com/llvm/llvm-project/releases
   - Set LIBCLANG_PATH environment variable to libclang.dll location

3. ISSUE: Version conflicts
   SOLUTION:
   - Use virtual environment: python3 -m venv venv && source venv/bin/activate
   - Install fresh: pip install libclang

4. ISSUE: "Wrong ELF class" or architecture mismatch
   SOLUTION:
   - Ensure Python and libclang are same architecture (32 vs 64 bit)
   - Reinstall matching version

5. ISSUE: Works in terminal but not in IDE/tests
   SOLUTION:
   - Ensure IDE uses same Python interpreter
   - Check LD_LIBRARY_PATH or DYLD_LIBRARY_PATH environment variable
   - Restart IDE after installing libclang
""")


def run_comprehensive_test():
    """Run a comprehensive test of clang functionality"""
    print_section("Running Comprehensive Clang Test")

    try:
        import clang.cindex
        from clang.cindex import Index, CursorKind, TranslationUnit

        # Create temp test file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
            f.write("class TestClass { public: void method(); };")
            test_file = f.name

        try:
            # Parse the file
            index = Index.create()
            tu = index.parse(test_file, args=['-std=c++17'])

            if tu:
                print_success("Successfully parsed C++ file")

                # Try to find a class
                found_class = False
                for cursor in tu.cursor.walk_preorder():
                    if cursor.kind == CursorKind.CLASS_DECL and cursor.spelling == "TestClass":
                        found_class = True
                        break

                if found_class:
                    print_success("Successfully analyzed C++ AST - clang is fully functional!")
                    return True
                else:
                    print_warning("Parsed file but couldn't find class (may be OK)")
                    return True
            else:
                print_error("Failed to parse C++ file")
                return False

        finally:
            # Clean up
            os.unlink(test_file)

    except Exception as e:
        print_error(f"Comprehensive test failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Diagnose and fix libclang installation issues")
    parser.add_argument('--fix', action='store_true', help='Attempt to automatically fix issues')
    parser.add_argument('--force-reinstall', action='store_true', help='Force reinstall libclang')
    args = parser.parse_args()

    print(f"{Colors.BOLD}Clang Installation Diagnostic Tool{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}\n")

    # Track issues
    issues = []

    # Run checks
    if not check_python_version():
        issues.append("python_version")

    pkg_status = check_libclang_package()
    if pkg_status == False:
        issues.append("package_missing")
    elif pkg_status == "outdated":
        issues.append("package_outdated")

    import_status = check_clang_import()
    if import_status == False:
        issues.append("import_failed")
    elif import_status == "lib_missing":
        issues.append("lib_missing")

    lib_status = check_libclang_library()
    if lib_status == False:
        issues.append("library_not_found")
    elif lib_status == "found_but_not_loaded":
        issues.append("library_not_loaded")

    check_system_clang()  # Informational only

    # Summary
    print_section("Diagnostic Summary")

    if not issues:
        print_success("All checks passed! Clang is properly installed.")

        # Run comprehensive test
        if run_comprehensive_test():
            print(f"\n{Colors.GREEN}{Colors.BOLD}[OK] EVERYTHING WORKS PERFECTLY!{Colors.END}\n")
            return 0
        else:
            print_warning("Basic checks passed but comprehensive test failed")
            issues.append("comprehensive_test_failed")
    else:
        print_error(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")

    # Attempt fixes
    if args.fix or args.force_reinstall:
        print_section("Attempting Automatic Fixes")

        if "package_missing" in issues or args.force_reinstall:
            if install_libclang(force=args.force_reinstall):
                print_success("Fixed package installation")

                # Re-test
                if check_clang_import() and check_libclang_library():
                    print_success("All issues resolved!")
                    run_comprehensive_test()
                    return 0
            else:
                print_error("Automatic fix failed")
        elif "package_outdated" in issues:
            if install_libclang(force=True):
                print_success("Upgraded libclang package")

    # Provide manual solutions
    if issues:
        provide_manual_solutions()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
