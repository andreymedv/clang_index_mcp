#!/usr/bin/env python3
"""
Helper script to validate include paths in compile_commands.json.
Checks if all include paths mentioned in the compilation database exist
and reports any non-existing paths.
"""

import argparse
import json
import os
import re
import sys
from typing import List, Set, Tuple


def extract_include_paths(command: str) -> List[str]:
    """
    Extract include paths from a compiler command.
    Handles both -I<path> and -isystem <path> formats.

    Args:
        command: The compiler command string

    Returns:
        List of include paths
    """
    include_paths = []

    # Pattern for -I<path> (no space between flag and path)
    i_pattern = r"-I([^\s]+)"
    # Pattern for -isystem <path> (space between flag and path)
    isystem_pattern = r"-isystem\s+([^\s]+)"

    # Find all -I paths
    for match in re.finditer(i_pattern, command):
        path = match.group(1)
        include_paths.append(path)

    # Find all -isystem paths
    for match in re.finditer(isystem_pattern, command):
        path = match.group(1)
        include_paths.append(path)

    return include_paths


def resolve_path(path: str, base_directory: str) -> str:
    """
    Resolve a path relative to a base directory if it's not absolute.

    Args:
        path: The path to resolve
        base_directory: Base directory for relative paths

    Returns:
        Resolved absolute path
    """
    if os.path.isabs(path):
        return path
    else:
        return os.path.join(base_directory, path)


def check_compile_commands(
    compile_commands_path: str, verbose: bool = False
) -> Tuple[Set[str], Set[str]]:
    """
    Check all include paths in compile_commands.json.

    Args:
        compile_commands_path: Path to compile_commands.json
        verbose: If True, print all checked paths

    Returns:
        Tuple of (all_paths, missing_paths)
    """
    try:
        with open(compile_commands_path, "r") as f:
            compile_commands = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {compile_commands_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON: {e}", file=sys.stderr)
        sys.exit(1)

    all_paths = set()
    missing_paths = set()

    for entry in compile_commands:
        command = entry.get("command", "")
        directory = entry.get("directory", "")

        if not command:
            continue

        # Extract include paths from the command
        include_paths = extract_include_paths(command)

        # Check each path
        for path in include_paths:
            # Resolve relative paths
            resolved_path = resolve_path(path, directory)
            all_paths.add(resolved_path)

            # Check if path exists
            if not os.path.exists(resolved_path):
                missing_paths.add(resolved_path)
                if verbose:
                    print(f"  Missing: {resolved_path}")
            elif verbose:
                print(f"  Found: {resolved_path}")

    return all_paths, missing_paths


def main():
    parser = argparse.ArgumentParser(
        description="Check if all include paths in compile_commands.json exist"
    )
    parser.add_argument(
        "compile_commands",
        nargs="?",
        default="compile_commands.json",
        help="Path to compile_commands.json (default: compile_commands.json)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print all checked paths")
    parser.add_argument("--stats", action="store_true", help="Print statistics about checked paths")

    args = parser.parse_args()

    if not os.path.exists(args.compile_commands):
        print(f"Error: File not found: {args.compile_commands}", file=sys.stderr)
        sys.exit(1)

    print(f"Checking include paths in: {args.compile_commands}")
    print()

    all_paths, missing_paths = check_compile_commands(args.compile_commands, args.verbose)

    if missing_paths:
        print("Non-existing include paths found:")
        print()
        for path in sorted(missing_paths):
            print(f"  {path}")
        print()
        print(f"Total: {len(missing_paths)} non-existing path(s)")
        if args.stats:
            print(f"Total unique include paths checked: {len(all_paths)}")
        sys.exit(1)
    else:
        print("All include paths exist!")
        if args.stats:
            print(f"Total unique include paths checked: {len(all_paths)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
