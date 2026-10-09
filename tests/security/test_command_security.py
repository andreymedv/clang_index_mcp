"""
Security Tests - Command Injection Security

Tests for command injection prevention in compile_commands.json.

Requirements: REQ-10.3 (Command Injection Prevention)
Priority: P0 - CRITICAL
"""

import json
import os

# Import test infrastructure
import sys

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from clang_index_mcp.cpp_analyzer import CppAnalyzer


@pytest.mark.security
@pytest.mark.critical
class TestCommandInjectionPrevention:
    """Test command injection prevention - REQ-10.3"""

    def test_semicolon_injection_not_executed(self, temp_project_dir):
        """Verify semicolon-separated shell commands are not executed.

        Security requirement: Shell metacharacters in compile_commands.json
        'command' field must be parsed as compiler arguments, not interpreted
        by a shell. The injected 'rm -rf /' must never execute.
        """
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        sentinel = temp_project_dir / "cmd_inject_semicolon.txt"
        assert not sentinel.exists()

        cc = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ -c {src_file}; touch {sentinel}",
                "file": str(src_file),
            }
        ]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc))

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0

        # Security assertion: the injected command must NOT have executed
        assert not sentinel.exists(), (
            "Shell injection via semicolon executed: sentinel file was created"
        )

        analyzer.close()

    def test_backtick_substitution_not_executed(self, temp_project_dir):
        """Verify backtick command substitution is not executed.

        Security requirement: Backtick-enclosed expressions in compile arguments
        must be treated as literal strings, not as command substitution.
        """
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        sentinel = temp_project_dir / "cmd_inject_backtick.txt"
        assert not sentinel.exists()

        cc = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ `touch {sentinel}` -c {src_file}",
                "file": str(src_file),
            }
        ]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc))

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0

        # Security assertion: backtick command substitution must NOT execute.
        # If shell interpretation occurred, the sentinel would be created.
        assert not sentinel.exists(), (
            "Shell injection via backticks executed: sentinel file was created"
        )

        analyzer.close()

    def test_pipe_to_shell_not_executed(self, temp_project_dir):
        """Verify pipe operators are not interpreted by a shell.

        Security requirement: Pipe characters in compile commands must be
        treated as literal argument text, not as shell pipe operators.
        """
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        sentinel = temp_project_dir / "cmd_inject_pipe.txt"
        assert not sentinel.exists()

        cc = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ -c {src_file} | touch {sentinel}",
                "file": str(src_file),
            }
        ]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc))

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0

        # Security assertion: pipe must not execute shell command
        assert not sentinel.exists(), (
            "Shell injection via pipe executed: sentinel file was created"
        )

        analyzer.close()

    def test_dollar_command_substitution_not_executed(self, temp_project_dir):
        """Verify $() command substitution is not executed.

        Security requirement: Dollar-paren expressions in compile arguments
        must be treated as literal strings, not as command substitution.
        """
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        sentinel = temp_project_dir / "cmd_inject_dollar.txt"
        assert not sentinel.exists()

        cc = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ $(touch {sentinel}) -c {src_file}",
                "file": str(src_file),
            }
        ]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc))

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0

        # Security assertion: $() command substitution must not execute
        assert not sentinel.exists(), (
            "Shell injection via $() executed: sentinel file was created"
        )

        analyzer.close()

    def test_double_ampersand_not_executed(self, temp_project_dir):
        """Verify && operators are not interpreted by a shell.

        Security requirement: Logical AND operators in compile commands must
        be treated as literal argument text, not as shell command chaining.
        """
        src_file = temp_project_dir / "src" / "test.cpp"
        src_file.write_text("class Test {};")

        sentinel = temp_project_dir / "cmd_inject_ampersand.txt"
        assert not sentinel.exists()

        cc = [
            {
                "directory": str(temp_project_dir),
                "command": f"g++ -c {src_file} && touch {sentinel}",
                "file": str(src_file),
            }
        ]
        (temp_project_dir / "compile_commands.json").write_text(json.dumps(cc))

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()
        assert count >= 0

        # Security assertion: && chaining must not execute the second command
        assert not sentinel.exists(), (
            "Shell injection via && executed: sentinel file was created"
        )

        analyzer.close()