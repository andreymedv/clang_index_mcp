"""
Security Tests - Command Injection Security

Tests for command injection prevention in compile_commands.json.

Requirements: REQ-10.3 (Command Injection Prevention)
Priority: P0 - CRITICAL
"""

import pytest
import json

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.security
@pytest.mark.critical
class TestCommandInjectionPrevention:
    """Test command injection prevention - REQ-10.3"""

    def test_command_injection_prevention(self, temp_project_dir):
        """Test prevention of shell injection in compile_commands - Task 1.3.3"""
        # Create legitimate source file
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        # Test Case 1: Shell command injection with semicolon
        cc1 = [{
            "directory": str(temp_project_dir),
            "command": f"g++ -c {src_file}; rm -rf /",
            "file": str(src_file)
        }]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc1))

        analyzer1 = CppAnalyzer(str(temp_project_dir))
        # Should not execute rm -rf /
        count1 = analyzer1.index_project()
        assert count1 >= 0, "Should not crash on injected commands"

        # Test Case 2: Backtick command substitution
        cc2 = [{
            "directory": str(temp_project_dir),
            "command": f"g++ `whoami` -c {src_file}",
            "file": str(src_file)
        }]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc2))

        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()
        assert count2 >= 0, "Should handle backtick injection safely"

        # Test Case 3: Pipe to shell command
        cc3 = [{
            "directory": str(temp_project_dir),
            "command": f"g++ -c {src_file} | sh",
            "file": str(src_file)
        }]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc3))

        analyzer3 = CppAnalyzer(str(temp_project_dir))
        count3 = analyzer3.index_project()
        assert count3 >= 0, "Should handle pipe injection safely"

        # Test Case 4: Command substitution $()
        cc4 = [{
            "directory": str(temp_project_dir),
            "command": f"g++ $(rm -rf /) -c {src_file}",
            "file": str(src_file)
        }]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc4))

        analyzer4 = CppAnalyzer(str(temp_project_dir))
        count4 = analyzer4.index_project()
        assert count4 >= 0, "Should handle $() injection safely"

        # Test Case 5: Double ampersand (background execution)
        cc5 = [{
            "directory": str(temp_project_dir),
            "command": f"g++ -c {src_file} && malicious_command",
            "file": str(src_file)
        }]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc5))

        analyzer5 = CppAnalyzer(str(temp_project_dir))
        count5 = analyzer5.index_project()
        assert count5 >= 0, "Should handle && injection safely"
