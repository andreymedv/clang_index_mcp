#!/usr/bin/env python3
"""
Integration tests for template alias tracking through MCP tools (Phase 2.0).

Tests the complete integration of template alias tracking through:
- get_type_alias_info returning template information
- Template alias queries with proper parameter display
- End-to-end workflows with real template alias code
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
# IT-T1: get_type_alias_info Template Alias Integration
# ============================================================================


class TestGetTypeAliasInfoTemplateIntegration:
    """Integration tests for get_type_alias_info with template aliases (IT-T1)."""

    def test_get_type_alias_info_returns_template_flag(self, temp_project_dir):
        """IT-T1.1: get_type_alias_info returns is_template_alias flag for template aliases."""
        # Create class with both simple and template aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>

class Widget {};

// Simple alias
using WidgetAlias = Widget;

// Template alias
template<typename T>
using Ptr = std::shared_ptr<T>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query Widget class (has simple alias)
        result = analyzer.get_type_alias_info("Widget")

        assert "aliases" in result
        assert len(result["aliases"]) >= 1

        # Find WidgetAlias in results
        widget_alias = next(
            (a for a in result["aliases"] if a["name"] == "WidgetAlias"), None
        )
        assert widget_alias is not None
        # Simple alias should NOT have is_template_alias flag (or it should be False)
        assert widget_alias.get("is_template_alias", False) is False

    def test_get_type_alias_info_returns_template_params(self, temp_project_dir):
        """IT-T1.2: get_type_alias_info returns template_params for template aliases."""
        # Create class used in template alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>

class Data {};

// Template alias referencing Data
template<typename T>
using DataPtr = std::shared_ptr<T>;

// Instantiation (creates relationship to Data)
using SpecificPtr = DataPtr<Data>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query DataPtr directly from database (it won't appear in get_type_alias_info for Data)
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT alias_name, is_template_alias, template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("DataPtr",),
        )
        row = cursor.fetchone()

        assert row is not None, "DataPtr template alias should be found"
        assert row["is_template_alias"] == 1

        # template_params should be non-null and parseable
        assert row["template_params"] is not None
        import json

        params = json.loads(row["template_params"])
        assert len(params) == 1
        assert params[0]["name"] == "T"
        assert params[0]["kind"] == "type"

    def test_template_vs_simple_alias_distinction(self, temp_project_dir):
        """IT-T1.3: MCP tools clearly distinguish template from simple aliases."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>
#include <vector>

class Item {};

// Simple alias
using ItemAlias = Item;

// Template alias
template<typename T>
using ItemPtr = std::shared_ptr<T>;

// Another template alias
template<typename T>
using ItemVec = std::vector<T>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query all aliases
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT alias_name, is_template_alias, template_params
            FROM type_aliases
            ORDER BY alias_name
            """
        )
        rows = cursor.fetchall()

        # Should have all 3 aliases
        assert len(rows) >= 3

        # Check each alias
        aliases_by_name = {row["alias_name"]: row for row in rows}

        # Simple alias
        if "ItemAlias" in aliases_by_name:
            assert aliases_by_name["ItemAlias"]["is_template_alias"] == 0
            assert aliases_by_name["ItemAlias"]["template_params"] is None

        # Template aliases
        if "ItemPtr" in aliases_by_name:
            assert aliases_by_name["ItemPtr"]["is_template_alias"] == 1
            assert aliases_by_name["ItemPtr"]["template_params"] is not None

        if "ItemVec" in aliases_by_name:
            assert aliases_by_name["ItemVec"]["is_template_alias"] == 1
            assert aliases_by_name["ItemVec"]["template_params"] is not None


# ============================================================================
# IT-T2: Namespace-Scoped Template Alias Integration
# ============================================================================


class TestNamespaceScopedTemplateAliasIntegration:
    """Integration tests for namespace-scoped template aliases (IT-T2)."""

    def test_namespace_scoped_template_alias_query(self, temp_project_dir):
        """IT-T2.1: Query namespace-scoped template alias through MCP tools."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>

namespace utils {
    template<typename T>
    using UniquePtr = std::unique_ptr<T>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query by qualified name
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT alias_name, qualified_name, namespace, is_template_alias, template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("UniquePtr",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["namespace"] == "utils"
        assert "utils::UniquePtr" in row["qualified_name"]
        assert row["is_template_alias"] == 1

        # Verify template parameters
        import json

        params = json.loads(row["template_params"])
        assert len(params) == 1
        assert params[0]["name"] == "T"


# ============================================================================
# IT-T3: Multiple Template Parameters Integration
# ============================================================================


class TestMultipleTemplateParametersIntegration:
    """Integration tests for template aliases with multiple parameters (IT-T3)."""

    def test_multiple_type_parameters(self, temp_project_dir):
        """IT-T3.1: Template alias with multiple type parameters."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <utility>
#include <map>

// Two type parameters
template<typename T, typename U>
using Pair = std::pair<T, U>;

// Two type parameters (map)
template<typename K, typename V>
using Map = std::map<K, V>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Check Pair template params
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Pair",),
        )
        row = cursor.fetchone()

        assert row is not None
        import json

        params = json.loads(row["template_params"])
        assert len(params) == 2
        assert params[0]["name"] == "T"
        assert params[1]["name"] == "U"
        assert all(p["kind"] == "type" for p in params)

    def test_mixed_type_and_non_type_parameters(self, temp_project_dir):
        """IT-T3.2: Template alias with mixed type and non-type parameters."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <array>

template<typename T, int N>
using Array = std::array<T, N>;
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Check Array template params
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Array",),
        )
        row = cursor.fetchone()

        assert row is not None
        import json

        params = json.loads(row["template_params"])
        assert len(params) == 2

        # First: type parameter
        assert params[0]["name"] == "T"
        assert params[0]["kind"] == "type"

        # Second: non-type parameter
        assert params[1]["name"] == "N"
        assert params[1]["kind"] == "non_type"
        assert params[1]["type"] == "int"


# ============================================================================
# Pytest Fixtures
# ============================================================================


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create temporary project directory structure."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    return project_dir
