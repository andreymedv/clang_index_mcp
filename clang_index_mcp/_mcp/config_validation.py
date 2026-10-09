"""Configuration file validation and project-root resolution for the MCP server."""

import json
import os
from typing import Any

from mcp.types import TextContent


def resolve_project_root_from_config(config_file: str) -> str:
    """Resolve the project root declared by a config file.

    Relative ``project_root`` values are resolved against the config file's
    directory. Raises ValueError if the config is unreadable, lacks a
    ``project_root`` field, or the resolved path is not an existing directory.
    """
    try:
        with open(config_file, "r") as f:
            config_data = json.load(f)
    except Exception as e:
        raise ValueError(f"reading config file: {e}") from e

    config_root = config_data.get("project_root")
    if not config_root:
        raise ValueError(f"Config file '{config_file}' is missing 'project_root' field")

    project_path = os.path.abspath(os.path.join(os.path.dirname(config_file), config_root))
    if not os.path.isdir(project_path):
        raise ValueError(
            f"'project_root' in config '{project_path}' is not a directory or does not exist"
        )

    return project_path


def _validate_config_file(config_file: Any) -> tuple[str | None, list[TextContent] | None]:
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
