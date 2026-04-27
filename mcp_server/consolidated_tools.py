"""Consolidated MCP tool definitions.

Provides the public tool surface for the C++ analyzer MCP server.
Each consolidated tool maps to one or more internal handlers.

Tool mapping (public      -> internal):
  set_project             -> set_project_directory + wait_for_indexing (sync wait)
  sync_project            -> check_system_status + refresh_project
  find_symbols_by_pattern -> search_classes / search_functions / search_symbols
  find_in_file            -> passthrough
  get_class_info          -> passthrough
  get_class_hierarchy     -> passthrough
  get_type_alias_info     -> passthrough
  find_outgoing_calls     -> find_outgoing_calls / get_call_sites
  find_incoming_calls     -> passthrough
  trace_execution_path    -> get_call_path
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.types import TextContent, Tool

# ---------------------------------------------------------------
# Passthrough: tools delegated to internal handlers without translation
# ---------------------------------------------------------------
_PASSTHROUGH_MAP = {
    "find_in_file": "find_in_file",
    "get_class_info": "get_class_info",
    "get_class_hierarchy": "get_class_hierarchy",
    "get_type_alias_info": "get_type_alias_info",
}

# Default sync timeout for set_project (seconds)
_DEFAULT_SYNC_TIMEOUT = 30

# Consolidated params that must not be forwarded to internal handlers
_SEARCH_CONSOLIDATED_PARAMS = {"target_type", "output_detail_level"}
_CALLGRAPH_CONSOLIDATED_PARAMS = {"return_format"}

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

# System state mapping from state -> simplified enum
_SYSTEM_STATE_MAP = {
    "uninitialized": "not_ready",
    "initializing": "not_ready",
    "indexing": "not_ready",
    "indexed": "ready",
    "refreshing": "partially_ready",
    "error": "error",
}

# All public tool names (for validation)
TOOL_NAMES = [
    "set_project",
    "sync_project",
    "find_symbols_by_pattern",
    "find_in_file",
    "get_class_info",
    "get_class_hierarchy",
    "get_type_alias_info",
    "find_outgoing_calls",
    "find_incoming_calls",
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

    indexing_state = data.get("state", "uninitialized")
    data["system_state"] = _SYSTEM_STATE_MAP.get(indexing_state, "not_ready")
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------


def list_tools_b() -> List[Tool]:
    """Return consolidated tool definitions (10 tools)."""
    return [
        Tool(
            name="set_project",
            description=(
                "REQUIRED FIRST STEP: Set the C++ project to analyze. "
                "The 'path' can be either a project root directory OR a .json configuration file "
                "defining 'project_root'. Using a config file allows multiple analysis profiles "
                "without polluting the source tree.\n\n"
                "Indexes all C++ files and waits for completion (up to sync_timeout seconds). "
                "Returns 'ready' when finished, or 'indexing_in_progress' if timeout exceeded."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to C++ project root directory OR a .json config file.",
                    },
                    "config_file": {
                        "type": "string",
                        "description": "Optional: Path to cpp-analyzer-config.json (if 'path' is a directory).",
                    },
                    "sync_timeout": {
                        "type": "number",
                        "description": (
                            "Max seconds to wait for indexing to complete "
                            "(default: 30). Set higher for large projects."
                        ),
                        "default": 30,
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="sync_project",
            description=(
                "Check project status or refresh the index. "
                "Without arguments: returns current status (system_state enum: "
                "'ready', 'not_ready', 'partially_ready', 'error'). "
                "With refresh_mode: triggers incremental or full re-indexing "
                "of changed files. Use after source files are modified."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "refresh_mode": {
                        "type": "string",
                        "enum": ["incremental", "full"],
                        "description": (
                            "If provided, triggers a refresh. "
                            "'incremental' (default): only changed files (30-300x faster). "
                            "'full': re-index everything (use if cache seems corrupted). "
                            "Omit to just check status."
                        ),
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="find_symbols_by_pattern",
            description=(
                "Discover C++ classes, functions, and methods by name pattern; "
                "optional filters narrow results by symbol kind, namespace, and file path.\n\n"
                "Use this tool when you need to DISCOVER symbols by pattern or enumerate "
                "symbols matching certain criteria (e.g., 'all classes with Manager in name').\n\n"
                "Do NOT use this tool when:\n"
                "- You already know the exact class name and need its hierarchy -> use get_class_hierarchy\n"
                "- You already know the exact class name and need its details -> use get_class_info\n"
                "- You already know the exact function name and need its callers -> use find_incoming_calls\n"
                "- You already know the exact function name and need its callees -> use find_outgoing_calls\n"
                "- You know the exact file name and want ALL symbols in it -> use find_in_file\n\n"
                "Pattern matching (case-insensitive):\n"
                "- 'DataRecord' — matches in any namespace\n"
                "- 'storage::DataRecord' — matches namespace suffix\n"
                "- '.*Manager.*' — regex, matches containing 'Manager'\n"
                "- '' (empty) — matches ALL symbols; combine with file_name or namespace for enumeration\n\n"
                "Enumeration via empty symbol_name + filters:\n"
                "- symbol_name='' + file_name='Helper' — all symbols in files with 'Helper' in path\n"
                "- symbol_name='' + namespace='project' — all symbols in that namespace\n\n"
                "Use symbol_name for C++ symbol names only; use file_name for file or directory prefixes; "
                "use namespace for namespace-scoped searches. "
                "Do not encode file paths or namespaces in the symbol_name when a dedicated filter exists.\n\n"
                "file_name semantics:\n"
                "- Substring match only (NOT glob/regex). 'Helper*.h' -> use file_name='Helper'\n"
                "- If a directory/subdirectory is known, preserve the narrowest path substring.\n"
                "- Examples: 'module/' for that subtree, 'module/tests/' for that exact tests dir\n"
                "- Examples: 'spec/' (files in spec dir), 'SAMPLE_' (files starting with SAMPLE_)\n\n"
                "Returns qualified_name, kind, and more based on detail level."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol_name": {
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
                            "What symbol kinds to return. Default 'all_symbol_types' returns both classes and functions. "
                            "IMPORTANT: When the user explicitly asks for ONLY classes OR ONLY functions, "
                            "you MUST set this parameter accordingly.\n\n"
                            "- 'classes_and_structs_only': class/struct definitions only\n"
                            "- 'functions_and_methods_only': functions and class methods only\n"
                            "- 'all_symbol_types': both classes and functions (default)\n\n"
                            "Examples:\n"
                            "- 'Find all classes with Widget in the name' -> target_type='classes_and_structs_only'\n"
                            "- 'List functions in files starting with Util_' -> target_type='functions_and_methods_only'"
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
                            "Optional: Filter by substring match on file path. "
                            "Examples: 'Record.h' (exact file), 'SAMPLE_' (files "
                            "starting with SAMPLE_), 'spec/' (files in spec dir)."
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
                "required": ["symbol_name"],
            },
        ),
        Tool(
            name="find_in_file",
            description=(
                "List all symbols defined in ONE specific file you already know by exact name.\n\n"
                "Use this when the user names ONE concrete file and asks what symbols are in it. "
                "Requires a concrete file path (absolute, relative, or basename). "
                "Empty pattern returns all symbols in that file.\n\n"
                "Examples:\n"
                "- 'What is defined in Foo.h?' -> find_in_file('Foo.h')\n"
                "- 'List symbols in src/main.cpp' -> find_in_file('src/main.cpp')\n\n"
                "Do NOT use this for searching across multiple files or file patterns — "
                "use find_symbols_by_pattern with file_name filter instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Concrete file path (absolute, relative, or basename).",
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
                "derived classes, and documentation.\n\n"
                "IMPORTANT: Call directly when the class name is known from the query; "
                "do NOT call find_symbols_by_pattern first to 'verify' the class exists. "
                "This tool accepts simple names ('DataManager') and qualified names ('app::DataManager') directly. "
                "Handles ambiguities when a name matches multiple classes.\n\n"
                "If you need the full inheritance tree, subclasses, or implementations, "
                "use get_class_hierarchy instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": (
                            "Exact class name (simple or qualified, "
                            "e.g. 'DataRecord' or 'storage::DataRecord')."
                        ),
                    },
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="get_class_hierarchy",
            description=(
                "Get inheritance graph for a class — ancestors, descendants, or both as a flat adjacency list.\n\n"
                "IMPORTANT: Call directly when you know the class name; do NOT call find_symbols_by_pattern first. "
                "This tool accepts simple names ('Widget') and qualified names ('UI::Widget') directly.\n\n"
                "Use for: full inheritance trees, interface implementations, subclass discovery.\n\n"
                "Traversal direction:\n"
                "- 'both' (default): ancestors AND descendants, but avoids explosion through shared bases\n"
                "- 'up': ancestors only (base classes and their bases)\n"
                "- 'down': descendants only (derived classes and their derivations)\n\n"
                "Output formats:\n"
                "- 'json' (default): Full structured JSON with all metadata\n"
                "- 'compact': Abbreviated JSON (smaller payload)\n"
                "- 'cpp': C++ pseudocode format — compact, readable inheritance view\n"
                "- 'cpp_with_meta': C++ format with metadata comments\n\n"
                "Examples:\n"
                "- 'full hierarchy of X' -> get_class_hierarchy('X', direction='both')\n"
                "- 'all implementations of IProcessor' -> get_class_hierarchy('IProcessor', direction='down')\n"
                "- 'base classes of Widget' -> get_class_hierarchy('Widget', direction='up')\n"
                "- 'compact view of Widget' -> get_class_hierarchy('Widget', output_format='compact')\n"
                "- 'C++ view of Widget' -> get_class_hierarchy('Widget', output_format='cpp')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Class name to get hierarchy for.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "both"],
                        "description": (
                            "Traversal direction: 'up' (ancestors only), "
                            "'down' (descendants only), 'both' (ancestors and descendants). "
                            "Default is 'both'."
                        ),
                        "default": "both",
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
                    "output_format": {
                        "type": "string",
                        "enum": ["json", "compact", "cpp", "cpp_with_meta"],
                        "description": (
                            "Output format: 'json' (default, full details), "
                            "'compact' (abbreviated JSON), "
                            "'cpp' (C++ pseudocode, 70% smaller), "
                            "'cpp_with_meta' (C++ with metadata comments)."
                        ),
                        "default": "json",
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
            name="find_outgoing_calls",
            description=(
                "OUTBOUND call graph: find functions that the specified function calls (X -> callees).\n\n"
                "Use for: what X calls, what X invokes, X's dependencies/callees, outgoing calls from X, "
                "functions called BY X (where X is the caller).\n\n"
                "Do NOT use for: who calls X, what calls X, callers of X, where is X used — "
                "those are INBOUND queries; use find_incoming_calls instead.\n\n"
                "Direction quick reference:\n"
                "- X calls Y -> find_outgoing_calls (this tool, X is the subject)\n"
                "- Y calls X -> find_incoming_calls (other tool, X is the subject)\n\n"
                "Call directly when function name is known from the query; do not search first.\n\n"
                "Return format:\n"
                "- 'function_definitions_summary' (default): callee names + file locations\n"
                "- 'function_definitions_full': complete signatures + metadata\n"
                "- 'exact_call_line_locations': file:line:column of every call within the function"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Function name to inspect.",
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
            name="find_incoming_calls",
            description=(
                "INBOUND call graph: find all functions that call the specified function (callers -> X).\n\n"
                "Use for: who calls X, what calls X, callers of X, where is X used/invoked, "
                "functions that depend on X, code that references X.\n\n"
                "Do NOT use for: what X calls, what X invokes, X's callees/dependencies — "
                "those are OUTBOUND queries; use find_outgoing_calls instead.\n\n"
                "Direction quick reference:\n"
                "- Y calls X -> find_incoming_calls (this tool, X is the subject)\n"
                "- X calls Y -> find_outgoing_calls (other tool, X is the subject)\n\n"
                "Call directly when function name is known from the query; do not search first."
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
                            "'project_code_only' (default) or 'include_external_libraries'."
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
                "Find execution paths between a source and target function using BFS. "
                "Returns all call chains from source to target within max_depth hops.\n\n"
                "Use when both source and target are known and you need paths between them. "
                "If you only need what X calls, use find_outgoing_calls instead.\n\n"
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
    """Dispatch consolidated tool calls, delegating to internal handlers."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    # Passthrough tools — delegate directly with same name and args
    if name in _PASSTHROUGH_MAP:
        return await _handle_tool_call(_PASSTHROUGH_MAP[name], arguments)

    if name == "set_project":
        return await _handle_set_project(arguments)

    if name == "sync_project":
        return await _handle_sync_project(arguments)

    if name == "find_symbols_by_pattern":
        return await _handle_search_codebase(arguments)

    if name == "find_outgoing_calls":
        return await _handle_find_outgoing_calls(arguments)

    if name == "find_incoming_calls":
        return await _handle_find_incoming_calls(arguments)

    if name == "trace_execution_path":
        return await _handle_trace_execution_path(arguments)

    return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]


async def _handle_set_project(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle set_project: set directory + synchronous wait for indexing."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    # Map 'path' -> 'project_path' for internal handler
    internal_args: Dict[str, Any] = {
        "project_path": arguments["path"],
    }
    if "config_file" in arguments:
        internal_args["config_file"] = arguments["config_file"]

    # Step 1: Set project directory (starts background indexing)
    await _handle_tool_call("set_project_directory", internal_args)

    # Step 2: Determine sync timeout
    sync_timeout = _resolve_sync_timeout(arguments.get("sync_timeout"))

    # Step 3: Wait for indexing to complete (synchronous fast-path)
    await _handle_tool_call("wait_for_indexing", {"timeout": sync_timeout})

    # Step 4: Build response with status
    status_result = await _handle_tool_call("check_system_status", {})
    status_result = _add_system_state(status_result)

    try:
        status_data = json.loads(status_result[0].text)
        system_state = status_data.get("system_state", "not_ready")
    except (json.JSONDecodeError, IndexError, AttributeError):
        system_state = "not_ready"

    response = {
        "project_path": arguments["path"],
        "status": "ready" if system_state == "ready" else "indexing_in_progress",
    }

    # Add stats if ready
    if system_state == "ready":
        try:
            response["indexed_classes"] = status_data.get("indexed_classes", 0)
            response["indexed_functions"] = status_data.get("indexed_functions", 0)
            response["parsed_files"] = status_data.get("parsed_files", 0)
        except (TypeError, KeyError):
            pass

    return [TextContent(type="text", text=json.dumps(response, indent=2))]


async def _handle_sync_project(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle sync_project: status check or refresh trigger."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    refresh_mode = arguments.get("refresh_mode")

    if refresh_mode is not None:
        # Trigger refresh
        await _handle_tool_call("refresh_project", {"refresh_mode": refresh_mode})

        # Wait briefly for completion
        sync_timeout = _resolve_sync_timeout(None)
        await _handle_tool_call("wait_for_indexing", {"timeout": sync_timeout})

    # Always return current status
    result = await _handle_tool_call("check_system_status", {})
    return _add_system_state(result)


def _resolve_sync_timeout(param_value: Optional[float]) -> float:
    """Resolve sync timeout: param > env var > default."""
    if param_value is not None:
        return float(param_value)
    env_val = os.environ.get("CPP_ANALYZER_SYNC_TIMEOUT")
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return float(_DEFAULT_SYNC_TIMEOUT)


async def _handle_search_codebase(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Route search_codebase to search_classes/search_functions/search_symbols."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    target_type = arguments.get("target_type", "all_symbol_types")
    detail_level = arguments.get("output_detail_level", "locations_and_metadata")

    # Forward only internal params
    schema_a_args = {k: v for k, v in arguments.items() if k not in _SEARCH_CONSOLIDATED_PARAMS}

    if target_type == "classes_and_structs_only":
        result = await _handle_tool_call("search_classes", schema_a_args)
    elif target_type == "functions_and_methods_only":
        result = await _handle_tool_call("search_functions", schema_a_args)
    else:  # all_symbol_types
        result = await _handle_tool_call("search_symbols", schema_a_args)

    return _filter_detail_level(result, detail_level)


async def _handle_find_outgoing_calls(
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
    schema_a_args = {k: v for k, v in arguments.items() if k not in _CALLGRAPH_CONSOLIDATED_PARAMS}
    result = await _handle_tool_call("get_outgoing_calls", schema_a_args)

    # For summary format, strip location/doc fields for compact output
    if return_format == "function_definitions_summary":
        result = _filter_detail_level(result, "signatures_only")

    return result


async def _handle_find_incoming_calls(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Translate find_incoming_calls -> find_incoming_calls (rename only)."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    return await _handle_tool_call("find_incoming_calls", arguments)


async def _handle_trace_execution_path(
    arguments: Dict[str, Any],
) -> List[TextContent]:
    """Translate trace_execution_path -> get_call_path (rename + param names)."""
    from mcp_server.cpp_mcp_server import _handle_tool_call

    schema_a_args: Dict[str, Any] = {
        "from_function": arguments["source_function"],
        "to_function": arguments["target_function"],
    }
    max_depth = arguments.get("max_depth")
    if max_depth is not None:
        schema_a_args["max_depth"] = max_depth

    return await _handle_tool_call("get_call_path", schema_a_args)
