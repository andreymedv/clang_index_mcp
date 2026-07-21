"""
Compile_commands.json parsing and argument normalization.

Loads compilation databases, filters and sanitizes compiler arguments, and
normalizes paths so that libclang receives consistent, project-relative
arguments.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from clang.cindex import CompilationDatabase

# Handle both package and script imports
try:
    from .._core import diagnostics
    from .._core.argument_sanitizer import ArgumentSanitizer
    from . import compile_commands_cache
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from argument_sanitizer import ArgumentSanitizer  # type: ignore[no-redef]
    import compile_commands_cache  # type: ignore[no-redef]


def filter_arguments(arguments: List[str]) -> List[str]:
    """Filter out compiler executable, -o, -c, and source files from arguments.

    Args:
        arguments: Raw list of compilation arguments

    Returns:
        Filtered list of arguments suitable for libclang
    """
    filtered_args = []
    i_arg = 0

    # Check if first argument is a compiler
    if arguments:
        first_arg = arguments[0]
        compiler_names = {"gcc", "g++", "clang", "clang++", "cc", "c++", "cl", "cl.exe"}
        basename = first_arg.split("/")[-1].split("\\")[-1].lower()
        if basename.endswith(".exe"):
            basename = basename[:-4]

        # Skip compiler executable if present
        if basename in compiler_names or first_arg.startswith("/") or first_arg.startswith("\\"):
            i_arg = 1

    # Filter out -o, -c, and source files
    while i_arg < len(arguments):
        arg = arguments[i_arg]

        if arg == "-o":
            i_arg += 2  # Skip -o and output file
            continue

        if arg == "-c":
            i_arg += 1
            continue

        # Skip source files
        if not arg.startswith("-"):
            lower_arg = arg.lower()
            source_extensions = [".c", ".cc", ".cpp", ".cxx", ".c++", ".m", ".mm"]
            if any(lower_arg.endswith(ext) for ext in source_extensions):
                i_arg += 1
                continue

        filtered_args.append(arg)
        i_arg += 1

    return filtered_args


def normalize_path(file_path: str, directory: str, project_root: Path) -> str:
    """Normalize file path to absolute path."""
    # Handle relative paths
    if not os.path.isabs(file_path):
        # If directory is provided, use it as base
        if directory and os.path.isabs(directory):
            file_path = os.path.join(directory, file_path)
        else:
            # Fall back to project root
            file_path = str(project_root / file_path)

    # Convert to absolute path and normalize
    return str(Path(file_path).resolve())


def normalize_single_argument(
    arg: str, next_arg: Optional[str], directory: str
) -> Tuple[List[str], int]:
    """Normalize a single argument and its optional successor. Returns (new_args, consumed_count)."""
    if arg == "-I" and next_arg is not None:
        include_path = next_arg
        if not os.path.isabs(include_path):
            include_path = os.path.abspath(os.path.join(directory, include_path))
        return [arg, include_path], 2

    if arg.startswith("-I"):
        include_path = arg[2:]
        if include_path and not os.path.isabs(include_path):
            arg = f"-I{os.path.abspath(os.path.join(directory, include_path))}"
        return [arg], 1

    if arg == "-isystem" and next_arg is not None:
        include_path = next_arg
        if not os.path.isabs(include_path):
            include_path = os.path.abspath(os.path.join(directory, include_path))
        return [arg, include_path], 2

    if arg.startswith("-isystem"):
        if len(arg) > 8:
            include_path = arg[8:]
            if not os.path.isabs(include_path):
                arg = f"-isystem{os.path.abspath(os.path.join(directory, include_path))}"
        return [arg], 1

    return [arg], 1


def normalize_arguments(arguments: List[str], directory: str) -> List[str]:
    """
    Normalize relative include paths in arguments to absolute paths.

    Args:
        arguments: List of compilation arguments
        directory: Base directory from compile_commands.json entry

    Returns:
        List of arguments with normalized include paths
    """
    normalized: List[str] = []
    i = 0

    while i < len(arguments):
        next_arg = arguments[i + 1] if i + 1 < len(arguments) else None
        new_args, consumed = normalize_single_argument(arguments[i], next_arg, directory)
        normalized.extend(new_args)
        i += consumed

    return normalized


def sanitize_args_for_libclang(args: List[str], argument_sanitizer: ArgumentSanitizer) -> List[str]:
    """Sanitize compiler arguments for use with libclang using rule-based system.

    Uses the ArgumentSanitizer with loaded rules to remove arguments that can
    cause libclang parsing failures:
    - Precompiled header options (-include-pch, -Xclang -include-pch, etc.)
    - Compiler-specific options that don't affect parsing
    - Color/diagnostic formatting options
    - Version-specific compiler options
    - Optimization and debug flags
    - Architecture-specific options
    - Code generation options

    Args:
        args: List of compiler arguments

    Returns:
        Sanitized list of arguments safe for libclang
    """
    return argument_sanitizer.sanitize(args)


def process_compile_command_entry(
    entry: dict,
    index: int,
    compdb: CompilationDatabase,
    project_root: Path,
    argument_sanitizer: ArgumentSanitizer,
) -> Optional[Tuple[str, dict]]:
    """Process a single compile command entry. Returns (normalized_path, command_dict) or None."""
    if not isinstance(entry, dict):
        diagnostics.warning(f"Skipping invalid command at index {index}")
        return None

    if "file" not in entry:
        diagnostics.warning(f"Skipping command without 'file' field at index {index}")
        return None

    file_path = entry["file"]
    directory = entry.get("directory", str(project_root))
    normalized_path = normalize_path(file_path, directory, project_root)

    compile_cmds = compdb.getCompileCommands(normalized_path)
    if compile_cmds is None or len(list(compile_cmds)) == 0:
        compile_cmds = compdb.getCompileCommands(file_path)

    if compile_cmds is None:
        return None

    for cmd in compile_cmds:
        raw_arguments = list(cmd.arguments)
        filtered_args = filter_arguments(raw_arguments)
        arguments = sanitize_args_for_libclang(filtered_args, argument_sanitizer)

        command = {
            "arguments": arguments,
            "directory": cmd.directory,
            "command": "",
            "index": index,
        }
        return normalized_path, command

    return None


def parse_compile_commands_from_db(
    compdb: "CompilationDatabase",
    compile_commands_file: Path,
    project_root: Path,
    argument_sanitizer: ArgumentSanitizer,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse compile commands from CompilationDatabase and build file-to-command mapping.

    This method uses the CompilationDatabase API to get compile commands,
    which handles command parsing internally without needing shlex.
    """
    compile_commands: Dict[str, Any] = {}
    file_to_command_map: Dict[str, Any] = {}

    try:
        with open(compile_commands_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            diagnostics.error("compile_commands.json must contain a list of commands")
            return compile_commands, file_to_command_map

        for i, entry in enumerate(data):
            result = process_compile_command_entry(
                entry, i, compdb, project_root, argument_sanitizer
            )
            if result is None:
                continue
            normalized_path, command = result
            compile_commands[normalized_path] = command
            if normalized_path not in file_to_command_map:
                file_to_command_map[normalized_path] = []
            file_to_command_map[normalized_path].append(command)

    except Exception as e:
        diagnostics.error(f"Error parsing compile commands from database: {e}")

    return compile_commands, file_to_command_map


def load_compile_commands(
    enabled: bool,
    project_root: Path,
    compile_commands_path: str,
    fallback_to_hardcoded: bool,
    cache_enabled: bool,
    cache_dir: Optional[Path],
    argument_sanitizer: ArgumentSanitizer,
) -> Tuple[bool, Dict[str, Any], Dict[str, Any], float]:
    """Load compile commands from compile_commands.json file.

    Optimized for large files:
    1. Try loading from cache first (fastest - ~10-100x faster)
    2. If cache miss, use CompilationDatabase API
    3. Save to cache for next time

    Returns:
        Tuple of (success, compile_commands, file_to_command_map, last_modified).
    """
    if not enabled:
        return False, {}, {}, 0

    compile_commands_file = project_root / compile_commands_path

    if not compile_commands_file.exists():
        if fallback_to_hardcoded:
            diagnostics.info(
                f"compile_commands.json not found at: {compile_commands_file} - using fallback compilation arguments"
            )
        else:
            diagnostics.warning(
                f"compile_commands.json not found at: {compile_commands_file} - fallback disabled"
            )
        return False, {}, {}, 0

    # Try loading from cache first (fast path)
    cached = compile_commands_cache.load_from_cache(
        compile_commands_file, cache_dir, project_root, compile_commands_path
    )
    if cached is not None:
        compile_commands, file_to_command_map, last_modified = cached
        diagnostics.debug("Compile commands will be used for accurate C++ parsing")
        return True, compile_commands, file_to_command_map, last_modified

    # Cache miss - parse using CompilationDatabase API
    file_size_mb = compile_commands_file.stat().st_size / 1024 / 1024
    diagnostics.info(f"Parsing compile_commands.json ({file_size_mb:.1f} MB)...")
    start_time = time.time()

    try:
        # Use CompilationDatabase API to load compile_commands.json
        # This is more efficient than manual JSON parsing
        compdb = CompilationDatabase.fromDirectory(str(Path(compile_commands_file).parent))

        parse_time = time.time() - start_time
        diagnostics.debug(f"CompilationDatabase loading completed in {parse_time:.2f}s")

        # Process and cache the commands
        process_start = time.time()
        compile_commands, file_to_command_map = parse_compile_commands_from_db(
            compdb, compile_commands_file, project_root, argument_sanitizer
        )
        process_time = time.time() - process_start
        diagnostics.debug(f"Command processing completed in {process_time:.2f}s")

        # Update last modified time
        last_modified = compile_commands_file.stat().st_mtime

        # Save to cache for next time
        compile_commands_cache.save_to_cache(
            compile_commands_file,
            cache_dir,
            project_root,
            compile_commands_path,
            compile_commands,
            file_to_command_map,
        )

        total_time = time.time() - start_time
        diagnostics.info(
            f"Successfully loaded {len(compile_commands)} compile commands in {total_time:.2f}s"
        )
        diagnostics.debug("Compile commands will be used for accurate C++ parsing")
        return True, compile_commands, file_to_command_map, last_modified

    except Exception as e:
        diagnostics.error(f"Error loading from {compile_commands_file}: {e}")
        return False, {}, {}, 0
