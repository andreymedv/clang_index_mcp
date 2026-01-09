"""
Tests for libclang parsing improvements added since commit 9587d4c.

This test suite covers:
1. System header diagnostic filtering (commit 5761d23)
2. Unknown cursor kind handling (commit 535cce4)
3. C++ stdlib path detection (commit 4b450ff)
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.compile_commands_manager import CompileCommandsManager


class TestSystemHeaderDiagnosticFiltering:
    """Test that errors from system headers are filtered out (commit 5761d23)."""

    def test_is_system_header_diagnostic_clang_builtins(self, temp_project):
        """Test detection of diagnostics from clang built-in headers."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from clang built-in header (ARM intrinsics)
        diag = Mock()
        diag.location.file = "/Library/Developer/CommandLineTools/usr/lib/clang/17/include/arm_acle.h"

        assert analyzer._is_system_header_diagnostic(diag) is True

    def test_is_system_header_diagnostic_sdk_headers(self, temp_project):
        """Test detection of diagnostics from SDK headers."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from macOS SDK header
        diag = Mock()
        diag.location.file = "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk/usr/include/stdio.h"

        assert analyzer._is_system_header_diagnostic(diag) is True

    def test_is_system_header_diagnostic_system_includes(self, temp_project):
        """Test detection of diagnostics from system include directories."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from /usr/include
        diag = Mock()
        diag.location.file = "/usr/include/stdlib.h"

        assert analyzer._is_system_header_diagnostic(diag) is True

    def test_is_system_header_diagnostic_homebrew(self, temp_project):
        """Test detection of diagnostics from Homebrew headers."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from Homebrew
        diag = Mock()
        diag.location.file = "/opt/homebrew/include/boost/config.hpp"

        assert analyzer._is_system_header_diagnostic(diag) is True

    def test_is_system_header_diagnostic_windows_system(self, temp_project):
        """Test detection of diagnostics from Windows system headers."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from Windows Program Files
        diag = Mock()
        diag.location.file = r"C:\Program Files\LLVM\include\stdio.h"

        assert analyzer._is_system_header_diagnostic(diag) is True

    def test_is_system_header_diagnostic_project_file(self, temp_project):
        """Test that project files are NOT detected as system headers."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic from project file
        diag = Mock()
        diag.location.file = f"{temp_project}/src/MyClass.h"

        assert analyzer._is_system_header_diagnostic(diag) is False

    def test_is_system_header_diagnostic_no_location(self, temp_project):
        """Test handling of diagnostics without file location."""
        analyzer = CppAnalyzer(temp_project)

        # Mock diagnostic without file location
        diag = Mock()
        diag.location.file = None

        assert analyzer._is_system_header_diagnostic(diag) is False

    def test_extract_diagnostics_filters_system_header_errors(self, temp_project):
        """Test that system header errors are filtered and downgraded to warnings."""
        analyzer = CppAnalyzer(temp_project)

        # Mock translation unit with system header error and project error
        tu = Mock()

        # System header error (should be filtered)
        system_diag = Mock()
        system_diag.severity = 3  # Error
        system_diag.location.file = "/Library/Developer/CommandLineTools/usr/lib/clang/17/include/arm_neon.h"

        # Project file error (should be kept)
        project_diag = Mock()
        project_diag.severity = 3  # Error
        project_diag.location.file = f"{temp_project}/src/MyClass.cpp"

        # Warning (should be kept as warning)
        warning_diag = Mock()
        warning_diag.severity = 2  # Warning
        warning_diag.location.file = f"{temp_project}/src/MyClass.cpp"

        tu.diagnostics = [system_diag, project_diag, warning_diag]

        errors, warnings = analyzer._extract_diagnostics(tu)

        # Only project error should be in errors
        assert len(errors) == 1
        assert errors[0] == project_diag

        # Both the original warning and downgraded system error should be in warnings
        assert len(warnings) == 2
        assert warning_diag in warnings
        assert system_diag in warnings

    def test_extract_diagnostics_no_false_positives_from_arm_headers(self, temp_project):
        """Test the specific Mac M1 ARM header issue that was fixed."""
        analyzer = CppAnalyzer(temp_project)

        # Mock translation unit with ARM-specific errors
        tu = Mock()

        # ARM built-in function errors (from the bug report)
        arm_acle_diag = Mock()
        arm_acle_diag.severity = 3  # Error
        arm_acle_diag.location.file = "/Library/Developer/CommandLineTools/usr/lib/clang/17/include/arm_acle.h"
        arm_acle_diag.location.line = 82
        arm_acle_diag.location.column = 10
        arm_acle_diag.spelling = "use of undeclared identifier '__builtin_arm_chkfeat'"

        arm_neon_diag = Mock()
        arm_neon_diag.severity = 3  # Error
        arm_neon_diag.location.file = "/Library/Developer/CommandLineTools/usr/lib/clang/17/include/arm_neon.h"
        arm_neon_diag.location.line = 6376
        arm_neon_diag.location.column = 25
        arm_neon_diag.spelling = "incompatible constant for this __builtin_neon function"

        tu.diagnostics = [arm_acle_diag, arm_neon_diag]

        errors, warnings = analyzer._extract_diagnostics(tu)

        # No errors should be reported (all filtered as system header errors)
        assert len(errors) == 0

        # Both should be downgraded to warnings
        assert len(warnings) == 2


class TestUnknownCursorKindHandling:
    """Test graceful handling of unknown cursor kinds (commit 535cce4)."""

    @patch('mcp_server.cpp_analyzer.diagnostics')
    def test_process_cursor_handles_unknown_cursor_kind(self, mock_diagnostics, temp_project):
        """Test that unknown cursor kinds don't crash the analyzer."""
        analyzer = CppAnalyzer(temp_project)

        # Mock cursor where accessing .kind raises ValueError
        cursor = Mock()
        # Make accessing cursor.kind raise ValueError (simulating version mismatch)
        type(cursor).kind = property(lambda self: (_ for _ in ()).throw(ValueError("Unknown cursor kind")))
        cursor.location.file.name = f"{temp_project}/test.cpp"
        cursor.get_children = Mock(return_value=[])
        cursor.spelling = "test_symbol"

        # Should not raise exception - the ValueError should be caught internally
        # and processing should continue with children
        analyzer._process_cursor(cursor)

        # Verify get_children was called (to process children after error)
        cursor.get_children.assert_called()

    @patch('mcp_server.cpp_analyzer.diagnostics')
    def test_process_cursor_continues_with_children_on_unknown_kind(self, mock_diagnostics, temp_project):
        """Test that processing continues with child nodes when cursor kind is unknown."""
        analyzer = CppAnalyzer(temp_project)

        # Mock child cursor that should be processed
        child_cursor = Mock()
        from clang.cindex import CursorKind
        child_cursor.kind = CursorKind.FUNCTION_DECL
        child_cursor.location.file.name = f"{temp_project}/test.cpp"
        child_cursor.location.line = 10
        child_cursor.location.column = 5
        child_cursor.get_children = Mock(return_value=[])
        child_cursor.spelling = "child_function"
        child_cursor.get_usr = Mock(return_value="usr_child")

        # Setup extent for _extract_line_range_info()
        child_cursor.extent.start.file.name = f"{temp_project}/test.cpp"
        child_cursor.extent.start.line = 10
        child_cursor.extent.end.file.name = f"{temp_project}/test.cpp"
        child_cursor.extent.end.line = 15

        # Setup type for signature extraction
        child_cursor.type.spelling = "void ()"

        # Setup raw_comment for _extract_documentation()
        child_cursor.raw_comment = None

        # Setup semantic_parent chain to terminate at TRANSLATION_UNIT
        # This is needed for _get_qualified_name() to work correctly
        translation_unit_cursor = Mock()
        translation_unit_cursor.kind = CursorKind.TRANSLATION_UNIT
        translation_unit_cursor.spelling = ""
        child_cursor.semantic_parent = translation_unit_cursor

        # Mock parent cursor where accessing .kind raises ValueError
        parent_cursor = Mock()
        type(parent_cursor).kind = property(lambda self: (_ for _ in ()).throw(ValueError("Unknown cursor kind")))
        parent_cursor.location.file.name = f"{temp_project}/test.cpp"
        parent_cursor.spelling = "parent"
        parent_cursor.get_children = Mock(return_value=[child_cursor])

        # Processing should handle parent gracefully and still process children
        analyzer._process_cursor(parent_cursor)

        # Verify that children were requested (parent error was handled)
        parent_cursor.get_children.assert_called()


class TestCppStdlibPathDetection:
    """Test C++ standard library path detection (commit 4b450ff)."""

    def test_detect_cxx_stdlib_path_with_libcxx_and_isysroot(self, temp_project):
        """Test detection of libc++ path with -stdlib and -isysroot flags."""
        manager = CompileCommandsManager(Path(temp_project))

        args = [
            "-stdlib=libc++",
            "-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk",
            "-I/some/include/path"
        ]

        stdlib_path = manager._detect_cxx_stdlib_path(args)

        # Should detect libc++ path within the sysroot
        assert stdlib_path is not None
        assert "libc++" in stdlib_path or "c++" in stdlib_path
        assert "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk" in stdlib_path

    def test_detect_cxx_stdlib_path_with_libstdcxx(self, temp_project):
        """Test detection of libstdc++ path."""
        manager = CompileCommandsManager(Path(temp_project))

        args = [
            "-stdlib=libstdc++",
            "-I/usr/include"
        ]

        stdlib_path = manager._detect_cxx_stdlib_path(args)

        # Should detect libstdc++ path (or None if not found on this system)
        # The exact behavior depends on the system
        assert stdlib_path is None or "libstdc++" in stdlib_path or "c++" in stdlib_path

    def test_detect_cxx_stdlib_path_no_stdlib_flag(self, temp_project):
        """Test behavior when no -stdlib flag is present."""
        manager = CompileCommandsManager(Path(temp_project))

        args = [
            "-I/some/include/path",
            "-std=c++17"
        ]

        stdlib_path = manager._detect_cxx_stdlib_path(args)

        # Should return None when no -stdlib flag is present
        assert stdlib_path is None

    def test_detect_cxx_stdlib_path_isysroot_only(self, temp_project):
        """Test detection with only -isysroot (no explicit -stdlib).

        On macOS, when -isysroot contains 'MacOSX', the implementation
        defaults to libc++ even without explicit -stdlib flag.
        """
        manager = CompileCommandsManager(Path(temp_project))

        args = [
            "-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk",
            "-I/some/include/path"
        ]

        stdlib_path = manager._detect_cxx_stdlib_path(args)

        # Should detect libc++ from macOS sysroot (implementation defaults to libc++ for macOS)
        assert stdlib_path is not None
        assert "c++" in stdlib_path
        assert "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk" in stdlib_path

    def test_add_builtin_includes_adds_stdlib_path(self, temp_project):
        """Test that _add_builtin_includes adds C++ stdlib path when detected."""
        manager = CompileCommandsManager(Path(temp_project))

        original_args = [
            "-stdlib=libc++",
            "-isysroot", "/Library/Developer/CommandLineTools/SDKs/MacOSX15.5.sdk",
            "-I/some/project/path"
        ]

        # The method returns a new list with builtin includes added
        result_args = manager._add_builtin_includes(original_args)

        # Check that stdlib path was added
        # It should be added with -isystem flag
        isystem_indices = [i for i, arg in enumerate(result_args) if arg == "-isystem"]

        # Should have at least one -isystem (for clang resource dir or C++ stdlib)
        assert len(isystem_indices) >= 1, f"Expected at least one -isystem flag in {result_args}"

        # If stdlib path was detected, it should appear after -isystem
        stdlib_related = [result_args[i+1] for i in isystem_indices
                         if i+1 < len(result_args) and ("c++" in result_args[i+1] or "libc++" in result_args[i+1])]

        # We should find the stdlib path since we provided -stdlib=libc++ and macOS sysroot
        assert len(stdlib_related) >= 1, f"Expected C++ stdlib path in -isystem arguments: {result_args}"


# Fixtures

@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create src directory
    src_dir = project_dir / "src"
    src_dir.mkdir()

    return str(project_dir)
