"""Shared libclang discovery/configuration for MCP server and scripts."""

import os

from clang.cindex import Config

# Handle both package and script imports
try:
    from . import diagnostics
except ImportError:
    import diagnostics  # type: ignore[no-redef]


def configure_libclang() -> bool:
    """Find and configure libclang library using hybrid discovery approach."""
    # If already loaded, keep current configuration.
    if Config.loaded:
        diagnostics.info("libclang already loaded; keeping existing configuration")
        return True

    import glob
    import platform
    import shutil
    import subprocess

    system = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)

    env_path = os.environ.get("LIBCLANG_PATH")
    if env_path and os.path.exists(env_path):
        if os.path.isdir(env_path):
            diagnostics.info(f"Using libclang search path from LIBCLANG_PATH: {env_path}")
            Config.set_library_path(env_path)
        else:
            diagnostics.info(f"Using libclang from LIBCLANG_PATH: {env_path}")
            Config.set_library_file(env_path)
        return True
    elif env_path:
        diagnostics.warning(f"LIBCLANG_PATH set but path not found: {env_path}")

    lib_path = os.environ.get("CLANG_LIBRARY_PATH")
    if lib_path and os.path.exists(lib_path) and os.path.isdir(lib_path):
        diagnostics.info(f"Using libclang search path from CLANG_LIBRARY_PATH: {lib_path}")
        Config.set_library_path(lib_path)
        return True
    elif lib_path:
        diagnostics.warning(f"CLANG_LIBRARY_PATH set but directory not found: {lib_path}")

    if system == "Darwin":
        try:
            result = subprocess.run(
                ["xcrun", "--find", "clang"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                clang_path = result.stdout.strip()
                clang_dir = os.path.dirname(os.path.dirname(clang_path))
                libclang_path = os.path.join(clang_dir, "lib", "libclang.dylib")
                if os.path.exists(libclang_path):
                    diagnostics.info(f"Found libclang via xcrun: {libclang_path}")
                    Config.set_library_file(libclang_path)
                    return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    diagnostics.info("Searching for system-installed libclang...")

    platform_config = {
        "Windows": {
            "lib_names": ["libclang.dll", "clang.dll"],
            "system_paths": [
                r"C:\Program Files\LLVM\bin",
                r"C:\Program Files (x86)\LLVM\bin",
                r"C:\vcpkg\installed\x64-windows\bin",
                r"C:\vcpkg\installed\x86-windows\bin",
                r"C:\ProgramData\Anaconda3\Library\bin",
            ],
            "llvm_config_query": "--libdir",
        },
        "Darwin": {
            "lib_names": ["libclang.dylib"],
            "system_paths": [
                "/Library/Developer/CommandLineTools/usr/lib",
                "/opt/homebrew/Cellar/llvm/*/lib",
                "/opt/homebrew/Cellar/llvm@*/*/lib",
                "/opt/homebrew/lib",
                "/usr/local/Cellar/llvm/*/lib",
                "/usr/local/Cellar/llvm@*/*/lib",
                "/usr/local/lib",
                "/opt/local/libexec/llvm-*/lib",
                "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib",
            ],
            "llvm_config_query": "--libdir",
        },
        "Linux": {
            "lib_names": ["libclang.so.1", "libclang.so"],
            "system_paths": [
                "/usr/lib/llvm-*/lib",
                "/usr/lib/x86_64-linux-gnu",
                "/usr/lib",
            ],
            "llvm_config_query": "--libdir",
        },
    }

    config = platform_config.get(system, platform_config["Linux"])
    lib_names = config["lib_names"]
    system_base_paths = list(config["system_paths"])

    llvm_config = shutil.which("llvm-config")
    if llvm_config:
        try:
            result = subprocess.run(
                [llvm_config, str(config["llvm_config_query"])],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lib_dir = result.stdout.strip()
                if os.path.exists(lib_dir):
                    system_base_paths.insert(0, lib_dir)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    for base_path in system_base_paths:
        for lib_name in lib_names:
            path_pattern = os.path.join(base_path, lib_name)
            if "*" in path_pattern:
                paths_to_check = sorted(glob.glob(path_pattern), reverse=True)
            else:
                paths_to_check = [path_pattern]

            for path in paths_to_check:
                if os.path.exists(path):
                    diagnostics.info(f"Found system libclang at: {path}")
                    Config.set_library_file(path)
                    return True

    diagnostics.info("No system libclang found, trying bundled libraries...")
    bundled_subdirs = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    platform_subdir = bundled_subdirs.get(system, "linux")

    for lib_name in lib_names:
        path = os.path.join(parent_dir, "lib", platform_subdir, "lib", lib_name)
        if os.path.exists(path):
            diagnostics.info(f"Using bundled libclang at: {path}")
            Config.set_library_file(path)
            return True

    return False


def get_libclang_runtime_info() -> dict:
    """Return the current libclang runtime settings for diagnostics."""
    return {
        "loaded": bool(Config.loaded),
        "library_file": getattr(Config, "library_file", None),
        "library_path": getattr(Config, "library_path", None),
    }
