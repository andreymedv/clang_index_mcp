"""Diagnostic logging system for C++ Analyzer.

This module provides categorized diagnostic output with configurable levels.
Separates MCP tool output (stdout) from diagnostic messages (stderr by default).
"""

import os
import sys
from enum import IntEnum
from typing import Optional, TextIO


class DiagnosticLevel(IntEnum):
    """Diagnostic message levels in order of severity."""

    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    FATAL = 4


class DiagnosticLogger:
    """Handles diagnostic output with configurable levels and output streams."""

    def __init__(
        self, level: DiagnosticLevel = DiagnosticLevel.INFO, output_stream: TextIO = sys.stderr
    ):
        self.level = level
        self.output_stream = output_stream
        self._enabled = True

    def set_level(self, level: DiagnosticLevel):
        """Set the minimum diagnostic level to output."""
        self.level = level

    def set_output_stream(self, stream: TextIO):
        """Set the output stream for diagnostics."""
        self.output_stream = stream

    def set_enabled(self, enabled: bool):
        """Enable or disable all diagnostic output."""
        self._enabled = enabled

    def _should_output(self, level: DiagnosticLevel) -> bool:
        """Check if a message at the given level should be output."""
        return self._enabled and level >= self.level

    def _format_message(self, level: DiagnosticLevel, message: str) -> str:
        """Format a diagnostic message with level prefix."""
        prefix = {
            DiagnosticLevel.DEBUG: "[DEBUG]",
            DiagnosticLevel.INFO: "[INFO]",
            DiagnosticLevel.WARNING: "[WARNING]",
            DiagnosticLevel.ERROR: "[ERROR]",
            DiagnosticLevel.FATAL: "[FATAL]",
        }
        return f"{prefix[level]} {message}"

    def debug(self, message: str):
        """Output a debug message."""
        if self._should_output(DiagnosticLevel.DEBUG):
            print(
                self._format_message(DiagnosticLevel.DEBUG, message),
                file=self.output_stream,
                flush=True,
            )

    def info(self, message: str):
        """Output an info message."""
        if self._should_output(DiagnosticLevel.INFO):
            print(
                self._format_message(DiagnosticLevel.INFO, message),
                file=self.output_stream,
                flush=True,
            )

    def warning(self, message: str):
        """Output a warning message."""
        if self._should_output(DiagnosticLevel.WARNING):
            print(
                self._format_message(DiagnosticLevel.WARNING, message),
                file=self.output_stream,
                flush=True,
            )

    def error(self, message: str):
        """Output an error message."""
        if self._should_output(DiagnosticLevel.ERROR):
            print(
                self._format_message(DiagnosticLevel.ERROR, message),
                file=self.output_stream,
                flush=True,
            )

    def fatal(self, message: str):
        """Output a fatal error message."""
        if self._should_output(DiagnosticLevel.FATAL):
            print(
                self._format_message(DiagnosticLevel.FATAL, message),
                file=self.output_stream,
                flush=True,
            )


# Global diagnostic logger instance
_global_logger: Optional[DiagnosticLogger] = None


def get_logger() -> DiagnosticLogger:
    """Get the global diagnostic logger instance."""
    global _global_logger
    if _global_logger is None:
        _global_logger = _create_default_logger()
    return _global_logger


def _create_default_logger() -> DiagnosticLogger:
    """Create a logger with default settings from environment/config."""
    # Check environment variable for diagnostic level
    level_str = os.environ.get("CPP_ANALYZER_DIAGNOSTIC_LEVEL", "INFO").upper()
    level_map = {
        "DEBUG": DiagnosticLevel.DEBUG,
        "INFO": DiagnosticLevel.INFO,
        "WARNING": DiagnosticLevel.WARNING,
        "ERROR": DiagnosticLevel.ERROR,
        "FATAL": DiagnosticLevel.FATAL,
    }
    level = level_map.get(level_str, DiagnosticLevel.INFO)

    return DiagnosticLogger(level=level, output_stream=sys.stderr)


def configure_from_config(config: dict):
    """Configure the global logger from a configuration dictionary.

    Expected config format:
    {
        "diagnostics": {
            "level": "info",  # debug, info, warning, error, fatal
            "enabled": true
        }
    }
    """
    diag_config = config.get("diagnostics", {})

    # Get or create logger
    logger = get_logger()

    # Set level
    level_str = diag_config.get("level", "INFO").upper()
    level_map = {
        "DEBUG": DiagnosticLevel.DEBUG,
        "INFO": DiagnosticLevel.INFO,
        "WARNING": DiagnosticLevel.WARNING,
        "ERROR": DiagnosticLevel.ERROR,
        "FATAL": DiagnosticLevel.FATAL,
    }
    if level_str in level_map:
        logger.set_level(level_map[level_str])

    # Set enabled state
    enabled = diag_config.get("enabled", True)
    logger.set_enabled(enabled)


# Convenience functions that use the global logger
def debug(message: str):
    """Output a debug diagnostic message."""
    get_logger().debug(message)


def info(message: str):
    """Output an info diagnostic message."""
    get_logger().info(message)


def warning(message: str):
    """Output a warning diagnostic message."""
    get_logger().warning(message)


def error(message: str):
    """Output an error diagnostic message."""
    get_logger().error(message)


def fatal(message: str):
    """Output a fatal error diagnostic message."""
    get_logger().fatal(message)
