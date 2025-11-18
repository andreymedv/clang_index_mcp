#!/usr/bin/env python3
"""
Comprehensive test suite for all features added in this session:
1. Config file validation (JSON array vs object)
2. Cache invalidation when compilation arguments change
3. Failure tracking and intelligent retry logic
"""
import sys
import json
import tempfile
import hashlib
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mcp_server.cpp_analyzer_config import CppAnalyzerConfig
from mcp_server.cache_manager import CacheManager
from mcp_server.symbol_info import SymbolInfo


class TestResults:
    """Track test results"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def record_pass(self, test_name):
        self.passed += 1
        print(f"  [OK] {test_name}")

    def record_fail(self, test_name, error):
        self.failed += 1
        self.errors.append((test_name, error))
        print(f"  [X] {test_name}: {error}")

    def print_summary(self):
        print("\n" + "=" * 70)
        print(f"Test Results: {self.passed} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for test_name, error in self.errors:
                print(f"  - {test_name}: {error}")
        print("=" * 70)
        return self.failed == 0


def test_config_validation(results):
    """Test config file validation (Feature 1)"""
    print("\n" + "=" * 70)
    print("Feature 1: Config File Validation")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Test 1.1: Valid config (JSON object)
        try:
            valid_dir = tmpdir_path / "valid"
            valid_dir.mkdir()
            valid_config = valid_dir / ".cpp-analyzer-config.json"
            with open(valid_config, 'w') as f:
                json.dump({"max_file_size_mb": 20}, f)

            config = CppAnalyzerConfig(valid_dir)
            assert config.get_max_file_size_mb() == 20, "Config value should be loaded"
            results.record_pass("Valid config (JSON object) loads correctly")
        except Exception as e:
            results.record_fail("Valid config (JSON object) loads correctly", str(e))

        # Test 1.2: Invalid config (JSON array like compile_commands.json)
        try:
            invalid_dir = tmpdir_path / "invalid"
            invalid_dir.mkdir()
            invalid_config = invalid_dir / ".cpp-analyzer-config.json"
            with open(invalid_config, 'w') as f:
                json.dump([{"file": "test.cpp"}], f)

            config = CppAnalyzerConfig(invalid_dir)
            # Should fall back to defaults without crashing
            assert config.get_max_file_size_mb() == 10, "Should use default on invalid config"
            results.record_pass("Invalid config (JSON array) falls back to defaults")
        except Exception as e:
            results.record_fail("Invalid config (JSON array) falls back to defaults", str(e))

        # Test 1.3: No config file
        try:
            no_config_dir = tmpdir_path / "no_config"
            no_config_dir.mkdir()

            config = CppAnalyzerConfig(no_config_dir)
            assert config.get_max_file_size_mb() == 10, "Should use defaults"
            results.record_pass("No config file uses defaults")
        except Exception as e:
            results.record_fail("No config file uses defaults", str(e))

        # Test 1.4: Config with max_parse_retries
        try:
            retry_dir = tmpdir_path / "retry"
            retry_dir.mkdir()
            retry_config = retry_dir / ".cpp-analyzer-config.json"
            with open(retry_config, 'w') as f:
                json.dump({"max_parse_retries": 5}, f)

            config = CppAnalyzerConfig(retry_dir)
            assert config.config.get("max_parse_retries") == 5, "Custom retry count should load"
            results.record_pass("Config with max_parse_retries loads correctly")
        except Exception as e:
            results.record_fail("Config with max_parse_retries loads correctly", str(e))


def test_cache_args_invalidation(results):
    """Test cache invalidation on compilation args change (Feature 2)"""
    print("\n" + "=" * 70)
    print("Feature 2: Cache Invalidation on Compilation Args Change")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        cache_mgr = CacheManager(tmpdir_path)

        test_file = tmpdir_path / "test.cpp"
        test_file.write_text("class Test {};")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()

        symbols = [SymbolInfo(
            name="Test",
            kind="class",
            file=file_path,
            line=1,
            column=7,
            is_project=True
        )]

        # Test 2.1: Save with args1
        try:
            args1 = ['-std=c++11', '-I/usr/include']
            args1_hash = hashlib.md5(" ".join(sorted(args1)).encode()).hexdigest()

            success = cache_mgr.save_file_cache(file_path, symbols, file_hash, args1_hash)
            assert success, "Save should succeed"
            results.record_pass("Save cache with compilation args")
        except Exception as e:
            results.record_fail("Save cache with compilation args", str(e))

        # Test 2.2: Load with same args
        try:
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args1_hash)
            assert cache_data is not None, "Cache should load with matching args"
            assert len(cache_data['symbols']) == 1, "Should have 1 symbol"
            results.record_pass("Load cache with matching args succeeds")
        except Exception as e:
            results.record_fail("Load cache with matching args succeeds", str(e))

        # Test 2.3: Load with different args (should invalidate)
        try:
            args2 = ['-std=c++17', '-I/usr/include']
            args2_hash = hashlib.md5(" ".join(sorted(args2)).encode()).hexdigest()

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
            assert cache_data is None, "Cache should be invalidated with different args"
            results.record_pass("Cache invalidated when args change")
        except Exception as e:
            results.record_fail("Cache invalidated when args change", str(e))

        # Test 2.4: Args order shouldn't matter (sorted)
        try:
            args3a = ['-I/usr/include', '-std=c++11']
            args3b = ['-std=c++11', '-I/usr/include']
            hash3a = hashlib.md5(" ".join(sorted(args3a)).encode()).hexdigest()
            hash3b = hashlib.md5(" ".join(sorted(args3b)).encode()).hexdigest()

            assert hash3a == hash3b, "Hash should be same regardless of order"
            results.record_pass("Args order doesn't affect hash (sorted)")
        except Exception as e:
            results.record_fail("Args order doesn't affect hash (sorted)", str(e))

        # Test 2.5: File content change invalidates cache
        try:
            test_file.write_text("class Test { int x; };")
            new_file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()

            cache_data = cache_mgr.load_file_cache(file_path, new_file_hash, args1_hash)
            assert cache_data is None, "Cache should be invalidated when file changes"
            results.record_pass("Cache invalidated when file content changes")
        except Exception as e:
            results.record_fail("Cache invalidated when file content changes", str(e))


def test_failure_tracking(results):
    """Test failure tracking and retry logic (Feature 3)"""
    print("\n" + "=" * 70)
    print("Feature 3: Failure Tracking and Retry Logic")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        cache_mgr = CacheManager(tmpdir_path)

        test_file = tmpdir_path / "test.cpp"
        test_file.write_text("invalid")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
        args_hash = hashlib.md5(b"-std=c++17").hexdigest()

        # Test 3.1: Save failure
        try:
            success = cache_mgr.save_file_cache(
                file_path, [], file_hash, args_hash,
                success=False, error_message="Parse error", retry_count=0
            )
            assert success, "Save failure should succeed"
            results.record_pass("Save failure to cache")
        except Exception as e:
            results.record_fail("Save failure to cache", str(e))

        # Test 3.2: Load failure
        try:
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data is not None, "Failure cache should load"
            assert cache_data['success'] == False, "Should be marked as failed"
            assert cache_data['error_message'] == "Parse error", "Error message should match"
            assert cache_data['retry_count'] == 0, "Retry count should be 0"
            results.record_pass("Load failure from cache")
        except Exception as e:
            results.record_fail("Load failure from cache", str(e))

        # Test 3.3: Increment retry count
        try:
            cache_mgr.save_file_cache(
                file_path, [], file_hash, args_hash,
                success=False, error_message="Parse error", retry_count=1
            )
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data['retry_count'] == 1, "Retry count should increment"
            results.record_pass("Retry count increments")
        except Exception as e:
            results.record_fail("Retry count increments", str(e))

        # Test 3.4: Multiple retries
        try:
            for i in range(2, 5):
                cache_mgr.save_file_cache(
                    file_path, [], file_hash, args_hash,
                    success=False, error_message="Parse error", retry_count=i
                )
                cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
                assert cache_data['retry_count'] == i, f"Retry count should be {i}"
            results.record_pass("Multiple retries tracked correctly")
        except Exception as e:
            results.record_fail("Multiple retries tracked correctly", str(e))

        # Test 3.5: Success overwrites failure
        try:
            symbols = [SymbolInfo(name="Test", kind="class", file=file_path,
                                 line=1, column=1, is_project=True)]
            cache_mgr.save_file_cache(
                file_path, symbols, file_hash, args_hash,
                success=True, error_message=None, retry_count=0
            )
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data['success'] == True, "Should be marked as success"
            assert cache_data['retry_count'] == 0, "Retry count should reset"
            assert len(cache_data['symbols']) == 1, "Should have symbols"
            results.record_pass("Success overwrites previous failures")
        except Exception as e:
            results.record_fail("Success overwrites previous failures", str(e))

        # Test 3.6: Error message truncation
        try:
            long_error = "A" * 500
            cache_mgr.save_file_cache(
                file_path, [], file_hash, args_hash,
                success=False, error_message=long_error, retry_count=0
            )
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            # The truncation happens in cpp_analyzer.py ([:200]), not cache_manager
            # So here we just verify the message is saved
            assert cache_data['error_message'] is not None, "Error message should be saved"
            results.record_pass("Error messages are saved")
        except Exception as e:
            results.record_fail("Error messages are saved", str(e))


def test_backward_compatibility(results):
    """Test backward compatibility with older cache versions"""
    print("\n" + "=" * 70)
    print("Backward Compatibility Tests")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        cache_mgr = CacheManager(tmpdir_path)

        test_file = tmpdir_path / "test.cpp"
        test_file.write_text("class Test {};")
        file_path = str(test_file)
        file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
        args_hash = hashlib.md5(b"-std=c++17").hexdigest()

        # Test 4.1: v1.1 cache compatibility
        try:
            cache_file = cache_mgr.get_file_cache_path(file_path)
            cache_file.parent.mkdir(exist_ok=True)

            v11_data = {
                "version": "1.1",
                "file_path": file_path,
                "file_hash": file_hash,
                "compile_args_hash": args_hash,
                "timestamp": 123456.0,
                "symbols": []
            }
            with open(cache_file, 'w') as f:
                json.dump(v11_data, f)

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data is not None, "v1.1 cache should load"
            assert cache_data['success'] == True, "v1.1 defaults to success"
            assert cache_data['retry_count'] == 0, "v1.1 defaults to retry_count=0"
            results.record_pass("v1.1 cache backward compatible")
        except Exception as e:
            results.record_fail("v1.1 cache backward compatible", str(e))

        # Test 4.2: v1.0 cache rejection
        try:
            v10_data = {
                "version": "1.0",
                "file_path": file_path,
                "file_hash": file_hash,
                "timestamp": 123456.0,
                "symbols": []
            }
            with open(cache_file, 'w') as f:
                json.dump(v10_data, f)

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data is None, "v1.0 cache should be rejected"
            results.record_pass("v1.0 cache correctly rejected")
        except Exception as e:
            results.record_fail("v1.0 cache correctly rejected", str(e))

        # Test 4.3: Missing version defaults to v1.0 and is rejected
        try:
            no_version_data = {
                "file_path": file_path,
                "file_hash": file_hash,
                "timestamp": 123456.0,
                "symbols": []
            }
            with open(cache_file, 'w') as f:
                json.dump(no_version_data, f)

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data is None, "No version should default to v1.0 and be rejected"
            results.record_pass("Missing version correctly rejected")
        except Exception as e:
            results.record_fail("Missing version correctly rejected", str(e))


def test_error_logging(results):
    """Test centralized error logging (Feature 4)"""
    print("\n" + "=" * 70)
    print("Feature 4: Centralized Error Logging")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        cache_mgr = CacheManager(tmpdir_path)

        # Test 4.1: Log error
        try:
            try:
                raise ValueError("Test error")
            except Exception as e:
                success = cache_mgr.log_parse_error(
                    "/tmp/test.cpp", e, "hash1", "args1", 0
                )
            assert success, "Error logging should succeed"
            results.record_pass("Log parse error")
        except Exception as e:
            results.record_fail("Log parse error", str(e))

        # Test 4.2: Retrieve errors
        try:
            errors = cache_mgr.get_parse_errors()
            assert len(errors) == 1, "Should have 1 error"
            assert errors[0]['error_type'] == 'ValueError', "Error type should match"
            assert errors[0]['file_path'] == '/tmp/test.cpp', "File path should match"
            results.record_pass("Retrieve parse errors")
        except Exception as e:
            results.record_fail("Retrieve parse errors", str(e))

        # Test 4.3: Error summary
        try:
            summary = cache_mgr.get_error_summary()
            assert summary['total_errors'] == 1, "Should have 1 total error"
            assert summary['unique_files'] == 1, "Should have 1 unique file"
            assert 'ValueError' in summary['error_types'], "Should have ValueError"
            results.record_pass("Error summary generation")
        except Exception as e:
            results.record_fail("Error summary generation", str(e))

        # Test 4.4: Filter errors
        try:
            # Add more errors
            for i in range(3):
                try:
                    raise RuntimeError(f"Error {i}")
                except Exception as e:
                    cache_mgr.log_parse_error(f"/tmp/file{i}.cpp", e, f"hash{i}", "args", i)

            filtered = cache_mgr.get_parse_errors(file_path_filter="file1")
            assert len(filtered) == 1, "Should filter to 1 error"
            assert "file1.cpp" in filtered[0]['file_path'], "Should match file1"
            results.record_pass("Filter errors by file path")
        except Exception as e:
            results.record_fail("Filter errors by file path", str(e))

        # Test 4.5: Clear errors
        try:
            cleared = cache_mgr.clear_error_log()
            assert cleared == 4, "Should clear 4 errors"

            remaining = cache_mgr.get_parse_errors()
            assert len(remaining) == 0, "Should have no errors after clear"
            results.record_pass("Clear error log")
        except Exception as e:
            results.record_fail("Clear error log", str(e))


def test_integration(results):
    """Integration tests combining multiple features"""
    print("\n" + "=" * 70)
    print("Integration Tests")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Test 5.1: Config + Cache Manager integration
        try:
            # Create config with custom retry count
            config_file = tmpdir_path / ".cpp-analyzer-config.json"
            with open(config_file, 'w') as f:
                json.dump({"max_parse_retries": 3}, f)

            config = CppAnalyzerConfig(tmpdir_path)
            assert config.config.get("max_parse_retries") == 3, "Custom retry loaded"

            # Create cache manager
            cache_mgr = CacheManager(tmpdir_path)

            # Save a failure and verify it works with config
            test_file = tmpdir_path / "test.cpp"
            test_file.write_text("invalid")
            file_path = str(test_file)
            file_hash = hashlib.md5(test_file.read_bytes()).hexdigest()
            args_hash = hashlib.md5(b"-std=c++17").hexdigest()

            cache_mgr.save_file_cache(
                file_path, [], file_hash, args_hash,
                success=False, error_message="Test error", retry_count=2
            )

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args_hash)
            assert cache_data['retry_count'] == 2, "Retry count should be 2"

            # With max_retries=3, retry_count=2 means we can retry once more
            can_retry = cache_data['retry_count'] < config.config.get("max_parse_retries")
            assert can_retry, "Should be able to retry one more time"

            results.record_pass("Config + Cache Manager integration")
        except Exception as e:
            results.record_fail("Config + Cache Manager integration", str(e))

        # Test 5.2: Failure tracking + Args change integration
        try:
            # Save a failure with args1
            args1_hash = hashlib.md5(b"-std=c++11").hexdigest()
            cache_mgr.save_file_cache(
                file_path, [], file_hash, args1_hash,
                success=False, error_message="Error with c++11", retry_count=2
            )

            # Change args - cache should be invalidated
            args2_hash = hashlib.md5(b"-std=c++17").hexdigest()
            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
            assert cache_data is None, "Cache should be invalidated even for failures"

            # Save new failure with new args
            cache_mgr.save_file_cache(
                file_path, [], file_hash, args2_hash,
                success=False, error_message="Error with c++17", retry_count=0
            )

            cache_data = cache_mgr.load_file_cache(file_path, file_hash, args2_hash)
            assert cache_data is not None, "New failure should be cached"
            assert cache_data['retry_count'] == 0, "Retry count should reset with new args"

            results.record_pass("Failure tracking + Args change integration")
        except Exception as e:
            results.record_fail("Failure tracking + Args change integration", str(e))


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE TEST SUITE - Session Features")
    print("=" * 70)

    results = TestResults()

    # Run all test suites
    test_config_validation(results)
    test_cache_args_invalidation(results)
    test_failure_tracking(results)
    test_error_logging(results)
    test_backward_compatibility(results)
    test_integration(results)

    # Print summary and return exit code
    success = results.print_summary()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
