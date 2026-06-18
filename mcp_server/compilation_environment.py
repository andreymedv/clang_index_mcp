"""
Compilation environment management — extracted from CppAnalyzer.

Handles file discovery, compile commands, file scanning,
and compilation argument resolution.
"""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from . import diagnostics
from .compile_commands_manager import CompileCommandsManager
from .file_scanner import FileScanner


class CompilationEnvironment:
    """
    Manages compilation environment: file discovery, compile commands,
    file scanning, and compilation argument resolution.
    """

    def __init__(self, analyzer: Any):
        """
        Initialize CompilationEnvironment.

        Args:
            analyzer: Reference to the CppAnalyzer instance for access to
                      project_root, config, cache_manager, and symbol_store.
        """
        self.analyzer = analyzer

        # File scanner
        self.file_scanner = FileScanner(analyzer.project_root)
        self.file_scanner.EXCLUDE_DIRS = set(analyzer.config.get_exclude_directories())
        self.file_scanner.DEPENDENCY_DIRS = set(analyzer.config.get_dependency_directories())

        # Compile commands manager (initialized later by CppAnalyzer)
        self.compile_commands_manager: Optional[CompileCommandsManager] = None

        # Configuration
        self.include_dependencies = analyzer.config.get_include_dependencies()
        self.max_parse_retries = analyzer.config.config.get("max_parse_retries", 2)

        # Precomputed compile args for worker mode
        self._provided_compile_args = None

    def _is_project_file(self, file_path: str) -> bool:
        """
        Check if a file is a project file (not system header or external dependency).

        Uses FileScanner.is_project_file() to determine if the file is:
        - Under the project root
        - NOT in excluded directories (e.g., build/, .git/)
        - NOT in dependency directories (e.g., vcpkg_installed/, third_party/)

        Args:
            file_path: Absolute or relative path to check

        Returns:
            True if file is a project file, False otherwise

        Implements:
            REQ-10.1.3: Distinguish between project headers, system headers, and external
            REQ-10.1.4: Extract symbols only from project headers
        """
        if not file_path:
            return False

        # Convert to absolute path
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        # Use FileScanner's logic to check if it's a project file
        return self.file_scanner.is_project_file(file_path)

    def _compute_compile_args_hash(self, args: List[str]) -> str:
        """Compute hash of compilation arguments for cache validation"""
        # Sort and join args to create a consistent hash
        args_str = " ".join(sorted(args))
        return hashlib.md5(args_str.encode()).hexdigest()

    def _should_skip_file(self, file_path: str) -> bool:
        """Check if file should be skipped"""
        # Update file scanner with current dependencies setting
        self.file_scanner.include_dependencies = self.include_dependencies
        return self.file_scanner.should_skip_file(file_path)

    def _find_cpp_files(self, include_dependencies: bool = False) -> List[str]:
        """Find all C++ files in the project

        When compile_commands.json is loaded and has entries, returns ONLY the files
        listed in it. Otherwise, scans for all C++ files based on extensions.
        """
        # If compile_commands.json is loaded and has entries, use only those files
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is not None and self.compile_commands_manager.enabled:
            compile_commands_files = self.compile_commands_manager.get_all_files()
            if compile_commands_files:
                diagnostics.debug(
                    f"Using {len(compile_commands_files)} files from compile_commands.json"
                )
                return compile_commands_files

        # Fall back to scanning all C++ files
        # Update file scanner with dependencies setting
        self.file_scanner.include_dependencies = include_dependencies
        return self.file_scanner.find_cpp_files()

    def _get_compile_args_for_file(self, file_path_obj: Path) -> List[str]:
        """Get compilation arguments for a file, handling worker and fallback modes."""
        if self._provided_compile_args is not None:
            # Worker mode: use compile args provided by main process
            return self._provided_compile_args

        # Main process mode: query CompileCommandsManager
        assert self.compile_commands_manager is not None
        args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)

        # If compile commands are not available and we're using fallback, add vcpkg includes
        if not self.compile_commands_manager.is_file_supported(file_path_obj):
            # Add vcpkg includes if available
            vcpkg_include = (
                self.analyzer.project_root / "vcpkg_installed" / "x64-windows" / "include"
            )
            if vcpkg_include.exists():
                args.append(f"-I{vcpkg_include}")

            # Add common vcpkg paths
            vcpkg_paths = [
                "C:/vcpkg/installed/x64-windows/include",
                "C:/dev/vcpkg/installed/x64-windows/include",
            ]
            for path in vcpkg_paths:
                if Path(path).exists():
                    args.append(f"-I{path}")
                    break
        return args

    def _prepare_worker_compile_args(self, files: List[str]) -> Dict[str, List[str]]:
        """Pre-calculate compile arguments for each file to save worker memory."""
        file_compile_args = {}
        assert self.compile_commands_manager is not None
        vcpkg_include = self.analyzer.project_root / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_paths = [
            "C:/vcpkg/installed/x64-windows/include",
            "C:/dev/vcpkg/installed/x64-windows/include",
        ]

        for file_path in files:
            file_path_obj = Path(file_path)
            args = self.compile_commands_manager.get_compile_args_with_fallback(file_path_obj)

            if not self.compile_commands_manager.is_file_supported(file_path_obj):
                if vcpkg_include.exists():
                    args.append(f"-I{vcpkg_include}")
                for path in vcpkg_paths:
                    if Path(path).exists():
                        args.append(f"-I{path}")
                        break
            file_compile_args[file_path] = args
        return file_compile_args

    def get_compile_commands_stats(self) -> Dict[str, Any]:
        """Get compile commands statistics"""
        # Task 3.2: Skip if CompileCommandsManager not initialized (worker mode)
        if self.compile_commands_manager is None or not self.compile_commands_manager.enabled:
            return {"enabled": False}

        return self.compile_commands_manager.get_stats()

    def _log_compilation_environment(self, files: List[str]) -> None:
        """Log libclang compilation environment for diagnostics."""
        if self.compile_commands_manager is None:
            return

        compile_stats = self.compile_commands_manager.get_stats()
        diagnostics.info(
            "Compilation environment: "
            f"compile_commands_enabled={compile_stats.get('enabled')} "
            f"compile_commands_count={compile_stats.get('compile_commands_count')} "
            f"clang_resource_dir={compile_stats.get('clang_resource_dir')} "
            f"fallback_cxx_standards={compile_stats.get('fallback_cxx_standards')} "
            f"fallback_system_include_dirs={compile_stats.get('fallback_system_include_dirs')}"
        )

        if not files:
            return

        sample_count = min(3, len(files))
        for source_file in files[:sample_count]:
            profile = self.compile_commands_manager.get_compile_arg_profile(Path(source_file))
            diagnostics.info(
                "Compile args profile: "
                f"file={profile.get('file')} "
                f"source={profile.get('args_source')} "
                f"cxx_standards={profile.get('cxx_standards')} "
                f"system_include_dirs={profile.get('system_include_dirs')}"
            )

    def _handle_deleted_files(self, current_files: Set[str]) -> int:
        """Find and remove deleted files from indexes."""
        tracked_files = set(self.analyzer.symbol_store.file_hashes.keys())
        deleted_files = set()
        for tracked_file in tracked_files:
            if tracked_file in current_files:
                continue

            if tracked_file.endswith((".h", ".hpp", ".hxx", ".h++")):
                if not os.path.exists(tracked_file):
                    deleted_files.add(tracked_file)
            else:
                deleted_files.add(tracked_file)

        deleted_count = 0
        for file_path in deleted_files:
            self.analyzer.symbol_store._remove_file_from_indexes(file_path)
            if file_path in self.analyzer.symbol_store.file_hashes:
                del self.analyzer.symbol_store.file_hashes[file_path]
            self.analyzer.cache_manager.remove_file_cache(file_path)
            deleted_count += 1
        return deleted_count

    def _identify_refresh_files(self, current_files: Set[str]) -> Tuple[List[str], List[str]]:
        """Identify modified and new files needing refresh."""
        tracked_files = set(self.analyzer.symbol_store.file_hashes.keys())
        new_files = list(current_files - tracked_files)
        modified_files = []
        for file_path in self.analyzer.symbol_store.file_hashes:
            if not os.path.exists(file_path):
                continue
            if self.analyzer.cache_manager.get_file_hash(
                file_path
            ) != self.analyzer.symbol_store.file_hashes.get(file_path):
                modified_files.append(file_path)
        return modified_files, new_files

    def _prepare_refresh_compile_args(
        self, all_files_to_process: List[str]
    ) -> Dict[str, List[str]]:
        """Prepare compilation arguments for all files in main process."""
        file_compile_args = {}
        for file_path in all_files_to_process:
            file_path_obj = Path(file_path)
            file_compile_args[file_path] = self._get_compile_args_for_file(file_path_obj)
        return file_compile_args
