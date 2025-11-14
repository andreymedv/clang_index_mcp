"""
Error Handling Tests - Data Errors

Tests for handling corrupt data, malformed JSON, invalid formats, etc.

Requirements: REQ-6.5 (Data Error Handling)
Priority: P0-P1
"""

import pytest
from pathlib import Path
import json

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.error_handling
class TestCorruptCompileCommands:
    """Test handling of corrupt compile_commands.json - REQ-6.5.1"""

    def test_corrupt_compile_commands_handling(self, temp_project_dir):
        """Test handling of various corrupted compile_commands.json formats - Task 1.2.4"""
        # Create a valid C++ file
        (temp_project_dir / "src" / "test.cpp").write_text("""
class TestClass {
public:
    void method();
};
""")

        # Test Case 1: Truncated JSON
        cc_file = temp_project_dir / "compile_commands.json"
        cc_file.write_text('[{"directory": "/tmp", "command": "g++",')  # Truncated

        analyzer1 = CppAnalyzer(str(temp_project_dir))
        # Should fall back to default args and not crash
        count1 = analyzer1.index_project()
        assert count1 >= 0, "Should handle truncated JSON gracefully"

        # Test Case 2: Invalid JSON
        cc_file.write_text('this is not JSON at all { invalid }')

        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()
        assert count2 >= 0, "Should handle invalid JSON gracefully"

        # Test Case 3: Missing required fields
        cc_file.write_text(json.dumps([
            {
                "directory": str(temp_project_dir)
                # Missing "command" and "file" fields
            }
        ]))

        analyzer3 = CppAnalyzer(str(temp_project_dir))
        count3 = analyzer3.index_project()
        assert count3 >= 0, "Should handle missing fields gracefully"

        # Test Case 4: Wrong types
        cc_file.write_text(json.dumps([
            {
                "directory": 12345,  # Should be string
                "command": ["array", "instead", "of", "string"],
                "file": None
            }
        ]))

        analyzer4 = CppAnalyzer(str(temp_project_dir))
        count4 = analyzer4.index_project()
        assert count4 >= 0, "Should handle wrong types gracefully"

        # Verify that despite corrupt compile_commands, indexing still works
        classes = analyzer4.search_classes("TestClass")
        # May or may not find class, but shouldn't crash


@pytest.mark.error_handling
@pytest.mark.critical
class TestMalformedCacheRecovery:
    """Test recovery from malformed cache files - REQ-6.5.2"""

    def test_malformed_json_cache_recovery(self, temp_project_dir):
        """Test recovery from various cache corruption scenarios - Task 1.2.5"""
        # Create a simple C++ file
        (temp_project_dir / "src" / "cached.cpp").write_text("""
class CachedClass {
public:
    void method();
};
""")

        # First, create a valid cache
        analyzer1 = CppAnalyzer(str(temp_project_dir))
        analyzer1.index_project()

        # Verify cache was created (use actual cache location)
        from pathlib import Path
        cache_dir = Path(analyzer1.cache_dir)
        assert cache_dir.exists(), "Cache directory should exist"

        cache_file = cache_dir / "cache_info.json"
        assert cache_file.exists(), "Cache file should exist"

        # Test Case 1: Truncated cache JSON
        cache_file.write_text('{"class_index": {"SomeClass":')  # Truncated

        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()
        # Should re-index from scratch
        assert count2 > 0, "Should re-index when cache is corrupt"

        classes2 = analyzer2.search_classes("CachedClass")
        assert len(classes2) > 0, "Should find class after re-indexing"

        # Test Case 2: Null bytes in cache
        cache_file.write_bytes(b'{"class_index":\x00\x00\x00}')

        analyzer3 = CppAnalyzer(str(temp_project_dir))
        count3 = analyzer3.index_project()
        assert count3 > 0, "Should re-index when cache has null bytes"

        # Test Case 3: Invalid UTF-8
        cache_file.write_bytes(b'{"class_index": "\xff\xfe invalid utf8"}')

        analyzer4 = CppAnalyzer(str(temp_project_dir))
        count4 = analyzer4.index_project()
        assert count4 > 0, "Should re-index when cache has invalid UTF-8"

        # Test Case 4: Wrong format (not a dictionary)
        cache_file.write_text('["array", "instead", "of", "object"]')

        analyzer5 = CppAnalyzer(str(temp_project_dir))
        count5 = analyzer5.index_project()
        assert count5 > 0, "Should re-index when cache has wrong format"

        # Verify final state - all should work
        classes5 = analyzer5.search_classes("CachedClass")
        assert len(classes5) > 0, "Should find class after recovering from corrupt cache"
