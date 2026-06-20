"""DTO describing a single file indexing task sent to a worker."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class IndexingTaskSpec:
    """Specification for indexing one C++ file in a worker process or thread."""

    project_root: str
    config_file: Optional[str]
    file_path: str
    force: bool
    include_dependencies: bool
    compile_args: List[str]
