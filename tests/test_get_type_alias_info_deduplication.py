"""
Unit tests for alias deduplication in get_type_alias_info.
Ensures that namespaced aliases and other scenarios don't result in duplicate entries.
"""

import os
import sys
from pathlib import Path
import pytest

# Add the clang_index_mcp directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


class TestAliasDeduplication:
    """Tests to verify that get_type_alias_info returns unique aliases."""

    def test_namespaced_alias_deduplication(self, temp_project_dir):
        """
        Verify that aliases in namespaces (where short name != qualified name)
        are not duplicated in the output.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("""
            namespace CO {
                class StringView { };
                using StringViewAlias = StringView;
            }
            """)

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

        # Case 1: Query by canonical type
        result_canonical = analyzer.get_type_alias_info("CO::StringView")
        assert result_canonical["canonical_type"] == "CO::StringView"

        alias_names = [a["qualified_name"] for a in result_canonical["aliases"]]
        assert len(result_canonical["aliases"]) == 1, f"Expected 1 alias, found: {alias_names}"
        assert result_canonical["aliases"][0]["qualified_name"] == "CO::StringViewAlias"

        # Case 2: Query by alias name
        result_alias = analyzer.get_type_alias_info("CO::StringViewAlias")
        assert result_alias["canonical_type"] == "CO::StringView"
        assert result_alias["input_was_alias"] is True

        alias_names = [a["qualified_name"] for a in result_alias["aliases"]]
        assert len(result_alias["aliases"]) == 1, f"Expected 1 alias, found: {alias_names}"
        assert result_alias["aliases"][0]["qualified_name"] == "CO::StringViewAlias"

    def test_multiple_aliases_deduplication(self, temp_project_dir):
        """
        Verify that when multiple distinct aliases exist, each is returned once.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("""
            class Widget { };
            using WidgetAlias = Widget;
            typedef Widget WidgetType;
            namespace ui {
                using UIWidget = ::Widget;
            }
            """)

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

        result = analyzer.get_type_alias_info("Widget")
        assert result["canonical_type"] == "Widget"

        alias_names = sorted([a["qualified_name"] for a in result["aliases"]])
        expected_names = sorted(["WidgetAlias", "WidgetType", "ui::UIWidget"])

        assert alias_names == expected_names, f"Expected {expected_names}, found: {alias_names}"
        assert len(result["aliases"]) == 3
