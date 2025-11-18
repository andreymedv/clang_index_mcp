#!/usr/bin/env python3
"""Diagnostic tool to check what arguments are being passed to libclang."""

import sys
import os
import json
from pathlib import Path

# Add the mcp_server directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mcp_server'))

from compile_commands_manager import CompileCommandsManager

def diagnose_file_args(project_root: str, file_path: str):
    """Diagnose compilation arguments for a specific file."""

    project_root = Path(project_root).resolve()
    file_path = Path(file_path).resolve()

    print(f"=== Diagnosing Arguments for {file_path.name} ===\n")
    print(f"Project root: {project_root}")
    print(f"File path: {file_path}\n")

    # Create manager
    manager = CompileCommandsManager(project_root)

    # Get the arguments
    args = manager.get_compile_args(file_path)

    if args is None:
        print("[ERROR] No compile arguments found for this file")
        return 1

    print(f"[OK] Found {len(args)} arguments\n")

    # Categorize arguments
    include_paths = []
    isystem_paths = []
    defines = []
    standards = []
    warnings = []
    other = []

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == '-I' and i + 1 < len(args):
            include_paths.append(args[i + 1])
            i += 2
        elif arg.startswith('-I'):
            include_paths.append(arg[2:])
            i += 1
        elif arg == '-isystem' and i + 1 < len(args):
            isystem_paths.append(args[i + 1])
            i += 2
        elif arg.startswith('-isystem'):
            isystem_paths.append(arg[8:])
            i += 1
        elif arg.startswith('-D'):
            defines.append(arg)
            i += 1
        elif arg.startswith('-std='):
            standards.append(arg)
            i += 1
        elif arg.startswith('-W'):
            warnings.append(arg)
            i += 1
        else:
            other.append(arg)
            i += 1

    # Print categorized arguments
    print("=== Categorized Arguments ===\n")

    if standards:
        print(f"Standard: {', '.join(standards)}")

    if defines:
        print(f"\nDefines ({len(defines)}):")
        for d in defines[:10]:
            print(f"  {d}")
        if len(defines) > 10:
            print(f"  ... and {len(defines) - 10} more")

    if include_paths:
        print(f"\n-I Include Paths ({len(include_paths)}):")
        for path in include_paths:
            exists = "[OK]" if Path(path).exists() else "[ERROR]"
            print(f"  {exists} {path}")

    if isystem_paths:
        print(f"\n-isystem Include Paths ({len(isystem_paths)}):")
        for path in isystem_paths:
            exists = "[OK]" if Path(path).exists() else "[ERROR]"
            print(f"  {exists} {path}")

    if warnings:
        print(f"\nWarning Flags ({len(warnings)}):")
        for w in warnings[:5]:
            print(f"  {w}")
        if len(warnings) > 5:
            print(f"  ... and {len(warnings) - 5} more")

    if other:
        print(f"\nOther Arguments ({len(other)}):")
        for o in other:
            print(f"  {o}")

    # Check for missing paths
    missing_include = [p for p in include_paths if not Path(p).exists()]
    missing_isystem = [p for p in isystem_paths if not Path(p).exists()]

    print("\n=== Path Validation ===\n")

    if missing_include or missing_isystem:
        print("[WARNING]  Some include paths don't exist:")
        for p in missing_include:
            print(f"  [ERROR] -I {p}")
        for p in missing_isystem:
            print(f"  [ERROR] -isystem {p}")
        print("\nThis will cause 'file not found' errors when parsing.")
        print("The paths in compile_commands.json may be from a different build or system.")
    else:
        print("[OK] All include paths exist")

    # Show all arguments as they would be passed to libclang
    print("\n=== Full Argument List (as passed to libclang) ===\n")
    for i, arg in enumerate(args, 1):
        print(f"{i:3d}. {arg}")

    return 0

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 diagnose_args.py <project_root> <file_path>")
        print("\nExample:")
        print("  python3 diagnose_args.py /home/andrey/myoffice /home/andrey/myoffice/CloudOffice/Testing/LLDBPrettyPrintersTest/TestCode.cpp")
        sys.exit(1)

    project_root = sys.argv[1]
    file_path = sys.argv[2]

    sys.exit(diagnose_file_args(project_root, file_path))
