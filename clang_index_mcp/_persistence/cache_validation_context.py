"""DTO grouping cache validation metadata."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class CacheValidationContext:
    """Configuration metadata used to validate cache freshness."""

    config_file_path: Path | None = None
    config_file_mtime: float | None = None
    compile_commands_path: Path | None = None
    compile_commands_mtime: float | None = None
