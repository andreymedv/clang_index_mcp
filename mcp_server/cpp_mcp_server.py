#!/usr/bin/env python3
"""
C++ Code Analysis MCP Server

Provides tools for analyzing C++ codebases using libclang.
Focused on specific queries rather than bulk data dumps.
"""

import asyncio
import json
import sys
import os
from typing import Any, Dict, List, Optional

# Import diagnostics early
try:
    from mcp_server import diagnostics
except ImportError:
    from . import diagnostics

try:
    from clang.cindex import Config
except ImportError:
    diagnostics.fatal("clang package not found. Install with: pip install libclang")
    sys.exit(1)

from mcp.server import Server
from mcp.types import (
    Tool,
    TextContent,
)


def find_and_configure_libclang():
    """Find and configure libclang library using hybrid discovery approach.

    Search order (FIX FOR ISSUE #003):
    1. LIBCLANG_PATH environment variable (user override)
    2. Smart discovery (xcrun for Xcode CLT on macOS)
    3. System-installed libraries (prefer system over bundled)
    4. Bundled libraries (fallback)

    See: docs/MACOS_LIBCLANG_DISCOVERY.md
    """
    # Guard: if libclang is already loaded, no need to reconfigure.
    # This handles the double-import case where the module is first loaded as
    # __main__ (via python -m) and then reimported under its package name
    # (from mcp_server.cpp_mcp_server import ...).  The second import would
    # otherwise call Config.set_library_file() after Config.loaded is True,
    # raising "library file must be set before ...".
    if Config.loaded:
        return True

    import platform
    import glob
    import shutil
    import subprocess

    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one directory to find lib folder (since we're in mcp_server subfolder)
    parent_dir = os.path.dirname(script_dir)

    # ========================================================================
    # STEP 1: Check LIBCLANG_PATH environment variable (user override)
    # ========================================================================
    env_path = os.environ.get("LIBCLANG_PATH")
    if env_path and os.path.exists(env_path):
        diagnostics.info(f"Using libclang from LIBCLANG_PATH: {env_path}")
        Config.set_library_file(env_path)
        return True
    elif env_path:
        diagnostics.warning(f"LIBCLANG_PATH set but file not found: {env_path}")

    # ========================================================================
    # STEP 2: Smart discovery (macOS only for now)
    # ========================================================================
    if system == "Darwin":
        # Try xcrun to find Xcode Command Line Tools libclang
        try:
            result = subprocess.run(
                ["xcrun", "--find", "clang"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                clang_path = result.stdout.strip()
                # clang is at .../usr/bin/clang, libclang.dylib is at .../usr/lib/libclang.dylib
                clang_dir = os.path.dirname(os.path.dirname(clang_path))  # Go up 2 levels
                libclang_path = os.path.join(clang_dir, "lib", "libclang.dylib")
                if os.path.exists(libclang_path):
                    diagnostics.info(f"Found libclang via xcrun: {libclang_path}")
                    Config.set_library_file(libclang_path)
                    return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # xcrun not available or timed out

    # ========================================================================
    # STEP 3: Search system-installed libraries (platform-specific)
    # ========================================================================
    diagnostics.info("Searching for system-installed libclang...")

    if system == "Windows":
        system_paths = [
            # LLVM official installer paths
            r"C:\Program Files\LLVM\bin\libclang.dll",
            r"C:\Program Files (x86)\LLVM\bin\libclang.dll",
            # vcpkg paths
            r"C:\vcpkg\installed\x64-windows\bin\clang.dll",
            r"C:\vcpkg\installed\x86-windows\bin\clang.dll",
            # Conda paths
            r"C:\ProgramData\Anaconda3\Library\bin\libclang.dll",
        ]

        # Try to find in system PATH using llvm-config
        llvm_config = shutil.which("llvm-config")
        if llvm_config:
            try:
                result = subprocess.run(
                    [llvm_config, "--libdir"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    lib_dir = result.stdout.strip()
                    system_paths.insert(0, os.path.join(lib_dir, "libclang.dll"))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

    elif system == "Darwin":  # macOS
        system_paths = [
            # Xcode Command Line Tools (most common, FIX FOR ISSUE #003)
            "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",
            # Homebrew Apple Silicon (versioned, use glob)
            "/opt/homebrew/Cellar/llvm/*/lib/libclang.dylib",
            "/opt/homebrew/Cellar/llvm@*/*/lib/libclang.dylib",  # Versioned (llvm@19, llvm@20, etc.)
            "/opt/homebrew/lib/libclang.dylib",  # Symlink
            # Homebrew Intel
            "/usr/local/Cellar/llvm/*/lib/libclang.dylib",
            "/usr/local/Cellar/llvm@*/*/lib/libclang.dylib",  # Versioned (llvm@19, llvm@20, etc.)
            "/usr/local/lib/libclang.dylib",
            # MacPorts
            "/opt/local/libexec/llvm-*/lib/libclang.dylib",
            # Xcode.app (less common)
            "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib",
        ]

    else:  # Linux
        system_paths = [
            "/usr/lib/llvm-*/lib/libclang.so.1",
            "/usr/lib/x86_64-linux-gnu/libclang-*.so.1",
            "/usr/lib/libclang.so.1",
            "/usr/lib/libclang.so",
        ]

    # Try each system path (with glob support)
    for path_pattern in system_paths:
        if "*" in path_pattern:
            # Handle glob patterns - sort to prefer latest version
            matches = sorted(glob.glob(path_pattern), reverse=True)
            if matches:
                path = matches[0]  # Use latest/first match
            else:
                continue
        else:
            path = path_pattern

        if os.path.exists(path):
            diagnostics.info(f"Found system libclang at: {path}")
            Config.set_library_file(path)
            return True

    # ========================================================================
    # STEP 4: Try bundled libraries (fallback)
    # ========================================================================
    diagnostics.info("No system libclang found, trying bundled libraries...")

    bundled_paths = []
    if system == "Windows":
        bundled_paths = [
            os.path.join(parent_dir, "lib", "windows", "lib", "libclang.dll"),
            os.path.join(parent_dir, "lib", "windows", "lib", "clang.dll"),
        ]
    elif system == "Darwin":  # macOS
        bundled_paths = [
            os.path.join(parent_dir, "lib", "macos", "lib", "libclang.dylib"),
        ]
    else:  # Linux
        bundled_paths = [
            os.path.join(parent_dir, "lib", "linux", "lib", "libclang.so.1"),
            os.path.join(parent_dir, "lib", "linux", "lib", "libclang.so"),
        ]

    for path in bundled_paths:
        if os.path.exists(path):
            diagnostics.info(f"Using bundled libclang at: {path}")
            Config.set_library_file(path)
            return True

    return False


# Try to find and configure libclang
if not find_and_configure_libclang():
    diagnostics.fatal("Could not find libclang library.")
    diagnostics.fatal("Please install LLVM/Clang:")
    diagnostics.fatal("  Windows: Download from https://releases.llvm.org/")
    diagnostics.fatal("  macOS: brew install llvm")
    diagnostics.fatal("  Linux: sudo apt install libclang-dev")
    sys.exit(1)

# Import the Python analyzer and state manager
try:
    # Try package import first (when run as module)
    from mcp_server.cpp_analyzer import CppAnalyzer
    from mcp_server.state_manager import (
        AnalyzerStateManager,
        AnalyzerState,
        IndexingProgress,
        BackgroundIndexer,
        EnhancedQueryResult,
        QueryBehaviorPolicy,
    )
    from mcp_server.session_manager import SessionManager
    from mcp_server.tool_call_logger import ToolCallLogger
    from mcp_server import suggestions
except ImportError:
    # Fall back to direct import (when run as script)
    from cpp_analyzer import CppAnalyzer  # type: ignore[no-redef]
    from state_manager import (  # type: ignore[no-redef]
        AnalyzerStateManager,
        AnalyzerState,
        IndexingProgress,
        BackgroundIndexer,
        EnhancedQueryResult,
        QueryBehaviorPolicy,
    )
    from session_manager import SessionManager  # type: ignore[no-redef]
    from tool_call_logger import ToolCallLogger  # type: ignore[no-redef]
    import suggestions  # type: ignore[no-redef]

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
    from mcp_server.consolidated_tools import list_tools_b

    return list_tools_b()


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
    # If fully indexed, always allow
    if state_manager.is_fully_indexed():
        return (True, "")

    # If not indexing, allow
    if not state_manager.is_ready_for_queries():
        return (True, "")  # Let the normal flow handle uninitialized state

    # Get policy from analyzer config
    if analyzer is None:
        return (True, "")  # No analyzer yet, allow
    policy_str = analyzer.config.get_query_behavior_policy()

    try:
        policy = QueryBehaviorPolicy(policy_str)
    except ValueError:
        # Invalid policy, default to allow_partial
        diagnostics.warning(
            f"Invalid query_behavior_policy: {policy_str}, defaulting to allow_partial"
        )
        policy = QueryBehaviorPolicy.ALLOW_PARTIAL

    # Check policy
    if policy == QueryBehaviorPolicy.ALLOW_PARTIAL:
        # Allow query, results will include metadata warning
        return (True, "")

    elif policy == QueryBehaviorPolicy.BLOCK:
        # Wait for indexing to complete
        progress = state_manager.get_progress()
        if progress:
            completion = progress.completion_percentage
            indexed = progress.indexed_files
            total = progress.total_files
            message = (
                f"Query blocked: Indexing in progress ({completion:.1f}% complete, "
                f"{indexed:,}/{total:,} files). Waiting for indexing to complete...\n\n"
                f"Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial "
                f"to allow queries during indexing."
            )
        else:
            message = (
                "Query blocked: Indexing in progress. Waiting for completion...\n\n"
                "Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial."
            )

        # Wait for indexing with a reasonable timeout (30 seconds)
        completed = state_manager.wait_for_indexed(timeout=30.0)

        if completed:
            # Indexing completed while waiting
            return (True, "")
        else:
            # Timeout - still return block message
            return (
                False,
                message
                + "\n\nTimeout waiting for indexing (30s). Try again later or use 'sync_project'.",
            )

    elif policy == QueryBehaviorPolicy.REJECT:
        # Reject query with error
        progress = state_manager.get_progress()
        if progress:
            completion = progress.completion_percentage
            indexed = progress.indexed_files
            total = progress.total_files
            message = (
                f"ERROR: Query rejected - indexing in progress ({completion:.1f}% complete, "
                f"{indexed:,}/{total:,} files).\n\n"
                f"Queries are not allowed until indexing completes. Options:\n"
                f"1. Use 'sync_project' tool to wait for completion\n"
                f"2. Check progress with 'sync_project'\n"
                f"3. Set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial to allow partial results\n"
                f"4. Set CPP_ANALYZER_QUERY_BEHAVIOR=block to auto-wait for completion"
            )
        else:
            message = (
                "ERROR: Query rejected - indexing in progress.\n\n"
                "Use 'sync_project' or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial/block."
            )
        return (False, message)

    # Default: allow
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


def _try_log_tool_call(name: str, arguments: Dict[str, Any], result: List[TextContent]) -> None:
    """Log a tool call for telemetry. Never raises."""
    try:
        if tool_call_logger is None or not tool_call_logger.enabled:
            return
        result_text = result[0].text if result else ""
        # Extract result count from JSON
        result_count = 0
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, list):
                result_count = len(parsed)
            elif isinstance(parsed, dict):
                # EnhancedQueryResult wrapper: count results list
                results_list = parsed.get("results")
                if isinstance(results_list, list):
                    result_count = len(results_list)
                else:
                    # find_incoming_calls/get_outgoing_calls: count callers/callees list
                    for key in ("callers", "callees"):
                        sub = parsed.get(key)
                        if isinstance(sub, list):
                            result_count = len(sub)
                            break
        except (json.JSONDecodeError, TypeError):
            pass
        tool_call_logger.log_tool_call(
            name, arguments, result_count, result_text, analyzer=analyzer
        )
    except Exception:
        pass  # Telemetry must never break tool calls


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    from mcp_server.consolidated_tools import handle_tool_call_b

    result = await handle_tool_call_b(name, arguments)
    _try_log_tool_call(name, arguments, result)
    return result


async def _handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "set_project_directory":
            project_path = arguments["project_path"]
            config_file = arguments.get("config_file", None)
            auto_refresh = arguments.get("auto_refresh", True)

            if not isinstance(project_path, str) or not project_path.strip():
                return [
                    TextContent(
                        type="text", text="Error: 'project_path' must be a non-empty string"
                    )
                ]

            if project_path != project_path.strip():
                return [
                    TextContent(
                        type="text",
                        text="Error: 'project_path' may not include leading or trailing whitespace",
                    )
                ]

            project_path = project_path.strip()

            if not os.path.isabs(project_path):
                return [
                    TextContent(
                        type="text", text=f"Error: '{project_path}' is not an absolute path"
                    )
                ]

            if not os.path.isdir(project_path):
                return [
                    TextContent(
                        type="text", text=f"Error: Directory '{project_path}' does not exist"
                    )
                ]

            # Validate config_file if provided
            if config_file:
                if not isinstance(config_file, str) or not config_file.strip():
                    return [
                        TextContent(
                            type="text", text="Error: 'config_file' must be a non-empty string"
                        )
                    ]
                config_file = config_file.strip()
                if not os.path.isabs(config_file):
                    return [
                        TextContent(
                            type="text", text=f"Error: '{config_file}' is not an absolute path"
                        )
                    ]
                if not os.path.isfile(config_file):
                    return [
                        TextContent(
                            type="text", text=f"Error: Config file '{config_file}' does not exist"
                        )
                    ]

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
                            f"Cache loaded successfully: {len(analyzer.class_index)} classes, "
                            f"{len(analyzer.function_index)} functions indexed"
                        )

                        # CRITICAL FIX FOR ISSUE #15: Initialize progress with cache data
                        # Without this, get_indexing_status returns 0 files even though cache is loaded
                        from .state_manager import IndexingProgress
                        from datetime import datetime

                        # Create progress object from cached data
                        total_files = len(analyzer.file_index)
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
            session_manager.save_session(project_path, config_file)

            # Build response message
            config_msg = f" with config '{config_file}'" if config_file else ""
            auto_refresh_msg = (
                " Auto-refresh enabled." if auto_refresh else " Auto-refresh disabled."
            )

            # Return immediately - indexing continues in background
            return [
                TextContent(
                    type="text",
                    text=f"Set project directory to: {project_path}{config_msg}\n"
                    f"Indexing started in background.{auto_refresh_msg}\n"
                    f"Use 'sync_project' to check progress.\n"
                    f"Tools are available but will return partial results until indexing completes.",
                )
            ]

        # Check if analyzer is initialized for all other commands
        # Phase 3: Allow queries during indexing (partial results)
        # Tools can execute in INDEXING, INDEXED, or REFRESHING states
        if analyzer is None or not state_manager.is_ready_for_queries():
            return [
                TextContent(
                    type="text",
                    text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.",
                )
            ]

        # Define tools that are subject to query behavior policy
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
        }

        # Check query behavior policy for query tools (but not management tools)
        if name in query_tools:
            allowed, policy_message = check_query_policy(name)
            if not allowed:
                return [TextContent(type="text", text=policy_message)]

        # Get event loop for running synchronous operations in executor
        loop = asyncio.get_event_loop()

        if name == "search_classes":
            project_only = _parse_search_scope(arguments)
            pattern = arguments["symbol_name"]
            file_name = arguments.get("file_name", None)
            namespace = arguments.get("namespace", None)
            max_results = arguments.get("max_results", None)
            include_base_classes = arguments.get("include_base_classes", True)
            # Run synchronous method in executor to avoid blocking event loop
            raw_results = await loop.run_in_executor(
                None,
                lambda: analyzer.search_classes(
                    pattern, project_only, file_name, namespace, max_results, include_base_classes
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

        elif name == "search_functions":
            project_only = _parse_search_scope(arguments)
            class_name = arguments.get("class_name", None)
            file_name = arguments.get("file_name", None)
            namespace = arguments.get("namespace", None)
            pattern = arguments["symbol_name"]
            max_results = arguments.get("max_results", None)
            signature_pattern = arguments.get("signature_pattern", None)
            include_attributes = arguments.get("include_attributes", False)
            # Run synchronous method in executor to avoid blocking event loop
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

        elif name == "get_class_info":
            class_name = str(arguments["class_name"])
            # Run synchronous method in executor to avoid blocking event loop
            result = await loop.run_in_executor(
                None, lambda: analyzer.get_class_info(class_name)  # type: ignore[arg-type]
            )
            # Wrap with metadata (even if not found)
            enhanced_result = EnhancedQueryResult.create_from_state(
                result, state_manager, "get_class_info"
            )
            if result and "error" not in (result or {}):
                enhanced_result.next_steps = suggestions.for_get_class_info(result)
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "get_type_alias_info":
            type_name = arguments["type_name"]
            # Run synchronous method in executor to avoid blocking event loop
            result = await loop.run_in_executor(
                None, lambda: analyzer.get_type_alias_info(type_name)
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                result, state_manager, "get_type_alias_info"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "search_symbols":
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

        elif name == "find_in_file":
            file_path = arguments["file_path"]
            pattern = arguments["pattern"]
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.find_in_file(file_path, pattern)
            )
            # find_in_file returns {"results": [...], "matched_files": [...], ...}
            # Count the actual symbol results for metadata logic
            result_list = results.get("results", []) if isinstance(results, dict) else []
            # Wrap with appropriate metadata based on special conditions
            # Use _create_search_result with the result list for counting
            enhanced_result = _create_search_result(
                result_list, state_manager, "find_in_file", None, None
            )
            # But return the full results dict (with matched_files, suggestions, etc.)
            # Merge the metadata into the results dict
            output = results.copy() if isinstance(results, dict) else {"results": results}
            enhanced_dict = enhanced_result.to_dict()
            if "metadata" in enhanced_dict:
                output["metadata"] = enhanced_dict["metadata"]
            return [TextContent(type="text", text=json.dumps(output, indent=2))]

        elif name == "refresh_project":
            refresh_mode = arguments.get("refresh_mode", "incremental")

            # Issue #7: Warn if full mode is used (should be rare)
            if refresh_mode == "full":
                diagnostics.warning(
                    "refresh_mode='full' was requested - this will re-analyze ALL files and may "
                    "take 5-10 minutes on large projects. Incremental mode is 30-300x faster "
                    "and sufficient for 99% of cases."
                )

            # Start refresh in background (non-blocking, similar to set_project_directory)
            async def run_background_refresh():
                try:
                    # Transition to REFRESHING state
                    state_manager.transition_to(AnalyzerState.REFRESHING)

                    loop = asyncio.get_event_loop()

                    # Create progress callback that updates state_manager (same as BackgroundIndexer)
                    def progress_callback(progress: IndexingProgress):
                        """Callback to update progress in state manager during refresh"""
                        state_manager.update_progress(progress)

                    if refresh_mode == "incremental":
                        try:
                            from mcp_server.incremental_analyzer import IncrementalAnalyzer

                            diagnostics.info("Starting incremental refresh...")
                            incremental_analyzer = IncrementalAnalyzer(analyzer)
                            result = await loop.run_in_executor(
                                None,
                                lambda: incremental_analyzer.perform_incremental_analysis(
                                    progress_callback
                                ),
                            )

                            if result.changes.is_empty():
                                diagnostics.info(
                                    "Incremental refresh complete: no changes detected"
                                )
                            else:
                                diagnostics.info(
                                    f"Incremental refresh complete: re-analyzed {result.files_analyzed} files, "
                                    f"removed {result.files_removed} files in {result.elapsed_seconds:.2f}s"
                                )

                            state_manager.transition_to(AnalyzerState.INDEXED)
                            return

                        except Exception as e:
                            diagnostics.error(f"Incremental analysis failed: {e}")
                            diagnostics.info("Falling back to full refresh...")
                            # Fallback to full refresh
                            modified_count = await loop.run_in_executor(
                                None, lambda: analyzer.refresh_if_needed(progress_callback)
                            )
                            diagnostics.info(
                                f"Fallback full refresh complete: re-analyzed {modified_count} files"
                            )
                            state_manager.transition_to(AnalyzerState.INDEXED)
                            return

                    else:
                        # Full refresh
                        diagnostics.info("Starting full refresh...")
                        modified_count = await loop.run_in_executor(
                            None, lambda: analyzer.refresh_if_needed(progress_callback)
                        )
                        diagnostics.info(
                            f"Full refresh complete: re-analyzed {modified_count} files"
                        )
                        state_manager.transition_to(AnalyzerState.INDEXED)
                        return

                except Exception as e:
                    diagnostics.error(f"Background refresh failed: {e}")
                    state_manager.transition_to(AnalyzerState.ERROR)
                    pass

            # Create background task (non-blocking)
            asyncio.create_task(run_background_refresh())

            # Return immediately - refresh continues in background
            return [
                TextContent(
                    type="text",
                    text=f"Refresh started in background (mode: {refresh_mode}).\n"
                    f"Use 'sync_project' to check progress.\n"
                    f"Tools will continue to work and return results based on current cache state.",
                )
            ]

        elif name == "check_system_status":
            # Combined server diagnostics and indexing status
            status_dict = state_manager.get_status_dict()

            ccm = analyzer.compile_commands_manager
            total_classes = sum(len(infos) for infos in analyzer.class_index.values())
            total_functions = sum(len(infos) for infos in analyzer.function_index.values())

            status_dict.update(
                {
                    "analyzer_type": "python_enhanced",
                    "call_graph_enabled": True,
                    "compile_commands_enabled": ccm.enabled if ccm else False,
                    "compile_commands_path": ccm.compile_commands_path if ccm else None,
                    "parsed_files": len(analyzer.file_index),
                    "indexed_classes": total_classes,
                    "indexed_functions": total_functions,
                }
            )
            return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]

        elif name == "wait_for_indexing":
            # Internal handler - used by sync_project and tests
            timeout = arguments.get("timeout", 60.0)

            if state_manager.is_fully_indexed():
                return [TextContent(type="text", text="Indexing already complete.")]

            completed = await loop.run_in_executor(
                None, lambda: state_manager.wait_for_indexed(timeout)
            )

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

        elif name == "get_class_hierarchy":
            class_name = str(arguments["class_name"])
            max_nodes = arguments.get("max_nodes", 200)
            max_depth = arguments.get("max_depth", None)
            # Run synchronous method in executor to avoid blocking event loop
            hierarchy = await loop.run_in_executor(
                None,
                lambda: analyzer.get_class_hierarchy(  # type: ignore[arg-type]
                    class_name, max_nodes=max_nodes, max_depth=max_depth  # type: ignore[arg-type]
                ),
            )
            if hierarchy:
                return [TextContent(type="text", text=json.dumps(hierarchy, indent=2))]
            else:
                return [TextContent(type="text", text=f"Class '{class_name}' not found")]

        elif name == "find_incoming_calls":
            function_name = str(arguments["function_name"])
            class_name = str(arguments.get("class_name", ""))
            max_results = arguments.get("max_results", None)
            project_only = _parse_search_scope(arguments)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None,
                lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=project_only),  # type: ignore[arg-type]
            )
            # Results is dict with "callers" list - use that for metadata logic
            callers_list = results.get("callers", []) if isinstance(results, dict) else []
            # 3-case empty-result logic (internal flags stripped before sending to LLM):
            #   not found            → default "check spelling" suggestions  (None)
            #   found, no callers    → no hints at all                        ([])
            #   found, ext. callers  → auto-expand to include external results
            function_found = (
                results.pop("_function_found", False) if isinstance(results, dict) else False
            )
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
                    lambda: analyzer.find_incoming_calls(function_name, class_name, project_only=False),  # type: ignore[arg-type]
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

        elif name == "get_outgoing_calls":
            function_name = str(arguments["function_name"])
            class_name = str(arguments.get("class_name", ""))
            max_results = arguments.get("max_results", None)
            project_only = _parse_search_scope(arguments)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None,
                lambda: analyzer.find_callees(function_name, class_name, project_only=project_only),  # type: ignore[arg-type]
            )
            # Results is dict with "callees" list - use that for metadata logic
            callees_list = results.get("callees", []) if isinstance(results, dict) else []
            # 3-case empty-result logic (internal flags stripped before sending to LLM):
            #   not found               → default "check spelling" suggestions  (None)
            #   found, no callees       → no hints at all                        ([])
            #   found, ext. callees     → auto-expand to include external results
            function_found = (
                results.pop("_function_found", False) if isinstance(results, dict) else False
            )
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
                    lambda: analyzer.find_callees(function_name, class_name, project_only=False),  # type: ignore[arg-type]
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
            empty_suggestions = None
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

        elif name == "get_call_sites":
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

        elif name == "get_call_path":
            from_function = arguments["from_function"]
            to_function = arguments["to_function"]
            max_depth = arguments.get("max_depth", 10)
            # Run synchronous method in executor to avoid blocking event loop
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

        else:
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


async def main():
    """Main entry point for the MCP server."""
    import argparse

    # Auto-resume last session if available (unless disabled for tests)
    global analyzer, analyzer_initialized, background_indexer
    disable_auto_resume = os.environ.get("MCP_DISABLE_SESSION_RESUME", "false").lower() == "true"
    saved_session = None if disable_auto_resume else session_manager.load_session()
    if saved_session:
        project_path = saved_session["project_path"]
        config_file = saved_session.get("config_file")

        diagnostics.info(f"Auto-resuming last session: {project_path}")

        try:
            # Initialize analyzer with saved project
            state_manager.transition_to(AnalyzerState.INITIALIZING)
            analyzer = CppAnalyzer(project_path, config_file=config_file)
            background_indexer = BackgroundIndexer(analyzer, state_manager)

            # Try to load cache immediately (fast path)
            cache_loaded = analyzer._load_cache()
            if cache_loaded:
                diagnostics.info(
                    f"Session restored from cache: {len(analyzer.class_index)} classes, "
                    f"{len(analyzer.function_index)} functions"
                )
                state_manager.transition_to(AnalyzerState.INDEXED)
                analyzer_initialized = True
            else:
                diagnostics.info("No valid cache for saved session, will need to re-index")
                state_manager.transition_to(AnalyzerState.UNINITIALIZED)

        except Exception as e:
            diagnostics.warning(f"Failed to resume session: {e}")
            analyzer = None
            analyzer_initialized = False
            state_manager.transition_to(AnalyzerState.UNINITIALIZED)

    # Parse command-line arguments
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

    args = parser.parse_args()

    async def cleanup():
        """Cleanup resources on shutdown"""
        diagnostics.debug("Starting cleanup...")

        # Cancel background indexing if running
        if background_indexer and background_indexer.is_indexing():
            diagnostics.debug("Canceling background indexing...")
            await background_indexer.cancel()

        # Shutdown default executor to allow clean exit
        # This is necessary because BackgroundIndexer uses run_in_executor(None, ...)
        # which creates a default ThreadPoolExecutor that needs explicit shutdown
        loop = asyncio.get_event_loop()
        if hasattr(loop, "_default_executor") and loop._default_executor:
            diagnostics.debug("Shutting down default executor...")
            loop._default_executor.shutdown(wait=False, cancel_futures=True)

        diagnostics.debug("Cleanup complete")

    # Run with selected transport
    if args.transport == "stdio":
        # Import here to avoid issues if mcp package not installed
        from mcp.server.stdio import stdio_server

        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
        finally:
            await cleanup()

    elif args.transport in ("http", "sse"):
        # Import HTTP server module
        try:
            from mcp_server.http_server import run_http_server
        except ImportError:
            from http_server import run_http_server

        # Run HTTP/SSE server with cleanup on shutdown
        try:
            await run_http_server(server, args.host, args.port, args.transport)
        finally:
            await cleanup()

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
