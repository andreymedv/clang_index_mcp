"""Tool-handler resilience: guarded execution and empty-vs-unavailable alias notes.

Implements epic clang_index_mcp-ent child .9:

* Every tool call is guarded so an escaping exception becomes a well-formed
  MCP error payload (isError + clear message + next-step suggestions per
  REQ-10.13.5) instead of a dropped connection or server crash.
* Alias lookups distinguish "not found" (error-state channel clean) from
  "alias lookup unavailable" (channel degraded) so LLM consumers are never
  told "no such alias" when the cache backend was actually down.
* Collection-style results stay valid empty list/dict payloads and may carry
  an additive degraded note; response schemas remain backward compatible.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any, TypeVar, cast

from mcp.types import CallToolResult, TextContent

# Operation names on the child .3 error-state channel that back alias lookups.
ALIAS_LOOKUP_OPERATIONS: tuple[str, ...] = (
    "get_canonical_for_alias",
    "get_type_alias_info",
    "get_aliases_for_canonical",
    "get_type_alias_details",
    "get_all_alias_mappings",
)

INTERNAL_ERROR_NEXT_STEPS: tuple[str, ...] = (
    "Use check_system_status to inspect server and cache state",
    "Retry the call after a short wait",
    "If the error persists, restart the MCP server",
)

ALIAS_UNAVAILABLE_NEXT_STEPS: tuple[str, ...] = (
    "Alias lookup is unavailable because the cache backend is degraded",
    "Use check_system_status to inspect cache error state",
    "Retry after cache recovery; core symbol search is unaffected",
)

ALIAS_DEGRADED_NOTE = (
    "Alias lookup was degraded (cache backend error); "
    "alias lists may be incomplete and empty results must not be read as 'no such alias'."
)

Handler = TypeVar("Handler", bound=Callable[..., Awaitable[Any]])


def _json_text(payload: dict[str, Any]) -> TextContent:
    return TextContent(type="text", text=json.dumps(payload, indent=2))


def tool_error_payload(
    message: str,
    *,
    tool_name: str | None = None,
    error_type: str = "tool_error",
    next_steps: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Build the well-formed error body for a tool failure (REQ-10.13.5)."""
    payload: dict[str, Any] = {
        "error": message,
        "error_type": error_type,
        "isError": True,
        "next_steps": list(next_steps if next_steps is not None else INTERNAL_ERROR_NEXT_STEPS),
    }
    if tool_name:
        payload["tool"] = tool_name
    return payload


def tool_error_content(
    message: str,
    *,
    tool_name: str | None = None,
    error_type: str = "tool_error",
    next_steps: Sequence[str] | None = None,
) -> list[TextContent]:
    """Error body as TextContent list (keeps handler return type stable)."""
    return [
        _json_text(
            tool_error_payload(
                message,
                tool_name=tool_name,
                error_type=error_type,
                next_steps=next_steps,
            )
        )
    ]


def tool_error_result(
    message: str,
    *,
    tool_name: str | None = None,
    error_type: str = "tool_error",
    next_steps: Sequence[str] | None = None,
) -> CallToolResult:
    """MCP CallToolResult with isError=True for escaping exceptions."""
    content = tool_error_content(
        message,
        tool_name=tool_name,
        error_type=error_type,
        next_steps=next_steps,
    )
    return CallToolResult(
        isError=True,
        content=cast(Any, content),
    )


def alias_unavailable_payload(type_name: str | None = None) -> dict[str, Any]:
    """Empty-vs-unavailable body: never claim 'no such alias' when degraded."""
    subject = f" for '{type_name}'" if type_name else ""
    return tool_error_payload(
        f"alias lookup unavailable{subject}",
        tool_name="get_type_alias_info",
        error_type="alias_lookup_unavailable",
        next_steps=ALIAS_UNAVAILABLE_NEXT_STEPS,
    )


def alias_unavailable_content(type_name: str | None = None) -> list[TextContent]:
    return [_json_text(alias_unavailable_payload(type_name))]


def alias_degraded_metadata() -> dict[str, Any]:
    """Additive metadata block for collection results served while degraded."""
    return {
        "degraded": True,
        "degraded_note": ALIAS_DEGRADED_NOTE,
        "next_steps": list(ALIAS_UNAVAILABLE_NEXT_STEPS),
    }


def consume_alias_degradation(cache_manager: Any) -> bool:
    """Report-and-clear degraded state for alias cache ops (child .3 channel).

    Returns True when any alias lookup just ended degraded. Call this right
    after the cache call so "empty" can be told from "unavailable".
    """
    if cache_manager is None:
        return False
    query = getattr(cache_manager, "get_and_clear_degraded", None)
    if not callable(query):
        return False
    degraded = False
    for operation in ALIAS_LOOKUP_OPERATIONS:
        try:
            if query(operation):
                degraded = True
        except Exception:
            # Channel must never break the tool response path.
            continue
    return degraded


def looks_like_alias_not_found(data: Any) -> bool:
    """True when a get_type_alias_info body claims a definitive not-found."""
    if data is None:
        return True
    if not isinstance(data, dict):
        return False
    # EnhancedQueryResult wraps tool data under "data".
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    if "error" not in data:
        return False
    error_text = str(data.get("error", "")).lower()
    return "not found" in error_text or "no such" in error_text


def apply_alias_availability(
    result: list[TextContent],
    *,
    type_name: str | None = None,
    degraded: bool,
) -> list[TextContent]:
    """Rewrite an alias-lookup response for the empty-vs-unavailable rule.

    * degraded + not-found  -> "alias lookup unavailable" (never "no such alias")
    * degraded + hit        -> keep data, add additive degraded metadata
    * clean                 -> unchanged (not-found is truthful)
    """
    if not degraded or not result:
        return result
    try:
        data = json.loads(result[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return result

    if looks_like_alias_not_found(data):
        return alias_unavailable_content(type_name)

    if isinstance(data, dict):
        # EnhancedQueryResult wraps tool data under "data"; keep that shape.
        if "data" in data and isinstance(data["data"], dict):
            meta = data.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                data["metadata"] = meta
            meta.update(alias_degraded_metadata())
        else:
            data.update(alias_degraded_metadata())
        return [_json_text(data)]
    return result


def attach_collection_degraded_note(
    result: list[TextContent],
    *,
    degraded: bool,
) -> list[TextContent]:
    """Add a degraded note to a collection payload without changing its type."""
    if not degraded or not result:
        return result
    try:
        data = json.loads(result[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return result
    if not isinstance(data, dict):
        return result
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        data["metadata"] = meta
    meta.update(alias_degraded_metadata())
    return [_json_text(data)]


def guard_tool_handler(name: str) -> Callable[[Handler], Handler]:
    """Top-level guard: escaping exceptions become well-formed error payloads.

    Handlers keep returning list[TextContent] so internal composition (status
    merging, detail filtering) stays intact. The payload carries isError=true,
    a clear message, and next-step suggestions (REQ-10.13.5). The MCP server
    boundary promotes these to CallToolResult(isError=True).
    """

    def decorator(handler: Handler) -> Handler:
        @functools.wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await handler(*args, **kwargs)
            except Exception as exc:
                return tool_error_content(
                    f"Internal error in tool '{name}': {exc}",
                    tool_name=name,
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def is_error_result(result: Any) -> bool:
    """True when a handler returned an MCP error (isError) response."""
    if isinstance(result, CallToolResult):
        return bool(result.isError)
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, TextContent):
            try:
                payload = json.loads(first.text)
            except (json.JSONDecodeError, TypeError):
                return False
            return isinstance(payload, dict) and bool(payload.get("isError"))
    return False


def result_text(result: Iterable[TextContent] | CallToolResult | None) -> str:
    """Extract concatenated text from either result shape (for telemetry)."""
    if result is None:
        return ""
    if isinstance(result, CallToolResult):
        blocks = result.content
    else:
        blocks = list(result)
    return "".join(block.text for block in blocks if isinstance(block, TextContent))
