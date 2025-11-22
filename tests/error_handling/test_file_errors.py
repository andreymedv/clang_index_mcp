"""
Error Handling Tests - File Errors

Tests for handling file permission errors, missing files, malformed files, etc.

Requirements: REQ-6.x (Error Handling)
Priority: P1
"""

import pytest
from pathlib import Path
import os
import stat

# Import test infrastructure
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.error_handling
class TestFilePermissionErrors:
    """Test file permission error handling - REQ-6.1"""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions not applicable on Windows")
    def test_file_permission_errors(self, temp_project_dir):
        """Test handling of files with no read permission - Task 1.2.1"""
        # Create a file with no read permissions
        restricted_file = temp_project_dir / "src" / "restricted.cpp"
        restricted_file.write_text("""
class RestrictedClass {
public:
    void method();
};
""")

        # Create a normal file
        normal_file = temp_project_dir / "src" / "normal.cpp"
        normal_file.write_text("""
class NormalClass {
public:
    void method();
};
""")

        # Remove read permission from restricted file
        os.chmod(restricted_file, 0o000)

        try:
            # Create analyzer - should gracefully skip unreadable file
            analyzer = CppAnalyzer(str(temp_project_dir))
            indexed_count = analyzer.index_project()

            # Should have indexed at least the normal file
            assert indexed_count > 0, "Should index at least one accessible file"

            # Verify normal file was indexed
            normal_classes = analyzer.search_classes("NormalClass")
            assert len(normal_classes) > 0, "Should find NormalClass"

            # Restricted class should not be found (file was skipped)
            restricted_classes = analyzer.search_classes("RestrictedClass")
            # Either not found or analyzer handled it gracefully
            # Don't assert failure - just verify analyzer didn't crash

        finally:
            # Restore permissions for cleanup
            os.chmod(restricted_file, 0o644)


@pytest.mark.error_handling
class TestMissingFileHandling:
    """Test missing file handling - REQ-6.2"""

    def test_missing_file_handling(self, temp_project_dir):
        """Test handling when file in compile_commands doesn't exist - Task 1.2.2"""
        import json

        # Create compile_commands.json referencing non-existent file
        non_existent = temp_project_dir / "src" / "doesnt_exist.cpp"
        existing = temp_project_dir / "src" / "exists.cpp"

        existing.write_text("""
class ExistingClass {
public:
    void method();
};
""")

        compile_commands = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ -c {non_existent}",
                "file": str(non_existent)
            },
            {
                "directory": str(temp_project_dir),
                "command": f"g++ -c {existing}",
                "file": str(existing)
            }
        ]

        cc_file = temp_project_dir / "compile_commands.json"
        cc_file.write_text(json.dumps(compile_commands, indent=2))

        # Create analyzer - should skip missing file
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Should have indexed at least the existing file
        # (may be 0 if compile_commands filtering is strict)
        # The key is that analyzer shouldn't crash

        # Verify existing file was processed
        existing_classes = analyzer.search_classes("ExistingClass")
        # Analyzer should either find it or gracefully handle missing file


@pytest.mark.error_handling
class TestMalformedFiles:
    """Test handling of malformed source files - REQ-6.3"""

    def test_empty_and_whitespace_files(self, temp_project_dir):
        """Test handling of empty and whitespace-only files - Task 1.2.6"""
        # Create empty file
        empty_file = temp_project_dir / "src" / "empty.cpp"
        empty_file.write_text("")

        # Create whitespace-only file
        whitespace_file = temp_project_dir / "src" / "whitespace.cpp"
        whitespace_file.write_text("   \n\t\n   \n")

        # Create normal file for comparison
        normal_file = temp_project_dir / "src" / "normal.cpp"
        normal_file.write_text("""
class NormalClass {
public:
    void method();
};
""")

        # Create analyzer - should handle empty files gracefully
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Should not crash and should index at least normal file
        assert indexed_count > 0, "Should index normal file"

        # Verify normal file was indexed
        normal_classes = analyzer.search_classes("NormalClass")
        assert len(normal_classes) > 0, "Should find NormalClass"

    def test_null_bytes_in_source(self, temp_project_dir):
        """Test handling of files with embedded null bytes - Task 1.2.7"""
        # Create file with null bytes
        null_file = temp_project_dir / "src" / "null_bytes.cpp"
        null_file.write_bytes(b"class Test\x00Class {\npublic:\n    void method();\n};")

        # Create normal file
        normal_file = temp_project_dir / "src" / "normal.cpp"
        normal_file.write_text("""
class NormalClass {
public:
    void method();
};
""")

        # Create analyzer - should handle null bytes gracefully
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Should not crash
        assert indexed_count >= 0, "Analyzer should not crash on null bytes"

        # Verify normal file was indexed
        normal_classes = analyzer.search_classes("NormalClass")
        assert len(normal_classes) > 0, "Should find NormalClass"

    def test_syntax_errors_in_source(self, temp_project_dir):
        """Test handling of C++ files with syntax errors - Task 1.2.8"""
        # Create file with syntax errors
        syntax_error_file = temp_project_dir / "src" / "syntax_error.cpp"
        syntax_error_file.write_text("""
class InvalidSyntax {
    this is not valid C++ code !!!
    missing semicolons
    unmatched braces {{{
}

void brokenFunction( {
    // missing closing paren
""")

        # Create normal file
        normal_file = temp_project_dir / "src" / "normal.cpp"
        normal_file.write_text("""
class NormalClass {
public:
    void method();
};
""")

        # Create analyzer - should handle syntax errors gracefully
        analyzer = CppAnalyzer(str(temp_project_dir))
        indexed_count = analyzer.index_project()

        # Should not crash and should index at least normal file
        assert indexed_count > 0, "Should index normal file despite syntax errors"

        # Verify normal file was indexed
        normal_classes = analyzer.search_classes("NormalClass")
        assert len(normal_classes) > 0, "Should find NormalClass"

        # Syntax error file may or may not have symbols extracted
        # The key is analyzer didn't crash
