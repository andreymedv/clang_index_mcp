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

# MCP Server
server = Server("cpp-analyzer")


@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_classes",
            description="Search for C++ class and struct definitions by name pattern. **Use this when**: user wants to find/locate a class, find where it's defined, or search by partial name. **Don't use** get_class_info (which needs exact name and returns full structure, not location).\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns list with: qualified_name (fully qualified with namespaces, e.g. 'app::ui::View'), namespace (namespace portion, e.g. 'app::ui'), kind (CLASS_DECL/STRUCT_DECL), file, line, is_project, base_classes (present by default; omit with include_base_classes=false), template_kind (null for non-templates; 'class_template'/'partial_specialization'/'full_specialization' for templates), template_parameters, specialization_of (qualified name of primary template, for specializations), start_line, end_line (complete line range), header_file (if declared in header), header_start_line, header_end_line, brief (first line of documentation or null), doc_comment (full documentation comment up to 4000 chars or null). Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Supports regex patterns.\n\n**POST-FILTERING TIP:** Results include full metadata. Filter client-side instead of making more tool calls: e.g., to find only structs, filter by `kind='STRUCT_DECL'`. To find base classes, check `base_classes` array (or use get_class_info for full inheritance info). To find templates, filter by `template_kind != null`. To find specializations, filter by `template_kind in ('full_specialization', 'partial_specialization')`.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            'Class/struct name to search for. **Empty string "" matches ALL classes** - '
                            'useful with file_name filter (e.g., pattern="", file_name="network.h" '
                            "returns all classes in that file).\n\n"
                            "**C++ Note**: Unlike Java, C++ has NO enforced naming convention linking class "
                            "names to file names. A class 'UserManager' could be in user_manager.h, users.h, "
                            "or any file. Always search by class name first, then check the 'file' field in "
                            "results.\n\n"
                            "**Pattern Matching Modes** (case-insensitive, validated in testing):\n\n"
                            "1. **Unqualified (no ::)**: Matches class in any namespace\n"
                            "   - Example: 'Handler' → matches global::Handler, app::ui::Handler, "
                            "legacy::ui::Handler\n\n"
                            "2. **Qualified Suffix (with ::)**: Component-based suffix matching\n"
                            "   - Example: 'ui::Handler' → matches app::ui::Handler, legacy::ui::Handler\n"
                            "   - Example: 'app::ui::Handler' → matches only app::ui::Handler\n"
                            "   - Note: Does NOT match 'myui::Handler' (requires component boundary)\n\n"
                            "3. **Exact Global Match (leading ::)**: Matches only global namespace\n"
                            "   - Example: '::Handler' → matches only global::Handler (not app::ui::Handler)\n\n"
                            "4. **Regex (with metacharacters)**: Full regex matching\n"
                            "   - Example: 'app::.*::Handler' → matches app::ui::Handler, app::core::Handler\n"
                            "   - Example: '.*Manager.*' → matches anything containing 'Manager'\n\n"
                            "**Tip**: Use the 'namespace' parameter for exact namespace filtering (e.g., "
                            "namespace='ui' returns only classes in exactly the 'ui' namespace)."
                        ),
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
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Optional: Filter results to classes in the specified namespace. **Supports "
                            "partial namespace matching** at :: boundaries (case-sensitive). "
                            "'builders' matches 'myapp::builders', 'app' matches 'myapp::app',"
                            "'app::ui' returns classes in any namespace ending with '::app::ui'. "
                            "'' (empty string) returns only global namespace classes. "
                            "**Use this to disambiguate** when multiple namespaces have the same class name."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Optional: Maximum number of results to return. Use this to limit large result "
                            "sets. When specified, response includes metadata with 'returned' and "
                            "'total_matches' counts for pagination awareness."
                        ),
                        "minimum": 1,
                    },
                    "include_base_classes": {
                        "type": "boolean",
                        "description": (
                            "When true (default), each result includes a base_classes list showing "
                            "direct parent classes. Set to false to reduce response size when inheritance "
                            "info is not needed (e.g., when only searching for class locations)."
                        ),
                        "default": True,
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="search_functions",
            description="Search for C++ functions and methods by name pattern. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns list with: prototype (full C++ declaration, e.g. 'public virtual void app::Handler::process(int) const = 0' — encodes access, qualifiers, return type, qualified name, params in one readable string), qualified_name (for tool chaining, e.g. 'app::Database::save'), namespace, kind (FUNCTION_DECL/CXX_METHOD/CONSTRUCTOR/DESTRUCTOR), parent_class, is_project, template_kind, template_parameters, specialization_of, location objects (declaration/definition with file/line/start_line/end_line), brief, doc_comment. Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. Searches both standalone functions and class methods. Supports regex patterns.\n\n**POST-FILTERING TIP:** The prototype field makes filtering intuitive: scan for 'virtual', 'const', '= 0', 'static' in prototype to identify method kinds. Use `signature_pattern` to filter by parameter types or return types (e.g., signature_pattern='std::string' finds functions taking or returning std::string — matches against the prototype string). Add `include_attributes=true` to get a machine-filterable `attributes` list (['virtual', 'const', 'definition', etc.]) for programmatic filtering without string parsing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            'Function/method name to search for. **Empty string "" matches ALL functions** - '
                            'useful with file_name filter (e.g., pattern="", file_name="network.cpp" '
                            "returns all functions in that file).\n\n"
                            "**C++ Note**: Unlike Java, C++ has NO enforced naming convention. Functions can "
                            "be declared/defined in any file, not necessarily matching their name or class.\n\n"
                            "**Pattern Matching Modes** (case-insensitive, validated in testing):\n\n"
                            "1. **Unqualified (no ::)**: Matches function/method in any namespace or class\n"
                            "   - Example: 'process' → matches global::process(), app::process(), "
                            "Handler::process()\n\n"
                            "2. **Qualified Suffix (with ::)**: Component-based suffix matching\n"
                            "   - Example: 'Handler::process' → matches app::Handler::process, "
                            "legacy::Handler::process\n"
                            "   - Example: 'app::Handler::process' → matches only app::Handler::process\n"
                            "   - Works for namespaces: 'app::init' → matches functions in app namespace\n\n"
                            "3. **Exact Global Match (leading ::)**: Matches only global namespace functions\n"
                            "   - Example: '::main' → matches only global::main (not app::main)\n\n"
                            "4. **Regex (with metacharacters)**: Full regex matching\n"
                            "   - Example: 'get.*' → matches getValue, getData, getConfig\n"
                            "   - Example: '.*Test.*' → matches anything containing 'Test'\n\n"
                            "**Tip**: Use the 'namespace' parameter for exact namespace/class filtering (e.g., "
                            "namespace='app::Handler' returns only methods of app::Handler class)."
                        ),
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). **Keep true for most use cases** - user questions typically refer to their project code. Only set to false if user explicitly asks about standard library, third-party dependencies, or 'all code including libraries'.",
                        "default": True,
                    },
                    "class_name": {
                        "type": "string",
                        "description": (
                            "Optional: Only populate if user specifically mentions a class (e.g., 'find "
                            "process method in Handler class'). Limits search to only methods belonging to "
                            "this specific class. **Leave empty** (which is typical) to search all functions "
                            "and methods across the codebase."
                        ),
                    },
                    "file_name": {
                        "type": "string",
                        "description": "Optional: Filter results to only symbols defined in files matching this name. Works with any file type (.h, .cpp, .cc, etc.). Accepts multiple formats: absolute path, relative to project root, or filename only (e.g., 'network.h', 'utils.cpp'). Uses 'endswith' matching, so partial paths work if they uniquely identify the file.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Optional: Filter results to functions/methods in the specified namespace. "
                            "**Supports partial namespace matching** at :: boundaries (case-sensitive). "
                            "For methods, matches namespace + class. "
                            "'Handler' matches 'app::Handler', 'app' matches 'myapp::app', "
                            "'app::Handler' matches 'org::app::Handler'. "
                            "'' (empty string) returns only global namespace functions. "
                            "**Use this to disambiguate** when multiple namespaces have the same function."
                        ),
                    },
                    "signature_pattern": {
                        "type": "string",
                        "description": (
                            "Optional: Filter to functions whose prototype contains this substring "
                            "(case-insensitive). Matches against the full prototype string which includes "
                            "access modifier, qualifiers, return type, qualified name, and parameters. "
                            "Examples: 'std::string' finds functions with std::string in params or "
                            "return type; 'const' finds const-qualified methods; 'void' finds "
                            "void-returning functions; 'virtual' finds virtual methods. "
                            "This is plain substring match — special characters like *, &, <, > are matched literally."
                        ),
                    },
                    "include_attributes": {
                        "type": "boolean",
                        "description": (
                            "Optional (default false): When true, include a machine-filterable 'attributes' "
                            "list in each result (e.g. ['virtual', 'const', 'definition']). "
                            "Useful for programmatic filtering without parsing the prototype string. "
                            "The prototype field already encodes all this information visually; "
                            "set this to true only when you need reliable attribute-based filtering."
                        ),
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Optional: Maximum number of results to return. Use this to limit large result "
                            "sets. When specified, response includes metadata with 'returned' and "
                            "'total_matches' counts for pagination awareness."
                        ),
                        "minimum": 1,
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="get_class_info",
            description="Get comprehensive information about a specific class: methods, base classes, direct derived classes, location, documentation, and virtual/abstract indicators. **Use this when**: user wants to see class methods, API, or inheritance neighborhood. **Requires exact class name** - if you don't know exact name, use search_classes first.\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns: name, kind, base_classes, derived_classes (direct project-only subclasses — each with name, qualified_name, kind, location), methods (sorted by line, each with prototype, access, location, template_kind, is_virtual, is_pure_virtual, is_const, is_static, is_definition, brief, doc_comment), is_project, template_kind (null for non-templates), location objects (declaration/definition), brief, doc_comment. Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments.\n\n**AMBIGUITY HANDLING:** If multiple classes have the same simple name (e.g., 'SomeClass' exists in both 'ns1::SomeClass' and 'ns2::SomeClass'), returns an ambiguity response: {error, is_ambiguous: true, matches: [{name, qualified_name, namespace, kind, file, line}], suggestion}. Use a qualified name to disambiguate.\n\n**EDGE CASES:**\n- `methods` array: May be empty for pure data classes or forward declarations.\n- `derived_classes`: Only includes DIRECT (one-level) subclasses from project files. For all descendants, use get_class_hierarchy.\n\n**POST-FILTERING TIP:** Methods include rich metadata. Filter client-side: e.g., to find abstract interface methods, filter by `is_pure_virtual=true`. To find public API only, filter by `access='public'`. To find implementations (not declarations), filter by `is_definition=true`.",
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
            description="Get formatted signature strings for function(s) with the exact name specified. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns a list of human-readable signature strings showing return type, function name with parameter types and names, and class scope qualifier (e.g., 'void ClassName::functionName(int x, const std::string &y)' or 'double functionName(double z)'). Includes return types, parameter names (when available from source), and const/noexcept qualifiers. If multiple overloads exist, returns all of them. Use this to quickly see full function signatures. Returns formatted strings only, not structured metadata - use search_functions if you need file locations, line numbers, or complete metadata.",
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
            name="get_type_alias_info",
            description="Get comprehensive type alias information for a C++ type. Resolves type aliases (using/typedef) bidirectionally and detects ambiguous type names. **Use this when**: user wants to know if a type is an alias, find the real type behind an alias, or find all aliases for a canonical type.\n\n**IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\n**Pattern Matching** (same as search_classes):\n- Unqualified: 'Widget' → matches Widget in any namespace\n- Qualified: 'ui::Widget' → component-based suffix matching\n- Exact: '::Widget' → matches only global namespace\n\n**Returns** (success case): canonical_type (the real type name), qualified_name (fully qualified canonical type), namespace, file (where canonical type is defined), line, input_was_alias (true if input was an alias), is_ambiguous (false), aliases (array of all aliases pointing to this type, each with name, qualified_name, file, line).\n\n**Returns** (ambiguous case): error message, is_ambiguous (true), matches (array of all matching types with canonical_type, qualified_name, namespace, file, line), suggestion ('Use qualified name').\n\n**Returns** (not found): error message, canonical_type (null), aliases (empty array).\n\n**Example 1** - Query canonical type:\n  Input: 'ui::Widget'\n  Output: canonical_type='ui::Widget', aliases=[{name='WidgetAlias', file='types.h', line=42}], input_was_alias=false\n\n**Example 2** - Query alias:\n  Input: 'WidgetAlias'\n  Output: canonical_type='ui::Widget', aliases=[{name='WidgetAlias'}, {name='WPtr'}], input_was_alias=true\n\n**Example 3** - Ambiguous:\n  Input: 'Widget' (exists in multiple namespaces)\n  Output: error='Ambiguous type name', is_ambiguous=true, matches=[{qualified_name='Widget'}, {qualified_name='ui::Widget'}]",
            inputSchema={
                "type": "object",
                "properties": {
                    "type_name": {
                        "type": "string",
                        "description": "Type name to query (unqualified, partially qualified, or fully qualified). Examples: 'Widget', 'ui::Widget', '::ui::Widget'",
                    }
                },
                "required": ["type_name"],
            },
        ),
        Tool(
            name="search_symbols",
            description="Unified search across multiple C++ symbol types (classes, structs, functions, methods) using a single pattern. **IMPORTANT:** If called during indexing, results will be incomplete. Check response metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\nReturns a dictionary with two keys: 'classes' (array of class/struct results) and 'functions' (array of function/method results). Each result includes name, qualified_name (fully qualified e.g. 'ns::Class'), namespace, kind, file location, line number, template_kind (null for non-templates; set to kind of template for templates and specializations), complete line ranges (start_line, end_line), header location (header_file, header_start_line, header_end_line), brief (first line of documentation or null), doc_comment (full documentation comment up to 4000 chars or null), and other metadata. Documentation extracted from Doxygen (///, /** */), JavaDoc, and Qt-style (/*!) comments. This is a convenient alternative to calling search_classes and search_functions separately. Use symbol_types to filter which categories are populated.\n\n**POST-FILTERING TIP:** Results include full metadata. Filter client-side: e.g., to find only implementations, filter functions by `is_definition=true`. To find only structs in classes array, filter by `kind='STRUCT_DECL'`. To find virtual methods, filter functions by `is_virtual=true`.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            'Symbol name pattern to search for. **Empty string "" matches ALL symbols** of '
                            "the specified types - useful for listing all classes or functions in a file.\n\n"
                            "**C++ Note**: C++ has NO enforced naming conventions. Symbols can be in any file, "
                            "regardless of their name.\n\n"
                            "**Pattern Matching Modes** (case-insensitive, validated in testing):\n\n"
                            "1. **Unqualified (no ::)**: Matches symbol in any namespace or class\n"
                            "   - Example: 'Config' → matches global::Config, app::Config, Handler::Config\n\n"
                            "2. **Qualified Suffix (with ::)**: Component-based suffix matching\n"
                            "   - Example: 'app::Config' → matches app::Config, legacy::app::Config\n"
                            "   - Works for classes and methods: 'Handler::process' → matches methods too\n\n"
                            "3. **Exact Global Match (leading ::)**: Matches only global namespace\n"
                            "   - Example: '::Config' → matches only global::Config\n\n"
                            "4. **Regex (with metacharacters)**: Full regex matching\n"
                            "   - Example: '.*Config.*' → matches anything containing 'Config'\n"
                            "   - Example: 'get.*|set.*' → matches all getters and setters\n\n"
                            "**Tip**: Use the 'namespace' parameter for exact namespace filtering across all "
                            "symbol types."
                        ),
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
                    "namespace": {
                        "type": "string",
                        "description": (
                            "Optional: Filter results to symbols in the specified namespace. "
                            "**Supports partial namespace matching** at :: boundaries (case-sensitive). "
                            "For methods, matches namespace + class. "
                            "'Handler' matches 'app::Handler', 'app' matches 'myapp::app'. "
                            "'' (empty string) returns only global namespace symbols. "
                            "**Use this to disambiguate** when multiple namespaces have the same symbol."
                        ),
                    },
                    "signature_pattern": {
                        "type": "string",
                        "description": (
                            "Optional: Filter to functions whose signature contains this substring "
                            "(case-insensitive). Only applies to function/method results, not classes. "
                            "Matches against the full human-readable signature. "
                            "Examples: 'std::string' finds functions with std::string in params or "
                            "return type; 'void' finds void-returning functions. This is plain "
                            "substring match — special characters like *, &, <, > are matched literally."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Optional: Maximum number of results to return (across all symbol types). "
                            "Use this to limit large result sets. When specified, response includes "
                            "metadata with 'returned' and 'total_matches' counts for pagination awareness."
                        ),
                        "minimum": 1,
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="find_in_file",
            description=(
                "Search for C++ symbols (classes, functions, methods) within a specific source file "
                "or files matching a glob pattern.\n\n"
                "**IMPORTANT:** If called during indexing, results will be incomplete. Check response "
                "metadata 'status' field. Use 'wait_for_indexing' first if you need guaranteed complete results.\n\n"
                "**RESPONSE FORMAT:** Returns dict with:\n"
                "- `results`: Array of matching symbols\n"
                "- `matched_files`: Files that were searched (useful for glob patterns)\n"
                "- `suggestions`: Similar file paths when no match found (helps fix typos)\n"
                "- `message`: Human-readable status message\n\n"
                "**GLOB PATTERN SUPPORT:** Use glob patterns to search across multiple files:\n"
                "- `**/tests/**/*.cpp` - all .cpp files under any tests directory\n"
                "- `src/*.h` - all headers directly in src/\n"
                "- `**/handler*` - files containing 'handler' in any path\n\n"
                "**SUGGESTIONS:** When file not found, response includes `suggestions` array with "
                "similar file paths to help correct typos or find the right file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Path to file(s) to search. **Supported formats:**\n\n"
                            "1. **Absolute path:** `/full/path/to/file.cpp`\n"
                            "2. **Relative path:** `src/main.cpp` (from project root)\n"
                            "3. **Filename only:** `main.cpp` (matches any file with this name)\n"
                            "4. **Glob pattern:** `**/tests/**/*.cpp`, `src/*.h`\n\n"
                            "**Examples:**\n"
                            "- `handler.cpp` - exact file\n"
                            "- `**/tests/**/*.cpp` - all test files\n"
                            "- `src/core/*.h` - headers in core directory\n\n"
                            "If no match found, `suggestions` array will contain similar paths."
                        ),
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Symbol name pattern to search for within the file(s). "
                            '**Empty string "" matches ALL symbols** - useful for listing all '
                            "classes/functions in a file.\n\n"
                            "**Pattern matching modes** (case-insensitive):\n"
                            "1. **Unqualified** (no ::): matches symbol in any namespace\n"
                            "2. **Qualified suffix**: 'ns::Symbol' - component-based suffix match\n"
                            "3. **Exact match**: '::Symbol' - global namespace only (leading ::)\n"
                            "4. **Regex**: uses regex with metacharacters\n\n"
                            "**Examples:** 'Handler', 'ui::Handler', '::Handler', '.*Manager.*'"
                        ),
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
            description=(
                "Manually refresh the project index to detect and re-parse files that have been "
                "modified, added, or deleted since the last index. The analyzer does NOT "
                "automatically detect file changes - you must call this tool whenever source files "
                "are modified (whether by you, external editor, git checkout, build system, or any "
                "other means) to ensure the index reflects the current state of the codebase.\n\n"
                "Supports two modes:\n"
                "- Incremental (default): Analyzes only changed files using dependency tracking\n"
                "- Full: Re-analyzes all files (use force_full=true)\n\n"
                "**IMPORTANT:** ALWAYS use incremental mode (default) unless absolutely necessary. "
                "Incremental refresh is fast (30-300x faster) and reliable. NEVER set force_full=true "
                "without explicit user permission - it can take 5-10 minutes on large projects "
                "(5000+ files) vs seconds for incremental.\n\n"
                "**Workflow guidance for common scenarios:**\n"
                "- Class/function not found: First try incremental refresh. If still not found, "
                "the symbol may be in a file not yet indexed (check project configuration) or use "
                "different qualified name.\n"
                "- After git checkout: Use incremental refresh (default) - it detects all file "
                "changes automatically.\n"
                "- After configuration changes: Only use force_full=true if you modified "
                "cpp-analyzer-config.json or compile_commands.json.\n"
                "- Symbol information outdated: Use incremental refresh (default) - sufficient for "
                "99% of cases.\n\n"
                "**Non-blocking operation:** Refresh runs in the background. This tool returns "
                "immediately while the refresh continues. Use 'get_indexing_status' to monitor "
                "progress. Tools remain available during refresh and will return results based on "
                "the current cache state."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "incremental": {
                        "type": "boolean",
                        "description": (
                            "When true (default), performs incremental analysis by detecting "
                            "changes and re-analyzing only affected files. When false, performs "
                            "full re-analysis of all files. ALWAYS use true (default) unless "
                            "force_full is set."
                        ),
                        "default": True,
                    },
                    "force_full": {
                        "type": "boolean",
                        "description": (
                            "CAUTION: Forces full re-analysis of ALL files (5-10 minutes for 5000+ "
                            "files). NEVER use without explicit user permission. Only needed after "
                            "major configuration file changes (cpp-analyzer-config.json, "
                            "compile_commands.json). For all other cases (file changes, git "
                            "operations, missing symbols), use incremental mode."
                        ),
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
            description="Get the complete inheritance graph for a C++ class as a flat adjacency list. BFS from the queried class explores ALL edges in both directions (upward to ancestors, downward to descendants) from every discovered node, returning the entire connected component. Diamond inheritance and multiple inheritance are handled cleanly — no duplicated nodes. **Use this when** user asks for: 'all subclasses/descendants of X', 'all classes inheriting from X', 'complete inheritance tree', 'full hierarchy of X', 'what does X inherit from (all levels)'. **Note:** get_class_info already returns direct base/derived classes — use get_class_hierarchy for full transitive closure.\n\nReturns: {queried_class: qualified name of the queried class, classes: flat dict keyed by qualified name where each entry has {name, qualified_name, kind, is_project, base_classes: [qualified names], derived_classes: [qualified names]}}. Unresolvable base classes (external libs, template-dependent types) are included with is_unresolved or is_dependent_type flags. If not found, returns {'error': 'Class <name> not found'}.\n\n**CAPS:** Result is limited to max_nodes (default 200) nodes and optionally max_depth BFS levels. When capped, response includes truncated=true and nodes_returned. Increase max_nodes or set max_depth to control scope.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to analyze. The result will show this class's complete inheritance hierarchy in both directions (ancestors and descendants).",
                    },
                    "max_nodes": {
                        "type": "integer",
                        "description": "Maximum number of nodes to include in the result (default 200). Prevents response explosion for widely-used base classes like QObject or std::exception. Set higher if you need the full hierarchy of a large class family.",
                        "default": 200,
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum BFS depth from the queried class (default: unlimited). Depth 0 = queried class only, depth 1 = direct parents/children, depth 2 = grandparents/grandchildren, etc. Useful when you only need nearby relatives.",
                    },
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="find_callers",
            description=(
                "**DIRECTION: INCOMING** - Find all code that CALLS (invokes) a specific target function.\n\n"
                "**USE THIS WHEN:**\n"
                "- User asks 'what calls X?', 'where is X invoked?', 'show callers of X', "
                "'what invokes X?', 'places where X is called', 'who calls X?'\n"
                "- Impact analysis: what code depends on this function?\n"
                "- Refactoring: what breaks if I change this function?\n"
                "- Finding all usages of a function\n\n"
                "**DO NOT USE THIS WHEN (use find_callees or get_call_sites instead):**\n"
                "- User asks 'what does X call?', 'show calls inside X'\n"
                "- You want to see what functions X depends on\n\n"
                "**Returns:**\n"
                "- callers: List of caller function info (name, kind, file, line where caller is defined, "
                "signature, parent_class, is_project, start_line, end_line)\n"
                "- call_sites: Array of EXACT call locations with file, line, column where each call occurs, "
                "plus caller name/signature for context\n"
                "- total_call_sites: Count of all call sites found\n\n"
                "The call_sites array provides LINE-LEVEL PRECISION - exact file:line:column where the "
                "target function is called.\n\n"
                "**Example:**\n"
                "  find_callers('processData') → returns all functions that CALL processData, "
                "with exact locations of each call"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": (
                            "Name of the TARGET function you want to find callers for - "
                            "the function being called by other code."
                        ),
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the target is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": "",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Optional: Maximum number of caller results to return. Use this to limit large "
                            "result sets. When specified, response includes metadata with 'returned' and "
                            "'total_matches' counts for pagination awareness."
                        ),
                        "minimum": 1,
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="find_callees",
            description=(
                "**DIRECTION: OUTGOING** - Find all functions that a specific source function CALLS "
                "(the inverse of find_callers).\n\n"
                "**USE THIS WHEN:**\n"
                "- User asks 'what does X call?', 'what functions does X invoke?', 'show X's dependencies'\n"
                "- Understanding what a function depends on\n"
                "- Analyzing code flow or execution paths\n\n"
                "**DO NOT USE THIS WHEN (use find_callers instead):**\n"
                "- User asks 'what calls X?', 'where is X invoked?'\n"
                "- You want to find code that depends ON this function\n\n"
                "**Returns:** List of callee functions with: name, kind, file, line (where callee is DEFINED), "
                "signature, parent_class, is_project, start_line, end_line, header_file info.\n\n"
                "**LIMITATION:** The line numbers indicate where each CALLEE IS DEFINED, not where it's called "
                "within the source function. For exact call site locations, use get_call_sites instead.\n\n"
                "**DIFFERENCE FROM get_call_sites:**\n"
                "- Both show what X calls (outgoing direction)\n"
                "- find_callees: Returns where called functions are DEFINED\n"
                "- get_call_sites: Returns exact CALL LOCATIONS within X's body\n\n"
                "**Example:**\n"
                "  find_callees('processData') → returns list of functions that processData calls, "
                "with each function's definition location"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": (
                            "Name of the SOURCE function to analyze - the function doing the calling. "
                            "Returns what this function calls, not what calls it."
                        ),
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the source is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": "",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Optional: Maximum number of callee results to return. Use this to limit large "
                            "result sets. When specified, response includes metadata with 'returned' and "
                            "'total_matches' counts for pagination awareness."
                        ),
                        "minimum": 1,
                    },
                },
                "required": ["function_name"],
            },
        ),
        Tool(
            name="get_call_sites",
            description=(
                "**DIRECTION: OUTGOING** - Shows what calls are made WITHIN a function's body, "
                "NOT where the function itself is called.\n\n"
                "**USE THIS WHEN:**\n"
                "- User asks 'what does X call?', 'show calls inside X', 'what functions does X invoke?'\n"
                "- You need exact file:line:column for call statements within a function body\n"
                "- You want to understand a function's dependencies with precise locations\n\n"
                "**DO NOT USE THIS WHEN (use find_callers instead):**\n"
                "- User asks 'what calls X?', 'where is X invoked?', 'show callers of X', "
                "'what invokes X?', 'places where X is called'\n"
                "- You want to find code that DEPENDS ON a function\n\n"
                "**DIFFERENCE FROM find_callees:**\n"
                "- Both show what X calls (outgoing/forward direction)\n"
                "- find_callees: Returns callee DEFINITIONS (where called functions are defined)\n"
                "- get_call_sites: Returns CALL LOCATIONS (exact file:line:column of each call "
                "statement within X's body)\n\n"
                "**Returns** array of call sites, each with:\n"
                "- target: Name of called function\n"
                "- target_signature: Full signature of called function\n"
                "- file: Source file containing the call\n"
                "- line: Exact line number of call\n"
                "- column: Column position of call\n"
                "- target_file: File where called function is defined\n\n"
                "**Example:**\n"
                "  get_call_sites('processData') → returns all function calls made INSIDE "
                "processData's body\n"
                "  find_callers('processData') → returns all places WHERE processData is called"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": (
                            "Name of the SOURCE function to analyze - the function whose BODY "
                            "you want to examine for outgoing calls. NOT the function you're "
                            "looking for callers of (use find_callers for that)."
                        ),
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
                    # find_callers/find_callees: count callers/callees list
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
    result = await _handle_tool_call(name, arguments)
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
            "get_type_alias_info",
            "search_symbols",
            "find_in_file",
            "get_class_hierarchy",
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
                enhanced_result.next_steps = suggestions.for_search_classes(results)
            return [TextContent(type="text", text=json.dumps(enhanced_result.to_dict(), indent=2))]

        elif name == "search_functions":
            project_only = arguments.get("project_only", True)
            class_name = arguments.get("class_name", None)
            file_name = arguments.get("file_name", None)
            namespace = arguments.get("namespace", None)
            pattern = arguments["pattern"]
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
            pattern = arguments["pattern"]
            project_only = arguments.get("project_only", True)
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
            incremental = arguments.get("incremental", True)
            force_full = arguments.get("force_full", False)

            # Issue #7: Warn if force_full is used (should be rare)
            if force_full:
                diagnostics.warning(
                    "force_full=true was requested - this will re-analyze ALL files and may "
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

            ccm = analyzer.compile_commands_manager
            status = {
                "analyzer_type": analyzer_type,
                "call_graph_enabled": True,
                "usr_tracking_enabled": True,
                "compile_commands_enabled": ccm.enabled if ccm else False,
                "compile_commands_path": ccm.compile_commands_path if ccm else None,
                "compile_commands_cache_enabled": ccm.cache_enabled if ccm else False,
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

        elif name == "find_callers":
            function_name = str(arguments["function_name"])
            class_name = str(arguments.get("class_name", ""))
            max_results = arguments.get("max_results", None)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None,
                lambda: analyzer.find_callers(function_name, class_name),  # type: ignore[arg-type]
            )
            # Results is dict with "callers" list - use that for metadata logic
            callers_list = results.get("callers", []) if isinstance(results, dict) else []
            total_count = len(callers_list)
            # Apply truncation if max_results specified
            if max_results is not None and len(callers_list) > max_results:
                results["callers"] = callers_list[:max_results]
            # 3-case empty-result logic (internal flags stripped before sending to LLM):
            #   not found            → default "check spelling" suggestions  (None)
            #   found, no callers    → no hints at all                        ([])
            #   found, ext. callers  → suggest project_only=false             ([...])
            function_found = (
                results.pop("_function_found", False) if isinstance(results, dict) else False
            )
            has_any_in_graph = (
                results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
            )
            if not function_found:
                empty_suggestions = None  # default "check spelling / broaden pattern"
            elif has_any_in_graph:
                empty_suggestions = [
                    "Function found but all callers are outside the indexed project; "
                    "pass project_only=false to include external callers"
                ]
            else:
                empty_suggestions = []  # genuinely no callers → no hints
            # Wrap with appropriate metadata
            enhanced_result = _create_search_result(
                results.get("callers", []),
                state_manager,
                "find_callers",
                max_results,
                total_count,
                empty_suggestions=empty_suggestions,
            )
            enhanced_result.next_steps = suggestions.for_find_callers(function_name, results)
            # Merge metadata into results dict
            output = results.copy() if isinstance(results, dict) else {"callers": results}
            enhanced_dict = enhanced_result.to_dict()
            if "metadata" in enhanced_dict:
                output["metadata"] = enhanced_dict["metadata"]
            return [TextContent(type="text", text=json.dumps(output, indent=2))]

        elif name == "find_callees":
            function_name = str(arguments["function_name"])
            class_name = str(arguments.get("class_name", ""))
            max_results = arguments.get("max_results", None)
            # Run synchronous method in executor to avoid blocking event loop
            results = await loop.run_in_executor(
                None,
                lambda: analyzer.find_callees(function_name, class_name),  # type: ignore[arg-type]
            )
            # Results is dict with "callees" list - use that for metadata logic
            callees_list = results.get("callees", []) if isinstance(results, dict) else []
            total_count = len(callees_list)
            # Apply truncation if max_results specified
            if max_results is not None and len(callees_list) > max_results:
                results["callees"] = callees_list[:max_results]
            # 3-case empty-result logic (internal flags stripped before sending to LLM):
            #   not found               → default "check spelling" suggestions  (None)
            #   found, no callees       → no hints at all                        ([])
            #   found, ext. callees     → suggest project_only=false             ([...])
            function_found = (
                results.pop("_function_found", False) if isinstance(results, dict) else False
            )
            has_any_in_graph = (
                results.pop("_has_any_in_graph", False) if isinstance(results, dict) else False
            )
            if not function_found:
                empty_suggestions = None  # default "check spelling / broaden pattern"
            elif has_any_in_graph:
                empty_suggestions = [
                    "Function found but all callees are outside the indexed project; "
                    "pass project_only=false to include calls to external libraries"
                ]
            else:
                empty_suggestions = []  # genuinely calls nothing → no hints
            # Wrap with appropriate metadata
            enhanced_result = _create_search_result(
                results.get("callees", []),
                state_manager,
                "find_callees",
                max_results,
                total_count,
                empty_suggestions=empty_suggestions,
            )
            enhanced_result.next_steps = suggestions.for_find_callees(function_name, results)
            # Merge metadata into results dict
            output = results.copy() if isinstance(results, dict) else {"callees": results}
            enhanced_dict = enhanced_result.to_dict()
            if "metadata" in enhanced_dict:
                output["metadata"] = enhanced_dict["metadata"]
            return [TextContent(type="text", text=json.dumps(output, indent=2))]

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
    asyncio.run(main())
