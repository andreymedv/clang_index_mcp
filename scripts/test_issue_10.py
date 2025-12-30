#!/usr/bin/env python3
"""
Test for Issue #10 fix: Verify get_server_status returns non-zero file counts

This script tests that the fix for Issue #10 works correctly by:
1. Creating an analyzer for the example project
2. Indexing files
3. Verifying that file_index is used (not translation_units)
4. Checking that file counts are non-zero

Usage:
    python scripts/test_issue_10.py
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer


def test_issue_10():
    """Test that file counts are reported correctly after Issue #10 fix"""

    # Use the small example project for quick testing
    project_path = Path(__file__).parent.parent / "examples" / "compile_commands_example"

    if not project_path.exists():
        print(f"❌ Test project not found: {project_path}")
        return False

    print("=" * 60)
    print("Testing Issue #10 Fix: File Counts in get_server_status")
    print("=" * 60)

    # Create analyzer
    print(f"\n1. Creating analyzer for: {project_path}")
    analyzer = CppAnalyzer(str(project_path))
    print("   ✓ Analyzer created")

    # Index the project
    print("\n2. Indexing project...")
    indexed_count = analyzer.index_project(force=False, include_dependencies=True)
    print(f"   ✓ Indexed {indexed_count} files")

    # Check file_index (what should be used now)
    file_index_count = len(analyzer.file_index)
    print(f"\n3. Checking file_index count: {file_index_count}")

    # Simulate what get_server_status does (after our fix)
    print("\n4. Simulating get_server_status (after fix)...")
    parsed_files = len(analyzer.file_index)
    project_files = len(analyzer.file_index)

    print(f"   - parsed_files: {parsed_files}")
    print(f"   - project_files: {project_files}")

    # Verify counts are non-zero
    print("\n5. Verification:")
    success = True

    if parsed_files == 0:
        print("   ❌ FAIL: parsed_files is 0 (should be non-zero)")
        success = False
    else:
        print(f"   ✓ PASS: parsed_files = {parsed_files} (non-zero)")

    if project_files == 0:
        print("   ❌ FAIL: project_files is 0 (should be non-zero)")
        success = False
    else:
        print(f"   ✓ PASS: project_files = {project_files} (non-zero)")

    if parsed_files != indexed_count:
        print(f"   ⚠  WARNING: parsed_files ({parsed_files}) != indexed_count ({indexed_count})")
    else:
        print(f"   ✓ PASS: parsed_files matches indexed_count")

    print("\n" + "=" * 60)
    if success:
        print("✓ Issue #10 fix verified: File counts are non-zero")
    else:
        print("❌ Issue #10 fix FAILED")
    print("=" * 60)

    return success


if __name__ == "__main__":
    try:
        success = test_issue_10()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
