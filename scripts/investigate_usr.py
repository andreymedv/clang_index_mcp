#!/usr/bin/env python3
"""
Investigation script: Do forward declarations and definitions have the same USR?

This answers investigation question #1 from beads issue cplusplus_mcp-7ps.
"""

import sys
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer  # noqa: E402
from mcp_server.diagnostics import DiagnosticLevel, get_logger  # noqa: E402


def test_usr_matching_same_file():
    """Test USR values when forward decl and definition are in the same file."""
    print("\n=== TEST 1: Forward decl + definition in SAME file ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create file with forward decl followed by definition
        test_h = tmp_path / "test.h"
        test_h.write_text("""
// Forward declaration
class MyClass;

// Definition
class MyClass {
    int value;
public:
    void method();
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))

        # Enable debug to see definition-wins messages
        get_logger().set_level(DiagnosticLevel.DEBUG)

        print(f"Indexing: {test_h}")
        analyzer.index_file(str(test_h))

        # Check what's in class_index
        print(f"\nclass_index['MyClass'] entries: {len(analyzer.class_index.get('MyClass', []))}")
        for i, sym in enumerate(analyzer.class_index.get("MyClass", [])):
            print(f"  [{i}] file={sym.file}:{sym.line}")
            print(f"      USR={sym.usr}")
            print(f"      is_definition={sym.is_definition}")
            print(f"      start_line={sym.start_line}, end_line={sym.end_line}")

        # Check usr_index
        print(
            f"\nusr_index entries with 'MyClass': {sum(1 for k in analyzer.usr_index if 'MyClass' in k)}"
        )
        for usr, sym in analyzer.usr_index.items():
            if "MyClass" in usr:
                print(f"  USR={usr}")
                print(f"  -> {sym.file}:{sym.line}, is_definition={sym.is_definition}")


def test_usr_matching_different_files():
    """Test USR values when forward decl and definition are in different files."""
    print("\n=== TEST 2: Forward decl + definition in DIFFERENT files ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Forward declaration in header
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
// Forward declaration only
class MyClass;
""")

        # Definition in another header
        myclass_h = tmp_path / "myclass.h"
        myclass_h.write_text("""
// Full definition
class MyClass {
    int value;
public:
    void method();
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        # Index forward declaration first
        print(f"Indexing forward decl: {fwd_h}")
        analyzer.index_file(str(fwd_h))

        print("\nAfter indexing forward declaration:")
        print(f"class_index['MyClass'] entries: {len(analyzer.class_index.get('MyClass', []))}")
        for i, sym in enumerate(analyzer.class_index.get("MyClass", [])):
            print(f"  [{i}] USR={sym.usr}")
            print(f"      is_definition={sym.is_definition}, file={sym.file}:{sym.line}")

        # Now index definition
        print(f"\nIndexing definition: {myclass_h}")
        analyzer.index_file(str(myclass_h))

        print("\nAfter indexing definition:")
        print(f"class_index['MyClass'] entries: {len(analyzer.class_index.get('MyClass', []))}")
        for i, sym in enumerate(analyzer.class_index.get("MyClass", [])):
            print(f"  [{i}] USR={sym.usr}")
            print(f"      is_definition={sym.is_definition}, file={sym.file}:{sym.line}")


def test_usr_matching_with_namespace():
    """Test USR values when class is in a namespace."""
    print("\n=== TEST 3: Forward decl + definition with NAMESPACE ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Forward declaration in namespace
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
namespace ns {
    class MyClass;
}
""")

        # Definition in namespace
        myclass_h = tmp_path / "myclass.h"
        myclass_h.write_text("""
namespace ns {
    class MyClass {
        int value;
    public:
        void method();
    };
}
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        print(f"Indexing forward decl: {fwd_h}")
        analyzer.index_file(str(fwd_h))

        fwd_symbols = analyzer.class_index.get("MyClass", [])
        print(f"\nAfter forward decl - entries: {len(fwd_symbols)}")
        for sym in fwd_symbols:
            print(f"  USR={sym.usr}")
            print(f"  qualified_name={sym.qualified_name}")

        print(f"\nIndexing definition: {myclass_h}")
        analyzer.index_file(str(myclass_h))

        def_symbols = analyzer.class_index.get("MyClass", [])
        print(f"\nAfter definition - entries: {len(def_symbols)}")
        for sym in def_symbols:
            print(f"  USR={sym.usr}")
            print(f"  qualified_name={sym.qualified_name}")
            print(f"  is_definition={sym.is_definition}")


def test_parallel_indexing_simulation():
    """Simulate what happens when files are processed in parallel (main issue scenario)."""
    print("\n=== TEST 4: Simulate PARALLEL indexing (merge symbols) ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Forward declaration
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
class Widget;
""")

        # Definition
        widget_h = tmp_path / "widget.h"
        widget_h.write_text("""
class Widget {
    int x;
};
""")

        # Source that includes both (forces both to be parsed)
        main_cpp = tmp_path / "main.cpp"
        main_cpp.write_text("""
#include "fwd.h"
#include "widget.h"

int main() {
    Widget w;
    return 0;
}
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        # This simulates what happens in real project indexing
        print("Indexing main.cpp (which includes both headers)...")
        analyzer.index_file(str(main_cpp))

        print(f"\nclass_index['Widget'] entries: {len(analyzer.class_index.get('Widget', []))}")
        for i, sym in enumerate(analyzer.class_index.get("Widget", [])):
            print(f"  [{i}] USR={sym.usr}")
            print(f"      file={sym.file}:{sym.line}")
            print(f"      is_definition={sym.is_definition}")


def test_source_includes_both_headers():
    """Test what happens when a source includes BOTH forward decl header AND definition header.

    This simulates a common real-world pattern where:
    - widget.h uses forward declaration: class QString;
    - main.cpp includes both widget.h (fwd decl) AND qstring.h (definition)
    """
    print("\n=== TEST 5: Source includes BOTH fwd decl header AND definition header ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Forward declaration in widget.h
        widget_h = tmp_path / "widget.h"
        widget_h.write_text("""
// widget.h - uses forward declaration
class QString;

class Widget {
    QString* text;
};
""")

        # Full definition in qstring.h
        qstring_h = tmp_path / "qstring.h"
        qstring_h.write_text("""
// qstring.h - full definition
class QString {
    char* data;
    int length;
public:
    QString();
    ~QString();
};
""")

        # main.cpp includes BOTH headers
        main_cpp = tmp_path / "main.cpp"
        main_cpp.write_text("""
#include "widget.h"
#include "qstring.h"

int main() {
    Widget w;
    QString s;
    return 0;
}
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        # Index the source file (which will parse both included headers)
        print("Indexing main.cpp (includes both widget.h and qstring.h)...")
        analyzer.index_file(str(main_cpp))

        print(f"\nclass_index['QString'] entries: {len(analyzer.class_index.get('QString', []))}")
        for i, sym in enumerate(analyzer.class_index.get("QString", [])):
            print(f"  [{i}] USR={sym.usr}")
            print(f"      file={sym.file}:{sym.line}")
            print(f"      is_definition={sym.is_definition}")
            print(f"      start_line={sym.start_line}, end_line={sym.end_line}")

        # Check if both are present (the bug!)
        symbols = analyzer.class_index.get("QString", [])
        if len(symbols) > 1:
            print("\n*** BUG DETECTED: Multiple entries for same class! ***")
            for i, sym in enumerate(symbols):
                print(f"  Entry {i}: is_definition={sym.is_definition}, USR={sym.usr}")
        elif len(symbols) == 1:
            sym = symbols[0]
            if not sym.is_definition:
                print("\n*** BUG: Only forward declaration kept, definition missing! ***")
            else:
                print("\n✓ Correct: Definition won over forward declaration")


def test_check_usr_for_forward_decl():
    """Test if forward declarations have non-empty USRs."""
    print("\n=== TEST 6: Verify forward declarations have valid USRs ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Various forward declaration scenarios
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
// Bare forward declaration
class FwdClass1;

// Forward decl in namespace
namespace ns {
    class FwdClass2;
}

// Multiple forward decls of same class
class FwdClass3;

// Forward decl followed by definition
class FwdClass4;
class FwdClass4 {
    int x;
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        print(f"Indexing {fwd_h}...")
        analyzer.index_file(str(fwd_h))

        print("\nChecking USRs for all indexed classes:")
        for name in sorted(analyzer.class_index.keys()):
            symbols = analyzer.class_index[name]
            print(f"\n  {name}: {len(symbols)} symbol(s)")
            for i, sym in enumerate(symbols):
                has_usr = bool(sym.usr)
                print(
                    f"    [{i}] USR={'YES' if has_usr else '**EMPTY**'}: {sym.usr[:50] if sym.usr else 'N/A'}..."
                )
                print(f"        is_definition={sym.is_definition}, line={sym.line}")

        # Check usr_index for duplicates
        print("\n\nUSR index entries:")
        for usr in sorted(analyzer.usr_index.keys()):
            if any(name in usr for name in ["FwdClass1", "FwdClass2", "FwdClass3", "FwdClass4"]):
                sym = analyzer.usr_index[usr]
                print(f"  {usr}: {sym.name} is_definition={sym.is_definition}")


def test_sqlite_storage():
    """Test what ends up in SQLite after indexing forward decl + definition."""
    print("\n=== TEST 7: Check SQLite storage after indexing ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Forward declaration
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
class TestClass;
""")

        # Definition
        test_h = tmp_path / "test.h"
        test_h.write_text("""
class TestClass {
    int x;
};
""")

        # Source that includes both
        main_cpp = tmp_path / "main.cpp"
        main_cpp.write_text("""
#include "fwd.h"
#include "test.h"

int main() {
    TestClass t;
    return 0;
}
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        print("Indexing main.cpp...")
        analyzer.index_file(str(main_cpp))

        # Now check what's in SQLite
        print("\nQuerying SQLite directly...")
        cache_backend = analyzer.cache_manager.backend

        # Query for all TestClass entries
        cursor = cache_backend.conn.execute(
            "SELECT usr, name, kind, file, line, is_definition FROM symbols WHERE name = 'TestClass'"
        )
        rows = cursor.fetchall()

        print(f"\nSQLite entries for 'TestClass': {len(rows)}")
        for row in rows:
            usr, name, kind, file, line, is_def = row
            print(f"  USR={usr}")
            print(f"  file={file}:{line}, is_definition={is_def}")

        if len(rows) > 1:
            print("\n*** POTENTIAL BUG: Multiple SQLite entries with same name! ***")
            print("    Check if USRs are different or if one is empty.")


def test_empty_usr_handling():
    """Test what happens when a symbol has an empty USR."""
    print("\n=== TEST 8: Check empty USR handling ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create files with unusual constructs that might produce empty USRs
        test_h = tmp_path / "test.h"
        test_h.write_text("""
// Anonymous struct (might have unusual USR behavior)
struct {
    int x;
} anonymous_instance;

// Forward decl of anonymous struct (invalid but let's see what happens)
// struct;  // This would be a syntax error

// Normal class for comparison
class NormalClass {
    int y;
};
""")

        analyzer = CppAnalyzer(project_root=str(tmp_path))
        get_logger().set_level(DiagnosticLevel.DEBUG)

        print(f"Indexing {test_h}...")
        analyzer.index_file(str(test_h))

        print("\nChecking for symbols with empty USRs:")
        for name, symbols in analyzer.class_index.items():
            for sym in symbols:
                if not sym.usr:
                    print(f"  *** EMPTY USR: {name} in {sym.file}:{sym.line}")
                else:
                    print(f"  OK: {name} has USR: {sym.usr[:40]}...")


if __name__ == "__main__":
    test_usr_matching_same_file()
    test_usr_matching_different_files()
    test_usr_matching_with_namespace()
    test_parallel_indexing_simulation()
    test_source_includes_both_headers()
    test_check_usr_for_forward_decl()
    test_sqlite_storage()
    test_empty_usr_handling()
    print("\n=== INVESTIGATION COMPLETE ===\n")
