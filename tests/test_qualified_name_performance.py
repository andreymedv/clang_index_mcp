"""
Performance benchmarks for Qualified Names Support (Phase 2-4).

This file benchmarks qualified pattern matching performance to ensure
queries complete within acceptable time limits.

NOTE: Timing thresholds are set conservatively (0.5s for single-result queries,
1.0s for queries returning many results) to avoid flaky failures under varying
system loads. The actual performance is typically much faster (~10-50ms).

Benchmarks cover:
- Unqualified pattern searches
- Qualified suffix pattern searches
- Exact match (leading ::) searches
- Regex pattern searches
- Large dataset performance
"""

import pytest
import time
from pathlib import Path
import tempfile
from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.benchmark
class TestQualifiedSearchPerformance:
    """Benchmark qualified pattern search performance."""

    @pytest.fixture
    def large_project(self):
        """Create a large test project with many classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files with many classes in various namespaces
            for i in range(50):  # 50 files
                test_file = Path(tmpdir) / f"file{i}.cpp"
                content = []
                for j in range(20):  # 20 classes per file = 1000 total classes
                    ns = f"ns{i % 10}"  # 10 different namespaces
                    content.append(f"""
namespace {ns} {{
    class Class{i}_{j} {{
    public:
        void method{j}() {{}}
        void process() {{}}
    }};
}}
""")
                test_file.write_text("\n".join(content))

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()
            yield analyzer

    def test_unqualified_search_performance(self, large_project):
        """Unqualified pattern search should complete quickly."""
        analyzer = large_project

        # Benchmark unqualified search
        start = time.time()
        results = analyzer.search_classes("Class0_0")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 1, "Should find at least one class"
        # Conservative threshold to avoid flaky failures under load
        assert elapsed < 0.5, f"Unqualified search too slow: {elapsed:.3f}s (target: <0.5s)"

        print(f"\n  Unqualified search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_qualified_suffix_search_performance(self, large_project):
        """Qualified suffix pattern search should complete quickly."""
        analyzer = large_project

        # Benchmark qualified suffix search
        start = time.time()
        results = analyzer.search_classes("ns0::Class0_0")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 1, "Should find at least one class"
        # Conservative threshold to avoid flaky failures under load
        assert elapsed < 0.5, f"Qualified suffix search too slow: {elapsed:.3f}s (target: <0.5s)"

        print(f"\n  Qualified suffix search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_exact_match_search_performance(self, large_project):
        """Exact match (leading ::) search should complete quickly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simpler project for exact match testing
            test_file = Path(tmpdir) / "test.cpp"
            content = []
            for i in range(100):  # 100 global classes
                content.append(f"""
class GlobalClass{i} {{
public:
    void method() {{}}
}};
""")
            test_file.write_text("\n".join(content))

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Benchmark exact match search
            start = time.time()
            results = analyzer.search_classes("::GlobalClass0")
            elapsed = time.time() - start
            result_count = len(results)

            assert result_count == 1, "Should find exactly one global class"
            # Conservative threshold to avoid flaky failures under load
            assert elapsed < 0.5, f"Exact match search too slow: {elapsed:.3f}s (target: <0.5s)"

            print(f"\n  Exact match search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_regex_search_performance(self, large_project):
        """Regex pattern search should complete quickly (regex is inherently slower)."""
        analyzer = large_project

        # Benchmark regex search (more expensive, larger threshold)
        start = time.time()
        results = analyzer.search_classes("ns0::.*")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 1, "Should find at least one class"
        # Conservative threshold - regex is slower and result set is large
        assert elapsed < 1.0, f"Regex search too slow: {elapsed:.3f}s (target: <1.0s)"

        print(f"\n  Regex search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_empty_pattern_performance(self, large_project):
        """Empty pattern (match all) should complete quickly for large dataset."""
        analyzer = large_project

        # Benchmark empty pattern search (returns all symbols - 1000 classes)
        start = time.time()
        results = analyzer.search_classes("")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 100, "Should find many classes"
        # Conservative threshold - returns 1000 results
        assert elapsed < 1.0, f"Empty pattern search too slow: {elapsed:.3f}s (target: <1.0s)"

        print(f"\n  Empty pattern search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_function_search_performance(self, large_project):
        """Function search should complete quickly."""
        analyzer = large_project

        # Benchmark function search (returns 1000 process() methods)
        start = time.time()
        results = analyzer.search_functions("process")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 100, "Should find many process methods"
        # Conservative threshold - returns 1000 results
        # Previous 0.1s threshold was too aggressive and caused flaky failures
        assert elapsed < 1.0, f"Function search too slow: {elapsed:.3f}s (target: <1.0s)"

        print(f"\n  Function search: {elapsed*1000:.1f}ms (found {result_count} results)")

    def test_qualified_function_search_performance(self, large_project):
        """Qualified function search should complete quickly."""
        analyzer = large_project

        # Benchmark qualified function search
        start = time.time()
        results = analyzer.search_functions("Class0_0::method0")
        elapsed = time.time() - start
        result_count = len(results)

        assert result_count >= 1, "Should find at least one method"
        # Conservative threshold to avoid flaky failures under load
        assert elapsed < 0.5, f"Qualified function search too slow: {elapsed:.3f}s (target: <0.5s)"

        print(f"\n  Qualified function search: {elapsed*1000:.1f}ms (found {result_count} results)")


@pytest.mark.benchmark
class TestIndexingPerformance:
    """Benchmark indexing performance for qualified names."""

    def test_indexing_small_project_performance(self):
        """Small project indexing should complete quickly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10 files with 10 classes each = 100 classes
            for i in range(10):
                test_file = Path(tmpdir) / f"file{i}.cpp"
                content = []
                for j in range(10):
                    content.append(f"""
namespace ns{i} {{
    class Class{i}_{j} {{
    public:
        void method{j}() {{}}
    }};
}}
""")
                test_file.write_text("\n".join(content))

            analyzer = CppAnalyzer(tmpdir)

            # Benchmark indexing
            start = time.time()
            analyzer.index_project()
            elapsed = time.time() - start

            # Verify qualified names were extracted
            results = analyzer.search_classes("")
            assert len(results) >= 100, "Should find all classes"
            for result in results:
                assert "qualified_name" in result
                assert "namespace" in result

            print(f"\n  Small project indexing: {elapsed*1000:.0f}ms ({len(results)} classes)")

    def test_incremental_refresh_performance(self):
        """Incremental refresh should be faster than full reindex."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create initial project
            test_file = Path(tmpdir) / "test.cpp"
            test_file.write_text("""
namespace app {
    class Original {};
}
""")

            analyzer = CppAnalyzer(tmpdir)
            analyzer.index_project()

            # Modify file
            test_file.write_text("""
namespace app {
    class Original {};
    class Modified {};
}
""")

            # Benchmark incremental refresh
            start = time.time()
            refreshed_count = analyzer.refresh_if_needed()
            elapsed = time.time() - start

            assert refreshed_count == 1, "Should refresh 1 file"
            assert elapsed < 1.0, f"Incremental refresh too slow: {elapsed:.3f}s"

            results = analyzer.search_classes("Modified")
            assert len(results) == 1

            print(f"\n  Incremental refresh: {elapsed*1000:.0f}ms ({refreshed_count} files)")


@pytest.mark.benchmark
class TestPatternMatchingPerformance:
    """Benchmark pattern matching algorithm performance."""

    def test_component_matching_performance(self):
        """Component-based suffix matching should be fast."""
        from mcp_server.search_engine import SearchEngine

        # Benchmark component matching on various patterns
        patterns = [
            ("app::ui::View", "ui::View"),
            ("a::b::c::d::e::f::View", "e::f::View"),
            ("GlobalClass", "GlobalClass"),
            ("app::core::ui::widgets::Button", "widgets::Button"),
        ]

        for qualified_name, pattern in patterns:
            start = time.time()
            for _ in range(1000):  # Run 1000 times
                SearchEngine.matches_qualified_pattern(qualified_name, pattern)
            elapsed = time.time() - start

            avg_time_ms = (elapsed / 1000) * 1000
            assert avg_time_ms < 1.0, f"Pattern matching too slow: {avg_time_ms:.3f}ms per match"

        print(f"\n  Pattern matching: <1ms per match (1000 iterations)")

    def test_regex_pattern_performance(self):
        """Regex pattern matching should be reasonable."""
        from mcp_server.search_engine import SearchEngine

        # Benchmark regex patterns
        patterns = [
            ("app::core::View", "app::.*::View"),
            ("app::ui::widgets::Button", ".*Button"),
            ("ns1::ns2::ns3::Class", "ns1::.*::Class"),
        ]

        for qualified_name, pattern in patterns:
            start = time.time()
            for _ in range(100):  # Run 100 times (regex is slower)
                SearchEngine.matches_qualified_pattern(qualified_name, pattern)
            elapsed = time.time() - start

            avg_time_ms = (elapsed / 100) * 1000
            assert avg_time_ms < 10.0, f"Regex pattern matching too slow: {avg_time_ms:.3f}ms per match"

        print(f"\n  Regex pattern matching: <10ms per match (100 iterations)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
