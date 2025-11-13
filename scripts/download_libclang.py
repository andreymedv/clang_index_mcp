#!/usr/bin/env python3
"""Download a self-contained libclang copy for the MCP server."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable, Optional

import urllib.request
import subprocess


LLVM_VERSION = "19.1.7"


class DownloadConfig:
    """Configuration for downloading the correct libclang artifact."""

    def __init__(self, system: str, archive_name: str, lib_paths: Iterable[str], dest_dir: Path):
        self.system = system
        self.archive_name = archive_name
        self.lib_paths = tuple(lib_paths)
        self.dest_dir = dest_dir

    @property
    def url(self) -> str:
        return (
            f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{LLVM_VERSION}/"
            f"{self.archive_name}"
        )


def get_download_config(system_override: Optional[str] = None) -> DownloadConfig:
    """Return the download configuration for the current platform."""

    system = (system_override or platform.system()).lower()
    base_dir = Path("lib")

    if system == "windows":
        return DownloadConfig(
            system="Windows",
            archive_name=f"clang+llvm-{LLVM_VERSION}-x86_64-pc-windows-msvc.tar.xz",
            lib_paths=("bin/libclang.dll",),
            dest_dir=base_dir / "windows",
        )

    if system == "darwin":
        # Detect Mac architecture (Apple Silicon vs Intel)
        arch = platform.machine().lower()
        if arch in ("arm64", "aarch64"):
            archive_name = f"LLVM-{LLVM_VERSION}-macOS-ARM64.tar.xz"
        else:  # x86_64, AMD64, i386
            archive_name = f"LLVM-{LLVM_VERSION}-macOS-X64.tar.xz"

        return DownloadConfig(
            system="macOS",
            archive_name=archive_name,
            lib_paths=("lib/libclang.dylib",),
            dest_dir=base_dir / "macos",
        )

    # Default to Linux (x86_64)
    return DownloadConfig(
        system="Linux",
        archive_name=f"LLVM-{LLVM_VERSION}-Linux-X64.tar.xz",
        lib_paths=(
            "lib/libclang.so.19",
            "lib/libclang.so.1",
            "lib/libclang.so",
        ),
        dest_dir=base_dir / "linux",
    )


def _already_present(dest_dir: Path, expected_files: Iterable[str]) -> bool:
    for filename in expected_files:
        if (dest_dir / filename).exists():
            return True
    return False


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _copy_libclang(temp_root: Path, config: DownloadConfig) -> bool:
    """Copy libclang from extracted archive into the destination directory."""

    extracted_libs = []
    for relative_path in config.lib_paths:
        matches = list(temp_root.glob(f"**/{relative_path}"))
        extracted_libs.extend(matches)

    if not extracted_libs:
        print("✗ Could not locate libclang in the downloaded archive")
        return False

    _ensure_directory(config.dest_dir)

    copied = False
    for src in extracted_libs:
        target_name = src.name
        target_path = config.dest_dir / target_name
        shutil.copy2(src, target_path)
        print(f"✓ Copied {target_name} to {target_path}")
        copied = True

        # For Linux we need libclang.so.1 as well as the full versioned .so
        if config.system == "Linux" and target_name.startswith("libclang.so."):
            symlink_target = config.dest_dir / "libclang.so.1"
            if not symlink_target.exists():
                try:
                    os.symlink(target_path.name, symlink_target)
                    print(f"✓ Created symlink {symlink_target} -> {target_path.name}")
                except OSError:
                    # Fall back to copying if symlinks are unavailable
                    shutil.copy2(target_path, symlink_target)
                    print(f"✓ Copied duplicate {symlink_target}")

    if not copied:
        print("✗ Failed to copy any libclang files")
    return copied


def download_libclang(system_override: Optional[str] = None) -> bool:
    """Download and extract a libclang build for the current platform."""

    config = get_download_config(system_override)
    print(f"Setting up libclang for {config.system}...")
    _ensure_directory(config.dest_dir)

    expected_names = {
        "Windows": ["libclang.dll"],
        "macOS": ["libclang.dylib"],
        "Linux": ["libclang.so", "libclang.so.1", "libclang.so.19"],
    }[config.system]

    if _already_present(config.dest_dir, expected_names):
        print("✓ libclang already present, skipping download")
        return True

    temp_file = Path(tempfile.gettempdir()) / "llvm-libclang.tar.xz"
    print(f"Downloading LLVM archive from {config.url} ...")

    try:
        urllib.request.urlretrieve(config.url, temp_file)
    except Exception as exc:
        print(f"✗ Download failed: {exc}")
        print("Please download the archive manually and extract libclang into:")
        print(f"  {config.dest_dir}")
        return False

    print("✓ Download complete, extracting...")

    with tarfile.open(temp_file, "r:xz") as tar:
        with tempfile.TemporaryDirectory() as extract_dir:
            tar.extractall(extract_dir)
            success = _copy_libclang(Path(extract_dir), config)

    try:
        temp_file.unlink()
    except OSError:
        pass

    if success:
        print("✓ libclang ready for use")
    else:
        print("✗ libclang setup failed")

    return success


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Download libclang for the MCP server")
    parser.add_argument(
        "--system",
        choices=["windows", "linux", "darwin"],
        help="Override detected operating system",
    )
    args = parser.parse_args(argv)

    success = download_libclang(args.system)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
