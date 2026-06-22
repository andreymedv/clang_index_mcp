"""DTO grouping cache validation metadata."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CacheValidationContext:
    """Configuration metadata used to validate cache freshness."""

    config_file_path: Optional[Path] = None
    config_file_mtime: Optional[float] = None
    compile_commands_path: Optional[Path] = None
    compile_commands_mtime: Optional[float] = None
