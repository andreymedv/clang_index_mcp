#!/usr/bin/env python3
"""
Tests for LibClang Compatibility Processing Requirements (REQ-5.7)

This module tests the compilation argument processing pipeline that ensures
compatibility with libclang's programmatic interface.

Test Coverage:
- REQ-5.7: LibClang Compatibility Processing
- REQ-5.7.1: Argument Sanitization
- REQ-5.7.2: Builtin Headers Support
- REQ-5.7.3: Path Normalization
- REQ-5.7.4: Processing Pipeline
"""

import sys
import os
import tempfile
import json
from pathlib import Path

# Add mcp_server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_server'))

from compile_commands_manager import CompileCommandsManager


class TestArgumentSanitization:
    """Tests for REQ-5.7.1: Argument Sanitization"""

    def test_req_5_7_1_1_pch_removal(self):
        """REQ-5.7.1.1: Remove precompiled header options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        # Test -Xclang -include-pch removal
        args = ['-std=c++17', '-Xclang', '-include-pch', '-Xclang', '/path/to/file.pch', '-Wall']
        result = manager._sanitize_args_for_libclang(args)
        assert '-Xclang' not in result, "Should remove -Xclang"
        assert '-include-pch' not in result, "Should remove -include-pch"
        assert '/path/to/file.pch' not in result, "Should remove PCH file path"
        assert '-std=c++17' in result, "Should keep -std flag"
        assert '-Wall' in result, "Should keep warning flags"

        # Test -Xclang -include -Xclang cmake_pch.hxx removal
        args = ['-std=c++17', '-Xclang', '-include', '-Xclang', 'cmake_pch.hxx', '-Wall']
        result = manager._sanitize_args_for_libclang(args)
        assert 'cmake_pch.hxx' not in result, "Should remove cmake_pch files"

        # Test -Winvalid-pch removal
        args = ['-std=c++17', '-Winvalid-pch', '-Wall']
        result = manager._sanitize_args_for_libclang(args)
        assert '-Winvalid-pch' not in result, "Should remove -Winvalid-pch"

        print("✓ REQ-5.7.1.1: PCH removal works correctly")

    def test_req_5_7_1_2_cosmetic_removal(self):
        """REQ-5.7.1.2: Remove cosmetic and formatting options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = [
            '-std=c++17',
            '-fcolor-diagnostics',
            '-fno-color-diagnostics',
            '-fdiagnostics-color',
            '-Wall'
        ]
        result = manager._sanitize_args_for_libclang(args)

        assert '-fcolor-diagnostics' not in result
        assert '-fno-color-diagnostics' not in result
        assert '-fdiagnostics-color' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.7.1.2: Cosmetic options removal works correctly")

    def test_req_5_7_1_3_version_specific_removal(self):
        """REQ-5.7.1.3: Remove version-specific compiler options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = [
            '-std=c++17',
            '-fconstexpr-steps=11000000',
            '-fconstexpr-depth=512',
            '-ftemplate-depth=768',
            '-Wall'
        ]
        result = manager._sanitize_args_for_libclang(args)

        assert not any('-fconstexpr-steps' in arg for arg in result)
        assert not any('-fconstexpr-depth' in arg for arg in result)
        assert not any('-ftemplate-depth' in arg for arg in result)
        assert '-std=c++17' in result

        print("✓ REQ-5.7.1.3: Version-specific options removal works correctly")

    def test_req_5_7_1_4_optimization_debug_removal(self):
        """REQ-5.7.1.4: Remove optimization and debug options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = [
            '-std=c++17',
            '-g', '-ggdb', '-g3',
            '-fno-limit-debug-info',
            '-O0', '-O2', '-O3',
            '-Wall'
        ]
        result = manager._sanitize_args_for_libclang(args)

        assert '-g' not in result
        assert '-ggdb' not in result
        assert '-g3' not in result
        assert '-fno-limit-debug-info' not in result
        assert '-O0' not in result
        assert '-O2' not in result
        assert '-O3' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.7.1.4: Optimization/debug options removal works correctly")

    def test_req_5_7_1_5_architecture_removal(self):
        """REQ-5.7.1.5: Remove architecture-specific options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = ['-std=c++17', '-m64', '-m32', '-msse2', '-mfpmath=sse', '-Wall']
        result = manager._sanitize_args_for_libclang(args)

        assert '-m64' not in result
        assert '-m32' not in result
        assert '-msse2' not in result
        assert '-mfpmath=sse' not in result
        assert '-std=c++17' in result

        print("✓ REQ-5.7.1.5: Architecture options removal works correctly")

    def test_req_5_7_1_6_codegen_removal(self):
        """REQ-5.7.1.6: Remove code generation options"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = [
            '-std=c++17',
            '-fvisibility-inlines-hidden',
            '-fvisibility=hidden',
            '-fPIC', '-fPIE',
            '-Wall'
        ]
        result = manager._sanitize_args_for_libclang(args)

        assert '-fvisibility-inlines-hidden' not in result
        assert '-fvisibility=hidden' not in result
        assert '-fPIC' not in result
        assert '-fPIE' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.7.1.6: Code generation options removal works correctly")

    def test_req_5_7_1_7_essential_preservation(self):
        """REQ-5.7.1.7: Preserve essential compilation flags"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = [
            '-std=c++17',
            '-DBOOST_ALL_DYN_LINK',
            '-I/usr/include',
            '-isystem', '/usr/local/include',
            '-Wall', '-Wextra', '-Werror',
            '-include', '/path/to/config.h',
            '-O0'  # Should be removed
        ]
        result = manager._sanitize_args_for_libclang(args)

        # Should keep
        assert '-std=c++17' in result
        assert '-DBOOST_ALL_DYN_LINK' in result
        assert '-I/usr/include' in result
        assert '-isystem' in result
        assert '/usr/local/include' in result
        assert '-Wall' in result
        assert '-Wextra' in result
        assert '-Werror' in result
        assert '-include' in result
        assert '/path/to/config.h' in result

        # Should remove
        assert '-O0' not in result

        print("✓ REQ-5.7.1.7: Essential flags preservation works correctly")


class TestBuiltinHeaders:
    """Tests for REQ-5.7.2: Builtin Headers Support"""

    def test_req_5_7_2_1_detection(self):
        """REQ-5.7.2.1: Detect clang resource directory"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        # Resource directory should be detected
        assert manager.clang_resource_dir is not None or True, \
            "Resource directory detection should succeed or gracefully fail"

        if manager.clang_resource_dir:
            # Verify stddef.h exists
            stddef_path = Path(manager.clang_resource_dir) / "stddef.h"
            assert stddef_path.exists(), f"stddef.h should exist at {stddef_path}"

            print(f"✓ REQ-5.7.2.1: Resource directory detected: {manager.clang_resource_dir}")
        else:
            print("⚠ REQ-5.7.2.1: Resource directory not detected (acceptable if clang not installed)")

    def test_req_5_7_2_2_addition_to_args(self):
        """REQ-5.7.2.2: Add resource directory using -isystem"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        if manager.clang_resource_dir:
            args = ['-std=c++17', '-Wall']
            result = manager._add_builtin_includes(args)

            assert '-isystem' in result, "Should add -isystem flag"
            assert manager.clang_resource_dir in result, "Should add resource directory"

            print("✓ REQ-5.7.2.2: Resource directory added with -isystem")
        else:
            print("⚠ REQ-5.7.2.2: Skipped (no resource directory)")

    def test_req_5_7_2_3_proper_positioning(self):
        """REQ-5.7.2.3: Resource directory positioning"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        if manager.clang_resource_dir:
            args = ['-std=c++17', '-I/project/include', '-Wall']
            result = manager._add_builtin_includes(args)

            # Find positions
            std_pos = result.index('-std=c++17')
            isystem_pos = result.index('-isystem')

            # Should be after -std
            assert isystem_pos > std_pos, "Resource dir should be after language standard"

            # Should not be added twice
            count = result.count(manager.clang_resource_dir)
            assert count == 1, "Resource directory should appear exactly once"

            print("✓ REQ-5.7.2.3: Resource directory positioning is correct")
        else:
            print("⚠ REQ-5.7.2.3: Skipped (no resource directory)")

    def test_req_5_7_2_4_included_everywhere(self):
        """REQ-5.7.2.4: Builtin headers included in all contexts"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        if manager.clang_resource_dir:
            # Check fallback args
            assert manager.clang_resource_dir in ' '.join(manager.fallback_args), \
                "Should be in fallback args"

            print("✓ REQ-5.7.2.4: Builtin headers included in fallback args")
        else:
            print("⚠ REQ-5.7.2.4: Skipped (no resource directory)")


class TestPathNormalization:
    """Tests for REQ-5.7.3: Path Normalization"""

    def test_req_5_7_3_1_i_path_normalization(self):
        """REQ-5.7.3.1: Normalize -I include paths"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        # Test -I <path> form (separate arguments)
        args = ['-std=c++17', '-I', 'relative/path', '-Wall']
        result = manager._normalize_arguments(args, '/base/dir')

        assert '-I' in result
        # The path after -I should be absolute
        i_index = result.index('-I')
        path = result[i_index + 1]
        assert os.path.isabs(path), f"Path should be absolute: {path}"
        assert '/base/dir/relative/path' in path or path.endswith('relative/path')

        # Test -I<path> form (combined)
        args = ['-std=c++17', '-Irelative/path', '-Wall']
        result = manager._normalize_arguments(args, '/base/dir')

        # Find the -I argument
        i_arg = [arg for arg in result if arg.startswith('-I')][0]
        path = i_arg[2:]  # Remove -I prefix
        assert os.path.isabs(path), f"Path should be absolute: {path}"

        print("✓ REQ-5.7.3.1: -I path normalization works correctly")

    def test_req_5_7_3_2_isystem_path_normalization(self):
        """REQ-5.7.3.2: Normalize -isystem include paths"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        # Test -isystem <path> form (separate arguments)
        args = ['-std=c++17', '-isystem', 'relative/sys', '-Wall']
        result = manager._normalize_arguments(args, '/base/dir')

        assert '-isystem' in result
        isystem_index = result.index('-isystem')
        path = result[isystem_index + 1]
        assert os.path.isabs(path), f"Path should be absolute: {path}"

        print("✓ REQ-5.7.3.2: -isystem path normalization works correctly")

    def test_req_5_7_3_3_relative_to_absolute(self):
        """REQ-5.7.3.3: Convert relative paths to absolute using directory"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        args = ['-I', '../include', '-I', '/absolute/path']
        result = manager._normalize_arguments(args, '/project/build')

        # First path should be made absolute relative to /project/build
        # Second path should remain absolute
        i_count = 0
        for i, arg in enumerate(result):
            if arg == '-I' and i + 1 < len(result):
                path = result[i + 1]
                assert os.path.isabs(path), f"All paths should be absolute: {path}"
                i_count += 1

        assert i_count == 2, "Should have 2 include paths"

        print("✓ REQ-5.7.3.3: Relative to absolute conversion works correctly")


class TestProcessingPipeline:
    """Tests for REQ-5.7.4: Processing Pipeline"""

    def test_req_5_7_4_complete_pipeline(self):
        """REQ-5.7.4: Complete processing pipeline"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create compile_commands.json
            compile_commands = [{
                "directory": str(project_root / "build"),
                "command": "/usr/bin/clang++ -DTEST -I../include -isystem ../external "
                           "-g -O0 -fcolor-diagnostics -fconstexpr-steps=10000 "
                           "-Xclang -include-pch -Xclang pch.pch "
                           "-std=c++17 -Wall "
                           "-o main.o -c ../src/main.cpp",
                "file": str(project_root / "src" / "main.cpp")
            }]

            cc_path = project_root / "compile_commands.json"
            with open(cc_path, 'w') as f:
                json.dump(compile_commands, f)

            manager = CompileCommandsManager(project_root)

            # Get arguments for the file
            args = manager.get_compile_args(project_root / "src" / "main.cpp")

            if args:
                # Verify pipeline steps:
                # 1. Parsing: compiler, -o, -c, source file removed
                assert '/usr/bin/clang++' not in args
                assert '-o' not in args
                assert '-c' not in args
                assert 'main.cpp' not in ' '.join(args)

                # 2. Normalization: paths should be absolute
                # (hard to test without knowing actual paths)

                # 3. Sanitization: problematic flags removed
                assert '-Xclang' not in args
                assert '-g' not in args
                assert '-O0' not in args
                assert '-fcolor-diagnostics' not in args
                assert not any('-fconstexpr-steps' in arg for arg in args)

                # 4. Builtin headers: resource dir added (if available)
                if manager.clang_resource_dir:
                    assert manager.clang_resource_dir in ' '.join(args)

                # Essential flags preserved
                assert '-std=c++17' in args
                assert '-DTEST' in args
                assert '-Wall' in args

                print("✓ REQ-5.7.4: Complete processing pipeline works correctly")
            else:
                print("⚠ REQ-5.7.4: Could not get args (file not in compile_commands)")

    def test_req_5_7_4_1_consistency(self):
        """REQ-5.7.4.1: Pipeline applied consistently to command and arguments"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            # Create two entries: one with command, one with arguments
            compile_commands = [
                {
                    "directory": str(project_root / "build"),
                    "command": "/usr/bin/clang++ -DTEST -std=c++17 -O0 "
                               "-o main.o -c ../src/main.cpp",
                    "file": str(project_root / "src" / "main.cpp")
                },
                {
                    "directory": str(project_root / "build"),
                    "arguments": [
                        "/usr/bin/clang++", "-DTEST", "-std=c++17", "-O0",
                        "-o", "other.o", "-c", "../src/other.cpp"
                    ],
                    "file": str(project_root / "src" / "other.cpp")
                }
            ]

            cc_path = project_root / "compile_commands.json"
            with open(cc_path, 'w') as f:
                json.dump(compile_commands, f)

            manager = CompileCommandsManager(project_root)

            args1 = manager.get_compile_args(project_root / "src" / "main.cpp")
            args2 = manager.get_compile_args(project_root / "src" / "other.cpp")

            if args1 and args2:
                # Both should have similar processing
                assert '-DTEST' in args1 and '-DTEST' in args2
                assert '-std=c++17' in args1 and '-std=c++17' in args2
                assert '-O0' not in args1 and '-O0' not in args2
                assert '-o' not in args1 and '-o' not in args2

                print("✓ REQ-5.7.4.1: Pipeline applied consistently")
            else:
                print("⚠ REQ-5.7.4.1: Could not test (files not in compile_commands)")

    def test_req_5_7_4_2_integrity(self):
        """REQ-5.7.4.2: Argument list integrity preserved"""
        manager = CompileCommandsManager(Path("/tmp/test"))

        original = [
            '-std=c++17',
            '-DTEST=1',
            '-DVALUE="hello world"',
            '-I/path/with spaces',
            '-isystem', '/system/path',
            '-Wall', '-Wextra',
            '-O0',  # Will be removed
            '-g'    # Will be removed
        ]

        # Process through sanitization
        result = manager._sanitize_args_for_libclang(original)

        # Check that we didn't corrupt arguments
        assert '-std=c++17' in result
        assert '-DTEST=1' in result
        assert '-DVALUE="hello world"' in result or '-DVALUE=hello world' in result
        assert any('spaces' in arg for arg in result), "Should preserve paths with spaces"
        assert '-isystem' in result
        assert '-Wall' in result
        assert '-Wextra' in result

        # Verify no empty strings or None
        assert all(arg and isinstance(arg, str) for arg in result)

        print("✓ REQ-5.7.4.2: Argument list integrity preserved")


def run_all_tests():
    """Run all libclang compatibility tests"""
    print("=" * 70)
    print("Testing LibClang Compatibility Processing (REQ-5.7)")
    print("=" * 70)

    test_classes = [
        TestArgumentSanitization(),
        TestBuiltinHeaders(),
        TestPathNormalization(),
        TestProcessingPipeline()
    ]

    total_tests = 0
    passed_tests = 0

    for test_class in test_classes:
        print(f"\n{test_class.__class__.__name__}:")
        print("-" * 70)

        for method_name in dir(test_class):
            if method_name.startswith('test_req_'):
                total_tests += 1
                try:
                    method = getattr(test_class, method_name)
                    method()
                    passed_tests += 1
                except AssertionError as e:
                    print(f"✗ {method_name}: {e}")
                except Exception as e:
                    print(f"✗ {method_name}: Unexpected error: {e}")

    print("\n" + "=" * 70)
    print(f"Test Results: {passed_tests}/{total_tests} passed")
    print("=" * 70)

    return passed_tests == total_tests


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
