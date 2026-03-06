#!/usr/bin/env python3
"""Tests for consolidated tools facade.

Tests tool list validation, parameter routing, detail filtering,
and system state injection.
"""

import json
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_server"))

from mcp.types import TextContent

from mcp_server.consolidated_tools import (
    TOOL_NAMES,
    _add_system_state,
    _filter_detail_level,
    _strip_from_data,
    handle_tool_call_b,
    list_tools_b,
)


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _tc(data: Any) -> list[TextContent]:
    """Wrap data as List[TextContent] (simulates internal handler output)."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _parse_tc(result: list[TextContent]) -> Any:
    """Parse TextContent list back to Python object."""
    return json.loads(result[0].text)


# ---------------------------------------------------------------
# Tool list validation
# ---------------------------------------------------------------


class TestListToolsB:
    """Verify list_tools_b returns correct consolidated tool definitions."""

    def test_exactly_10_tools(self) -> None:
        tools = list_tools_b()
        assert len(tools) == 10

    def test_tool_names(self) -> None:
        tools = list_tools_b()
        names = [t.name for t in tools]
        assert sorted(names) == sorted(TOOL_NAMES)

    def test_all_tools_have_schemas(self) -> None:
        tools = list_tools_b()
        for tool in tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    def test_all_tools_have_descriptions(self) -> None:
        tools = list_tools_b()
        for tool in tools:
            assert tool.description
            assert len(tool.description) > 10

    def test_search_codebase_has_target_type_enum(self) -> None:
        tools = list_tools_b()
        search = [t for t in tools if t.name == "search_codebase"][0]
        props = search.inputSchema["properties"]
        assert "target_type" in props
        assert set(props["target_type"]["enum"]) == {
            "classes_and_structs_only",
            "functions_and_methods_only",
            "all_symbol_types",
        }

    def test_search_codebase_has_detail_level_enum(self) -> None:
        tools = list_tools_b()
        search = [t for t in tools if t.name == "search_codebase"][0]
        props = search.inputSchema["properties"]
        assert "output_detail_level" in props
        assert set(props["output_detail_level"]["enum"]) == {
            "signatures_only",
            "locations_and_metadata",
            "full_details_with_docs",
        }

    def test_get_functions_called_by_has_return_format_enum(self) -> None:
        tools = list_tools_b()
        tool = [t for t in tools if t.name == "get_functions_called_by"][0]
        props = tool.inputSchema["properties"]
        assert "return_format" in props
        assert set(props["return_format"]["enum"]) == {
            "function_definitions_summary",
            "function_definitions_full",
            "exact_call_line_locations",
        }

    def test_trace_execution_path_params(self) -> None:
        tools = list_tools_b()
        tool = [t for t in tools if t.name == "trace_execution_path"][0]
        assert set(tool.inputSchema["required"]) == {
            "source_function",
            "target_function",
        }

    def test_no_internal_only_tools_present(self) -> None:
        """Internal-only tools should not appear in consolidated tool list."""
        tools = list_tools_b()
        names = {t.name for t in tools}
        internal_only = {
            "search_classes",
            "search_functions",
            "search_symbols",
            "get_outgoing_calls",
            "get_incoming_calls",
            "get_call_sites",
            "get_call_path",
            "get_function_signature",
            "wait_for_indexing",
            "get_files_containing_symbol",
            "set_project_directory",
            "check_system_status",
            "refresh_project",
        }
        assert names.isdisjoint(internal_only)


# ---------------------------------------------------------------
# Output filtering
# ---------------------------------------------------------------


class TestFilterDetailLevel:
    """Test output_detail_level filtering logic."""

    def test_full_details_no_filtering(self) -> None:
        data = {
            "results": [
                {"qualified_name": "Foo", "file": "f.cpp", "brief": "A class"}
            ]
        }
        result = _filter_detail_level(_tc(data), "full_details_with_docs")
        parsed = _parse_tc(result)
        assert parsed["results"][0]["brief"] == "A class"
        assert parsed["results"][0]["file"] == "f.cpp"

    def test_locations_strips_docs(self) -> None:
        data = {
            "results": [
                {
                    "qualified_name": "Foo",
                    "file": "f.cpp",
                    "line": 10,
                    "brief": "A class",
                    "doc_comment": "Full docs",
                }
            ]
        }
        result = _filter_detail_level(_tc(data), "locations_and_metadata")
        parsed = _parse_tc(result)
        item = parsed["results"][0]
        assert "brief" not in item
        assert "doc_comment" not in item
        assert item["file"] == "f.cpp"
        assert item["line"] == 10

    def test_signatures_only_strips_locations_and_docs(self) -> None:
        data = {
            "results": [
                {
                    "qualified_name": "Foo",
                    "kind": "CLASS_DECL",
                    "file": "f.cpp",
                    "line": 10,
                    "namespace": "ns",
                    "is_project": True,
                    "brief": "A class",
                    "doc_comment": "Full docs",
                    "template_kind": None,
                }
            ]
        }
        result = _filter_detail_level(_tc(data), "signatures_only")
        parsed = _parse_tc(result)
        item = parsed["results"][0]
        assert item["qualified_name"] == "Foo"
        assert item["kind"] == "CLASS_DECL"
        assert "file" not in item
        assert "line" not in item
        assert "namespace" not in item
        assert "is_project" not in item
        assert "brief" not in item
        assert "template_kind" not in item

    def test_filters_classes_and_functions_keys(self) -> None:
        """search_symbols format: {classes: [...], functions: [...]}."""
        data = {
            "classes": [
                {"qualified_name": "A", "brief": "cls", "file": "a.h"}
            ],
            "functions": [
                {"qualified_name": "f", "brief": "fn", "file": "b.cpp"}
            ],
        }
        result = _filter_detail_level(_tc(data), "locations_and_metadata")
        parsed = _parse_tc(result)
        assert "brief" not in parsed["classes"][0]
        assert "brief" not in parsed["functions"][0]
        assert parsed["classes"][0]["file"] == "a.h"

    def test_filters_callees_key(self) -> None:
        """get_outgoing_calls format: {callees: [...]}."""
        data = {
            "callees": [
                {
                    "qualified_name": "f",
                    "file": "a.cpp",
                    "line": 5,
                    "brief": "doc",
                }
            ]
        }
        result = _filter_detail_level(_tc(data), "signatures_only")
        parsed = _parse_tc(result)
        callee = parsed["callees"][0]
        assert callee["qualified_name"] == "f"
        assert "file" not in callee
        assert "brief" not in callee

    def test_preserves_metadata(self) -> None:
        """Metadata dict should not be stripped."""
        data = {
            "results": [{"qualified_name": "X", "file": "f.h"}],
            "metadata": {"status": "indexed", "returned": 1},
        }
        result = _filter_detail_level(_tc(data), "signatures_only")
        parsed = _parse_tc(result)
        assert parsed["metadata"]["status"] == "indexed"

    def test_empty_result_passthrough(self) -> None:
        assert _filter_detail_level([], "signatures_only") == []

    def test_invalid_json_passthrough(self) -> None:
        bad = [TextContent(type="text", text="not json")]
        result = _filter_detail_level(bad, "signatures_only")
        assert result[0].text == "not json"


class TestStripFromData:
    """Test _strip_from_data helper."""

    def test_strips_from_list(self) -> None:
        data = [{"a": 1, "b": 2, "c": 3}]
        _strip_from_data(data, {"b", "c"})
        assert data == [{"a": 1}]

    def test_strips_from_dict_results(self) -> None:
        data = {"results": [{"x": 1, "y": 2}]}
        _strip_from_data(data, {"y"})
        assert data["results"] == [{"x": 1}]

    def test_ignores_non_list_values(self) -> None:
        data = {"results": "not a list", "count": 5}
        _strip_from_data(data, {"count"})
        # Should not crash, data unchanged
        assert data["results"] == "not a list"


# ---------------------------------------------------------------
# System state injection
# ---------------------------------------------------------------


class TestAddSystemState:
    """Test system_state enum injection for check_system_status."""

    @pytest.mark.parametrize(
        "state,expected_state",
        [
            ("uninitialized", "not_ready"),
            ("initializing", "not_ready"),
            ("indexing", "not_ready"),
            ("indexed", "ready"),
            ("refreshing", "partially_ready"),
            ("error", "error"),
        ],
    )
    def test_state_mapping(self, state: str, expected_state: str) -> None:
        data = {"state": state, "parsed_files": 100}
        result = _add_system_state(_tc(data))
        parsed = _parse_tc(result)
        assert parsed["system_state"] == expected_state
        assert parsed["parsed_files"] == 100  # original data preserved

    def test_unknown_state_defaults_to_not_ready(self) -> None:
        data = {"state": "some_unknown_state"}
        result = _add_system_state(_tc(data))
        parsed = _parse_tc(result)
        assert parsed["system_state"] == "not_ready"

    def test_missing_state(self) -> None:
        data = {"parsed_files": 50}
        result = _add_system_state(_tc(data))
        parsed = _parse_tc(result)
        assert parsed["system_state"] == "not_ready"

    def test_empty_input(self) -> None:
        assert _add_system_state([]) == []


# ---------------------------------------------------------------
# Handler routing tests (mocked internal dispatcher)
# ---------------------------------------------------------------


@pytest.fixture
def mock_handle_tool_call():
    """Mock _handle_tool_call to capture internal calls."""
    with patch("mcp_server.consolidated_tools._handle_tool_call") as mock:
        # Since it's used inside the module via lazy import, we need to
        # patch it at the call site in each handler. Patch at module level.
        yield mock


class TestHandleToolCallBRouting:
    """Test that handle_tool_call_b routes to correct internal handlers."""

    @pytest.mark.asyncio
    async def test_passthrough_tools(self) -> None:
        """Passthrough tools delegate to internal with same name/args."""
        passthrough = [
            "find_in_file",
            "get_class_info",
            "get_class_hierarchy",
            "get_type_alias_info",
        ]
        for tool_name in passthrough:
            with patch(
                "mcp_server.cpp_mcp_server._handle_tool_call",
                new_callable=AsyncMock,
                return_value=_tc({"result": "ok"}),
            ) as mock:
                args = {"test_key": "test_val"}
                await handle_tool_call_b(tool_name, args)
                mock.assert_called_once_with(tool_name, args)

    @pytest.mark.asyncio
    async def test_sync_project_status_adds_state(self) -> None:
        """sync_project (no args) returns status with system_state."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"state": "indexed", "parsed_files": 42}),
        ):
            result = await handle_tool_call_b("sync_project", {})
            parsed = _parse_tc(result)
            assert parsed["system_state"] == "ready"
            assert parsed["parsed_files"] == 42

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        result = await handle_tool_call_b("nonexistent_tool", {})
        assert "Error" in result[0].text
        assert "nonexistent_tool" in result[0].text


class TestSearchCodebaseRouting:
    """Test search_codebase routing to internal search tools."""

    @pytest.mark.asyncio
    async def test_classes_routes_to_search_classes(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"results": []}),
        ) as mock:
            await handle_tool_call_b(
                "search_codebase",
                {
                    "pattern": "Foo",
                    "target_type": "classes_and_structs_only",
                },
            )
            mock.assert_called_once()
            call_args = mock.call_args
            assert call_args[0][0] == "search_classes"
            assert call_args[0][1]["pattern"] == "Foo"
            assert "target_type" not in call_args[0][1]
            assert "output_detail_level" not in call_args[0][1]

    @pytest.mark.asyncio
    async def test_functions_routes_to_search_functions(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"results": []}),
        ) as mock:
            await handle_tool_call_b(
                "search_codebase",
                {
                    "pattern": "bar",
                    "target_type": "functions_and_methods_only",
                },
            )
            assert mock.call_args[0][0] == "search_functions"

    @pytest.mark.asyncio
    async def test_all_routes_to_search_symbols(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"classes": [], "functions": []}),
        ) as mock:
            await handle_tool_call_b(
                "search_codebase",
                {"pattern": "X", "target_type": "all_symbol_types"},
            )
            assert mock.call_args[0][0] == "search_symbols"

    @pytest.mark.asyncio
    async def test_default_target_type_is_all(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"classes": [], "functions": []}),
        ) as mock:
            await handle_tool_call_b("search_codebase", {"pattern": "X"})
            assert mock.call_args[0][0] == "search_symbols"

    @pytest.mark.asyncio
    async def test_schema_b_params_not_forwarded(self) -> None:
        """target_type and output_detail_level should not be in internal args."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"results": []}),
        ) as mock:
            await handle_tool_call_b(
                "search_codebase",
                {
                    "pattern": "X",
                    "target_type": "classes_and_structs_only",
                    "output_detail_level": "signatures_only",
                    "search_scope": "project_code_only",
                    "max_results": 5,
                },
            )
            forwarded = mock.call_args[0][1]
            assert "target_type" not in forwarded
            assert "output_detail_level" not in forwarded
            assert forwarded["search_scope"] == "project_code_only"
            assert forwarded["max_results"] == 5

    @pytest.mark.asyncio
    async def test_detail_level_filtering_applied(self) -> None:
        """Output should be filtered by output_detail_level."""
        raw_data = {
            "results": [
                {
                    "qualified_name": "Foo",
                    "file": "f.cpp",
                    "line": 10,
                    "brief": "doc",
                }
            ]
        }
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc(raw_data),
        ):
            result = await handle_tool_call_b(
                "search_codebase",
                {
                    "pattern": "Foo",
                    "target_type": "classes_and_structs_only",
                    "output_detail_level": "signatures_only",
                },
            )
            parsed = _parse_tc(result)
            item = parsed["results"][0]
            assert item["qualified_name"] == "Foo"
            assert "file" not in item
            assert "brief" not in item


class TestGetFunctionsCalledByRouting:
    """Test get_functions_called_by routing based on return_format."""

    @pytest.mark.asyncio
    async def test_summary_routes_to_outgoing_calls(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc(
                {"callees": [{"qualified_name": "f", "file": "a.cpp"}]}
            ),
        ) as mock:
            await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "process",
                    "return_format": "function_definitions_summary",
                },
            )
            assert mock.call_args[0][0] == "get_outgoing_calls"

    @pytest.mark.asyncio
    async def test_summary_applies_compact_filter(self) -> None:
        """Summary format should strip location/doc fields."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc(
                {
                    "callees": [
                        {
                            "qualified_name": "f",
                            "file": "a.cpp",
                            "line": 5,
                            "brief": "doc",
                        }
                    ]
                }
            ),
        ):
            result = await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "process",
                    "return_format": "function_definitions_summary",
                },
            )
            parsed = _parse_tc(result)
            callee = parsed["callees"][0]
            assert callee["qualified_name"] == "f"
            assert "file" not in callee

    @pytest.mark.asyncio
    async def test_full_routes_to_outgoing_calls_no_filter(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc(
                {
                    "callees": [
                        {"qualified_name": "f", "file": "a.cpp", "brief": "doc"}
                    ]
                }
            ),
        ) as mock:
            result = await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "process",
                    "return_format": "function_definitions_full",
                },
            )
            assert mock.call_args[0][0] == "get_outgoing_calls"
            parsed = _parse_tc(result)
            assert parsed["callees"][0]["file"] == "a.cpp"
            assert parsed["callees"][0]["brief"] == "doc"

    @pytest.mark.asyncio
    async def test_call_sites_routes_to_get_call_sites(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"call_sites": []}),
        ) as mock:
            await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "process",
                    "return_format": "exact_call_line_locations",
                },
            )
            assert mock.call_args[0][0] == "get_call_sites"

    @pytest.mark.asyncio
    async def test_call_sites_strips_extra_args(self) -> None:
        """get_call_sites only takes function_name + class_name."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"call_sites": []}),
        ) as mock:
            await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "process",
                    "class_name": "Handler",
                    "return_format": "exact_call_line_locations",
                    "max_results": 10,
                    "search_scope": "include_external_libraries",
                },
            )
            forwarded = mock.call_args[0][1]
            assert forwarded == {
                "function_name": "process",
                "class_name": "Handler",
            }

    @pytest.mark.asyncio
    async def test_return_format_not_forwarded(self) -> None:
        """return_format is consolidated only, must not appear in internal args."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"callees": []}),
        ) as mock:
            await handle_tool_call_b(
                "get_functions_called_by",
                {
                    "function_name": "f",
                    "return_format": "function_definitions_full",
                    "search_scope": "project_code_only",
                },
            )
            forwarded = mock.call_args[0][1]
            assert "return_format" not in forwarded
            assert forwarded["search_scope"] == "project_code_only"


class TestFindUsageSitesRouting:
    """Test find_usage_sites → get_incoming_calls delegation."""

    @pytest.mark.asyncio
    async def test_delegates_to_incoming_calls(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"callers": []}),
        ) as mock:
            args = {"function_name": "render", "class_name": "View"}
            await handle_tool_call_b("find_usage_sites", args)
            mock.assert_called_once_with("get_incoming_calls", args)


class TestTraceExecutionPathRouting:
    """Test trace_execution_path → get_call_path delegation."""

    @pytest.mark.asyncio
    async def test_translates_param_names(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"paths": []}),
        ) as mock:
            await handle_tool_call_b(
                "trace_execution_path",
                {
                    "source_function": "main",
                    "target_function": "loadConfig",
                    "max_depth": 5,
                },
            )
            mock.assert_called_once_with(
                "get_call_path",
                {
                    "from_function": "main",
                    "to_function": "loadConfig",
                    "max_depth": 5,
                },
            )

    @pytest.mark.asyncio
    async def test_max_depth_optional(self) -> None:
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"paths": []}),
        ) as mock:
            await handle_tool_call_b(
                "trace_execution_path",
                {"source_function": "a", "target_function": "b"},
            )
            forwarded = mock.call_args[0][1]
            assert forwarded == {"from_function": "a", "to_function": "b"}
            assert "max_depth" not in forwarded


# ---------------------------------------------------------------
# Schema switching via env var
# ---------------------------------------------------------------


class TestSetProjectRouting:
    """Test set_project → set_project_directory + wait_for_indexing."""

    @pytest.mark.asyncio
    async def test_set_project_calls_internal_handlers(self) -> None:
        """set_project should call set_project_directory then wait then status."""
        calls: list[tuple[str, Any]] = []

        async def mock_handle(name: str, args: Any) -> list[TextContent]:
            calls.append((name, args))
            if name == "check_system_status":
                return _tc({"state": "indexed", "parsed_files": 10,
                             "indexed_classes": 5, "indexed_functions": 20})
            return _tc({"result": "ok"})

        with patch("mcp_server.cpp_mcp_server._handle_tool_call", side_effect=mock_handle):
            result = await handle_tool_call_b("set_project", {"path": "/tmp/proj"})
            parsed = _parse_tc(result)
            assert parsed["status"] == "ready"
            assert parsed["project_path"] == "/tmp/proj"
            # Should have called: set_project_directory, wait_for_indexing, check_system_status
            call_names = [c[0] for c in calls]
            assert "set_project_directory" in call_names
            assert "wait_for_indexing" in call_names
            assert "check_system_status" in call_names

    @pytest.mark.asyncio
    async def test_set_project_maps_path_param(self) -> None:
        """set_project 'path' param maps to 'project_path' internally."""
        captured_args: dict[str, Any] = {}

        async def mock_handle(name: str, args: Any) -> list[TextContent]:
            if name == "set_project_directory":
                captured_args.update(args)
            if name == "check_system_status":
                return _tc({"state": "indexed"})
            return _tc({"result": "ok"})

        with patch("mcp_server.cpp_mcp_server._handle_tool_call", side_effect=mock_handle):
            await handle_tool_call_b("set_project", {"path": "/tmp/proj", "config_file": "/c.json"})
            assert captured_args["project_path"] == "/tmp/proj"
            assert captured_args["config_file"] == "/c.json"

    @pytest.mark.asyncio
    async def test_set_project_indexing_in_progress(self) -> None:
        """set_project returns indexing_in_progress when not ready."""
        async def mock_handle(name: str, args: Any) -> list[TextContent]:
            if name == "check_system_status":
                return _tc({"state": "indexing", "parsed_files": 5})
            return _tc({"result": "ok"})

        with patch("mcp_server.cpp_mcp_server._handle_tool_call", side_effect=mock_handle):
            result = await handle_tool_call_b("set_project", {"path": "/tmp/proj"})
            parsed = _parse_tc(result)
            assert parsed["status"] == "indexing_in_progress"


class TestSyncProjectRouting:
    """Test sync_project routing: status-only vs refresh."""

    @pytest.mark.asyncio
    async def test_sync_project_no_args_returns_status(self) -> None:
        """sync_project with no args returns current status."""
        with patch(
            "mcp_server.cpp_mcp_server._handle_tool_call",
            new_callable=AsyncMock,
            return_value=_tc({"state": "indexed", "parsed_files": 100}),
        ) as mock:
            result = await handle_tool_call_b("sync_project", {})
            parsed = _parse_tc(result)
            assert parsed["system_state"] == "ready"
            # Should only call check_system_status (no refresh)
            call_names = [c[0][0] for c in mock.call_args_list]
            assert "check_system_status" in call_names
            assert "refresh_project" not in call_names

    @pytest.mark.asyncio
    async def test_sync_project_with_refresh_mode(self) -> None:
        """sync_project with refresh_mode triggers refresh then status."""
        calls: list[str] = []

        async def mock_handle(name: str, args: Any) -> list[TextContent]:
            calls.append(name)
            if name == "check_system_status":
                return _tc({"state": "indexed", "parsed_files": 100})
            return _tc({"result": "ok"})

        with patch("mcp_server.cpp_mcp_server._handle_tool_call", side_effect=mock_handle):
            result = await handle_tool_call_b(
                "sync_project", {"refresh_mode": "incremental"}
            )
            parsed = _parse_tc(result)
            assert parsed["system_state"] == "ready"
            assert "refresh_project" in calls
            assert "wait_for_indexing" in calls


class TestModuleImports:
    """Test that consolidated_tools module is importable."""

    def test_module_imports(self) -> None:
        """consolidated_tools module should be importable."""
        from mcp_server.consolidated_tools import (
            TOOL_NAMES,
            handle_tool_call_b,
            list_tools_b,
        )

        assert callable(list_tools_b)
        assert callable(handle_tool_call_b)  # type: ignore[arg-type]
        assert len(TOOL_NAMES) == 10
