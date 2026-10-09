"""Edge Case Tests - Scale
Tests for large projects. REQ-12.6, Priority: P2"""

import os
import sys

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from clang_index_mcp.cpp_analyzer import CppAnalyzer


@pytest.mark.edge_case
@pytest.mark.slow
class TestScale:
    def test_extremely_large_project(self, temp_project_dir):
        """Verify that indexing a project with many source files succeeds and returns a positive count."""
        for i in range(100):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"class Class{i} {{}};")
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should index large projects"
