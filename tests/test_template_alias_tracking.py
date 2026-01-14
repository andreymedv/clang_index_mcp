#!/usr/bin/env python3
"""
Unit tests for template alias tracking (Phase 2.0).

Tests template alias extraction, storage, and parameter handling for C++ template
type aliases (template using declarations).
"""

import os
import sys
import json
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# ============================================================================
# UT-T1: Template Alias Detection Tests
# ============================================================================


class TestTemplateAliasDetection:
    """Tests for template alias detection (UT-T1)."""

    def test_detect_simple_template_alias(self, temp_project_dir):
        """UT-T1.1: Detect simple template alias with single type parameter."""
        # Create source file with template alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>
template<typename T>
using Ptr = std::shared_ptr<T>;
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

        # Query database directly to check is_template_alias flag
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT alias_name, is_template_alias, template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Ptr",),
        )
        row = cursor.fetchone()

        assert row is not None, "Template alias 'Ptr' should be extracted"
        assert row["is_template_alias"] == 1, "is_template_alias should be True"
        assert row["template_params"] is not None, "template_params should not be None"

    def test_distinguish_template_from_simple_alias(self, temp_project_dir):
        """UT-T1.2: Distinguish between template and simple aliases."""
        # Create source file with both types
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>

// Simple alias
class Widget {};
using WidgetAlias = Widget;

// Template alias
template<typename T>
using Ptr = std::shared_ptr<T>;
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

        # Check both aliases
        analyzer.cache_manager.backend._ensure_connected()

        # Check simple alias
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT is_template_alias
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("WidgetAlias",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["is_template_alias"] == 0, "WidgetAlias should NOT be template alias"

        # Check template alias
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT is_template_alias
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Ptr",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["is_template_alias"] == 1, "Ptr should be template alias"


# ============================================================================
# UT-T2: Template Parameter Extraction Tests
# ============================================================================


class TestTemplateParameterExtraction:
    """Tests for template parameter extraction (UT-T2)."""

    def test_extract_single_type_parameter(self, temp_project_dir):
        """UT-T2.1: Extract single type parameter."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>
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

        # Query template parameters
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Ptr",),
        )
        row = cursor.fetchone()

        assert row is not None
        params = json.loads(row["template_params"])
        assert len(params) == 1
        assert params[0]["name"] == "T"
        assert params[0]["kind"] == "type"

    def test_extract_multiple_type_parameters(self, temp_project_dir):
        """UT-T2.2: Extract multiple type parameters."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <utility>
template<typename T, typename U>
using Pair = std::pair<T, U>;
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

        # Query template parameters
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
        params = json.loads(row["template_params"])
        assert len(params) == 2
        assert params[0]["name"] == "T"
        assert params[0]["kind"] == "type"
        assert params[1]["name"] == "U"
        assert params[1]["kind"] == "type"

    def test_extract_non_type_parameter(self, temp_project_dir):
        """UT-T2.3: Extract non-type template parameter."""
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

        # Query template parameters
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
        params = json.loads(row["template_params"])
        assert len(params) == 2
        # First parameter: type
        assert params[0]["name"] == "T"
        assert params[0]["kind"] == "type"
        # Second parameter: non-type
        assert params[1]["name"] == "N"
        assert params[1]["kind"] == "non_type"
        assert params[1]["type"] == "int"

    def test_extract_variadic_template_parameter(self, temp_project_dir):
        """UT-T2.4: Extract variadic template parameter."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <tuple>
template<typename... Args>
using Tuple = std::tuple<Args...>;
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

        # Query template parameters
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Tuple",),
        )
        row = cursor.fetchone()

        assert row is not None
        params = json.loads(row["template_params"])
        assert len(params) == 1
        # Variadic parameter name includes "Args" (may or may not include "...")
        assert "Args" in params[0]["name"]
        assert params[0]["kind"] == "type"


# ============================================================================
# UT-T3: Template Alias Target Type Tests
# ============================================================================


class TestTemplateAliasTargetType:
    """Tests for template alias target type extraction (UT-T3)."""

    def test_extract_template_alias_target(self, temp_project_dir):
        """UT-T3.1: Extract target type from template alias."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <memory>
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

        # Query target type
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT target_type, canonical_type
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("Ptr",),
        )
        row = cursor.fetchone()

        assert row is not None
        # Target type should reference the template parameter
        assert "shared_ptr" in row["target_type"] or "T" in row["target_type"]


# ============================================================================
# UT-T4: Namespace-Scoped Template Alias Tests
# ============================================================================


class TestNamespaceScopedTemplateAlias:
    """Tests for namespace-scoped template aliases (UT-T4)."""

    def test_namespace_scoped_template_alias(self, temp_project_dir):
        """UT-T4.1: Extract template alias from namespace."""
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

        # Query namespace and qualified name
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT alias_name, qualified_name, namespace, is_template_alias
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("UniquePtr",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["is_template_alias"] == 1
        assert row["namespace"] == "utils"
        assert "utils::UniquePtr" in row["qualified_name"]


# ============================================================================
# UT-T5: Database Storage Tests
# ============================================================================


class TestTemplatealiasDatabaseStorage:
    """Tests for template alias database storage (UT-T5)."""

    def test_template_params_json_format(self, temp_project_dir):
        """UT-T5.1: Verify template_params stored as valid JSON."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
#include <utility>
template<typename T, typename U>
using Pair = std::pair<T, U>;
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

        # Query and parse JSON
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
        # Should be able to parse as JSON without error
        params = json.loads(row["template_params"])
        assert isinstance(params, list)
        assert all(isinstance(p, dict) for p in params)
        assert all("name" in p and "kind" in p for p in params)

    def test_simple_alias_template_params_null(self, temp_project_dir):
        """UT-T5.2: Verify simple aliases have NULL template_params."""
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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query template_params
        analyzer.cache_manager.backend._ensure_connected()
        cursor = analyzer.cache_manager.backend.conn.execute(
            """
            SELECT template_params
            FROM type_aliases
            WHERE alias_name = ?
            """,
            ("WidgetAlias",),
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["template_params"] is None, "Simple aliases should have NULL template_params"


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
