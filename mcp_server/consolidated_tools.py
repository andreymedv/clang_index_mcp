#!/usr/bin/env python3
"""Schema B: Consolidated tool definitions for small LLM benchmarking.

Provides 11 tools (vs 17 in Schema A) to test whether fewer tools with
enum-based parameters improve small LLM tool selection accuracy.

Activated via TOOL_SCHEMA=B environment variable.

Tool mapping (Schema B → Schema A):
  set_project_directory   → passthrough
  check_system_status     → passthrough + system_state enum
  refresh_project         → passthrough
  search_codebase         → search_classes / search_functions / search_symbols
  find_in_file            → passthrough
  get_class_info          → passthrough
  get_class_hierarchy     → passthrough
  get_type_alias_info     → passthrough
  get_functions_called_by → get_outgoing_calls / get_call_sites
  find_usage_sites        → get_incoming_calls
  trace_execution_path    → get_call_path
"""

import json
from typing import Any, Dict, List

from mcp.types import Tool, TextContent

# ---------------------------------------------------------------
# Passthrough: Schema B name → Schema A name (no translation)
# ---------------------------------------------------------------
_PASSTHROUGH_MAP = {
    "set_project_directory": "set_project_directory",
    "refresh_project": "refresh_project",
    "find_in_file": "find_in_file",
    "get_class_info": "get_class_info",
    "get_class_hierarchy": "get_class_hierarchy",
    "get_type_alias_info": "get_type_alias_info",
}

# Schema B-only params that must not be forwarded to Schema A
_SEARCH_B_PARAMS = {"target_type", "output_detail_level"}
_CALLGRAPH_B_PARAMS = {"return_format"}

# Fields to strip at each output_detail_level
_DOC_FIELDS = {"brief", "doc_comment"}
_LOCATION_FIELDS = {
    "file",
    "line",
    "start_line",
    "end_line",
    "header_file",
    "header_start_line",
    "header_end_line",
    "declaration",
    "definition",
    "is_project",
    "namespace",
    "template_kind",
    "template_parameters",
    "specialization_of",
}

# System state mapping from indexing_state → simplified enum
_SYSTEM_STATE_MAP = {
    "uninitialized": "not_ready",
    "initializing": "not_ready",
    "indexing": "not_ready",
    "indexed": "ready",
    "refreshing": "partially_ready",
    "error": "error",
}

# All Schema B tool names (for validation)
SCHEMA_B_TOOL_NAMES = [
    "set_project_directory",
    "check_system_status",
    "refresh_project",
    "search_codebase",
    "find_in_file",
    "get_class_info",
    "get_class_hierarchy",
    "get_type_alias_info",
    "get_functions_called_by",
    "find_usage_sites",
    "trace_execution_path",
]


# ---------------------------------------------------------------
# Output filtering helpers
# ---------------------------------------------------------------


def _filter_detail_level(result: List[TextContent], detail_level: str) -> List[TextContent]:
    """Filter output fields based on output_detail_level enum."""
    if detail_level == "full_details_with_docs":
        return result

    if not result:
        return result

    try:
        data = json.loads(result[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return result

    strip_fields: set[str] = set()
    if detail_level == "signatures_only":
        strip_fields = _DOC_FIELDS | _LOCATION_FIELDS
    elif detail_level == "locations_and_metadata":
        strip_fields = _DOC_FIELDS

    if not strip_fields:
        return result

    _strip_from_data(data, strip_fields)
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _strip_from_data(data: Any, fields: set[str]) -> None:
    """Strip fields from result lists inside a data dict or list."""
    if isinstance(data, dict):
        for key in ("results", "classes", "functions", "callers", "callees", "call_sites"):
            items = data.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        for f in fields:
                            item.pop(f, None)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for f in fields:
                    item.pop(f, None)


def _add_system_state(result: List[TextContent]) -> List[TextContent]:
    """Add simplified system_state enum to check_system_status response."""
    if not result:
        return result
    try:
        data = json.loads(result[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return result

    indexing_state = data.get("indexing_state", "uninitialized")
    data["system_state"] = _SYSTEM_STATE_MAP.get(indexing_state, "not_ready")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------


def list_tools_b() -> List[Tool]:
    """Return Schema B tool definitions (11 consolidated tools)."""
    return [
        Tool(
            name="set_project_directory",
            description=(
                "REQUIRED FIRST STEP: Set the C++ project directory to analyze. "
                "Must be called before any other tools. Indexes all C++ files "
                "using libclang. Supports incremental analysis on re-runs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to C++ project root directory.",
                    },
                    "config_file": {
                        "type": "string",
                        "description": "Optional: Path to cpp-analyzer-config.json.",
                    },
                    "auto_refresh": {
                        "type": "boolean",
                        "description": "Auto-detect changes on cache load (default: true).",
                        "default": True,
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="check_system_status",
            description=(
                "Get server status, indexing progress, and index statistics. "
                "Returns system_state enum: 'ready' (indexed, safe to query), "
                "'not_ready' (initializing/indexing, results incomplete), "
                "'partially_ready' (refreshing, cached results available), "
                "'error'. Always check system_state before querying if you "
                "get empty results."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="refresh_project",
            description=(
                "Re-scan project for file changes and re-index affected files. "
                "Call after source files are modified. 'incremental' (default) "
                "is 30-300x faster. Only use 'full' if cache seems corrupted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "refresh_mode": {
                        "type": "string",
                        "enum": ["incremental", "full"],
                        "description": (
                            "'incremental' (default): only changed files. "
                            "'full': re-index everything."
                        ),
                        "default": "incremental",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_codebase",
            description=(
                "Search for C++ symbols by name pattern. Use target_type to "
                "narrow to classes, functions, or all. Use output_detail_level "
                "to control response size.\n\n"
                "Pattern matching (case-insensitive):\n"
                "- 'Widget' — matches in any namespace\n"
                "- 'ui::Widget' — matches namespace suffix\n"
                "- '.*Manager.*' — regex, matches containing 'Manager'\n"
                "- '' (empty) — matches ALL symbols (use with file_name)\n\n"
                "Returns qualified_name, kind, and more based on detail level."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Symbol name or regex pattern. Empty string matches all.",
                    },
                    "target_type": {
                        "type": "string",
                        "enum": [
                            "classes_and_structs_only",
                            "functions_and_methods_only",
                            "all_symbol_types",
                        ],
                        "description": (
                            "What to search for. 'classes_and_structs_only': "
                            "class/struct definitions. 'functions_and_methods_only': "
                            "functions and class methods. 'all_symbol_types': both."
                        ),
                        "default": "all_symbol_types",
                    },
                    "output_detail_level": {
                        "type": "string",
                        "enum": [
                            "signatures_only",
                            "locations_and_metadata",
                            "full_details_with_docs",
                        ],
                        "description": (
                            "'signatures_only': names and prototypes. "
                            "'locations_and_metadata': add file locations, "
                            "namespaces, template info. "
                            "'full_details_with_docs': everything including docs."
                        ),
                        "default": "locations_and_metadata",
                    },
                    "search_scope": {
                        "type": "string",
                        "enum": ["project_code_only", "include_external_libraries"],
                        "description": (
                            "'project_code_only' (default): project files only. "
                            "'include_external_libraries': include system/third-party."
                        ),
                        "default": "project_code_only",
                    },
                    "file_name": {
                        "type": "string",
                        "description": (
                            "Optional: Filter to symbols in this file "
                            "(filename, relative path, or absolute path)."
                        ),
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Optional: Filter to symbols in this namespace.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Optional: Maximum results to return.",
                        "minimum": 1,
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="find_in_file",
            description=(
                "Search for symbols within a specific file or glob pattern. "
                "Supports: absolute path, relative path, filename, "
                "glob patterns (**/tests/*.cpp). "
                "Empty pattern matches all symbols in the file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path or glob pattern to search in.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Symbol name pattern. Empty string matches all " "symbols in the file."
                        ),
                    },
                },
                "required": ["file_path", "pattern"],
            },
        ),
        Tool(
            name="get_class_info",
            description=(
                "Get full details of a specific class: methods, base classes, "
                "derived classes, documentation. Requires exact class name — "
                "use search_codebase first if unsure. Returns disambiguation "
                "options if name is ambiguous."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": (
                            "Exact class name (simple or qualified, "
                            "e.g. 'Widget' or 'ui::Widget')."
                        ),
                    },
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="get_class_hierarchy",
            description=(
                "Get complete inheritance graph for a class — all ancestors "
                "and descendants as a flat adjacency list. Use this for full "
                "inheritance trees; get_class_info gives only direct parents/children."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Class name to get hierarchy for.",
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "Max nodes in result (default 200).",
                        "default": 200,
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Max BFS depth from queried class.",
                    },
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="get_type_alias_info",
            description=(
                "Resolve C++ type aliases (using/typedef). Given a type name, "
                "returns the canonical type and all aliases pointing to it. "
                "Detects ambiguous names across namespaces."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "type_name": {
                        "type": "string",
                        "description": "Type name to query (simple or qualified).",
                    },
                },
                "required": ["type_name"],
            },
        ),
        Tool(
            name="get_functions_called_by",
            description=(
                "Find all functions called BY a specified function (OUTGOING "
                "direction). Shows what this function depends on.\n\n"
                "Use return_format to choose:\n"
                "- 'function_definitions_summary': compact list of callees\n"
                "- 'function_definitions_full': callees with full metadata\n"
                "- 'exact_call_line_locations': file:line:column of each call\n\n"
                "Do NOT use for finding callers — use find_usage_sites instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to analyze (the caller).",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Class name if function is a method.",
                        "default": "",
                    },
                    "return_format": {
                        "type": "string",
                        "enum": [
                            "function_definitions_summary",
                            "function_definitions_full",
                            "exact_call_line_locations",
                        ],
                        "description": (
                            "'function_definitions_summary': callee names and "
                            "locations (compact). 'function_definitions_full': "
                            "full metadata. 'exact_call_line_locations': exact "
                            "file:line:column of each call within function body."
                        ),
                        "default": "function_definitions_summary",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Optional: Maximum results.",
                        "minimum": 1,
                    },
                    "search_scope": {
                        "type": "string",
                        "enum": ["project_code_only", "include_external_libraries"],
                        "description": (
                            "'project_code_only' (default) or " "'include_external_libraries'."
                        ),
                        "default": "project_code_only",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="find_usage_sites",
            description=(
                "Find all functions that CALL the specified function (INCOMING "
                "direction). Shows what code depends on this function.\n\n"
                "Use for: 'what calls X?', 'where is X used?', 'callers of X', "
                "impact analysis, refactoring safety.\n\n"
                "Returns callers with definitions + exact call site locations.\n\n"
                "Do NOT use for finding what a function calls — use "
                "get_functions_called_by instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to find callers for.",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Class name if function is a method.",
                        "default": "",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Optional: Maximum results.",
                        "minimum": 1,
                    },
                    "search_scope": {
                        "type": "string",
                        "enum": ["project_code_only", "include_external_libraries"],
                        "description": (
                            "'project_code_only' (default) or " "'include_external_libraries'."
                        ),
                        "default": "project_code_only",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="trace_execution_path",
            description=(
                "Find call chains between two functions using BFS. Returns all "
                "execution paths from source to target within max_depth hops.\n\n"
                "Example: trace_execution_path('main', 'loadConfig') might "
                "return: main -> init -> setup -> loadConfig\n\n"
                "WARNING: Can return many paths in highly connected code. "
                "Keep max_depth low (5-15)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_function": {
                        "type": "string",
                        "description": "Starting function of the path.",
                    },
                    "target_function": {
                        "type": "string",
                        "description": "Destination function to reach.",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": (
                            "Max intermediate hops (default: 10). " "Keep low for large codebases."
                        ),
                        "default": 10,
                    },
                },
                "required": ["source_function", "target_function"],
            },
        ),
    ]


# ---------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------


async def handle_tool_call_b(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Dispatch Schema B tool calls, delegating to Schema A handlers."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    # Passthrough tools — delegate directly with same name and args
    if name in _PASSTHROUGH_MAP:
        return await _handle_tool_call(_PASSTHROUGH_MAP[name], arguments)

    if name == "check_system_status":
        result = await _handle_tool_call("check_system_status", arguments)
        return _add_system_state(result)

    if name == "search_codebase":
        return await _handle_search_codebase(arguments)

    if name == "get_functions_called_by":
        return await _handle_get_functions_called_by(arguments)

    if name == "find_usage_sites":
        return await _handle_find_usage_sites(arguments)

    if name == "trace_execution_path":
        return await _handle_trace_execution_path(arguments)

    return [TextContent(type="text", text=f"Error: Unknown Schema B tool '{name}'")]


async def _handle_search_codebase(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Route search_codebase to search_classes/search_functions/search_symbols."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    target_type = arguments.get("target_type", "all_symbol_types")
    detail_level = arguments.get("output_detail_level", "locations_and_metadata")

    # Forward only Schema A params
    schema_a_args = {k: v for k, v in arguments.items() if k not in _SEARCH_B_PARAMS}

    if target_type == "classes_and_structs_only":
        result = await _handle_tool_call("search_classes", schema_a_args)
    elif target_type == "functions_and_methods_only":
        result = await _handle_tool_call("search_functions", schema_a_args)
    else:  # all_symbol_types
        result = await _handle_tool_call("search_symbols", schema_a_args)

    return _filter_detail_level(result, detail_level)


async def _handle_get_functions_called_by(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Route to get_outgoing_calls or get_call_sites based on return_format."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    return_format = arguments.get("return_format", "function_definitions_summary")

    if return_format == "exact_call_line_locations":
        # Route to get_call_sites (only needs function_name + class_name)
        call_sites_args = {
            "function_name": arguments["function_name"],
            "class_name": arguments.get("class_name", ""),
        }
        return await _handle_tool_call("get_call_sites", call_sites_args)

    # Route to get_outgoing_calls (strip Schema B-only params)
    schema_a_args = {k: v for k, v in arguments.items() if k not in _CALLGRAPH_B_PARAMS}
    result = await _handle_tool_call("get_outgoing_calls", schema_a_args)

    # For summary format, strip location/doc fields for compact output
    if return_format == "function_definitions_summary":
        result = _filter_detail_level(result, "signatures_only")

    return result


async def _handle_find_usage_sites(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Translate find_usage_sites → get_incoming_calls (rename only)."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    return await _handle_tool_call("get_incoming_calls", arguments)


async def _handle_trace_execution_path(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Translate trace_execution_path → get_call_path (rename + param names)."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    schema_a_args: Dict[str, Any] = {
        "from_function": arguments["source_function"],
        "to_function": arguments["target_function"],
    }
    max_depth = arguments.get("max_depth")
    if max_depth is not None:
        schema_a_args["max_depth"] = max_depth

    return await _handle_tool_call("get_call_path", schema_a_args)
