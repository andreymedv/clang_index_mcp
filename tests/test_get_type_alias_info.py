#!/usr/bin/env python3
"""
Unit tests for get_type_alias_info method (Phase 1.6 - MCP Tool Integration).

Tests the comprehensive type alias information retrieval including:
- Canonical type resolution
- Alias lookup
- Ambiguity detection
- Qualified name pattern matching
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
# Success Cases: Canonical Type Input
# ============================================================================


class TestCanonicalTypeInput:
    """Tests for get_type_alias_info with canonical type as input."""

    def test_canonical_type_with_aliases(self, temp_project_dir):
        """Query canonical type that has aliases."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
public:
    void show();
};

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

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query canonical type
        result = analyzer.get_type_alias_info("Widget")

        # Verify result structure
        assert "canonical_type" in result
        assert "qualified_name" in result
        assert "namespace" in result
        assert "file" in result
        assert "line" in result
        assert "input_was_alias" in result
        assert "is_ambiguous" in result
        assert "aliases" in result

        # Verify values
        assert result["canonical_type"] == "Widget"
        assert result["input_was_alias"] is False
        assert result["is_ambiguous"] is False
        assert len(result["aliases"]) == 2  # WidgetAlias and WidgetType

        # Verify alias details
        alias_names = [a["name"] for a in result["aliases"]]
        assert "WidgetAlias" in alias_names
        assert "WidgetType" in alias_names

        # Each alias should have file and line
        for alias in result["aliases"]:
            assert "file" in alias
            assert "line" in alias
            assert "qualified_name" in alias

    def test_canonical_type_without_aliases(self, temp_project_dir):
        """Query canonical type that has no aliases."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
public:
    void show();
};
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

        # Query canonical type
        result = analyzer.get_type_alias_info("Widget")

        # Verify result
        assert result["canonical_type"] == "Widget"
        assert result["input_was_alias"] is False
        assert result["is_ambiguous"] is False
        assert len(result["aliases"]) == 0

    def test_qualified_canonical_type(self, temp_project_dir):
        """Query qualified canonical type name."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
namespace ui {
    class Widget {
    public:
        void show();
    };

    using WidgetAlias = Widget;
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

        # Query with qualified name
        result = analyzer.get_type_alias_info("ui::Widget")

        # Verify result
        assert result["qualified_name"] == "ui::Widget"
        assert result["namespace"] == "ui"
        assert result["input_was_alias"] is False
        assert result["is_ambiguous"] is False
        assert len(result["aliases"]) >= 1


# ============================================================================
# Success Cases: Alias Input
# ============================================================================


class TestAliasInput:
    """Tests for get_type_alias_info with alias as input."""

    def test_alias_resolves_to_canonical(self, temp_project_dir):
        """Query alias name, should resolve to canonical type."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};

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

        # Query by alias name
        result = analyzer.get_type_alias_info("WidgetAlias")

        # Verify resolution
        assert result["canonical_type"] == "Widget"
        assert result["input_was_alias"] is True
        assert result["is_ambiguous"] is False

        # Should include the queried alias in results
        alias_names = [a["name"] for a in result["aliases"]]
        assert "WidgetAlias" in alias_names

    def test_alias_chain_resolution(self, temp_project_dir):
        """Query alias in chain, should resolve to ultimate canonical type."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class RealClass {
};

using AliasOne = RealClass;
using AliasTwo = AliasOne;
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

        # Query final alias in chain
        result = analyzer.get_type_alias_info("AliasTwo")

        # Should resolve to RealClass (libclang's get_canonical)
        assert result["canonical_type"] == "RealClass"
        assert result["input_was_alias"] is True
        assert result["is_ambiguous"] is False

        # Should include both aliases
        alias_names = [a["name"] for a in result["aliases"]]
        assert "AliasOne" in alias_names
        assert "AliasTwo" in alias_names


# ============================================================================
# Ambiguity Detection
# ============================================================================


class TestAmbiguityDetection:
    """Tests for ambiguous type name detection."""

    def test_ambiguous_unqualified_name(self, temp_project_dir):
        """Unqualified name matching multiple types should return ambiguity error."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};

namespace ui {
    class Widget {
    };
}

namespace app {
    class Widget {
    };
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

        # Query unqualified name (ambiguous)
        result = analyzer.get_type_alias_info("Widget")

        # Should return ambiguity error
        assert "error" in result
        assert result["is_ambiguous"] is True
        assert "matches" in result
        assert len(result["matches"]) >= 2  # At least 2 different Widgets
        assert "suggestion" in result

        # Verify matches structure
        for match in result["matches"]:
            assert "canonical_type" in match
            assert "qualified_name" in match
            assert "namespace" in match
            assert "file" in match
            assert "line" in match

    def test_qualified_name_disambiguates(self, temp_project_dir):
        """Qualified name should disambiguate successfully."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};

namespace ui {
    class Widget {
    };
    using WidgetAlias = Widget;
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

        # Query with qualified name (not ambiguous)
        result = analyzer.get_type_alias_info("ui::Widget")

        # Should succeed
        assert "error" not in result
        assert result["is_ambiguous"] is False
        assert result["qualified_name"] == "ui::Widget"
        assert result["namespace"] == "ui"


# ============================================================================
# Error Cases
# ============================================================================


class TestErrorCases:
    """Tests for error handling."""

    def test_type_not_found(self, temp_project_dir):
        """Non-existent type should return not found error."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};
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

        # Query non-existent type
        result = analyzer.get_type_alias_info("NonexistentType")

        # Should return error
        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["canonical_type"] is None
        assert result["aliases"] == []

    def test_empty_project(self, temp_project_dir):
        """Query on empty project should return not found."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
// Empty file
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

        # Query any type
        result = analyzer.get_type_alias_info("AnyType")

        # Should return not found
        assert "error" in result
        assert result["canonical_type"] is None
        assert result["aliases"] == []


# ============================================================================
# Pattern Matching
# ============================================================================


class TestPatternMatching:
    """Tests for qualified pattern matching support."""

    def test_exact_global_namespace(self, temp_project_dir):
        """Leading :: should match only global namespace."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};

namespace ui {
    class Widget {
    };
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

        # Query with leading :: (exact global match)
        result = analyzer.get_type_alias_info("::Widget")

        # Should match only global Widget
        assert "error" not in result
        assert result["namespace"] == ""
        assert result["is_ambiguous"] is False

    def test_partial_qualification(self, temp_project_dir):
        """Partially qualified name should use component suffix matching."""
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
namespace app {
    namespace ui {
        class Widget {
        };
        using WidgetAlias = Widget;
    }
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

        # Query with partial qualification
        result = analyzer.get_type_alias_info("ui::Widget")

        # Should match app::ui::Widget (suffix matching)
        assert "error" not in result
        assert result["qualified_name"] == "app::ui::Widget"
        assert result["is_ambiguous"] is False
