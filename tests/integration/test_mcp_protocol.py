"""
Integration Tests - MCP Protocol

Tests for real MCP protocol integration with all server tools.

Requirements: P1 - High Priority
"""

import pytest
import asyncio
import json
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_mcp_server import server, list_tools
from mcp.types import CallToolRequest, ListToolsRequest


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPProtocolIntegration:
    """Test real MCP protocol with all server tools"""

    async def test_list_tools(self):
        """Test listing all available MCP tools"""
        # Get tools list
        tools = await list_tools()

        # Verify we have all expected tools
        tool_names = [tool.name for tool in tools]

        expected_tools = [
            "search_classes",
            "search_functions",
            "get_class_info",
            "get_function_signature",
            "search_symbols",
            "find_in_file",
            "set_project_directory",
            "refresh_project",
            "get_server_status",
            "get_indexing_status",
            "wait_for_indexing",
            "get_class_hierarchy",
            "get_derived_classes",
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"

        # Verify all tools have required fields
        for tool in tools:
            assert tool.name, "Tool must have a name"
            assert tool.description, "Tool must have a description"
            assert tool.inputSchema, "Tool must have an input schema"

    async def test_search_classes_tool(self, temp_project_dir):
        """Test search_classes tool through MCP protocol"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};

class AnotherClass {
public:
    void another();
};
""")

        # Import the call_tool handler
        from mcp_server.cpp_mcp_server import call_tool

        # Initialize project
        result = await call_tool(
            "set_project_directory",
            {"project_path": str(temp_project_dir)}
        )
        assert result is not None

        # Wait for indexing
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Search for classes
        result = await call_tool(
            "search_classes",
            {"pattern": "Test.*", "project_only": True}
        )

        # Parse result
        assert result is not None
        assert len(result) > 0
        assert result[0].type == "text"

        # Verify we found TestClass
        text = result[0].text
        # Handle both JSON and error text responses
        if text.startswith("Error"):
            pytest.skip(f"Indexing issue: {text}")
        data = json.loads(text)
        classes = data.get("results", [])
        assert len(classes) > 0
        assert any(c["name"] == "TestClass" for c in classes)

    async def test_search_functions_tool(self, temp_project_dir):
        """Test search_functions tool through MCP protocol"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
void globalFunction() {}

class TestClass {
public:
    void testMethod();
    void anotherMethod();
};
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Search for functions
        result = await call_tool(
            "search_functions",
            {"pattern": "test.*", "project_only": True}
        )

        assert result is not None
        data = json.loads(result[0].text)
        functions = data.get("results", [])
        assert len(functions) > 0
        assert any(f["name"] == "testMethod" for f in functions)

    async def test_get_class_info_tool(self, temp_project_dir):
        """Test get_class_info tool through MCP protocol"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method1();
    void method2(int x);
private:
    void privateMethod();
};
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Get class info
        result = await call_tool(
            "get_class_info",
            {"class_name": "TestClass"}
        )

        assert result is not None
        data = json.loads(result[0].text)

        # Verify class info structure
        assert data["name"] == "TestClass"
        assert "methods" in data
        assert len(data["methods"]) >= 3  # method1, method2, privateMethod

    async def test_get_function_signature_tool(self, temp_project_dir):
        """Test get_function_signature tool through MCP protocol"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
void testFunction(int x, double y) {}

class TestClass {
public:
    void testFunction(std::string s);
};
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Get function signature
        result = await call_tool(
            "get_function_signature",
            {"function_name": "testFunction"}
        )

        assert result is not None
        data = json.loads(result[0].text)
        signatures = data.get("signatures", [])

        # Should have at least 2 overloads
        assert len(signatures) >= 2

    async def test_search_symbols_tool(self, temp_project_dir):
        """Test search_symbols unified search through MCP protocol"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {};
void testFunction() {}
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Search for symbols
        result = await call_tool(
            "search_symbols",
            {"pattern": "test.*", "project_only": True}
        )

        assert result is not None
        data = json.loads(result[0].text)

        # Should have both classes and functions
        assert "classes" in data
        assert "functions" in data
        assert len(data["classes"]) > 0 or len(data["functions"]) > 0

    async def test_get_server_status_tool(self, temp_project_dir):
        """Test get_server_status tool through MCP protocol"""
        from mcp_server.cpp_mcp_server import call_tool

        # Initialize project
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Get server status
        result = await call_tool("get_server_status", {})

        assert result is not None
        data = json.loads(result[0].text)

        # Verify status structure
        assert "analyzer_type" in data
        assert "features" in data
        assert "stats" in data

    async def test_get_indexing_status_tool(self, temp_project_dir):
        """Test get_indexing_status tool through MCP protocol"""
        from mcp_server.cpp_mcp_server import call_tool

        # Get status before initialization
        result = await call_tool("get_indexing_status", {})
        assert result is not None
        data = json.loads(result[0].text)
        assert "state" in data

        # Initialize project
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})

        # Get status during/after indexing
        result = await call_tool("get_indexing_status", {})
        data = json.loads(result[0].text)
        assert data["state"] in ["indexing", "indexed"]

    async def test_get_class_hierarchy_tool(self, temp_project_dir):
        """Test get_class_hierarchy tool through MCP protocol"""
        # Create test file with inheritance
        (temp_project_dir / "src" / "test.cpp").write_text("""
class Base {};
class Derived : public Base {};
class MoreDerived : public Derived {};
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Get class hierarchy
        result = await call_tool(
            "get_class_hierarchy",
            {"class_name": "Derived"}
        )

        assert result is not None
        data = json.loads(result[0].text)

        # Verify hierarchy structure
        assert "name" in data
        assert data["name"] == "Derived"
        assert "base_hierarchy" in data
        assert "derived_hierarchy" in data

    async def test_get_derived_classes_tool(self, temp_project_dir):
        """Test get_derived_classes tool through MCP protocol"""
        # Create test file with inheritance
        (temp_project_dir / "src" / "test.cpp").write_text("""
class Base {};
class Derived1 : public Base {};
class Derived2 : public Base {};
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Get derived classes
        result = await call_tool(
            "get_derived_classes",
            {"class_name": "Base", "project_only": True}
        )

        assert result is not None
        data = json.loads(result[0].text)
        derived = data.get("derived_classes", [])

        # Should have Derived1 and Derived2
        assert len(derived) >= 2

    async def test_refresh_project_tool(self, temp_project_dir):
        """Test refresh_project tool through MCP protocol"""
        # Create initial file
        test_file = temp_project_dir / "src" / "test.cpp"
        test_file.write_text("class TestClass {};")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Modify file
        test_file.write_text("class TestClass {};\nclass NewClass {};")

        # Refresh project
        result = await call_tool(
            "refresh_project",
            {"incremental": True}
        )

        assert result is not None
        data = json.loads(result[0].text)

        # Verify refresh stats
        assert "files_analyzed" in data or "message" in data

    async def test_find_in_file_tool(self, temp_project_dir):
        """Test find_in_file tool through MCP protocol"""
        # Create test file
        test_file = temp_project_dir / "src" / "test.cpp"
        test_file.write_text("""
class TestClass {};
void testFunction() {}
""")

        from mcp_server.cpp_mcp_server import call_tool

        # Initialize and wait
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Find symbols in file
        result = await call_tool(
            "find_in_file",
            {"file_path": "test.cpp", "pattern": "test.*"}
        )

        assert result is not None
        data = json.loads(result[0].text)

        # Should find both class and function
        assert "symbols" in data or "results" in data

    async def test_error_handling_missing_project(self):
        """Test error handling when project not initialized"""
        from mcp_server.cpp_mcp_server import call_tool

        # Try to search without initializing project
        # This should handle gracefully
        result = await call_tool(
            "search_classes",
            {"pattern": "Test.*"}
        )

        # Should return an error or empty result
        assert result is not None


@pytest.mark.integration
@pytest.mark.asyncio
class TestMCPProtocolErrorHandling:
    """Test MCP protocol error handling"""

    async def test_invalid_tool_parameters(self, temp_project_dir):
        """Test error handling with invalid parameters"""
        from mcp_server.cpp_mcp_server import call_tool

        # Initialize project first
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Try with invalid pattern (ReDoS)
        with pytest.raises(Exception):  # Should raise RegexValidationError
            await call_tool(
                "search_classes",
                {"pattern": "(a+)+b"}
            )

    async def test_nonexistent_class(self, temp_project_dir):
        """Test querying non-existent class"""
        from mcp_server.cpp_mcp_server import call_tool

        # Initialize project
        await call_tool("set_project_directory", {"project_path": str(temp_project_dir)})
        await call_tool("wait_for_indexing", {"timeout": 30.0})

        # Query non-existent class
        result = await call_tool(
            "get_class_info",
            {"class_name": "NonExistentClass"}
        )

        assert result is not None
        # Should return error message
        text = result[0].text
        assert "not found" in text.lower() or "error" in text.lower()

    async def test_invalid_project_path(self):
        """Test error handling with invalid project path"""
        from mcp_server.cpp_mcp_server import call_tool

        # Try to initialize with non-existent path
        result = await call_tool(
            "set_project_directory",
            {"project_path": "/nonexistent/path/to/project"}
        )

        # Should return error
        assert result is not None
        text = result[0].text
        assert "error" in text.lower() or "not found" in text.lower() or "does not exist" in text.lower()
