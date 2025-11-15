#!/usr/bin/env python3
"""
Console test script for C++ MCP Server
Allows testing MCP server functionality with a real codebase
"""

import sys
import os
import json
import asyncio
from pathlib import Path

# Add parent directory to path to import the server
sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_mcp_server(project_path: str):
    """Test the MCP server with a real codebase"""

    # Import the analyzer
    from mcp_server.cpp_analyzer import CppAnalyzer

    print("=" * 60)
    print("C++ MCP Server Console Test")
    print("=" * 60)

    # 1. Configure - Set project directory
    print(f"\n1. Configuring analyzer with project: {project_path}")
    if not os.path.isdir(project_path):
        print(f"Error: Directory '{project_path}' does not exist")
        return

    analyzer = CppAnalyzer(project_path)
    print("✓ Analyzer created")

    # 2. Analyze - Index the project
    print("\n2. Analyzing project (indexing C++ files)...")
    indexed_count = analyzer.index_project(force=False, include_dependencies=True)
    print(f"✓ Indexed {indexed_count} C++ files")

    # 3. Get server status
    print("\n3. Getting server status...")
    status = {
        "parsed_files": len(analyzer.translation_units),
        "indexed_classes": len(analyzer.class_index),
        "indexed_functions": len(analyzer.function_index),
        "indexed_symbols": len(analyzer.usr_index),
        "call_graph_size": len(analyzer.call_graph_analyzer.call_graph),
        "compile_commands_enabled": analyzer.compile_commands_manager.enabled,
        "compile_commands_path": str(analyzer.compile_commands_manager.compile_commands_path),
    }
    print(f"✓ Server status:")
    for key, value in status.items():
        print(f"   {key}: {value}")

    # 4. Search for classes
    print("\n4. Searching for classes (pattern: '.*')...")
    classes = analyzer.search_classes(".*", project_only=True)
    print(f"✓ Found {len(classes)} classes in project")
    if classes:
        print("   First 5 classes:")
        for cls in classes[:5]:
            print(f"   - {cls['name']} at {cls['file']}:{cls['line']}")

    # 5. Search for functions
    print("\n5. Searching for functions (pattern: '.*')...")
    functions = analyzer.search_functions(".*", project_only=True)
    print(f"✓ Found {len(functions)} functions in project")
    if functions:
        print("   First 5 functions:")
        for func in functions[:5]:
            print(f"   - {func['name']} at {func['file']}:{func['line']}")

    # 6. Get detailed class info (if classes exist)
    if classes:
        print(f"\n6. Getting detailed info for class: {classes[0]['name']}")
        class_info = analyzer.get_class_info(classes[0]['name'])
        if class_info:
            print(f"✓ Class info:")
            print(f"   Name: {class_info['name']}")
            print(f"   File: {class_info['file']}:{class_info['line']}")
            print(f"   Methods: {len(class_info['methods'])}")
            print(f"   Members: {len(class_info['members'])}")
            if class_info['methods']:
                print("   First 3 methods:")
                for method in class_info['methods'][:3]:
                    print(f"   - {method['name']} ({method['access']})")

    # 7. Get function signature (if functions exist)
    if functions:
        print(f"\n7. Getting signature for function: {functions[0]['name']}")
        signatures = analyzer.get_function_signature(functions[0]['name'])
        if signatures:
            print(f"✓ Found {len(signatures)} function(s) with this name:")
            for sig in signatures[:3]:
                # get_function_signature returns a list of signature strings
                print(f"   - {sig}")

    # 8. Get class hierarchy (if classes exist)
    if classes:
        print(f"\n8. Getting class hierarchy for: {classes[0]['name']}")
        hierarchy = analyzer.get_class_hierarchy(classes[0]['name'])
        if hierarchy:
            print(f"✓ Class hierarchy:")
            print(f"   Class: {hierarchy['name']}")
            if hierarchy.get('base_classes'):
                print(f"   Base classes: {', '.join(hierarchy['base_classes'])}")
            if hierarchy.get('derived_classes'):
                print(f"   Derived classes: {len(hierarchy['derived_classes'])}")

    # 9. Find callers (if functions exist)
    if functions:
        print(f"\n9. Finding callers of function: {functions[0]['name']}")
        callers = analyzer.find_callers(functions[0]['name'])
        print(f"✓ Found {len(callers)} caller(s)")
        if callers:
            print("   First 3 callers:")
            for caller in callers[:3]:
                print(f"   - {caller['name']} at {caller['file']}:{caller['line']}")

    # 10. Find callees (if functions exist)
    if functions and len(functions) > 1:
        print(f"\n10. Finding callees of function: {functions[0]['name']}")
        callees = analyzer.find_callees(functions[0]['name'])
        print(f"✓ Found {len(callees)} callee(s)")
        if callees:
            print("   First 3 callees:")
            for callee in callees[:3]:
                print(f"   - {callee['name']} at {callee['file']}:{callee['line']}")

    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)

def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python test_mcp_console.py <path-to-cpp-project>")
        print("\nExample:")
        print("  python test_mcp_console.py /path/to/your/cpp/project")
        print("  python test_mcp_console.py C:\\Users\\YourName\\MyProject")
        sys.exit(1)

    project_path = sys.argv[1]

    # Run the test
    asyncio.run(test_mcp_server(project_path))

if __name__ == "__main__":
    main()
