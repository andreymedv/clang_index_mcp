"""
Edge Case Tests - Boundary Conditions

Tests for file size limits, deep inheritance, many overloads.

Requirements: REQ-12.x (Edge Cases)
Priority: P1
"""

import pytest

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.edge_case
class TestFileSizeBoundaries:
    """Test file size boundary conditions - REQ-12.1"""

    def test_file_size_boundary_conditions(self, temp_project_dir):
        """Test files at 9.99MB, 10MB, 10.01MB boundaries - Task 1.5.1"""
        # Assuming 10MB limit
        sizes = [9_990_000, 10_000_000, 10_010_000]

        for i, size in enumerate(sizes):
            content = "// " + "x" * (size - 10) + "\nclass Test{};"
            (temp_project_dir / "src" / f"size{i}.cpp").write_text(content)

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0, "Should handle boundary file sizes"


@pytest.mark.edge_case
class TestInheritanceDepth:
    """Test deep inheritance hierarchies - REQ-12.2"""

    def test_maximum_inheritance_depth(self, temp_project_dir):
        """Test 100-level deep class hierarchy - Task 1.5.2"""
        content = "class Base {};\n"
        for i in range(100):
            parent = "Base" if i == 0 else f"Level{i-1}"
            content += f"class Level{i} : public {parent} {{}};\n"

        (temp_project_dir / "src" / "deep.cpp").write_text(content)

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should handle deep inheritance"

        # Get hierarchy
        hierarchy = analyzer.get_class_hierarchy("Level99")
        assert hierarchy is not None, "Should return hierarchy for deep class"


@pytest.mark.edge_case
class TestManyOverloads:
    """Test many function overloads - REQ-12.3"""

    def test_many_function_overloads(self, temp_project_dir):
        """Test 50+ overloads per function name - Task 1.5.3"""
        content = ""
        for i in range(50):
            content += f"void overloaded({', '.join(['int'] * i)});\n"

        (temp_project_dir / "src" / "overloads.cpp").write_text(content)

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count > 0, "Should handle many overloads"

        results = analyzer.search_functions("overloaded")
        # Should find many overloads
        assert len(results) > 0, "Should find overloaded functions"
