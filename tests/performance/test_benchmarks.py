"""
Performance Benchmarks

Performance tests for MCP server and analyzer.

Requirements: P1 - High Priority
"""

import pytest
import time
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.cache_manager import CacheManager
from mcp_server.symbol_info import SymbolInfo
from mcp_server.sqlite_cache_backend import SqliteCacheBackend


@pytest.mark.slow
@pytest.mark.benchmark
class TestPerformanceBenchmarks:
    """Performance benchmarks for critical operations"""

    def test_indexing_performance_small_project(self, temp_project_dir):
        """Benchmark indexing performance on small project (10 files)"""
        # Create 10 test files
        for i in range(10):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"""
class TestClass{i} {{
public:
    void method{i}();
    void anotherMethod{i}(int x, double y);
}};

void globalFunction{i}() {{}}
""")

        analyzer = CppAnalyzer(str(temp_project_dir))

        start = time.time()
        count = analyzer.index_project()
        elapsed = time.time() - start

        # Performance targets
        assert count >= 10, "Should index all files"
        assert elapsed < 10.0, f"Indexing 10 files should take less than 10s, took {elapsed:.2f}s"

        # Log performance
        print(f"\nSmall project indexing: {count} files in {elapsed:.2f}s ({count/elapsed:.1f} files/sec)")

    def test_indexing_performance_medium_project(self, temp_project_dir):
        """Benchmark indexing performance on medium project (50 files)"""
        # Create 50 test files
        for i in range(50):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"""
class TestClass{i} {{
public:
    void method{i}();
    void anotherMethod{i}(int x, double y);
private:
    int member{i};
}};

void globalFunction{i}() {{}}
void helperFunction{i}() {{}}
""")

        analyzer = CppAnalyzer(str(temp_project_dir))

        start = time.time()
        count = analyzer.index_project()
        elapsed = time.time() - start

        # Performance targets
        assert count >= 50, "Should index all files"
        assert elapsed < 30.0, f"Indexing 50 files should take less than 30s, took {elapsed:.2f}s"

        print(f"\nMedium project indexing: {count} files in {elapsed:.2f}s ({count/elapsed:.1f} files/sec)")

    def test_search_performance(self, temp_project_dir):
        """Benchmark search performance"""
        # Create project with many classes
        for i in range(20):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"""
class TestClass{i} {{}};
class AnotherClass{i} {{}};
class DifferentClass{i} {{}};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Benchmark class search
        iterations = 100
        start = time.time()
        for _ in range(iterations):
            results = analyzer.search_classes("Test")
        elapsed = time.time() - start

        avg_time = (elapsed / iterations) * 1000  # Convert to ms
        assert avg_time < 100, f"Average search should be <100ms, was {avg_time:.2f}ms"

        print(f"\nSearch performance: {avg_time:.2f}ms average over {iterations} iterations")

    def test_cache_save_performance(self, temp_project_dir):
        """Benchmark cache save performance"""
        # Create project with moderate size
        for i in range(30):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"""
class TestClass{i} {{
    void method1();
    void method2();
    void method3();
}};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Benchmark cache save
        start = time.time()
        analyzer._save_cache()
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Cache save should be <5s, was {elapsed:.2f}s"

        print(f"\nCache save performance: {elapsed*1000:.2f}ms")

    def test_cache_load_performance(self, temp_project_dir):
        """Benchmark cache load performance"""
        # Create and index project
        for i in range(30):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"""
class TestClass{i} {{
    void method1();
    void method2();
}};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        count1 = analyzer.index_project()
        assert count1 > 0, "Should have indexed files"

        # Create new analyzer to test cache load
        analyzer2 = CppAnalyzer(str(temp_project_dir))

        start = time.time()
        # Use index_project which will load from cache
        count2 = analyzer2.index_project()
        elapsed = time.time() - start

        assert count2 > 0, "Cache should load successfully"
        assert elapsed < 5.0, f"Cache load should be <5s, was {elapsed:.2f}s"

        print(f"\nCache load performance: {elapsed*1000:.2f}ms")

    def test_incremental_refresh_performance(self, temp_project_dir):
        """Benchmark incremental refresh performance"""
        # Create initial project
        for i in range(20):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"class TestClass{i} {{}};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Modify one file
        (temp_project_dir / "src" / "file0.cpp").write_text("class TestClass0 {};\nclass NewClass {};")

        # Benchmark incremental refresh
        start = time.time()
        count = analyzer.refresh_if_needed()
        elapsed = time.time() - start

        assert elapsed < 3.0, f"Incremental refresh should be <3s, was {elapsed:.2f}s"

        print(f"\nIncremental refresh performance: {elapsed*1000:.2f}ms")

    def test_hierarchy_analysis_performance(self, temp_project_dir):
        """Benchmark class hierarchy analysis performance"""
        # Create deep inheritance hierarchy
        (temp_project_dir / "src" / "hierarchy.cpp").write_text("""
class Base0 {};
class Base1 : public Base0 {};
class Base2 : public Base1 {};
class Base3 : public Base2 {};
class Base4 : public Base3 {};
class Base5 : public Base4 {};
class Base6 : public Base5 {};
class Base7 : public Base6 {};
class Base8 : public Base7 {};
class Base9 : public Base8 {};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Benchmark hierarchy analysis
        start = time.time()
        hierarchy = analyzer.get_class_hierarchy("Base5")
        elapsed = time.time() - start

        assert hierarchy is not None
        assert elapsed < 1.0, f"Hierarchy analysis should be <1s, was {elapsed:.2f}s"

        print(f"\nHierarchy analysis performance: {elapsed*1000:.2f}ms")

    def test_call_graph_performance(self, temp_project_dir):
        """Benchmark call graph analysis performance"""
        # Create files with function calls
        (temp_project_dir / "src" / "calls.cpp").write_text("""
void func1() {}
void func2() { func1(); }
void func3() { func2(); func1(); }
void func4() { func3(); func2(); }
void func5() { func4(); func3(); }
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Benchmark call graph analysis
        start = time.time()
        callees = analyzer.find_callees("func3")
        elapsed = time.time() - start

        assert elapsed < 0.5, f"Call graph analysis should be <500ms, was {elapsed*1000:.2f}ms"

        print(f"\nCall graph analysis performance: {elapsed*1000:.2f}ms")


@pytest.mark.slow
@pytest.mark.benchmark
class TestCacheBenchmarks:
    """Benchmarks for cache backend performance"""

    def generate_test_symbols(self, count):
        """Generate test symbols for benchmarking"""
        symbols = []
        for i in range(count):
            if i % 2 == 0:
                symbol = SymbolInfo(
                    name=f"TestClass{i}",
                    kind="class",
                    file=f"/test/file{i % 100}.cpp",
                    line=i * 10 + 1,
                    column=1,
                    usr=f"usr_class_{i}"
                )
            else:
                symbol = SymbolInfo(
                    name=f"testFunc{i}",
                    kind="function",
                    file=f"/test/file{i % 100}.cpp",
                    line=i * 10 + 1,
                    column=1,
                    usr=f"usr_func_{i}"
                )
            symbols.append(symbol)
        return symbols

    def test_bulk_write_performance(self, temp_dir):
        """Benchmark bulk symbol write performance"""
        cache_manager = CacheManager(temp_dir)
        try:
            backend = cache_manager.backend

            if not isinstance(backend, SqliteCacheBackend):
                pytest.skip("This test is for SQLite backend only")

            symbols = self.generate_test_symbols(10000)

            start = time.time()
            backend.save_symbols_batch(symbols)
            elapsed = time.time() - start

            throughput = len(symbols) / elapsed
            # Use conservative threshold that works across different environments
            # 5000 symbols/sec is ideal but 1000 is acceptable minimum
            assert throughput > 1000, f"Throughput should be >1000 symbols/sec, was {throughput:.0f}"

            print(f"\nBulk write performance: {throughput:.0f} symbols/sec ({elapsed*1000:.2f}ms for {len(symbols)} symbols)")
        finally:
            cache_manager.close()

    def test_fts_search_performance(self, temp_dir):
        """Benchmark FTS5 search performance"""
        cache_manager = CacheManager(temp_dir)
        try:
            backend = cache_manager.backend

            if not isinstance(backend, SqliteCacheBackend):
                pytest.skip("This test is for SQLite backend only")

            # Populate database
            symbols = self.generate_test_symbols(10000)
            backend.save_symbols_batch(symbols)

            # Benchmark searches
            search_times = []
            for i in range(100):
                search_name = f"TestClass{(i * 100) % 10000}"
                start = time.time()
                results = backend.search_symbols_fts(search_name)
                elapsed = time.time() - start
                search_times.append(elapsed * 1000)

            avg_time = sum(search_times) / len(search_times)
            assert avg_time < 5.0, f"Average FTS search should be <5ms, was {avg_time:.2f}ms"

            print(f"\nFTS search performance: {avg_time:.2f}ms average (min: {min(search_times):.2f}ms, max: {max(search_times):.2f}ms)")
        finally:
            cache_manager.close()


@pytest.mark.slow
@pytest.mark.benchmark
class TestScalabilityBenchmarks:
    """Benchmarks for testing scalability"""

    def test_large_file_handling(self, temp_project_dir):
        """Test performance with large source files"""
        # Create a large file (1000 classes)
        content = "\n".join([f"class TestClass{i} {{}};" for i in range(1000)])
        (temp_project_dir / "src" / "large.cpp").write_text(content)

        analyzer = CppAnalyzer(str(temp_project_dir))

        start = time.time()
        count = analyzer.index_project()
        elapsed = time.time() - start

        assert count >= 1
        assert elapsed < 15.0, f"Large file indexing should be <15s, was {elapsed:.2f}s"

        print(f"\nLarge file handling: {elapsed:.2f}s for 1000 classes in one file")

    def test_many_small_files(self, temp_project_dir):
        """Test performance with many small files"""
        # Create 100 small files
        for i in range(100):
            (temp_project_dir / "src" / f"file{i}.cpp").write_text(f"class TestClass{i} {{}};")

        analyzer = CppAnalyzer(str(temp_project_dir))

        start = time.time()
        count = analyzer.index_project()
        elapsed = time.time() - start

        assert count >= 100
        assert elapsed < 60.0, f"100 files should index in <60s, took {elapsed:.2f}s"

        print(f"\nMany small files: {count} files in {elapsed:.2f}s ({count/elapsed:.1f} files/sec)")
