#!/usr/bin/env python3
"""
Analyze how templates are indexed in SQLite.

This script indexes the template test project and examines
how templates are stored in the SQLite cache.
"""

import sys
import os
import sqlite3
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup libclang
from mcp_server import diagnostics
from mcp_server.cpp_mcp_server import find_and_configure_libclang

if not find_and_configure_libclang():
    print("Error: Could not find libclang library!")
    sys.exit(1)

from mcp_server.cpp_analyzer import CppAnalyzer


def analyze_template_indexing():
    """Analyze how templates are indexed."""
    test_project_path = project_root / "tests/fixtures/template_test_project"

    print(f"Analyzing template indexing for: {test_project_path}")
    print("=" * 80)

    # Create analyzer with test project as root
    analyzer = CppAnalyzer(project_root=str(test_project_path))

    # Index the test project
    print("\n1. Indexing project...")
    result = analyzer.index_project(force=True)
    print(f"   Indexing completed")
    print(f"   Total files: {result.get('total_files', 0) if isinstance(result, dict) else 'unknown'}")

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

    # Debug: Check class_index contents
    print("\n\n4.5. DEBUG: Checking class_index contents...")
    print(f"   class_index keys: {list(analyzer.class_index.keys())}")
    if 'Container' in analyzer.class_index:
        print(f"   Container entries in class_index: {len(analyzer.class_index['Container'])}")
        for info in analyzer.class_index['Container']:
            print(f"     - {info.name} (kind={info.kind}, USR={info.usr})")
    else:
        print("   'Container' not found in class_index!")

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
        print(f"     - {r.get('qualified_name', r.get('name'))} - {r.get('signature', 'unknown')}")

    # Test cross-specialization derived class queries (Phase 3)
    print("\n\n6. Testing cross-specialization derived class queries (Phase 3)...")

    print("\n   Querying derived classes of 'Container' (template):")
    derived = analyzer.get_derived_classes("Container")
    print(f"   Found {len(derived)} derived classes:")
    for d in derived:
        print(f"     - {d['name']} inherits from {d.get('base_classes', [])}")

    print("\n   Querying derived classes of 'Base' (CRTP template):")
    derived = analyzer.get_derived_classes("Base")
    print(f"   Found {len(derived)} derived classes:")
    for d in derived:
        print(f"     - {d['name']} inherits from {d.get('base_classes', [])}")

    # Test _find_template_specializations directly
    print("\n\n7. Testing _find_template_specializations() method...")

    print("\n   Finding all specializations of 'Container':")
    specs = analyzer._find_template_specializations("Container")
    print(f"   Found {len(specs)} specializations:")
    for spec in specs:
        print(f"     - {spec.name} (kind={spec.kind}, USR={spec.usr})")

    print("\n   Finding all specializations of 'Pair':")
    specs = analyzer._find_template_specializations("Pair")
    print(f"   Found {len(specs)} specializations:")
    for spec in specs:
        print(f"     - {spec.name} (kind={spec.kind}, USR={spec.usr})")

    conn.close()

    print("\n" + "=" * 80)
    print("Analysis complete!")


if __name__ == "__main__":
    analyze_template_indexing()
