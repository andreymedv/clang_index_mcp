"""
Compile Commands Manager for handling compile_commands.json files.

This module provides functionality to parse and cache compilation commands
from compile_commands.json files, enabling accurate C++ parsing with
project-specific build configurations.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import time
import threading
from collections import defaultdict


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
        
        # Default fallback arguments (current hardcoded approach)
        self.fallback_args = self._build_fallback_args()
        
        # Load compile commands if enabled
        if self.enabled:
            self._load_compile_commands()
    
    def _build_fallback_args(self) -> List[str]:
        """Build the fallback compilation arguments (current hardcoded approach)."""
        args = [
            '-std=c++17',
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
        ]
        
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
    
    def _load_compile_commands(self) -> bool:
        """Load compile commands from compile_commands.json file."""
        if not self.enabled:
            return False

        compile_commands_file = self.project_root / self.compile_commands_path

        if not compile_commands_file.exists():
            if self.fallback_to_hardcoded:
                print(f"compile_commands.json not found at: {compile_commands_file} - using fallback compilation arguments", file=sys.stderr)
            else:
                print(f"compile_commands.json not found at: {compile_commands_file} - fallback disabled", file=sys.stderr)
            return False
        
        try:
            with open(compile_commands_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                print("Error: compile_commands.json must contain a list of commands", file=sys.stderr)
                return False
            
            # Parse and cache the commands
            self._parse_compile_commands(data)

            # Update last modified time
            self.last_modified = compile_commands_file.stat().st_mtime

            print(f"Successfully loaded {len(self.compile_commands)} compile commands from: {compile_commands_file}", file=sys.stderr)
            print(f"Compile commands will be used for accurate C++ parsing", file=sys.stderr)
            return True
            
        except json.JSONDecodeError as e:
            print(f"Error parsing compile_commands.json: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Error loading compile_commands.json: {e}", file=sys.stderr)
            return False
    
    def _parse_compile_commands(self, commands: List[Dict[str, Any]]) -> None:
        """Parse compile commands and build file-to-command mapping."""
        self.compile_commands.clear()
        self.file_to_command_map.clear()
        
        for i, cmd in enumerate(commands):
            if not isinstance(cmd, dict):
                print(f"Warning: Skipping invalid command at index {i}", file=sys.stderr)
                continue
            
            # Extract required fields
            if 'file' not in cmd:
                print(f"Warning: Skipping command without 'file' field at index {i}", file=sys.stderr)
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
    
    def _parse_command_string(self, command: str) -> List[str]:
        """Parse command string into arguments list."""
        import shlex
        
        try:
            # Handle quoted arguments properly
            args = shlex.split(command)
            
            # Filter out empty strings and ensure proper formatting
            return [arg for arg in args if arg.strip()]
        except Exception as e:
            print(f"Warning: Failed to parse command string '{command}': {e}", file=sys.stderr)
            return []
    
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
                    return commands[-1]['arguments'].copy()

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
            print("Refreshed compile_commands.json cache", file=sys.stderr)
        
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