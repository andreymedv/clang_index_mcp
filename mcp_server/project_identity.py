"""Project Identity System for Incremental Analysis.

This module provides unique project identification based on the combination of
source directory and configuration file path. This enables:
- Multiple projects sharing the same source directory but different configs
- Automatic project switching when paths change
- Incremental updates when only file contents change within the same project

Design:
    Project identity = hash(source_directory + config_file_path)
    Different identity → Different cache directory
    Same identity → Reuse cache with incremental updates
"""

import hashlib
from pathlib import Path
from typing import Optional


class ProjectIdentity:
    """
    Unique identifier for a C++ project based on source directory and config file.

    A project is uniquely identified by:
    1. Source directory (absolute path)
    2. Configuration file path (absolute path, optional)

    Changing either path creates a new project identity, resulting in a separate
    cache directory. Changing only file contents within the same paths maintains
    the same identity and enables incremental analysis.

    Examples:
        >>> # Same source, no config
        >>> id1 = ProjectIdentity(Path("/project"), None)
        >>> id2 = ProjectIdentity(Path("/project"), None)
        >>> id1.compute_hash() == id2.compute_hash()  # True - same identity

        >>> # Same source, different config
        >>> id3 = ProjectIdentity(Path("/project"), Path("/project/config1.json"))
        >>> id4 = ProjectIdentity(Path("/project"), Path("/project/config2.json"))
        >>> id3.compute_hash() != id4.compute_hash()  # True - different identity

        >>> # Different source, same config name (but different absolute paths)
        >>> id5 = ProjectIdentity(Path("/project1"), Path("/project1/config.json"))
        >>> id6 = ProjectIdentity(Path("/project2"), Path("/project2/config.json"))
        >>> id5.compute_hash() != id6.compute_hash()  # True - different identity

    Attributes:
        source_directory: Absolute path to project source directory
        config_file_path: Absolute path to configuration file (optional)
    """

    def __init__(self, source_directory: Path, config_file_path: Optional[Path] = None):
        """
        Initialize project identity.

        Args:
            source_directory: Path to project source directory (will be resolved to absolute)
            config_file_path: Path to configuration file (will be resolved to absolute if provided)

        Note:
            Paths are automatically resolved to absolute canonical paths to ensure
            consistent identity regardless of how paths are specified (relative vs absolute).
        """
        self.source_directory = source_directory.resolve()
        self.config_file_path = config_file_path.resolve() if config_file_path else None

    def compute_hash(self) -> str:
        """
        Compute unique hash for this project identity.

        Combines absolute source directory path and config file path (if present)
        into a stable hash value. Uses SHA-256 for cryptographic strength and
        collision resistance.

        Returns:
            16-character hexadecimal hash string (64-bit hash space)

        Algorithm:
            1. Concatenate source_directory and config_file_path with "|" separator
            2. Compute SHA-256 hash of UTF-8 encoded string
            3. Take first 16 hex characters (64 bits)

        Note:
            64-bit hash space provides ~10^19 unique values, sufficient for
            collision-free operation with millions of projects.
        """
        components = [str(self.source_directory)]

        if self.config_file_path:
            components.append(str(self.config_file_path))

        combined = "|".join(components)
        hash_value = hashlib.sha256(combined.encode("utf-8")).hexdigest()

        # Use first 16 characters (64 bits) for reasonable uniqueness
        # while keeping directory names readable
        return hash_value[:16]

    def get_cache_directory_name(self) -> str:
        """
        Get cache directory name for this project.

        Combines human-readable project name with unique hash to create
        a directory name that is both identifiable and guaranteed unique.

        Returns:
            Cache directory name in format: "{project_name}_{hash}"

        Example:
            Source: /home/user/myproject
            Config: /home/user/myproject/.cpp-analyzer-config.json
            Result: "myproject_a1b2c3d4e5f6g7h8"
        """
        project_name = self.source_directory.name or "project"
        return f"{project_name}_{self.compute_hash()}"

    def __eq__(self, other: object) -> bool:
        """
        Compare two project identities for equality.

        Two identities are equal if they have the same source directory
        and config file path (both resolved to absolute paths).

        Args:
            other: Another ProjectIdentity or object

        Returns:
            True if identities are equal, False otherwise
        """
        if not isinstance(other, ProjectIdentity):
            return False

        return (
            self.source_directory == other.source_directory
            and self.config_file_path == other.config_file_path
        )

    def __hash__(self) -> int:
        """
        Compute hash for use in sets and dicts.

        Returns:
            Integer hash value
        """
        return hash((self.source_directory, self.config_file_path))

    def __repr__(self) -> str:
        """
        Return detailed string representation.

        Returns:
            String representation for debugging
        """
        config_str = str(self.config_file_path) if self.config_file_path else "None"
        return (
            f"ProjectIdentity("
            f"source={self.source_directory}, "
            f"config={config_str}, "
            f"hash={self.compute_hash()})"
        )

    def __str__(self) -> str:
        """
        Return user-friendly string representation.

        Returns:
            String representation for display
        """
        if self.config_file_path:
            return f"{self.source_directory} + {self.config_file_path}"
        return str(self.source_directory)

    def to_dict(self) -> dict:
        """
        Convert to dictionary representation.

        Useful for serialization to JSON or other formats.

        Returns:
            Dictionary with source_directory, config_file_path, and hash
        """
        return {
            "source_directory": str(self.source_directory),
            "config_file_path": str(self.config_file_path) if self.config_file_path else None,
            "hash": self.compute_hash(),
            "cache_directory": self.get_cache_directory_name(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectIdentity":
        """
        Create ProjectIdentity from dictionary representation.

        Args:
            data: Dictionary with 'source_directory' and optional 'config_file_path'

        Returns:
            ProjectIdentity instance

        Example:
            >>> data = {
            ...     "source_directory": "/project",
            ...     "config_file_path": "/project/config.json"
            ... }
            >>> identity = ProjectIdentity.from_dict(data)
        """
        source_dir = Path(data["source_directory"])
        config_file = Path(data["config_file_path"]) if data.get("config_file_path") else None

        return cls(source_dir, config_file)
