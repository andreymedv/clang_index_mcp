#!/usr/bin/env python3
"""
Tests for CompileCommandsManager class.

This module provides comprehensive tests for the compile_commands.json
integration functionality.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add the mcp_server directory to the path so we can import the modules
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_server'))

from compile_commands_manager import CompileCommandsManager


class TestCompileCommandsManager(unittest.TestCase):
    """Test cases for CompileCommandsManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.project_root = Path(self.test_dir)

        # Create a test compile_commands.json file
        self.compile_commands_data = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-Iinclude", "-I.", "-o", "main"],
                "command": "clang++ -std=c++17 -Iinclude -I. -o main src/main.cpp"
            },
            {
                "file": "src/utils.cpp", 
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-Iinclude", "-I.", "-c", "src/utils.cpp"],
                "command": "clang++ -std=c++17 -Iinclude -I. -c src/utils.cpp"
            },
            {
                "file": "tests/test_main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-Iinclude", "-I.", "-Itests", "-c", "tests/test_main.cpp"],
                "command": "clang++ -std=c++17 -Iinclude -I. -Itests -c tests/test_main.cpp"
            }
        ]
        
        self.compile_commands_file = self.project_root / "compile_commands.json"
        with open(self.compile_commands_file, 'w') as f:
            json.dump(self.compile_commands_data, f)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir)

    def assertHasIncludePath(self, args, path_suffix):
        """Helper to check if args contain an include path ending with path_suffix."""
        for i, arg in enumerate(args):
            # Handle -I<path> combined form
            if arg.startswith('-I'):
                include_path = arg[2:]  # Remove -I prefix
                if include_path.endswith(path_suffix) or include_path == path_suffix:
                    return
            # Handle -I <path> separated form
            if arg == '-I' and i + 1 < len(args):
                include_path = args[i + 1]
                if include_path.endswith(path_suffix) or include_path == path_suffix:
                    return
        self.fail(f"No include path ending with '{path_suffix}' found in args: {args}")

    def test_init_with_default_config(self):
        """Test initialization with default configuration."""
        manager = CompileCommandsManager(self.project_root)
        
        self.assertTrue(manager.enabled)
        self.assertEqual(manager.compile_commands_path, "compile_commands.json")
        self.assertTrue(manager.cache_enabled)
        self.assertTrue(manager.fallback_to_hardcoded)
        self.assertEqual(manager.cache_expiry_seconds, 300)
        self.assertIn(".cpp", manager.supported_extensions)
        self.assertEqual(len(manager.exclude_patterns), 0)
    
    def test_init_with_custom_config(self):
        """Test initialization with custom configuration."""
        config = {
            'compile_commands_enabled': False,
            'compile_commands_path': 'custom_compile_commands.json',
            'compile_commands_cache_enabled': False,
            'fallback_to_hardcoded': False,
            'cache_expiry_seconds': 600,
            'supported_extensions': ['.cpp', '.cxx'],
            'exclude_patterns': ['*/build/*', '*/tests/*']
        }
        
        manager = CompileCommandsManager(self.project_root, config)
        
        self.assertFalse(manager.enabled)
        self.assertEqual(manager.compile_commands_path, 'custom_compile_commands.json')
        self.assertFalse(manager.cache_enabled)
        self.assertFalse(manager.fallback_to_hardcoded)
        self.assertEqual(manager.cache_expiry_seconds, 600)
        self.assertEqual(manager.supported_extensions, {'.cpp', '.cxx'})
        self.assertEqual(manager.exclude_patterns, ['*/build/*', '*/tests/*'])
    
    def test_load_compile_commands_success(self):
        """Test successful loading of compile commands."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        self.assertTrue(manager.enabled)
        self.assertEqual(len(manager.compile_commands), 3)
        self.assertEqual(len(manager.file_to_command_map), 3)
        
        # Check that files are properly normalized
        main_cpp_file = str((self.project_root / "src" / "main.cpp").resolve())
        self.assertIn(main_cpp_file, manager.file_to_command_map)
        
        # Check that arguments are properly stored
        args = manager.file_to_command_map[main_cpp_file][0]['arguments']
        self.assertIn('-std=c++17', args)
        # Note: include paths are normalized to absolute paths
        self.assertHasIncludePath(args, 'include')
    
    def test_load_compile_commands_file_not_found(self):
        """Test behavior when compile_commands.json file is not found."""
        non_existent_dir = Path("/tmp/non_existent_dir")
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(non_existent_dir, config)
        
        self.assertFalse(manager.compile_commands)
        self.assertFalse(manager.file_to_command_map)
    
    def test_load_compile_commands_invalid_json(self):
        """Test behavior when compile_commands.json contains invalid JSON."""
        invalid_json_file = self.project_root / "invalid_compile_commands.json"
        with open(invalid_json_file, 'w') as f:
            f.write("invalid json content")
        
        config = {'compile_commands_enabled': True, 'compile_commands_path': 'invalid_compile_commands.json'}
        manager = CompileCommandsManager(self.project_root, config)
        
        self.assertFalse(manager.compile_commands)
        self.assertFalse(manager.file_to_command_map)
    
    def test_load_compile_commands_not_a_list(self):
        """Test behavior when compile_commands.json doesn't contain a list."""
        invalid_data_file = self.project_root / "invalid_data.json"
        with open(invalid_data_file, 'w') as f:
            json.dump({"key": "value"}, f)
        
        config = {'compile_commands_enabled': True, 'compile_commands_path': 'invalid_data.json'}
        manager = CompileCommandsManager(self.project_root, config)
        
        self.assertFalse(manager.compile_commands)
        self.assertFalse(manager.file_to_command_map)
    
    def test_load_compile_commands_missing_file_field(self):
        """Test behavior when commands are missing required 'file' field."""
        invalid_commands = [
            {"directory": "/some/dir", "arguments": ["-arg"]},
            {"file": "valid.cpp", "directory": "/some/dir", "arguments": ["-arg"]}
        ]
        
        invalid_file = self.project_root / "invalid_commands.json"
        with open(invalid_file, 'w') as f:
            json.dump(invalid_commands, f)
        
        config = {'compile_commands_enabled': True, 'compile_commands_path': 'invalid_commands.json'}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Should only load the valid command
        self.assertEqual(len(manager.compile_commands), 1)
        self.assertEqual(len(manager.file_to_command_map), 1)
    
    def test_normalize_path_absolute(self):
        """Test path normalization for absolute paths."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test absolute path
        abs_path = str((self.project_root / "src" / "main.cpp").resolve())
        normalized = manager._normalize_path(abs_path, str(self.project_root))
        self.assertEqual(normalized, abs_path)
    
    def test_normalize_path_relative_with_directory(self):
        """Test path normalization for relative paths with directory."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test relative path with directory
        rel_path = "src/main.cpp"
        directory = str(self.project_root)
        normalized = manager._normalize_path(rel_path, directory)
        
        expected = str((self.project_root / "src" / "main.cpp").resolve())
        self.assertEqual(normalized, expected)
    
    def test_normalize_path_relative_without_directory(self):
        """Test path normalization for relative paths without directory."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test relative path without directory
        rel_path = "src/main.cpp"
        normalized = manager._normalize_path(rel_path, "")
        
        expected = str((self.project_root / "src" / "main.cpp").resolve())
        self.assertEqual(normalized, expected)
    
    def test_parse_command_string(self):
        """Test parsing of command strings into arguments with filtering."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test simple command - should strip compiler, -c, and source file
        command = "clang++ -std=c++17 -Iinclude -c main.cpp"
        args = manager._parse_command_string(command)

        # Should keep compilation flags
        self.assertIn('-std=c++17', args)
        self.assertIn('-Iinclude', args)

        # Should strip compiler, -c flag, and source file
        self.assertNotIn('clang++', args)
        self.assertNotIn('-c', args)
        self.assertNotIn('main.cpp', args)
    
    def test_parse_command_string_with_quotes(self):
        """Test parsing of command strings with quoted arguments."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test command with quotes - quotes should be removed by shell parsing
        command = 'clang++ -std=c++17 -I"include/path" -D"DEFINE=value" -c main.cpp'
        args = manager._parse_command_string(command)

        self.assertIn('-std=c++17', args)
        # Quotes are removed by shlex.split() as per shell parsing rules
        self.assertIn('-Iinclude/path', args)
        self.assertIn('-DDEFINE=value', args)

        # Should strip compiler, -c flag, and source file
        self.assertNotIn('clang++', args)
        self.assertNotIn('-c', args)
        self.assertNotIn('main.cpp', args)
    
    def test_parse_command_string_invalid(self):
        """Test parsing of invalid command strings."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test invalid command (unbalanced quotes)
        command = 'clang++ -std=c++17 -I"include/path -c main.cpp'
        args = manager._parse_command_string(command)

        # Should return empty list for invalid command
        self.assertEqual(len(args), 0)

    def test_parse_command_string_strips_output_file(self):
        """Test that -o flag and output file are stripped."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test command with -o flag
        command = "/usr/bin/c++ -std=c++17 -DNDEBUG -I/path/include -o build/output.o -c src/main.cpp"
        args = manager._parse_command_string(command)

        # Should keep compilation flags
        self.assertIn('-std=c++17', args)
        self.assertIn('-DNDEBUG', args)
        self.assertIn('-I/path/include', args)

        # Should strip compiler path, -o flag, output file, -c flag, and source file
        self.assertNotIn('/usr/bin/c++', args)
        self.assertNotIn('-o', args)
        self.assertNotIn('build/output.o', args)
        self.assertNotIn('-c', args)
        self.assertNotIn('src/main.cpp', args)

    def test_parse_command_string_recognizes_compiler_paths(self):
        """Test that various compiler paths are recognized and stripped."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test different compiler paths
        # Note: CMake typically generates forward slashes even on Windows
        test_cases = [
            "/usr/bin/gcc -std=c11 -DTEST",
            "/Library/Developer/CommandLineTools/usr/bin/cc -std=c++17 -DTEST",
            '"C:\\Program Files\\LLVM\\bin\\clang++.exe" -std=c++17 -DTEST',  # Windows path with spaces (must be quoted)
            "C:/LLVM/bin/clang++.exe -std=c++17 -DTEST",  # Windows path with forward slashes (CMake style)
            "gcc -std=c11 -DTEST",
            "g++ -std=c++17 -DTEST",
            "clang -std=c11 -DTEST",
            "clang++ -std=c++17 -DTEST",
        ]

        for command in test_cases:
            args = manager._parse_command_string(command)

            # Should keep flags
            self.assertIn('-DTEST', args, f"Failed for command: {command}")

            # Should not start with compiler name or path
            if len(args) > 0:
                first_arg = args[0]
                self.assertTrue(first_arg.startswith('-'),
                              f"First arg should be a flag, got: {first_arg} for command: {command}")

    def test_get_compile_args_success(self):
        """Test successful retrieval of compile arguments."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        file_path = self.project_root / "src" / "main.cpp"
        args = manager.get_compile_args(file_path)

        self.assertIsNotNone(args)
        self.assertIn('-std=c++17', args)
        self.assertHasIncludePath(args, 'include')
    
    def test_get_compile_args_file_not_found(self):
        """Test retrieval of compile arguments for non-existent file."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "non_existent.cpp"
        args = manager.get_compile_args(file_path)
        
        self.assertIsNone(args)
    
    def test_get_compile_args_with_fallback_success(self):
        """Test get_compile_args_with_fallback when compile commands are available."""
        config = {'compile_commands_enabled': True, 'fallback_to_hardcoded': True}
        manager = CompileCommandsManager(self.project_root, config)

        file_path = self.project_root / "src" / "main.cpp"
        args = manager.get_compile_args_with_fallback(file_path)

        # Should return compile commands, not fallback args
        self.assertIn('-std=c++17', args)
        self.assertHasIncludePath(args, 'include')
        # Should not contain fallback-specific args
        self.assertNotIn('-DNOMINMAX', args)
    
    def test_get_compile_args_with_fallback_no_compile_commands(self):
        """Test get_compile_args_with_fallback when no compile commands are available."""
        config = {'compile_commands_enabled': False, 'fallback_to_hardcoded': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "src" / "main.cpp"
        args = manager.get_compile_args_with_fallback(file_path)
        
        # Should return fallback args
        self.assertIn('-std=c++17', args)
        self.assertIn('-DNOMINMAX', args)
        # Should not contain compile command specific args
        self.assertNotIn('-Iinclude', args)
    
    def test_get_compile_args_with_fallback_fallback_disabled(self):
        """Test get_compile_args_with_fallback when fallback is disabled."""
        config = {'compile_commands_enabled': False, 'fallback_to_hardcoded': False}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "src" / "main.cpp"
        args = manager.get_compile_args_with_fallback(file_path)
        
        # Should return empty list
        self.assertEqual(args, [])
    
    def test_refresh_if_needed_success(self):
        """Test successful refresh of compile commands."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Modify the compile_commands.json file
        new_data = [
            {
                "file": "src/new_file.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++20", "-Inew_include"],
                "command": "clang++ -std=c++20 -Inew_include src/new_file.cpp"
            }
        ]
        
        with open(self.compile_commands_file, 'w') as f:
            json.dump(new_data, f)
        
        # Wait a bit to ensure different modification time
        import time
        time.sleep(0.1)
        
        result = manager.refresh_if_needed()
        
        self.assertTrue(result)
        self.assertEqual(len(manager.compile_commands), 1)
        self.assertIn('src/new_file.cpp', str(manager.file_to_command_map))
    
    def test_refresh_if_needed_no_changes(self):
        """Test refresh when no changes are detected."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        original_count = len(manager.compile_commands)
        
        # Refresh without changes
        result = manager.refresh_if_needed()
        
        self.assertFalse(result)
        self.assertEqual(len(manager.compile_commands), original_count)
    
    def test_refresh_if_needed_file_not_found(self):
        """Test refresh when compile_commands.json file is not found."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Remove the compile_commands.json file
        self.compile_commands_file.unlink()
        
        result = manager.refresh_if_needed()
        
        self.assertFalse(result)
        self.assertFalse(manager.compile_commands)
    
    def test_get_stats(self):
        """Test retrieval of statistics."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        stats = manager.get_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertEqual(stats['enabled'], True)
        self.assertEqual(stats['compile_commands_count'], 3)
        self.assertEqual(stats['file_mapping_count'], 3)
        self.assertEqual(stats['cache_enabled'], True)
        self.assertEqual(stats['fallback_enabled'], True)
        self.assertIn('compile_commands_path', stats)
    
    def test_is_file_supported(self):
        """Test file support checking."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        supported_file = self.project_root / "src" / "main.cpp"
        unsupported_file = self.project_root / "unsupported.txt"
        
        self.assertTrue(manager.is_file_supported(supported_file))
        self.assertFalse(manager.is_file_supported(unsupported_file))
    
    def test_is_file_supported_disabled(self):
        """Test file support checking when compile commands are disabled."""
        config = {'compile_commands_enabled': False}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "src" / "main.cpp"
        
        self.assertFalse(manager.is_file_supported(file_path))
    
    def test_get_all_files(self):
        """Test retrieval of all files with compile commands."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        files = manager.get_all_files()
        
        self.assertEqual(len(files), 3)
        self.assertIn(str((self.project_root / "src" / "main.cpp").resolve()), files)
        self.assertIn(str((self.project_root / "src" / "utils.cpp").resolve()), files)
        self.assertIn(str((self.project_root / "tests" / "test_main.cpp").resolve()), files)
    
    def test_get_all_files_disabled(self):
        """Test retrieval of all files when compile commands are disabled."""
        config = {'compile_commands_enabled': False}
        manager = CompileCommandsManager(self.project_root, config)
        
        files = manager.get_all_files()
        
        self.assertEqual(len(files), 0)
    
    def test_should_process_file_with_compile_commands(self):
        """Test should_process_file when compile commands are available."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "src" / "main.cpp"
        
        self.assertTrue(manager.should_process_file(file_path))
    
    def test_should_process_file_without_compile_commands_but_supported_extension(self):
        """Test should_process_file when no compile commands but supported extension."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Remove compile commands for this file
        file_path = self.project_root / "new_file.cpp"
        
        self.assertTrue(manager.should_process_file(file_path))
    
    def test_should_process_file_unsupported_extension(self):
        """Test should_process_file with unsupported extension."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        file_path = self.project_root / "document.txt"
        
        self.assertFalse(manager.should_process_file(file_path))
    
    def test_is_extension_supported(self):
        """Test extension support checking."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        supported_extensions = ['.cpp', '.h', '.hpp', '.cc', '.cxx']
        unsupported_extensions = ['.txt', '.py', '.md']
        
        for ext in supported_extensions:
            file_path = self.project_root / f"test{ext}"
            self.assertTrue(manager.is_extension_supported(file_path))
        
        for ext in unsupported_extensions:
            file_path = self.project_root / f"test{ext}"
            self.assertFalse(manager.is_extension_supported(file_path))
    
    def test_clear_cache(self):
        """Test cache clearing."""
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Ensure cache has data
        self.assertTrue(len(manager.compile_commands) > 0)
        
        # Clear cache
        manager.clear_cache()
        
        # Check that cache is empty
        self.assertEqual(len(manager.compile_commands), 0)
        self.assertEqual(len(manager.file_to_command_map), 0)
        self.assertEqual(manager.last_modified, 0)
    
    def test_fallback_args_windows(self):
        """Test fallback arguments generation on Windows."""
        with patch('sys.platform', 'win32'):
            with patch('glob.glob') as mock_glob:
                mock_glob.return_value = ['C:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/ucrt']
                
                config = {'compile_commands_enabled': False}
                manager = CompileCommandsManager(self.project_root, config)
                
                args = manager.fallback_args
                
                self.assertIn('-std=c++17', args)
                self.assertIn('-I.', args)
                self.assertIn('-DNOMINMAX', args)
                self.assertIn('-DWIN32', args)
                self.assertIn('-D_WIN32', args)
                self.assertIn('-D_WINDOWS', args)
                # Should include Windows SDK include
                self.assertIn('-IC:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/ucrt', args)
    
    def test_fallback_args_linux(self):
        """Test fallback arguments generation on Linux."""
        with patch('sys.platform', 'linux'):
            config = {'compile_commands_enabled': False}
            manager = CompileCommandsManager(self.project_root, config)
            
            args = manager.fallback_args
            
            self.assertIn('-std=c++17', args)
            self.assertIn('-I.', args)
            self.assertIn('-DNOMINMAX', args)
            self.assertIn('-DWIN32', args)  # These should still be included for compatibility
            self.assertNotIn('-IC:/Program Files', args)  # No Windows-specific paths


class TestCompileCommandsManagerIntegration(unittest.TestCase):
    """Integration tests for CompileCommandsManager with real scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.project_root = Path(self.test_dir)
        
        # Create a realistic project structure
        (self.project_root / "src").mkdir()
        (self.project_root / "include").mkdir()
        (self.project_root / "tests").mkdir()
        
        # Create source files
        (self.project_root / "src" / "main.cpp").write_text("""
#include "utils.h"
#include <iostream>

int main() {
    std::cout << Hello World << std::endl;
    return 0;
}
""")
        
        (self.project_root / "src" / "utils.cpp").write_text("""
#include "utils.h"
#include <string>

std::string get_message() {
    return "Hello World";
}
""")
        
        (self.project_root / "include" / "utils.h").write_text("""
#pragma once
#include <string>

std::string get_message();
""")
        
        (self.project_root / "tests" / "test_utils.cpp").write_text("""
#include "utils.h"
#include <cassert>

int main() {
    std::string msg = get_message();
    assert(msg == "Hello World");
    return 0;
}
""")
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir)

    def assertHasIncludePath(self, args, path_suffix):
        """Helper to check if args contain an include path ending with path_suffix."""
        for i, arg in enumerate(args):
            # Handle -I<path> combined form
            if arg.startswith('-I'):
                include_path = arg[2:]  # Remove -I prefix
                if include_path.endswith(path_suffix) or include_path == path_suffix:
                    return
            # Handle -I <path> separated form
            if arg == '-I' and i + 1 < len(args):
                include_path = args[i + 1]
                if include_path.endswith(path_suffix) or include_path == path_suffix:
                    return
        self.fail(f"No include path ending with '{path_suffix}' found in args: {args}")

    def test_realistic_project_setup(self):
        """Test with a realistic project structure and compile_commands.json."""
        # Create a realistic compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": [
                    "-std=c++17",
                    "-I", "include",
                    "-I", ".",
                    "-Wall",
                    "-Wextra",
                    "-o", "main"
                ],
                "command": f"clang++ -std=c++17 -I include -I . -Wall -Wextra -o main src/main.cpp"
            },
            {
                "file": "src/utils.cpp",
                "directory": str(self.project_root),
                "arguments": [
                    "-std=c++17",
                    "-I", "include",
                    "-I", ".",
                    "-Wall",
                    "-Wextra",
                    "-c", "src/utils.cpp",
                    "-o", "utils.o"
                ],
                "command": f"clang++ -std=c++17 -I include -I . -Wall -Wextra -c src/utils.cpp -o utils.o"
            },
            {
                "file": "tests/test_utils.cpp",
                "directory": str(self.project_root),
                "arguments": [
                    "-std=c++17",
                    "-I", "include",
                    "-I", ".",
                    "-I", "tests",
                    "-Wall",
                    "-Wextra",
                    "-c", "tests/test_utils.cpp",
                    "-o", "test_utils.o"
                ],
                "command": f"clang++ -std=c++17 -I include -I . -I tests -Wall -Wextra -c tests/test_utils.cpp -o test_utils.o"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Test the manager
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Verify all files are found
        self.assertEqual(len(manager.compile_commands), 3)
        self.assertEqual(len(manager.file_to_command_map), 3)
        
        # Test argument retrieval for each file
        main_args = manager.get_compile_args(self.project_root / "src" / "main.cpp")
        utils_args = manager.get_compile_args(self.project_root / "src" / "utils.cpp")
        test_args = manager.get_compile_args(self.project_root / "tests" / "test_utils.cpp")
        
        self.assertIsNotNone(main_args)
        self.assertIsNotNone(utils_args)
        self.assertIsNotNone(test_args)
        
        # Verify specific arguments
        self.assertIn('-std=c++17', main_args)
        self.assertHasIncludePath(main_args, 'include')
        self.assertIn('-Wall', main_args)
        self.assertIn('-Wextra', main_args)
        
        # Test file processing decisions
        self.assertTrue(manager.should_process_file(self.project_root / "src" / "main.cpp"))
        self.assertTrue(manager.should_process_file(self.project_root / "src" / "utils.cpp"))
        self.assertTrue(manager.should_process_file(self.project_root / "tests" / "test_utils.cpp"))
        self.assertFalse(manager.should_process_file(self.project_root / "README.md"))
    
    def test_caching_behavior(self):
        """Test caching behavior with file modifications."""
        # Create initial compile_commands.json
        initial_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(initial_commands, f)
        
        # Initialize manager
        config = {'compile_commands_enabled': True, 'cache_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Verify initial load
        self.assertEqual(len(manager.compile_commands), 1)
        
        # Modify the file
        import time
        time.sleep(0.1)  # Ensure different modification time
        
        updated_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++20", "-I", "include", "-I", "new_include"],
                "command": "clang++ -std=c++20 -I include -I new_include src/main.cpp"
            }
        ]
        
        with open(compile_commands_file, 'w') as f:
            json.dump(updated_commands, f)
        
        # Test refresh
        result = manager.refresh_if_needed()
        self.assertTrue(result)
        
        # Verify updated arguments
        args = manager.get_compile_args(self.project_root / "src" / "main.cpp")
        self.assertIn('-std=c++20', args)
        self.assertHasIncludePath(args, 'new_include')
        self.assertNotIn('-std=c++17', args)

    def test_custom_compile_commands_path_in_subdirectory(self):
        """Test loading compile_commands.json from a custom subdirectory path."""
        # Create a build subdirectory
        build_dir = self.project_root / "build"
        build_dir.mkdir(exist_ok=True)

        # Create compile_commands.json in the build directory
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++20", "-I", "include", "-DCUSTOM_BUILD"],
                "command": "clang++ -std=c++20 -I include -DCUSTOM_BUILD src/main.cpp"
            },
            {
                "file": "src/utils.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++20", "-I", "include", "-DCUSTOM_BUILD"],
                "command": "clang++ -std=c++20 -I include -DCUSTOM_BUILD src/utils.cpp"
            }
        ]

        custom_compile_commands_file = build_dir / "compile_commands.json"
        with open(custom_compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)

        # Configure manager to use custom path
        config = {
            'compile_commands_enabled': True,
            'compile_commands_path': 'build/compile_commands.json'
        }
        manager = CompileCommandsManager(self.project_root, config)

        # Verify it loaded the custom compile commands
        self.assertTrue(manager.enabled)
        self.assertEqual(len(manager.compile_commands), 2)

        # Verify we can get compile args from the custom location
        args = manager.get_compile_args(self.project_root / "src" / "main.cpp")
        self.assertIsNotNone(args)
        self.assertIn('-std=c++20', args)
        self.assertIn('-DCUSTOM_BUILD', args)

        # Verify file mapping works correctly
        main_cpp_path = str((self.project_root / "src" / "main.cpp").resolve())
        self.assertIn(main_cpp_path, manager.file_to_command_map)

    def test_custom_compile_commands_absolute_path(self):
        """Test loading compile_commands.json from an absolute path."""
        # Create a temporary directory outside the project
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create compile_commands.json in the temporary directory
            compile_commands = [
                {
                    "file": str(self.project_root / "src" / "main.cpp"),
                    "directory": str(self.project_root),
                    "arguments": ["-std=c++17", "-I", "include", "-DEXTERNAL_BUILD"],
                    "command": "clang++ -std=c++17 -I include -DEXTERNAL_BUILD src/main.cpp"
                }
            ]

            absolute_compile_commands_file = temp_path / "compile_commands.json"
            with open(absolute_compile_commands_file, 'w') as f:
                json.dump(compile_commands, f)

            # Configure manager to use absolute path
            config = {
                'compile_commands_enabled': True,
                'compile_commands_path': str(absolute_compile_commands_file)
            }
            manager = CompileCommandsManager(self.project_root, config)

            # Verify it loaded the compile commands
            self.assertTrue(manager.enabled)
            self.assertEqual(len(manager.compile_commands), 1)

            # Verify compile args
            args = manager.get_compile_args(self.project_root / "src" / "main.cpp")
            self.assertIsNotNone(args)
            self.assertIn('-DEXTERNAL_BUILD', args)


if __name__ == '__main__':
    unittest.main()