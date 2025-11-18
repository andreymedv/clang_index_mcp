#!/usr/bin/env python3
"""
Diagnostic script for compile_commands.json issues.

This script helps diagnose why files are failing to parse when using compile_commands.json.
It shows:
1. Sample compile commands from the file
2. How arguments are being extracted
3. Detailed error messages from attempting to parse a sample file

Usage:
    python scripts/diagnose_compile_commands.py <project_root> [--file <specific_file>]
"""

import sys
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.compile_commands_manager import CompileCommandsManager
from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
import mcp_server.diagnostics as diagnostics


def show_compile_command_sample(project_root: Path, sample_count: int = 3):
    """Show sample entries from compile_commands.json"""
    config = CppAnalyzerConfig(project_root)
    cc_config = config.get_compile_commands_config()
    cc_path = project_root / cc_config.get('compile_commands_path', 'compile_commands.json')

    if not cc_path.exists():
        print(f"[ERROR] compile_commands.json not found at: {cc_path}")
        return None

    print(f"\n{'='*70}")
    print(f"COMPILE_COMMANDS.JSON LOCATION")
    print(f"{'='*70}")
    print(f"Path: {cc_path}")

    try:
        with open(cc_path, 'r') as f:
            commands = json.load(f)

        print(f"Total entries: {len(commands)}")
        print(f"\n{'='*70}")
        print(f"SAMPLE COMPILE COMMANDS (showing {min(sample_count, len(commands))})")
        print(f"{'='*70}")

        for i, cmd in enumerate(commands[:sample_count]):
            print(f"\n[{i+1}] File: {cmd.get('file', 'N/A')}")
            print(f"    Directory: {cmd.get('directory', 'N/A')}")

            if 'arguments' in cmd:
                print(f"    Arguments format: LIST")
                print(f"    Arguments ({len(cmd['arguments'])} items):")
                for arg in cmd['arguments'][:10]:  # Show first 10
                    print(f"      - {arg}")
                if len(cmd['arguments']) > 10:
                    print(f"      ... and {len(cmd['arguments']) - 10} more")
            elif 'command' in cmd:
                print(f"    Arguments format: STRING")
                print(f"    Command: {cmd['command'][:200]}{'...' if len(cmd['command']) > 200 else ''}")
            else:
                print(f"    [ERROR] No 'arguments' or 'command' field!")

        return commands
    except Exception as e:
        print(f"[ERROR] Error reading compile_commands.json: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_argument_extraction(project_root: Path, compile_commands: list):
    """Test how arguments are being extracted"""
    print(f"\n{'='*70}")
    print(f"ARGUMENT EXTRACTION TEST")
    print(f"{'='*70}")

    config = CppAnalyzerConfig(project_root)
    cc_config = config.get_compile_commands_config()
    cc_manager = CompileCommandsManager(project_root, cc_config)

    # Test first file
    if compile_commands:
        first_file = compile_commands[0].get('file')
        if first_file:
            file_path = Path(first_file)
            args = cc_manager.get_compile_args(file_path)

            print(f"\nTest file: {first_file}")
            if args:
                print(f"Extracted {len(args)} arguments:")
                for i, arg in enumerate(args[:20]):  # Show first 20
                    print(f"  [{i}] {arg}")
                if len(args) > 20:
                    print(f"  ... and {len(args) - 20} more")
            else:
                print("[ERROR] No arguments extracted!")
                print("\nThis suggests the file path normalization might be failing.")
                print(f"File path from compile_commands.json: {first_file}")
                print(f"Resolved path: {file_path.resolve()}")


def test_single_file_parse(project_root: Path, file_to_test: str = None):
    """Test parsing a single file with detailed error output"""
    print(f"\n{'='*70}")
    print(f"SINGLE FILE PARSE TEST")
    print(f"{'='*70}")

    # Create analyzer
    analyzer = CppAnalyzer(str(project_root))

    # Get files from compile commands
    files = analyzer.compile_commands_manager.get_all_files()

    if not files:
        print("[ERROR] No files found in compile_commands.json")
        return

    # Select file to test
    if file_to_test:
        test_file = file_to_test
        if test_file not in files:
            print(f"[WARNING]  File {test_file} not found in compile_commands.json")
            print(f"Using first file instead...")
            test_file = files[0]
    else:
        test_file = files[0]

    print(f"\nTesting file: {test_file}")

    # Get compile args
    file_path = Path(test_file)
    args = analyzer.compile_commands_manager.get_compile_args_with_fallback(file_path)

    print(f"\nCompilation arguments ({len(args)} total):")
    for i, arg in enumerate(args[:30]):
        print(f"  [{i}] {arg}")
    if len(args) > 30:
        print(f"  ... and {len(args) - 30} more")

    # Try to parse
    print(f"\nAttempting to parse...")
    success, was_cached = analyzer.index_file(test_file, force=True)

    if success:
        print("[PASS] File parsed successfully!")
        # Show symbols found
        if test_file in analyzer.file_index:
            symbols = analyzer.file_index[test_file]
            print(f"Found {len(symbols)} symbols:")
            for sym in symbols[:10]:
                print(f"  - {sym.kind}: {sym.name}")
    else:
        print("[ERROR] File failed to parse!")
        print("\nTo see detailed error messages, run:")
        print(f"  python scripts/view_parse_errors.py {project_root} -l 5 -v")


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose compile_commands.json parsing issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "project_root",
        help="Path to the C++ project root directory"
    )

    parser.add_argument(
        "--file", "-f",
        type=str,
        help="Specific file to test parsing (optional)"
    )

    parser.add_argument(
        "--samples", "-s",
        type=int,
        default=3,
        help="Number of sample compile commands to show (default: 3)"
    )

    args = parser.parse_args()

    # Validate project root
    project_path = Path(args.project_root).resolve()
    if not project_path.exists():
        print(f"[ERROR] Project root does not exist: {args.project_root}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"COMPILE_COMMANDS.JSON DIAGNOSTIC")
    print(f"{'='*70}")
    print(f"Project: {project_path}")

    # 1. Show sample compile commands
    commands = show_compile_command_sample(project_path, args.samples)

    if not commands:
        sys.exit(1)

    # 2. Test argument extraction
    test_argument_extraction(project_path, commands)

    # 3. Test parsing a single file
    test_single_file_parse(project_path, args.file)

    print(f"\n{'='*70}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
