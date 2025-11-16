#!/usr/bin/env python3
"""
Tests for Rule-Based Argument Sanitizer (REQ-5.8)

This module tests the flexible rule-based argument sanitization system
that allows users to customize and extend sanitization rules.

Test Coverage:
- REQ-5.8.1: Rule loading from JSON files
- REQ-5.8.2: Rule application
- REQ-5.8.3: Custom rules support
- REQ-5.8.4: Rule types
"""

import sys
import os
import tempfile
import json
from pathlib import Path

# Add mcp_server to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'mcp_server'))

from argument_sanitizer import ArgumentSanitizer


class TestRuleLoading:
    """Tests for REQ-5.8.1: Rule loading from JSON"""

    def test_req_5_8_1_1_default_rules_loading(self):
        """REQ-5.8.1.1: Load default rules from built-in file"""
        sanitizer = ArgumentSanitizer()

        # Should have loaded default rules
        info = sanitizer.get_rules_info()
        assert info['rule_count'] > 0, "Should load default rules"
        assert info['version'] == '1.0', "Should have version 1.0"

        # Verify some expected rules exist
        rule_ids = [r['id'] for r in info['rules']]
        assert 'pch-winvalid' in rule_ids
        assert 'color-diagnostics' in rule_ids
        assert 'debug-info' in rule_ids

        print("✓ REQ-5.8.1.1: Default rules loaded successfully")

    def test_req_5_8_1_2_custom_rules_loading(self):
        """REQ-5.8.1.2: Load and append custom rules"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            custom_rules = {
                "version": "1.0",
                "rules": [
                    {
                        "id": "my-custom-rule",
                        "type": "exact_match",
                        "patterns": ["-my-custom-flag"],
                        "description": "Custom test rule"
                    }
                ]
            }
            json.dump(custom_rules, f)
            custom_file = f.name

        try:
            sanitizer = ArgumentSanitizer(custom_rules_file=Path(custom_file))

            info = sanitizer.get_rules_info()
            rule_ids = [r['id'] for r in info['rules']]

            # Should have both default and custom rules
            assert 'pch-winvalid' in rule_ids, "Should have default rules"
            assert 'my-custom-rule' in rule_ids, "Should have custom rules"

            # Test that custom rule works
            result = sanitizer.sanitize(['-std=c++17', '-my-custom-flag', '-Wall'])
            assert '-my-custom-flag' not in result, "Custom rule should remove flag"
            assert '-std=c++17' in result
            assert '-Wall' in result

            print("✓ REQ-5.8.1.2: Custom rules loaded and appended successfully")

        finally:
            os.unlink(custom_file)

    def test_req_5_8_1_3_graceful_failure(self):
        """REQ-5.8.1.3: Gracefully handle missing or invalid rule files"""
        # Should not crash with non-existent custom rules file
        sanitizer = ArgumentSanitizer(custom_rules_file=Path("/nonexistent/rules.json"))

        # Should still have default rules
        info = sanitizer.get_rules_info()
        assert info['rule_count'] > 0, "Should fall back to default rules"

        print("✓ REQ-5.8.1.3: Gracefully handles missing rule files")


class TestRuleTypes:
    """Tests for REQ-5.8.4: Different rule types"""

    def test_req_5_8_4_1_exact_match_rule(self):
        """REQ-5.8.4.1: exact_match rule type"""
        sanitizer = ArgumentSanitizer()

        args = ['-std=c++17', '-g', '-Wall', '-O0', '-Werror']
        result = sanitizer.sanitize(args)

        # exact_match rules should remove -g and -O0
        assert '-g' not in result
        assert '-O0' not in result
        # But keep others
        assert '-std=c++17' in result
        assert '-Wall' in result
        assert '-Werror' in result

        print("✓ REQ-5.8.4.1: exact_match rule works correctly")

    def test_req_5_8_4_2_prefix_match_rule(self):
        """REQ-5.8.4.2: prefix_match rule type"""
        sanitizer = ArgumentSanitizer()

        args = [
            '-std=c++17',
            '-fconstexpr-steps=10000',
            '-fconstexpr-depth=512',
            '-ftemplate-depth=768',
            '-Wall'
        ]
        result = sanitizer.sanitize(args)

        # prefix_match rules should remove all -fconstexpr* and -ftemplate-depth*
        assert not any('-fconstexpr-steps' in arg for arg in result)
        assert not any('-fconstexpr-depth' in arg for arg in result)
        assert not any('-ftemplate-depth' in arg for arg in result)
        # But keep others
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.8.4.2: prefix_match rule works correctly")

    def test_req_5_8_4_3_flag_with_optional_value_rule(self):
        """REQ-5.8.4.3: flag_with_optional_value rule type"""
        sanitizer = ArgumentSanitizer()

        # Test with value
        args = ['-std=c++17', '-include-pch', '/path/to/file.pch', '-Wall']
        result = sanitizer.sanitize(args)

        assert '-include-pch' not in result
        assert '/path/to/file.pch' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        # Test without value (flag at end)
        args = ['-std=c++17', '-Wall', '-include-pch']
        result = sanitizer.sanitize(args)

        assert '-include-pch' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.8.4.3: flag_with_optional_value rule works correctly")

    def test_req_5_8_4_4_xclang_sequence_rule(self):
        """REQ-5.8.4.4: xclang_sequence rule type"""
        sanitizer = ArgumentSanitizer()

        args = [
            '-std=c++17',
            '-Xclang', '-include-pch',
            '-Xclang', '/path/to/file.pch',
            '-Wall'
        ]
        result = sanitizer.sanitize(args)

        # Should remove entire sequence
        assert '-Xclang' not in result
        assert '-include-pch' not in result
        assert '/path/to/file.pch' not in result
        # But keep others
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.8.4.4: xclang_sequence rule works correctly")

    def test_req_5_8_4_5_xclang_conditional_sequence_rule(self):
        """REQ-5.8.4.5: xclang_conditional_sequence rule type"""
        sanitizer = ArgumentSanitizer()

        # Should remove when file contains 'pch'
        args = [
            '-std=c++17',
            '-Xclang', '-include',
            '-Xclang', 'cmake_pch.hxx',
            '-Wall'
        ]
        result = sanitizer.sanitize(args)

        assert 'cmake_pch.hxx' not in result
        assert '-Xclang' not in result
        assert '-include' not in result

        # Should NOT remove when file doesn't contain 'pch'
        args = [
            '-std=c++17',
            '-Xclang', '-include',
            '-Xclang', 'config.h',
            '-Wall'
        ]
        result = sanitizer.sanitize(args)

        # This should be kept (no 'pch' in filename)
        # Note: -Xclang -include -Xclang config.h is unusual but valid
        assert 'config.h' in result
        assert '-include' in result

        print("✓ REQ-5.8.4.5: xclang_conditional_sequence rule works correctly")

    def test_req_5_8_4_6_xclang_option_with_value_rule(self):
        """REQ-5.8.4.6: xclang_option_with_value rule type"""
        sanitizer = ArgumentSanitizer()

        # Test with value
        args = [
            '-std=c++17',
            '-Xclang', '-fmodules-cache-path', '/path/to/cache',
            '-Wall'
        ]
        result = sanitizer.sanitize(args)

        assert '-Xclang' not in result
        assert '-fmodules-cache-path' not in result
        assert '/path/to/cache' not in result
        assert '-std=c++17' in result
        assert '-Wall' in result

        print("✓ REQ-5.8.4.6: xclang_option_with_value rule works correctly")


class TestRuleApplication:
    """Tests for REQ-5.8.2: Rule application logic"""

    def test_req_5_8_2_1_sequential_processing(self):
        """REQ-5.8.2.1: Process arguments sequentially"""
        sanitizer = ArgumentSanitizer()

        args = ['-g', '-std=c++17', '-O0', '-Wall', '-fPIC']
        result = sanitizer.sanitize(args)

        # All matching flags should be removed in order
        assert '-g' not in result
        assert '-O0' not in result
        assert '-fPIC' not in result

        # Non-matching flags should remain in order
        assert result.index('-std=c++17') < result.index('-Wall')

        print("✓ REQ-5.8.2.1: Sequential processing works correctly")

    def test_req_5_8_2_2_no_rule_match_preserves_arg(self):
        """REQ-5.8.2.2: Arguments with no matching rule are preserved"""
        sanitizer = ArgumentSanitizer()

        args = [
            '-std=c++17',
            '-DTEST_DEFINE',
            '-I/usr/include',
            '-Wunknown-custom-warning'
        ]
        result = sanitizer.sanitize(args)

        # All should be preserved (no rules match these)
        assert result == args, "Arguments without matching rules should be preserved"

        print("✓ REQ-5.8.2.2: Non-matching arguments preserved")

    def test_req_5_8_2_3_first_matching_rule_wins(self):
        """REQ-5.8.2.3: First matching rule is applied"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            # Create overlapping rules - first should win
            custom_rules = {
                "version": "1.0",
                "rules": [
                    {
                        "id": "rule1",
                        "type": "prefix_match",
                        "patterns": ["-ftest"],
                        "description": "Remove -ftest* flags"
                    },
                    {
                        "id": "rule2",
                        "type": "exact_match",
                        "patterns": ["-ftest-specific"],
                        "description": "This should not be reached"
                    }
                ]
            }
            json.dump(custom_rules, f)
            custom_file = f.name

        try:
            # Load only custom rules (no defaults) for this test
            sanitizer = ArgumentSanitizer(rules_file=Path(custom_file))

            args = ['-std=c++17', '-ftest-specific', '-Wall']
            result = sanitizer.sanitize(args)

            # First rule (prefix_match) should match and remove
            assert '-ftest-specific' not in result

            print("✓ REQ-5.8.2.3: First matching rule is applied")

        finally:
            os.unlink(custom_file)


class TestComplexScenarios:
    """Tests for complex real-world sanitization scenarios"""

    def test_complex_cmake_pch_removal(self):
        """Test removal of complex CMake PCH patterns"""
        sanitizer = ArgumentSanitizer()

        args = [
            '/usr/bin/clang++',  # Will be removed by earlier parsing
            '-std=c++17',
            '-DTEST',
            '-I/project/include',
            '-isystem', '/system/include',
            '-g', '-Wall', '-Wextra', '-Werror',
            '-O0', '-m64', '-ggdb',
            '-fcolor-diagnostics',
            '-fconstexpr-steps=11000000',
            '-ftemplate-depth=768',
            '-fPIC',
            '-fvisibility-inlines-hidden',
            '-Winvalid-pch',
            '-Xclang', '-include-pch',
            '-Xclang', '/build/pch.pch',
            '-Xclang', '-include',
            '-Xclang', '/build/cmake_pch.hxx'
        ]

        result = sanitizer.sanitize(args)

        # Should keep essential flags
        assert '-std=c++17' in result
        assert '-DTEST' in result
        assert '-I/project/include' in result
        assert '-isystem' in result
        assert '/system/include' in result
        assert '-Wall' in result
        assert '-Wextra' in result
        assert '-Werror' in result

        # Should remove all problematic flags
        assert '-g' not in result
        assert '-O0' not in result
        assert '-m64' not in result
        assert '-ggdb' not in result
        assert '-fcolor-diagnostics' not in result
        assert not any('-fconstexpr-steps' in arg for arg in result)
        assert not any('-ftemplate-depth' in arg for arg in result)
        assert '-fPIC' not in result
        assert '-fvisibility-inlines-hidden' not in result
        assert '-Winvalid-pch' not in result
        assert '-Xclang' not in result
        assert '-include-pch' not in result
        assert '/build/pch.pch' not in result
        assert 'cmake_pch.hxx' not in result

        print("✓ Complex CMake PCH removal works correctly")


def run_all_tests():
    """Run all argument sanitizer tests"""
    print("=" * 70)
    print("Testing Rule-Based Argument Sanitizer (REQ-5.8)")
    print("=" * 70)

    test_classes = [
        TestRuleLoading(),
        TestRuleTypes(),
        TestRuleApplication(),
        TestComplexScenarios()
    ]

    total_tests = 0
    passed_tests = 0

    for test_class in test_classes:
        print(f"\n{test_class.__class__.__name__}:")
        print("-" * 70)

        for method_name in dir(test_class):
            if method_name.startswith('test_'):
                total_tests += 1
                try:
                    method = getattr(test_class, method_name)
                    method()
                    passed_tests += 1
                except AssertionError as e:
                    print(f"✗ {method_name}: {e}")
                except Exception as e:
                    print(f"✗ {method_name}: Unexpected error: {e}")
                    import traceback
                    traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"Test Results: {passed_tests}/{total_tests} passed")
    print("=" * 70)

    return passed_tests == total_tests


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
