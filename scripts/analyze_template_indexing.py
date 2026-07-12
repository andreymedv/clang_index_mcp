#!/usr/bin/env python3
"""
Analyze how templates are indexed in SQLite.

This script indexes the template test project and examines
how templates are stored in the SQLite cache.
"""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup libclang
from clang_index_mcp._mcp.cpp_mcp_server import find_and_configure_libclang  # noqa: E402

if not find_and_configure_libclang():
    print("Error: Could not find libclang library!")
    sys.exit(1)

from clang_index_mcp.cpp_analyzer import CppAnalyzer  # noqa: E402
from tests.utils.test_helpers import write_template_compile_commands  # noqa: E402


def _prepare_template_project(fixture_path: Path, dest: Path) -> Path:
    """Copy fixture sources into dest and write a host-local compile_commands.json."""
    for item in fixture_path.iterdir():
        if item.name == "compile_commands.json":
            continue
        if item.is_dir():
            shutil.copytree(item, dest / item.name)
        else:
            shutil.copy2(item, dest / item.name)
    write_template_compile_commands(dest)
    return dest


def analyze_template_indexing():
    """Analyze how templates are indexed."""
    fixture_path = project_root / "tests/fixtures/template_test_project"
    if not fixture_path.is_dir():
        print(f"Error: fixture not found: {fixture_path}")
        sys.exit(1)

    # Work in a temp copy so the fixture tree stays free of host-local paths
    with tempfile.TemporaryDirectory(prefix="template_test_project_") as tmp:
        test_project_path = _prepare_template_project(fixture_path, Path(tmp))

        print(f"Analyzing template indexing for: {fixture_path}")
        print(f"Working copy: {test_project_path}")
        print("=" * 80)

        # Create analyzer with test project as root
        analyzer = CppAnalyzer(project_root=str(test_project_path))

        # Index the test project
        print("\n1. Indexing project...")
        total_files = analyzer.index_project(force=True)
        print("   Indexing completed")
        print(f"   Total files: {total_files}")

        # Get cache database path
        cache_dir = analyzer.cache_manager.cache_dir
        db_path = cache_dir / "symbols.db"

        print(f"\n3. Cache database: {db_path}")

        if not db_path.exists():
            print("   ERROR: Database not found!")
            return

        # Connect to database and query
        print("\n4. Analyzing database contents...")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        cursor = conn.cursor()

        # Query classes and templates
        print("\n   === CLASSES AND TEMPLATES ===")
        cursor.execute("""
            SELECT name, qualified_name, kind, file, line, usr
            FROM symbols
            WHERE kind IN ('class', 'struct', 'class_template', 'partial_specialization')
              AND (name LIKE '%Container%' OR name LIKE '%Pair%' OR name LIKE '%Base%' OR name LIKE '%Tuple%')
            ORDER BY kind, name, line
        """)

        classes = cursor.fetchall()
        for row in classes:
            print(f"\n   Name: {row['name']}")
            print(f"   Qualified: {row['qualified_name']}")
            print(f"   Kind: {row['kind']}")
            print(f"   USR: {row['usr']}")
            print(f"   Location: {Path(row['file']).name}:{row['line']}")

        print(f"\n   Total classes found: {len(classes)}")

        # Query functions and templates
        print("\n\n   === FUNCTIONS AND TEMPLATES ===")
        cursor.execute("""
            SELECT name, qualified_name, signature, kind, file, line, usr
            FROM symbols
            WHERE kind IN ('function', 'method', 'function_template')
              AND name LIKE '%max%'
            ORDER BY kind, name, line
        """)

        functions = cursor.fetchall()
        for row in functions:
            print(f"\n   Name: {row['name']}")
            print(f"   Qualified: {row['qualified_name']}")
            print(f"   Kind: {row['kind']}")
            print(f"   Signature: {row['signature']}")
            print(f"   USR: {row['usr']}")
            print(f"   Location: {Path(row['file']).name}:{row['line']}")

        print(f"\n   Total functions found: {len(functions)}")

        # Search via analyzer
        print("\n\n5. Testing search functionality...")

        print("\n   Searching for 'Container':")
        results = analyzer.search_classes("Container")
        print(f"   Found {len(results)} results:")
        for r in results:
            print(f"     - {r.get('qualified_name', r.get('name'))} ({r.get('kind', 'unknown')})")

        print("\n   Searching for 'Container.*':")
        results = analyzer.search_classes("Container.*")
        print(f"   Found {len(results)} results:")
        for r in results:
            print(f"     - {r.get('qualified_name', r.get('name'))} ({r.get('kind', 'unknown')})")

        print("\n   Searching for 'Pair':")
        results = analyzer.search_classes("Pair")
        print(f"   Found {len(results)} results:")
        for r in results:
            print(f"     - {r.get('qualified_name', r.get('name'))} ({r.get('kind', 'unknown')})")

        print("\n   Searching for template function 'max':")
        results = analyzer.search_functions("max")
        print(f"   Found {len(results)} results:")
        for r in results:
            print(
                f"     - {r.get('qualified_name', r.get('name'))} - {r.get('signature', 'unknown')}"
            )

        # Test cross-specialization derived class queries (Phase 3)
        print("\n\n6. Testing cross-specialization derived class queries (Phase 3)...")

        print("\n   Querying derived classes of 'Container' (template):")
        derived = analyzer.get_derived_classes("Container")
        print(f"   Found {len(derived)} derived classes:")
        for d in derived:
            label = d.get("qualified_name") or d.get("name")
            print(f"     - {label} inherits from {d.get('base_classes', [])}")

        print("\n   Querying derived classes of 'Base' (CRTP template):")
        derived = analyzer.get_derived_classes("Base")
        print(f"   Found {len(derived)} derived classes:")
        for d in derived:
            label = d.get("qualified_name") or d.get("name")
            print(f"     - {label} inherits from {d.get('base_classes', [])}")

        conn.close()

        # Drop analyzer cache before temp dir is removed
        if hasattr(analyzer, "cache_manager"):
            analyzer.cache_manager.close()

        print("\n" + "=" * 80)
        print("Analysis complete!")


if __name__ == "__main__":
    analyze_template_indexing()
