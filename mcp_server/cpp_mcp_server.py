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

try:
    from clang.cindex import Config
except ImportError:
    print("Error: clang package not found. Install with: pip install libclang", file=sys.stderr)
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
    
    def _preload_linux_dependencies(lib_dir: str) -> None:
        """Load additional shared objects required by bundled libclang."""
        if platform.system() != "Linux":
            return

        try:
            import ctypes
        except ImportError:
            return

        for name in ("libtinfo.so.5", "libtinfo.so.5.9"):
            candidate = os.path.join(lib_dir, name)
            if os.path.exists(candidate):
                try:
                    ctypes.CDLL(candidate)
                    print(f"Preloaded dependency {candidate}", file=sys.stderr)
                    break
                except OSError as exc:
                    print(f"Warning: failed to preload {candidate}: {exc}", file=sys.stderr)

    # Try bundled libraries first
    for path in bundled_paths:
        if os.path.exists(path):
            print(f"Using bundled libclang at: {path}", file=sys.stderr)
            lib_dir = os.path.dirname(path)
            _preload_linux_dependencies(lib_dir)
            Config.set_library_file(path)
            return True
    
    print("No bundled libclang found, searching system...", file=sys.stderr)
    
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
            print(f"Found system libclang at: {path}", file=sys.stderr)
            Config.set_library_file(path)
            return True
    
    return False

# Try to find and configure libclang
if not find_and_configure_libclang():
    print("Error: Could not find libclang library.", file=sys.stderr)
    print("Please install LLVM/Clang:", file=sys.stderr)
    print("  Windows: Download from https://releases.llvm.org/", file=sys.stderr)
    print("  macOS: brew install llvm", file=sys.stderr)
    print("  Linux: sudo apt install libclang-dev", file=sys.stderr)
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
            description="Search for C++ classes by name pattern (regex supported)",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Class name pattern to search for (supports regex)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "Only search project files (exclude dependencies like vcpkg, system headers). Default: true",
                        "default": True
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="search_functions", 
            description="Search for C++ functions by name pattern (regex supported)",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Function name pattern to search for (supports regex)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "Only search project files (exclude dependencies like vcpkg, system headers). Default: true",
                        "default": True
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: search only for methods within this class"
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="get_class_info",
            description="Get detailed information about a specific class",
            inputSchema={
                "type": "object", 
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Exact class name to analyze"
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="get_function_signature",
            description="Get signature and details for functions with given name",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string", 
                        "description": "Exact function name to analyze"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: specify class name to get method signatures only from that class"
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="search_symbols",
            description="Search for all symbols (classes and functions) matching a pattern",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Pattern to search for (supports regex)"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "Only search project files (exclude dependencies). Default: true",
                        "default": True
                    },
                    "symbol_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["class", "struct", "function", "method"]
                        },
                        "description": "Types of symbols to include. If not specified, includes all types"
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="find_in_file",
            description="Search for symbols within a specific file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to file from project root"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Symbol pattern to search for in the file"
                    }
                },
                "required": ["file_path", "pattern"]
            }
        ),
        Tool(
            name="set_project_directory",
            description="Set the project directory to analyze (use this first before other commands)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the C++ project directory"
                    }
                },
                "required": ["project_path"]
            }
        ),
        Tool(
            name="refresh_project",
            description="Manually refresh/re-parse project files to detect changes",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_server_status",
            description="Get MCP server status including parsing progress and index stats",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_class_hierarchy",
            description="Get complete inheritance hierarchy for a C++ class",
            inputSchema={
                "type": "object", 
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to analyze"
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="get_derived_classes",
            description="Get all classes that inherit from a given base class",
            inputSchema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string", 
                        "description": "Name of the base class"
                    },
                    "project_only": {
                        "type": "boolean",
                        "description": "Only include project classes (exclude dependencies). Default: true",
                        "default": True
                    }
                },
                "required": ["class_name"]
            }
        ),
        Tool(
            name="find_callers",
            description="Find all functions that call a specific function",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to find callers for"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Class name if searching for a method",
                        "default": ""
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="find_callees",
            description="Find all functions called by a specific function",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to find callees for"
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Optional: Class name if searching for a method",
                        "default": ""
                    }
                },
                "required": ["function_name"]
            }
        ),
        Tool(
            name="get_call_path",
            description="Find call paths from one function to another",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_function": {
                        "type": "string",
                        "description": "Starting function name"
                    },
                    "to_function": {
                        "type": "string",
                        "description": "Target function name"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum search depth (default: 10)",
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
            analyzer_initialized = True
            
            # Start indexing in the background
            indexed_count = analyzer.index_project(force=False, include_dependencies=True)
            
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
