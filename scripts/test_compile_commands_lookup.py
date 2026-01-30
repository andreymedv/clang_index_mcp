#!/usr/bin/env python3
"""
Test compile_commands.json lookup for specific files without parsing all files.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer  # noqa: E402


def test_compile_commands_lookup(project_path: str, test_file: str):
    """Test if a specific file gets its args from compile_commands.json"""

    print("=" * 80)
    print("Compile Commands Lookup Test")
    print("=" * 80)
    print()

    project_path = Path(project_path).absolute()
    test_file = Path(test_file).absolute()

    print(f"Project: {project_path}")
    print(f"Test file: {test_file}")
    print()

    # Initialize analyzer (loads compile_commands.json)
    print("1. Initializing analyzer...")
    analyzer = CppAnalyzer(str(project_path))

    ccm = analyzer.compile_commands_manager
    print(f"   Compile commands enabled: {ccm.enabled}")
    print(f"   Compile commands loaded: {len(ccm.compile_commands)} entries")
    print(f"   Compile commands path: {ccm.compile_commands_path}")
    print()

    # Check if file is supported
    print("2. Checking if file is in compile_commands.json...")
    is_supported = ccm.is_file_supported(test_file)
    print(f"   File is supported: {is_supported}")
    print()

    if is_supported:
        # Get actual compile args
        print("3. Getting compile args from compile_commands.json...")
        args = ccm.get_compile_args(test_file)
        if args:
            print(f"   ✓ Got {len(args)} arguments from compile_commands.json")
            print()
            print("   First 15 arguments:")
            for i, arg in enumerate(args[:15]):
                print(f"     [{i:2d}] {arg}")
            if len(args) > 15:
                print(f"     ... and {len(args) - 15} more")
        else:
            print("   ✗ No args found (returned None)")
    else:
        print("3. File NOT in compile_commands.json")
        print()
        print("   Possible reasons:")
        print("   - File path format doesn't match")
        print("   - File not included in build")
        print("   - Path normalization issue")
        print()

        # Try to find similar paths
        print("   Searching for similar paths in compile_commands.json...")
        file_name = test_file.name
        matching_entries = [
            path for path in ccm.compile_commands.keys() if Path(path).name == file_name
        ]

        if matching_entries:
            print(f"   Found {len(matching_entries)} file(s) with same name:")
            for entry in matching_entries[:5]:
                print(f"     - {entry}")
            if len(matching_entries) > 5:
                print(f"     ... and {len(matching_entries) - 5} more")
        else:
            print(f"   No files with name '{file_name}' found in compile_commands.json")

    print()

    # Get args with fallback
    print("4. Getting compile args with fallback...")
    args_with_fallback = ccm.get_compile_args_with_fallback(test_file)
    print(f"   Got {len(args_with_fallback)} arguments")

    # Check if it's using fallback
    if not is_supported:
        print("   → Using FALLBACK arguments (hardcoded)")
    else:
        print("   → Using compile_commands.json arguments")

    print()
    print("=" * 80)
    print()

    # Print conclusion
    if is_supported:
        print("✅ SUCCESS: File found in compile_commands.json")
        print("   The file should be parsed with correct compilation arguments.")
    else:
        print("❌ ISSUE: File NOT found in compile_commands.json")
        print("   The file will use fallback arguments, which may cause parse errors.")
        print()
        print("   Recommendation:")
        print("   - Verify the file is included in your build system")
        print("   - Regenerate compile_commands.json")
        print("   - Check path normalization in compile_commands.json")

    return is_supported


def main():
    if len(sys.argv) < 3:
        print("Usage: python test_compile_commands_lookup.py <project-path> <file-path>")
        print()
        print("Example:")
        print("  python test_compile_commands_lookup.py /path/to/project /path/to/file.cpp")
        sys.exit(1)

    project_path = sys.argv[1]
    test_file = sys.argv[2]

    result = test_compile_commands_lookup(project_path, test_file)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
