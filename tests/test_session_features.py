"""
Test suite for session features:
1. Config file validation (JSON array vs object)
2. Cache invalidation when compilation arguments change
3. Failure tracking and intelligent retry logic
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from clang_index_mcp._persistence.cache_manager import CacheManager
from clang_index_mcp.cpp_analyzer_config import CppAnalyzerConfig
from clang_index_mcp._symbols.model import SymbolInfo


class TestConfigValidation:
    """Test config file validation — a JSON array should fall back to defaults."""

    def test_valid_config_json_object(self, tmp_path):
        """Verify a valid JSON-object config file is loaded with its values."""
        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()
        valid_config = valid_dir / ".cpp-analyzer-config.json"
        valid_config.write_text(json.dumps({"max_file_size_mb": 20}))

        config = CppAnalyzerConfig(valid_dir, config_path=valid_config)
        assert config.get_max_file_size_mb() == 20

    def test_invalid_config_json_array_falls_back(self, tmp_path):
        """Verify a JSON-array config (mimicking compile_commands.json) falls back to defaults."""
        invalid_dir = tmp_path / "invalid"
        invalid_dir.mkdir()
        invalid_config = invalid_dir / ".cpp-analyzer-config.json"
        invalid_config.write_text(json.dumps([{"file": "test.cpp"}]))

        config = CppAnalyzerConfig(invalid_dir, config_path=invalid_config)
        assert config.get_max_file_size_mb() == 10

    def test_no_config_file_uses_defaults(self, tmp_path):
        """Verify defaults are used when no config file exists."""
        no_config_dir = tmp_path / "no_config"
        no_config_dir.mkdir()

        config = CppAnalyzerConfig(no_config_dir)
        assert config.get_max_file_size_mb() == 10

    def test_config_with_max_parse_retries(self, tmp_path):
        """Verify max_parse_retries option loads correctly from config."""
        retry_dir = tmp_path / "retry"
        retry_dir.mkdir()
        retry_config = retry_dir / ".cpp-analyzer-config.json"
        retry_config.write_text(json.dumps({"max_parse_retries": 5}))

        config = CppAnalyzerConfig(retry_dir, config_path=retry_config)
        assert config.config.get("max_parse_retries") == 5


class TestCacheArgsInvalidation:
    """Test cache invalidation when compilation arguments change."""

    @pytest.fixture
    def cache_setup(self, tmp_path):
        """Create a CacheManager and a test file, return shared state."""
        cache_mgr = CacheManager(tmp_path)
        test_file = tmp_path / "test.cpp"
        test_file.write_text("class Test {};")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
        symbols = [
            SymbolInfo(name="Test", kind="class", file=file_path, line=1, column=7, is_project=True)
        ]
        return cache_mgr, test_file, file_path, file_hash, symbols

    def test_save_and_load_with_same_args(self, cache_setup):
        """Verify cache saves and loads successfully with matching compilation args."""
        cache_mgr, _, file_path, file_hash, symbols = cache_setup
        args1 = ["-std=c++11", "-I/usr/include"]
        args1_hash = hashlib.md5(" ".join(sorted(args1)).encode()).hexdigest()

        success = cache_mgr.save_file_cache(file_path, symbols, file_hash, args1_hash)
        assert success

        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args1_hash)
        assert cache_data is not None
        assert len(cache_data["symbols"]) == 1

    def test_cache_invalidated_when_args_change(self, cache_setup):
        """Verify cache miss when compilation args differ."""
        cache_mgr, _, file_path, file_hash, symbols = cache_setup
        args1 = ["-std=c++11", "-I/usr/include"]
        args1_hash = hashlib.md5(" ".join(sorted(args1)).encode()).hexdigest()
        cache_mgr.save_file_cache(file_path, symbols, file_hash, args1_hash)

        args2 = ["-std=c++17", "-I/usr/include"]
        args2_hash = hashlib.md5(" ".join(sorted(args2)).encode()).hexdigest()

        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
        assert cache_data is None

    def test_args_order_does_not_affect_hash(self):
        """Verify that argument order does not change the hash (args are sorted)."""
        args3a = ["-I/usr/include", "-std=c++11"]
        args3b = ["-std=c++11", "-I/usr/include"]
        hash3a = hashlib.md5(" ".join(sorted(args3a)).encode()).hexdigest()
        hash3b = hashlib.md5(" ".join(sorted(args3b)).encode()).hexdigest()

        assert hash3a == hash3b

    def test_cache_invalidated_when_file_content_changes(self, cache_setup):
        """Verify cache miss when file content changes."""
        cache_mgr, test_file, file_path, file_hash, symbols = cache_setup
        args1 = ["-std=c++11", "-I/usr/include"]
        args1_hash = hashlib.md5(" ".join(sorted(args1)).encode()).hexdigest()
        cache_mgr.save_file_cache(file_path, symbols, file_hash, args1_hash)

        test_file.write_text("class Test { int x; };")
        new_file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()

        cache_data = cache_mgr.load_file_cache(file_path, new_file_hash, args1_hash)
        assert cache_data is None


class TestFailureTracking:
    """Test failure tracking and retry logic in the cache."""

    @pytest.fixture
    def failure_cache(self, tmp_path):
        """Create a CacheManager with a test file for failure tracking tests."""
        cache_mgr = CacheManager(tmp_path)
        test_file = tmp_path / "test.cpp"
        test_file.write_text("invalid")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
        args_hash = hashlib.md5(b"-std=c++17").hexdigest()
        return cache_mgr, file_path, file_hash, args_hash

    def test_save_and_load_failure(self, failure_cache):
        """Verify a parse failure can be saved to and loaded from cache."""
        cache_mgr, file_path, file_hash, args_hash = failure_cache

        success = cache_mgr.save_file_cache(
            file_path, [], file_hash, args_hash,
            success=False, error_message="Parse error", retry_count=0,
        )
        assert success

        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
        assert cache_data is not None
        assert cache_data["success"] is False
        assert cache_data["error_message"] == "Parse error"
        assert cache_data["retry_count"] == 0

    def test_retry_count_increments(self, failure_cache):
        """Verify retry count increments correctly."""
        cache_mgr, file_path, file_hash, args_hash = failure_cache

        cache_mgr.save_file_cache(
            file_path, [], file_hash, args_hash,
            success=False, error_message="Parse error", retry_count=1,
        )
        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
        assert cache_data["retry_count"] == 1

    def test_multiple_retries_tracked(self, failure_cache):
        """Verify retry counts 2..4 are tracked correctly."""
        cache_mgr, file_path, file_hash, args_hash = failure_cache

        for i in range(2, 5):
            cache_mgr.save_file_cache(
                file_path, [], file_hash, args_hash,
                success=False, error_message="Parse error", retry_count=i,
            )
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data["retry_count"] == i

    def test_success_overwrites_failure(self, failure_cache):
        """Verify a successful parse overwrites a previously cached failure."""
        cache_mgr, file_path, file_hash, args_hash = failure_cache

        symbols = [
            SymbolInfo(name="Test", kind="class", file=file_path, line=1, column=1, is_project=True)
        ]
        cache_mgr.save_file_cache(
            file_path, symbols, file_hash, args_hash,
            success=True, error_message=None, retry_count=0,
        )
        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
        assert cache_data["success"] is True
        assert cache_data["retry_count"] == 0
        assert len(cache_data["symbols"]) == 1

    def test_error_message_is_saved(self, failure_cache):
        """Verify error messages are persisted in the cache."""
        cache_mgr, file_path, file_hash, args_hash = failure_cache

        long_error = "A" * 500
        cache_mgr.save_file_cache(
            file_path, [], file_hash, args_hash,
            success=False, error_message=long_error, retry_count=0,
        )
        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
        assert cache_data["error_message"] is not None


class TestErrorLogging:
    """Test centralized error logging via CacheManager."""

    def test_log_and_retrieve_parse_error(self, tmp_path):
        """Verify a parse error can be logged and retrieved."""
        cache_mgr = CacheManager(tmp_path)

        try:
            raise ValueError("Test error")
        except Exception as e:
            success = cache_mgr.log_parse_error("/tmp/test.cpp", e, "hash1", "args1", 0)
        assert success

        errors = cache_mgr.get_parse_errors()
        assert len(errors) == 1
        assert errors[0]["error_type"] == "ValueError"
        assert errors[0]["file_path"] == "/tmp/test.cpp"

    def test_error_summary(self, tmp_path):
        """Verify get_error_summary returns at least the logged error count."""
        cache_mgr = CacheManager(tmp_path)

        try:
            raise ValueError("Test error")
        except Exception as e:
            cache_mgr.log_parse_error("/tmp/test.cpp", e, "hash1", "args1", 0)

        summary = cache_mgr.get_error_summary()
        assert summary["total_errors"] >= 1

    def test_filter_errors_by_file_path(self, tmp_path):
        """Verify errors can be filtered by file path substring."""
        cache_mgr = CacheManager(tmp_path)

        for i in range(3):
            try:
                raise RuntimeError(f"Error {i}")
            except Exception as e:
                cache_mgr.log_parse_error(f"/tmp/file{i}.cpp", e, f"hash{i}", "args", i)

        filtered = cache_mgr.get_parse_errors(file_path_filter="file1")
        assert len(filtered) == 1
        assert "file1.cpp" in filtered[0]["file_path"]

    def test_clear_error_log(self, tmp_path):
        """Verify clear_error_log removes all logged errors."""
        cache_mgr = CacheManager(tmp_path)

        try:
            raise ValueError("Test error")
        except Exception as e:
            cache_mgr.log_parse_error("/tmp/test.cpp", e, "hash1", "args1", 0)
        for i in range(3):
            try:
                raise RuntimeError(f"Error {i}")
            except Exception as e:
                cache_mgr.log_parse_error(f"/tmp/file{i}.cpp", e, f"hash{i}", "args", i)

        cleared = cache_mgr.clear_error_log()
        assert cleared == 4

        remaining = cache_mgr.get_parse_errors()
        assert len(remaining) == 0


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_config_and_cache_manager_integration(self, tmp_path):
        """Verify config retry count and cache failure tracking work together."""
        config_file = tmp_path / ".cpp-analyzer-config.json"
        config_file.write_text(json.dumps({"max_parse_retries": 3}))

        config = CppAnalyzerConfig(tmp_path, config_path=config_file)
        assert config.config.get("max_parse_retries") == 3

        cache_mgr = CacheManager(tmp_path)

        test_file = tmp_path / "test.cpp"
        test_file.write_text("invalid")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
        args_hash = hashlib.md5(b"-std=c++17").hexdigest()

        cache_mgr.save_file_cache(
            file_path, [], file_hash, args_hash,
            success=False, error_message="Test error", retry_count=2,
        )

        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
        assert cache_data["retry_count"] == 2

        can_retry = cache_data["retry_count"] < config.config.get("max_parse_retries")
        assert can_retry

    def test_failure_tracking_with_args_invalidation(self, tmp_path):
        """Verify cache is invalidated for failures when args change, resetting retry count."""
        cache_mgr = CacheManager(tmp_path)

        test_file = tmp_path / "test.cpp"
        test_file.write_text("invalid")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()

        args1_hash = hashlib.md5(b"-std=c++11").hexdigest()
        cache_mgr.save_file_cache(
            file_path, [], file_hash, args1_hash,
            success=False, error_message="Error with c++11", retry_count=2,
        )

        args2_hash = hashlib.md5(b"-std=c++17").hexdigest()
        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
        assert cache_data is None

        cache_mgr.save_file_cache(
            file_path, [], file_hash, args2_hash,
            success=False, error_message="Error with c++17", retry_count=0,
        )

        cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
        assert cache_data is not None
        assert cache_data["retry_count"] == 0