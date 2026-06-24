"""
Compile Commands Manager for handling compile_commands.json files.

This module provides functionality to parse and cache compilation commands
from compile_commands.json files, enabling accurate C++ parsing with
project-specific build configurations.

The manager is now a thin orchestrator around focused helper modules:
- compile_commands_diff: change detection and argument hashing
- compile_commands_cache: cache path/hashing and pickle persistence
- resource_detector: clang resource dir and C++ stdlib detection
- compile_commands_parser: compilation database parsing and normalization
"""

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Handle both package and script imports
try:
    from ..cpp_analyzer_config import CompileCommandsConfig
    from .._core import diagnostics
    from .._core.argument_sanitizer import ArgumentSanitizer
except ImportError:
    from cpp_analyzer_config import CompileCommandsConfig  # type: ignore[no-redef]
    import diagnostics  # type: ignore[no-redef]
    from argument_sanitizer import ArgumentSanitizer  # type: ignore[no-redef]

from . import compile_commands_cache
from . import compile_commands_diff
from . import compile_commands_parser
from . import resource_detector

# Try to import orjson for faster JSON parsing (optional)
HAS_ORJSON = False
try:
    import orjson  # noqa: F401

    HAS_ORJSON = True
except ImportError:
    pass


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

    # ------------------------------------------------------------------
    # Compile-commands diff and argument-hash wrappers
    # ------------------------------------------------------------------
    @staticmethod
    def compute_commands_diff(
        old_commands: Dict[str, List[str]], new_commands: Dict[str, List[str]]
    ) -> Tuple[Set[str], Set[str], Set[str]]:
        """Compute difference between two compile-command maps."""
        return compile_commands_diff.compute_commands_diff(old_commands, new_commands)

    def _hash_args(self, args: List[str]) -> str:
        """Return a stable hash of a compilation argument list."""
        return compile_commands_diff.hash_args(args)

    def store_command_hashes(self, commands: Dict[str, List[str]]) -> int:
        """Store argument hashes for the given compile commands in SQLite."""
        return compile_commands_diff.store_command_hashes(commands, self.cache_backend)

    def get_stored_args_hash(self, file_path: str) -> str:
        """Return the stored argument hash for a file, or empty string."""
        return compile_commands_diff.get_stored_args_hash(file_path, self.cache_backend)

    def has_args_changed(self, file_path: str, current_args: List[str]) -> bool:
        """Return True if the stored argument hash differs from the current args."""
        return compile_commands_diff.has_args_changed(file_path, current_args, self.cache_backend)

    def clear_stored_command_hashes(self) -> int:
        """Clear all stored compilation argument hashes."""
        return compile_commands_diff.clear_stored_command_hashes(self.cache_backend)

    # ------------------------------------------------------------------
    # Cache path and persistence wrappers
    # ------------------------------------------------------------------
    def _get_compile_commands_cache_path(self) -> Path:
        """Get the cache file path for parsed compile commands."""
        return compile_commands_cache.get_compile_commands_cache_path(
            self.cache_dir, self.project_root, self.compile_commands_path
        )

    def _get_file_hash(self, file_path: Path) -> str:
        """Get MD5 hash of a file for cache validation."""
        return compile_commands_cache.get_file_hash(file_path)

    def _load_from_cache(self, compile_commands_file: Path) -> bool:
        """Try to load parsed commands from cache."""
        result = compile_commands_cache.load_from_cache(
            compile_commands_file, self.cache_dir, self.project_root, self.compile_commands_path
        )
        if result is None:
            return False
        self.compile_commands, self.file_to_command_map, self.last_modified = result
        return True

    def _save_to_cache(self, compile_commands_file: Path) -> None:
        """Save parsed commands to cache for faster loading next time."""
        compile_commands_cache.save_to_cache(
            compile_commands_file,
            self.cache_dir,
            self.project_root,
            self.compile_commands_path,
            self.compile_commands,
            self.file_to_command_map,
        )

    def get_compile_commands_hash(self) -> str:
        """Return the MD5 hash of compile_commands.json, or empty if unavailable."""
        return compile_commands_cache.get_compile_commands_hash(
            self.enabled, self.project_root, self.compile_commands_path
        )

    # ------------------------------------------------------------------
    # Resource detection wrappers
    # ------------------------------------------------------------------
    def _build_fallback_args(self) -> List[str]:
        """Build the fallback compilation arguments (current hardcoded approach)."""
        return resource_detector.build_fallback_args(self.project_root, self.clang_resource_dir)

    def _detect_clang_resource_dir(self) -> Optional[str]:
        """Detect the clang resource directory containing builtin headers."""
        return resource_detector.detect_clang_resource_dir()

    def _detect_cxx_stdlib_path(self, arguments: List[str]) -> Optional[str]:
        """Detect the C++ standard library include path based on compile arguments."""
        return resource_detector.detect_cxx_stdlib_path(arguments)

    def _detect_system_c_headers_dir(self) -> Optional[str]:
        """Detect the system C header directory for #include_next resolution."""
        return resource_detector.detect_system_c_headers_dir(self.clang_resource_dir)

    def _find_std_insert_position(self, arguments: List[str]) -> int:
        """Find insertion position after -std= flag if present."""
        return resource_detector.find_std_insert_position(arguments)

    def _is_path_in_args(self, path: str, arguments: List[str]) -> bool:
        """Check if a path is already present in arguments."""
        return resource_detector.is_path_in_args(path, arguments)

    def _insert_system_include(self, arguments: List[str], insert_pos: int, path: str) -> int:
        """Insert -isystem path at insert_pos and return updated position."""
        return resource_detector.insert_system_include(arguments, insert_pos, path)

    def _add_builtin_includes(self, arguments: List[str]) -> List[str]:
        """Add clang builtin include directory and C++ stdlib to arguments if needed."""
        return resource_detector.add_builtin_includes(arguments, self.clang_resource_dir)

    # ------------------------------------------------------------------
    # Compile commands parsing wrappers
    # ------------------------------------------------------------------
    def _load_compile_commands(self) -> bool:
        """Load compile commands from compile_commands.json file."""
        success, compile_commands, file_to_command_map, last_modified = (
            compile_commands_parser.load_compile_commands(
                self.enabled,
                self.project_root,
                self.compile_commands_path,
                self.fallback_to_hardcoded,
                self.cache_enabled,
                self.cache_dir,
                self.argument_sanitizer,
            )
        )
        if success:
            self.compile_commands = compile_commands
            self.file_to_command_map = file_to_command_map
            self.last_modified = last_modified
        return success

    def _filter_arguments(self, arguments: List[str]) -> List[str]:
        """Filter out compiler executable, -o, -c, and source files from arguments."""
        return compile_commands_parser.filter_arguments(arguments)

    def _normalize_path(self, file_path: str, directory: str) -> str:
        """Normalize file path to absolute path."""
        return compile_commands_parser.normalize_path(file_path, directory, self.project_root)

    def _normalize_single_argument(
        self, arg: str, next_arg: Optional[str], directory: str
    ) -> Tuple[List[str], int]:
        """Normalize a single argument and its optional successor."""
        return compile_commands_parser.normalize_single_argument(arg, next_arg, directory)

    def _normalize_arguments(self, arguments: List[str], directory: str) -> List[str]:
        """Normalize relative include paths in arguments to absolute paths."""
        return compile_commands_parser.normalize_arguments(arguments, directory)

    def _sanitize_args_for_libclang(self, args: List[str]) -> List[str]:
        """Sanitize compiler arguments for use with libclang using rule-based system."""
        return compile_commands_parser.sanitize_args_for_libclang(args, self.argument_sanitizer)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
