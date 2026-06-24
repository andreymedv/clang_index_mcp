"""
Clang resource directory and C++ standard-library detection.

These helpers locate clang builtin headers, libc++/libstdc++ include paths,
and system C headers so that libclang can parse code outside a normal
compiler invocation.
"""

import glob
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Handle both package and script imports
try:
    from .._core import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


def build_fallback_args(project_root: Path, clang_resource_dir: Optional[str]) -> List[str]:
    """Build the fallback compilation arguments (current hardcoded approach)."""
    args = [
        "-std=c++17",
    ]

    # Add clang builtin includes first (highest priority for system headers)
    if clang_resource_dir:
        args.extend(["-isystem", clang_resource_dir])

    args.extend(
        [
            "-I.",
            f"-I{project_root}",
            f"-I{project_root}/src",
            # Preprocessor defines for common libraries
            "-DWIN32",
            "-D_WIN32",
            "-D_WINDOWS",
            "-DNOMINMAX",
            # Common warnings to suppress
            "-Wno-pragma-once-outside-header",
            "-Wno-unknown-pragmas",
            "-Wno-deprecated-declarations",
            # Parse as C++
            "-x",
            "c++",
        ]
    )

    # Add Windows SDK includes if on Windows
    if sys.platform.startswith("win"):
        winsdk_patterns = [
            "C:/Program Files (x86)/Windows Kits/10/Include/*/ucrt",
            "C:/Program Files (x86)/Windows Kits/10/Include/*/um",
            "C:/Program Files (x86)/Windows Kits/10/Include/*/shared",
        ]
        for pattern in winsdk_patterns:
            matches = glob.glob(pattern)
            if matches:
                args.append(f"-I{matches[-1]}")  # Use latest version

    return args


def validate_resource_dir(include_dir: str) -> bool:
    """Check if a directory contains the required builtin headers."""
    return os.path.isdir(include_dir) and os.path.isfile(os.path.join(include_dir, "stddef.h"))


def get_resource_dir_from_clang() -> Optional[str]:
    """Try to get the clang resource directory by invoking clang directly."""
    try:
        result = subprocess.run(
            ["clang", "-print-resource-dir"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            include_dir = os.path.join(result.stdout.strip(), "include")
            if validate_resource_dir(include_dir):
                diagnostics.debug(f"Found clang resource directory: {include_dir}")
                return include_dir
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        diagnostics.debug(f"Clang execution failed, trying fallback locations: {e}")
    return None


def find_resource_dir_in_common_locations() -> Optional[str]:
    """Search for the clang resource directory in common system locations."""
    clang_lib_dir = "/usr/lib/clang"
    if not os.path.isdir(clang_lib_dir):
        return None

    versions = []
    for entry in os.listdir(clang_lib_dir):
        include_dir = os.path.join(clang_lib_dir, entry, "include")
        if validate_resource_dir(include_dir):
            versions.append((entry, include_dir))

    if versions:
        versions.sort(reverse=True)
        include_dir = versions[0][1]
        diagnostics.debug(f"Found clang resource directory (fallback): {include_dir}")
        return include_dir

    return None


def detect_clang_resource_dir() -> Optional[str]:
    """
    Detect the clang resource directory containing builtin headers.

    The resource directory contains compiler builtin headers like:
    - stddef.h
    - stdarg.h
    - stdint.h
    etc.

    These are required for libclang to parse code correctly but are not
    automatically included when using libclang programmatically.

    Returns:
        Path to the resource directory's include folder, or None if not found
    """
    try:
        include_dir = get_resource_dir_from_clang()
        if include_dir is not None:
            return include_dir

        include_dir = find_resource_dir_in_common_locations()
        if include_dir is not None:
            return include_dir

        diagnostics.warning(
            "Could not detect clang resource directory - builtin headers may not be found"
        )
        return None

    except Exception as e:
        diagnostics.warning(f"Error detecting clang resource directory: {e}")
        return None


def get_libcxx_path(sysroot: Optional[str]) -> Optional[str]:
    """Get the path for libc++ headers."""
    if sysroot:
        cxx_path = os.path.join(sysroot, "usr", "include", "c++", "v1")
        # Return the path even if directory doesn't exist on current system
        # (e.g., when analyzing macOS code on Linux)
        # libclang will handle missing directories gracefully
        return cxx_path

    # Try system paths
    system_paths = ["/usr/include/c++/v1", "/usr/local/include/c++/v1"]
    for path in system_paths:
        if os.path.isdir(path):
            return path
    return None


def get_libstdcxx_path(sysroot: Optional[str]) -> Optional[str]:
    """Get the path for libstdc++ headers."""
    if sysroot:
        cxx_base = os.path.join(sysroot, "usr", "include", "c++")
        if os.path.isdir(cxx_base):
            # Find the highest version directory
            try:
                versions = [
                    d
                    for d in os.listdir(cxx_base)
                    if os.path.isdir(os.path.join(cxx_base, d)) and d[0].isdigit()
                ]
                if versions:
                    versions.sort(reverse=True)
                    return os.path.join(cxx_base, versions[0])
            except Exception:
                pass
    return None


def get_bundled_cxx_stdlib_path() -> Optional[str]:
    """Get C++ stdlib include path from bundled libclang directory.

    When libclang is bundled with C++ standard library headers (e.g.
    libclang/include/c++/v1/), return that path so libclang can
    resolve standard headers like <cstdio>, <vector>, etc.
    """
    # Handle both package and script imports
    try:
        from clang.cindex import Config
    except ImportError:
        return None

    lib_file = getattr(Config, "library_file", None)
    lib_path = getattr(Config, "library_path", None)

    bundled_dir = None
    if lib_file:
        # libclang.dylib -> go up to lib/<platform>/lib/ then to lib/<platform>/
        bundled_dir = os.path.dirname(os.path.dirname(lib_file))
    elif lib_path:
        # library_path is the dir containing libclang.so/dylib
        bundled_dir = os.path.dirname(lib_path)

    if not bundled_dir:
        return None

    cxx_path = os.path.join(bundled_dir, "include", "c++", "v1")
    if os.path.isdir(cxx_path):
        diagnostics.debug(f"Found bundled C++ stdlib includes: {cxx_path}")
        return cxx_path

    return None


def detect_system_c_headers_dir(clang_resource_dir: Optional[str]) -> Optional[str]:
    """Detect the system C header directory for #include_next resolution.

    When using bundled libc++ headers, the wrapper headers (like stdio.h)
    use #include_next to find the real system C headers. This requires the
    system C header directory to be in the include search path.
    """
    if clang_resource_dir:
        # Derive from resource dir: .../usr/lib/clang/X.Y.Z/include -> .../usr/include
        # Go up from include/ to clang/X.Y.Z/ to lib/ to usr/ then to include/
        clang_lib = os.path.dirname(clang_resource_dir)  # .../clang/X.Y.Z
        usr_dir = os.path.dirname(os.path.dirname(clang_lib))  # .../usr
        c_headers = os.path.join(usr_dir, "include")
        if os.path.isdir(c_headers):
            return c_headers

    # Fallback: search SDK paths on macOS
    sdk_patterns = [
        "/Library/Developer/CommandLineTools/SDKs/MacOSX*.sdk/usr/include",
        "/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX*.sdk/usr/include",
    ]
    for pattern in sdk_patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]

    return None


def extract_stdlib_and_sysroot(arguments: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract -stdlib and -isysroot flags from arguments."""
    stdlib = None
    sysroot = None

    # Detect -stdlib flag
    for i, arg in enumerate(arguments):
        if arg == "-stdlib" and i + 1 < len(arguments):
            stdlib = arguments[i + 1]
        elif arg.startswith("-stdlib="):
            stdlib = arg[8:]  # Remove '-stdlib=' prefix

    # Detect -isysroot flag
    for i, arg in enumerate(arguments):
        if arg == "-isysroot" and i + 1 < len(arguments):
            sysroot = arguments[i + 1]
        elif arg.startswith("-isysroot="):
            sysroot = arg[10:]  # Remove '-isysroot=' prefix

    return stdlib, sysroot


def detect_cxx_stdlib_path(arguments: List[str]) -> Optional[str]:
    """
    Detect the C++ standard library include path based on compile arguments.

    When using libclang programmatically, the C++ standard library headers
    are not automatically found even when -stdlib and -isysroot are specified.
    We need to explicitly add the C++ stdlib include path.

    Args:
        arguments: List of compilation arguments

    Returns:
        Path to C++ standard library includes, or None if not found
    """
    stdlib, sysroot = extract_stdlib_and_sysroot(arguments)

    # If no stdlib specified, assume system default
    # For macOS, this is typically libc++
    if not stdlib and sysroot:
        # On macOS, default is libc++
        if "MacOSX" in sysroot or "macos" in sysroot.lower():
            stdlib = "libc++"

    if stdlib:
        # Build the C++ stdlib include path from stdlib/sysroot info
        if stdlib == "libc++":
            path = get_libcxx_path(sysroot)
            if path:
                return path
        elif stdlib == "libstdc++":
            path = get_libstdcxx_path(sysroot)
            if path:
                return path

    # Fallback: check bundled includes shipped with the project
    return get_bundled_cxx_stdlib_path()


def find_std_insert_position(arguments: List[str]) -> int:
    """Find insertion position after -std= flag if present."""
    for i, arg in enumerate(arguments):
        if arg.startswith("-std="):
            return i + 1
    return 0


def is_path_in_args(path: str, arguments: List[str]) -> bool:
    """Check if a path is already present in arguments."""
    for arg in arguments:
        if path in arg:
            return True
    return False


def insert_system_include(arguments: List[str], insert_pos: int, path: str) -> int:
    """Insert -isystem path at insert_pos and return updated position."""
    arguments.insert(insert_pos, "-isystem")
    arguments.insert(insert_pos + 1, path)
    return insert_pos + 2


def add_builtin_includes(arguments: List[str], clang_resource_dir: Optional[str]) -> List[str]:
    """
    Add clang builtin include directory and C++ stdlib to arguments if not already present.

    This is necessary for libclang to find compiler builtin headers like:
    - stddef.h
    - stdarg.h
    - stdint.h

    And C++ standard library headers like:
    - <iostream>
    - <vector>
    - <string>

    These headers are not automatically available when using libclang
    programmatically, unlike when using the clang compiler directly.

    IMPORTANT: The C++ stdlib path MUST come before the clang resource directory.
    This is because C++ wrapper headers (like <cstddef>) need to include the C++
    version of C headers, not the plain C versions.

    Args:
        arguments: List of compilation arguments

    Returns:
        Arguments with builtin include directory added if needed
    """
    result = arguments.copy()
    insert_pos = find_std_insert_position(result)

    cxx_stdlib_path = detect_cxx_stdlib_path(arguments)
    if cxx_stdlib_path and not is_path_in_args(cxx_stdlib_path, result):
        insert_pos = insert_system_include(result, insert_pos, cxx_stdlib_path)
        diagnostics.debug(f"Added C++ stdlib path: {cxx_stdlib_path}")

        # When using bundled C++ stdlib, the wrapper headers (e.g. stdio.h)
        # use #include_next to find system C headers. Add the system C
        # header directory so #include_next can resolve them.
        system_c_dir = detect_system_c_headers_dir(clang_resource_dir)
        if system_c_dir and not is_path_in_args(system_c_dir, result):
            insert_pos = insert_system_include(result, insert_pos, system_c_dir)
            diagnostics.debug(f"Added system C headers: {system_c_dir}")

    if clang_resource_dir and not is_path_in_args(clang_resource_dir, result):
        insert_system_include(result, insert_pos, clang_resource_dir)
        diagnostics.debug(f"Added clang resource dir: {clang_resource_dir}")

    return result
