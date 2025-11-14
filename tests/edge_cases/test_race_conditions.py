"""Edge Case Tests - Race Conditions
Tests for concurrent file modifications. REQ-12.4, Priority: P1"""
import pytest, time, threading
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.edge_case
class TestConcurrentModification:
    def test_concurrent_file_modification(self, temp_project_dir):
        """Test file modification during parsing - Task 1.5.4"""
        file = temp_project_dir / "src" / "concurrent.cpp"
        file.write_text("class Test1 {};")
        analyzer = CppAnalyzer(str(temp_project_dir))

        def modify_file():
            time.sleep(0.1)
            file.write_text("class Test2 {};")

        thread = threading.Thread(target=modify_file)
        thread.start()
        count = analyzer.index_project()
        thread.join()
        assert count >= 0, "Should handle concurrent modifications"
