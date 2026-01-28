#!/usr/bin/env python3
"""Debug cursor location vs extent"""

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from clang.cindex import Index, CursorKind

# Create test files
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir)

    header = project / "test.h"
    header.write_text("int add(int a, int b);")

    source = project / "test.cpp"
    source.write_text("""
#include "test.h"
int add(int a, int b) { return a + b; }
""")

    # Parse with libclang
    index = Index.create()
    tu = index.parse(str(source), args=["-I", str(project)])

    def visit(cursor, depth=0):
        if cursor.kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
            indent = "  " * depth
            loc_file = str(cursor.location.file.name) if cursor.location.file else "None"
            ext_file = (
                str(cursor.extent.start.file.name)
                if cursor.extent and cursor.extent.start.file
                else "None"
            )

            print(f"{indent}Function: {cursor.spelling}")
            print(f"{indent}  location.file: {loc_file[-30:]}")
            print(f"{indent}  extent.start.file: {ext_file[-30:]}")
            print(f"{indent}  is_definition: {cursor.is_definition()}")
            print(f"{indent}  location.line: {cursor.location.line}")
            print()

        for child in cursor.get_children():
            visit(child, depth + 1)

    print("Visiting AST of test.cpp:")
    visit(tu.cursor)
