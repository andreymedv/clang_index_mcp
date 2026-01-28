#!/usr/bin/env python3
"""Debug script to see full compile arguments"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.compile_commands_manager import CompileCommandsManager
from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
import json

project_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

config = CppAnalyzerConfig(project_root)
cc_config = config.get_compile_commands_config()
cc_manager = CompileCommandsManager(project_root, cc_config)

# Get first file
files = cc_manager.get_all_files()
if files:
    test_file = Path(files[0])
    args = cc_manager.get_compile_args(test_file)

    print(f"File: {test_file}")
    print(f"\nAll {len(args)} arguments:")
    for i, arg in enumerate(args):
        print(f"  [{i}] {arg}")
