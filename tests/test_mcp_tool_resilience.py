"""MCP tool-handler resilience (epic clang_index_mcp-ent, child .9).

Covers:
* Top-level guard: escaping exceptions become well-formed MCP error responses
  (isError + clear message + next-step suggestions per REQ-10.13.5).
* Empty vs unavailable for alias lookups: never claim "no such alias" when the
  error-state channel says the cache backend actually failed.
* Collection results stay valid empty list/dict payloads with an optional
  additive degraded note.
* Core symbol/class/call-site tools served from SymbolIndexStore stay
  unaffected by cache failures.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.types import CallToolResult, TextContent

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp._mcp.consolidated_tools import handle_tool_call_b
from clang_index_mcp._mcp.context import ctx
from clang_index_mcp._mcp.state_manager import AnalyzerState, AnalyzerStateManager
from clang_index_mcp._mcp.tool_handlers.resilience import (
    ALIAS_LOOKUP_OPERATIONS,
    apply_alias_availability,
    attach_collection_degraded_note,
    consume_alias_degradation,
    guard_tool_handler,
    looks_like_alias_not_found,
    tool_error_payload,
    tool_error_result,
)
from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp._persistence.error_tracking_adapter import ErrorTrackingAdapter


def _tc(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _parse(result: Any) -> Any:
    if isinstance(result, CallToolResult):
        text = result.content[0].text
    else:
        text = result[0].text
    return json.loads(text)


class TestGuardToolHandler:
    """Escaping exceptions become well-formed error payloads with next_steps."""

    @pytest.mark.asyncio
    async def test_exception_becomes_iserror_payload(self) -> None:
        @guard_tool_handler("boom")
        async def boom(_arguments: dict[str, Any]) -> list[TextContent]:
            raise RuntimeError("kaboom")

        result = await boom({})
        assert isinstance(result, list)
        payload = _parse(result)
        assert payload["isError"] is True
        assert "kaboom" in payload["error"]
        assert payload["tool"] == "boom"
        assert payload["next_steps"]
        assert all(isinstance(step, str) and step for step in payload["next_steps"])

    @pytest.mark.asyncio
    async def test_success_path_unchanged(self) -> None:
        @guard_tool_handler("ok")
        async def ok(_arguments: dict[str, Any]) -> list[TextContent]:
            return _tc({"data": [1, 2]})

        result = await ok({})
        assert not isinstance(result, CallToolResult)
        assert _parse(result)["data"] == [1, 2]

    @pytest.mark.asyncio
    async def test_handle_tool_call_b_exception_is_guarded(self) -> None:
        with patch(
            "clang_index_mcp._mcp.consolidated_tools._handle_set_project",
            new_callable=AsyncMock,
            side_effect=RuntimeError("set_project exploded"),
        ):
            result = await handle_tool_call_b("set_project", {"config_file": "/tmp/x.json"})
        assert isinstance(result, list)
        payload = _parse(result)
        assert payload["isError"] is True
        assert "set_project exploded" in payload["error"]
        assert payload["next_steps"]

    @pytest.mark.asyncio
    async def test_handle_tool_call_dispatch_exception_is_guarded(self) -> None:
        import clang_index_mcp._mcp.cpp_mcp_server as srv

        original_analyzer = ctx.analyzer
        original_state = ctx.state_manager
        ctx.analyzer = Mock()
        ctx.state_manager = AnalyzerStateManager()
        ctx.state_manager.transition_to(AnalyzerState.INDEXED)
        try:
            with patch.dict(
                srv._QUERY_HANDLERS,
                {"get_class_info": AsyncMock(side_effect=RuntimeError("handler boom"))},
            ):
                result = await srv._handle_tool_call("get_class_info", {"class_name": "X"})
        finally:
            ctx.analyzer = original_analyzer
            ctx.state_manager = original_state

        assert isinstance(result, list)
        payload = _parse(result)
        assert payload["isError"] is True
        assert "handler boom" in payload["error"]

    def test_tool_error_payload_shape(self) -> None:
        payload = tool_error_payload("bad", tool_name="t", next_steps=["do x"])
        assert payload == {
            "error": "bad",
            "error_type": "tool_error",
            "isError": True,
            "next_steps": ["do x"],
            "tool": "t",
        }

    def test_tool_error_result_is_error(self) -> None:
        result = tool_error_result("bad")
        assert isinstance(result, CallToolResult)
        assert result.isError is True

    @pytest.mark.asyncio
    async def test_server_boundary_promotes_to_call_tool_result(self) -> None:
        import clang_index_mcp._mcp.cpp_mcp_server as srv

        error_list = [
            TextContent(
                type="text",
                text=json.dumps(tool_error_payload("boom", tool_name="t")),
            )
        ]
        with patch(
            "clang_index_mcp._mcp.tool_registry.ToolRegistry.call_tool",
            new_callable=AsyncMock,
            return_value=error_list,
        ):
            result = await srv.call_tool("t", {})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "boom" in _parse(result)["error"]


class TestEmptyVsUnavailable:
    """Alias lookups must not claim not-found when the cache is degraded."""

    def _broken_cache_manager(self, method: str = "get_type_alias_info") -> CacheManager:
        backend = Mock()
        backend.close = Mock()
        for op in ALIAS_LOOKUP_OPERATIONS:
            setattr(backend, op, Mock(side_effect=OSError("backend down")))
        return CacheManager(
            project_root,
            backend=backend,
            recovery=ErrorTrackingAdapter(),
        )

    def test_consume_alias_degradation_true_when_channel_set(self) -> None:
        cm = self._broken_cache_manager()
        try:
            cm.get_type_alias_info("Foo")
            assert consume_alias_degradation(cm) is True
            # Consumed: a second check is clean until a new failure.
            assert consume_alias_degradation(cm) is False
        finally:
            cm.close()

    def test_consume_alias_degradation_false_when_clean(self) -> None:
        backend = Mock()
        backend.close = Mock()
        backend.get_type_alias_info = Mock(return_value=None)
        cm = CacheManager(project_root, backend=backend, recovery=ErrorTrackingAdapter())
        try:
            cm.get_type_alias_info("Foo")
            assert consume_alias_degradation(cm) is False
        finally:
            cm.close()

    def test_consume_alias_degradation_handles_missing_channel(self) -> None:
        assert consume_alias_degradation(None) is False
        assert consume_alias_degradation(object()) is False

    def test_looks_like_alias_not_found(self) -> None:
        assert looks_like_alias_not_found({"error": "Type 'X' not found"})
        assert looks_like_alias_not_found(None)
        assert not looks_like_alias_not_found({"canonical_type": "int"})
        assert not looks_like_alias_not_found({"error": "Ambiguous type name 'X'"})

    def test_apply_alias_availability_unavailable_when_degraded_not_found(self) -> None:
        result = _tc({"data": {"error": "Type 'Missing' not found", "canonical_type": None}})
        out = apply_alias_availability(result, type_name="Missing", degraded=True)
        payload = _parse(out)
        assert "unavailable" in payload["error"].lower()
        assert "not found" not in payload["error"].lower()
        assert payload["isError"] is True
        assert payload["error_type"] == "alias_lookup_unavailable"
        assert payload["next_steps"]

    def test_apply_alias_availability_keeps_truthful_not_found(self) -> None:
        result = _tc({"data": {"error": "Type 'Missing' not found", "canonical_type": None}})
        out = apply_alias_availability(result, type_name="Missing", degraded=False)
        payload = _parse(out)
        assert "not found" in payload["data"]["error"].lower()

    def test_apply_alias_availability_degraded_hit_adds_note(self) -> None:
        result = _tc(
            {
                "data": {
                    "canonical_type": "int",
                    "aliases": [],
                    "input_was_alias": False,
                }
            }
        )
        out = apply_alias_availability(result, type_name="int", degraded=True)
        payload = _parse(out)
        assert payload["data"]["canonical_type"] == "int"
        assert payload["metadata"]["degraded"] is True
        assert "incomplete" in payload["metadata"]["degraded_note"].lower()
        assert payload["metadata"]["next_steps"]

    def test_attach_collection_degraded_note_keeps_empty_list(self) -> None:
        result = _tc({"results": [], "metadata": {"status": "empty"}})
        out = attach_collection_degraded_note(result, degraded=True)
        payload = _parse(out)
        assert payload["results"] == []
        assert payload["metadata"]["degraded"] is True
        assert payload["metadata"]["status"] == "empty"

    def test_attach_collection_degraded_note_noop_when_clean(self) -> None:
        result = _tc({"results": [1]})
        out = attach_collection_degraded_note(result, degraded=False)
        payload = _parse(out)
        assert "metadata" not in payload or "degraded" not in payload.get("metadata", {})


class TestGetTypeAliasInfoHandler:
    """Handler-level empty-vs-unavailable for get_type_alias_info."""

    def _install_ctx(self, analyzer: Any) -> Any:
        original_analyzer = ctx.analyzer
        original_state = ctx.state_manager
        ctx.analyzer = analyzer
        ctx.state_manager = AnalyzerStateManager()
        ctx.state_manager.transition_to(AnalyzerState.INDEXED)

        def restore() -> None:
            ctx.analyzer = original_analyzer
            ctx.state_manager = original_state

        return restore

    @pytest.mark.asyncio
    async def test_degraded_says_unavailable_not_not_found(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_get_type_alias_info

        analyzer = Mock()
        analyzer.get_type_alias_info = Mock(
            return_value={"error": "Type 'Ghost' not found", "canonical_type": None, "aliases": []}
        )
        analyzer.cache_manager = Mock()
        analyzer.cache_manager.get_and_clear_degraded = Mock(side_effect=lambda op: True)

        restore = self._install_ctx(analyzer)
        try:
            result = await _handle_get_type_alias_info({"type_name": "Ghost"})
        finally:
            restore()

        payload = _parse(result)
        assert "unavailable" in json.dumps(payload).lower()
        assert "not found" not in json.dumps(payload).lower()
        assert analyzer.cache_manager.get_and_clear_degraded.called

    @pytest.mark.asyncio
    async def test_clean_not_found_is_truthful(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_get_type_alias_info

        analyzer = Mock()
        analyzer.get_type_alias_info = Mock(
            return_value={"error": "Type 'Ghost' not found", "canonical_type": None, "aliases": []}
        )
        analyzer.cache_manager = Mock()
        analyzer.cache_manager.get_and_clear_degraded = Mock(return_value=False)

        restore = self._install_ctx(analyzer)
        try:
            result = await _handle_get_type_alias_info({"type_name": "Ghost"})
        finally:
            restore()

        payload = _parse(result)
        body = payload.get("data", payload)
        assert "not found" in body["error"].lower()
        assert "unavailable" not in json.dumps(payload).lower()

    @pytest.mark.asyncio
    async def test_degraded_hit_keeps_data_with_note(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_get_type_alias_info

        analyzer = Mock()
        analyzer.get_type_alias_info = Mock(
            return_value={
                "canonical_type": "int",
                "qualified_name": "int",
                "aliases": [],
                "input_was_alias": False,
                "is_ambiguous": False,
            }
        )
        analyzer.cache_manager = Mock()
        analyzer.cache_manager.get_and_clear_degraded = Mock(return_value=True)

        restore = self._install_ctx(analyzer)
        try:
            result = await _handle_get_type_alias_info({"type_name": "int"})
        finally:
            restore()

        payload = _parse(result)
        assert payload["data"]["canonical_type"] == "int"
        assert payload["metadata"]["degraded"] is True

    @pytest.mark.asyncio
    async def test_handler_exception_becomes_iserror(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_get_type_alias_info

        analyzer = Mock()
        analyzer.get_type_alias_info = Mock(side_effect=RuntimeError("resolver blew up"))
        analyzer.cache_manager = Mock()

        restore = self._install_ctx(analyzer)
        try:
            result = await _handle_get_type_alias_info({"type_name": "X"})
        finally:
            restore()

        assert isinstance(result, list)
        payload = _parse(result)
        assert payload["isError"] is True
        assert "resolver blew up" in payload["error"]


class TestCoreToolsUnaffectedByCacheFailure:
    """Symbol/class/call-site tools serve from SymbolIndexStore, not the cache."""

    def _make_analyzer_with_broken_cache(self) -> Any:
        analyzer = Mock()
        analyzer.search_classes = Mock(
            return_value=[{"qualified_name": "Widget", "name": "Widget", "file": "a.h", "line": 1}]
        )
        analyzer.get_class_info = Mock(return_value={"name": "Widget", "methods": []})
        analyzer.get_call_sites = Mock(return_value=[{"file": "a.h", "line": 2}])
        analyzer.get_class_hierarchy = Mock(return_value={"classes": {}})
        analyzer.find_incoming_calls = Mock(return_value={"callers": [], "call_sites": []})
        analyzer.pop_last_fallback = Mock(return_value=None)

        cache_manager = Mock()
        cache_manager.get_and_clear_degraded = Mock(return_value=True)
        analyzer.cache_manager = cache_manager
        return analyzer

    def _install(self, analyzer: Any) -> Any:
        original_analyzer = ctx.analyzer
        original_state = ctx.state_manager
        ctx.analyzer = analyzer
        ctx.state_manager = AnalyzerStateManager()
        ctx.state_manager.transition_to(AnalyzerState.INDEXED)

        def restore() -> None:
            ctx.analyzer = original_analyzer
            ctx.state_manager = original_state

        return restore

    @pytest.mark.asyncio
    async def test_search_classes_still_returns_symbols(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_search_classes

        analyzer = self._make_analyzer_with_broken_cache()
        restore = self._install(analyzer)
        try:
            result = await _handle_search_classes({"symbol_name": "Widget"})
        finally:
            restore()

        payload = _parse(result)
        data = payload.get("data", payload)
        assert data, "core search must not be empty when symbols are indexed"
        assert analyzer.search_classes.called

    @pytest.mark.asyncio
    async def test_get_class_info_still_returns_class(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.search_tools import _handle_get_class_info

        analyzer = self._make_analyzer_with_broken_cache()
        restore = self._install(analyzer)
        try:
            result = await _handle_get_class_info({"class_name": "Widget"})
        finally:
            restore()

        payload = _parse(result)
        data = payload.get("data", payload)
        assert data["name"] == "Widget"

    @pytest.mark.asyncio
    async def test_get_call_sites_still_returns_sites(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.call_graph_tools import _handle_get_call_sites

        analyzer = self._make_analyzer_with_broken_cache()
        restore = self._install(analyzer)
        try:
            result = await _handle_get_call_sites({"function_name": "f"})
        finally:
            restore()

        payload = _parse(result)
        assert payload["call_sites"]

    @pytest.mark.asyncio
    async def test_find_incoming_calls_still_returns_callers(self) -> None:
        from clang_index_mcp._mcp.tool_handlers.call_graph_tools import _handle_find_incoming_calls

        analyzer = self._make_analyzer_with_broken_cache()
        restore = self._install(analyzer)
        try:
            result = await _handle_find_incoming_calls({"function_name": "f"})
        finally:
            restore()

        payload = _parse(result)
        assert "callers" in payload
        assert "call_sites" in payload


class TestFailFastReads:
    """Handlers must not introduce synchronous retries (latency protection)."""

    def test_consume_alias_degradation_is_single_pass(self) -> None:
        backend = Mock()
        backend.close = Mock()
        backend.get_type_alias_info = Mock(side_effect=OSError("down"))
        cm = CacheManager(project_root, backend=backend, recovery=ErrorTrackingAdapter())
        try:
            cm.get_type_alias_info("Foo")
            # First consume observes the failure; second is clean — no retry
            # re-invokes the backend inside the handler helper.
            assert consume_alias_degradation(cm) is True
            assert consume_alias_degradation(cm) is False
            assert backend.get_type_alias_info.call_count == 1
        finally:
            cm.close()

    def test_guard_does_not_retry_handler(self) -> None:
        calls = {"n": 0}

        @guard_tool_handler("once")
        async def once(_arguments: dict[str, Any]) -> list[TextContent]:
            calls["n"] += 1
            raise RuntimeError("fail once")

        result = asyncio.run(once({}))
        assert isinstance(result, list)
        assert _parse(result)["isError"] is True
        assert calls["n"] == 1


class TestSchemasAdditive:
    """Existing success payloads stay shaped as list[TextContent] JSON."""

    @pytest.mark.asyncio
    async def test_unknown_tool_is_valid_text_content(self) -> None:
        result = await handle_tool_call_b("nonexistent_tool", {})
        assert isinstance(result, list)
        assert "Error" in result[0].text
        assert "nonexistent_tool" in result[0].text

    def test_degraded_note_is_additive_only(self) -> None:
        original = {"results": [{"a": 1}], "metadata": {"returned": 1}}
        result = attach_collection_degraded_note(_tc(original), degraded=True)
        payload = _parse(result)
        assert payload["results"] == [{"a": 1}]
        assert payload["metadata"]["returned"] == 1
        assert payload["metadata"]["degraded"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
