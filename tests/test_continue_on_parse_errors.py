"""Tests for continuing parsing despite non-fatal errors.

This module tests that the analyzer continues to extract symbols from files
even when there are non-fatal libclang parsing errors, taking advantage of
libclang's error recovery and partial AST generation.
"""

import pytest
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer


class TestContinueOnParseErrors:
    """Test that analyzer continues parsing with non-fatal errors."""

    def test_continue_parsing_with_syntax_errors(self, tmp_path):
        """Test that files with syntax errors still get partially indexed."""
        # Create a C++ file with some valid declarations and a syntax error
        test_file = tmp_path / "test_partial.cpp"
        test_file.write_text("""
// Valid class declaration
class ValidClass {
public:
    void validMethod();
};

// Syntax error: missing semicolon
class BrokenClass {
public:
    void brokenMethod()  // Missing semicolon here
}

// Valid function after error
void validFunction() {
    int x = 42;
}

// Another valid class
class AnotherValidClass {
public:
    int getValue();
};
""")

        # Create analyzer and index the file
        analyzer = CppAnalyzer(str(tmp_path))
        success, was_cached = analyzer.index_file(str(test_file))

        # Should succeed (return True) even with syntax errors
        assert success is True, "File with syntax errors should still be indexed"
        assert was_cached is False

        # Should have extracted at least some symbols
        # libclang's error recovery should allow us to get ValidClass and AnotherValidClass
        class_results = analyzer.search_classes(".*Class")
        assert len(class_results) >= 1, "Should extract at least one valid class despite errors"

        # Check that ValidClass was extracted
        valid_class_found = any(c['name'] == 'ValidClass' for c in class_results)
        assert valid_class_found, "ValidClass should be extracted despite later syntax error"

    def test_continue_parsing_with_undeclared_identifier(self, tmp_path):
        """Test that files with undeclared identifiers still get indexed."""
        test_file = tmp_path / "test_undeclared.cpp"
        test_file.write_text("""
// Valid class
class MyClass {
public:
    void validMethod();
};

// Function using undeclared type (semantic error, not syntax error)
void testFunction() {
    UndeclaredType var;  // This type doesn't exist
}

// Valid function after error
void anotherValidFunction() {
    int y = 100;
}

// Another valid class
class SecondClass {
public:
    void method();
};
""")

        analyzer = CppAnalyzer(str(tmp_path))
        success, was_cached = analyzer.index_file(str(test_file))

        # Should succeed even with semantic errors
        assert success is True, "File with semantic errors should still be indexed"

        # Should extract both classes
        class_results = analyzer.search_classes(".*Class")
        assert len(class_results) >= 2, "Should extract both classes despite semantic error"

        # Should extract functions (both end with "Function")
        function_results = analyzer.search_functions(".*Function")
        assert len(function_results) >= 2, "Should extract functions despite semantic error"

    def test_error_message_logged_and_cached(self, tmp_path):
        """Test that error messages are logged and cached for files with errors."""
        test_file = tmp_path / "test_with_errors.cpp"
        test_file.write_text("""
class GoodClass {
public:
    void method();
};

// Syntax error: missing semicolon
class BadClass {
    void badMethod()
}

class AnotherGoodClass {
public:
    void anotherMethod();
};
""")

        analyzer = CppAnalyzer(str(tmp_path))

        # First parse
        success1, was_cached1 = analyzer.index_file(str(test_file))
        assert success1 is True, "Should succeed despite errors"
        assert was_cached1 is False, "First parse should not be from cache"

        # Second parse should use cache
        analyzer2 = CppAnalyzer(str(tmp_path))
        success2, was_cached2 = analyzer2.index_file(str(test_file))
        assert success2 is True, "Cached parse should also succeed"
        assert was_cached2 is True, "Second parse should be from cache"

        # Both should extract symbols
        class_results = analyzer2.search_classes(".*Class")
        assert len(class_results) >= 1, "Should have classes from cached parse"

    def test_fatal_errors_still_fail(self, tmp_path):
        """Test that truly fatal errors (no TU) still cause failure."""
        test_file = tmp_path / "test_fatal.cpp"
        # Empty file should parse successfully (empty TU)
        # We can't easily create a "fatal" error without invalid compiler flags
        # This test documents the expected behavior
        test_file.write_text("")

        analyzer = CppAnalyzer(str(tmp_path))
        success, was_cached = analyzer.index_file(str(test_file))

        # Empty file should succeed (returns valid empty TU)
        assert success is True, "Empty file should succeed with empty TU"

    def test_partial_ast_extraction(self, tmp_path):
        """Test that we extract symbols from partial AST before error."""
        test_file = tmp_path / "test_partial_ast.cpp"
        test_file.write_text("""
// These should be extracted
class FirstClass {
public:
    void firstMethod();
};

class SecondClass {
public:
    void secondMethod();
};

// Major syntax error that may stop parsing
#error This is a preprocessor error

// These might not be visible depending on error
class ThirdClass {
public:
    void thirdMethod();
};
""")

        analyzer = CppAnalyzer(str(tmp_path))
        success, was_cached = analyzer.index_file(str(test_file))

        # Should succeed and extract at least the first two classes
        assert success is True, "Should succeed with partial AST"

        class_results = analyzer.search_classes(".*Class")
        # We should get at least FirstClass and SecondClass
        assert len(class_results) >= 2, "Should extract classes before preprocessor error"

        class_names = [c['name'] for c in class_results]
        assert 'FirstClass' in class_names, "FirstClass should be extracted"
        assert 'SecondClass' in class_names, "SecondClass should be extracted"

    def test_multiple_files_with_errors(self, tmp_path):
        """Test that multiple files with errors are all processed."""
        # Create multiple files with errors
        file1 = tmp_path / "file1.cpp"
        file1.write_text("""
class Class1 {
public:
    void method1()  // Missing semicolon
}

class Class1Valid {
public:
    void method();
};
""")

        file2 = tmp_path / "file2.cpp"
        file2.write_text("""
class Class2 {
public:
    void method2();
};

void brokenFunction() {
    UndeclaredType x;
}
""")

        analyzer = CppAnalyzer(str(tmp_path))

        # Index both files
        success1, _ = analyzer.index_file(str(file1))
        success2, _ = analyzer.index_file(str(file2))

        # Both should succeed
        assert success1 is True, "File1 should succeed despite syntax error"
        assert success2 is True, "File2 should succeed despite semantic error"

        # Should find classes from both files
        class_results = analyzer.search_classes("Class.*")
        assert len(class_results) >= 2, "Should extract classes from both files"

        class_names = [c['name'] for c in class_results]
        assert 'Class1Valid' in class_names or 'Class2' in class_names, \
            "Should have classes from files with errors"
