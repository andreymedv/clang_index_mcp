#!/usr/bin/env python3
"""
Unit tests for type alias tracking (Phase 1.3).

Tests alias extraction, storage, and lookup for C++ type aliases (using/typedef).
Covers Phase 1 scope: simple non-template aliases.
"""

import os
import sys
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# ============================================================================
# UT-1: Alias Extraction Tests
# ============================================================================


class TestAliasExtraction:
    """Tests for alias extraction from C++ code (UT-1)."""

    def test_extract_using_class_alias(self, temp_project_dir):
        """UT-1.1: Extract simple class alias with 'using' syntax."""
        # Create source file with using alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify alias was extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "WidgetAlias" in aliases
        assert aliases["WidgetAlias"] == "Widget"

    def test_extract_typedef_class_alias(self, temp_project_dir):
        """UT-1.2: Extract simple class alias with 'typedef' syntax."""
        # Create source file with typedef alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Button {};
typedef Button ButtonAlias;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify alias was extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "ButtonAlias" in aliases
        assert aliases["ButtonAlias"] == "Button"

    def test_extract_pointer_type_alias(self, temp_project_dir):
        """UT-1.3: Extract pointer type alias."""
        # Create source file with pointer alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Data {};
using DataPtr = Data*;
typedef Data* DataPointer;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify pointer aliases were extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "DataPtr" in aliases
        assert "DataPointer" in aliases
        # Both should resolve to "Data *" (with space from libclang)
        assert aliases["DataPtr"] == "Data *"
        assert aliases["DataPointer"] == "Data *"

    def test_extract_reference_type_alias(self, temp_project_dir):
        """UT-1.4: Extract reference type alias."""
        # Create source file with reference alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Data {};
using DataRef = Data&;
typedef Data& DataReference;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify reference aliases were extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "DataRef" in aliases
        assert "DataReference" in aliases
        assert aliases["DataRef"] == "Data &"
        assert aliases["DataReference"] == "Data &"

    def test_extract_builtin_type_alias(self, temp_project_dir):
        """UT-1.5: Extract built-in type alias."""
        # Create source file with built-in type aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
using size_type = unsigned long;
typedef int int32_t;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify built-in type aliases were extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "size_type" in aliases
        assert "int32_t" in aliases
        assert aliases["size_type"] == "unsigned long"
        assert aliases["int32_t"] == "int"

    def test_extract_stl_type_alias(self, temp_project_dir):
        """UT-1.6: Extract STL type alias."""
        # Create source file with STL type alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <functional>
#include <vector>
#include <string>

using ErrorCallback = std::function<void(int)>;
using StringVector = std::vector<std::string>;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify STL type aliases were extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "ErrorCallback" in aliases
        assert "StringVector" in aliases
        # Check that it resolves to STL types (exact spelling may vary)
        assert "function" in aliases["ErrorCallback"]
        assert "vector" in aliases["StringVector"]

    def test_extract_alias_chain(self, temp_project_dir):
        """UT-1.7: Extract alias chain (A -> B -> C)."""
        # Create source file with alias chain
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class RealClass {};
using AliasOne = RealClass;
using AliasTwo = AliasOne;
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify alias chain resolves to canonical type
        # libclang's get_canonical() should resolve the chain automatically
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert "AliasOne" in aliases
        assert "AliasTwo" in aliases
        # Both should resolve to RealClass (canonical type)
        assert aliases["AliasOne"] == "RealClass"
        assert aliases["AliasTwo"] == "RealClass"

    def test_extract_namespace_scoped_alias(self, temp_project_dir):
        """UT-1.8: Extract namespace-scoped alias."""
        # Create source file with namespace-scoped alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
namespace foo {
    class LocalClass {};
    using LocalAlias = LocalClass;
}

namespace bar {
    using ExternalAlias = foo::LocalClass;
}
"""
        )

        # Create compile commands
        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index and extract
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify namespace-scoped aliases were extracted
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        # Should have both short and qualified names
        assert "LocalAlias" in aliases or "foo::LocalAlias" in aliases
        assert "ExternalAlias" in aliases or "bar::ExternalAlias" in aliases


# ============================================================================
# UT-2: Alias Storage Tests
# ============================================================================


class TestAliasStorage:
    """Tests for alias storage in SQLite (UT-2)."""

    def test_store_single_alias(self, temp_project_dir):
        """UT-2.1: Store single type alias in database."""
        # Create simple alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify stored in database
        canonical = analyzer.cache_manager.get_canonical_for_alias("WidgetAlias")
        assert canonical == "Widget"

    def test_store_multiple_aliases(self, temp_project_dir):
        """UT-2.2: Store multiple type aliases in batch."""
        # Create multiple aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
class Button {};
class Data {};

using WidgetAlias = Widget;
using ButtonAlias = Button;
using DataPtr = Data*;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify all stored
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert len(aliases) >= 3
        assert "WidgetAlias" in aliases
        assert "ButtonAlias" in aliases
        assert "DataPtr" in aliases

    def test_alias_persistence(self, temp_project_dir):
        """UT-2.3: Verify aliases persist across analyzer instances."""
        # Create alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index with first analyzer
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        analyzer1.index_project()
        analyzer1.close()

        # Create second analyzer (should load from cache)
        analyzer2 = CppAnalyzer(str(temp_project_dir))

        # Verify aliases are still accessible
        canonical = analyzer2.cache_manager.get_canonical_for_alias("WidgetAlias")
        assert canonical == "Widget"
        analyzer2.close()


# ============================================================================
# UT-3: Alias Lookup Tests
# ============================================================================


class TestAliasLookup:
    """Tests for alias lookup methods (UT-3)."""

    def test_get_canonical_for_alias(self, temp_project_dir):
        """UT-3.1: Lookup canonical type for alias name."""
        # Create alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class RealClass {};
using AliasName = RealClass;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Lookup canonical type
        canonical = analyzer.cache_manager.get_canonical_for_alias("AliasName")
        assert canonical == "RealClass"

    def test_get_aliases_for_canonical(self, temp_project_dir):
        """UT-3.2: Find all aliases pointing to a canonical type."""
        # Create multiple aliases for same type
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
using WidgetPtr = Widget*;
typedef Widget WidgetType;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Find all aliases for Widget
        aliases = analyzer.cache_manager.get_aliases_for_canonical("Widget")
        # Should have at least WidgetAlias and WidgetType (WidgetPtr is Widget*, not Widget)
        assert "WidgetAlias" in aliases or any("WidgetAlias" in a for a in aliases)
        assert "WidgetType" in aliases or any("WidgetType" in a for a in aliases)

    def test_lookup_nonexistent_alias(self, temp_project_dir):
        """UT-3.3: Lookup returns None for nonexistent alias."""
        # Create empty project
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Lookup nonexistent alias
        canonical = analyzer.cache_manager.get_canonical_for_alias("NonexistentAlias")
        assert canonical is None

    def test_lookup_empty_result(self, temp_project_dir):
        """UT-3.4: Lookup returns empty list for canonical type with no aliases."""
        # Create class without aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Find aliases for Widget (should be empty)
        aliases = analyzer.cache_manager.get_aliases_for_canonical("Widget")
        assert isinstance(aliases, list)
        assert len(aliases) == 0


# ============================================================================
# UT-4: Search Engine Type Expansion Tests
# ============================================================================


class TestSearchEngineTypeExpansion:
    """Tests for search engine type expansion infrastructure (UT-4)."""

    def test_expand_alias_to_canonical(self, temp_project_dir):
        """UT-4.1: Expand alias name to include canonical type."""
        # Create alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Expand alias name
        expanded = analyzer.search_engine.expand_type_name("WidgetAlias")
        assert "WidgetAlias" in expanded  # Original
        assert "Widget" in expanded  # Canonical

    def test_expand_canonical_to_aliases(self, temp_project_dir):
        """UT-4.2: Expand canonical type to include aliases."""
        # Create aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetAlias = Widget;
typedef Widget WidgetType;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Expand canonical type
        expanded = analyzer.search_engine.expand_type_name("Widget")
        assert "Widget" in expanded  # Original
        # Should include at least one alias
        assert "WidgetAlias" in expanded or "WidgetType" in expanded

    def test_expand_without_aliases(self, temp_project_dir):
        """UT-4.3: Expand returns only original name if no aliases exist."""
        # Create class without aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Expand type with no aliases
        expanded = analyzer.search_engine.expand_type_name("Widget")
        assert expanded == ["Widget"]


# ============================================================================
# UT-5: Edge Cases and Error Handling
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling (UT-5)."""

    def test_empty_project(self, temp_project_dir):
        """UT-5.1: Handle project with no aliases."""
        # Create empty source file
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify no aliases
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert len(aliases) == 0

    def test_malformed_alias(self, temp_project_dir):
        """UT-5.2: Handle malformed alias gracefully."""
        # Create source with intentional syntax error in alias
        # (This should be caught by libclang, not crash the analyzer)
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using BrokenAlias =   // Missing target type
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index (should not crash)
        analyzer = CppAnalyzer(str(temp_project_dir))
        result = analyzer.index_project()

        # Should succeed despite parsing error (continue-on-error behavior)
        assert result is not None

    def test_duplicate_alias_names(self, temp_project_dir):
        """UT-5.3: Handle duplicate alias names in different namespaces."""
        # Create aliases with same name in different namespaces
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
namespace foo {
    class Widget {};
    using Alias = Widget;
}

namespace bar {
    class Button {};
    using Alias = Button;
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        # Index
        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Both aliases should be stored with qualified names
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        # Should have entries for both foo::Alias and bar::Alias
        assert len(aliases) >= 2
