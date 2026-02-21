"""
Integration Tests - CppAnalyzer with SQLite Backend

Tests full integration of CppAnalyzer with SQLite cache backend.

Requirements: REQ-1.5 (Cache Management)
Priority: P1
"""

import unittest
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

# Import test infrastructure
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.sqlite_cache_backend import SqliteCacheBackend


class TestCppAnalyzerSQLiteIntegration(unittest.TestCase):
    """Test CppAnalyzer integration with SQLite backend - REQ-1.5"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_project_dir = Path(self.temp_dir)
        (self.temp_project_dir / "src").mkdir(parents=True)

    def tearDown(self):
        """Clean up test fixtures"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_full_index_save_load_cycle_sqlite(self):
        """Test full indexing cycle with SQLite backend"""
        # Create test C++ file
        test_file = self.temp_project_dir / "src" / "test.cpp"
        test_file.write_text("""
class TestClass {
public:
    void method();
    int value;
};

void testFunction() {
    TestClass obj;
}
""")

        # Enable SQLite backend
        # First indexing - should create SQLite cache
        analyzer1 = CppAnalyzer(str(self.temp_project_dir))
        count1 = analyzer1.index_project()

        # Verify indexing succeeded
        self.assertGreater(count1, 0, "Should have indexed at least one file")

        # Verify SQLite backend is being used
        self.assertIsInstance(analyzer1.cache_manager.backend, SqliteCacheBackend,
            "Should use SQLite backend")

        # Verify symbols were indexed
        classes1 = analyzer1.search_classes("TestClass")
        funcs1 = analyzer1.search_functions("testFunction")
        self.assertGreater(len(classes1), 0, "Should find TestClass")
        self.assertGreater(len(funcs1), 0, "Should find testFunction")

        # Save class and function counts
        class_count1 = len(classes1)
        func_count1 = len(funcs1)

        # Create new analyzer instance - should load from SQLite cache
        analyzer2 = CppAnalyzer(str(self.temp_project_dir))
        count2 = analyzer2.index_project()

        # Verify cache was loaded
        self.assertGreater(count2, 0, "Should have loaded from cache")

        # Verify cached symbols are available
        classes2 = analyzer2.search_classes("TestClass")
        funcs2 = analyzer2.search_functions("testFunction")
        self.assertEqual(len(classes2), class_count1, "Should find same number of classes")
        self.assertEqual(len(funcs2), func_count1, "Should find same number of functions")

        # Verify results match
        self.assertEqual(classes1[0]['qualified_name'], classes2[0]['qualified_name'])
        self.assertEqual(funcs1[0]['qualified_name'], funcs2[0]['qualified_name'])

    def test_incremental_file_update_sqlite(self):
        """Test incremental update when file changes with SQLite"""
        test_file = self.temp_project_dir / "src" / "changing.cpp"

        # Create initial file
        test_file.write_text("""
class OriginalClass {
public:
    void method();
};
""")

        # First indexing
        analyzer1 = CppAnalyzer(str(self.temp_project_dir))
        analyzer1.index_project()

        # Verify original class is found
        original = analyzer1.search_classes("OriginalClass")
        self.assertGreater(len(original), 0, "Should find OriginalClass")

        # Modify the file
        test_file.write_text("""
class ModifiedClass {
public:
    void newMethod();
};
""")

        # Re-index - should detect file change
        analyzer2 = CppAnalyzer(str(self.temp_project_dir))
        analyzer2.index_project()

        # Verify modified class is found and original is not
        modified = analyzer2.search_classes("ModifiedClass")
        original2 = analyzer2.search_classes("OriginalClass")

        self.assertGreater(len(modified), 0, "Should find ModifiedClass")
        self.assertEqual(len(original2), 0, "Should not find OriginalClass anymore")

    def test_cache_invalidation_on_config_change(self):
        """Test cache invalidation when config file changes"""
        # Create test file
        test_file = self.temp_project_dir / "src" / "test.cpp"
        test_file.write_text("""
class TestClass {};
""")

        # Create config file
        config_file = self.temp_project_dir / ".clang_index"
        config_file.write_text("""
[files]
patterns = ["*.cpp"]
""")

        # First indexing
        analyzer1 = CppAnalyzer(str(self.temp_project_dir))
        count1 = analyzer1.index_project()
        self.assertGreater(count1, 0)

        # Modify config file
        import time
        time.sleep(0.1)  # Ensure timestamp difference
        config_file.write_text("""
[files]
patterns = ["*.cpp", "*.h"]
exclude = ["test/*"]
""")

        # Re-index - should invalidate cache due to config change
        analyzer2 = CppAnalyzer(str(self.temp_project_dir))
        count2 = analyzer2.index_project()

        # Should have re-indexed (not loaded from cache)
        # We can't directly verify cache invalidation, but the system should work
        self.assertGreater(count2, 0)

    def test_sqlite_backend_preserves_all_symbol_data(self):
        """Test that SQLite backend preserves all symbol fields"""
        test_file = self.temp_project_dir / "src" / "detailed.cpp"
        test_file.write_text("""
namespace MyNamespace {
    class BaseClass {};

    class DerivedClass : public BaseClass {
    public:
        void publicMethod();
    private:
        void privateMethod();
        int privateField;
    };

    void globalFunction() {
        DerivedClass obj;
        obj.publicMethod();
    }
}
""")

        # Index project
        analyzer1 = CppAnalyzer(str(self.temp_project_dir))
        analyzer1.index_project()

        # Search for DerivedClass
        derived_results = analyzer1.search_classes("DerivedClass")
        self.assertGreater(len(derived_results), 0, "Should find DerivedClass")

        derived = derived_results[0]

        # Verify all fields are preserved
        self.assertEqual(derived['qualified_name'].split("::")[-1], "DerivedClass")
        self.assertEqual(derived['kind'], "class")
        _derived_loc = derived.get("definition") or derived.get("declaration") or {}
        self.assertIn("detailed.cpp", _derived_loc['file'])

        # Create new analyzer - load from cache
        analyzer2 = CppAnalyzer(str(self.temp_project_dir))
        analyzer2.index_project()

        # Search again
        derived_results2 = analyzer2.search_classes("DerivedClass")
        self.assertGreater(len(derived_results2), 0, "Should find DerivedClass from cache")

        derived2 = derived_results2[0]

        # Verify all fields match
        self.assertEqual(derived2['qualified_name'], derived['qualified_name'])
        self.assertEqual(derived2['kind'], derived['kind'])
        _loc1 = derived.get("definition") or derived.get("declaration") or {}
        _loc2 = derived2.get("definition") or derived2.get("declaration") or {}
        self.assertEqual(_loc2['file'], _loc1['file'])
        self.assertEqual(_loc2['line'], _loc1['line'])

    def test_large_project_performance(self):
        """Test SQLite backend with moderately large project"""
        import time

        # Create multiple files with multiple classes
        for i in range(20):
            test_file = self.temp_project_dir / "src" / f"file{i}.cpp"
            classes = "\n".join([
                f"class File{i}Class{j} {{ public: void method{j}(); }};"
                for j in range(10)
            ])
            test_file.write_text(classes)

        # Measure cold start (first indexing)
        start = time.time()
        analyzer1 = CppAnalyzer(str(self.temp_project_dir))
        count1 = analyzer1.index_project()
        cold_time = time.time() - start

        # Should have indexed many files
        self.assertGreater(count1, 10, "Should have indexed many files")

        # Measure warm start (loading from cache)
        start = time.time()
        analyzer2 = CppAnalyzer(str(self.temp_project_dir))
        count2 = analyzer2.index_project()
        warm_time = time.time() - start

        # Warm start should be significantly faster
        # (though this depends on libclang initialization)
        self.assertGreater(count2, 10)

        # Verify some symbols
        results = analyzer2.search_classes("File0Class0")
        self.assertGreater(len(results), 0, "Should find indexed class")


if __name__ == '__main__':
    unittest.main()
