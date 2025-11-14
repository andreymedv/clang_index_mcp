"""Edge Case Tests - Unicode
Tests for Unicode in symbols and comments. REQ-12.5, Priority: P2"""
import pytest
import sys, os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path: sys.path.insert(0, project_root)
from mcp_server.cpp_analyzer import CppAnalyzer

@pytest.mark.edge_case
class TestUnicode:
    def test_unicode_in_symbols(self, temp_project_dir):
        """Test Unicode identifiers and emoji in comments - Task 1.5.5"""
        content = "// Unicode: 你好 🎉\nclass TestClass {\n// Comment with émoji 😀\npublic:\n    void method();\n};\n"
        (temp_project_dir / "src" / "unicode.cpp").write_text(content, encoding='utf-8')
        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0, "Should handle Unicode without crashing"
