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
from typing import Any, Dict, List

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

    See: docs/issues/003-macos-libclang-discovery.md
    """
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

# Import the Python analyzer and compile commands manager
try:
    # Try package import first (when run as module)
    from mcp_server.cpp_analyzer import CppAnalyzer
    from mcp_server.compile_commands_manager import CompileCommandsManager
    from mcp_server.state_manager import (
        AnalyzerStateManager,
        AnalyzerState,
        IndexingProgress,
        BackgroundIndexer,
        EnhancedQueryResult,
        QueryBehaviorPolicy,
    )
except ImportError:
    # Fall back to direct import (when run as script)
    from cpp_analyzer import CppAnalyzer
    from compile_commands_manager import CompileCommandsManager
    from state_manager import (
        AnalyzerStateManager,
        AnalyzerState,
        IndexingProgress,
        BackgroundIndexer,
        EnhancedQueryResult,
        QueryBehaviorPolicy,
    )

# Initialize analyzer
PROJECT_ROOT = os.environ.get("CPP_PROJECT_ROOT", None)

# Initialize analyzer as None - will be set when project directory is specified
analyzer = None

# State management for analyzer lifecycle
state_manager = AnalyzerStateManager()

# Background indexer for async indexing
background_indexer = None

# Session manager for persistence across restarts
from .session_manager import SessionManager

session_manager = SessionManager()

# Track if analyzer has been initialized with a valid project
# TODO Phase 3: This boolean will be replaced by state_manager checks in async mode
analyzer_initialized = False

# MCP Server
server = Server("cpp-analyzer")


@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_classes",
            description="Search for C++ class and struct definitions by name pattern. **Use this when**: user wants to find/locate a class, find where it's defined, or search by partial name. **Don't use** get_class_info (which needs exact name and returns full structure, not location).\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns list with: name, kind (CLASS_DECL/STRUCT_DECL), file, line, is_project, base_classes, start_line, end_line (complete line range), header_file (if declared in header), header_start_line, header_end_line, brief (first line of documentation or null), doc_comment (full documentation comment up to 4000 chars or null). Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Supports regex patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Class/struct name to search for. **Empty string matches all** - useful with file_name filter to get all classes in a file. **Default behavior: exact match** (case-insensitive). For example, 'View' returns only the class named 'View', not 'ViewManager' or 'ListView'. **For pattern matching**, use regex metacharacters: '.*View.*' matches all classes containing 'View', 'View.*' matches classes starting with 'View', etc. Pattern examples: 'My.*Class' matches MyBaseClass, MyDerivedClass.",
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). **Keep true for most use cases** - user questions typically refer to their project code. Only set to false if user explicitly asks about standard library, third-party dependencies, or 'all code including libraries'.",
                        "default": True,
                    },
                    "file_name": {
                        "type": "string",
                        "description": "Optional: Filter results to only symbols defined in files matching this name. Works with any file type (.h, .cpp, .cc, etc.). Accepts multiple formats: absolute path, relative to project root, or filename only (e.g., 'network.h', 'utils.cpp'). Uses 'endswith' matching, so partial paths work if they uniquely identify the file.",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="search_functions",
            description="Search for C++ functions and methods by name pattern. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns list with: name, kind (FUNCTION_DECL/CXX_METHOD/CONSTRUCTOR/DESTRUCTOR), file, line, signature, parent_class, is_project, start_line, end_line (complete line range), header_file (if declared in header), header_start_line, header_end_line, brief (first line of documentation or null), doc_comment (full documentation comment up to 4000 chars or null). Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Searches both standalone functions and class methods. Supports regex patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Function/method name to search for. **Empty string matches all** - useful with file_name filter to get all functions in a file. **Default behavior: exact match** (case-insensitive). For example, 'getValue' returns only functions named 'getValue', not 'getValueFromCache'. **For pattern matching**, use regex metacharacters: 'get.*' matches all functions starting with 'get', '.*Value.*' matches all functions containing 'Value', etc.",
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). **Keep true for most use cases** - user questions typically refer to their project code. Only set to false if user explicitly asks about standard library, third-party dependencies, or 'all code including libraries'.",
                        "default": True,
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Only populate if user specifically mentions a class (e.g., 'find save method in Database class'). Limits search to only methods belonging to this specific class. **Leave empty** (which is typical) to search all functions and methods across the codebase.",
                    },
                    "file_name": {
                        "type": "string",
                        "description": "Optional: Filter results to only symbols defined in files matching this name. Works with any file type (.h, .cpp, .cc, etc.). Accepts multiple formats: absolute path, relative to project root, or filename only (e.g., 'network.h', 'utils.cpp'). Uses 'endswith' matching, so partial paths work if they uniquely identify the file.",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="get_class_info",
            description="Get comprehensive information about a specific class: methods with signatures (all access levels), base classes, file location, line ranges, documentation. **Note**: Member variables/fields (members) are not currently indexed and will be an empty list. **Use this when**: user wants to see class methods or API. **Requires exact class name** - if you don't know exact name, use search_classes first.\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns: name, kind, file, line, base_classes, methods (sorted by line, each with line ranges, brief, and doc_comment), members (currently empty), is_project, start_line, end_line (class body range), header_file (if declared in header), header_start_line, header_end_line, brief (class documentation first line or null), doc_comment (class full documentation up to 4000 chars or null). Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Returns plain text error 'Class <name> not found' if not found. Returns first match if multiple classes have same name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Exact name of the class to analyze (case-sensitive, must match exactly)",
                    }
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="get_function_signature",
            description="Get formatted signature strings for function(s) with the exact name specified. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns a list of signature strings showing the function name with parameter types and class scope qualifier (e.g., 'ClassName::functionName(int x, std::string y)' or 'functionName(double z)'). Note: Does NOT include return types in the output, only function name, parameters, and class scope if applicable. If multiple overloads exist, returns all of them. Use this to quickly see function parameter types. Returns formatted strings only, not structured metadata - use search_functions if you need file locations, line numbers, or complete metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Exact name of the function/method to look up (case-sensitive). Will return signature strings for all overloads if multiple exist.",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If specified, only returns method signatures from this specific class, ignoring standalone functions and methods from other classes. Leave empty to get signatures for all matching functions across the codebase.",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="search_symbols",
            description="Unified search across multiple C++ symbol types (classes, structs, functions, methods) using a single pattern. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns a dictionary with two keys: 'classes' (array of class/struct results) and 'functions' (array of function/method results). Each result includes name, kind, file location, line number, complete line ranges (start_line, end_line), header location (header_file, header_start_line, header_end_line), brief (first line of documentation or null), doc_comment (full documentation comment up to 4000 chars or null), and other metadata. Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. This is a convenient alternative to calling search_classes and search_functions separately. Use symbol_types to filter which categories are populated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Symbol name pattern to search for. **Empty string matches all symbols** of the specified types. Supports exact matching (default) and regex patterns. Searches across all symbol types unless filtered by symbol_types parameter.",
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies. Set to false to include third-party libraries and system headers.",
                        "default": True,
                    },
                    "symbol_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["class", "struct", "function", "method"],
                        },
                        "description": "Filter results to specific symbol types. Options: 'class' (class definitions), 'struct' (struct definitions), 'function' (standalone functions), 'method' (class member functions). If omitted, both 'classes' and 'functions' arrays will be populated.",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="find_in_file",
            description="Search for C++ symbols (classes, functions, methods) within a specific source file. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns only symbols defined in that file, with locations (file, line, column, start_line, end_line, header_file, header_start_line, header_end_line) and basic information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file. Accepts multiple formats: absolute path (/full/path/to/file.cpp), relative to project root (src/main.cpp), or even partial path (main.cpp). The matcher uses both exact absolute path resolution and 'endswith' matching, so shorter paths work if they uniquely identify the file.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Symbol name pattern to search for within the file. **Empty string matches all symbols** in the file. Supports exact matching (default) and regex patterns.",
                    },
                },
                "required": ["file_path", "pattern"],
            },
        ),
        Tool(
            name="set_project_directory",
            description="**REQUIRED FIRST STEP**: Initialize the analyzer with your C++ project directory. Must be called before any other tools. Indexes all C++ source/header files (.cpp, .h, .hpp, etc.) in the directory and subdirectories, parsing with libclang to build searchable database of classes, functions, and relationships.\n\nSupports incremental analysis: If a valid cache exists and auto_refresh=true (default), will automatically detect and re-analyze only changed files. Different config_file paths create separate cache directories, enabling multi-configuration workflows.\n\nWARNING: Indexing large projects takes time. Can be called multiple times to switch projects (reinitializes each time). Returns count of indexed files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the root directory of your C++ project. Must be a valid, existing directory. All subsequent analysis operations will be performed on this project.",
                    },
                    "config_file": {
                        "type": "string",
                        "description": "Optional: Path to configuration file (.cpp-analyzer-config.json). When provided, creates a unique cache for this project+config combination, enabling multiple configurations for the same source directory.",
                    },
                    "auto_refresh": {
                        "type": "boolean",
                        "description": "When true (default), automatically performs incremental analysis on cache load to detect and re-analyze changed files. Set to false to skip automatic refresh and use cached data as-is.",
                        "default": True,
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="refresh_project",
            description="Manually refresh the project index to detect and re-parse files that have been modified, added, or deleted since the last index. The analyzer does NOT automatically detect file changes - you must call this tool whenever source files are modified (whether by you, external editor, git checkout, build system, or any other means) to ensure the index reflects the current state of the codebase.\n\nSupports two modes:\n- Incremental (default): Analyzes only changed files using dependency tracking\n- Full: Re-analyzes all files (use force_full=true)\n\n**Non-blocking operation:** Refresh runs in the background. This tool returns immediately while the refresh continues. Use 'get_indexing_status' to monitor progress. Tools remain available during refresh and will return results based on the current cache state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "incremental": {
                        "type": "boolean",
                        "description": "When true (default), performs incremental analysis by detecting changes and re-analyzing only affected files. When false, performs full re-analysis of all files.",
                        "default": True,
                    },
                    "force_full": {
                        "type": "boolean",
                        "description": "When true, forces full re-analysis of all files regardless of incremental setting. Use after major configuration changes or to rebuild index from scratch.",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_server_status",
            description="Get diagnostic information about the MCP server state and index statistics. Returns JSON with: analyzer type, enabled features (call_graph, usr_tracking, compile_commands), file counts (parsed, indexed classes/functions). Use to verify server is working, check if indexing is complete, or debug configuration issues.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_indexing_status",
            description="Get real-time status of project indexing. Returns state (uninitialized/initializing/indexing/indexed/refreshing/error), progress information (files indexed/total, completion percentage, current file, ETA), and whether tools will return complete or partial results. Use this to check if indexing is complete before running queries on large projects, or to monitor indexing progress.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="wait_for_indexing",
            description="Block until indexing completes or timeout is reached. Use this when you need complete results and want to wait for indexing to finish. Returns success when indexing completes, or timeout error if it takes too long. Useful after set_project_directory on large projects to ensure queries return complete data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "number",
                        "description": "Maximum time to wait in seconds (default: 60.0). Set higher for large projects.",
                        "default": 60.0,
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="get_class_hierarchy",
            description="Get the complete bidirectional inheritance hierarchy for a C++ class. **Use this when** user asks for: 'all subclasses/descendants of X', 'all classes inheriting from X', 'complete inheritance tree', or wants both ancestors AND descendants. **Do NOT use** get_derived_classes which only returns immediate children.\n\nReturns: name (class name), base_hierarchy (all ancestors recursively to root), derived_hierarchy (all descendants recursively to leaves), class_info (detailed info), direct base_classes and derived_classes lists. If not found, returns {'error': 'Class <name> not found'}.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to analyze. The result will show this class's complete inheritance hierarchy in both directions (ancestors and descendants).",
                    }
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="get_derived_classes",
            description="[WARNING] IMPORTANT: This returns ONLY DIRECT children (one level), NOT all descendants. If user asks for 'all classes that inherit from X' or 'all subclasses', use get_class_hierarchy instead for complete transitive closure.\n\nGet a flat list of classes that DIRECTLY inherit from a specified base class (immediate children only). Returns classes where the specified class appears in their direct base_classes list. Example: if C→B→A (C inherits B, B inherits A), calling this on 'A' returns only [B], not C. Returns list with: name, kind, file, line, column, is_project, base_classes, start_line, end_line (complete line range), header_file, header_start_line, header_end_line. Supports filtering by project_only.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the base class for which to find direct derived classes (immediate children only, one level down in inheritance tree)",
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only includes derived classes from project source files, excluding those from external dependencies and libraries. Set to false to include all derived classes from all indexed files.",
                        "default": True,
                    },
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="find_callers",
            description="Find all functions/methods that call (invoke) a specific target function. Performs call graph analysis with LINE-LEVEL PRECISION (Phase 3).\n\nReturns:\n- callers: List of caller function info (name, kind, file, line where function is defined, signature, parent_class, is_project, start_line, end_line of function body)\n- call_sites: Array of EXACT call locations with file, line, column where each call occurs, caller name/signature (NEW in Phase 3)\n- total_call_sites: Count of all call sites found\n\nThe call_sites array provides LINE-LEVEL PRECISION - you get the exact file:line:column where each call occurs, eliminating the need to search within function bodies. Each call site includes the calling function's name and signature for context.\n\nUse this for: impact analysis (which functions depend on this), refactoring planning (what breaks if I change this), call graph visualization, or finding exact usage locations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the target function/method to find callers for (the function being called)",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the target is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": "",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="find_callees",
            description="Find all functions/methods that are called (invoked) by a specific source function. This is the inverse of find_callers - while find_callers shows what calls a function (backwards), find_callees shows what a function calls (forwards). Performs call graph analysis to identify every function called within the body of the specified function. Returns list with: name, kind, file, line, column, signature, parent_class, is_project, start_line, end_line (callee function body range), header_file, header_start_line, header_end_line.\n\nIMPORTANT - Line Number Limitation: The 'line' and 'column' fields indicate where each CALLEE FUNCTION IS DEFINED, not the call site. To find exact call site line numbers: read the source function's file and search within its body for these callee invocations.\n\nUse this for: understanding dependencies (what does this function depend on), analyzing code flow, or mapping execution paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the source function/method to analyze (the function doing the calling)",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the source is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": "",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="get_call_sites",
            description="Get all function calls made FROM a specific source function with LINE-LEVEL PRECISION (Phase 3). Returns exact file:line:column for each function call within the source function's body.\n\nReturns array of call sites, each with:\n- target: Name of called function\n- target_signature: Full signature of called function\n- file: Source file containing the call\n- line: Exact line number of call\n- column: Column position of call\n- target_file: File where called function is defined\n\nThis tool shows WHAT a function calls (forward analysis) with precise locations. Inverse of find_callers which shows what calls a function (backward analysis).\n\nUse this for: understanding function dependencies with exact call locations, analyzing code flow, finding specific call statements, or refactoring call sites.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the source function to analyze (the function doing the calling)",
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the source is a class method, specify the class name to disambiguate. Leave empty for standalone functions.",
                        "default": "",
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="get_files_containing_symbol",
            description="Get list of all files that contain references to or define a symbol. **Phase 1: LLM Integration** - Enables targeted code search by narrowing down which files to examine. Returns the file paths where the symbol is defined and referenced, enabling efficient integration with filesystem and ripgrep MCP tools.\n\n**Use this when**: You need to find all files that use a class or function, want to perform targeted grep searches, or need to understand symbol usage scope across the project.\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns: symbol name, kind, list of file paths (sorted), and total reference count. File list includes definition file, header file (if separate), and files that reference/call the symbol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol (class, function, method) to find references for. Must be exact name (case-sensitive).",
                    },
                    "symbol_kind": {
                        "type": "string",
                        "enum": ["class", "function", "method"],
                        "description": "Optional: Type of symbol to disambiguate if multiple symbols share the same name. Leave empty to search all symbol types.",
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only includes project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). Set to false to include all files including dependencies.",
                        "default": True,
                    },
                },
                "required": ["symbol_name"],
            },
        ),
        Tool(
            name="get_call_path",
            description="Find execution paths through the call graph from a starting function to a target function using BFS. A call path is a sequence of function calls connecting two functions (e.g., main -> init -> setup -> loadConfig). Returns ALL possible paths up to max_depth, showing intermediate function chains.\n\nWARNING: In highly connected codebases, can return hundreds/thousands of paths. Use max_depth conservatively. Returns empty array if no path exists within max_depth.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_function": {
                        "type": "string",
                        "description": "Name of the starting/source function (where the execution path begins)",
                    },
                    "to_function": {
                        "type": "string",
                        "description": "Name of the target/destination function (where the execution path should end)",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum number of intermediate function calls to search through (default: 10). Higher values find longer paths but exponentially increase computation time and result count in highly connected graphs. Keep this low (5-15) for large codebases.",
                        "default": 10,
                    },
                },
                "required": ["from_function", "to_function"],
            },
        ),
    ]


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
                f"Use 'wait_for_indexing' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial "
                f"to allow queries during indexing."
            )
        else:
            message = (
                "Query blocked: Indexing in progress. Waiting for completion...\n\n"
                "Use 'wait_for_indexing' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial."
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
                + "\n\nTimeout waiting for indexing (30s). Try again later or use 'get_indexing_status'.",
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
                f"1. Use 'wait_for_indexing' tool to wait for completion\n"
                f"2. Check progress with 'get_indexing_status'\n"
                f"3. Set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial to allow partial results\n"
                f"4. Set CPP_ANALYZER_QUERY_BEHAVIOR=block to auto-wait for completion"
            )
        else:
            message = (
                "ERROR: Query rejected - indexing in progress.\n\n"
                "Use 'wait_for_indexing' or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial/block."
            )
        return (False, message)

    # Default: allow
    return (True, "")


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
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
            global analyzer, analyzer_initialized, state_manager, background_indexer

            # Transition to INDEXING state (allows immediate queries with partial results)
            # This prevents race condition where get_indexing_status fails if called immediately
            state_manager.transition_to(AnalyzerState.INDEXING)
            analyzer = CppAnalyzer(project_path, config_file=config_file)
            background_indexer = BackgroundIndexer(analyzer, state_manager)

            # Start indexing in background (truly asynchronous, non-blocking)
            # The task will run independently while the MCP server continues to handle requests
            async def run_background_indexing():
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
                            estimated_completion=None  # Already complete
                        )
                        state_manager.update_progress(progress)

                        state_manager.transition_to(AnalyzerState.INDEXED)

                        # Mark as initialized immediately
                        global analyzer_initialized
                        analyzer_initialized = True

                        diagnostics.info(
                            "Server ready (loaded from cache) - use 'refresh_project' to detect file changes"
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
                    f"Use 'get_indexing_status' to check progress.\n"
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
            "get_function_signature",
            "search_symbols",
            "find_in_file",
            "get_class_hierarchy",
            "get_derived_classes",
            "find_callers",
            "find_callees",
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
            project_only = arguments.get("project_only", True)
            pattern = arguments["pattern"]
            file_name = arguments.get("file_name", None)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.search_classes(pattern, project_only, file_name)
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                results, state_manager, "search_classes"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "search_functions":
            project_only = arguments.get("project_only", True)
            class_name = arguments.get("class_name", None)
            file_name = arguments.get("file_name", None)
            pattern = arguments["pattern"]
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None,
                lambda: analyzer.search_functions(pattern, project_only, class_name, file_name),
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                results, state_manager, "search_functions"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "get_class_info":
            class_name = arguments["class_name"]
            # Run synchronous method in executor to avoid blocking event loop
            result = await loop.run_in_executor(None, lambda: analyzer.get_class_info(class_name))
            # Wrap with metadata (even if not found)
            enhanced_result = EnhancedQueryResult.create_from_state(
                result, state_manager, "get_class_info"
            )
            if result:
                return [
                    TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))
                ]
            else:
                # Include metadata even for "not found" case
                return [
                    TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))
                ]

        elif name == "get_function_signature":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", None)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.get_function_signature(function_name, class_name)
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                results, state_manager, "get_function_signature"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "search_symbols":
            pattern = arguments["pattern"]
            project_only = arguments.get("project_only", True)
            symbol_types = arguments.get("symbol_types", None)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.search_symbols(pattern, project_only, symbol_types)
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                results, state_manager, "search_symbols"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "find_in_file":
            file_path = arguments["file_path"]
            pattern = arguments["pattern"]
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.find_in_file(file_path, pattern)
            )
            # Wrap with metadata
            enhanced_result = EnhancedQueryResult.create_from_state(
                results, state_manager, "find_in_file"
            )
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "refresh_project":
            incremental = arguments.get("incremental", True)
            force_full = arguments.get("force_full", False)

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

                    # Force full re-analysis overrides incremental setting
                    if force_full:
                        diagnostics.info("Starting full refresh (forced)...")
                        modified_count = await loop.run_in_executor(
                            None, lambda: analyzer.refresh_if_needed(progress_callback)
                        )
                        diagnostics.info(
                            f"Full refresh complete: re-analyzed {modified_count} files"
                        )
                        state_manager.transition_to(AnalyzerState.INDEXED)
                        return

                    # Incremental analysis using IncrementalAnalyzer
                    if incremental:
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

                    # Non-incremental (full) refresh
                    else:
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

            # Build response message
            refresh_mode = (
                "full (forced)" if force_full else ("incremental" if incremental else "full")
            )

            # Return immediately - refresh continues in background
            return [
                TextContent(
                    type="text",
                    text=f"Refresh started in background (mode: {refresh_mode}).\n"
                    f"Use 'get_indexing_status' to check progress.\n"
                    f"Tools will continue to work and return results based on current cache state.",
                )
            ]

        elif name == "get_server_status":
            # Determine analyzer type
            analyzer_type = "python_enhanced"

            status = {
                "analyzer_type": analyzer_type,
                "call_graph_enabled": True,
                "usr_tracking_enabled": True,
                "compile_commands_enabled": analyzer.compile_commands_manager.enabled,
                "compile_commands_path": analyzer.compile_commands_manager.compile_commands_path,
                "compile_commands_cache_enabled": analyzer.compile_commands_manager.cache_enabled,
            }

            # Add analyzer stats from enhanced Python analyzer
            # Count total symbols, not just unique names
            total_classes = sum(len(infos) for infos in analyzer.class_index.values())
            total_functions = sum(len(infos) for infos in analyzer.function_index.values())

            status.update(
                {
                    "parsed_files": len(analyzer.file_index),
                    "indexed_classes": total_classes,
                    "indexed_functions": total_functions,
                    "project_files": len(analyzer.file_index),
                }
            )
            return [TextContent(type="text", text=json.dumps(status, indent=2))]

        elif name == "get_indexing_status":
            # Get current state and progress from state manager
            status_dict = state_manager.get_status_dict()
            return [TextContent(type="text", text=json.dumps(status_dict, indent=2))]

        elif name == "wait_for_indexing":
            # Wait for indexing to complete with timeout
            timeout = arguments.get("timeout", 60.0)

            if state_manager.is_fully_indexed():
                return [TextContent(type="text", text="Indexing already complete.")]

            # Wait for indexed event asynchronously to avoid blocking event loop
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
                        text=f"Timeout waiting for indexing (waited {timeout}s). Use 'get_indexing_status' to check progress.",
                    )
                ]

        elif name == "get_class_hierarchy":
            class_name = arguments["class_name"]
            # Run synchronous method in executor to avoid blocking event loop
            hierarchy = await loop.run_in_executor(
                None, lambda: analyzer.get_class_hierarchy(class_name)
            )
            if hierarchy:
                return [TextContent(type="text", text=json.dumps(hierarchy, indent=2))]
            else:
                return [TextContent(type="text", text=f"Class '{class_name}' not found")]

        elif name == "get_derived_classes":
            class_name = arguments["class_name"]
            project_only = arguments.get("project_only", True)
            # Run synchronous method in executor to avoid blocking event loop
            derived = await loop.run_in_executor(
                None, lambda: analyzer.get_derived_classes(class_name, project_only)
            )
            return [TextContent(type="text", text=json.dumps(derived, indent=2))]

        elif name == "find_callers":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", "")
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.find_callers(function_name, class_name)
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "find_callees":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", "")
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.find_callees(function_name, class_name)
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_call_sites":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", "")
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None, lambda: analyzer.get_call_sites(function_name, class_name)
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_files_containing_symbol":
            symbol_name = arguments["symbol_name"]
            symbol_kind = arguments.get("symbol_kind")
            project_only = arguments.get("project_only", True)
            result = await analyzer.get_files_containing_symbol(
                symbol_name, symbol_kind, project_only
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_call_path":
            from_function = arguments["from_function"]
            to_function = arguments["to_function"]
            max_depth = arguments.get("max_depth", 10)
            # Run synchronous method in executor to avoid blocking event loop
            paths = await loop.run_in_executor(
                None, lambda: analyzer.get_call_path(from_function, to_function, max_depth)
            )
            return [TextContent(type="text", text=json.dumps(paths, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


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

    # Run with selected transport
    if args.transport == "stdio":
        # Import here to avoid issues if mcp package not installed
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    elif args.transport in ("http", "sse"):
        # Import HTTP server module
        try:
            from mcp_server.http_server import run_http_server
        except ImportError:
            from http_server import run_http_server

        # Run HTTP/SSE server
        await run_http_server(server, args.host, args.port, args.transport)

    else:
        diagnostics.fatal(f"Unknown transport: {args.transport}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
