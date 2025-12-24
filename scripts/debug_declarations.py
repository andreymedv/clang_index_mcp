#!/usr/bin/env python3
"""Debug why declarations aren't in file_index"""

import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer

# Patch _bulk_write_symbols to see what's happening
original_bulk_write = CppAnalyzer._bulk_write_symbols

def patched_bulk_write(self):
    symbols_buffer, calls_buffer = self._get_thread_local_buffers()

    print(f"\n_bulk_write_symbols called with {len(symbols_buffer)} symbols:")
    for s in symbols_buffer:
        print(f"  - {s.name} in {s.file} (is_def={s.is_definition}, usr={s.usr[:20] if s.usr else 'None'})")

    result = original_bulk_write(self)

    print(f"After _bulk_write_symbols:")
    print(f"  file_index keys: {[k[-40:] for k in self.file_index.keys()]}")
    for file, syms in self.file_index.items():
        print(f"  {file[-40:]}: {[s.name for s in syms]}")

    return result

CppAnalyzer._bulk_write_symbols = patched_bulk_write

# Create test project
with tempfile.TemporaryDirectory() as tmpdir:
    project = Path(tmpdir) / 'project'
    project.mkdir()
    src = project / 'src'
    src.mkdir()

    # Create header with declarations
    (src / 'functions.h').write_text('''
int add(int a, int b);
int subtract(int a, int b);
''')

    # Create source with definitions
    (src / 'functions.cpp').write_text('''
#include "functions.h"

int add(int a, int b) { return a + b; }
int subtract(int a, int b) { return a - b; }
''')

    # Index
    analyzer = CppAnalyzer(str(project))
    analyzer.index_project()

    print("\n\n=== FINAL STATE ===")
    print(f"file_index keys: {list(analyzer.file_index.keys())}")
    for file, symbols in analyzer.file_index.items():
        print(f"\n{file}:")
        for s in symbols:
            print(f"  - {s.name} (is_def={s.is_definition})")
