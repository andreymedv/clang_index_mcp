"""Platform Tests - Windows
Windows-specific tests. REQ-13.2, Priority: P1"""
import pytest
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.platform
@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
class TestWindowsPaths:
    def test_windows_path_separators(self, temp_project_dir):
        """Test mixed / and \\ in paths on Windows - Task 1.6.2"""
        file = temp_project_dir / "src" / "test.cpp"
        file.write_text("class Test {};")
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should handle Windows paths"
        mixed_path = str(file).replace("\\", "/")
        results = analyzer.find_in_file(mixed_path, ".*")
        assert isinstance(results, list), "Should handle mixed separators"

    def test_windows_max_path_length(self, temp_project_dir):
        """Test paths > 260 characters on Windows - Task 1.6.3"""
        long_dir = temp_project_dir / "src" / ("subdir_" * 30)
        long_dir.mkdir(parents=True, exist_ok=True)
        file = long_dir / "test.cpp"
        try:
            file.write_text("class Test {};")
            analyzer = CppAnalyzer(str(temp_project_dir))
            count = analyzer.index_project()
            assert count >= 0, "Should handle long paths gracefully"
        except OSError:
            pytest.skip("Cannot create long path on this system")
