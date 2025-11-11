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
LIBTINFO_DEB_URL = "https://deb.debian.org/debian/pool/main/n/ncurses/libtinfo5_6.4-4_amd64.deb"


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
        return DownloadConfig(
            system="macOS",
            archive_name=f"LLVM-{LLVM_VERSION}-macOS-ARM64.tar.xz",
            lib_paths=("lib/libclang.dylib",),
            dest_dir=base_dir / "macos",
        )

    # Default to Linux (x86_64)
    return DownloadConfig(
        system="Linux",
        archive_name=f"LLVM-{LLVM_VERSION}-Linux-X64.tar.xz",
        lib_paths=(
            "lib/libclang.so.19",
            "lib/libclang.so.18",
            "lib/libclang.so.17",
            "lib/libclang.so.16",
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


def _find_system_libtinfo() -> Optional[Path]:
    """Locate a libtinfo shared library on the host system."""

    search_dirs = [
        Path("/lib"),
        Path("/lib64"),
        Path("/usr/lib"),
        Path("/usr/lib64"),
        Path("/lib/x86_64-linux-gnu"),
        Path("/usr/lib/x86_64-linux-gnu"),
    ]

    candidates = []
    pattern = re.compile(r"libtinfo\.so\.(\d+(?:\.\d+)*)")

    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in directory.glob("libtinfo.so.*"):
            if path.is_symlink():
                continue  # Prefer real files to avoid copying symlinks
            match = pattern.match(path.name)
            if match:
                version = tuple(int(part) for part in match.group(1).split('.'))
                candidates.append((version, path))

    if not candidates:
        return None

    # Return the highest version available
    candidates.sort(reverse=True)
    return candidates[0][1]


def _download_libtinfo(dest_dir: Path) -> bool:
    """Download a compatible libtinfo build and copy it into the destination."""

    try:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            deb_path = temp_dir / "libtinfo5.deb"
            print(f"Downloading libtinfo from {LIBTINFO_DEB_URL} ...")
            urllib.request.urlretrieve(LIBTINFO_DEB_URL, deb_path)

            # Extract the deb (ar archive)
            result = subprocess.run(["ar", "x", str(deb_path)], cwd=temp_dir, capture_output=True)
            if result.returncode != 0:
                print("⚠ Failed to extract libtinfo archive (missing 'ar' tool?)", file=sys.stderr)
                return False

            data_tar = temp_dir / "data.tar.xz"
            if not data_tar.exists():
                print("⚠ libtinfo package did not contain data.tar.xz", file=sys.stderr)
                return False

            with tarfile.open(data_tar, "r:xz") as tar:
                tar.extractall(temp_dir)

            lib_dirs = [
                temp_dir / "usr/lib/x86_64-linux-gnu",
                temp_dir / "lib/x86_64-linux-gnu",
            ]

            copied_any = False
            for lib_dir in lib_dirs:
                if not lib_dir.exists():
                    continue

                for candidate in lib_dir.glob("libtinfo.so*"):
                    dest_path = dest_dir / candidate.name
                    if candidate.is_symlink():
                        link_target = os.readlink(candidate)
                        try:
                            os.symlink(link_target, dest_path)
                        except FileExistsError:
                            pass
                        continue

                    shutil.copy2(candidate, dest_path)
                    copied_any = True
                    print(f"✓ Copied {candidate.name} to {dest_path}")

            if not copied_any:
                print("⚠ libtinfo package did not contain expected files", file=sys.stderr)
                return False

            return True

    except Exception as exc:
        print(f"⚠ Failed to download libtinfo: {exc}", file=sys.stderr)

    return False


def _ensure_linux_dependencies(config: DownloadConfig) -> None:
    """Ensure additional shared library dependencies are available on Linux."""

    if config.system != "Linux":
        return

    dest_dir = config.dest_dir

    # Skip if libtinfo already present (copy or symlink)
    if any(dest_dir.glob("libtinfo.so*")):
        return

    system_libtinfo = _find_system_libtinfo()
    if system_libtinfo and system_libtinfo.name.startswith("libtinfo.so.5"):
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied_name = system_libtinfo.name
        target_path = dest_dir / copied_name

        try:
            shutil.copy2(system_libtinfo, target_path)
            print(f"✓ Copied {copied_name} to {target_path}")
        except Exception as exc:
            print(f"⚠ Failed to copy libtinfo from {system_libtinfo}: {exc}", file=sys.stderr)
            return

        source_name = copied_name
    else:
        if not _download_libtinfo(dest_dir):
            print(
                "⚠ Could not provision libtinfo automatically. Install 'libtinfo5' or copy libtinfo.so.5 manually.",
                file=sys.stderr,
            )
            return
        # Use the copied file as target for symlinks
        candidates = sorted(dest_dir.glob("libtinfo.so.*"))
        source_name = candidates[-1].name if candidates else ""

    if not source_name:
        return

    # Provide compatibility symlinks expected by libclang builds
    for link_name in ["libtinfo.so.6", "libtinfo.so.5"]:
        link_path = dest_dir / link_name
        if link_path.exists():
            continue
        try:
            os.symlink(source_name, link_path)
            print(f"✓ Created symlink {link_path} -> {source_name}")
        except OSError as exc:
            print(f"⚠ Failed to create symlink {link_path}: {exc}", file=sys.stderr)


def download_libclang(system_override: Optional[str] = None) -> bool:
    """Download and extract a libclang build for the current platform."""

    config = get_download_config(system_override)
    print(f"Setting up libclang for {config.system}...")
    _ensure_directory(config.dest_dir)

    expected_names = {
        "Windows": ["libclang.dll"],
        "macOS": ["libclang.dylib"],
        "Linux": ["libclang.so", "libclang.so.1", "libclang.so.18"],
    }[config.system]

    if _already_present(config.dest_dir, expected_names):
        print("✓ libclang already present, skipping download")
        _ensure_linux_dependencies(config)
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
            if success:
                _ensure_linux_dependencies(config)

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
