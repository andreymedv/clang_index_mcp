"""
Security Tests - Path Security

Tests for path traversal attacks and symlink attack prevention.

Requirements: REQ-10.1 (Path Security)
Priority: P0 - CRITICAL
"""

import os

# Import test infrastructure
import sys
from pathlib import Path

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer


@pytest.mark.security
@pytest.mark.critical
class TestPathTraversalAttacks:
    """Test path traversal attack prevention - REQ-10.1.1"""

    def test_comprehensive_path_traversal_attacks(self, temp_project_dir):
        """Verify path traversal attack vectors cannot access files outside the project.

        Security requirement: find_in_file must never return results from files
        outside the project root, regardless of traversal sequences in the path.
        Attack vectors: ../ traversal, absolute paths, URL-encoded traversal,
        UNC paths, and file:// protocol must all be rejected or return empty results.
        """
        # Create legitimate file
        (temp_project_dir / "src" / "legitimate.cpp").write_text("class Safe {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Attack Vector 1: ../ traversal — must not return any results
        result1 = analyzer.find_in_file("../../../etc/passwd", ".*")
        assert isinstance(result1, dict), "Should return dict, not crash"
        assert "results" in result1
        assert result1["results"] == [], (
            f"Path traversal attack succeeded: found {len(result1['results'])} results "
            f"via ../../../etc/passwd"
        )

        # Attack Vector 2: Absolute path outside project — must not return results
        result2 = analyzer.find_in_file("/etc/passwd", ".*")
        assert isinstance(result2, dict)
        assert "results" in result2
        assert result2["results"] == [], (
            f"Absolute path attack succeeded: found {len(result2['results'])} results "
            f"from /etc/passwd"
        )

        # Attack Vector 3: URL-encoded traversal — must not return results
        result3 = analyzer.find_in_file("..%2F..%2F..%2Fetc%2Fpasswd", ".*")
        assert isinstance(result3, dict)
        assert "results" in result3
        assert result3["results"] == [], (
            f"URL-encoded traversal attack succeeded: found {len(result3['results'])} results"
        )

        # Attack Vector 4: UNC paths (Windows) — must not return results
        result4 = analyzer.find_in_file("\\\\server\\share\\file.cpp", ".*")
        assert isinstance(result4, dict)
        assert "results" in result4
        assert result4["results"] == [], (
            f"UNC path attack succeeded: found {len(result4['results'])} results"
        )

        # Attack Vector 5: file:// protocol — must not return results
        result5 = analyzer.find_in_file("file:///etc/passwd", ".*")
        assert isinstance(result5, dict)
        assert "results" in result5
        assert result5["results"] == [], (
            f"file:// protocol attack succeeded: found {len(result5['results'])} results"
        )

        # Verify legitimate file still works
        legit_result = analyzer.find_in_file(str(temp_project_dir / "src" / "legitimate.cpp"), ".*")
        assert isinstance(legit_result, dict), "Legitimate paths should still work"
        assert "results" in legit_result

        analyzer.close()


@pytest.mark.security
@pytest.mark.critical
@pytest.mark.skipif(sys.platform == "win32", reason="Symlink tests for Unix")
class TestSymlinkAttacks:
    """Test symlink attack prevention - REQ-10.1.2"""

    def test_symlink_attack_prevention(self, temp_project_dir):
        """Verify symlinks to sensitive files don't expose their contents.

        Security requirement: Indexing must not follow symlinks that point
        outside the project root. A symlink from a project file to /etc/passwd
        must not cause passwd contents to appear in the symbol index.
        """
        # Create legitimate file
        legit_file = temp_project_dir / "src" / "legitimate.cpp"
        legit_file.write_text("class Safe {};")

        # Attempt to create symlink to /etc/passwd
        symlink_file = temp_project_dir / "src" / "malicious_link.cpp"

        try:
            if Path("/etc/passwd").exists():
                symlink_file.symlink_to("/etc/passwd")
            else:
                pytest.skip("/etc/passwd not found for symlink test")
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks (permission denied)")

        analyzer = CppAnalyzer(str(temp_project_dir))

        try:
            indexed_count = analyzer.index_project()
            assert indexed_count >= 0, "Should not crash on symlinks"

            # Security assertion: searching for terms common in /etc/passwd
            # must NOT return results from the symlinked file.
            # "root" is a common username in /etc/passwd; if the symlink was
            # followed, it would appear as a class or in parsed content.
            results = analyzer.search_classes("root")
            if isinstance(results, tuple):
                results = results[0]

            for result in results:
                file_path = result.get("file", "")
                # No result should come from /etc/passwd or the symlink
                assert "/etc/passwd" not in file_path, (
                    f"Symlink attack: /etc/passwd content exposed in index at {file_path}"
                )
                assert "malicious_link" not in file_path, (
                    f"Symlink attack: symlinked file was indexed: {file_path}"
                )

            # Also verify the symlinked file wasn't indexed by checking
            # that searching for passwd-specific content returns nothing
            passwd_results = analyzer.search_functions(".*")
            if isinstance(passwd_results, tuple):
                passwd_results = passwd_results[0]

            for result in passwd_results:
                file_path = result.get("file", "")
                assert "/etc/passwd" not in file_path, (
                    f"Symlink attack: /etc/passwd functions exposed in index at {file_path}"
                )

        finally:
            # Clean up symlink
            if symlink_file.exists() or symlink_file.is_symlink():
                try:
                    symlink_file.unlink()
                except OSError:
                    pass
            analyzer.close()