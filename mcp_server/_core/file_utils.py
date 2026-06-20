"""File utility functions shared across the C++ analyzer."""

import hashlib
from pathlib import Path
from typing import List


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


def hash_compile_args(args: List[str], normalize_order: bool = True) -> str:
    """
    Hash compilation arguments for change detection.

    Creates a stable hash of the argument list that can be used to detect
    changes in compilation flags.

    Args:
        args: List of compilation arguments
        normalize_order: If True, sort args before hashing (for cache validation).
                        If False, preserve order (for detecting flag order changes).

    Returns:
        SHA-256 hex digest (full length)

    Rationale:
        - SHA-256 over MD5 for better collision resistance
        - Pipe separator avoids ambiguity (e.g., "-I /foo" vs "-I/foo")
        - normalize_order=True makes cache validation order-independent
          (most compilation flags are order-independent)
        - normalize_order=False detects when flag order changes
          (matters for some flags like -I include paths)

    Example:
        >>> hash_compile_args(["-std=c++17", "-O2"], normalize_order=True)
        "a1b2c3d4..."
        >>> hash_compile_args(["-I/usr/include", "-I/opt/include"], normalize_order=False)
        "e5f6g7h8..."
    """
    normalized = sorted(args) if normalize_order else args
    args_str = "|".join(normalized)
    return hashlib.sha256(args_str.encode("utf-8")).hexdigest()
