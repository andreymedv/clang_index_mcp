"""Configuration loader for C++ analyzer settings."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Handle both package and script imports
try:
    from .file_scanner import FileScanner
except ImportError:
    from file_scanner import FileScanner  # type: ignore[no-redef]

try:
    from . import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


class CppAnalyzerConfig:
    """Loads and manages configuration for the C++ analyzer."""

    DEFAULT_CONFIG = {
        "exclude_directories": [
            ".git",
            ".svn",
            ".hg",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".vs",
            ".vscode",
            ".idea",
            "CMakeFiles",
            "CMakeCache.txt",
        ],
        "dependency_directories": [
            "vcpkg_installed",
            "third_party",
            "ThirdParty",
            "external",
            "External",
            "vendor",
            "dependencies",
            "packages",
        ],
        "exclude_patterns": [],
        "include_dependencies": True,
        "max_file_size_mb": 10,
        "max_parse_retries": 2,  # Maximum number of times to retry parsing a failed file
        "max_workers": None,  # None = use cpu_count(), or specify integer for memory control
        "query_behavior": "allow_partial",  # allow_partial, block, or reject
        "diagnostics": {"level": "info", "enabled": True},  # debug, info, warning, error, fatal
    }

    def __init__(self, project_root: Path, config_path: Optional[Path] = None):
        self.project_root = project_root
        self.config_path = config_path  # Pre-specified config path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        config = self.DEFAULT_CONFIG.copy()

        if self.config_path:
            if not self.config_path.exists():
                diagnostics.warning(f"Specified config file not found: {self.config_path}")
                diagnostics.configure_from_config(config)
                return config

            try:
                with open(self.config_path, "r") as f:
                    user_config = json.load(f)

                # Validate that the config file contains a JSON object, not an array
                if not isinstance(user_config, dict):
                    diagnostics.error(f"Invalid config file format at {self.config_path}")
                    diagnostics.error(
                        f"Expected a JSON object (dict), but got {type(user_config).__name__}"
                    )
                    diagnostics.warning("Using default configuration")
                    return config

                # Merge with defaults (user config takes precedence)
                config.update(user_config)

                # Configure diagnostics system from config
                diagnostics.configure_from_config(config)

                diagnostics.debug(f"Configuration loaded from specified file: {self.config_path}")
                return config
            except Exception as e:
                diagnostics.error(f"Error loading config from {self.config_path}: {e}")
                diagnostics.warning("Using default configuration")
        else:
            # Configure diagnostics with defaults
            diagnostics.configure_from_config(config)
            diagnostics.debug("No config file provided, using defaults")

        return config

    def get_exclude_directories(self) -> List[str]:
        """Get list of directories to exclude."""
        result: List[str] = self.config.get(
            "exclude_directories", self.DEFAULT_CONFIG["exclude_directories"]
        )
        return result

    def get_dependency_directories(self) -> List[str]:
        """Get list of directories that contain dependencies."""
        result: List[str] = self.config.get(
            "dependency_directories", self.DEFAULT_CONFIG["dependency_directories"]
        )
        return result

    def get_exclude_patterns(self) -> List[str]:
        """Get list of file patterns to exclude."""
        result: List[str] = self.config.get(
            "exclude_patterns", self.DEFAULT_CONFIG["exclude_patterns"]
        )
        return result

    def get_include_dependencies(self) -> bool:
        """Get whether to include dependencies."""
        result: bool = self.config.get(
            "include_dependencies", self.DEFAULT_CONFIG["include_dependencies"]
        )
        return result

    def get_max_file_size_mb(self) -> float:
        """Get maximum file size in MB."""
        result: float = self.config.get("max_file_size_mb", self.DEFAULT_CONFIG["max_file_size_mb"])
        return result

    def get_max_workers(self) -> Optional[int]:
        """Get maximum number of worker processes for parallel indexing.

        Returns:
            None to use cpu_count() (default), or integer to limit workers.
            Limiting workers reduces memory usage (~1.2 GB per worker on large projects).
        """
        value = self.config.get("max_workers", self.DEFAULT_CONFIG["max_workers"])
        if value is None:
            return None
        if isinstance(value, int) and value > 0:
            return value
        diagnostics.warning(f"Invalid max_workers value: {value}. Using default (cpu_count).")
        return None

    def get_query_behavior_policy(self) -> str:
        """Get query behavior policy during indexing.

        Priority order:
        1. Environment variable CPP_ANALYZER_QUERY_BEHAVIOR
        2. Config file query_behavior setting
        3. Default: allow_partial

        Returns:
            Policy string: "allow_partial", "block", or "reject"
        """
        # Check environment variable first (highest priority)
        env_policy = os.environ.get("CPP_ANALYZER_QUERY_BEHAVIOR")
        if env_policy:
            policy = env_policy.lower()
            if policy in ["allow_partial", "block", "reject"]:
                diagnostics.debug(f"Using query behavior policy from env: {policy}")
                return policy
            else:
                diagnostics.warning(
                    f"Invalid CPP_ANALYZER_QUERY_BEHAVIOR value: {env_policy}. "
                    f"Using config/default value."
                )

        # Check config file
        policy = self.config.get("query_behavior", self.DEFAULT_CONFIG["query_behavior"])
        if policy not in ["allow_partial", "block", "reject"]:
            diagnostics.warning(
                f"Invalid query_behavior in config: {policy}. Using default: allow_partial"
            )
            return "allow_partial"

        result: str = policy
        return result

    def get_compile_commands_config(self) -> Dict[str, Any]:
        """Get compile commands configuration.

        Returns a dictionary with compile commands settings for CompileCommandsManager.
        """
        compile_commands = self.config.get("compile_commands", {})

        return {
            "compile_commands_enabled": compile_commands.get("enabled", True),
            "compile_commands_path": compile_commands.get("path", "compile_commands.json"),
            "compile_commands_cache_enabled": compile_commands.get("cache_enabled", True),
            "fallback_to_hardcoded": compile_commands.get("fallback_to_hardcoded", True),
            "cache_expiry_seconds": compile_commands.get("cache_expiry_seconds", 300),
            "supported_extensions": compile_commands.get(
                "supported_extensions", list(FileScanner.CPP_EXTENSIONS)
            ),
            "exclude_patterns": compile_commands.get("exclude_patterns", []),
        }

    def create_example_config(self, target_path: Path) -> Path:
        """Create an example configuration file at the specified path.

        Args:
            target_path: Absolute path to the file to be created.

        Returns:
            Path to the created config file
        """
        example_config = {
            "_comment": "C++ Analyzer configuration file",
            "project_root": ".",
            "exclude_directories": [
                ".git",
                ".svn",
                "node_modules",
                "build",
                "Build",
                "ThirdParty",
                "Intermediate",
                "Binaries",
                "DerivedDataCache",
            ],
            "exclude_patterns": ["*.generated.h", "*.generated.cpp", "*_test.cpp"],
            "dependency_directories": ["vcpkg_installed", "third_party", "external"],
            "include_dependencies": True,
            "max_file_size_mb": 10,
            "max_workers": None,
            "_max_workers_comment": "Set to integer (e.g., 8) to limit memory usage (~1.2 GB per worker)",
            "query_behavior": "allow_partial",
            "_query_behavior_options": [
                "allow_partial - Allow queries during indexing (results may be incomplete)",
                "block - Block queries until indexing completes (wait for completion)",
                "reject - Reject queries during indexing with error",
            ],
            "compile_commands": {
                "enabled": True,
                "path": "compile_commands.json",
                "cache_enabled": True,
                "fallback_to_hardcoded": True,
                "cache_expiry_seconds": 300,
            },
            "diagnostics": {"level": "info", "enabled": True},
        }

        # Write the config file
        with open(target_path, "w") as f:
            json.dump(example_config, f, indent=2)

        diagnostics.info(f"Created example config at: {target_path}")
        return target_path
