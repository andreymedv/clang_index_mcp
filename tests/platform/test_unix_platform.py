"""Platform Tests - Unix
Unix-specific tests. REQ-13.1, Priority: P1"""
import pytest, stat
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.platform
@pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
class TestUnixPermissions:
    def test_unix_file_permissions(self, temp_project_dir):
        """Test chmod restrictions on Unix - Task 1.6.1"""
        file = temp_project_dir / "src" / "test.cpp"
        file.write_text("class Test {};")
        os.chmod(file, 0o444)  # Read-only
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should read read-only files"
        os.chmod(file, 0o644)  # Restore
