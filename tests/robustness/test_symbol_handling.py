"""
Robustness Tests - Symbol Handling

Tests for extremely long symbol names and edge cases.

Requirements: REQ-11.2 (Symbol Robustness)
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


@pytest.mark.robustness
class TestExtremelyLongSymbols:
    """Test handling of extremely long symbol names - REQ-11.2"""

    def test_extremely_long_symbol_names(self, temp_project_dir):
        """Test 5000+ character identifiers - Task 1.4.4"""
        # Create class with very long name
        long_name = "A" * 5000
        content = f"class {long_name} {{\npublic:\n    void method();\n}};\n"
        (temp_project_dir / "src" / "long.cpp").write_text(content)

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        # Should not crash
        assert count >= 0, "Should handle long identifiers without crashing"

        # Try to search for it
        results = analyzer.search_classes(f"{long_name[:100]}.*")
        # May or may not find it, but shouldn't crash
        assert isinstance(results, list), "Should return list"
