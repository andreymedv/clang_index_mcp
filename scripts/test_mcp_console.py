#!/usr/bin/env python3
"""
Console test script for C++ MCP Server
Allows testing MCP server functionality with a real codebase

Interrupt Handling:
- Press Ctrl-C ONCE during indexing for clean shutdown
- Pressing Ctrl-C multiple times will forcefully terminate worker processes
  and may show stack traces (this is expected for forceful termination)
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import the server
sys.path.insert(0, str(Path(__file__).parent.parent))

# Global analyzer reference for cleanup
_analyzer = None


def test_clang_index_mcp(project_path: str, config_file: str | None = None):
    """Test the MCP server with a real codebase"""

    # Configure libclang exactly like production MCP server
    from clang_index_mcp._core.libclang_setup import configure_libclang, get_libclang_runtime_info

    if not configure_libclang():
        print("Error: Could not find libclang library")
        return
    print(f"[OK] libclang runtime config: {get_libclang_runtime_info()}")

    # Import the analyzer after libclang setup
    from clang_index_mcp.cpp_analyzer import CppAnalyzer

    print("=" * 60)
    print("C++ MCP Server Console Test")
    print("=" * 60)

    # 1. Configure - Set project directory
    print(f"\n1. Configuring analyzer with project: {project_path}")
    if config_file:
        print(f"   Using configuration file: {config_file}")

    if not os.path.isdir(project_path):
        print(f"Error: Directory '{project_path}' does not exist")
        return

    global _analyzer
    analyzer = CppAnalyzer(project_path, config_file=config_file)
    _analyzer = analyzer
    print("[OK] Analyzer created")

    # 2. Analyze - Index the project
    print("\n2. Analyzing project (indexing C++ files)...")
    indexed_count = analyzer.index_project(force=False, include_dependencies=True)
    print(f"[OK] Indexed {indexed_count} C++ files")

    # 3. Get server status
    print("\n3. Getting server status...")

    # Phase 4: Task 4.3 - call_graph dict removed, query SQLite for count
    call_sites_count = 0
    total_symbols = 0
    if analyzer.cache_manager and analyzer.cache_manager.backend:
        from clang_index_mcp._persistence.sqlite_cache_backend import SqliteCacheBackend

        assert type(analyzer.cache_manager.backend) is SqliteCacheBackend
        assert analyzer.cache_manager.backend.conn is not None
        try:
            # Query SQLite for total call sites count
            cursor = analyzer.cache_manager.backend.conn.execute("SELECT COUNT(*) FROM call_sites")
            call_sites_count = cursor.fetchone()[0]
            cursor = analyzer.cache_manager.backend.conn.execute("SELECT COUNT(*) FROM symbols")
            total_symbols = cursor.fetchone()[0]
        except Exception:
            call_sites_count = 0  # Silently ignore if table doesn't exist
            total_symbols = 0

    stats = analyzer.get_stats()
    status = {
        "parsed_files": stats.get("file_count", 0),
        "indexed_classes": stats.get("class_count", 0),
        "indexed_functions": stats.get("function_count", 0),
        "indexed_symbols": total_symbols,
        "call_sites_count": call_sites_count,  # Phase 4: Query SQLite instead
        "compile_commands_enabled": analyzer.context.is_compile_commands_enabled(),
        "compile_commands_path": "",
    }

    ccm = analyzer.context.compile_commands_manager
    if ccm is not None:
        status["compile_commands_path"] = str(ccm.compile_commands_path)

    print("[OK] Server status:")
    for key, value in status.items():
        print(f"   {key}: {value}")

    # 3.1. Show compile args profile for a sample file
    if ccm is not None:
        source_files = ccm.get_all_files()
        if source_files:
            profile = ccm.get_compile_arg_profile(Path(source_files[0]))
            print("   compile_arg_profile(sample):")
            print(f"      file: {profile['file']}")
            print(f"      args_source: {profile['args_source']}")
            print(f"      cxx_standards: {profile['cxx_standards']}")
            print(f"      system_include_dirs: {profile['system_include_dirs']}")

    # 4. Search for classes
    print("\n4. Searching for classes (pattern: '.*')...")
    classes = analyzer.search_classes(".*", project_only=True)
    assert type(classes) is list
    print(f"[OK] Found {len(classes)} classes in project")
    if classes:
        print("   First 5 classes:")
        for cls in classes[:5]:
            name = cls.get("qualified_name") or cls.get("name")
            loc = cls.get("definition") or cls.get("declaration")
            loc_str = f"{loc['file']}:{loc['line']}" if loc else "unknown"
            print(f"   - {name} at {loc_str}")

    # 5. Search for functions
    print("\n5. Searching for functions (pattern: '.*')...")
    functions = analyzer.search_functions(".*", project_only=True)
    assert type(functions) is list
    print(f"[OK] Found {len(functions)} functions in project")
    if functions:
        print("   First 5 functions:")
        for func in functions[:5]:
            assert type(func) is dict
            name = func.get("qualified_name") or func.get("name")
            loc = func.get("definition") or func.get("declaration")
            loc_str = f"{loc['file']}:{loc['line']}" if loc else "unknown"
            print(f"   - {name} at {loc_str}")

    # 6. Get detailed class info (if classes exist)
    if classes:
        cls_name = classes[0].get("qualified_name") or classes[0].get("name")
        assert type(cls_name) is str
        print(f"\n6. Getting detailed info for class: {cls_name}")
        class_info = analyzer.get_class_info(cls_name)
        if class_info:
            print("[OK] Class info:")
            print(f"   Name: {class_info.get('qualified_name') or class_info.get('name')}")
            loc = class_info.get("definition") or class_info.get("declaration")
            loc_str = f"{loc['file']}:{loc['line']}" if loc else "unknown"
            print(f"   File: {loc_str}")
            print(f"   Methods: {len(class_info.get('methods', []))}")
            print(f"   Members: {len(class_info.get('members', []))}")
            if class_info.get("methods"):
                print("   First 3 methods:")
                for method in class_info["methods"][:3]:
                    method_name = (
                        method.get("qualified_name")
                        or method.get("name")
                        or method.get("prototype", "unknown")
                    )
                    method_access = method.get("access", "unknown")
                    print(f"   - {method_name} ({method_access})")

    # 7. Get function signature (if functions exist)
    if functions:
        func_name = functions[0].get("qualified_name") or functions[0].get("name")
        assert type(func_name) is str
        print(f"\n7. Getting signature for function: {func_name}")
        signatures = analyzer.get_function_signature(func_name)
        if signatures:
            print(f"[OK] Found {len(signatures)} function(s) with this name:")
            for sig in signatures[:3]:
                # get_function_signature returns a list of signature strings
                print(f"   - {sig}")

    # 8. Get class hierarchy (if classes exist)
    if classes:
        cls_name = classes[0].get("qualified_name") or classes[0].get("name")
        assert type(cls_name) is str
        print(f"\n8. Getting class hierarchy for: {cls_name}")
        hierarchy = analyzer.get_class_hierarchy(cls_name)
        if hierarchy and "queried_class" in hierarchy:
            print("[OK] Class hierarchy:")
            queried_cls = hierarchy["queried_class"]
            print(f"   Class: {queried_cls}")

            # hierarchy["classes"] contains detailed info for each class in the graph
            if "classes" in hierarchy and queried_cls in hierarchy["classes"]:
                cls_data = hierarchy["classes"][queried_cls]
                if cls_data.get("base_classes"):
                    print(f"   Base classes: {', '.join(cls_data['base_classes'])}")
                if cls_data.get("derived_classes"):
                    print(f"   Derived classes: {len(cls_data['derived_classes'])}")

    # 9. Find callers (if functions exist)
    if functions:
        func_name = functions[0].get("qualified_name") or functions[0].get("name")
        assert type(func_name) is str
        print(f"\n9. Finding callers of function: {func_name}")
        callers_result = analyzer.find_incoming_calls(func_name)
        callers_list = callers_result.get("callers", [])
        print(f"[OK] Found {len(callers_list)} caller(s)")
        if callers_list:
            print("   First 3 callers:")
            for caller in callers_list[:3]:
                name = caller.get("qualified_name") or caller.get("name")
                loc = caller.get("definition") or caller.get("declaration")
                loc_str = f"{loc['file']}:{loc['line']}" if loc else "unknown"
                print(f"   - {name} at {loc_str}")

    # 10. Find callees (if functions exist)
    if functions and len(functions) > 1:
        func_name = functions[0].get("qualified_name") or functions[0].get("name")
        assert type(func_name) is str
        print(f"\n10. Finding callees of function: {func_name}")
        callees_result = analyzer.find_callees(func_name)
        callees_list = callees_result.get("callees", [])
        print(f"[OK] Found {len(callees_list)} callee(s)")
        if callees_list:
            print("   First 3 callees:")
            for callee in callees_list[:3]:
                name = callee.get("qualified_name") or callee.get("name")
                loc = callee.get("definition") or callee.get("declaration")
                loc_str = f"{loc['file']}:{loc['line']}" if loc else "unknown"
                print(f"   - {name} at {loc_str}")

    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python test_mcp_console.py <path-to-cpp-project> OR <path-to-config.json>")
        print("\nExample:")
        print("  python test_mcp_console.py /path/to/your/cpp/project")
        print("  python test_mcp_console.py /path/to/my-config.json")
        sys.exit(1)

    path_arg = sys.argv[1]
    project_path = None
    config_file = None

    if os.path.isfile(path_arg) and path_arg.endswith(".json"):
        import json

        config_file = os.path.abspath(path_arg)
        try:
            with open(config_file, "r") as f:
                config_data = json.load(f)
            config_root = config_data.get("project_root")
            if not config_root:
                print(f"Error: Config file {config_file} missing 'project_root'", file=sys.stderr)
                sys.exit(1)

            config_dir = os.path.dirname(config_file)
            project_path = os.path.abspath(os.path.join(config_dir, config_root))
        except Exception as e:
            print(f"Error reading config file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        project_path = path_arg

    try:
        # Run the test
        test_clang_index_mcp(project_path, config_file=config_file)
    except KeyboardInterrupt:
        # Handle Ctrl-C gracefully
        print("\n\nInterrupted by user (Ctrl-C)", file=sys.stderr)
        print("Cleaning up...", file=sys.stderr)
    finally:
        # Ensure analyzer is closed (if _analyzer was set globally)
        if _analyzer is not None:
            try:
                _analyzer.close()
                print("Analyzer closed successfully", file=sys.stderr)
            except Exception as e:
                print(f"Error closing analyzer: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
