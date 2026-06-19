"""File utility functions shared across the C++ analyzer."""

import hashlib
from pathlib import Path


def hash_file(file_path: str | Path, chunk_size: int = 8192) -> str:
    """
    Calculate MD5 hash of a file using chunked reads.

    Uses chunked reading to avoid loading large files entirely into memory.
    This is important for source files which can be several MB in size.

    Args:
        file_path: Path to file (string or Path object)
        chunk_size: Read chunk size in bytes (default 8KB)

    Returns:
        MD5 hex digest string, or empty string if file doesn't exist or is unreadable

    Example:
        >>> hash_file("/path/to/source.cpp")
        "d41d8cd98f00b204e9800998ecf8427e"
    """
    path = Path(file_path)
    if not path.exists():
        return ""

    hash_md5 = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                hash_md5.update(chunk)
    except Exception:
        return ""

    return hash_md5.hexdigest()
