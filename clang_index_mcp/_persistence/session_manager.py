"""
Session Manager - Persists MCP server session across restarts

Saves last project directory and config to a session file,
allowing automatic resume on server restart.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .._core import diagnostics


class SessionManager:
    """Manages persistent session state across server restarts"""

    def __init__(self, cache_dir: str = ".mcp_cache"):
        """Initialize session manager

        Args:
            cache_dir: Directory to store session file (default: .mcp_cache)
        """
        self.cache_dir = Path(cache_dir)
        self.session_file = self.cache_dir / "session.json"

    def save_session(self, config_file: str) -> None:
        """Save current session to disk

        Args:
            config_file: Absolute path to the configuration file
        """
        try:
            # Ensure cache directory exists
            self.cache_dir.mkdir(parents=True, exist_ok=True)

            session_data = {
                "config_file": str(config_file),
                "last_accessed": datetime.now(timezone.utc).isoformat(),
                "version": "2.0",  # Bump version due to schema change
            }

            # Atomic write via temp file
            temp_file = self.session_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2)

            # Atomic rename
            temp_file.replace(self.session_file)

            diagnostics.debug(f"Session saved: {config_file}")

        except Exception as e:
            diagnostics.warning(f"Failed to save session: {e}")

    def load_session(self) -> Optional[Dict[str, Any]]:
        """Load last session from disk

        Returns:
            Session data dict if valid session exists, None otherwise
            Dict contains: config_file, last_accessed
        """
        try:
            if not self.session_file.exists():
                diagnostics.debug("No saved session found")
                return None

            with open(self.session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)

            # Validate session data
            if not isinstance(session_data, dict):
                diagnostics.warning("Invalid session file format")
                return None

            if "config_file" not in session_data:
                diagnostics.warning("Session missing config_file")
                return None

            # Check if config file still exists
            config_file = Path(session_data["config_file"])
            if not config_file.exists() or not config_file.is_file():
                diagnostics.info(f"Saved config file no longer exists: {config_file}")
                return None

            diagnostics.debug(f"Loaded session: {session_data['config_file']}")
            return session_data

        except Exception as e:
            diagnostics.warning(f"Failed to load session: {e}")
            return None

    def clear_session(self) -> None:
        """Clear saved session"""
        try:
            if self.session_file.exists():
                self.session_file.unlink()
                diagnostics.debug("Session cleared")
        except Exception as e:
            diagnostics.warning(f"Failed to clear session: {e}")

    def has_session(self) -> bool:
        """Check if a saved session exists

        Returns:
            True if session file exists and is readable
        """
        return self.session_file.exists()
