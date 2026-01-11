#!/usr/bin/env python3
"""
Investigate libclang alias detection capabilities.
Phase 1.1 of Type Alias Tracking feature.

This script analyzes how libclang represents type aliases (using/typedef)
and what information can be extracted from them.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import clang.cindex
from clang.cindex import CursorKind, TypeKind, Config


def init_libclang():
    """Initialize libclang library."""
    # Find libclang library
    import platform

    system = platform.system().lower()

    if system == "windows":
        lib_path = Path(__file__).parent.parent / "lib" / "windows" / "lib" / "libclang.dll"
    elif system == "darwin":
        lib_path = Path(__file__).parent.parent / "lib" / "macos" / "lib" / "libclang.dylib"
    else:  # Linux
        lib_path = Path(__file__).parent.parent / "lib" / "linux" / "lib" / "libclang.so.1"

    if lib_path.exists():
        Config.set_library_file(str(lib_path))

    return clang.cindex.Index.create()


def analyze_alias_cursor(cursor, indent=0):
    """Analyze a single alias cursor and extract all available information."""
    prefix = "  " * indent

    print(f"{prefix}{'='*70}")
    print(f"{prefix}Alias Found: {cursor.spelling}")
    print(f"{prefix}{'='*70}")
    print(f"{prefix}Cursor Kind: {cursor.kind}")
    print(f"{prefix}Location: {cursor.location.file.name}:{cursor.location.line}")

    # Get cursor type
    cursor_type = cursor.type
    print(f"\n{prefix}Cursor Type:")
    print(f"{prefix}  - Type Kind: {cursor_type.kind}")
    print(f"{prefix}  - Type Spelling: {cursor_type.spelling}")

    # Try to get canonical type
    canonical_type = cursor_type.get_canonical()
    print(f"\n{prefix}Canonical Type:")
    print(f"{prefix}  - Kind: {canonical_type.kind}")
    print(f"{prefix}  - Spelling: {canonical_type.spelling}")

    # Check if type is different from canonical
    is_alias = cursor_type.spelling != canonical_type.spelling
    print(f"\n{prefix}Is Alias? {is_alias}")

    # Try to get underlying type (for TypeAliasDecl)
    try:
        underlying_type = cursor.underlying_typedef_type
        print(f"\n{prefix}Underlying Typedef Type:")
        print(f"{prefix}  - Kind: {underlying_type.kind}")
        print(f"{prefix}  - Spelling: {underlying_type.spelling}")

        underlying_canonical = underlying_type.get_canonical()
        print(f"{prefix}  - Canonical: {underlying_canonical.spelling}")
    except AttributeError:
        print(f"\n{prefix}No underlying_typedef_type attribute")

    # Try to get type declaration
    try:
        type_decl = cursor_type.get_declaration()
        if type_decl and type_decl.kind != CursorKind.NO_DECL_FOUND:
            print(f"\n{prefix}Type Declaration:")
            print(f"{prefix}  - Kind: {type_decl.kind}")
            print(f"{prefix}  - Spelling: {type_decl.spelling}")
            print(
                f"{prefix}  - Location: {type_decl.location.file.name if type_decl.location.file else 'N/A'}:{type_decl.location.line}"
            )
    except Exception as e:
        print(f"\n{prefix}Error getting type declaration: {e}")

    # Check children
    children = list(cursor.get_children())
    if children:
        print(f"\n{prefix}Children ({len(children)}):")
        for i, child in enumerate(children):
            print(f"{prefix}  [{i}] {child.kind}: {child.spelling} (type: {child.type.spelling})")

    print(f"{prefix}{'-'*70}\n")

    return {
        "name": cursor.spelling,
        "kind": cursor.kind,
        "type_spelling": cursor_type.spelling,
        "canonical_spelling": canonical_type.spelling,
        "is_different": is_alias,
        "location": f"{cursor.location.file.name}:{cursor.location.line}",
    }


def find_aliases(cursor, results, target_file, depth=0):
    """Recursively find all alias declarations in the AST."""
    # Check if this is an alias declaration
    if cursor.kind in (CursorKind.TYPE_ALIAS_DECL, CursorKind.TYPEDEF_DECL):
        # Only process aliases from target file
        if cursor.location.file and cursor.location.file.name == target_file:
            info = analyze_alias_cursor(cursor, depth)
            results.append(info)

    # Recurse into children
    for child in cursor.get_children():
        find_aliases(child, results, target_file, depth + 1)


def main():
    """Main entry point."""
    print("=" * 80)
    print("libclang Alias Detection Investigation")
    print("Phase 1.1 - Type Alias Tracking Feature")
    print("=" * 80)
    print()

    # Get test file path
    script_dir = Path(__file__).parent
    test_file = script_dir.parent / "tests" / "fixtures" / "alias_test.cpp"

    if not test_file.exists():
        print(f"Error: Test file not found: {test_file}")
        return 1

    print(f"Analyzing file: {test_file}")
    print()

    # Initialize libclang
    index = init_libclang()

    # Parse the file
    # Use C++17 standard for modern syntax
    args = ["-std=c++17"]

    print("Parsing file with libclang...")
    tu = index.parse(str(test_file), args=args)

    if not tu:
        print("Error: Failed to parse translation unit")
        return 1

    # Check for parse errors
    diagnostics = list(tu.diagnostics)
    if diagnostics:
        print("\nDiagnostics:")
        for diag in diagnostics:
            print(f"  {diag.severity}: {diag.spelling}")
        print()

    # Find all aliases
    print("\nSearching for alias declarations...")
    print()

    results = []
    find_aliases(tu.cursor, results, str(test_file))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"\nTotal aliases found: {len(results)}")
    print()

    if results:
        print("Alias Name                    | Cursor Kind           | Type -> Canonical")
        print("-" * 80)
        for r in results:
            kind_short = str(r["kind"]).split(".")[-1]
            name = r["name"].ljust(28)
            kind_str = kind_short.ljust(20)
            types = f"{r['type_spelling']} -> {r['canonical_spelling']}"
            print(f"{name} | {kind_str} | {types}")

    print("\n" + "=" * 80)
    print("Key Findings:")
    print("=" * 80)

    # Analyze findings
    using_count = sum(1 for r in results if r["kind"] == CursorKind.TYPE_ALIAS_DECL)
    typedef_count = sum(1 for r in results if r["kind"] == CursorKind.TYPEDEF_DECL)

    print(f"- TYPE_ALIAS_DECL (using): {using_count}")
    print(f"- TYPEDEF_DECL (typedef): {typedef_count}")

    resolvable = sum(1 for r in results if r["is_different"])
    print(f"- Resolvable to different canonical type: {resolvable}/{len(results)}")

    print("\n" + "=" * 80)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
