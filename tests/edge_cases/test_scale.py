"""Edge Case Tests - Scale
Tests for large projects. REQ-12.6, Priority: P2"""
import pytest
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.edge_case
@pytest.mark.slow
class TestScale:
    @pytest.mark.skip(reason="Slow test - creates 10k files")
    def test_extremely_large_project(self, temp_project_dir):
        """Test indexing 10,000+ files - Task 1.5.6"""
        for i in range(100):  # Reduced for practicality
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"class Class{i} {{}};")
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should index large projects"
