#!/usr/bin/env python3
"""
Investigate how libclang represents template definitions vs specializations.

This script parses a C++ file with templates and shows detailed AST information
for each template entity to understand:
1. How generic template definitions are represented
2. How explicit specializations are represented
3. How implicit specializations are represented
4. Whether we can distinguish between them
5. What information is available for linking specializations to templates
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup libclang using the same method as the MCP server
from mcp_server import diagnostics
from mcp_server.cpp_mcp_server import find_and_configure_libclang

if not find_and_configure_libclang():
    print("Error: Could not find libclang library!")
    sys.exit(1)

import clang.cindex as clang


def print_cursor_info(cursor, depth=0):
    """Print detailed information about a cursor."""
    indent = "  " * depth

    # Basic info
    print(f"{indent}Kind: {cursor.kind}")
    print(f"{indent}Spelling: {cursor.spelling}")
    print(f"{indent}Display Name: {cursor.displayname}")
    print(f"{indent}Type: {cursor.type.spelling}")
    print(f"{indent}USR: {cursor.get_usr()}")

    # Check if it's a template
    print(
        f"{indent}Is Template: {cursor.kind in [clang.CursorKind.CLASS_TEMPLATE, clang.CursorKind.FUNCTION_TEMPLATE]}"
    )

    # Check for specialization (if attribute exists)
    if hasattr(cursor, "specialized_cursor_template"):
        specialized_cursor = cursor.specialized_cursor_template
        if specialized_cursor and specialized_cursor != cursor:
            print(f"{indent}Is Specialization: YES")
            print(f"{indent}  Template USR: {specialized_cursor.get_usr()}")
            print(f"{indent}  Template Name: {specialized_cursor.spelling}")
        else:
            print(f"{indent}Is Specialization: NO")
    else:
        print(f"{indent}Is Specialization: (attribute not available)")

    # Check template specialization kind
    if hasattr(cursor, "get_template_specialization_kind"):
        try:
            spec_kind = cursor.get_template_specialization_kind()
            print(f"{indent}Template Specialization Kind: {spec_kind}")
        except:
            pass

    # Location
    location = cursor.location
    if location.file:
        print(f"{indent}Location: {location.file.name}:{location.line}:{location.column}")

    print()


def analyze_templates(file_path, compile_args=None):
    """Analyze template representations in a C++ file."""
    print(f"Analyzing file: {file_path}")
    print("=" * 80)
    print()

    # Ensure file path is absolute
    file_path = str(Path(file_path).resolve())
    print(f"Resolved path: {file_path}")
    print()

    # Parse with libclang
    index = clang.Index.create()

    if compile_args is None:
        compile_args = ["-std=c++17", "-I."]

    print(f"Compile args: {compile_args}")
    print()

    try:
        tu = index.parse(
            file_path,
            args=compile_args,
            options=clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
            | clang.TranslationUnit.PARSE_INCOMPLETE,
        )
    except clang.TranslationUnitLoadError as e:
        print(f"Error parsing file: {e}")
        print("\nTrying with different options...")
        try:
            tu = index.parse(file_path, args=compile_args)
        except Exception as e2:
            print(f"Failed again: {e2}")
            return

    if not tu:
        print("Failed to parse file!")
        return

    # Show diagnostics
    print("DIAGNOSTICS:")
    if tu.diagnostics:
        for diag in tu.diagnostics:
            print(f"  {diag.severity}: {diag.spelling}")
    else:
        print("  No diagnostics")
    print()

    # Walk AST and find template entities
    def visit_node(cursor, depth=0):
        """Recursively visit AST nodes."""

        # Check if this is a template-related node
        is_template_related = (
            cursor.kind == clang.CursorKind.CLASS_TEMPLATE
            or cursor.kind == clang.CursorKind.FUNCTION_TEMPLATE
            or cursor.kind == clang.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION
            or cursor.kind == clang.CursorKind.TYPE_ALIAS_TEMPLATE_DECL
        )

        # Check for specializations (if attribute exists)
        if hasattr(cursor, "specialized_cursor_template"):
            is_template_related = is_template_related or (
                (cursor.kind == clang.CursorKind.CLASS_DECL and cursor.specialized_cursor_template)
                or (
                    cursor.kind == clang.CursorKind.FUNCTION_DECL
                    and cursor.specialized_cursor_template
                )
            )

        # Only print template-related entities or classes/functions with template keywords
        if (
            is_template_related
            or (cursor.spelling and "Container" in cursor.spelling)
            or (cursor.spelling and "Pair" in cursor.spelling)
            or (cursor.spelling and "Base" in cursor.spelling)
            or (cursor.spelling and "Tuple" in cursor.spelling)
        ):

            # Skip if from system header
            if cursor.location.file and "template_test_project" in str(cursor.location.file.name):
                print(f"{'=' * 80}")
                print(f"FOUND: {cursor.spelling} (line {cursor.location.line})")
                print(f"{'=' * 80}")
                print_cursor_info(cursor, depth)

        # Recurse
        for child in cursor.get_children():
            visit_node(child, depth + 1)

    print("\n" + "=" * 80)
    print("TEMPLATE ENTITIES IN AST:")
    print("=" * 80 + "\n")

    visit_node(tu.cursor)

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # Default to our test project
        file_path = project_root / "tests/fixtures/template_test_project/templates.h"

    if not Path(file_path).exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    # Check if there's a compile_commands.json in the same directory
    compile_commands_path = Path(file_path).parent / "compile_commands.json"

    compile_args = None
    if compile_commands_path.exists():
        # Load compile args from compile_commands.json
        import json

        with open(compile_commands_path) as f:
            commands = json.load(f)
            for entry in commands:
                if entry["file"] == Path(file_path).name:
                    # Extract args from command
                    command = entry["command"]
                    # Simple extraction - just get -std and -I flags
                    compile_args = ["-std=c++17", f"-I{Path(file_path).parent}"]
                    break

    analyze_templates(file_path, compile_args)


if __name__ == "__main__":
    main()
