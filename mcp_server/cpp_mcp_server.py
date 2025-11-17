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
    """Find and configure libclang library"""
    import platform
    import glob
    
    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one directory to find lib folder (since we're in mcp_server subfolder)
    parent_dir = os.path.dirname(script_dir)
    
    # First, try bundled libraries (self-contained)
    bundled_paths = []
    if system == "Windows":
        bundled_paths = [
            os.path.join(parent_dir, "lib", "windows", "libclang.dll"),
            os.path.join(parent_dir, "lib", "windows", "clang.dll"),
        ]
    elif system == "Darwin":  # macOS
        bundled_paths = [
            os.path.join(parent_dir, "lib", "macos", "libclang.dylib"),
        ]
    else:  # Linux
        bundled_paths = [
            os.path.join(parent_dir, "lib", "linux", "libclang.so.1"),
            os.path.join(parent_dir, "lib", "linux", "libclang.so"),
        ]
    
    # Try bundled libraries first
    for path in bundled_paths:
        if os.path.exists(path):
            diagnostics.info(f"Using bundled libclang at: {path}")
            Config.set_library_file(path)
            return True

    diagnostics.info("No bundled libclang found, searching system...")
    
    # Fallback to system-installed libraries
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
        
        # Try to find in system PATH
        import shutil
        llvm_config = shutil.which("llvm-config")
        if llvm_config:
            try:
                import subprocess
                result = subprocess.run([llvm_config, "--libdir"], capture_output=True, text=True)
                if result.returncode == 0:
                    lib_dir = result.stdout.strip()
                    system_paths.insert(0, os.path.join(lib_dir, "libclang.dll"))
            except:
                pass
    
    elif system == "Darwin":  # macOS
        system_paths = [
            "/usr/local/lib/libclang.dylib",
            "/opt/homebrew/lib/libclang.dylib",
            "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/libclang.dylib",
        ]
    
    else:  # Linux
        system_paths = [
            "/usr/lib/llvm-*/lib/libclang.so.1",
            "/usr/lib/x86_64-linux-gnu/libclang-*.so.1",
            "/usr/lib/libclang.so.1",
            "/usr/lib/libclang.so",
        ]
    
    # Try each system path
    for path_pattern in system_paths:
        if "*" in path_pattern:
            # Handle glob patterns
            matches = glob.glob(path_pattern)
            if matches:
                path = matches[0]  # Use first match
            else:
                continue
        else:
            path = path_pattern
        
        if os.path.exists(path):
            diagnostics.info(f"Found system libclang at: {path}")
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
except ImportError:
    # Fall back to direct import (when run as script)
    from cpp_analyzer import CppAnalyzer
    from compile_commands_manager import CompileCommandsManager

# Initialize analyzer
PROJECT_ROOT = os.environ.get('CPP_PROJECT_ROOT', None)

# Initialize analyzer as None - will be set when project directory is specified
analyzer = None

# Track if analyzer has been initialized with a valid project
analyzer_initialized = False

# MCP Server
server = Server("cpp-analyzer")

@server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_classes",
            description="Search for C++ class and struct definitions by name pattern. **Use this when**: user wants to find/locate a class, find where it's defined, or search by partial name. **Don't use** get_class_info (which needs exact name and returns full structure, not location).\n\nReturns list with: name, kind (CLASS_DECL/STRUCT_DECL), file, line, is_project, base_classes. Supports regex patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Class/struct name pattern to search for. Supports regular expressions (e.g., 'My.*Class' matches MyBaseClass, MyDerivedClass, etc.)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). **Keep true for most use cases** - user questions typically refer to their project code. Only set to false if user explicitly asks about standard library, third-party dependencies, or 'all code including libraries'.",
                        "default": True
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="search_functions",
            description="Search for C++ functions and methods by name pattern. Returns list with: name, kind (FUNCTION_DECL/CXX_METHOD/CONSTRUCTOR/DESTRUCTOR), file, line, signature, parent_class, is_project. Searches both standalone functions and class methods. Supports regex patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Function/method name pattern to search for. Supports regular expressions (e.g., 'get.*' matches getWidth, getValue, etc.)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies (vcpkg, system headers, third-party libraries). **Keep true for most use cases** - user questions typically refer to their project code. Only set to false if user explicitly asks about standard library, third-party dependencies, or 'all code including libraries'.",
                        "default": True
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Only populate if user specifically mentions a class (e.g., 'find save method in Database class'). Limits search to only methods belonging to this specific class. **Leave empty** (which is typical) to search all functions and methods across the codebase."
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="get_class_info",
            description="Get comprehensive information about a specific class: methods with signatures (all access levels), base classes, file location. **Note**: Member variables/fields (members) are not currently indexed and will be an empty list. **Use this when**: user wants to see class methods or API. **Requires exact class name** - if you don't know exact name, use search_classes first.\n\nReturns: name, kind, file, line, base_classes, methods (sorted by line), members (currently empty), is_project. Returns plain text error 'Class <name> not found' if not found. Returns first match if multiple classes have same name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Exact name of the class to analyze (case-sensitive, must match exactly)"
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="get_function_signature",
            description="Get formatted signature strings for function(s) with the exact name specified. Returns a list of signature strings showing the function name with parameter types and class scope qualifier (e.g., 'ClassName::functionName(int x, std::string y)' or 'functionName(double z)'). Note: Does NOT include return types in the output, only function name, parameters, and class scope if applicable. If multiple overloads exist, returns all of them. Use this to quickly see function parameter types. Returns formatted strings only, not structured metadata - use search_functions if you need file locations, line numbers, or complete metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Exact name of the function/method to look up (case-sensitive). Will return signature strings for all overloads if multiple exist."
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If specified, only returns method signatures from this specific class, ignoring standalone functions and methods from other classes. Leave empty to get signatures for all matching functions across the codebase."
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="search_symbols",
            description="Unified search across multiple C++ symbol types (classes, structs, functions, methods) using a single pattern. Returns a dictionary with two keys: 'classes' (array of class/struct results) and 'functions' (array of function/method results). Each result includes name, kind, file location, line number, and other metadata. This is a convenient alternative to calling search_classes and search_functions separately. Use symbol_types to filter which categories are populated.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Symbol name pattern to search for. Supports regular expressions. Searches across all symbol types unless filtered by symbol_types parameter."
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only searches project source files and excludes external dependencies. Set to false to include third-party libraries and system headers.",
                        "default": True
                    },
                    "symbol_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["class", "struct", "function", "method"]
                        },
                        "description": "Filter results to specific symbol types. Options: 'class' (class definitions), 'struct' (struct definitions), 'function' (standalone functions), 'method' (class member functions). If omitted, both 'classes' and 'functions' arrays will be populated."
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="find_in_file",
            description="Search for C++ symbols (classes, functions, methods) within a specific source file. Returns only symbols defined in that file, with locations and basic information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file. Accepts multiple formats: absolute path (/full/path/to/file.cpp), relative to project root (src/main.cpp), or even partial path (main.cpp). The matcher uses both exact absolute path resolution and 'endswith' matching, so shorter paths work if they uniquely identify the file."
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Symbol name pattern to search for within the file. Supports regular expressions."
                    }
                },
                "required": ["file_path", "pattern"]
            }
        ),
        Tool(
            name="set_project_directory",
            description="**REQUIRED FIRST STEP**: Initialize the analyzer with your C++ project directory. Must be called before any other tools. Indexes all C++ source/header files (.cpp, .h, .hpp, etc.) in the directory and subdirectories, parsing with libclang to build searchable database of classes, functions, and relationships.\n\nWARNING: Indexing large projects takes time. Can be called multiple times to switch projects (reinitializes each time). Returns count of indexed files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the root directory of your C++ project. Must be a valid, existing directory. All subsequent analysis operations will be performed on this project."
                    }
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="refresh_project",
            description="Manually refresh the project index to detect and re-parse files that have been modified, added, or deleted since the last index. The analyzer does NOT automatically detect file changes - you must call this tool whenever source files are modified (whether by you, external editor, git checkout, build system, or any other means) to ensure the index reflects the current state of the codebase. Returns the count of files that were re-parsed.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_server_status",
            description="Get diagnostic information about the MCP server state and index statistics. Returns JSON with: analyzer type, enabled features (call_graph, usr_tracking, compile_commands), file counts (parsed, indexed classes/functions). Use to verify server is working, check if indexing is complete, or debug configuration issues.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_class_hierarchy",
            description="Get the complete bidirectional inheritance hierarchy for a C++ class. **Use this when** user asks for: 'all subclasses/descendants of X', 'all classes inheriting from X', 'complete inheritance tree', or wants both ancestors AND descendants. **Do NOT use** get_derived_classes which only returns immediate children.\n\nReturns: name (class name), base_hierarchy (all ancestors recursively to root), derived_hierarchy (all descendants recursively to leaves), class_info (detailed info), direct base_classes and derived_classes lists. If not found, returns {'error': 'Class <name> not found'}.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to analyze. The result will show this class's complete inheritance hierarchy in both directions (ancestors and descendants)."
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="get_derived_classes",
            description="⚠️ IMPORTANT: This returns ONLY DIRECT children (one level), NOT all descendants. If user asks for 'all classes that inherit from X' or 'all subclasses', use get_class_hierarchy instead for complete transitive closure.\n\nGet a flat list of classes that DIRECTLY inherit from a specified base class (immediate children only). Returns classes where the specified class appears in their direct base_classes list. Example: if C→B→A (C inherits B, B inherits A), calling this on 'A' returns only [B], not C. Returns list with: name, kind, file, line, column, is_project, base_classes. Supports filtering by project_only.",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the base class for which to find direct derived classes (immediate children only, one level down in inheritance tree)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "When true (default), only includes derived classes from project source files, excluding those from external dependencies and libraries. Set to false to include all derived classes from all indexed files.",
                        "default": True
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="find_callers",
            description="Find all functions/methods that call (invoke) a specific target function. Performs call graph analysis to identify caller functions. Returns list with: name, kind, file, line, column, signature, parent_class, is_project.\n\nIMPORTANT - Line Number Limitation: The 'line' and 'column' fields indicate where each CALLER FUNCTION IS DEFINED, not the call site. To find exact call site line numbers: 1) Use this tool to get caller function names/files, 2) Then read those files or use text search to find the specific lines where the target function is invoked.\n\nUse this for: impact analysis (which functions depend on this), refactoring planning (what breaks if I change this), or call graph visualization.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the target function/method to find callers for (the function being called)"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the target is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": ""
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="find_callees",
            description="Find all functions/methods that are called (invoked) by a specific source function. This is the inverse of find_callers - while find_callers shows what calls a function (backwards), find_callees shows what a function calls (forwards). Performs call graph analysis to identify every function called within the body of the specified function. Returns list with: name, kind, file, line, column, signature, parent_class, is_project.\n\nIMPORTANT - Line Number Limitation: The 'line' and 'column' fields indicate where each CALLEE FUNCTION IS DEFINED, not the call site. To find exact call site line numbers: read the source function's file to see where these callees are invoked.\n\nUse this for: understanding dependencies (what does this function depend on), analyzing code flow, or mapping execution paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the source function/method to analyze (the function doing the calling)"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "If the source is a class method, specify the class name here to disambiguate between methods with the same name in different classes. Leave empty to search across both standalone functions and all class methods with the given name.",
                        "default": ""
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="get_call_path",
            description="Find execution paths through the call graph from a starting function to a target function using BFS. A call path is a sequence of function calls connecting two functions (e.g., main -> init -> setup -> loadConfig). Returns ALL possible paths up to max_depth, showing intermediate function chains.\n\nWARNING: In highly connected codebases, can return hundreds/thousands of paths. Use max_depth conservatively. Returns empty array if no path exists within max_depth.",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_function": {
                        "type": "string",
                        "description": "Name of the starting/source function (where the execution path begins)"
                    },
                    "to_function": {
                        "type": "string",
                        "description": "Name of the target/destination function (where the execution path should end)"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum number of intermediate function calls to search through (default: 10). Higher values find longer paths but exponentially increase computation time and result count in highly connected graphs. Keep this low (5-15) for large codebases.",
                        "default": 10
                    }
                },
                "required": ["from_function", "to_function"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    try:
        if name == "set_project_directory":
            project_path = arguments["project_path"]

            if not isinstance(project_path, str) or not project_path.strip():
                return [TextContent(type="text", text="Error: 'project_path' must be a non-empty string")]

            if project_path != project_path.strip():
                return [TextContent(type="text", text="Error: 'project_path' may not include leading or trailing whitespace")]

            project_path = project_path.strip()

            if not os.path.isabs(project_path):
                return [TextContent(type="text", text=f"Error: '{project_path}' is not an absolute path")]

            if not os.path.isdir(project_path):
                return [TextContent(type="text", text=f"Error: Directory '{project_path}' does not exist")]

            # Re-initialize analyzer with new path
            global analyzer, analyzer_initialized
            analyzer = CppAnalyzer(project_path)

            # IMPORTANT: Don't set analyzer_initialized yet - indexing must complete first
            # to prevent race condition where tools execute on partially-indexed data.
            # Note: This blocks the MCP server until indexing completes (synchronous behavior).
            # For large projects, this may take several minutes. Future enhancement: async indexing.
            indexed_count = analyzer.index_project(force=False, include_dependencies=True)

            # Only now mark as initialized - indexing is complete, tools can safely execute
            analyzer_initialized = True

            return [TextContent(type="text", text=f"Set project directory to: {project_path}\nIndexed {indexed_count} C++ files")]
        
        # Check if analyzer is initialized for all other commands
        if not analyzer_initialized or analyzer is None:
            return [TextContent(type="text", text="Error: Project directory not set. Please use 'set_project_directory' first with the path to your C++ project.")]
        
        if name == "search_classes":
            project_only = arguments.get("project_only", True)
            results = analyzer.search_classes(arguments["pattern"], project_only)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "search_functions":
            project_only = arguments.get("project_only", True)
            class_name = arguments.get("class_name", None)
            results = analyzer.search_functions(arguments["pattern"], project_only, class_name)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "get_class_info":
            result = analyzer.get_class_info(arguments["class_name"])
            if result:
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            else:
                return [TextContent(type="text", text=f"Class '{arguments['class_name']}' not found")]
        
        elif name == "get_function_signature":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", None)
            results = analyzer.get_function_signature(function_name, class_name)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "search_symbols":
            pattern = arguments["pattern"]
            project_only = arguments.get("project_only", True)
            symbol_types = arguments.get("symbol_types", None)
            results = analyzer.search_symbols(pattern, project_only, symbol_types)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "find_in_file":
            results = analyzer.find_in_file(arguments["file_path"], arguments["pattern"])
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "refresh_project":
            modified_count = analyzer.refresh_if_needed()
            return [TextContent(type="text", text=f"Refreshed project. Re-parsed {modified_count} modified/new files.")]
        
        elif name == "get_server_status":
            # Determine analyzer type
            analyzer_type = "python_enhanced"
            
            status = {
                "analyzer_type": analyzer_type,
                "call_graph_enabled": True,
                "usr_tracking_enabled": True,
                "compile_commands_enabled": analyzer.compile_commands_manager.enabled,
                "compile_commands_path": analyzer.compile_commands_manager.compile_commands_path,
                "compile_commands_cache_enabled": analyzer.compile_commands_manager.cache_enabled
            }
            
            # Add analyzer stats from enhanced Python analyzer
            status.update({
                "parsed_files": len(analyzer.translation_units),
                "indexed_classes": len(analyzer.class_index),
                "indexed_functions": len(analyzer.function_index),
                "project_files": len(analyzer.translation_units)  # Approximate count
            })
            return [TextContent(type="text", text=json.dumps(status, indent=2))]
        
        elif name == "get_class_hierarchy":
            class_name = arguments["class_name"]
            hierarchy = analyzer.get_class_hierarchy(class_name)
            if hierarchy:
                return [TextContent(type="text", text=json.dumps(hierarchy, indent=2))]
            else:
                return [TextContent(type="text", text=f"Class '{class_name}' not found")]
        
        elif name == "get_derived_classes":
            class_name = arguments["class_name"]
            project_only = arguments.get("project_only", True)
            derived = analyzer.get_derived_classes(class_name, project_only)
            return [TextContent(type="text", text=json.dumps(derived, indent=2))]
        
        elif name == "find_callers":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", "")
            results = analyzer.find_callers(function_name, class_name)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "find_callees":
            function_name = arguments["function_name"]
            class_name = arguments.get("class_name", "")
            results = analyzer.find_callees(function_name, class_name)
            return [TextContent(type="text", text=json.dumps(results, indent=2))]
        
        elif name == "get_call_path":
            from_function = arguments["from_function"]
            to_function = arguments["to_function"]
            max_depth = arguments.get("max_depth", 10)
            paths = analyzer.get_call_path(from_function, to_function, max_depth)
            return [TextContent(type="text", text=json.dumps(paths, indent=2))]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    # Import here to avoid issues if mcp package not installed
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
