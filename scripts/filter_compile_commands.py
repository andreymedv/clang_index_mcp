#!/usr/bin/env python3
"""
Filter compile_commands.json to include only entries for source files
located in specified directories (recursively).

This script is useful for creating test versions of compile_commands.json
that contain only entries from specific project subdirectories.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any


def normalize_path(path: str, base_directory: str = None) -> Path:
    """
    Normalize a path, handling both absolute and relative paths.

    Args:
        path: The path to normalize
        base_directory: Base directory for relative paths

    Returns:
        Normalized absolute Path object
    """
    path_obj = Path(path)

    # If path is relative and base_directory provided, resolve relative to base
    if not path_obj.is_absolute() and base_directory:
        path_obj = Path(base_directory) / path_obj

    # Resolve to absolute path and normalize
    try:
        return path_obj.resolve()
    except (OSError, RuntimeError):
        # If resolve fails, just make it absolute
        return path_obj.absolute()


def is_path_in_directories(file_path: Path, directories: List[Path]) -> bool:
    """
    Check if a file path is located within any of the specified directories.

    Args:
        file_path: Path to the file to check
        directories: List of directory paths to check against

    Returns:
        True if file_path is within any of the directories (recursively)
    """
    for directory in directories:
        try:
            # Check if file_path is relative to directory
            file_path.relative_to(directory)
            return True
        except ValueError:
            # file_path is not relative to this directory
            continue

    return False


def filter_compile_commands(
    input_path: str,
    output_path: str,
    filter_dirs: List[str],
    verbose: bool = False
) -> int:
    """
    Filter compile_commands.json to include only entries from specified directories.

    Args:
        input_path: Path to input compile_commands.json
        output_path: Path to output compile_commands.json
        filter_dirs: List of directory paths to filter by
        verbose: If True, print detailed information

    Returns:
        Number of entries in the filtered output
    """
    # Load input compile_commands.json
    try:
        with open(input_path, 'r') as f:
            compile_commands = json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse input JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(compile_commands, list):
        print(f"Error: compile_commands.json should contain a list", file=sys.stderr)
        sys.exit(1)

    # Normalize filter directories
    normalized_dirs = []
    for dir_path in filter_dirs:
        if not os.path.exists(dir_path):
            print(f"Warning: Directory does not exist: {dir_path}", file=sys.stderr)
            continue

        if not os.path.isdir(dir_path):
            print(f"Warning: Not a directory: {dir_path}", file=sys.stderr)
            continue

        normalized_dirs.append(normalize_path(dir_path))

    if not normalized_dirs:
        print("Error: No valid filter directories specified", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"Filter directories (normalized):")
        for dir_path in normalized_dirs:
            print(f"  {dir_path}")
        print()

    # Filter entries
    filtered_entries = []
    for entry in compile_commands:
        if not isinstance(entry, dict):
            continue

        # Get the source file path
        file_path = entry.get('file')
        directory = entry.get('directory', '')

        if not file_path:
            if verbose:
                print(f"Warning: Entry missing 'file' field", file=sys.stderr)
            continue

        # Normalize the file path
        normalized_file = normalize_path(file_path, directory)

        # Check if file is in any of the filter directories
        if is_path_in_directories(normalized_file, normalized_dirs):
            filtered_entries.append(entry)
            if verbose:
                print(f"Including: {normalized_file}")
        elif verbose:
            print(f"Excluding: {normalized_file}")

    # Write output compile_commands.json
    try:
        # Create output directory if it doesn't exist
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(output_path, 'w') as f:
            json.dump(filtered_entries, f, indent=2)
    except IOError as e:
        print(f"Error: Failed to write output file: {e}", file=sys.stderr)
        sys.exit(1)

    return len(filtered_entries)


def main():
    parser = argparse.ArgumentParser(
        description='Filter compile_commands.json by source file directories',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter to include only src/ directory
  %(prog)s input.json output.json src/

  # Filter to include multiple directories
  %(prog)s input.json output.json src/ tests/ include/

  # Use verbose mode to see what's being included/excluded
  %(prog)s -v input.json output.json src/
        """
    )

    parser.add_argument(
        'input',
        help='Path to input compile_commands.json'
    )

    parser.add_argument(
        'output',
        help='Path to output compile_commands.json'
    )

    parser.add_argument(
        'directories',
        nargs='+',
        help='One or more directories to filter by (recursive)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Print detailed information about filtering'
    )

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Warn if output file exists
    if os.path.exists(args.output):
        print(f"Warning: Output file already exists and will be overwritten: {args.output}")
        print()

    # Perform filtering
    print(f"Filtering {args.input} -> {args.output}")
    print(f"Filter directories: {', '.join(args.directories)}")
    print()

    num_filtered = filter_compile_commands(
        args.input,
        args.output,
        args.directories,
        args.verbose
    )

    print()
    print(f"Filtered {num_filtered} entries written to {args.output}")


if __name__ == '__main__':
    main()
