"""Configuration loader for C++ analyzer settings."""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


class CppAnalyzerConfig:
    """Loads and manages configuration for the C++ analyzer."""

    CONFIG_FILENAME = ".cpp-analyzer-config.json"

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
        "query_behavior": "allow_partial",  # allow_partial, block, or reject
        "diagnostics": {"level": "info", "enabled": True},  # debug, info, warning, error, fatal
    }

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_path = None  # Will be set by _find_config_file
        self.config = self._load_config()

    def _find_config_file(self) -> Optional[Tuple[Path, str]]:
        """Find config file by checking multiple locations in priority order.

        Priority order:
        1. Environment variable CPP_ANALYZER_CONFIG
        2. Project root (.cpp-analyzer-config.json)

        Returns tuple of (config_path, source_description) or (None, None) if not found.
        """
        # 1. Check environment variable
        env_config = os.environ.get("CPP_ANALYZER_CONFIG")
        if env_config:
            env_path = Path(env_config)
            if env_path.exists():
                diagnostics.debug(f"Using config from CPP_ANALYZER_CONFIG: {env_path}")
                return (env_path, "environment variable CPP_ANALYZER_CONFIG")
            else:
                diagnostics.warning(f"CPP_ANALYZER_CONFIG points to non-existent file: {env_path}")

        # 2. Check project root
        project_config = self.project_root / self.CONFIG_FILENAME
        if project_config.exists():
            diagnostics.debug(f"Using config from project root: {project_config}")
            return (project_config, "project root directory")

        diagnostics.debug(
            f"No config file found. Checked: {project_config}, env var: {'set' if env_config else 'not set'}"
        )
        return (None, None)

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        config_file, config_source = self._find_config_file()

        config = self.DEFAULT_CONFIG.copy()

        if config_file:
            self.config_path = config_file
            try:
                with open(config_file, "r") as f:
                    user_config = json.load(f)

                # Validate that the config file contains a JSON object, not an array
                if not isinstance(user_config, dict):
                    diagnostics.error(f"Invalid config file format at {config_file}")
                    diagnostics.error(
                        f"Expected a JSON object (dict), but got {type(user_config).__name__}"
                    )
                    diagnostics.error(
                        f"Note: If you see 'compile_commands.json' here, you may have:"
                    )
                    diagnostics.error(
                        f"  1. Set CPP_ANALYZER_CONFIG environment variable to wrong file"
                    )
                    diagnostics.error(f"  2. Named .cpp-analyzer-config.json incorrectly")
                    diagnostics.warning("Using default configuration")
                    return config

                # Merge with defaults (user config takes precedence)
                config.update(user_config)

                # Configure diagnostics system from config
                diagnostics.configure_from_config(config)

                diagnostics.debug(f"Configuration loaded from {config_source}: {config_file}")
                return config
            except Exception as e:
                diagnostics.error(f"Error loading config from {config_file}: {e}")
                diagnostics.warning("Using default configuration")
        else:
            # Configure diagnostics with defaults
            diagnostics.configure_from_config(config)

            diagnostics.debug("No config file found, using defaults")
            diagnostics.debug(
                f"You can create a config file at: {self.project_root / self.CONFIG_FILENAME}"
            )

        return config

    def get_exclude_directories(self) -> List[str]:
        """Get list of directories to exclude."""
        return self.config.get("exclude_directories", self.DEFAULT_CONFIG["exclude_directories"])

    def get_dependency_directories(self) -> List[str]:
        """Get list of directories that contain dependencies."""
        return self.config.get(
            "dependency_directories", self.DEFAULT_CONFIG["dependency_directories"]
        )

    def get_exclude_patterns(self) -> List[str]:
        """Get list of file patterns to exclude."""
        return self.config.get("exclude_patterns", self.DEFAULT_CONFIG["exclude_patterns"])

    def get_include_dependencies(self) -> bool:
        """Get whether to include dependencies."""
        return self.config.get("include_dependencies", self.DEFAULT_CONFIG["include_dependencies"])

    def get_max_file_size_mb(self) -> float:
        """Get maximum file size in MB."""
        return self.config.get("max_file_size_mb", self.DEFAULT_CONFIG["max_file_size_mb"])

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

        return policy

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
                "supported_extensions",
                [".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"],
            ),
            "exclude_patterns": compile_commands.get("exclude_patterns", []),
        }

    def create_example_config(self, location: str = "project") -> Path:
        """Create an example configuration file.

        Args:
            location: Where to create the config file:
                     'project' - Project root directory (default)
                     'path' - Custom path (uses self.config_path if set)

        Returns:
            Path to the created config file
        """
        example_config = {
            "_comment": "C++ Analyzer configuration file",
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

        # Determine target path
        if location == "project":
            target_path = self.project_root / self.CONFIG_FILENAME
        elif location == "path":
            if self.config_path:
                target_path = self.config_path
            else:
                # Default to project root
                target_path = self.project_root / self.CONFIG_FILENAME
        else:
            raise ValueError(f"Invalid location: {location}. Use 'project' or 'path'.")

        # Write the config file
        with open(target_path, "w") as f:
            json.dump(example_config, f, indent=2)

        diagnostics.info(f"Created example config at: {target_path}")
        return target_path
