#!/usr/bin/env python3
"""
Unit tests for documentation data model (Phase 2 - UT-5).

Tests SymbolInfo dataclass updates with brief and doc_comment fields.
"""

import os
import sys
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.symbol_info import SymbolInfo


class TestSymbolInfoDocumentation:
    """Tests for SymbolInfo dataclass with documentation fields (UT-5)."""

    def test_symbol_info_has_brief_field(self):
        """UT-5.1: Verify SymbolInfo has brief field."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1
        )

        assert hasattr(symbol, 'brief')
        assert symbol.brief is None

    def test_symbol_info_has_doc_comment_field(self):
        """UT-5.2: Verify SymbolInfo has doc_comment field."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1
        )

        assert hasattr(symbol, 'doc_comment')
        assert symbol.doc_comment is None

    def test_create_symbol_with_brief(self):
        """UT-5.3: Create SymbolInfo with brief documentation."""
        symbol = SymbolInfo(
            name="DocumentedClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            brief="This is the brief description"
        )

        assert symbol.brief == "This is the brief description"
        assert symbol.doc_comment is None

    def test_create_symbol_with_doc_comment(self):
        """UT-5.4: Create SymbolInfo with full documentation."""
        doc = "Full documentation\nwith multiple lines"

        symbol = SymbolInfo(
            name="FullyDocumentedClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            doc_comment=doc
        )

        assert symbol.doc_comment == doc
        assert symbol.brief is None

    def test_create_symbol_with_both_docs(self):
        """UT-5.5: Create SymbolInfo with both brief and doc_comment."""
        symbol = SymbolInfo(
            name="CompleteClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            brief="Brief description",
            doc_comment="Full documentation\nwith details"
        )

        assert symbol.brief == "Brief description"
        assert symbol.doc_comment == "Full documentation\nwith details"

    def test_symbol_to_dict_includes_docs(self):
        """UT-5.6: Test to_dict() includes documentation fields."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            brief="Brief",
            doc_comment="Docs"
        )

        d = symbol.to_dict()
        assert 'brief' in d
        assert d['brief'] == "Brief"
        assert 'doc_comment' in d
        assert d['doc_comment'] == "Docs"

    def test_symbol_with_none_documentation(self):
        """UT-5.7: Test SymbolInfo with None for documentation fields."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            brief=None,
            doc_comment=None
        )

        assert symbol.brief is None
        assert symbol.doc_comment is None

    def test_symbol_with_unicode_documentation(self):
        """UT-5.8: Test SymbolInfo with Unicode documentation."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            brief="Unicode test: Привет мир 你好",
            doc_comment="Full docs with emoji: 🚀 📝 ✅"
        )

        assert "Привет" in symbol.brief
        assert "🚀" in symbol.doc_comment


class TestSymbolInfoBackwardCompatibility:
    """Tests to ensure backward compatibility."""

    def test_create_symbol_without_docs_still_works(self):
        """UT-5.9: Verify creating SymbolInfo without docs still works."""
        symbol = SymbolInfo(
            name="OldStyleClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1
        )

        assert symbol.name == "OldStyleClass"
        assert symbol.brief is None
        assert symbol.doc_comment is None

    def test_all_existing_fields_still_present(self):
        """UT-5.10: Verify all existing SymbolInfo fields still exist."""
        symbol = SymbolInfo(
            name="TestClass",
            kind="class",
            file="/test/test.cpp",
            line=10,
            column=1,
            namespace="namespace",
            parent_class="BaseClass",
            brief="Brief",
            doc_comment="Docs"
        )

        # Check all fields exist
        assert hasattr(symbol, 'name')
        assert hasattr(symbol, 'kind')
        assert hasattr(symbol, 'file')
        assert hasattr(symbol, 'line')
        assert hasattr(symbol, 'column')
        assert hasattr(symbol, 'namespace')
        assert hasattr(symbol, 'parent_class')
        assert hasattr(symbol, 'brief')
        assert hasattr(symbol, 'doc_comment')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
