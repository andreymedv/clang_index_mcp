#!/usr/bin/env python3
"""
Very detailed debug script for Issue #8

Patches the analyzer to add debug output for symbol collection.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer
import threading

# Patch _bulk_write_symbols to add debug output
original_bulk_write = CppAnalyzer._bulk_write_symbols

def patched_bulk_write(self):
    """Patched version with debug output"""
    symbols_buffer, calls_buffer = self._get_thread_local_buffers()
    thread_id = threading.current_thread().name

    print(f"  [Thread {thread_id}] _bulk_write_symbols called:")
    print(f"    symbols_buffer size: {len(symbols_buffer)}")
    print(f"    calls_buffer size: {len(calls_buffer)}")

    if symbols_buffer:
        print(f"    Symbols to write:")
        for sym in symbols_buffer:
            file_short = sym.file[-50:] if sym.file else "None"
            print(f"      - {sym.name} in {file_short}")

    result = original_bulk_write(self)

    print(f"    Result: added {result} symbols to shared indexes")
    print(f"    file_index now has {len(self.file_index)} files")

    return result

CppAnalyzer._bulk_write_symbols = patched_bulk_write

# Also patch _index_translation_unit
original_index_tu = CppAnalyzer._index_translation_unit

def patched_index_tu(self, tu, source_file):
    """Patched version with debug output"""
    thread_id = threading.current_thread().name
    print(f"\n  [Thread {thread_id}] _index_translation_unit({source_file[-50:]})")

    result = original_index_tu(self, tu, source_file)

    print(f"  [Thread {thread_id}] _index_translation_unit result:")
    print(f"    processed: {[f[-50:] for f in result['processed']]}")
    print(f"    skipped: {[f[-50:] for f in result['skipped'][:3]]}...")

    return result

CppAnalyzer._index_translation_unit = patched_index_tu

def debug_issue8():
    """Debug Issue #8 with detailed output"""

    project_path = Path(__file__).parent.parent / "examples" / "compile_commands_example"

    print(f"Detailed debug for Issue #8")
    print(f"Mode: {'ThreadPoolExecutor' if os.environ.get('CPP_ANALYZER_USE_THREADS') == 'true' else 'ProcessPoolExecutor'}")
    print("=" * 80)

    analyzer = CppAnalyzer(str(project_path))

    print(f"\n[Indexing...]")
    analyzer.index_project()

    print(f"\n[After indexing]")
    print(f"  file_index size: {len(analyzer.file_index)}")
    for f in sorted(analyzer.file_index.keys()):
        symbol_count = len(analyzer.file_index[f])
        file_type = "HEADER" if f.endswith(('.h', '.hpp', '.hxx')) else "SOURCE"
        print(f"    [{file_type}] {f[-60:]}: {symbol_count} symbols")

    headers = [f for f in analyzer.file_index.keys() if f.endswith(('.h', '.hpp', '.hxx'))]
    if len(headers) == 0:
        print(f"\n🔴 FAIL: No headers in file_index")
        return False
    else:
        print(f"\n✅ PASS: {len(headers)} headers in file_index")
        return True

if __name__ == "__main__":
    try:
        success = debug_issue8()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n🔴 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
