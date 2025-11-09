#!/usr/bin/env python3
"""
Integration tests for CppAnalyzer with compile_commands.json support.

This module tests the integration between CppAnalyzer and CompileCommandsManager.
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

# Import CompileCommandsManager directly to avoid relative import issues
from compile_commands_manager import CompileCommandsManager


class TestCompileCommandsManagerIntegration(unittest.TestCase):
    """Integration tests for CompileCommandsManager with realistic scenarios."""
    
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
    std::cout << get_message() << std::endl;
    return 0;
}
""")
        
        (self.project_root / "src" / "utils.cpp").write_text("""
#include "utils.h"
#include <string>

std::string get_message() {
    return "Hello World";
}

void helper_function() {
    // This is a helper function
}
""")
        
        (self.project_root / "include" / "utils.h").write_text("""
#pragma once
#include <string>

std::string get_message();
void helper_function();
""")
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir)
    
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
        self.assertIn('-I', main_args)
        self.assertIn('include', main_args)
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
        self.assertIn('-I', args)
        self.assertIn('new_include', args)
        self.assertNotIn('-std=c++17', args)
    
    def test_fallback_behavior(self):
        """Test fallback behavior when compile_commands.json is removed."""
        # First create compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create manager and test initial state
        config = {'compile_commands_enabled': True, 'fallback_to_hardcoded': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test initial compile args
        initial_args = manager.get_compile_args(self.project_root / "src" / "main.cpp")
        self.assertIsNotNone(initial_args)
        self.assertIn('-std=c++17', initial_args)
        
        # Remove compile_commands.json
        compile_commands_file.unlink()
        
        # Test fallback behavior
        fallback_args = manager.get_compile_args_with_fallback(self.project_root / "src" / "main.cpp")
        self.assertIsNotNone(fallback_args)
        
        # Should contain fallback-specific args
        self.assertIn('-std=c++17', fallback_args)
        self.assertIn('-DNOMINMAX', fallback_args)
        # Should not contain compile command specific args
        self.assertNotIn('-Iinclude', fallback_args)
    
    def test_disabled_compile_commands(self):
        """Test behavior when compile_commands is disabled in config."""
        # Create compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create config with compile_commands disabled
        config = {'compile_commands_enabled': False, 'fallback_to_hardcoded': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Should use fallback arguments despite compile_commands.json existing
        args = manager.get_compile_args_with_fallback(self.project_root / "src" / "main.cpp")
        self.assertIsNotNone(args)
        
        # Verify fallback args are used
        self.assertIn('-std=c++17', args)
        self.assertIn('-DNOMINMAX', args)
        self.assertNotIn('-Iinclude', args)
        
        # Verify compile commands are disabled
        self.assertFalse(manager.enabled)
        self.assertEqual(manager.get_stats()["enabled"], False)
    
    def test_error_handling_malformed_compile_commands(self):
        """Test error handling with malformed compile_commands.json."""
        # Create malformed compile_commands.json
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            f.write("invalid json content")
        
        # Create manager
        config = {'compile_commands_enabled': True, 'fallback_to_hardcoded': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Should still work using fallback
        args = manager.get_compile_args_with_fallback(self.project_root / "src" / "main.cpp")
        self.assertIsNotNone(args)
        
        # Should contain fallback args
        self.assertIn('-std=c++17', args)
        self.assertIn('-DNOMINMAX', args)
    
    def test_relative_path_handling(self):
        """Test handling of relative paths in compile_commands.json."""
        # Create compile_commands.json with relative paths
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            },
            {
                "file": "src/utils.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/utils.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create manager
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test path normalization
        abs_path = str(self.project_root / "src" / "main.cpp")
        rel_path = "src/main.cpp"
        
        # Both should resolve to the same file
        args1 = manager.get_compile_args(Path(abs_path))
        args2 = manager.get_compile_args(Path(rel_path))
        
        self.assertIsNotNone(args1)
        self.assertIsNotNone(args2)
        self.assertEqual(args1, args2)
    
    def test_extension_filtering(self):
        """Test file extension filtering."""
        # Create compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create manager
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Test supported extensions
        self.assertTrue(manager.is_extension_supported(self.project_root / "test.cpp"))
        self.assertTrue(manager.is_extension_supported(self.project_root / "test.hpp"))
        self.assertTrue(manager.is_extension_supported(self.project_root / "test.h"))
        self.assertFalse(manager.is_extension_supported(self.project_root / "test.txt"))
        self.assertFalse(manager.is_extension_supported(self.project_root / "test.py"))
        
        # Test file processing decisions
        self.assertTrue(manager.should_process_file(self.project_root / "src" / "main.cpp"))
        self.assertTrue(manager.should_process_file(self.project_root / "new_file.cpp"))  # Supported extension
        self.assertFalse(manager.should_process_file(self.project_root / "document.txt"))  # Unsupported extension
    
    def test_cache_clearing(self):
        """Test cache clearing functionality."""
        # Create compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create manager
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Verify cache has data
        self.assertEqual(len(manager.compile_commands), 1)
        self.assertEqual(len(manager.file_to_command_map), 1)
        
        # Clear cache
        manager.clear_cache()
        
        # Verify cache is empty
        self.assertEqual(len(manager.compile_commands), 0)
        self.assertEqual(len(manager.file_to_command_map), 0)
        self.assertEqual(manager.last_modified, 0)
    
    def test_stats_functionality(self):
        """Test statistics functionality."""
        # Create compile_commands.json
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/main.cpp"
            },
            {
                "file": "src/utils.cpp",
                "directory": str(self.project_root),
                "arguments": ["-std=c++17", "-I", "include"],
                "command": "clang++ -std=c++17 -I include src/utils.cpp"
            }
        ]
        
        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)
        
        # Create manager
        config = {'compile_commands_enabled': True, 'cache_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)
        
        # Get stats
        stats = manager.get_stats()
        
        # Verify stats
        self.assertTrue(stats['enabled'])
        self.assertEqual(stats['compile_commands_count'], 2)
        self.assertEqual(stats['file_mapping_count'], 2)
        self.assertTrue(stats['cache_enabled'])
        self.assertTrue(stats['fallback_enabled'])
        self.assertIn('compile_commands_path', stats)
    
    def test_command_string_parsing(self):
        """Test command string parsing with various formats."""
        # Create compile_commands.json with command strings
        compile_commands = [
            {
                "file": "src/main.cpp",
                "directory": str(self.project_root),
                "command": 'clang++ -std=c++17 -I"include path" -D"DEFINE=value" -c main.cpp'
            }
        ]

        compile_commands_file = self.project_root / "compile_commands.json"
        with open(compile_commands_file, 'w') as f:
            json.dump(compile_commands, f)

        # Create manager
        config = {'compile_commands_enabled': True}
        manager = CompileCommandsManager(self.project_root, config)

        # Test command parsing
        args = manager.get_compile_args(self.project_root / "src" / "main.cpp")

        self.assertIsNotNone(args)
        self.assertIn('-std=c++17', args)
        # Quotes are removed by shell parsing, but spaces are preserved within the token
        self.assertIn('-Iinclude path', args)
        self.assertIn('-DDEFINE=value', args)
        self.assertIn('-c', args)
        self.assertIn('main.cpp', args)
    
    def test_fallback_args_generation(self):
        """Test fallback arguments generation on different platforms."""
        # Test Linux fallback args
        with patch('sys.platform', 'linux'):
            config = {'compile_commands_enabled': False}
            manager = CompileCommandsManager(self.project_root, config)
            
            args = manager.fallback_args
            
            self.assertIn('-std=c++17', args)
            self.assertIn('-I.', args)
            self.assertIn('-DNOMINMAX', args)
            self.assertIn('-DWIN32', args)  # Should still be included for compatibility
            self.assertNotIn('-IC:/Program Files', args)  # No Windows-specific paths
        
        # Test Windows fallback args
        with patch('sys.platform', 'win32'):
            with patch('glob.glob') as mock_glob:
                mock_glob.return_value = [
                    'C:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/ucrt',
                    'C:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/um'
                ]
                
                config = {'compile_commands_enabled': False}
                manager = CompileCommandsManager(self.project_root, config)
                
                args = manager.fallback_args
                
                self.assertIn('-std=c++17', args)
                self.assertIn('-I.', args)
                self.assertIn('-DNOMINMAX', args)
                self.assertIn('-DWIN32', args)
                self.assertIn('-D_WIN32', args)
                self.assertIn('-D_WINDOWS', args)
                # Should include Windows SDK includes
                self.assertIn('-IC:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/ucrt', args)
                self.assertIn('-IC:/Program Files (x86)/Windows Kits/10/Include/10.0.19041.0/um', args)


if __name__ == '__main__':
    unittest.main()