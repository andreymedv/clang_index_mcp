"""
Test macro-generated type aliases.

Verifies that type aliases created via C++ macros are properly indexed
and can be queried via get_type_alias_info.

Issue: Macro-generated type aliases like:
    #define DECL_UNIQUE_PTRS(name) using name##UPtr = std::unique_ptr<name>
    DECL_UNIQUE_PTRS(DataBuilder)

were not being indexed, even though libclang correctly exposes them.
"""

import os
import pytest
import shutil

from mcp_server.cpp_analyzer import CppAnalyzer


class TestMacroTypeAlias:
    """Test suite for macro-generated type alias indexing."""

    @pytest.fixture
    def macro_alias_project(self, tmp_path):
        """Create a test project with macro-generated type aliases."""
        # Copy the macro_alias fixtures to temp directory
        fixture_dir = os.path.join(
            os.path.dirname(__file__), "fixtures", "macro_alias"
        )

        # Copy all files
        for filename in os.listdir(fixture_dir):
            src = os.path.join(fixture_dir, filename)
            dst = os.path.join(tmp_path, filename)
            shutil.copy2(src, dst)

        return str(tmp_path)

    @pytest.fixture
    def analyzer(self, macro_alias_project):
        """Create and initialize analyzer for the test project."""
        analyzer = CppAnalyzer(macro_alias_project)
        analyzer.index_project()
        yield analyzer
        analyzer.close()

    def test_macro_type_alias_indexed(self, analyzer):
        """Test that macro-expanded type aliases are indexed."""
        # Get type alias info for DataBuilderUPtr
        result = analyzer.get_type_alias_info("DataBuilderUPtr")

        # Should NOT have an error - the type alias should be found
        assert "error" not in result or "not found" not in result.get("error", "").lower(), (
            f"DataBuilderUPtr should be found, but got: {result}"
        )

    def test_macro_type_alias_canonical(self, analyzer):
        """Test that macro-expanded type alias has correct canonical type."""
        result = analyzer.get_type_alias_info("DataBuilderUPtr")

        if "error" not in result:
            # Should resolve to unique_ptr<DataBuilder, ...>
            canonical = result.get("canonical_type", "")
            assert "unique_ptr" in canonical.lower() or "DataBuilder" in canonical, (
                f"Canonical type should contain unique_ptr or DataBuilder, got: {canonical}"
            )

    def test_macro_type_alias_in_search(self, analyzer):
        """Test that macro-expanded type aliases appear in search results."""
        # Search for functions using DataBuilderUPtr in signature
        functions = analyzer.search_functions("builder")

        # Find the builder method
        builder_funcs = [f for f in functions if "DataBuilder" in f.get("qualified_name", "")]

        # At least one should have DataBuilderUPtr in signature
        has_uptr_return = any(
            "DataBuilderUPtr" in f.get("signature", "")
            for f in builder_funcs
        )

        assert has_uptr_return, (
            f"Expected DataBuilder::builder to return DataBuilderUPtr, "
            f"found: {[f.get('signature') for f in builder_funcs]}"
        )

    def test_macro_type_alias_const_variant(self, analyzer):
        """Test that both UPtr and ConstUPtr variants are indexed."""
        # The macro creates both name##UPtr and name##ConstUPtr
        result_uptr = analyzer.get_type_alias_info("DataBuilderUPtr")
        result_const = analyzer.get_type_alias_info("DataBuilderConstUPtr")

        # Both should be found
        uptr_found = "error" not in result_uptr or "not found" not in result_uptr.get("error", "").lower()
        const_found = "error" not in result_const or "not found" not in result_const.get("error", "").lower()

        assert uptr_found, f"DataBuilderUPtr should be found: {result_uptr}"
        assert const_found, f"DataBuilderConstUPtr should be found: {result_const}"

    def test_macro_type_alias_file_location(self, analyzer, macro_alias_project):
        """Test that macro-expanded type alias is reported at expansion site, not definition."""
        # Query the cache directly to check file location
        aliases = analyzer.cache_manager.backend.conn.execute(
            "SELECT alias_name, file, line FROM type_aliases WHERE alias_name = ?",
            ("DataBuilderUPtr",)
        ).fetchall()

        assert len(aliases) > 0, "DataBuilderUPtr should be in the cache"

        # The file should be textbuilder_fwd.h (where macro is expanded)
        # NOT macros.h (where macro is defined)
        for alias in aliases:
            file_path = alias["file"]
            assert "textbuilder_fwd.h" in file_path, (
                f"DataBuilderUPtr should be at expansion site (textbuilder_fwd.h), "
                f"not macro definition. Found: {file_path}"
            )


class TestMacroTypeAliasDebug:
    """Debug tests to understand the issue."""

    @pytest.fixture
    def macro_alias_project(self, tmp_path):
        """Create a test project with macro-generated type aliases."""
        fixture_dir = os.path.join(
            os.path.dirname(__file__), "fixtures", "macro_alias"
        )
        for filename in os.listdir(fixture_dir):
            src = os.path.join(fixture_dir, filename)
            dst = os.path.join(tmp_path, filename)
            shutil.copy2(src, dst)
        return str(tmp_path)

    @pytest.fixture
    def analyzer(self, macro_alias_project):
        """Create and initialize analyzer for the test project."""
        analyzer = CppAnalyzer(macro_alias_project)
        analyzer.index_project()
        yield analyzer
        analyzer.close()

    def test_debug_all_indexed_aliases(self, analyzer):
        """Debug: Print all indexed type aliases."""
        # Query all aliases from the cache
        aliases = analyzer.cache_manager.backend.conn.execute(
            "SELECT alias_name, qualified_name, canonical_type, file, line FROM type_aliases"
        ).fetchall()

        print(f"\n=== All indexed type aliases ({len(aliases)}) ===")
        for alias in aliases:
            print(f"  {alias['alias_name']}")
            print(f"    qualified_name: {alias['qualified_name']}")
            print(f"    canonical_type: {alias['canonical_type']}")
            print(f"    file: {alias['file']}")
            print(f"    line: {alias['line']}")
            print()

        # This test is for debugging - always passes
        # Look at the output to understand what's being indexed
        assert True

    def test_debug_indexed_files(self, analyzer):
        """Debug: Print all indexed files."""
        files = list(analyzer.file_index.keys())
        print(f"\n=== All indexed files ({len(files)}) ===")
        for f in sorted(files):
            print(f"  {f}")

        assert True

    def test_debug_header_tracking(self, analyzer):
        """Debug: Print header tracking state."""
        headers = analyzer.cache_manager.backend.conn.execute(
            "SELECT header_path, processed_by FROM header_tracker"
        ).fetchall()

        print(f"\n=== Header tracking ({len(headers)}) ===")
        for h in headers:
            print(f"  {h['header_path']}")
            print(f"    processed_by: {h['processed_by']}")
            print()

        assert True
