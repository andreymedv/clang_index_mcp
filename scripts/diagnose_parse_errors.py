#!/usr/bin/env python3
"""
Diagnostic script for investigating parse errors in C++ MCP server.

This script helps diagnose why files are failing to parse by:
1. Showing compilation arguments being used
2. Testing libclang directly with those arguments
3. Providing suggestions for fixes
"""

import sys
import os
from pathlib import Path
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.compile_commands_manager import CompileCommandsManager
from clang.cindex import Index, TranslationUnit, TranslationUnitLoadError


def diagnose_file(project_path: str, file_path: str):
    """Diagnose parsing issues for a specific file."""
    print("=" * 80)
    print("C++ MCP Server - Parse Error Diagnostics")
    print("=" * 80)
    print()

    project_path = Path(project_path).absolute()
    file_path = Path(file_path).absolute()

    if not project_path.exists():
        print(f"Error: Project path does not exist: {project_path}")
        return

    if not file_path.exists():
        print(f"Error: File path does not exist: {file_path}")
        return

    print(f"Project: {project_path}")
    print(f"File: {file_path}")
    print()

    # Create analyzer to get compilation arguments
    print("1. Initializing analyzer...")
    analyzer = CppAnalyzer(str(project_path))
    print(f"   Compile commands enabled: {analyzer.compile_commands_manager.enabled}")
    print(f"   Clang resource dir: {analyzer.compile_commands_manager.clang_resource_dir or 'NOT FOUND'}")
    print()

    # Get compilation arguments
    print("2. Getting compilation arguments...")
    args = analyzer.compile_commands_manager.get_compile_args_with_fallback(file_path)

    is_from_compile_commands = analyzer.compile_commands_manager.is_file_supported(file_path)
    source = "compile_commands.json" if is_from_compile_commands else "fallback (hardcoded)"
    print(f"   Source: {source}")
    print(f"   Number of args: {len(args)}")
    print()
    print("   Arguments:")
    for i, arg in enumerate(args):
        print(f"     [{i:2d}] {arg}")
    print()

    # Try parsing with different options
    print("3. Testing libclang parsing with different options...")
    index = Index.create()

    parse_attempts = [
        (TranslationUnit.PARSE_INCOMPLETE | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
         "PARSE_INCOMPLETE | PARSE_DETAILED_PROCESSING_RECORD (default)"),
        (TranslationUnit.PARSE_INCOMPLETE,
         "PARSE_INCOMPLETE only"),
        (0,
         "No special options"),
    ]

    successful_parse = None
    for options, description in parse_attempts:
        print(f"   Attempt: {description}")
        try:
            tu = index.parse(str(file_path), args=args, options=options)
            if tu:
                print(f"   ✓ SUCCESS with {description}")

                # Check for errors in diagnostics
                errors = [d for d in tu.diagnostics if d.severity >= 3]  # Error or Fatal
                warnings = [d for d in tu.diagnostics if d.severity == 2]  # Warning

                print(f"     Diagnostics: {len(errors)} errors, {len(warnings)} warnings")

                if errors:
                    print("     Errors:")
                    for diag in errors[:5]:  # Show first 5 errors
                        print(f"       - {diag.spelling} (line {diag.location.line})")
                    if len(errors) > 5:
                        print(f"       ... and {len(errors) - 5} more errors")

                successful_parse = (tu, options, description)
                break
            else:
                print("   ✗ Failed: Translation unit is None")
        except TranslationUnitLoadError as e:
            print(f"   ✗ Failed: TranslationUnitLoadError - {e}")
        except Exception as e:
            print(f"   ✗ Failed: {type(e).__name__} - {e}")
        print()

    # Provide recommendations
    print()
    print("4. Recommendations:")
    print()

    if not successful_parse:
        print("   ✗ All parse attempts failed!")
        print()
        print("   Possible issues:")
        print("   1. Missing system headers")
        if not analyzer.compile_commands_manager.clang_resource_dir:
            print("      → Clang resource directory not detected")
            print("      → Install clang: sudo apt-get install clang (Linux)")
            print("                       brew install llvm (macOS)")

        print("   2. Incompatible compilation arguments")
        if is_from_compile_commands:
            print("      → Arguments from compile_commands.json may be incompatible with libclang")
            print("      → Try disabling compile_commands in config: 'compile_commands.enabled: false'")

        problematic_args = [arg for arg in args if any(x in arg for x in
                           ['-fms-compatibility', '/clr', '-m32', '-m64'])]
        if problematic_args:
            print(f"      → Found potentially problematic args: {problematic_args}")

        print("   3. C++ standard compatibility")
        std_args = [arg for arg in args if '-std=' in arg]
        if std_args:
            print(f"      → C++ standard: {std_args}")
            print("      → Make sure libclang supports this standard")
    else:
        tu, options, description = successful_parse
        print(f"   ✓ File can be parsed with: {description}")
        print()
        print("   The MCP server will now automatically use compatible parse options.")
        print("   If you're still seeing errors, they may be from actual C++ compilation issues")
        print("   rather than libclang parsing failures.")

    print()
    print("=" * 80)


def main():
    if len(sys.argv) < 3:
        print("Usage: python diagnose_parse_errors.py <project-path> <file-path>")
        print()
        print("Example:")
        print("  python diagnose_parse_errors.py /path/to/project /path/to/project/src/file.cpp")
        sys.exit(1)

    project_path = sys.argv[1]
    file_path = sys.argv[2]

    diagnose_file(project_path, file_path)


if __name__ == "__main__":
    main()
