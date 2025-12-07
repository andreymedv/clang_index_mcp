"""
Tests for Phase 1 multiple declarations handling (definition-wins logic).

Tests cover:
- EC-6: Multiple forward declarations
- EC-7: Forward declaration + real class (definition-wins)
- EC-8: Multiple function declarations (definition-wins)
- EC-9: Processing order independence (determinism)
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.cpp_analyzer import CppAnalyzer


class TestMultipleForwardDeclarations:
    """Test EC-6: Multiple forward declarations."""

    def test_multiple_forward_declarations_first_wins(self, tmp_path):
        """Test that first forward declaration wins when no definition exists."""
        # Create two headers with forward declarations
        fwd1_h = tmp_path / "fwd1.h"
        fwd1_h.write_text("""
// fwd1.h
class Parser;  // Line 3
""")

        fwd2_h = tmp_path / "fwd2.h"
        fwd2_h.write_text("""
// fwd2.h
class Parser;  // Line 3
""")

        # Index both files
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(fwd1_h))
        analyzer.index_file(str(fwd2_h))

        # Should store first forward declaration
        assert 'Parser' in analyzer.class_index
        parser_symbols = analyzer.class_index['Parser']
        assert len(parser_symbols) == 1

        parser_info = parser_symbols[0]
        assert parser_info.start_line == 3
        assert parser_info.end_line == 3  # Forward decl is single line
        # File should be fwd1.h (processed first)
        assert 'fwd1.h' in parser_info.file


class TestForwardDeclarationPlusRealClass:
    """Test EC-7: Forward declaration + real class (definition-wins)."""

    def test_forward_decl_then_real_class_definition_wins(self, tmp_path):
        """Test that real class definition replaces forward declaration."""
        # Create forward declaration header
        forward_h = tmp_path / "forward.h"
        forward_h.write_text("""
// forward.h
class QString;  // Line 3 - IDE-suggested forward decl
""")

        # Create real class header
        qstring_h = tmp_path / "QString.h"
        qstring_h.write_text("""
// QString.h
class QString {  // Lines 3-5
    int length;
};
""")

        # Index forward declaration first
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(forward_h))

        # Verify forward declaration is initially stored
        assert 'QString' in analyzer.class_index
        qstring_symbols = analyzer.class_index['QString']
        assert len(qstring_symbols) == 1
        initial_info = qstring_symbols[0]
        assert 'forward.h' in initial_info.file
        assert initial_info.start_line == 3
        assert initial_info.end_line == 3  # Single line
        assert not initial_info.is_definition

        # Now index the real class
        analyzer.index_file(str(qstring_h))

        # Definition should replace forward declaration
        qstring_symbols = analyzer.class_index['QString']
        assert len(qstring_symbols) == 1  # Still only one symbol

        replaced_info = qstring_symbols[0]
        assert 'QString.h' in replaced_info.file
        assert replaced_info.start_line == 3
        assert replaced_info.end_line == 5  # Multi-line class, not single line!
        assert replaced_info.is_definition

    def test_real_class_then_forward_decl_definition_kept(self, tmp_path):
        """Test that definition is kept when forward decl comes later."""
        # Create real class header
        qstring_h = tmp_path / "QString.h"
        qstring_h.write_text("""
// QString.h
class QString {  // Lines 3-5
    int length;
};
""")

        # Create forward declaration header
        forward_h = tmp_path / "forward.h"
        forward_h.write_text("""
// forward.h
class QString;  // Line 3
""")

        # Index real class first
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(qstring_h))

        # Verify definition is stored
        qstring_symbols = analyzer.class_index['QString']
        assert len(qstring_symbols) == 1
        initial_info = qstring_symbols[0]
        assert 'QString.h' in initial_info.file
        assert initial_info.is_definition

        # Now index forward declaration
        analyzer.index_file(str(forward_h))

        # Definition should be kept (forward decl ignored)
        qstring_symbols = analyzer.class_index['QString']
        assert len(qstring_symbols) == 1

        kept_info = qstring_symbols[0]
        assert 'QString.h' in kept_info.file  # Still the definition
        assert kept_info.start_line == 3
        assert kept_info.end_line == 5  # Still multi-line
        assert kept_info.is_definition


class TestMultipleFunctionDeclarations:
    """Test EC-8: Multiple function declarations (definition-wins)."""

    def test_multiple_function_declarations_definition_wins(self, tmp_path):
        """Test function declared in multiple headers - definition wins."""
        # Create first header with declaration
        util_h = tmp_path / "util.h"
        util_h.write_text("""
// util.h
void processData(int x);  // Line 3
""")

        # Create second header with duplicate declaration
        helper_h = tmp_path / "helper.h"
        helper_h.write_text("""
// helper.h
void processData(int x);  // Line 3 - manually redeclared
""")

        # Create source with definition
        util_cpp = tmp_path / "util.cpp"
        util_cpp.write_text("""
// util.cpp
void processData(int x) {  // Lines 3-5
    // implementation
}
""")

        # Index all files
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(util_h))
        analyzer.index_file(str(helper_h))
        analyzer.index_file(str(util_cpp))

        # Definition should win
        assert 'processData' in analyzer.function_index
        func_symbols = analyzer.function_index['processData']
        assert len(func_symbols) == 1

        func_info = func_symbols[0]
        assert 'util.cpp' in func_info.file
        assert func_info.start_line == 3
        assert func_info.end_line == 5  # Full function body
        assert func_info.is_definition

    def test_declaration_replaced_when_definition_found(self, tmp_path):
        """Test that declaration is replaced when definition is encountered."""
        # Create header with declaration
        api_h = tmp_path / "api.h"
        api_h.write_text("""
// api.h
int calculate(int a, int b);  // Line 3
""")

        # Create source with definition
        api_cpp = tmp_path / "api.cpp"
        api_cpp.write_text("""
// api.cpp
int calculate(int a, int b) {  // Lines 3-5
    return a + b;
}
""")

        # Index header first
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(api_h))

        # Check that declaration is initially stored
        assert 'calculate' in analyzer.function_index
        func_symbols = analyzer.function_index['calculate']
        assert len(func_symbols) == 1
        initial_info = func_symbols[0]
        assert 'api.h' in initial_info.file
        assert initial_info.start_line == 3
        assert initial_info.end_line == 3  # Declaration only
        assert not initial_info.is_definition

        # Now index source with definition
        analyzer.index_file(str(api_cpp))

        # Definition should replace declaration
        func_symbols = analyzer.function_index['calculate']
        assert len(func_symbols) == 1

        replaced_info = func_symbols[0]
        assert 'api.cpp' in replaced_info.file
        assert replaced_info.start_line == 3
        assert replaced_info.end_line == 5  # Full function body
        assert replaced_info.is_definition


class TestProcessingOrderIndependence:
    """Test EC-9: Processing order independence (determinism)."""

    def test_definition_always_wins_regardless_of_order(self, tmp_path):
        """Test that definition wins regardless of processing order."""
        # Create forward declaration
        fwd_h = tmp_path / "fwd.h"
        fwd_h.write_text("""
// fwd.h
class Data;  // Line 3
""")

        # Create definition
        data_h = tmp_path / "data.h"
        data_h.write_text("""
// data.h
class Data {  // Lines 3-5
    int value;
};
""")

        # Test order 1: Forward first, then definition
        analyzer1 = CppAnalyzer(project_root=str(tmp_path))
        analyzer1.index_file(str(fwd_h))
        analyzer1.index_file(str(data_h))

        data_symbols1 = analyzer1.class_index['Data']
        assert len(data_symbols1) == 1
        data_info1 = data_symbols1[0]

        # Test order 2: Definition first, then forward
        analyzer2 = CppAnalyzer(project_root=str(tmp_path))
        analyzer2.index_file(str(data_h))
        analyzer2.index_file(str(fwd_h))

        data_symbols2 = analyzer2.class_index['Data']
        assert len(data_symbols2) == 1
        data_info2 = data_symbols2[0]

        # Both should have the definition, regardless of order
        assert 'data.h' in data_info1.file
        assert data_info1.start_line == 3
        assert data_info1.end_line == 5  # Multi-line class
        assert data_info1.is_definition

        assert 'data.h' in data_info2.file
        assert data_info2.start_line == 3
        assert data_info2.end_line == 5  # Multi-line class
        assert data_info2.is_definition

        # Results should be identical
        assert data_info1.file == data_info2.file
        assert data_info1.start_line == data_info2.start_line
        assert data_info1.end_line == data_info2.end_line


class TestIDEForwardDeclarationScenario:
    """Real-world scenario: IDE suggests forward declaration that gets processed first."""

    def test_ide_forward_decl_processed_before_real_class(self, tmp_path):
        """Test IDE-suggested forward declaration scenario."""
        # Simulate IDE suggesting forward declaration in widget.h
        widget_h = tmp_path / "widget.h"
        widget_h.write_text("""
// widget.h
class QString;  // Line 3 - IDE-suggested forward decl

class Widget {
    QString* name;
};
""")

        # Real QString class in Qt headers
        qstring_h = tmp_path / "QString.h"
        qstring_h.write_text("""
// QString.h
class QString {  // Lines 3-10
    char* data;
    int length;

public:
    QString(const char* str);
    int size() const;
};
""")

        # Index widget.h first (as might happen due to compile_commands order)
        analyzer = CppAnalyzer(project_root=str(tmp_path))
        analyzer.index_file(str(widget_h))
        analyzer.index_file(str(qstring_h))

        # Real class definition should win
        qstring_symbols = analyzer.class_index['QString']
        assert len(qstring_symbols) == 1

        qstring_info = qstring_symbols[0]
        assert 'QString.h' in qstring_info.file
        assert qstring_info.start_line == 3
        assert qstring_info.end_line == 10  # Full class, not forward decl!
        assert qstring_info.is_definition

        # Verify we get accurate line ranges for reading the full class
        line_range = qstring_info.end_line - qstring_info.start_line + 1
        assert line_range == 8  # Should cover the full class body
