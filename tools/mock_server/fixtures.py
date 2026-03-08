#!/usr/bin/env python3
"""YAML fixture loader and argument matcher for mock MCP server.

Loads canned tool responses from YAML files and matches them by
tool name + argument patterns.

Matching priority (first match wins):
  1. Exact match on tool_name + all specified argument values
  2. Pattern match (contains/regex) on tool_name + argument values
  3. Default response for the tool (marked with default: true)
  4. Global fallback: {"error": "no fixture matched"}
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class FixtureStore:
    """Load and match canned MCP tool responses from YAML fixtures."""

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._defaults: Dict[str, Dict[str, Any]] = {}  # tool_name -> response

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

    def match(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Find the best matching canned response for a tool call.

        Returns the response dict (ready to be JSON-serialized).
        """
        # Pass 1: check entries with match criteria
        for entry in self._entries:
            if entry["tool"] != tool_name:
                continue
            match_spec = entry.get("match", {})
            if not match_spec:
                continue
            if self._matches(match_spec, arguments):
                return entry["response"]

        # Pass 2: default for this tool
        if tool_name in self._defaults:
            return self._defaults[tool_name]

        # Pass 3: global fallback
        return {"error": f"no fixture matched for {tool_name}"}

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
