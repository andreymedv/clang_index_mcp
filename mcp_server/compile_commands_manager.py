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

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics


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
                diagnostics.info(f"compile_commands.json not found at: {compile_commands_file} - using fallback compilation arguments")
            else:
                diagnostics.warning(f"compile_commands.json not found at: {compile_commands_file} - fallback disabled")
            return False
        
        try:
            with open(compile_commands_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                diagnostics.error("compile_commands.json must contain a list of commands")
                return False

            # Parse and cache the commands
            self._parse_compile_commands(data)

            # Update last modified time
            self.last_modified = compile_commands_file.stat().st_mtime

            diagnostics.info(f"Successfully loaded {len(self.compile_commands)} compile commands from: {compile_commands_file}")
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

            return filtered_args

        except Exception as e:
            diagnostics.warning(f"Failed to parse command string '{command}': {e}")
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