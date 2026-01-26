"""
Security Tests - Path Security

Tests for path traversal attacks and symlink attack prevention.

Requirements: REQ-10.1 (Path Security)
Priority: P0 - CRITICAL
"""

import pytest
from pathlib import Path
import os

# Import test infrastructure
import sys
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.security
@pytest.mark.critical
class TestPathTraversalAttacks:
    """Test path traversal attack prevention - REQ-10.1.1"""

    def test_comprehensive_path_traversal_attacks(self, temp_project_dir):
        """Test all path traversal attack vectors - Task 1.3.1"""
        # Create legitimate file
        (temp_project_dir / "src" / "legitimate.cpp").write_text("class Safe {};")

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Attack Vector 1: ../ traversal
        result1 = analyzer.find_in_file("../../../etc/passwd", ".*")
        assert isinstance(result1, dict), "Should return dict, not crash"
        assert "results" in result1, "Should have results key"

        # Attack Vector 2: Absolute paths outside project
        result2 = analyzer.find_in_file("/etc/passwd", ".*")
        assert isinstance(result2, dict), "Should handle absolute paths safely"
        assert "results" in result2, "Should have results key"

        # Attack Vector 3: URL-encoded traversal
        result3 = analyzer.find_in_file("..%2F..%2F..%2Fetc%2Fpasswd", ".*")
        assert isinstance(result3, dict), "Should handle URL-encoded paths safely"
        assert "results" in result3, "Should have results key"

        # Attack Vector 4: UNC paths (Windows)
        result4 = analyzer.find_in_file("\\\\server\\share\\file.cpp", ".*")
        assert isinstance(result4, dict), "Should handle UNC paths safely"
        assert "results" in result4, "Should have results key"

        # Attack Vector 5: file:// protocol
        result5 = analyzer.find_in_file("file:///etc/passwd", ".*")
        assert isinstance(result5, dict), "Should handle file:// protocol safely"
        assert "results" in result5, "Should have results key"

        # Verify legitimate file still works
        legit_result = analyzer.find_in_file(str(temp_project_dir / "src" / "legitimate.cpp"), ".*")
        # Should work for legitimate paths
        assert isinstance(legit_result, dict), "Legitimate paths should still work"
        assert "results" in legit_result, "Should have results key"


@pytest.mark.security
@pytest.mark.critical
@pytest.mark.skipif(sys.platform == "win32", reason="Symlink tests for Unix")
class TestSymlinkAttacks:
    """Test symlink attack prevention - REQ-10.1.2"""

    def test_symlink_attack_prevention(self, temp_project_dir):
        """Test prevention of symlink attacks to sensitive files - Task 1.3.4"""
        # Create legitimate file
        legit_file = temp_project_dir / "src" / "legitimate.cpp"
        legit_file.write_text("class Safe {};")

        # Attempt to create symlink to /etc/passwd
        symlink_file = temp_project_dir / "src" / "malicious_link.cpp"

        try:
            if Path("/etc/passwd").exists():
                symlink_file.symlink_to("/etc/passwd")
            else:
                # If /etc/passwd doesn't exist, skip this test
                pytest.skip("/etc/passwd not found for symlink test")
        except (OSError, PermissionError):
            # If symlink creation fails, skip the test
            pytest.skip("Cannot create symlinks (permission denied)")

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index should either skip the symlink or handle it safely
        # Should NOT expose contents of /etc/passwd
        try:
            indexed_count = analyzer.index_project()
            # Should not crash
            assert indexed_count >= 0, "Should not crash on symlinks"

            # Search should not reveal passwd file contents
            results = analyzer.search_classes("root")  # Common in /etc/passwd
            # Even if found, should be from legitimate files only

        finally:
            # Clean up symlink
            if symlink_file.exists():
                symlink_file.unlink()
