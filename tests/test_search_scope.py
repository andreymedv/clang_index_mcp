"""
Tests for search_scope parameter validation and conversion.

Verifies that the search_scope string enum correctly replaces
the old project_only boolean in the MCP tool interface.
"""

import pytest
from mcp_server.cpp_mcp_server import _parse_search_scope, _VALID_SEARCH_SCOPES


class TestParseSearchScope:
    """Tests for _parse_search_scope helper."""

    def test_default_returns_project_only_true(self):
        """Missing search_scope defaults to project_code_only (project_only=True)."""
        assert _parse_search_scope({}) is True

    def test_project_code_only(self):
        """Explicit project_code_only returns True."""
        assert _parse_search_scope({"search_scope": "project_code_only"}) is True

    def test_include_external_libraries(self):
        """include_external_libraries returns False (project_only=False)."""
        assert _parse_search_scope({"search_scope": "include_external_libraries"}) is False

    def test_invalid_value_raises(self):
        """Invalid enum value raises ValueError with clear message."""
        with pytest.raises(ValueError, match="Invalid search_scope 'bogus'"):
            _parse_search_scope({"search_scope": "bogus"})

    def test_invalid_boolean_true_raises(self):
        """Passing old-style boolean True is rejected."""
        with pytest.raises(ValueError):
            _parse_search_scope({"search_scope": True})

    def test_invalid_boolean_false_raises(self):
        """Passing old-style boolean False is rejected."""
        with pytest.raises(ValueError):
            _parse_search_scope({"search_scope": False})

    def test_valid_scopes_constant(self):
        """Ensure the valid scopes tuple has exactly two values."""
        assert _VALID_SEARCH_SCOPES == ("project_code_only", "include_external_libraries")

    def test_other_arguments_ignored(self):
        """Other arguments in the dict are ignored."""
        result = _parse_search_scope({
            "pattern": ".*",
            "search_scope": "include_external_libraries",
            "max_results": 10,
        })
        assert result is False
