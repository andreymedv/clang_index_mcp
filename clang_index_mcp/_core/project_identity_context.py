"""Project identity and configuration context."""

from dataclasses import dataclass
from pathlib import Path

from ..cpp_analyzer_config import CppAnalyzerConfig
from .._persistence.project_identity import ProjectIdentity


@dataclass
class ProjectIdentityContext:
    """Stable project identity: root path, identity object, and configuration."""

    project_root: Path
    project_identity: ProjectIdentity
    config: CppAnalyzerConfig
