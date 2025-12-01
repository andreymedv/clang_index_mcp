#!/usr/bin/env python3
"""
Simple test to verify the progressive fallback parsing fix works
"""

import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clang.cindex import Index, TranslationUnit, TranslationUnitLoadError


def test_progressive_fallback():
    """Test that progressive fallback parsing works"""

    # Create a temporary C++ file with complex code
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as f:
        f.write("""
#include <vector>
#include <string>
#include <memory>

class TestClass {
public:
    TestClass() = default;
    ~TestClass() = default;

    void method() {
        auto lambda = [this]() {
            return 42;
        };
    }

private:
    std::vector<std::string> data;
    std::unique_ptr<int> ptr;
};

int main() {
    TestClass obj;
    obj.method();
    return 0;
}
""")
        temp_file = f.name

    try:
        # Test the progressive fallback strategy
        index = Index.create()
        args = ['-std=c++17', '-x', 'c++']

        parse_options_attempts = [
            (TranslationUnit.PARSE_INCOMPLETE | TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
             "full detailed processing"),
            (TranslationUnit.PARSE_INCOMPLETE,
             "incomplete parsing"),
            (0,
             "minimal options"),
        ]

        tu = None
        successful_option = None

        for options, description in parse_options_attempts:
            try:
                print(f"Attempting parse with: {description}")
                tu = index.parse(temp_file, args=args, options=options)
                if tu:
                    successful_option = description
                    print(f"✓ Success with: {description}")
                    break
            except TranslationUnitLoadError as e:
                print(f"✗ Failed with {description}: {e}")
                continue

        if tu:
            print(f"\n✅ Progressive fallback works! Parsed with: {successful_option}")
            print(f"   Translation unit cursor: {tu.cursor.spelling}")
            print(f"   Number of diagnostics: {len(list(tu.diagnostics))}")
            return True
        else:
            print("\n❌ All parse attempts failed!")
            return False

    finally:
        # Clean up
        if os.path.exists(temp_file):
            os.unlink(temp_file)


if __name__ == "__main__":
    print("Testing progressive fallback parsing fix...")
    print("=" * 60)

    success = test_progressive_fallback()

    print("=" * 60)
    sys.exit(0 if success else 1)
