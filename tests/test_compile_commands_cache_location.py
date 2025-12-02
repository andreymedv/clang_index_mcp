#!/usr/bin/env python3
"""Test script to verify compile_commands cache works with multiple builds."""

import tempfile
import json
from pathlib import Path
from mcp_server.cpp_analyzer import CppAnalyzer
from mcp_server.project_identity import ProjectIdentity
from mcp_server.cache_manager import CacheManager

def test_multiple_builds():
    """Test that different compile_commands.json paths get different caches."""

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Create source files
        (project_root / "src").mkdir()
        (project_root / "src" / "main.cpp").write_text("int main() {}")

        # Create two different build directories with compile_commands.json
        build_debug = project_root / "build.debug"
        build_release = project_root / "build.release"
        build_debug.mkdir()
        build_release.mkdir()

        # Debug compile_commands.json
        debug_cc = [
            {
                "directory": str(build_debug),
                "command": "g++ -g -DDEBUG main.cpp",
                "file": str(project_root / "src" / "main.cpp")
            }
        ]
        (build_debug / "compile_commands.json").write_text(json.dumps(debug_cc))

        # Release compile_commands.json
        release_cc = [
            {
                "directory": str(build_release),
                "command": "g++ -O3 -DNDEBUG main.cpp",
                "file": str(project_root / "src" / "main.cpp")
            }
        ]
        (build_release / "compile_commands.json").write_text(json.dumps(release_cc))

        # Create configs pointing to different compile_commands.json
        debug_config = {
            "compile_commands_enabled": True,
            "compile_commands_path": "build.debug/compile_commands.json"
        }
        release_config = {
            "compile_commands_enabled": True,
            "compile_commands_path": "build.release/compile_commands.json"
        }

        debug_config_path = project_root / ".cpp-analyzer-config-debug.json"
        release_config_path = project_root / ".cpp-analyzer-config-release.json"
        debug_config_path.write_text(json.dumps(debug_config))
        release_config_path.write_text(json.dumps(release_config))

        # Create analyzers with different configs
        print("Creating debug analyzer...")
        debug_identity = ProjectIdentity(project_root, debug_config_path)
        debug_cache_mgr = CacheManager(debug_identity)
        debug_analyzer = CppAnalyzer(str(project_root), str(debug_config_path))

        print("Creating release analyzer...")
        release_identity = ProjectIdentity(project_root, release_config_path)
        release_cache_mgr = CacheManager(release_identity)
        release_analyzer = CppAnalyzer(str(project_root), str(release_config_path))

        # Get cache paths
        debug_cc_path = debug_analyzer.compile_commands_manager.project_root / debug_analyzer.compile_commands_manager.compile_commands_path
        release_cc_path = release_analyzer.compile_commands_manager.project_root / release_analyzer.compile_commands_manager.compile_commands_path

        print(f"\nDebug compile_commands.json:   {debug_cc_path}")
        print(f"Release compile_commands.json: {release_cc_path}")

        debug_cc_cache = debug_analyzer.compile_commands_manager._get_compile_commands_cache_path()
        release_cc_cache = release_analyzer.compile_commands_manager._get_compile_commands_cache_path()

        print(f"\nDebug cache:   {debug_cc_cache}")
        print(f"Release cache: {release_cc_cache}")

        # Verify they're different
        assert debug_cc_cache != release_cc_cache, \
            "Different compile_commands.json should get different cache files!"

        # Verify they're both in .mcp_cache
        assert ".mcp_cache" in str(debug_cc_cache), \
            "Debug cache should be in .mcp_cache"
        assert ".mcp_cache" in str(release_cc_cache), \
            "Release cache should be in .mcp_cache"

        # Verify they're in compile_commands subdirectory
        assert debug_cc_cache.parent.name == "compile_commands", \
            "Cache should be in compile_commands subdirectory"
        assert release_cc_cache.parent.name == "compile_commands", \
            "Cache should be in compile_commands subdirectory"

        print("\n✅ SUCCESS: Different builds get different compile_commands caches!")
        print(f"   Debug uses:   {debug_cc_cache.name}")
        print(f"   Release uses: {release_cc_cache.name}")


if __name__ == "__main__":
    test_multiple_builds()
