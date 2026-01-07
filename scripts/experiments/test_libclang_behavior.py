#!/usr/bin/env python3
"""
libclang Behavior Validation Experiment

Tests critical assumptions about libclang's type alias handling
and template metadata extraction.

Usage:
    python test_libclang_behavior.py --all
    python test_libclang_behavior.py --test tc4
    python test_libclang_behavior.py --verify
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional
import tempfile
import os

try:
    import clang.cindex as clx
except ImportError:
    print("ERROR: clang.cindex not available")
    print("Install with: pip install libclang")
    sys.exit(1)


# Test cases as code strings
TEST_CASES = {
    "tc1": {
        "name": "Simple Type Alias",
        "code": """
using IntPtr = int*;

class Test {
public:
    IntPtr member;
};
""",
        "check": "member type canonical form",
    },
    "tc2": {
        "name": "Nested Type Aliases",
        "code": """
using Ptr1 = int*;
using Ptr2 = Ptr1;

class Test {
public:
    Ptr2 member;
};
""",
        "check": "chain resolution",
    },
    "tc3": {
        "name": "Template Type Alias",
        "code": """
#include <vector>

template<typename T>
using Vec = std::vector<T>;

class Test {
public:
    Vec<int> member;
};
""",
        "check": "template alias expansion",
    },
    "tc4": {
        "name": "Base Class with Alias (CRITICAL)",
        "code": """
#include <memory>

namespace ns1 {
    class Foo {};
}

using FooPtr = std::unique_ptr<ns1::Foo>;

template<typename T>
class Container {};

class Derived : public Container<FooPtr> {};
""",
        "check": "base class canonical name with alias",
        "critical": True,
    },
    "tc5": {
        "name": "Template Function Detection",
        "code": """
template<typename T>
void func(T value) {}

template<>
void func<int>(int value) {}

void func(double value) {}
""",
        "check": "distinguish template vs specialization vs overload",
    },
    "tc6": {
        "name": "Template Class Specialization",
        "code": """
template<typename T>
class Container {
public:
    void generic() {}
};

template<>
class Container<int> {
public:
    void special() {}
};
""",
        "check": "detect specialization",
    },
}


class LibclangTester:
    def __init__(self):
        self.index = clx.Index.create()
        self.results = {}

    def setup_libclang(self):
        """Verify libclang is available and working"""
        print("Setting up libclang...")
        print(f"  Python clang module: {clx.__file__}")
        print(f"  libclang version: {clx.version.__version__}")

        # Try to parse simple code
        try:
            code = "int main() { return 0; }"
            tu = self.index.parse('test.cpp', unsaved_files=[('test.cpp', code)])
            if tu is None:
                raise RuntimeError("Failed to create translation unit")
            print("  libclang working: ✅")
            return True
        except Exception as e:
            print(f"  libclang error: ❌ {e}")
            return False

    def parse_test_case(self, test_id: str, code: str) -> Optional[clx.TranslationUnit]:
        """Parse test case code"""
        filename = f'test_{test_id}.cpp'

        # Parse with C++11 and std includes
        args = [
            '-std=c++11',
            '-I/usr/include',
            '-I/usr/include/c++/11',  # Adjust if needed
        ]

        try:
            tu = self.index.parse(
                filename,
                args=args,
                unsaved_files=[(filename, code)],
                options=clx.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
            )

            if tu is None:
                print(f"    ❌ Failed to parse {test_id}")
                return None

            # Check for errors
            diagnostics = list(tu.diagnostics)
            errors = [d for d in diagnostics if d.severity >= clx.Diagnostic.Error]
            if errors:
                print(f"    ⚠️  Parse errors in {test_id}:")
                for err in errors[:3]:  # Show first 3
                    print(f"       {err.spelling}")
                # Continue anyway - we might still extract useful info

            return tu

        except Exception as e:
            print(f"    ❌ Exception parsing {test_id}: {e}")
            return None

    def analyze_tc1_simple_alias(self, tu: clx.TranslationUnit) -> Dict:
        """TC1: Check simple type alias resolution"""
        results = {"found": False}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind == clx.CursorKind.CLASS_DECL and cursor.spelling == "Test":
                # Find member
                for child in cursor.get_children():
                    if child.kind == clx.CursorKind.FIELD_DECL and child.spelling == "member":
                        results["found"] = True
                        results["type_spelling"] = child.type.spelling

                        # Get canonical type
                        canonical = child.type.get_canonical()
                        results["canonical_spelling"] = canonical.spelling
                        results["is_expanded"] = "int*" in canonical.spelling

                        break
                break

        return results

    def analyze_tc2_nested_alias(self, tu: clx.TranslationUnit) -> Dict:
        """TC2: Check nested alias resolution"""
        results = {"found": False}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind == clx.CursorKind.CLASS_DECL and cursor.spelling == "Test":
                for child in cursor.get_children():
                    if child.kind == clx.CursorKind.FIELD_DECL and child.spelling == "member":
                        results["found"] = True
                        results["type_spelling"] = child.type.spelling

                        canonical = child.type.get_canonical()
                        results["canonical_spelling"] = canonical.spelling
                        results["fully_expanded"] = "int*" in canonical.spelling

                        break
                break

        return results

    def analyze_tc3_template_alias(self, tu: clx.TranslationUnit) -> Dict:
        """TC3: Check template alias resolution"""
        results = {"found": False}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind == clx.CursorKind.CLASS_DECL and cursor.spelling == "Test":
                for child in cursor.get_children():
                    if child.kind == clx.CursorKind.FIELD_DECL and child.spelling == "member":
                        results["found"] = True
                        results["type_spelling"] = child.type.spelling

                        canonical = child.type.get_canonical()
                        results["canonical_spelling"] = canonical.spelling
                        results["expanded_to_std_vector"] = "vector" in canonical.spelling.lower()

                        break
                break

        return results

    def analyze_tc4_base_class_alias(self, tu: clx.TranslationUnit) -> Dict:
        """TC4: CRITICAL - Check base class with alias in template arg"""
        results = {"found": False, "critical": True}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind == clx.CursorKind.CLASS_DECL and cursor.spelling == "Derived":
                results["found"] = True

                # Get base classes
                for child in cursor.get_children():
                    if child.kind == clx.CursorKind.CXX_BASE_SPECIFIER:
                        base_type = child.type
                        results["base_type_spelling"] = base_type.spelling

                        # Get canonical
                        canonical = base_type.get_canonical()
                        results["canonical_spelling"] = canonical.spelling

                        # Check if alias expanded
                        has_fooptr = "FooPtr" in canonical.spelling
                        has_unique_ptr = "unique_ptr" in canonical.spelling
                        has_qualified = "ns1::Foo" in canonical.spelling or "ns1::class Foo" in canonical.spelling

                        results["contains_alias_name"] = has_fooptr
                        results["contains_unique_ptr"] = has_unique_ptr
                        results["contains_qualified_arg"] = has_qualified

                        # Verdict
                        if has_fooptr:
                            results["verdict"] = "ALIAS NOT EXPANDED - Q12 blocks Q3"
                        elif has_unique_ptr and has_qualified:
                            results["verdict"] = "ALIAS EXPANDED + QUALIFIED - Q3 works!"
                        elif has_unique_ptr and not has_qualified:
                            results["verdict"] = "PARTIAL - unique_ptr but missing qualification"
                        else:
                            results["verdict"] = "UNCLEAR - needs investigation"

                        break
                break

        return results

    def analyze_tc5_template_function(self, tu: clx.TranslationUnit) -> Dict:
        """TC5: Check template function detection"""
        results = {"functions": []}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind in [clx.CursorKind.FUNCTION_DECL, clx.CursorKind.FUNCTION_TEMPLATE]:
                if cursor.spelling == "func":
                    func_info = {
                        "spelling": cursor.spelling,
                        "kind": cursor.kind.name,
                        "displayname": cursor.displayname,
                    }

                    # Check if it's a template
                    try:
                        specialized = cursor.specialized_cursor_template()
                        if specialized:
                            func_info["is_specialization"] = True
                            func_info["template_spelling"] = specialized.spelling
                        else:
                            func_info["is_specialization"] = False
                    except:
                        func_info["is_specialization"] = "unknown"

                    # Check template kind
                    if cursor.kind == clx.CursorKind.FUNCTION_TEMPLATE:
                        func_info["type"] = "template"
                    else:
                        func_info["type"] = "regular or specialization"

                    results["functions"].append(func_info)

        results["can_distinguish"] = len(results["functions"]) == 3
        return results

    def analyze_tc6_template_class(self, tu: clx.TranslationUnit) -> Dict:
        """TC6: Check template class specialization detection"""
        results = {"classes": []}

        for cursor in tu.cursor.walk_preorder():
            if cursor.kind in [clx.CursorKind.CLASS_DECL, clx.CursorKind.CLASS_TEMPLATE]:
                if "Container" in cursor.spelling:
                    class_info = {
                        "spelling": cursor.spelling,
                        "kind": cursor.kind.name,
                        "displayname": cursor.displayname,
                    }

                    # Check specialization
                    try:
                        specialized = cursor.specialized_cursor_template()
                        if specialized:
                            class_info["is_specialization"] = True
                        else:
                            class_info["is_specialization"] = False
                    except:
                        class_info["is_specialization"] = "unknown"

                    results["classes"].append(class_info)

        return results

    def run_test_case(self, test_id: str) -> Dict:
        """Run single test case"""
        test = TEST_CASES[test_id]
        print(f"\n{'='*60}")
        print(f"Running {test_id}: {test['name']}")
        print(f"  Check: {test['check']}")
        if test.get('critical'):
            print(f"  ⚠️  CRITICAL TEST")
        print(f"{'='*60}")

        # Parse
        tu = self.parse_test_case(test_id, test['code'])
        if tu is None:
            return {"error": "Failed to parse"}

        # Analyze based on test ID
        if test_id == "tc1":
            results = self.analyze_tc1_simple_alias(tu)
        elif test_id == "tc2":
            results = self.analyze_tc2_nested_alias(tu)
        elif test_id == "tc3":
            results = self.analyze_tc3_template_alias(tu)
        elif test_id == "tc4":
            results = self.analyze_tc4_base_class_alias(tu)
        elif test_id == "tc5":
            results = self.analyze_tc5_template_function(tu)
        elif test_id == "tc6":
            results = self.analyze_tc6_template_class(tu)
        else:
            results = {"error": "Unknown test case"}

        # Print results
        print("\nResults:")
        for key, value in results.items():
            if isinstance(value, list):
                print(f"  {key}:")
                for item in value:
                    print(f"    {item}")
            else:
                print(f"  {key}: {value}")

        # Special handling for TC4
        if test_id == "tc4" and "verdict" in results:
            print(f"\n🎯 VERDICT: {results['verdict']}")

        self.results[test_id] = results
        return results

    def run_all_tests(self):
        """Run all test cases"""
        print("\n" + "="*60)
        print("RUNNING ALL TEST CASES")
        print("="*60)

        for test_id in TEST_CASES.keys():
            self.run_test_case(test_id)

        self.print_summary()

    def print_summary(self):
        """Print summary of all results"""
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)

        # TC4 verdict
        if "tc4" in self.results:
            tc4 = self.results["tc4"]
            if "verdict" in tc4:
                print(f"\n🎯 CRITICAL FINDING (TC4):")
                print(f"   {tc4['verdict']}")

                if "ALIAS NOT EXPANDED" in tc4['verdict']:
                    print(f"\n   ⚠️  IMPACT: Q12 becomes blocker for Q3")
                    print(f"   Phase 1 increases from ~3 weeks to ~6-7 weeks")
                elif "Q3 works" in tc4['verdict']:
                    print(f"\n   ✅ IMPACT: Q3 works as planned, Q12 stays deferred")

        # Template detection
        if "tc5" in self.results:
            tc5 = self.results["tc5"]
            if tc5.get("can_distinguish"):
                print(f"\n✅ Template function detection: Feasible")
            else:
                print(f"\n⚠️  Template function detection: Needs investigation")

        print(f"\n{'='*60}")
        print("Next steps:")
        print("1. Review results above")
        print("2. Document in: docs/experiments/LIBCLANG_EXPERIMENT_RESULTS.md")
        print("3. Share with Claude for analysis")
        print("4. Adjust prioritization based on findings")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Test libclang behavior")
    parser.add_argument("--verify", action="store_true", help="Verify libclang setup only")
    parser.add_argument("--all", action="store_true", help="Run all test cases")
    parser.add_argument("--test", type=str, help="Run specific test case (e.g., tc4)")

    args = parser.parse_args()

    tester = LibclangTester()

    if args.verify:
        if tester.setup_libclang():
            print("\n✅ libclang is ready for experiments")
            sys.exit(0)
        else:
            print("\n❌ libclang setup failed")
            sys.exit(1)

    if not tester.setup_libclang():
        print("\n❌ Cannot proceed - libclang not working")
        sys.exit(1)

    if args.all:
        tester.run_all_tests()
    elif args.test:
        if args.test not in TEST_CASES:
            print(f"❌ Unknown test case: {args.test}")
            print(f"Available: {', '.join(TEST_CASES.keys())}")
            sys.exit(1)
        tester.run_test_case(args.test)
    else:
        print("Use --all to run all tests, or --test tcX for specific test")
        print(f"Available tests: {', '.join(TEST_CASES.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
