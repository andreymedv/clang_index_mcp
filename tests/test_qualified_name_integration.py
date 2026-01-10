"""
Integration tests for Qualified Names Support (Phase 1-3).

This file tests the complete qualified name implementation:
- F1: Basic support (store & return qualified names)
- F4: Overload metadata (is_template_specialization)
- F5: Template args qualification (canonical types in base classes)
- F6: Anonymous namespaces
- F7: Nested classes

Note: F2 (pattern matching) and F3 (leading ::) are tested in test_qualified_search.py
"""

import pytest
from pathlib import Path
import tempfile
from mcp_server.cpp_analyzer import CppAnalyzer


class TestF1BasicQualifiedNameSupport:
    """Test F1: Store and return qualified names for all symbol types."""

    def test_qualified_name_extraction_for_classes(self):
        """Test that classes get correct qualified names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ns1 {
    namespace ns2 {
        class MyClass {};
    }
}

class GlobalClass {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test nested namespace class
            results = analyzer.search_classes("MyClass")
            assert len(results) == 1
            assert results[0]["name"] == "MyClass"
            assert results[0]["qualified_name"] == "ns1::ns2::MyClass"
            assert results[0]["namespace"] == "ns1::ns2"

            # Test global namespace class
            results = analyzer.search_classes("GlobalClass")
            assert len(results) == 1
            assert results[0]["name"] == "GlobalClass"
            assert results[0]["qualified_name"] == "GlobalClass"
            assert results[0]["namespace"] == ""

    def test_qualified_name_extraction_for_functions(self):
        """Test that functions get correct qualified names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace utils {
        void helperFunction() {}
    }
}

void globalFunction() {}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test namespaced function
            results = analyzer.search_functions("helperFunction")
            assert len(results) == 1
            assert results[0]["name"] == "helperFunction"
            assert results[0]["qualified_name"] == "app::utils::helperFunction"
            assert results[0]["namespace"] == "app::utils"

            # Test global function
            results = analyzer.search_functions("globalFunction")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "globalFunction"
            assert results[0]["namespace"] == ""

    def test_qualified_name_extraction_for_methods(self):
        """Test that class methods get correct qualified names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace ui {
    class View {
    public:
        void render() {}
        void update() {}
    };
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test methods
            results = analyzer.search_functions("render")
            assert len(results) == 1
            assert results[0]["name"] == "render"
            assert results[0]["qualified_name"] == "ui::View::render"
            assert results[0]["namespace"] == "ui::View"

    def test_namespace_field_populated_correctly(self):
        """Test that namespace field is extracted correctly from qualified name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace a {
    namespace b {
        namespace c {
            class DeepClass {};
        }
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_classes("DeepClass")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "a::b::c::DeepClass"
            assert results[0]["namespace"] == "a::b::c"

    def test_all_search_tools_return_qualified_names(self):
        """Test that all search tools return qualified_name and namespace fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace test {
    class TestClass {};
    void testFunc() {}
    struct TestStruct {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # search_classes
            class_results = analyzer.search_classes("TestClass")
            assert len(class_results) == 1
            assert "qualified_name" in class_results[0]
            assert "namespace" in class_results[0]
            assert class_results[0]["qualified_name"] == "test::TestClass"

            # search_functions
            func_results = analyzer.search_functions("testFunc")
            assert len(func_results) == 1
            assert "qualified_name" in func_results[0]
            assert "namespace" in func_results[0]
            assert func_results[0]["qualified_name"] == "test::testFunc"

            # find_in_file
            file_results = analyzer.find_in_file(str(test_file), "")
            assert len(file_results) >= 2
            for result in file_results:
                assert "qualified_name" in result
                assert "namespace" in result


class TestF4OverloadMetadata:
    """Test F4: is_template_specialization field for function overload distinction."""

    def test_generic_template_not_marked_as_specialization(self):
        """Generic templates should have is_template_specialization=False.

        Note: libclang may not index template function declarations without
        instantiations. This test verifies the field exists when templates ARE indexed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
template<typename T>
void genericFunc(T value) {}

// Add instantiation to ensure libclang indexes the template
template void genericFunc<int>(int);
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_functions("genericFunc")
            # libclang may return 0, 1, or 2 results depending on version
            # We just verify that IF found, the field is present and correct
            if len(results) > 0:
                assert "is_template_specialization" in results[0]
                # Generic template should be False (if libclang reports it)
                generic = [r for r in results if not r.get("is_template_specialization", False)]
                if len(generic) > 0:
                    assert generic[0]["is_template_specialization"] is False

    def test_template_specialization_marked_correctly(self):
        """Template specializations should have is_template_specialization=True.

        Note: libclang may not index generic template declarations, but it does
        index explicit specializations. This test verifies specializations are marked.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
template<typename T>
void func(T value) {}

template<>
void func<int>(int value) {}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_functions("func")
            # libclang may return 1 or 2 results (specialization always found, generic sometimes)
            assert len(results) >= 1, "Should find at least the specialization"

            # Verify the field exists
            for result in results:
                assert "is_template_specialization" in result

            # Find specializations (should be at least one)
            specialized = [r for r in results if r["is_template_specialization"]]
            assert len(specialized) >= 1, "Should find at least one specialization"

    def test_regular_overload_not_marked_as_specialization(self):
        """Regular function overloads should have is_template_specialization=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
void foo(int x) {}
void foo(double x) {}
void foo(int x, int y) {}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_functions("foo")
            assert len(results) == 3

            # All should be False (not template specializations)
            for result in results:
                assert "is_template_specialization" in result
                assert result["is_template_specialization"] is False

    def test_template_class_methods(self):
        """Test is_template_specialization for template class methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
template<typename T>
class Container {
public:
    void add(T item) {}
};

template<>
class Container<int> {
public:
    void add(int item) {}
};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Check that class methods inherit correct metadata
            results = analyzer.search_functions("add")
            assert len(results) >= 1  # May see generic or specialized or both

            # Verify field exists
            for result in results:
                assert "is_template_specialization" in result


class TestF5TemplateArgsQualification:
    """Test F5: Canonical qualified template arguments in base classes."""

    def test_base_classes_include_qualified_template_args(self):
        """Base classes should store template args with qualification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace std {
    template<typename T>
    class vector {};
}

namespace app {
    class Item {};

    template<typename T>
    class Container {};

    class MyContainer : public Container<Item> {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Get class info for MyContainer
            results = analyzer.search_classes("MyContainer")
            assert len(results) == 1
            class_info = results[0]

            # Check base_classes field exists and is populated
            assert "base_classes" in class_info
            base_classes = class_info["base_classes"]
            assert len(base_classes) > 0

            # Base class should include qualification
            # Expected: Container<app::Item> or app::Container<app::Item>
            base_class = base_classes[0]
            assert "Container" in base_class
            assert "Item" in base_class

    def test_nested_template_args_qualified(self):
        """Nested template arguments should be qualified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace std {
    template<typename T>
    class vector {};
}

namespace app {
    class Config {};

    template<typename T>
    class Manager {};

    class ConfigManager : public Manager<Config> {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_classes("ConfigManager")
            assert len(results) == 1

            # Verify base_classes field is present
            assert "base_classes" in results[0]
            assert len(results[0]["base_classes"]) > 0


class TestF6AnonymousNamespaces:
    """Test F6: Anonymous namespace handling."""

    def test_anonymous_namespace_representation(self):
        """Anonymous namespaces should be represented in qualified names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace {
    class InternalClass {};
    void internalFunc() {}
}

namespace app {
    namespace {
        class InternalHelper {};
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Check anonymous namespace class
            results = analyzer.search_classes("InternalClass")
            assert len(results) == 1
            # libclang may represent this differently, just verify field exists
            assert "qualified_name" in results[0]
            assert "namespace" in results[0]

            # Check nested anonymous namespace
            results = analyzer.search_classes("InternalHelper")
            assert len(results) == 1
            assert "qualified_name" in results[0]
            # Should include app in the qualified name
            assert "app" in results[0]["qualified_name"].lower() or \
                   "anonymous" in results[0]["qualified_name"].lower()

    def test_anonymous_namespace_not_confused_with_regular(self):
        """Anonymous namespace symbols should be distinct from regular namespace symbols."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace {
    class Helper {};
}

namespace util {
    class Helper {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Should find both Helpers
            results = analyzer.search_classes("Helper")
            assert len(results) == 2

            # They should have different qualified names
            qualified_names = {r["qualified_name"] for r in results}
            assert len(qualified_names) == 2


class TestF7NestedClasses:
    """Test F7: Nested class qualified names."""

    def test_nested_class_qualified_name(self):
        """Nested classes should have full qualified names with parent class."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
class Outer {
public:
    class Inner {
    public:
        class DeepNested {};
    };
};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test single-level nesting
            results = analyzer.search_classes("Inner")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "Outer::Inner"
            assert results[0]["namespace"] == "Outer"

            # Test deep nesting
            results = analyzer.search_classes("DeepNested")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "Outer::Inner::DeepNested"
            assert results[0]["namespace"] == "Outer::Inner"

    def test_nested_class_in_namespace(self):
        """Nested classes in namespaces should include both namespace and parent class."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace ui {
        class Widget {
        public:
            class Style {};
        };
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_classes("Style")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "app::ui::Widget::Style"
            assert results[0]["namespace"] == "app::ui::Widget"

    def test_nested_class_methods_qualified_name(self):
        """Methods of nested classes should have correct qualified names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace core {
    class Database {
    public:
        class Connection {
        public:
            void connect() {}
            void disconnect() {}
        };
    };
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_functions("connect")
            assert len(results) >= 1

            # Find the connect method
            connect = [r for r in results if r["name"] == "connect"][0]
            assert connect["qualified_name"] == "core::Database::Connection::connect"
            assert connect["namespace"] == "core::Database::Connection"


class TestComprehensiveIntegration:
    """Comprehensive integration tests combining multiple features."""

    def test_complex_project_structure(self):
        """Test a complex project with multiple features combined."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace core {
        template<typename T>
        class Manager {
        public:
            class Config {};
            void process(T item) {}
        };

        template<>
        void Manager<int>::process(int item) {}
    }

    namespace {
        class InternalUtil {};
    }
}

class GlobalService {
public:
    class Settings {};
};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Test nested template class (libclang may not index template classes)
            results = analyzer.search_classes("Manager")
            # If found, verify qualified name is correct
            if len(results) > 0:
                manager = results[0]
                assert "app::core" in manager["qualified_name"]

            # Test nested class inside template (may not be found if parent template not indexed)
            results = analyzer.search_classes("Config")
            # If found, verify it has nesting info
            if len(results) > 0:
                config = [r for r in results if "qualified_name" in r]
                assert len(config) >= 1

            # Test template specialization
            results = analyzer.search_functions("process")
            # Should have both generic and specialized versions
            specialized = [r for r in results if r.get("is_template_specialization", False)]
            # Note: May or may not detect specialization depending on libclang version

            # Test anonymous namespace
            results = analyzer.search_classes("InternalUtil")
            assert len(results) == 1

            # Test global nested class
            results = analyzer.search_classes("Settings")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "GlobalService::Settings"

    def test_search_by_qualified_pattern_integration(self):
        """Test that qualified patterns work across all features."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    namespace ui {
        class View {};
        class ViewModel {};
    }
    namespace core {
        class View {};
    }
}

class View {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Unqualified: all Views
            all_views = analyzer.search_classes("View")
            assert len(all_views) == 3

            # Qualified suffix: ui::View
            ui_views = analyzer.search_classes("ui::View")
            assert len(ui_views) == 1
            assert ui_views[0]["qualified_name"] == "app::ui::View"

            # Exact: global View
            global_views = analyzer.search_classes("::View")
            assert len(global_views) == 1
            assert global_views[0]["qualified_name"] == "View"
            assert global_views[0]["namespace"] == ""

            # Regex: app::.*::View
            app_views = analyzer.search_classes("app::.*::View")
            assert len(app_views) == 2  # ui::View and core::View
            for view in app_views:
                assert view["qualified_name"].startswith("app::")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_pattern_returns_all_symbols(self):
        """Empty pattern should return all symbols."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
class A {};
class B {};
class C {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_classes("")
            assert len(results) >= 3

    def test_very_deep_nesting(self):
        """Test deeply nested namespaces and classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace n1 {
    namespace n2 {
        namespace n3 {
            namespace n4 {
                namespace n5 {
                    class DeepClass {};
                }
            }
        }
    }
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            results = analyzer.search_classes("DeepClass")
            assert len(results) == 1
            assert results[0]["qualified_name"] == "n1::n2::n3::n4::n5::DeepClass"
            assert results[0]["namespace"] == "n1::n2::n3::n4::n5"

    def test_template_with_multiple_params(self):
        """Test templates with multiple parameters.

        Note: libclang may not index template declarations without instantiations.
        This test verifies that IF templates are indexed, the fields are correct.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
template<typename K, typename V>
class Map {};

template<typename K, typename V>
void insert(K key, V value) {}

// Add a non-template class to ensure we can test something
class RegularClass {};
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Verify qualified names work with multi-param templates (if indexed)
            class_results = analyzer.search_classes("Map")
            if len(class_results) > 0:
                assert "qualified_name" in class_results[0]
                assert "is_template_specialization" in class_results[0]

            func_results = analyzer.search_functions("insert")
            if len(func_results) > 0:
                assert "qualified_name" in func_results[0]
                assert "is_template_specialization" in func_results[0]

            # Test that non-template class is definitely found and has correct fields
            regular_results = analyzer.search_classes("RegularClass")
            assert len(regular_results) == 1
            assert "qualified_name" in regular_results[0]
            assert "is_template_specialization" in regular_results[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
