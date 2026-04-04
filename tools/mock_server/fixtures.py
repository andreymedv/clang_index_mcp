#!/usr/bin/env python3
"""YAML fixture loader and argument matcher for mock MCP server.

Loads canned tool responses from YAML files and matches them by
tool name + argument patterns.

Matching priority (most specific wins):
  1. Best match: entry with most matching criteria in match spec
     (ties broken by entry order — first wins)
  2. Default response for the tool (marked with default: true)
  3. Record unmatched incident and return internal error response
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class FixtureStore:
    """Load and match canned MCP tool responses from YAML fixtures."""

    def __init__(self, report_path: Optional[Path] = None) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._defaults: Dict[str, Dict[str, Any]] = {}  # tool_name -> response
        self._report_path: Optional[Path] = report_path
        self._unmatched_incidents: List[Dict[str, Any]] = []

    def load(self, yaml_path: str | Path) -> "FixtureStore":
        """Load fixture entries from a YAML file."""
        path = Path(yaml_path)
        with open(path) as f:
            data = yaml.safe_load(f)

        for entry in data.get("responses", []):
            tool = entry["tool"]
            if entry.get("default"):
                self._defaults[tool] = entry["response"]
            else:
                self._entries.append(entry)

        return self

    def get_unmatched_incidents(self) -> List[Dict[str, Any]]:
        """Return list of unmatched tool call incidents."""
        return list(self._unmatched_incidents)

    def clear_incidents(self) -> None:
        """Clear the unmatched incidents list."""
        self._unmatched_incidents.clear()

    def match(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Find the best matching canned response for a tool call.

        Uses best-match strategy: among all matching entries, the one with
        the most criteria in its match spec wins (most specific match).
        Ties are broken by entry order (first wins).

        If no match found, records an incident and returns an internal error
        response instead of a default/wrong response.

        Returns the response dict (ready to be JSON-serialized).
        """
        # Normalize arguments: unwrap if wrapped in 'parameters'
        normalized_args = self._normalize_arguments(arguments)

        # Pass 1: find all matching entries, pick most specific
        best_entry = None
        best_specificity = -1
        for entry in self._entries:
            if entry["tool"] != tool_name:
                continue
            match_spec = entry.get("match", {})
            if not match_spec:
                continue
            if self._matches(match_spec, normalized_args):
                specificity = len(match_spec)
                if specificity > best_specificity:
                    best_specificity = specificity
                    best_entry = entry

        if best_entry is not None:
            return best_entry["response"]

        # Pass 2: default for this tool (only if exists and no arguments provided)
        # We no longer use defaults when arguments were provided but didn't match
        if tool_name in self._defaults and not normalized_args:
            return self._defaults[tool_name]

        # Pass 3: record unmatched incident and return internal error
        incident = {
            "tool": tool_name,
            "arguments": arguments,
            "normalized_arguments": normalized_args,
        }
        self._unmatched_incidents.append(incident)

        # Return internal error response
        return {
            "error": f"Internal error: no fixture matched for {tool_name}",
            "message": f"The mock server has no canned response for this tool call. Tool: {tool_name}, Arguments: {json.dumps(arguments)}",
            "hint": "This is a test infrastructure issue - the fixture is missing for this specific tool call.",
        }

    @staticmethod
    def _normalize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize arguments by unwrapping common wrapper patterns.

        Some models wrap arguments in {'parameters': {...}} instead of passing
        them directly. This method unwraps such patterns.
        """
        if not isinstance(arguments, dict):
            return arguments

        # Unwrap {'parameters': {...}} → {...}
        if "parameters" in arguments and len(arguments) == 1:
            return arguments["parameters"]

        return arguments

    def match_json(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Like match() but returns JSON string."""
        return json.dumps(self.match(tool_name, arguments), indent=2)

    @staticmethod
    def _matches(match_spec: Dict[str, Any], arguments: Dict[str, Any]) -> bool:
        """Check if arguments satisfy match_spec.

        Each key in match_spec must be present in arguments and match:
        - str value: exact case-insensitive match
        - dict with 'contains': substring match
        - dict with 'regex': regex match
        """
        for key, expected in match_spec.items():
            actual = arguments.get(key)
            if actual is None:
                return False

            actual_str = str(actual)

            if isinstance(expected, dict):
                if "contains" in expected:
                    if expected["contains"].lower() not in actual_str.lower():
                        return False
                elif "regex" in expected:
                    if not re.search(expected["regex"], actual_str, re.IGNORECASE):
                        return False
                else:
                    return False
            else:
                # Exact match (case-insensitive for strings)
                if isinstance(expected, str):
                    if actual_str.lower() != expected.lower():
                        return False
                elif actual != expected:
                    return False

        return True
