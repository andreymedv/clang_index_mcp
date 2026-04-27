
import json
import os
import sys
import tempfile
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
from mcp_server.cpp_mcp_server import _handle_tool_call

@pytest.mark.asyncio
async def test_cpp_analyzer_config_prioritization():
    """Test that CppAnalyzerConfig prioritizes the explicitly passed path."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # 1. Project root config (lower priority)
        project_root = tmp_path / "project"
        project_root.mkdir()
        root_config = project_root / ".cpp-analyzer-config.json"
        with open(root_config, "w") as f:
            json.dump({"max_file_size_mb": 50}, f)
            
        # 2. External config (higher priority)
        external_config = tmp_path / "external.json"
        with open(external_config, "w") as f:
            json.dump({"max_file_size_mb": 99}, f)
            
        # Initialize config with both present
        config = CppAnalyzerConfig(project_root, config_path=external_config)
        
        # Should pick external_config (99) over root_config (50)
        assert config.get_max_file_size_mb() == 99
        assert config.config_path == external_config

@pytest.mark.asyncio
async def test_hybrid_project_setup():
    """Test setting project directory via a configuration file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        # 1. Create a dummy project directory
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "main.cpp").write_text("int main() { return 0; }")
        
        # 2. Create an external configuration file
        config_file = tmp_path / "external_config.json"
        config_data = {
            "project_root": "my_project",  # Relative to config_file
            "exclude_directories": ["build"]
        }
        with open(config_file, "w") as f:
            json.dump(config_data, f)
            
        # 3. Mock dependencies in _handle_tool_call to avoid actual indexing
        with patch("mcp_server.cpp_mcp_server.CppAnalyzer") as MockAnalyzer, \
             patch("mcp_server.cpp_mcp_server.BackgroundIndexer"), \
             patch("mcp_server.cpp_mcp_server.ToolCallLogger"), \
             patch("mcp_server.cpp_mcp_server.state_manager") as mock_state_manager, \
             patch("mcp_server.cpp_mcp_server.session_manager") as mock_session_manager:
            
            # Setup mock analyzer
            mock_analyzer_instance = MockAnalyzer.return_value
            mock_analyzer_instance.cache_dir = "/tmp/fake_cache"
            mock_analyzer_instance.class_index = {}
            mock_analyzer_instance.function_index = {}
            mock_analyzer_instance.file_index = {}
            
            # Call set_project_directory with the config file path
            arguments = {
                "project_path": str(config_file.absolute()),
                "auto_refresh": True
            }
            
            from mcp_server.cpp_mcp_server import _handle_tool_call
            results = await _handle_tool_call("set_project_directory", arguments)
            
            # Verify results
            assert "Set project directory to" in results[0].text
            assert str(project_dir.absolute()) in results[0].text
            assert str(config_file.absolute()) in results[0].text
            
            # Verify MockAnalyzer was called with resolved paths
            # The first argument should be the resolved project root
            # The config_file argument should be the config file path
            args, kwargs = MockAnalyzer.call_args
            assert args[0] == str(project_dir.absolute())
            assert kwargs["config_file"] == str(config_file.absolute())

@pytest.mark.asyncio
async def test_hybrid_project_setup_invalid_root():
    """Test hybrid setup with a non-existent project_root."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        config_file = tmp_path / "bad_config.json"
        config_data = {
            "project_root": "non_existent_folder"
        }
        with open(config_file, "w") as f:
            json.dump(config_data, f)
            
        arguments = {
            "project_path": str(config_file.absolute())
        }
        
        results = await _handle_tool_call("set_project_directory", arguments)
        assert "Error: 'project_root' in config" in results[0].text
        assert "is not a directory" in results[0].text

@pytest.mark.asyncio
async def test_hybrid_project_setup_missing_field():
    """Test hybrid setup with a config file missing project_root."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
        config_file = tmp_path / "missing_field.json"
        config_data = {
            "some_other_field": "value"
        }
        with open(config_file, "w") as f:
            json.dump(config_data, f)
            
        arguments = {
            "project_path": str(config_file.absolute())
        }
        
        results = await _handle_tool_call("set_project_directory", arguments)
        assert "is missing 'project_root' field" in results[0].text
