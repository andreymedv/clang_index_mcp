"""Configuration loader for C++ analyzer settings."""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional


class CppAnalyzerConfig:
    """Loads and manages configuration for the C++ analyzer."""
    
    CONFIG_FILENAME = "cpp-analyzer-config.json"
    
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
            "CMakeCache.txt"
        ],
        "dependency_directories": [
            "vcpkg_installed",
            "third_party",
            "ThirdParty",
            "external",
            "External",
            "vendor",
            "dependencies",
            "packages"
        ],
        "exclude_patterns": [],
        "include_dependencies": True,
        "max_file_size_mb": 10
    }
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config_path = None  # Will be set by _find_config_file
        self.config = self._load_config()

    def _get_user_config_dir(self) -> Path:
        """Get the user-specific config directory based on platform."""
        if os.name == 'nt':  # Windows
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        else:  # Linux, macOS
            base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        return base / 'cpp-analyzer'

    def _find_config_file(self) -> Optional[Path]:
        """Find config file by checking multiple locations in priority order.

        Priority order:
        1. Environment variable CPP_ANALYZER_CONFIG
        2. Project root (analyzed C++ project)
        3. User config directory (~/.config/cpp-analyzer/ or %APPDATA%/cpp-analyzer/)
        4. MCP server installation directory (for backward compatibility)

        Returns the first config file found, or None if not found.
        """
        # 1. Check environment variable
        env_config = os.environ.get('CPP_ANALYZER_CONFIG')
        if env_config:
            env_path = Path(env_config)
            if env_path.exists():
                return env_path
            else:
                print(f"Warning: CPP_ANALYZER_CONFIG points to non-existent file: {env_path}", file=os.sys.stderr)

        # 2. Check project root
        project_config = self.project_root / self.CONFIG_FILENAME
        if project_config.exists():
            return project_config

        # 3. Check user config directory
        user_config_dir = self._get_user_config_dir()
        user_config = user_config_dir / self.CONFIG_FILENAME
        if user_config.exists():
            return user_config

        # 4. Check MCP server installation directory (backward compatibility)
        mcp_server_root = Path(__file__).parent.parent
        package_config = mcp_server_root / self.CONFIG_FILENAME
        if package_config.exists():
            return package_config

        return None

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        config_file = self._find_config_file()

        if config_file:
            self.config_path = config_file
            try:
                with open(config_file, 'r') as f:
                    user_config = json.load(f)
                # Merge with defaults (user config takes precedence)
                config = self.DEFAULT_CONFIG.copy()
                config.update(user_config)
                print(f"Loaded config from: {config_file}", file=os.sys.stderr)
                return config
            except Exception as e:
                print(f"Error loading config from {config_file}: {e}", file=os.sys.stderr)
                print("Using default configuration", file=os.sys.stderr)
        else:
            print("No config file found, using defaults", file=os.sys.stderr)
            print(f"You can create a config file at one of these locations:", file=os.sys.stderr)
            print(f"  - Project: {self.project_root / self.CONFIG_FILENAME}", file=os.sys.stderr)
            print(f"  - User:    {self._get_user_config_dir() / self.CONFIG_FILENAME}", file=os.sys.stderr)
            print(f"  - Env var: CPP_ANALYZER_CONFIG=<path>", file=os.sys.stderr)

        return self.DEFAULT_CONFIG.copy()
    
    def get_exclude_directories(self) -> List[str]:
        """Get list of directories to exclude."""
        return self.config.get("exclude_directories", self.DEFAULT_CONFIG["exclude_directories"])
    
    def get_dependency_directories(self) -> List[str]:
        """Get list of directories that contain dependencies."""
        return self.config.get("dependency_directories", self.DEFAULT_CONFIG["dependency_directories"])
    
    def get_exclude_patterns(self) -> List[str]:
        """Get list of file patterns to exclude."""
        return self.config.get("exclude_patterns", self.DEFAULT_CONFIG["exclude_patterns"])
    
    def get_include_dependencies(self) -> bool:
        """Get whether to include dependencies."""
        return self.config.get("include_dependencies", self.DEFAULT_CONFIG["include_dependencies"])
    
    def get_max_file_size_mb(self) -> float:
        """Get maximum file size in MB."""
        return self.config.get("max_file_size_mb", self.DEFAULT_CONFIG["max_file_size_mb"])

    def get_compile_commands_config(self) -> Dict[str, Any]:
        """Get compile commands configuration.

        Returns a dictionary with compile commands settings for CompileCommandsManager.
        """
        compile_commands = self.config.get("compile_commands", {})

        return {
            'compile_commands_enabled': compile_commands.get('enabled', True),
            'compile_commands_path': compile_commands.get('path', 'compile_commands.json'),
            'compile_commands_cache_enabled': compile_commands.get('cache_enabled', True),
            'fallback_to_hardcoded': compile_commands.get('fallback_to_hardcoded', True),
            'cache_expiry_seconds': compile_commands.get('cache_expiry_seconds', 300),
            'supported_extensions': compile_commands.get('supported_extensions',
                [".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hxx", ".h++"]),
            'exclude_patterns': compile_commands.get('exclude_patterns', [])
        }
    
    def create_example_config(self, location: str = 'user') -> Path:
        """Create an example configuration file.

        Args:
            location: Where to create the config file:
                     'user' - User config directory (default)
                     'project' - Project root directory
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
                "DerivedDataCache"
            ],
            "exclude_patterns": [
                "*.generated.h",
                "*.generated.cpp",
                "*_test.cpp"
            ],
            "dependency_directories": [
                "vcpkg_installed",
                "third_party",
                "external"
            ],
            "include_dependencies": True,
            "max_file_size_mb": 10,
            "compile_commands": {
                "enabled": True,
                "path": "compile_commands.json",
                "cache_enabled": True,
                "fallback_to_hardcoded": True,
                "cache_expiry_seconds": 300
            }
        }

        # Determine target path
        if location == 'user':
            target_dir = self._get_user_config_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / self.CONFIG_FILENAME
        elif location == 'project':
            target_path = self.project_root / self.CONFIG_FILENAME
        else:  # 'path' or custom
            if self.config_path:
                target_path = self.config_path
            else:
                # Default to user config directory
                target_dir = self._get_user_config_dir()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / self.CONFIG_FILENAME

        # Write the config file
        with open(target_path, 'w') as f:
            json.dump(example_config, f, indent=2)

        print(f"Created example config at: {target_path}", file=os.sys.stderr)
        return target_path