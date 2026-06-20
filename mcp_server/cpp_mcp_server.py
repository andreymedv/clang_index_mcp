"""
C++ Code Analysis MCP Server

Provides tools for analyzing C++ codebases using libclang.
Focused on specific queries rather than bulk data dumps.
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple, cast

# Import diagnostics early
try:
    from mcp_server import diagnostics
except ImportError:
    from . import diagnostics

try:
    from clang.cindex import Config  # noqa: F401
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)

from mcp.server import Server
from mcp.types import TextContent, Tool

from mcp_server.tool_registry import ToolRegistry
import mcp_server.consolidated_tools  # noqa: F401

try:
    from mcp_server.libclang_setup import configure_libclang, get_libclang_runtime_info
except ImportError:
    from libclang_setup import configure_libclang, get_libclang_runtime_info  # type: ignore[no-redef]


def find_and_configure_libclang():
    """Backwards-compatible wrapper around shared libclang setup."""
    return configure_libclang()


# Try to find and configure libclang
if not find_and_configure_libclang():
    diagnostics.fatal("Could not find libclang library.")
    diagnostics.fatal("Please install LLVM/Clang:")
    diagnostics.fatal("  Windows: Download from https://releases.llvm.org/")
    diagnostics.fatal("  macOS: brew install llvm")
    diagnostics.fatal("  Linux: sudo apt install libclang-dev")
    sys.exit(1)

diagnostics.info(f"libclang runtime config: {get_libclang_runtime_info()}")

# Import the Python analyzer and state manager
try:
    # Try package import first (when run as module)
    from mcp_server import suggestions
    from mcp_server.cpp_analyzer import CppAnalyzer
    from mcp_server.session_manager import SessionManager
    from mcp_server.state_manager import (
        AnalyzerState,
        AnalyzerStateManager,
        BackgroundIndexer,
        EnhancedQueryResult,
        IndexingProgress,
        QueryBehaviorPolicy,
    )
    from mcp_server.tool_call_logger import ToolCallLogger
except ImportError:
    # Fall back to direct import (when run as script)
    import suggestions  # type: ignore[no-redef]
    from cpp_analyzer import CppAnalyzer  # type: ignore[no-redef]
    from session_manager import SessionManager  # type: ignore[no-redef]
    from state_manager import (  # type: ignore[no-redef]
        AnalyzerState,
        AnalyzerStateManager,
        BackgroundIndexer,
        EnhancedQueryResult,
        IndexingProgress,
        QueryBehaviorPolicy,
    )
    from tool_call_logger import ToolCallLogger  # type: ignore[no-redef]

# Initialize analyzer
PROJECT_ROOT = os.environ.get("CPP_PROJECT_ROOT", None)

# Initialize analyzer as None - will be set when project directory is specified
analyzer: Optional["CppAnalyzer"] = None

# State management for analyzer lifecycle
state_manager = AnalyzerStateManager()

# Background indexer for async indexing
background_indexer = None

# Session manager for persistence across restarts
session_manager = SessionManager()

# Track if analyzer has been initialized with a valid project
# TODO Phase 3: This boolean will be replaced by state_manager checks in async mode
analyzer_initialized = False

# Tool call telemetry logger (enabled via MCP_TOOL_LOGGING=1)
tool_call_logger = None

# Valid search_scope values
_VALID_SEARCH_SCOPES = ("project_code_only", "include_external_libraries")


def _parse_search_scope(arguments: Dict[str, Any]) -> bool:
    """Convert search_scope string enum to project_only bool.

    Returns True (project_only) for 'project_code_only' (default),
    False for 'include_external_libraries'.
    Raises ValueError for invalid values.
    """
    scope: str = arguments.get("search_scope", "project_code_only")
    if scope not in _VALID_SEARCH_SCOPES:
        raise ValueError(
            f"Invalid search_scope '{scope}'. " f"Must be one of: {', '.join(_VALID_SEARCH_SCOPES)}"
        )
    return bool(scope == "project_code_only")


# MCP Server
server = Server("cpp-analyzer")


@server.list_tools()
async def list_tools() -> List[Tool]:
    return cast(List[Tool], ToolRegistry.call_tool("list_tools_b"))


def _parse_query_policy(policy_str: str) -> QueryBehaviorPolicy:
    """Parse a query behavior policy string with fallback to ALLOW_PARTIAL."""
    try:
        return QueryBehaviorPolicy(policy_str)
    except ValueError:
        diagnostics.warning(
            f"Invalid query_behavior_policy: {policy_str}, defaulting to allow_partial"
        )
        return QueryBehaviorPolicy.ALLOW_PARTIAL


def _build_block_message(progress) -> str:
    """Build a message explaining that queries are blocked due to indexing."""
    if progress:
        return (
            f"Query blocked: Indexing in progress ({progress.completion_percentage:.1f}% complete, "
            f"{progress.indexed_files:,}/{progress.total_files:,} files). Waiting for indexing to complete...\n\n"
            f"Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial "
            f"to allow queries during indexing."
        )
    return (
        "Query blocked: Indexing in progress. Waiting for completion...\n\n"
        "Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial."
    )


def _build_reject_message(progress) -> str:
    """Build a message explaining that queries are rejected due to indexing."""
    if progress:
        return (
            f"ERROR: Query rejected - indexing in progress ({progress.completion_percentage:.1f}% complete, "
            f"{progress.indexed_files:,}/{progress.total_files:,} files).\n\n"
            f"Queries are not allowed until indexing completes. Options:\n"
            f"1. Use 'sync_project' tool to wait for completion\n"
            f"2. Check progress with 'sync_project'\n"
            f"3. Set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial to allow partial results\n"
            f"4. Set CPP_ANALYZER_QUERY_BEHAVIOR=block to auto-wait for completion"
        )
    return (
        "ERROR: Query rejected - indexing in progress.\n\n"
        "Use 'sync_project' or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial/block."
    )


def check_query_policy(tool_name: str) -> tuple[bool, str]:
    """
    Check if query is allowed based on current indexing state and policy.

    Args:
        tool_name: Name of the tool being called

    Returns:
        Tuple of (allowed: bool, message: str)
        - If allowed=True, query can proceed (message will be empty)
        - If allowed=False, query should be blocked/rejected (message contains error/wait info)
    """
    if state_manager.is_fully_indexed():
        return (True, "")

    if not state_manager.is_ready_for_queries():
        return (True, "")

    if analyzer is None:
        return (True, "")

    policy = _parse_query_policy(analyzer.config.get_query_behavior_policy())

    if policy == QueryBehaviorPolicy.ALLOW_PARTIAL:
        return (True, "")

    if policy == QueryBehaviorPolicy.BLOCK:
        message = _build_block_message(state_manager.get_progress())
        completed = state_manager.wait_for_indexed(timeout=30.0)
        if completed:
            return (True, "")
        return (
            False,
            message
            + "\n\nTimeout waiting for indexing (30s). Try again later or use 'sync_project'.",
        )

    if policy == QueryBehaviorPolicy.REJECT:
        return (False, _build_reject_message(state_manager.get_progress()))

    return (True, "")


def _create_search_result(
    data: Any,
    state_manager: AnalyzerStateManager,
    tool_name: str,
    max_results: Optional[int] = None,
    total_count: Optional[int] = None,
    fallback: Any = None,
    empty_suggestions: Optional[List[str]] = None,
) -> EnhancedQueryResult:
    """
    Create an EnhancedQueryResult with appropriate metadata based on special conditions.

    Design principle: Silence = Success. Metadata only appears for special conditions
    that require LLM guidance (empty, truncated, large, partial).

    Args:
        data: Query result data (list or dict with lists)
        state_manager: State manager for checking indexing status
        tool_name: Name of the tool (for customized messages)
        max_results: If specified, max_results limit was applied
        total_count: Total count before truncation (when max_results is specified)
        fallback: Optional FallbackResult from smart_fallback module
        empty_suggestions: Custom suggestions for the empty-result case.  When None,
            create_empty() uses its own default "search" suggestions.  Pass an explicit
            list (including []) to override those defaults.

    Returns:
        EnhancedQueryResult with appropriate metadata
    """
    # Priority 1: Check for partial indexing (always takes precedence)
    if not state_manager.is_fully_indexed():
        return EnhancedQueryResult.create_from_state(data, state_manager, tool_name)

    # Calculate result count for both list and dict data
    if isinstance(data, list):
        result_count = len(data)
    elif isinstance(data, dict):
        # For search_symbols which returns {"classes": [...], "functions": [...]}
        result_count = sum(len(v) for v in data.values() if isinstance(v, list))
    else:
        result_count = 0

    # Priority 2: Check for empty results (with smart fallback if available)
    if result_count == 0:
        return EnhancedQueryResult.create_empty(
            data, suggestions=empty_suggestions, fallback=fallback
        )

    # Priority 3: Check for truncation (max_results was specified and applied)
    if max_results is not None and total_count is not None and total_count > max_results:
        return EnhancedQueryResult.create_truncated(data, result_count, total_count)

    # Priority 4: Check for large result set (>20 results without max_results)
    if max_results is None and result_count > EnhancedQueryResult.LARGE_RESULT_THRESHOLD:
        return EnhancedQueryResult.create_large(data, result_count)

    # Default: Normal result (no metadata - silence = success)
    return EnhancedQueryResult.create_normal(data)


def _count_results_from_text(result_text: str) -> int:
    """Extract result count from JSON text for telemetry."""
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, list):
            return len(parsed)
        if isinstance(parsed, dict):
            results_list = parsed.get("results")
            if isinstance(results_list, list):
                return len(results_list)
            for key in ("callers", "callees"):
                sub = parsed.get(key)
                if isinstance(sub, list):
                    return len(sub)
    except (json.JSONDecodeError, TypeError):
        pass
    return 0


def _try_log_tool_call(name: str, arguments: Dict[str, Any], result: List[TextContent]) -> None:
    """Log a tool call for telemetry. Never raises."""
    try:
        if tool_call_logger is None or not tool_call_logger.enabled:
            return
        result_text = result[0].text if result else ""
        result_count = _count_results_from_text(result_text)
        tool_call_logger.log_tool_call(
            name, arguments, result_count, result_text, analyzer=analyzer
        )
    except Exception:
        pass  # Telemetry must never break tool calls


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    result = cast(
        List[TextContent], await ToolRegistry.call_tool("handle_tool_call_b", name, arguments)
    )
    _try_log_tool_call(name, arguments, result)
    return result


def _validate_config_file(config_file: Any) -> Tuple[Optional[str], Optional[List[TextContent]]]:
    if not config_file or not isinstance(config_file, str) or not config_file.strip():
        return None, [
            TextContent(type="text", text="Error: 'config_file' must be a non-empty string")
        ]

    config_file = config_file.strip()

    if not os.path.isabs(config_file):
        return None, [
            TextContent(type="text", text=f"Error: '{config_file}' is not an absolute path")
        ]

    if not os.path.isfile(config_file):
        return None, [
            TextContent(type="text", text=f"Error: Config file '{config_file}' does not exist")
        ]

    if not config_file.endswith(".json"):
        return None, [
            TextContent(
                type="text",
                text=f"Error: Config file '{config_file}' must have .json extension",
            )
        ]

    return config_file, None


async def _handle_set_project_directory(arguments: Dict[str, Any]) -> List[TextContent]:
    config_file_raw = arguments.get("config_file")
    auto_refresh = arguments.get("auto_refresh", True)

    config_file, error_response = _validate_config_file(config_file_raw)
    if error_response:
        return error_response
    assert config_file is not None

    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)

        config_root = config_data.get("project_root")
        if not config_root:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Config file '{config_file}' is missing 'project_root' field",
                )
            ]

        # Resolve project_root relative to config file directory
        config_dir = os.path.dirname(config_file)  # type: ignore[arg-type]
        project_path = os.path.abspath(os.path.join(config_dir, config_root))

        if not os.path.isdir(project_path):
            return [
                TextContent(
                    type="text",
                    text=f"Error: 'project_root' in config '{project_path}' is not a directory or does not exist",
                )
            ]

        diagnostics.info(f"Using config {config_file} for root {project_path}")

    except Exception as e:
        return [TextContent(type="text", text=f"Error reading config file: {str(e)}")]

    # Re-initialize analyzer with new path and config
    global analyzer, background_indexer, tool_call_logger

    # Transition to INDEXING state (allows immediate queries with partial results)
    # This prevents race condition where get_indexing_status fails if called immediately
    state_manager.transition_to(AnalyzerState.INDEXING)
    analyzer = CppAnalyzer(project_path, config_file=config_file)
    background_indexer = BackgroundIndexer(analyzer, state_manager)

    # Initialize tool call telemetry logger
    import uuid as _uuid

    tool_call_logger = ToolCallLogger(analyzer.cache_dir, str(_uuid.uuid4()))

    # Start indexing in background (truly asynchronous, non-blocking)
    # The task will run independently while the MCP server continues to handle requests
    async def run_background_indexing():
        global analyzer_initialized
        try:
            # FAST PATH: Check if cache exists and is valid
            # If so, load directly without calling index_project
            loop = asyncio.get_event_loop()
            cache_valid = await loop.run_in_executor(None, analyzer._load_cache)

            if cache_valid:
                # Cache loaded successfully - skip indexing
                diagnostics.info(
                    f"Cache loaded successfully: "
                    f"{len(analyzer.context.symbol_store.class_index)} classes, "
                    f"{len(analyzer.context.symbol_store.function_index)} functions indexed"
                )

                # CRITICAL FIX FOR ISSUE #15: Initialize progress with cache data
                # Without this, get_indexing_status returns 0 files even though cache is loaded
                from datetime import datetime

                from .state_manager import IndexingProgress

                # Create progress object from cached data
                total_files = len(analyzer.context.symbol_store.file_index)
                progress = IndexingProgress(
                    total_files=total_files,
                    indexed_files=total_files,  # All files loaded from cache
                    failed_files=0,  # No failures when loading from cache
                    cache_hits=total_files,  # Everything came from cache
                    current_file=None,  # No active file
                    start_time=datetime.now(),
                    estimated_completion=None,  # Already complete
                )
                state_manager.update_progress(progress)

                state_manager.transition_to(AnalyzerState.INDEXED)

                # Mark as initialized immediately
                global analyzer_initialized
                analyzer_initialized = True

                diagnostics.info(
                    "Server ready (loaded from cache) - use sync_project with refresh_mode to detect file changes"
                )
                return

            # SLOW PATH: Cache not valid, need to index from scratch
            diagnostics.info("No valid cache found, starting full indexing...")
            await background_indexer.start_indexing(force=False, include_dependencies=True)

            # Indexing complete - mark as initialized
            analyzer_initialized = True

        except Exception as e:
            diagnostics.error(f"Background indexing failed: {e}")
            state_manager.transition_to(AnalyzerState.ERROR)
            pass

    # Create background task (non-blocking)
    asyncio.create_task(run_background_indexing())

    # Save session for auto-resume on restart
    session_manager.save_session(config_file=config_file)

    # Build response message
    auto_refresh_msg = " Auto-refresh enabled." if auto_refresh else " Auto-refresh disabled."

    # Return immediately - indexing continues in background
    return [
        TextContent(
            type="text",
            text=f"Set project via config: {config_file}\n"
            f"Resolved project root: {project_path}\n"
            f"Indexing started in background.{auto_refresh_msg}\n"
            f"Use 'sync_project' to check progress.\n"
            f"Tools are available but will return partial results until indexing completes.",
        )
    ]


async def _handle_search_classes(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    project_only = _parse_search_scope(arguments)
    pattern = arguments["symbol_name"]
    file_name = arguments.get("file_name", None)
    namespace = arguments.get("namespace", None)
    max_results = arguments.get("max_results", None)
    include_base_classes = arguments.get("include_base_classes", True)

    # Run synchronous method in executor to avoid blocking event loop
    with state_manager.tool_execution():
        raw_results = await loop.run_in_executor(
            None,
            lambda: analyzer.search_classes(
                pattern,
                project_only,
                file_name,
                namespace,
                max_results,
                include_base_classes,
            ),
        )

    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None

    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, state_manager, "search_classes", max_results, total_count, fallback
    )
    if results:
        enhanced_result.next_steps = suggestions.for_search_classes(
            results,
            pattern=pattern,
            file_name=file_name,
            namespace=namespace,
        )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_search_functions(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    project_only = _parse_search_scope(arguments)
    class_name = arguments.get("class_name", None)
    file_name = arguments.get("file_name", None)
    namespace = arguments.get("namespace", None)
    pattern = arguments["symbol_name"]
    max_results = arguments.get("max_results", None)
    signature_pattern = arguments.get("signature_pattern", None)
    include_attributes = arguments.get("include_attributes", False)

    # Run synchronous method in executor to avoid blocking event loop
    with state_manager.tool_execution():
        raw_results = await loop.run_in_executor(
            None,
            lambda: analyzer.search_functions(
                pattern,
                project_only,
                class_name,
                file_name,
                namespace,
                max_results,
                signature_pattern,
                include_attributes,
            ),
        )

    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None

    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, state_manager, "search_functions", max_results, total_count, fallback
    )
    if results:
        enhanced_result.next_steps = suggestions.for_search_functions(results)
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_get_class_info(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    class_name = str(arguments["class_name"])
    # Run synchronous method in executor to avoid blocking event loop
    result = await loop.run_in_executor(None, lambda: analyzer.get_class_info(class_name))
    # Wrap with metadata (even if not found)
    enhanced_result = EnhancedQueryResult.create_from_state(result, state_manager, "get_class_info")
    if result and "error" not in (result or {}):
        enhanced_result.next_steps = suggestions.for_get_class_info(result)
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_get_type_alias_info(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    type_name = arguments["type_name"]
    # Run synchronous method in executor to avoid blocking event loop
    result = await loop.run_in_executor(None, lambda: analyzer.get_type_alias_info(type_name))
    # Wrap with metadata
    enhanced_result = EnhancedQueryResult.create_from_state(
        result, state_manager, "get_type_alias_info"
    )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_search_symbols(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    pattern = arguments["symbol_name"]
    project_only = _parse_search_scope(arguments)
    symbol_types = arguments.get("symbol_types", None)
    namespace = arguments.get("namespace", None)
    max_results = arguments.get("max_results", None)
    signature_pattern = arguments.get("signature_pattern", None)
    # Run synchronous method in executor to avoid blocking event loop
    raw_results = await loop.run_in_executor(
        None,
        lambda: analyzer.search_symbols(
            pattern,
            project_only,
            symbol_types,
            namespace,
            max_results,
            signature_pattern,
        ),
    )
    fallback = analyzer.pop_last_fallback()
    # Handle tuple return (results, total_count) when max_results is specified
    if isinstance(raw_results, tuple):
        results, total_count = raw_results
    else:
        results, total_count = raw_results, None
    # Wrap with appropriate metadata based on special conditions
    enhanced_result = _create_search_result(
        results, state_manager, "search_symbols", max_results, total_count, fallback
    )
    return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]


async def _handle_find_in_file(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    file_path = arguments["file_path"]
    pattern = arguments["pattern"]
    # Run synchronous method in executor to avoid blocking event loop
    with state_manager.tool_execution():
        results = await loop.run_in_executor(
            None, lambda: analyzer.find_in_file(file_path, pattern)
        )
    # find_in_file returns {"results": [...], "matched_files": [...], ...}
    # Count the actual symbol results for metadata logic
    result_list = results.get("results", []) if isinstance(results, dict) else []
    # Wrap with appropriate metadata based on special conditions
    # Use _create_search_result with the result list for counting
    enhanced_result = _create_search_result(result_list, state_manager, "find_in_file", None, None)
    # But return the full results dict (with matched_files, suggestions, etc.)
    # Merge the metadata into the results dict
    output = results.copy() if isinstance(results, dict) else {"results": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _ensure_analyzer_resumed() -> bool:
    """Ensure analyzer is initialized, attempting auto-resume if needed."""
    global analyzer, background_indexer, analyzer_initialized
    if analyzer is not None:
        return True

    diagnostics.info("Attempting auto-resume of last used session...")
    disable_auto_resume = os.environ.get("MCP_DISABLE_SESSION_RESUME", "false").lower() == "true"
    saved_session = None if disable_auto_resume else session_manager.load_session()
    if saved_session:
        analyzer, background_indexer, analyzer_initialized = _try_resume_session(saved_session)

    return analyzer is not None


async def _run_background_refresh(refresh_mode: str):
    """Background task to perform project refresh (incremental or full)."""
    assert analyzer is not None
    try:
        loop = asyncio.get_event_loop()

        # Create progress callback that updates state_manager (same as BackgroundIndexer)
        def progress_callback(progress: IndexingProgress):
            """Callback to update progress in state manager during refresh"""
            state_manager.update_progress(progress)

        def wait_for_tools():
            """Wrapper to match Callable[[], None] expected by analyzers"""
            state_manager.wait_for_tools_to_finish()

        if refresh_mode == "incremental":
            diagnostics.info("Starting incremental refresh...")
        else:
            diagnostics.info("Starting full refresh...")

        modified_count = await loop.run_in_executor(
            None, lambda: analyzer.refresh_if_needed(progress_callback, wait_for_tools)
        )
        diagnostics.info(f"Refresh complete: re-analyzed {modified_count} files")
        state_manager.transition_to(AnalyzerState.INDEXED)
        return

    except Exception as e:
        diagnostics.error(f"Background refresh failed: {e}")
        state_manager.transition_to(AnalyzerState.ERROR)
        pass


async def _handle_refresh_project(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle refresh_project: trigger incremental or full re-indexing."""
    # 1. If analyzer is None, try to resume session from last used config
    if not await _ensure_analyzer_resumed():
        return [
            TextContent(
                type="text",
                text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.",
            )
        ]

    refresh_mode = arguments.get("refresh_mode", "incremental")

    # Issue #7: Warn if full mode is used (should be rare)
    if refresh_mode == "full":
        diagnostics.warning(
            "refresh_mode='full' was requested - this will re-analyze ALL files and may "
            "take 5-10 minutes on large projects. Incremental mode is 30-300x faster "
            "and sufficient for 99% of cases."
        )

    # Transition to REFRESHING state synchronously
    state_manager.transition_to(AnalyzerState.REFRESHING)

    # Create background task (non-blocking)
    asyncio.create_task(_run_background_refresh(refresh_mode))

    # Return immediately - refresh continues in background
    return [
        TextContent(
            type="text",
            text=f"Refresh started in background (mode: {refresh_mode}).\n"
            f"Use 'sync_project' to check progress.\n"
            f"Tools will continue to work and return results based on current cache state.",
        )
    ]


async def _handle_check_system_status(arguments: Dict[str, Any]) -> List[TextContent]:
    # Combined server diagnostics and indexing status
    status_dict = state_manager.get_status_dict()
    status_dict["analyzer_type"] = "python_enhanced"

    if analyzer is None:
        return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]

    ccm = analyzer.context.compile_commands_manager
    symbol_store = analyzer.context.symbol_store
    assert symbol_store is not None
    total_classes = sum(len(infos) for infos in symbol_store.class_index.values())
    total_functions = sum(len(infos) for infos in symbol_store.function_index.values())

    status_dict.update(
        {
            "call_graph_enabled": True,
            "compile_commands_enabled": ccm.enabled if ccm else False,
            "compile_commands_path": ccm.compile_commands_path if ccm else None,
            "parsed_files": len(symbol_store.file_index),
            "indexed_classes": total_classes,
            "indexed_functions": total_functions,
        }
    )
    return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]


async def _handle_wait_for_indexing(arguments: Dict[str, Any]) -> List[TextContent]:
    loop = asyncio.get_event_loop()
    # Internal handler - used by sync_project and tests
    timeout = arguments.get("timeout", 60.0)

    if state_manager.is_fully_indexed():
        return [TextContent(type="text", text="Indexing already complete.")]

    completed = await loop.run_in_executor(None, lambda: state_manager.wait_for_indexed(timeout))

    if completed:
        progress = state_manager.get_progress()
        indexed_count = progress.indexed_files if progress else 0
        failed_count = progress.failed_files if progress else 0
        return [
            TextContent(
                type="text",
                text=f"Indexing complete! Indexed {indexed_count} files successfully ({failed_count} failed).",
            )
        ]
    else:
        return [
            TextContent(
                type="text",
                text=f"Timeout waiting for indexing (waited {timeout}s). Use 'sync_project' to check progress.",
            )
        ]


async def _handle_get_class_hierarchy(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    class_name = str(arguments["class_name"])
    max_nodes = arguments.get("max_nodes", 200)
    max_depth = arguments.get("max_depth", None)
    direction = arguments.get("direction", "both")
    output_format = arguments.get("output_format", "json")
    # Run synchronous method in executor to avoid blocking event loop
    hierarchy = await loop.run_in_executor(
        None,
        lambda: analyzer.get_class_hierarchy(
            class_name, max_nodes=max_nodes, max_depth=max_depth, direction=direction
        ),
    )
    if hierarchy:
        # Check for error in hierarchy result
        if "error" in hierarchy:
            from .hierarchy_format import format_hierarchy_error

            error_text = format_hierarchy_error(hierarchy["error"], output_format)
            return [TextContent(type="text", text=error_text)]
        # Convert to requested output format
        from .hierarchy_format import convert_hierarchy_format

        formatted = convert_hierarchy_format(hierarchy, output_format)
        return [TextContent(type="text", text=formatted)]
    else:
        from .hierarchy_format import format_hierarchy_error

        error_text = format_hierarchy_error(f"Class '{class_name}' not found", output_format)
        return [TextContent(type="text", text=error_text)]


async def _handle_find_incoming_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = str(arguments["function_name"])
    class_name = str(arguments.get("class_name", ""))
    max_results = arguments.get("max_results", None)
    project_only = _parse_search_scope(arguments)
    # Run synchronous method in executor to avoid blocking event loop
    results = await loop.run_in_executor(
        None,
        lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=project_only),
    )
    # Results is dict with "callers" list - use that for metadata logic
    callers_list = results.get("callers", []) if isinstance(results, dict) else []
    # 3-case empty-result logic (internal flags stripped before sending to LLM):
    #   not found            → default "check spelling" suggestions  (None)
    #   found, no callers    → no hints at all                        ([])
    #   found, ext. callers  → auto-expand to include external results
    function_found = results.pop("_function_found", False) if isinstance(results, dict) else False
    has_any_in_graph = (
        results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
    )
    target_qualified_name = (
        results.pop("_target_qualified_name", None) if isinstance(results, dict) else None
    )
    # Auto-expand: when project_only=True yields 0 results but external callers
    # exist, re-fetch with project_only=False so the LLM gets useful data without
    # needing to interpret a suggestion and issue a second tool call.
    search_note = None
    if project_only and not callers_list and function_found and has_any_in_graph:
        expanded = await loop.run_in_executor(
            None,
            lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=False),
        )
        # Strip internal flags from expanded results
        expanded.pop("_function_found", None)
        expanded.pop("_has_any_in_graph", None)
        expanded.pop("_target_qualified_name", None)
        results = expanded
        callers_list = results.get("callers", [])
        ext_count = len(callers_list)
        search_note = (
            f"Project-only search yielded 0 results. "
            f"Auto-expanded to include external libraries "
            f"({ext_count} external caller{'s' if ext_count != 1 else ''} found)."
        )
    total_count = len(callers_list)
    # Apply truncation if max_results specified
    if max_results is not None and len(callers_list) > max_results:
        results["callers"] = callers_list[:max_results]
    empty_suggestions: Optional[List[str]] = None
    if not function_found:
        pass  # None → default "check spelling / broaden pattern"
    elif has_any_in_graph:
        empty_suggestions = []  # auto-expanded above; no hint needed
    else:
        empty_suggestions = []  # genuinely no callers → no hints
    # Wrap with appropriate metadata
    enhanced_result = _create_search_result(
        results.get("callers", []),
        state_manager,
        "find_incoming_calls",
        max_results,
        total_count,
        empty_suggestions=empty_suggestions,
    )
    enhanced_result.next_steps = suggestions.for_find_incoming_calls(
        function_name, results, qualified_name=target_qualified_name
    )
    # Merge metadata into results dict
    output = results.copy() if isinstance(results, dict) else {"callers": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    if search_note:
        output["search_note"] = search_note
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_get_outgoing_calls(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = str(arguments["function_name"])
    class_name = str(arguments.get("class_name", ""))
    max_results = arguments.get("max_results", None)
    project_only = _parse_search_scope(arguments)
    # Run synchronous method in executor to avoid blocking event loop
    results = await loop.run_in_executor(
        None,
        lambda: analyzer.find_callees(function_name, class_name, project_only=project_only),
    )
    # Results is dict with "callees" list - use that for metadata logic
    callees_list = results.get("callees", []) if isinstance(results, dict) else []
    # 3-case empty-result logic (internal flags stripped before sending to LLM):
    #   not found               → default "check spelling" suggestions  (None)
    #   found, no callees       → no hints at all                        ([])
    #   found, ext. callees     → auto-expand to include external results
    function_found = results.pop("_function_found", False) if isinstance(results, dict) else False
    has_any_in_graph = (
        results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
    )
    target_qualified_name = (
        results.pop("_target_qualified_name", None) if isinstance(results, dict) else None
    )
    # Auto-expand: when project_only=True yields 0 results but external callees
    # exist, re-fetch with project_only=False so the LLM gets useful data without
    # needing to interpret a suggestion and issue a second tool call.
    search_note = None
    if project_only and not callees_list and function_found and has_any_in_graph:
        expanded = await loop.run_in_executor(
            None,
            lambda: analyzer.find_callees(function_name, class_name, project_only=False),
        )
        # Strip internal flags from expanded results
        expanded.pop("_function_found", None)
        expanded.pop("_has_any_in_graph", None)
        expanded.pop("_target_qualified_name", None)
        results = expanded
        callees_list = results.get("callees", [])
        ext_count = len(callees_list)
        search_note = (
            f"Project-only search yielded 0 results. "
            f"Auto-expanded to include external libraries "
            f"({ext_count} external callee{'s' if ext_count != 1 else ''} found)."
        )
    total_count = len(callees_list)
    # Apply truncation if max_results specified
    if max_results is not None and len(callees_list) > max_results:
        results["callees"] = callees_list[:max_results]
    empty_suggestions: Optional[List[str]] = None
    if not function_found:
        pass  # None → default "check spelling / broaden pattern"
    elif has_any_in_graph:
        empty_suggestions = []  # auto-expanded above; no hint needed
    else:
        empty_suggestions = []  # genuinely calls nothing → no hints
    # Wrap with appropriate metadata
    enhanced_result = _create_search_result(
        results.get("callees", []),
        state_manager,
        "get_outgoing_calls",
        max_results,
        total_count,
        empty_suggestions=empty_suggestions,
    )
    enhanced_result.next_steps = suggestions.for_get_outgoing_calls(
        function_name, results, qualified_name=target_qualified_name
    )
    # Merge metadata into results dict
    output = results.copy() if isinstance(results, dict) else {"callees": results}
    enhanced_dict = enhanced_result.to_dict()
    if "metadata" in enhanced_dict:
        output["metadata"] = enhanced_dict["metadata"]
    if search_note:
        output["search_note"] = search_note
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _handle_get_call_sites(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    function_name = arguments["function_name"]
    class_name = arguments.get("class_name", "")
    # Run synchronous method in executor to avoid blocking event loop
    call_sites = await loop.run_in_executor(
        None, lambda: analyzer.get_call_sites(function_name, class_name)
    )
    output_sites: Dict[str, Any] = {"call_sites": call_sites}
    if not call_sites:
        output_sites["metadata"] = {
            "suggestions": suggestions.for_get_call_sites_empty(function_name, class_name),
        }
    return [TextContent(type="text", text=json.dumps(output_sites, indent=2))]


async def _handle_get_call_path(arguments: Dict[str, Any]) -> List[TextContent]:
    assert analyzer is not None
    loop = asyncio.get_event_loop()
    from_function = arguments["from_function"]
    to_function = arguments["to_function"]
    max_depth = arguments.get("max_depth", 10)
    # Run synchronous method in executor to avoid blocking event loop
    with state_manager.tool_execution():
        paths = await loop.run_in_executor(
            None, lambda: analyzer.get_call_path(from_function, to_function, max_depth)
        )
    output_paths: Dict[str, Any] = {"paths": paths}
    if not paths:
        output_paths["metadata"] = {
            "suggestions": suggestions.for_get_call_path_empty(
                from_function, to_function, max_depth
            ),
        }
    return [TextContent(type="text", text=json.dumps(output_paths, indent=2))]


def _check_tool_readiness(name: str) -> Optional[List[TextContent]]:
    """
    Check if a tool is ready to be executed based on current analyzer state.
    Returns None if ready, or a List[TextContent] with an error message if not.
    """
    # Policy check and readiness for query tools
    query_tools = {
        "search_classes",
        "search_functions",
        "get_class_info",
        "get_type_alias_info",
        "search_symbols",
        "find_in_file",
        "get_class_hierarchy",
        "find_incoming_calls",
        "get_outgoing_calls",
        "get_call_path",
        "get_call_sites",
    }

    if name in query_tools:
        if analyzer is None:
            return [
                TextContent(
                    type="text",
                    text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.",
                )
            ]
        if not state_manager.is_ready_for_queries():
            return [
                TextContent(
                    type="text",
                    text="Error: Project is not ready for queries yet. Use 'sync_project' to start indexing or check status.",
                )
            ]

        allowed, policy_message = check_query_policy(name)
        if not allowed:
            return [TextContent(type="text", text=policy_message)]

    # Check for other tools (refresh_project, wait_for_indexing)
    if name in ("refresh_project", "wait_for_indexing") and analyzer is None:
        # For refresh_project, we'll try to resume inside the handler
        if name == "wait_for_indexing":
            return [
                TextContent(
                    type="text",
                    text="Error: Project directory not set. Please use 'set_project_directory' first.",
                )
            ]

    return None


async def _handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        # 1. Management tools (handle their own state checks)
        if name == "set_project_directory":
            return await _handle_set_project_directory(arguments)
        if name == "check_system_status":
            return await _handle_check_system_status(arguments)

        # 2. Check tool readiness
        error_response = _check_tool_readiness(name)
        if error_response:
            return error_response

        # 3. Route to specific handler
        handlers = {
            "search_classes": _handle_search_classes,
            "search_functions": _handle_search_functions,
            "get_class_info": _handle_get_class_info,
            "get_type_alias_info": _handle_get_type_alias_info,
            "search_symbols": _handle_search_symbols,
            "find_in_file": _handle_find_in_file,
            "refresh_project": _handle_refresh_project,
            "check_system_status": _handle_check_system_status,
            "wait_for_indexing": _handle_wait_for_indexing,
            "get_class_hierarchy": _handle_get_class_hierarchy,
            "find_incoming_calls": _handle_find_incoming_calls,
            "get_outgoing_calls": _handle_get_outgoing_calls,
            "get_call_sites": _handle_get_call_sites,
            "get_call_path": _handle_get_call_path,
        }

        if name in handlers:
            return await handlers[name](arguments)

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Internal error: {str(e)}\n\n"
                "This is a server-side issue, not a user error. "
                "Try restarting the MCP server.",
            )
        ]


ToolRegistry.register("_handle_tool_call", _handle_tool_call)


def _create_argument_parser():
    """Create and configure the argument parser for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="C++ Code Analysis MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Transport Options:
  stdio  - Standard I/O transport (default, for CLI integration)
  http   - HTTP/Streamable HTTP transport (RESTful API)
  sse    - Server-Sent Events transport (streaming updates)

Examples:
  %(prog)s                                    # Run with stdio transport
  %(prog)s --transport http --port 8000      # Run HTTP server on port 8000
  %(prog)s --transport sse --port 8080       # Run SSE server on port 8080
        """,
    )

    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )

    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address for HTTP/SSE server (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--port", type=int, default=8000, help="Port number for HTTP/SSE server (default: 8000)"
    )

    return parser


def _try_resume_session(saved_session):
    """Attempt to resume a saved session and return initialized components."""
    config_file = saved_session.get("config_file")

    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)

        config_root = config_data.get("project_root")
        if not config_root:
            raise ValueError(f"Config file {config_file} missing 'project_root'")

        config_dir = os.path.dirname(config_file)
        project_path = os.path.abspath(os.path.join(config_dir, config_root))

        diagnostics.info(f"Auto-resuming session via config: {config_file}")
        diagnostics.info(f"Resolved project root: {project_path}")

        state_manager.transition_to(AnalyzerState.INITIALIZING)
        new_analyzer = CppAnalyzer(project_path, config_file=config_file)
        new_background_indexer = BackgroundIndexer(new_analyzer, state_manager)

        cache_loaded = new_analyzer._load_cache()
        if cache_loaded:
            diagnostics.info(
                f"Session restored from cache: {len(new_analyzer.context.symbol_store.class_index)} classes, "
                f"{len(new_analyzer.context.symbol_store.function_index)} functions"
            )
            state_manager.transition_to(AnalyzerState.INDEXED)
            return new_analyzer, new_background_indexer, True

        diagnostics.info("No valid cache for saved session, will need to re-index")
        state_manager.transition_to(AnalyzerState.UNINITIALIZED)
        return new_analyzer, new_background_indexer, False

    except Exception as e:
        diagnostics.warning(f"Failed to resume session: {e}")
        state_manager.transition_to(AnalyzerState.UNINITIALIZED)
        return None, None, False


async def _cleanup_resources():
    """Cleanup resources on shutdown."""
    diagnostics.debug("Starting cleanup...")

    if background_indexer and background_indexer.is_indexing():
        diagnostics.debug("Canceling background indexing...")
        await background_indexer.cancel()

    loop = asyncio.get_event_loop()
    if hasattr(loop, "_default_executor") and loop._default_executor:
        diagnostics.debug("Shutting down default executor...")
        loop._default_executor.shutdown(wait=False, cancel_futures=True)

    diagnostics.debug("Cleanup complete")


async def _run_stdio_transport():
    """Run the server using stdio transport."""
    from mcp.server.stdio import stdio_server

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        await _cleanup_resources()


async def _run_http_transport(host, port, transport):
    """Run the server using HTTP or SSE transport."""
    try:
        from mcp_server.http_server import run_http_server
    except ImportError:
        from http_server import run_http_server

    try:
        await run_http_server(server, host, port, transport)
    finally:
        await _cleanup_resources()


async def main():
    """Main entry point for the MCP server."""
    global analyzer, analyzer_initialized, background_indexer

    disable_auto_resume = os.environ.get("MCP_DISABLE_SESSION_RESUME", "false").lower() == "true"
    saved_session = None if disable_auto_resume else session_manager.load_session()
    if saved_session:
        analyzer, background_indexer, analyzer_initialized = _try_resume_session(saved_session)

    parser = _create_argument_parser()
    args = parser.parse_args()

    if args.transport == "stdio":
        await _run_stdio_transport()
    elif args.transport in ("http", "sse"):
        await _run_http_transport(args.host, args.port, args.transport)
    else:
        diagnostics.fatal(f"Unknown transport: {args.transport}")
        sys.exit(1)


if __name__ == "__main__":
    # Register this module under its package name so that
    # `from mcp_server.cpp_mcp_server import X` reuses it instead of
    # reimporting and re-running module-level code (which would fail
    # because Config.set_library_file() cannot be called twice).
    sys.modules.setdefault("mcp_server.cpp_mcp_server", sys.modules[__name__])
    asyncio.run(main())
