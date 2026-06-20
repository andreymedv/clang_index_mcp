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

import hashlib
import json
import os
import pickle
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from clang.cindex import CompilationDatabase

# Handle both package and script imports
try:
    from .cpp_analyzer_config import CompileCommandsConfig
    from .file_scanner import FileScanner
except ImportError:
    from cpp_analyzer_config import CompileCommandsConfig  # type: ignore[no-redef]
    from file_scanner import FileScanner  # type: ignore[no-redef]  # noqa: F401

# Try to import orjson for faster JSON parsing (optional)
HAS_ORJSON = False
try:
    import orjson  # noqa: F401

    HAS_ORJSON = True
except ImportError:
    pass

# Handle both package and script imports
try:
    from . import diagnostics
    from .argument_sanitizer import ArgumentSanitizer
except ImportError:
    import diagnostics  # type: ignore[no-redef]
    from argument_sanitizer import ArgumentSanitizer  # type: ignore[no-redef]


class CompileCommandsManager:
    """Manages compilation commands from compile_commands.json files."""

    def __init__(
        self,
        project_root: Path,
        config: Optional[Union[Dict[str, Any], CompileCommandsConfig]] = None,
        cache_dir: Optional[Path] = None,
        cache_backend: Optional[Any] = None,
    ):
        self.project_root = project_root
        self._config = (
            config
            if isinstance(config, CompileCommandsConfig)
            else CompileCommandsConfig.from_dict(config)
        )
        self.cache_dir = cache_dir  # Optional cache directory from CacheManager
        self.cache_backend = cache_backend  # Optional SQLite cache backend

        # Configuration settings
        self.enabled = self._config.compile_commands_enabled
        self.compile_commands_path = self._config.compile_commands_path
        self.cache_enabled = self._config.compile_commands_cache_enabled
        self.fallback_to_hardcoded = self._config.fallback_to_hardcoded
        self.cache_expiry_seconds = self._config.cache_expiry_seconds
        self.supported_extensions = set(self._config.supported_extensions)
        self.exclude_patterns = list(self._config.exclude_patterns)

        # Cache data
        self.compile_commands: Dict[str, Any] = {}
        self.file_to_command_map: Dict[str, Any] = {}
        self.last_modified: float = 0
        self.cache_lock = threading.Lock()

        # Initialize argument sanitizer with optional custom rules
        custom_rules_file = self._config.sanitization_rules_file
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
        """Get the cache file path for parsed compile commands.

        If cache_dir is provided (from CacheManager), stores cache in:
            <cache_dir>/compile_commands/<hash>.cache

        Where <hash> is derived from the absolute path of compile_commands.json
        to support multiple build configurations.

        If cache_dir is not provided, falls back to legacy location:
            <project_root>/.clang_index/compile_commands.cache
        """
        if self.cache_dir:
            # New location: .mcp_cache/<project>/compile_commands/<hash>.cache
            compile_commands_file = self.project_root / self.compile_commands_path

            # Hash the absolute path of compile_commands.json for uniqueness
            cc_path_hash = hashlib.md5(str(compile_commands_file.absolute()).encode()).hexdigest()[
                :16
            ]

            # Create compile_commands subdirectory
            cc_cache_dir = self.cache_dir / "compile_commands"
            cc_cache_dir.mkdir(parents=True, exist_ok=True)

            return cc_cache_dir / f"{cc_path_hash}.cache"
        else:
            # Legacy location: <project_root>/.clang_index/compile_commands.cache
            cache_dir = self.project_root / ".clang_index"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir / "compile_commands.cache"

    def _get_file_hash(self, file_path: Path) -> str:
        """Get MD5 hash of a file for cache validation."""
        from .file_utils import hash_file

        return hash_file(file_path)

    # ------------------------------------------------------------------
    # Compile-commands diff and argument-hash helpers
    # ------------------------------------------------------------------
    @staticmethod
    def compute_commands_diff(
        old_commands: Dict[str, List[str]], new_commands: Dict[str, List[str]]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """
        Compute difference between two compile-command maps.

        Returns:
            Tuple of (added_files, removed_files, changed_files).
        """
        old_files = set(old_commands.keys())
        new_files = set(new_commands.keys())

        added = new_files - old_files
        removed = old_files - new_files
        changed = {
            file_path
            for file_path in old_files & new_files
            if old_commands[file_path] != new_commands[file_path]
        }

        diagnostics.debug(f"Compile commands diff: +{len(added)} -{len(removed)} ~{len(changed)}")
        return added, removed, changed

    def _hash_args(self, args: List[str]) -> str:
        """Return a stable hash of a compilation argument list."""
        from .file_utils import hash_compile_args

        return hash_compile_args(args, normalize_order=False)

    def store_command_hashes(self, commands: Dict[str, List[str]]) -> int:
        """Store argument hashes for the given compile commands in SQLite."""
        if self.cache_backend is None or not hasattr(self.cache_backend, "conn"):
            diagnostics.debug("Compile commands storage not supported without SQLite backend")
            return 0

        stored = 0
        try:
            for file_path, args in commands.items():
                args_hash = self._hash_args(args)
                cursor = self.cache_backend.conn.execute(
                    """
                    UPDATE file_metadata
                    SET compile_args_hash = ?
                    WHERE file_path = ?
                """,
                    (args_hash, file_path),
                )

                if cursor.rowcount == 0:
                    self.cache_backend.conn.execute(
                        """
                        INSERT OR IGNORE INTO file_metadata
                        (file_path, file_hash, compile_args_hash, indexed_at, symbol_count)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (file_path, "", args_hash, time.time(), 0),
                    )

                stored += 1

            self.cache_backend.conn.commit()
            diagnostics.debug(f"Stored {stored} compile command hashes")
            return stored
        except Exception as e:
            diagnostics.error(f"Failed to store compile commands: {e}")
            self.cache_backend.conn.rollback()
            return 0

    def get_stored_args_hash(self, file_path: str) -> str:
        """Return the stored argument hash for a file, or empty string."""
        if self.cache_backend is None or not hasattr(self.cache_backend, "conn"):
            return ""

        try:
            cursor = self.cache_backend.conn.execute(
                """
                SELECT compile_args_hash FROM file_metadata
                WHERE file_path = ?
            """,
                (file_path,),
            )
            row = cursor.fetchone()
            return row[0] or "" if row else ""
        except Exception as e:
            diagnostics.warning(f"Error getting stored commands hash: {e}")
            return ""

    def has_args_changed(self, file_path: str, current_args: List[str]) -> bool:
        """Return True if the stored argument hash differs from the current args."""
        stored_hash = self.get_stored_args_hash(file_path)
        if not stored_hash:
            return True
        return stored_hash != self._hash_args(current_args)

    def clear_stored_command_hashes(self) -> int:
        """Clear all stored compilation argument hashes."""
        if self.cache_backend is None or not hasattr(self.cache_backend, "conn"):
            return 0

        try:
            cursor = self.cache_backend.conn.execute("""
                UPDATE file_metadata
                SET compile_args_hash = NULL
            """)
            cleared: int = cursor.rowcount or 0
            self.cache_backend.conn.commit()
            diagnostics.info(f"Cleared {cleared} stored command hashes")
            return cleared
        except Exception as e:
            diagnostics.error(f"Failed to clear command hashes: {e}")
            self.cache_backend.conn.rollback()
            return 0

    def get_compile_commands_hash(self) -> str:
        """Return the MD5 hash of compile_commands.json, or empty if unavailable."""
        if not self.enabled:
            return ""

        compile_commands_file = self.project_root / self.compile_commands_path
        if not compile_commands_file.exists():
            return ""

        try:
            with open(compile_commands_file, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            diagnostics.warning(f"Failed to calculate compile_commands.json hash: {e}")
            return ""

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
            with open(cache_path, "rb") as f:
                cache_data = pickle.load(f)

            # Validate cache
            if cache_data.get("file_hash") != current_hash:
                diagnostics.debug("Compile commands cache invalid: file changed")
                return False

            if cache_data.get("version") != "1.0":
                diagnostics.debug("Compile commands cache invalid: version mismatch")
                return False

            # Load cached data
            self.compile_commands = cache_data.get("compile_commands", {})
            self.file_to_command_map = cache_data.get("file_to_command_map", {})
            self.last_modified = compile_commands_file.stat().st_mtime

            diagnostics.debug(
                f"Loaded {len(self.compile_commands)} compile commands from cache (fast path)"
            )
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
                "version": "1.0",
                "file_hash": current_hash,
                "compile_commands": self.compile_commands,
                "file_to_command_map": self.file_to_command_map,
            }

            # Atomic write via temp file
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            temp_path.replace(cache_path)
            diagnostics.debug(f"Saved compile commands cache to {cache_path}")

        except Exception as e:
            diagnostics.debug(f"Failed to save cache: {e}")

    def _build_fallback_args(self) -> List[str]:
        """Build the fallback compilation arguments (current hardcoded approach)."""
        args = [
            "-std=c++17",
        ]

        # Add clang builtin includes first (highest priority for system headers)
        if self.clang_resource_dir:
            args.extend(["-isystem", self.clang_resource_dir])

        args.extend(
            [
                "-I.",
                f"-I{self.project_root}",
                f"-I{self.project_root}/src",
                # Preprocessor defines for common libraries
                "-DWIN32",
                "-D_WIN32",
                "-D_WINDOWS",
                "-DNOMINMAX",
                # Common warnings to suppress
                "-Wno-pragma-once-outside-header",
                "-Wno-unknown-pragmas",
                "-Wno-deprecated-declarations",
                # Parse as C++
                "-x",
                "c++",
            ]
        )

        # Add Windows SDK includes if on Windows
        if sys.platform.startswith("win"):
            import glob

            winsdk_patterns = [
                "C:/Program Files (x86)/Windows Kits/10/Include/*/ucrt",
                "C:/Program Files (x86)/Windows Kits/10/Include/*/um",
                "C:/Program Files (x86)/Windows Kits/10/Include/*/shared",
            ]
            for pattern in winsdk_patterns:
                matches = glob.glob(pattern)
                if matches:
                    args.append(f"-I{matches[-1]}")  # Use latest version

        return args

    @staticmethod
    def _validate_resource_dir(include_dir: str) -> bool:
        """Check if a directory contains the required builtin headers."""
        return os.path.isdir(include_dir) and os.path.isfile(os.path.join(include_dir, "stddef.h"))

    def _get_resource_dir_from_clang(self) -> Optional[str]:
        """Try to get the clang resource directory by invoking clang directly."""
        try:
            result = subprocess.run(
                ["clang", "-print-resource-dir"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                include_dir = os.path.join(result.stdout.strip(), "include")
                if self._validate_resource_dir(include_dir):
                    diagnostics.debug(f"Found clang resource directory: {include_dir}")
                    return include_dir
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            diagnostics.debug(f"Clang execution failed, trying fallback locations: {e}")
        return None

    def _find_resource_dir_in_common_locations(self) -> Optional[str]:
        """Search for the clang resource directory in common system locations."""
        clang_lib_dir = "/usr/lib/clang"
        if not os.path.isdir(clang_lib_dir):
            return None

        versions = []
        for entry in os.listdir(clang_lib_dir):
            include_dir = os.path.join(clang_lib_dir, entry, "include")
            if self._validate_resource_dir(include_dir):
                versions.append((entry, include_dir))

        if versions:
            versions.sort(reverse=True)
            include_dir = versions[0][1]
            diagnostics.debug(f"Found clang resource directory (fallback): {include_dir}")
            return include_dir

        return None

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
            include_dir = self._get_resource_dir_from_clang()
            if include_dir is not None:
                return include_dir

            include_dir = self._find_resource_dir_in_common_locations()
            if include_dir is not None:
                return include_dir

            diagnostics.warning(
                "Could not detect clang resource directory - builtin headers may not be found"
            )
            return None

        except Exception as e:
            diagnostics.warning(f"Error detecting clang resource directory: {e}")
            return None

    def _load_compile_commands(self) -> bool:
        """Load compile commands from compile_commands.json file.

        Optimized for large files:
        1. Try loading from cache first (fastest - ~10-100x faster)
        2. If cache miss, use CompilationDatabase API
        3. Save to cache for next time
        """
        if not self.enabled:
            return False

        compile_commands_file = self.project_root / self.compile_commands_path

        if not compile_commands_file.exists():
            if self.fallback_to_hardcoded:
                diagnostics.info(
                    f"compile_commands.json not found at: {compile_commands_file} - using fallback compilation arguments"
                )
            else:
                diagnostics.warning(
                    f"compile_commands.json not found at: {compile_commands_file} - fallback disabled"
                )
            return False

        # Try loading from cache first (fast path)
        if self._load_from_cache(compile_commands_file):
            diagnostics.debug("Compile commands will be used for accurate C++ parsing")
            return True

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
            self._parse_compile_commands_from_db(compdb)
            process_time = time.time() - process_start
            diagnostics.debug(f"Command processing completed in {process_time:.2f}s")

            # Update last modified time
            self.last_modified = compile_commands_file.stat().st_mtime

            # Save to cache for next time
            self._save_to_cache(compile_commands_file)

            total_time = time.time() - start_time
            diagnostics.info(
                f"Successfully loaded {len(self.compile_commands)} compile commands in {total_time:.2f}s"
            )
            diagnostics.debug("Compile commands will be used for accurate C++ parsing")
            return True

        except Exception as e:
            diagnostics.error(f"Error loading from {compile_commands_file}: {e}")
            return False

    def _process_compile_command_entry(
        self, entry: dict, index: int, compdb: CompilationDatabase
    ) -> Optional[Tuple[str, dict]]:
        """Process a single compile command entry. Returns (normalized_path, command_dict) or None."""
        if not isinstance(entry, dict):
            diagnostics.warning(f"Skipping invalid command at index {index}")
            return None

        if "file" not in entry:
            diagnostics.warning(f"Skipping command without 'file' field at index {index}")
            return None

        file_path = entry["file"]
        directory = entry.get("directory", str(self.project_root))
        normalized_path = self._normalize_path(file_path, directory)

        compile_cmds = compdb.getCompileCommands(normalized_path)
        if compile_cmds is None or len(list(compile_cmds)) == 0:
            compile_cmds = compdb.getCompileCommands(file_path)

        if compile_cmds is None:
            return None

        for cmd in compile_cmds:
            raw_arguments = list(cmd.arguments)
            filtered_args = self._filter_arguments(raw_arguments)
            arguments = self._sanitize_args_for_libclang(filtered_args)

            command = {
                "arguments": arguments,
                "directory": cmd.directory,
                "command": "",
                "index": index,
            }
            return normalized_path, command

        return None

    def _parse_compile_commands_from_db(self, compdb: CompilationDatabase) -> None:
        """Parse compile commands from CompilationDatabase and build file-to-command mapping.

        This method uses the CompilationDatabase API to get compile commands,
        which handles command parsing internally without needing shlex.
        """
        self.compile_commands.clear()
        self.file_to_command_map.clear()

        compile_commands_file = self.project_root / self.compile_commands_path

        try:
            with open(compile_commands_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not isinstance(data, list):
                diagnostics.error("compile_commands.json must contain a list of commands")
                return

            for i, entry in enumerate(data):
                result = self._process_compile_command_entry(entry, i, compdb)
                if result is None:
                    continue
                normalized_path, command = result
                self.compile_commands[normalized_path] = command
                if normalized_path not in self.file_to_command_map:
                    self.file_to_command_map[normalized_path] = []
                self.file_to_command_map[normalized_path].append(command)

        except Exception as e:
            diagnostics.error(f"Error parsing compile commands from database: {e}")

    def _filter_arguments(self, arguments: List[str]) -> List[str]:
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
            if (
                basename in compiler_names
                or first_arg.startswith("/")
                or first_arg.startswith("\\")
            ):
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

    def _normalize_single_argument(
        self, arg: str, next_arg: Optional[str], directory: str
    ) -> Tuple[List[str], int]:
        """Normalize a single argument and its optional successor. Returns (new_args, consumed_count)."""
        import os

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

    def _normalize_arguments(self, arguments: List[str], directory: str) -> List[str]:
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
            new_args, consumed = self._normalize_single_argument(arguments[i], next_arg, directory)
            normalized.extend(new_args)
            i += consumed

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

    def _extract_stdlib_and_sysroot(
        self, arguments: List[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract -stdlib and -isysroot flags from arguments."""
        stdlib = None
        sysroot = None

        # Detect -stdlib flag
        for i, arg in enumerate(arguments):
            if arg == "-stdlib" and i + 1 < len(arguments):
                stdlib = arguments[i + 1]
            elif arg.startswith("-stdlib="):
                stdlib = arg[8:]  # Remove '-stdlib=' prefix

        # Detect -isysroot flag
        for i, arg in enumerate(arguments):
            if arg == "-isysroot" and i + 1 < len(arguments):
                sysroot = arguments[i + 1]
            elif arg.startswith("-isysroot="):
                sysroot = arg[10:]  # Remove '-isysroot=' prefix

        return stdlib, sysroot

    def _get_libcxx_path(self, sysroot: Optional[str]) -> Optional[str]:
        """Get the path for libc++ headers."""
        if sysroot:
            cxx_path = os.path.join(sysroot, "usr", "include", "c++", "v1")
            # Return the path even if directory doesn't exist on current system
            # (e.g., when analyzing macOS code on Linux)
            # libclang will handle missing directories gracefully
            return cxx_path

        # Try system paths
        system_paths = ["/usr/include/c++/v1", "/usr/local/include/c++/v1"]
        for path in system_paths:
            if os.path.isdir(path):
                return path
        return None

    def _get_libstdcxx_path(self, sysroot: Optional[str]) -> Optional[str]:
        """Get the path for libstdc++ headers."""
        if sysroot:
            cxx_base = os.path.join(sysroot, "usr", "include", "c++")
            if os.path.isdir(cxx_base):
                # Find the highest version directory
                try:
                    versions = [
                        d
                        for d in os.listdir(cxx_base)
                        if os.path.isdir(os.path.join(cxx_base, d)) and d[0].isdigit()
                    ]
                    if versions:
                        versions.sort(reverse=True)
                        return os.path.join(cxx_base, versions[0])
                except Exception:
                    pass
        return None

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
        stdlib, sysroot = self._extract_stdlib_and_sysroot(arguments)

        # If no stdlib specified, assume system default
        # For macOS, this is typically libc++
        if not stdlib and sysroot:
            # On macOS, default is libc++
            if "MacOSX" in sysroot or "macos" in sysroot.lower():
                stdlib = "libc++"

        if not stdlib:
            # No stdlib or sysroot info, can't determine path
            return None

        # Build the C++ stdlib include path
        if stdlib == "libc++":
            return self._get_libcxx_path(sysroot)
        elif stdlib == "libstdc++":
            return self._get_libstdcxx_path(sysroot)

        return None

    def _find_std_insert_position(self, arguments: List[str]) -> int:
        """Find insertion position after -std= flag if present."""
        for i, arg in enumerate(arguments):
            if arg.startswith("-std="):
                return i + 1
        return 0

    def _is_path_in_args(self, path: str, arguments: List[str]) -> bool:
        """Check if a path is already present in arguments."""
        for arg in arguments:
            if path in arg:
                return True
        return False

    def _insert_system_include(self, arguments: List[str], insert_pos: int, path: str) -> int:
        """Insert -isystem path at insert_pos and return updated position."""
        arguments.insert(insert_pos, "-isystem")
        arguments.insert(insert_pos + 1, path)
        return insert_pos + 2

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
        insert_pos = self._find_std_insert_position(result)

        cxx_stdlib_path = self._detect_cxx_stdlib_path(arguments)
        if cxx_stdlib_path and not self._is_path_in_args(cxx_stdlib_path, result):
            insert_pos = self._insert_system_include(result, insert_pos, cxx_stdlib_path)
            diagnostics.debug(f"Added C++ stdlib path: {cxx_stdlib_path}")

        if self.clang_resource_dir and not self._is_path_in_args(self.clang_resource_dir, result):
            self._insert_system_include(result, insert_pos, self.clang_resource_dir)
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
                    arguments = cmd["arguments"].copy()
                    directory = cmd["directory"]
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
            diagnostics.debug("Refreshed compile_commands.json cache")

        return success

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the compile commands manager."""
        with self.cache_lock:
            fallback_profile = self._extract_arg_insights(self.fallback_args)
            return {
                "enabled": self.enabled,
                "compile_commands_count": len(self.compile_commands),
                "file_mapping_count": len(self.file_to_command_map),
                "cache_enabled": self.cache_enabled,
                "fallback_enabled": self.fallback_to_hardcoded,
                "last_modified": self.last_modified,
                "compile_commands_path": str(self.project_root / self.compile_commands_path),
                "clang_resource_dir": self.clang_resource_dir,
                "fallback_cxx_standards": fallback_profile["cxx_standards"],
                "fallback_system_include_dirs": fallback_profile["system_include_dirs"],
            }

    def _extract_arg_insights(self, args: List[str]) -> Dict[str, List[str]]:
        """Extract concise diagnostics from compile arguments."""
        standards: List[str] = []
        system_includes: List[str] = []

        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("-std="):
                standards.append(arg[len("-std=") :])
            elif arg == "-std" and i + 1 < len(args):
                standards.append(args[i + 1])
                i += 1
            elif arg.startswith("-isystem="):
                system_includes.append(arg[len("-isystem=") :])
            elif arg == "-isystem" and i + 1 < len(args):
                system_includes.append(args[i + 1])
                i += 1
            i += 1

        # De-duplicate while preserving order
        unique_standards = list(dict.fromkeys(standards))
        unique_system_includes = list(dict.fromkeys(system_includes))
        return {
            "cxx_standards": unique_standards,
            "system_include_dirs": unique_system_includes,
        }

    def get_compile_arg_profile(self, file_path: Path) -> Dict[str, Any]:
        """Return compile argument profile for a specific source file."""
        compile_args = self.get_compile_args(file_path)
        if compile_args is not None:
            args_source = "compile_commands"
            final_args = compile_args
        elif self.fallback_to_hardcoded:
            args_source = "fallback"
            final_args = self.fallback_args.copy()
        else:
            args_source = "none"
            final_args = []

        insights = self._extract_arg_insights(final_args)
        return {
            "file": str(file_path),
            "args_source": args_source,
            "cxx_standards": insights["cxx_standards"],
            "system_include_dirs": insights["system_include_dirs"],
            "clang_resource_dir": self.clang_resource_dir,
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
