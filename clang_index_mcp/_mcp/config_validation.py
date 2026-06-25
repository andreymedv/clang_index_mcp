"""Configuration file validation for the MCP server."""

import os
from typing import Any, List, Optional, Tuple

from mcp.types import TextContent


def _validate_config_file(config_file: Any) -> Tuple[Optional[str], Optional[List[TextContent]]]:
    if not config_file or not isinstance(config_file, str) or not config_file.strip():
        return None, [
            TextContent(type="text", text="Error: 'config_file' must be a non-empty string")
        ]

    config_file = config_file.strip()

    if not os.path.isabs(config_file):
        return None, [
            TextContent(type="text", text=f"Error: '{config_file}' is not an absolute path")
        ]

    if not os.path.isfile(config_file):
        return None, [
            TextContent(type="text", text=f"Error: Config file '{config_file}' does not exist")
        ]

    if not config_file.endswith(".json"):
        return None, [
            TextContent(
                type="text",
                text=f"Error: Config file '{config_file}' must have .json extension",
            )
        ]

    return config_file, None
