#!/usr/bin/env python3
"""
Test script for Issue #8: Missing headers after refresh

This script tests whether headers and their symbols are properly indexed
and preserved after refresh operations.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer


def test_issue8():
    """Test Issue #8: Headers should be indexed and preserved"""

    # Use Tier 1 test project
    project_path = Path(__file__).parent.parent / "examples" / "compile_commands_example"

    print(f"Testing Issue #8 with project: {project_path}")
    print("=" * 80)

    # Create analyzer
    analyzer = CppAnalyzer(str(project_path))

    # Index the project
    print("\n[Step 1] Initial indexing...")
    analyzer.index_project()

    print(f"Indexing complete.")
    print(f"Total files in file_index: {len(analyzer.file_index)}")
    print(f"Total classes: {sum(len(v) for v in analyzer.class_index.values())}")
    print(f"Total functions: {sum(len(v) for v in analyzer.function_index.values())}")

    # Count headers vs sources
    headers = [f for f in analyzer.file_index.keys() if f.endswith((".h", ".hpp", ".hxx"))]
    sources = [f for f in analyzer.file_index.keys() if f.endswith((".cpp", ".cc", ".cxx"))]

    print(f"  - Source files: {len(sources)}")
    print(f"  - Header files: {len(headers)}")

    if headers:
        print(f"\nHeaders found:")
        for h in headers[:5]:  # Show first 5
            symbol_count = len(analyzer.file_index[h])
            print(f"  - {h}: {symbol_count} symbols")
    else:
        print("\n⚠️  WARNING: No headers found in file_index!")

    # Check functions (should find some from headers if they exist)
    print("\n[Step 2] Checking function index...")
    all_functions = [f for funcs in analyzer.function_index.values() for f in funcs]
    print(f"Found {len(all_functions)} functions total")
    if all_functions:
        # Check if any are from headers
        header_funcs = [f for f in all_functions if f.file.endswith((".h", ".hpp", ".hxx"))]
        print(f"  - {len(header_funcs)} from headers")
        print(f"  - {len(all_functions) - len(header_funcs)} from sources")

    # Perform incremental refresh
    print("\n[Step 3] Performing incremental refresh...")
    refreshed_count = analyzer.refresh_if_needed()
    print(f"Refreshed {refreshed_count} files")

    print(f"Refresh complete.")
    print(f"Total files in file_index: {len(analyzer.file_index)}")
    print(f"Total classes: {sum(len(v) for v in analyzer.class_index.values())}")
    print(f"Total functions: {sum(len(v) for v in analyzer.function_index.values())}")

    # Count headers vs sources after refresh
    headers_after = [f for f in analyzer.file_index.keys() if f.endswith((".h", ".hpp", ".hxx"))]
    sources_after = [f for f in analyzer.file_index.keys() if f.endswith((".cpp", ".cc", ".cxx"))]

    print(f"  - Source files: {len(sources_after)}")
    print(f"  - Header files: {len(headers_after)}")

    if headers_after:
        print(f"\nHeaders found after refresh:")
        for h in headers_after[:5]:  # Show first 5
            symbol_count = len(analyzer.file_index[h])
            print(f"  - {h}: {symbol_count} symbols")
    else:
        print("\n🔴 FAIL: No headers found after refresh!")

    # Check functions after refresh
    print("\n[Step 4] Checking function index after refresh...")
    all_functions_after = [f for funcs in analyzer.function_index.values() for f in funcs]
    print(f"Found {len(all_functions_after)} functions total")
    if all_functions_after:
        header_funcs_after = [
            f for f in all_functions_after if f.file.endswith((".h", ".hpp", ".hxx"))
        ]
        print(f"  - {len(header_funcs_after)} from headers")
        print(f"  - {len(all_functions_after) - len(header_funcs_after)} from sources")

    # Verdict
    print("\n" + "=" * 80)
    print("VERDICT:")
    if len(headers) == 0:
        print("🔴 FAIL: No headers indexed initially (Issue #8 - headers not extracted)")
        return False
    elif len(headers_after) < len(headers):
        print(f"🔴 FAIL: Headers lost after refresh ({len(headers)} → {len(headers_after)})")
        return False
    elif len(all_functions_after) < len(all_functions):
        print(
            f"🔴 FAIL: Functions lost after refresh ({len(all_functions)} → {len(all_functions_after)})"
        )
        return False
    else:
        print("✅ PASS: Headers and symbols preserved after refresh")
        return True


if __name__ == "__main__":
    try:
        success = test_issue8()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n🔴 ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
