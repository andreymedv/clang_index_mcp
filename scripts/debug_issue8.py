#!/usr/bin/env python3
"""
Debug script for Issue #8: Check why ThreadPoolExecutor doesn't extract headers

This script adds detailed logging to understand the indexing flow.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server import diagnostics

# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

def debug_issue8():
    """Debug Issue #8 in ThreadPoolExecutor mode"""

    # Use Tier 1 test project
    project_path = Path(__file__).parent.parent / "examples" / "compile_commands_example"

    print(f"Debugging Issue #8 with project: {project_path}")
    print(f"Mode: {'ThreadPoolExecutor' if os.environ.get('CPP_ANALYZER_USE_THREADS') == 'true' else 'ProcessPoolExecutor'}")
    print("=" * 80)

    # Create analyzer
    analyzer = CppAnalyzer(str(project_path))

    # Check header_tracker state before indexing
    print(f"\n[Before indexing]")
    print(f"  header_tracker.get_processed_count(): {analyzer.header_tracker.get_processed_count()}")
    print(f"  file_index size: {len(analyzer.file_index)}")

    # Index the project
    print(f"\n[Indexing...]")
    analyzer.index_project()

    # Check header_tracker state after indexing
    print(f"\n[After indexing]")
    print(f"  header_tracker.get_processed_count(): {analyzer.header_tracker.get_processed_count()}")
    processed_headers = analyzer.header_tracker.get_processed_headers()
    if processed_headers:
        print(f"  Processed headers:")
        for h, hash_val in processed_headers.items():
            print(f"    - {h[:80]}: {hash_val[:8]}...")
    else:
        print(f"  ⚠️ No headers in header_tracker!")

    print(f"  file_index size: {len(analyzer.file_index)}")
    print(f"  Files in file_index:")
    for f in analyzer.file_index.keys():
        symbol_count = len(analyzer.file_index[f])
        file_type = "HEADER" if f.endswith(('.h', '.hpp', '.hxx')) else "SOURCE"
        print(f"    - [{file_type}] {f[:80]}: {symbol_count} symbols")

    # Check if headers are in file_index
    headers = [f for f in analyzer.file_index.keys() if f.endswith(('.h', '.hpp', '.hxx'))]
    sources = [f for f in analyzer.file_index.keys() if f.endswith(('.cpp', '.cc', '.cxx'))]

    print(f"\n[Summary]")
    print(f"  Source files in file_index: {len(sources)}")
    print(f"  Header files in file_index: {len(headers)}")
    print(f"  Headers in header_tracker: {analyzer.header_tracker.get_processed_count()}")

    if analyzer.header_tracker.get_processed_count() > 0 and len(headers) == 0:
        print(f"\n🔴 BUG CONFIRMED: Headers claimed in header_tracker but NOT in file_index!")
        print(f"  This means headers were claimed but symbols weren't extracted or added to file_index")
        return False
    elif analyzer.header_tracker.get_processed_count() == 0 and len(headers) == 0:
        print(f"\n🔴 BUG: Headers not even claimed by header_tracker!")
        print(f"  This means should_extract_from_file() never returned True for headers")
        return False
    elif len(headers) > 0:
        print(f"\n✅ PASS: Headers successfully indexed")
        return True
    else:
        print(f"\n❓ UNEXPECTED STATE")
        return False

if __name__ == "__main__":
    try:
        success = debug_issue8()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n🔴 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
