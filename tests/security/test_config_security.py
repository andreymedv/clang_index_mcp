"""
Security Tests - Configuration Security

Tests for malicious configuration values.

Requirements: REQ-10.4 (Config Security)
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
class TestMaliciousConfigValues:
    """Test handling of malicious config values - REQ-10.4"""

    def test_malicious_config_values(self, temp_project_dir):
        """Test prevention of malicious configuration values - Task 1.3.5"""
        # Create test file
        (temp_project_dir / "src" / "test.cpp").write_text("class Test {};")

        # Test Case 1: Integer overflow in max_file_size
        config1 = {
            "max_file_size": 999999999999999999999999999
        }
        (temp_project_dir / ".clang_index_config.json").write_text(json.dumps(config1))

        analyzer1 = CppAnalyzer(str(temp_project_dir))
        count1 = analyzer1.index_project()
        assert count1 >= 0, "Should handle integer overflow in config"

        # Test Case 2: Negative values
        config2 = {
            "max_workers": -100,
            "cache_size": -999
        }
        (temp_project_dir / ".clang_index_config.json").write_text(json.dumps(config2))

        analyzer2 = CppAnalyzer(str(temp_project_dir))
        count2 = analyzer2.index_project()
        assert count2 >= 0, "Should handle negative values in config"

        # Test Case 3: Path traversal in exclude_directories
        config3 = {
            "exclude_directories": ["../../../etc", "/etc/passwd", "../../.."]
        }
        (temp_project_dir / ".clang_index_config.json").write_text(json.dumps(config3))

        analyzer3 = CppAnalyzer(str(temp_project_dir))
        count3 = analyzer3.index_project()
        assert count3 >= 0, "Should handle path traversal in exclude dirs"

        # Test Case 4: Command injection in compile_commands_path
        config4 = {
            "compile_commands": {
                "compile_commands_path": "file.json; rm -rf /"
            }
        }
        (temp_project_dir / ".clang_index_config.json").write_text(json.dumps(config4))

        analyzer4 = CppAnalyzer(str(temp_project_dir))
        count4 = analyzer4.index_project()
        assert count4 >= 0, "Should handle injection in compile_commands_path"

        # Cleanup
        config_file = temp_project_dir / ".clang_index_config.json"
        if config_file.exists():
            config_file.unlink()
