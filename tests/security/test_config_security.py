"""
Security Tests - Configuration Security

Tests for malicious configuration values.

Requirements: REQ-10.4 (Config Security)
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
class TestMaliciousConfigValues:
    """Test handling of malicious config values - REQ-10.4"""

    def test_integer_overflow_in_max_file_size(self, temp_project_dir):
        """Verify integer overflow values in max_file_size don't crash the analyzer.

        Security requirement: Extreme numeric values in config must be handled
        gracefully without integer overflow, memory exhaustion, or denial of service.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        config = {"max_file_size_mb": 999999999999999999999999999}
        config_file = temp_project_dir / "malicious_config.json"
        config_file.write_text(json.dumps(config))

        # Load the malicious config via config_file parameter
        analyzer = CppAnalyzer(str(temp_project_dir), config_file=str(config_file))
        count = analyzer.index_project()

        # Verify: analyzer handled the extreme value and still produced results
        assert count >= 0
        assert analyzer.config.get_max_file_size_mb() == 999999999999999999999999999

        analyzer.close()

    def test_negative_config_values_sanitized(self, temp_project_dir):
        """Verify negative values for numeric config keys are rejected/sanitized.

        Security requirement: Negative worker counts must not be accepted.
        The config layer should sanitize invalid values to safe defaults
        to prevent resource abuse or undefined behavior.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        config = {"max_workers": -100, "max_file_size_mb": -999}
        config_file = temp_project_dir / "malicious_config.json"
        config_file.write_text(json.dumps(config))

        analyzer = CppAnalyzer(str(temp_project_dir), config_file=str(config_file))

        # Security assertion: negative max_workers must be sanitized to None
        # (see CppAnalyzerConfig.get_max_workers: checks value > 0)
        workers = analyzer.config.get_max_workers()
        assert workers is None, (
            f"Negative max_workers (-100) must be sanitized to None, got {workers}"
        )

        # Indexing must still succeed with sanitized config
        count = analyzer.index_project()
        assert count >= 0

        analyzer.close()

    def test_path_traversal_in_exclude_directories(self, temp_project_dir):
        """Verify path traversal values in exclude_directories don't escape the project.

        Security requirement: exclude_directories entries containing traversal
        sequences (../, absolute paths outside project) must not cause the analyzer
        to access or leak files outside the project root.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        traversal_paths = ["../../../etc", "/etc/passwd", "../../.."]
        config = {"exclude_directories": traversal_paths}
        config_file = temp_project_dir / "malicious_config.json"
        config_file.write_text(json.dumps(config))

        analyzer = CppAnalyzer(str(temp_project_dir), config_file=str(config_file))

        # Security assertion: config should not allow traversal outside project root.
        # Verify the project_root is respected as a boundary by checking indexed
        # files are within the project.
        count = analyzer.index_project()
        assert count >= 0

        # Verify no file outside the project was indexed by checking that
        # searching for symbols doesn't return results from system files
        results = analyzer.search_classes(".*", project_only=True)
        if isinstance(results, tuple):
            results = results[0]
        for result in results:
            file_path = result.get("file", "")
            if file_path:
                assert not file_path.startswith("/etc"), (
                    f"Traversal attack: symbol from /etc found in index: {file_path}"
                )
                assert not file_path.startswith("/root"), (
                    f"Traversal attack: symbol from /root found in index: {file_path}"
                )

        analyzer.close()

    def test_command_injection_in_compile_commands_path(self, temp_project_dir):
        """Verify command injection in compile_commands_path is not shell-executed.

        Security requirement: The compile_commands_path config value must be treated
        as a filesystem path, never passed to a shell for execution. Injection
        payloads (semicolons, pipes, backticks) must be inert.
        """
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        # Create a sentinel file that would be created if shell injection succeeded
        sentinel = temp_project_dir / "injection_test_sentinel.txt"
        assert not sentinel.exists(), "Sentinel should not exist before test"

        injection_path = f"file.json; touch {sentinel}"
        config = {"compile_commands": {"compile_commands_path": injection_path}}
        config_file = temp_project_dir / "malicious_config.json"
        config_file.write_text(json.dumps(config))

        analyzer = CppAnalyzer(str(temp_project_dir), config_file=str(config_file))

        # Security assertion: the injection path must NOT be shell-executed.
        # If it were, the sentinel file would be created.
        assert not sentinel.exists(), (
            "Shell injection succeeded: sentinel file was created via compile_commands_path"
        )

        # Analyzer should still function (indexing may fail gracefully due to
        # missing compile_commands.json, but no shell command should execute)
        count = analyzer.index_project()
        assert count >= 0

        # Sentinel must still not exist after indexing
        assert not sentinel.exists(), (
            "Shell injection during indexing: sentinel file was created"
        )

        analyzer.close()