"""
Compile Commands Manager for handling compile_commands.json files.

This module provides functionality to parse and cache compilation commands
from compile_commands.json files, enabling accurate C++ parsing with
project-specific build configurations.

Performance optimizations for large files:
- Supports orjson for faster JSON parsing (optional dependency)
- Caches parsed commands to avoid re-parsing on every startup
- Uses pickle for fast binary serialization of parsed data
"""

import json
import os
import sys
import subprocess
import pickle
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import time
import threading
from collections import defaultdict

# Try to import orjson for faster JSON parsing (optional)
try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    HAS_ORJSON = False

# Handle both package and script imports
try:
    from . import diagnostics
    from .argument_sanitizer import ArgumentSanitizer
except ImportError:
    import diagnostics
    from argument_sanitizer import ArgumentSanitizer


class CompileCommandsManager:
    """Manages compilation commands from compile_commands.json files."""
    
    def __init__(self, project_root: Path, config: Optional[Dict[str, Any]] = None):
        self.project_root = project_root
        self.config = config or {}
        
        # Configuration settings
        self.enabled = self.config.get('compile_commands_enabled', True)
        self.compile_commands_path = self.config.get('compile_commands_path', 'compile_commands.json')
        self.cache_enabled = self.config.get('compile_commands_cache_enabled', True)
        self.fallback_to_hardcoded = self.config.get('fallback_to_hardcoded', True)
        self.cache_expiry_seconds = self.config.get('cache_expiry_seconds', 300)
        self.supported_extensions = set(self.config.get('supported_extensions',
            [".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"]))
        self.exclude_patterns = self.config.get('exclude_patterns', [])
        
        # Cache data
        self.compile_commands = {}
        self.file_to_command_map = {}
        self.last_modified = 0
        self.cache_lock = threading.Lock()

        # Initialize argument sanitizer with optional custom rules
        custom_rules_file = self.config.get('sanitization_rules_file')
        custom_rules_path = None
        if custom_rules_file:
            custom_rules_path = Path(custom_rules_file)
            if not custom_rules_path.is_absolute():
                custom_rules_path = self.project_root / custom_rules_path

        self.argument_sanitizer = ArgumentSanitizer(custom_rules_file=custom_rules_path)

        # Detect clang resource directory for builtin headers (stddef.h, etc.)
        # Do this before building fallback args so we can include it
        self.clang_resource_dir = self._detect_clang_resource_dir()

        # Default fallback arguments (current hardcoded approach)
        self.fallback_args = self._build_fallback_args()

        # Load compile commands if enabled
        if self.enabled:
            self._load_compile_commands()

    def _get_compile_commands_cache_path(self) -> Path:
        """Get the cache file path for parsed compile commands."""
        # Cache in .clang_index directory
        cache_dir = self.project_root / ".clang_index"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "compile_commands.cache"

    def _get_file_hash(self, file_path: Path) -> str:
        """Get MD5 hash of a file for cache validation."""
        if not file_path.exists():
            return ""

        hash_md5 = hashlib.md5()
        # For large files, read in chunks
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _load_from_cache(self, compile_commands_file: Path) -> bool:
        """Try to load parsed commands from cache.

        Returns True if successfully loaded from cache, False otherwise.
        """
        cache_path = self._get_compile_commands_cache_path()

        if not cache_path.exists():
            return False

        try:
            # Calculate current file hash
            current_hash = self._get_file_hash(compile_commands_file)
            if not current_hash:
                return False

            # Load cache
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)

            # Validate cache
            if cache_data.get('file_hash') != current_hash:
                diagnostics.debug("Compile commands cache invalid: file changed")
                return False

            if cache_data.get('version') != '1.0':
                diagnostics.debug("Compile commands cache invalid: version mismatch")
                return False

            # Load cached data
            self.compile_commands = cache_data.get('compile_commands', {})
            self.file_to_command_map = cache_data.get('file_to_command_map', {})
            self.last_modified = compile_commands_file.stat().st_mtime

            diagnostics.info(f"Loaded {len(self.compile_commands)} compile commands from cache (fast path)")
            return True

        except Exception as e:
            diagnostics.debug(f"Failed to load from cache: {e}")
            return False

    def _save_to_cache(self, compile_commands_file: Path) -> None:
        """Save parsed commands to cache for faster loading next time."""
        cache_path = self._get_compile_commands_cache_path()

        try:
            current_hash = self._get_file_hash(compile_commands_file)

            cache_data = {
                'version': '1.0',
                'file_hash': current_hash,
                'compile_commands': self.compile_commands,
                'file_to_command_map': self.file_to_command_map
            }

            # Atomic write via temp file
            temp_path = cache_path.with_suffix('.tmp')
            with open(temp_path, 'wb') as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            temp_path.replace(cache_path)
            diagnostics.debug(f"Saved compile commands cache to {cache_path}")

        except Exception as e:
            diagnostics.debug(f"Failed to save cache: {e}")
    
    def _build_fallback_args(self) -> List[str]:
        """Build the fallback compilation arguments (current hardcoded approach)."""
        args = [
            '-std=c++17',
        ]

        # Add clang builtin includes first (highest priority for system headers)
        if self.clang_resource_dir:
            args.extend(['-isystem', self.clang_resource_dir])

        args.extend([
            '-I.',
            f'-I{self.project_root}',
            f'-I{self.project_root}/src',
            # Preprocessor defines for common libraries
            '-DWIN32',
            '-D_WIN32',
            '-D_WINDOWS',
            '-DNOMINMAX',
            # Common warnings to suppress
            '-Wno-pragma-once-outside-header',
            '-Wno-unknown-pragmas',
            '-Wno-deprecated-declarations',
            # Parse as C++
            '-x', 'c++',
        ])

        # Add Windows SDK includes if on Windows
        if sys.platform.startswith('win'):
            import glob
            winsdk_patterns = [
                "C:/Program Files (x86)/Windows Kits/10/Include/*/ucrt",
                "C:/Program Files (x86)/Windows Kits/10/Include/*/um",
                "C:/Program Files (x86)/Windows Kits/10/Include/*/shared"
            ]
            for pattern in winsdk_patterns:
                matches = glob.glob(pattern)
                if matches:
                    args.append(f'-I{matches[-1]}')  # Use latest version

        return args

    def _detect_clang_resource_dir(self) -> Optional[str]:
        """
        Detect the clang resource directory containing builtin headers.

        The resource directory contains compiler builtin headers like:
        - stddef.h
        - stdarg.h
        - stdint.h
        etc.

        These are required for libclang to parse code correctly but are not
        automatically included when using libclang programmatically.

        Returns:
            Path to the resource directory's include folder, or None if not found
        """
        try:
            # Try to get resource directory from clang itself
            result = subprocess.run(
                ['clang', '-print-resource-dir'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                resource_dir = result.stdout.strip()
                include_dir = os.path.join(resource_dir, 'include')

                # Verify the directory exists and contains stddef.h
                if os.path.isdir(include_dir):
                    stddef_path = os.path.join(include_dir, 'stddef.h')
                    if os.path.isfile(stddef_path):
                        diagnostics.debug(f"Found clang resource directory: {include_dir}")
                        return include_dir

            # Fallback: try common locations
            # Format: /usr/lib/clang/<version>/include
            clang_lib_dir = '/usr/lib/clang'
            if os.path.isdir(clang_lib_dir):
                # Find the highest version directory
                versions = []
                for entry in os.listdir(clang_lib_dir):
                    version_dir = os.path.join(clang_lib_dir, entry)
                    include_dir = os.path.join(version_dir, 'include')
                    stddef_path = os.path.join(include_dir, 'stddef.h')

                    if os.path.isfile(stddef_path):
                        versions.append((entry, include_dir))

                if versions:
                    # Sort by version (simple string sort works for most cases)
                    versions.sort(reverse=True)
                    include_dir = versions[0][1]
                    diagnostics.debug(f"Found clang resource directory (fallback): {include_dir}")
                    return include_dir

            diagnostics.warning("Could not detect clang resource directory - builtin headers may not be found")
            return None

        except Exception as e:
            diagnostics.warning(f"Error detecting clang resource directory: {e}")
            return None

    def _load_compile_commands(self) -> bool:
        """Load compile commands from compile_commands.json file.

        Optimized for large files:
        1. Try loading from cache first (fastest - ~10-100x faster)
        2. If cache miss, parse JSON file
        3. Use orjson if available (3-5x faster than stdlib json)
        4. Save to cache for next time
        """
        if not self.enabled:
            return False

        compile_commands_file = self.project_root / self.compile_commands_path

        if not compile_commands_file.exists():
            if self.fallback_to_hardcoded:
                diagnostics.info(f"compile_commands.json not found at: {compile_commands_file} - using fallback compilation arguments")
            else:
                diagnostics.warning(f"compile_commands.json not found at: {compile_commands_file} - fallback disabled")
            return False

        # Try loading from cache first (fast path)
        if self._load_from_cache(compile_commands_file):
            diagnostics.info(f"Compile commands will be used for accurate C++ parsing")
            return True

        # Cache miss - parse the file
        file_size_mb = compile_commands_file.stat().st_size / 1024 / 1024
        diagnostics.info(f"Parsing compile_commands.json ({file_size_mb:.1f} MB)...")
        start_time = time.time()

        try:
            # Use orjson if available (much faster for large files)
            if HAS_ORJSON:
                with open(compile_commands_file, 'rb') as f:
                    data = orjson.loads(f.read())
                diagnostics.debug("Using orjson for fast JSON parsing")
            else:
                with open(compile_commands_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if file_size_mb > 5:
                    diagnostics.info("Tip: Install orjson for 3-5x faster parsing of large compile_commands.json files")

            parse_time = time.time() - start_time
            diagnostics.debug(f"JSON parsing completed in {parse_time:.2f}s")

            if not isinstance(data, list):
                diagnostics.error("compile_commands.json must contain a list of commands")
                return False

            # Process and cache the commands
            process_start = time.time()
            self._parse_compile_commands(data)
            process_time = time.time() - process_start
            diagnostics.debug(f"Command processing completed in {process_time:.2f}s")

            # Update last modified time
            self.last_modified = compile_commands_file.stat().st_mtime

            # Save to cache for next time
            self._save_to_cache(compile_commands_file)

            total_time = time.time() - start_time
            diagnostics.info(f"Successfully loaded {len(self.compile_commands)} compile commands in {total_time:.2f}s")
            diagnostics.info(f"Compile commands will be used for accurate C++ parsing")
            return True

        except json.JSONDecodeError as e:
            diagnostics.error(f"Error parsing compile_commands.json: {e}")
            return False
        except Exception as e:
            diagnostics.error(f"Error loading compile_commands.json: {e}")
            return False
    
    def _parse_compile_commands(self, commands: List[Dict[str, Any]]) -> None:
        """Parse compile commands and build file-to-command mapping."""
        self.compile_commands.clear()
        self.file_to_command_map.clear()


        for i, cmd in enumerate(commands):
            if not isinstance(cmd, dict):
                diagnostics.warning(f"Skipping invalid command at index {i}")
                continue

            # Extract required fields
            if 'file' not in cmd:
                diagnostics.warning(f"Skipping command without 'file' field at index {i}")
                continue
            
            file_path = cmd['file']
            directory = cmd.get('directory', str(self.project_root))
            arguments = cmd.get('arguments', [])
            command = cmd.get('command', '')

            # Normalize file path
            file_path = self._normalize_path(file_path, directory)

            # Build arguments list from command string if needed
            if not arguments and command:
                arguments = self._parse_command_string(command)
            elif arguments:
                # If arguments were provided as a list, we still need to sanitize them
                # First, filter out compiler executable, -o, -c, and source files
                filtered_args = []
                i_arg = 0

                # Check if first argument is a compiler
                if arguments:
                    first_arg = arguments[0]
                    compiler_names = {'gcc', 'g++', 'clang', 'clang++', 'cc', 'c++', 'cl', 'cl.exe'}
                    basename = first_arg.split('/')[-1].split('\\')[-1].lower()
                    if basename.endswith('.exe'):
                        basename = basename[:-4]

                    # Skip compiler executable if present
                    if basename in compiler_names or first_arg.startswith('/') or first_arg.startswith('\\'):
                        i_arg = 1

                # Filter out -o, -c, and source files
                while i_arg < len(arguments):
                    arg = arguments[i_arg]

                    if arg == '-o':
                        i_arg += 2  # Skip -o and output file
                        continue

                    if arg == '-c':
                        i_arg += 1
                        continue

                    # Skip source files
                    if not arg.startswith('-'):
                        lower_arg = arg.lower()
                        source_extensions = ['.c', '.cc', '.cpp', '.cxx', '.c++', '.m', '.mm']
                        if any(lower_arg.endswith(ext) for ext in source_extensions):
                            i_arg += 1
                            continue

                    filtered_args.append(arg)
                    i_arg += 1

                # Sanitize for libclang
                arguments = self._sanitize_args_for_libclang(filtered_args)

            # Store the command
            self.compile_commands[file_path] = {
                'arguments': arguments,
                'directory': directory,
                'command': command,
                'index': i
            }
            
            # Build mapping from file to command (handle multiple entries for same file)
            if file_path not in self.file_to_command_map:
                self.file_to_command_map[file_path] = []
            self.file_to_command_map[file_path].append(self.compile_commands[file_path])
    
    def _normalize_path(self, file_path: str, directory: str) -> str:
        """Normalize file path to absolute path."""
        # Handle relative paths
        if not os.path.isabs(file_path):
            # If directory is provided, use it as base
            if directory and os.path.isabs(directory):
                file_path = os.path.join(directory, file_path)
            else:
                # Fall back to project root
                file_path = str(self.project_root / file_path)
        
        # Convert to absolute path and normalize
        return str(Path(file_path).resolve())

    def _normalize_arguments(self, arguments: List[str], directory: str) -> List[str]:
        """
        Normalize relative include paths in arguments to absolute paths.

        Args:
            arguments: List of compilation arguments
            directory: Base directory from compile_commands.json entry

        Returns:
            List of arguments with normalized include paths
        """
        import os
        normalized = []
        i = 0

        while i < len(arguments):
            arg = arguments[i]

            # Handle -I with separate argument
            if arg == '-I' and i + 1 < len(arguments):
                include_path = arguments[i + 1]
                # Make relative paths absolute based on directory
                if not os.path.isabs(include_path):
                    include_path = os.path.abspath(os.path.join(directory, include_path))
                normalized.append(arg)
                normalized.append(include_path)
                i += 2
                continue

            # Handle -I<path> (combined form)
            if arg.startswith('-I'):
                include_path = arg[2:]  # Remove -I prefix
                if include_path and not os.path.isabs(include_path):
                    include_path = os.path.abspath(os.path.join(directory, include_path))
                    arg = f'-I{include_path}'
                normalized.append(arg)
                i += 1
                continue

            # Handle -isystem with separate argument
            if arg == '-isystem' and i + 1 < len(arguments):
                include_path = arguments[i + 1]
                # Make relative paths absolute based on directory
                if not os.path.isabs(include_path):
                    include_path = os.path.abspath(os.path.join(directory, include_path))
                normalized.append(arg)
                normalized.append(include_path)
                i += 2
                continue

            # Handle -isystem<path> (combined form, rare but possible)
            if arg.startswith('-isystem'):
                # Check if there's a path after -isystem
                if len(arg) > 8:  # More than just "-isystem"
                    include_path = arg[8:]  # Remove -isystem prefix
                    if not os.path.isabs(include_path):
                        include_path = os.path.abspath(os.path.join(directory, include_path))
                        arg = f'-isystem{include_path}'
                normalized.append(arg)
                i += 1
                continue

            # Keep other arguments as-is
            normalized.append(arg)
            i += 1

        return normalized

    def _sanitize_args_for_libclang(self, args: List[str]) -> List[str]:
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

        The rules are loaded from sanitization_rules.json and can be extended with
        custom rules via the 'sanitization_rules_file' config option.

        Args:
            args: List of compiler arguments

        Returns:
            Sanitized list of arguments safe for libclang

        See Also:
            - mcp_server/sanitization_rules.json for default rules
            - ArgumentSanitizer class for rule engine implementation
        """
        return self.argument_sanitizer.sanitize(args)

    def _parse_command_string(self, command: str) -> List[str]:
        """Parse command string into arguments list.

        The command string typically starts with the compiler executable path,
        which should be stripped out since libclang only needs the compilation flags.
        Also strips output file arguments (-o <file>), compile-only flag (-c),
        and the source file argument.
        """
        import shlex
        import os

        try:
            # Handle quoted arguments properly
            args = shlex.split(command)

            # Filter out empty strings
            args = [arg for arg in args if arg.strip()]

            if not args:
                return []

            # Strip the first argument if it looks like a compiler executable
            # This is necessary because libclang expects only compilation flags,
            # not the compiler path itself
            first_arg = args[0]

            # Check if first argument is a compiler executable path or name
            # Common patterns: gcc, g++, clang, clang++, cc, c++, or paths to them
            compiler_names = {'gcc', 'g++', 'clang', 'clang++', 'cc', 'c++', 'cl', 'cl.exe'}

            # Get the basename to check if it's a compiler
            # Handle both Unix and Windows path separators
            basename = first_arg.split('/')[-1].split('\\')[-1].lower()
            # Remove .exe extension if present (case-insensitive)
            if basename.endswith('.exe'):
                basename = basename[:-4]

            # If the first argument is a compiler, strip it
            if basename in compiler_names or first_arg.startswith('/') or first_arg.startswith('\\'):
                # This looks like a compiler path, remove it
                args = args[1:]

            # Filter out arguments that libclang doesn't need:
            # - Output file: -o <file>
            # - Compile-only flag: -c
            # - Source files (arguments that look like file paths, typically at the end)
            filtered_args = []
            i = 0
            while i < len(args):
                arg = args[i]

                # Skip -o and its argument (output file)
                if arg == '-o':
                    # Skip both -o and the next argument (the output file path)
                    i += 2
                    continue

                # Skip -c (compile-only flag)
                if arg == '-c':
                    i += 1
                    continue

                # Skip arguments that look like source files
                # These are typically file paths with C/C++ extensions, not starting with -
                if not arg.startswith('-'):
                    # Check if it looks like a source file
                    lower_arg = arg.lower()
                    source_extensions = ['.c', '.cc', '.cpp', '.cxx', '.c++', '.m', '.mm']
                    if any(lower_arg.endswith(ext) for ext in source_extensions):
                        # This is likely the source file being compiled, skip it
                        i += 1
                        continue

                # Keep this argument
                filtered_args.append(arg)
                i += 1

            # Sanitize the arguments for libclang
            filtered_args = self._sanitize_args_for_libclang(filtered_args)

            return filtered_args

        except Exception as e:
            diagnostics.warning(f"Failed to parse command string '{command}': {e}")
            return []
    
    def _detect_cxx_stdlib_path(self, arguments: List[str]) -> Optional[str]:
        """
        Detect the C++ standard library include path based on compile arguments.

        When using libclang programmatically, the C++ standard library headers
        are not automatically found even when -stdlib and -isysroot are specified.
        We need to explicitly add the C++ stdlib include path.

        Args:
            arguments: List of compilation arguments

        Returns:
            Path to C++ standard library includes, or None if not found
        """
        stdlib = None
        sysroot = None

        # Detect -stdlib flag
        for i, arg in enumerate(arguments):
            if arg == '-stdlib' and i + 1 < len(arguments):
                stdlib = arguments[i + 1]
            elif arg.startswith('-stdlib='):
                stdlib = arg[8:]  # Remove '-stdlib=' prefix

        # Detect -isysroot flag
        for i, arg in enumerate(arguments):
            if arg == '-isysroot' and i + 1 < len(arguments):
                sysroot = arguments[i + 1]
            elif arg.startswith('-isysroot='):
                sysroot = arg[10:]  # Remove '-isysroot=' prefix

        # If no stdlib specified, assume system default
        # For macOS, this is typically libc++
        if not stdlib and sysroot:
            # On macOS, default is libc++
            if 'MacOSX' in sysroot or 'macos' in sysroot.lower():
                stdlib = 'libc++'

        if not stdlib:
            # No stdlib or sysroot info, can't determine path
            return None

        # Build the C++ stdlib include path
        if stdlib == 'libc++':
            # For libc++, headers are in /usr/include/c++/v1
            if sysroot:
                cxx_path = os.path.join(sysroot, 'usr', 'include', 'c++', 'v1')
                # Return the path even if directory doesn't exist on current system
                # (e.g., when analyzing macOS code on Linux)
                # libclang will handle missing directories gracefully
                return cxx_path

            # Try system paths
            system_paths = [
                '/usr/include/c++/v1',
                '/usr/local/include/c++/v1'
            ]
            for path in system_paths:
                if os.path.isdir(path):
                    return path

        elif stdlib == 'libstdc++':
            # For libstdc++, headers are in /usr/include/c++/<version>
            if sysroot:
                cxx_base = os.path.join(sysroot, 'usr', 'include', 'c++')
                if os.path.isdir(cxx_base):
                    # Find the highest version directory
                    try:
                        versions = [d for d in os.listdir(cxx_base)
                                   if os.path.isdir(os.path.join(cxx_base, d))
                                   and d[0].isdigit()]
                        if versions:
                            versions.sort(reverse=True)
                            return os.path.join(cxx_base, versions[0])
                    except Exception:
                        pass

        return None

    def _add_builtin_includes(self, arguments: List[str]) -> List[str]:
        """
        Add clang builtin include directory and C++ stdlib to arguments if not already present.

        This is necessary for libclang to find compiler builtin headers like:
        - stddef.h
        - stdarg.h
        - stdint.h

        And C++ standard library headers like:
        - <iostream>
        - <vector>
        - <string>

        These headers are not automatically available when using libclang
        programmatically, unlike when using the clang compiler directly.

        IMPORTANT: The C++ stdlib path MUST come before the clang resource directory.
        This is because C++ wrapper headers (like <cstddef>) need to include the C++
        version of C headers, not the plain C versions.

        Args:
            arguments: List of compilation arguments

        Returns:
            Arguments with builtin include directory added if needed
        """
        result = arguments.copy()

        # Find insertion position (after -std= flag if present)
        insert_pos = 0
        for i, arg in enumerate(result):
            if arg.startswith('-std='):
                insert_pos = i + 1
                break

        # Step 1: Add C++ standard library include path FIRST
        # This must come BEFORE the clang resource directory to ensure proper header resolution
        cxx_stdlib_path = self._detect_cxx_stdlib_path(arguments)
        if cxx_stdlib_path:
            # Check if already present
            already_has_stdlib = False
            for arg in result:
                if cxx_stdlib_path in arg:
                    already_has_stdlib = True
                    break

            if not already_has_stdlib:
                # Add C++ stdlib path as first system include
                # This ensures it has priority for C++ headers
                result.insert(insert_pos, '-isystem')
                result.insert(insert_pos + 1, cxx_stdlib_path)
                diagnostics.debug(f"Added C++ stdlib path: {cxx_stdlib_path}")
                # Update insert position for next includes
                insert_pos += 2

        # Step 2: Add clang resource directory for builtin headers AFTER C++ stdlib
        if self.clang_resource_dir:
            # Check if the resource directory is already in the include paths
            already_has_resource = False
            for arg in result:
                if self.clang_resource_dir in arg:
                    already_has_resource = True
                    break

            if not already_has_resource:
                # Add the resource directory as a system include (-isystem)
                # Use -isystem instead of -I to avoid warnings from system headers
                # Insert after C++ stdlib
                result.insert(insert_pos, '-isystem')
                result.insert(insert_pos + 1, self.clang_resource_dir)
                diagnostics.debug(f"Added clang resource dir: {self.clang_resource_dir}")

        return result

    def get_compile_args(self, file_path: Path) -> Optional[List[str]]:
        """Get compilation arguments for a specific file."""
        if not self.enabled:
            return None

        # Check if compile_commands.json still exists
        compile_commands_file = self.project_root / self.compile_commands_path
        if not compile_commands_file.exists():
            return None

        # Resolve relative paths relative to project_root
        if not file_path.is_absolute():
            file_path = self.project_root / file_path

        # Normalize the file path
        file_path_str = str(file_path.resolve())

        # Check cache first
        with self.cache_lock:
            if file_path_str in self.file_to_command_map:
                # Get the most recent command for this file
                commands = self.file_to_command_map[file_path_str]
                if commands:
                    cmd = commands[-1]
                    arguments = cmd['arguments'].copy()
                    directory = cmd['directory']
                    # Normalize relative include paths to absolute paths
                    normalized_args = self._normalize_arguments(arguments, directory)
                    # Add clang builtin includes if needed
                    return self._add_builtin_includes(normalized_args)

        return None
    
    def get_compile_args_with_fallback(self, file_path: Path) -> List[str]:
        """Get compilation arguments for a file, with fallback to hardcoded args."""
        # Try to get compile commands first
        compile_args = self.get_compile_args(file_path)
        
        if compile_args is not None:
            return compile_args
        
        # Fall back to hardcoded arguments
        if self.fallback_to_hardcoded:
            return self.fallback_args.copy()
        
        # Return empty list if fallback is disabled
        return []
    
    def refresh_if_needed(self) -> bool:
        """Refresh compile commands if the file has been modified."""
        if not self.enabled:
            return False

        compile_commands_file = self.project_root / self.compile_commands_path

        if not compile_commands_file.exists():
            # Clear cache if file no longer exists
            with self.cache_lock:
                self.compile_commands.clear()
                self.file_to_command_map.clear()
                self.last_modified = 0
            return False
        
        # Check if file has been modified
        current_modified = compile_commands_file.stat().st_mtime
        if current_modified <= self.last_modified:
            return False
        
        # Reload the commands
        success = self._load_compile_commands()
        if success:
            diagnostics.info("Refreshed compile_commands.json cache")

        return success
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the compile commands manager."""
        with self.cache_lock:
            return {
                'enabled': self.enabled,
                'compile_commands_count': len(self.compile_commands),
                'file_mapping_count': len(self.file_to_command_map),
                'cache_enabled': self.cache_enabled,
                'fallback_enabled': self.fallback_to_hardcoded,
                'last_modified': self.last_modified,
                'compile_commands_path': str(self.project_root / self.compile_commands_path)
            }
    
    def is_file_supported(self, file_path: Path) -> bool:
        """Check if a file has compile commands available."""
        if not self.enabled:
            return False
        
        file_path_str = str(file_path.resolve())
        return file_path_str in self.file_to_command_map
    
    def get_all_files(self) -> List[str]:
        """Get all files that have compile commands."""
        if not self.enabled:
            return []
        
        with self.cache_lock:
            return list(self.file_to_command_map.keys())
        
    def should_process_file(self, file_path: Path) -> bool:
        """Determine if a file should be processed based on compile_commands.json availability and extensions."""
        # Check if the file has compile commands available
        if self.is_file_supported(file_path):
            return True
        
        # If no compile commands are available but extension is supported, we can still process it with fallback
        if self.is_extension_supported(file_path):
            return True
            
        return False
    
    def is_extension_supported(self, file_path: Path) -> bool:
        """Check if a file extension is supported for compile commands."""
        try:
            ext = file_path.suffix.lower()
            return ext in self.supported_extensions
        except Exception:
            return False
    
    def clear_cache(self) -> None:
        """Clear the compile commands cache."""
        with self.cache_lock:
            self.compile_commands.clear()
            self.file_to_command_map.clear()
            self.last_modified = 0