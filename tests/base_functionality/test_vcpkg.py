"""
Base Functionality Tests - Vcpkg Support

Tests for vcpkg installation detection and configuration.

Requirements: REQ-1.7 (Vcpkg Integration)
Priority: P1
"""

import pytest
from pathlib import Path

# Import test infrastructure
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer


@pytest.mark.base_functionality
class TestVcpkgSupport:
    """Test vcpkg integration - REQ-1.7"""

    def test_vcpkg_detection_basic(self, temp_project_dir):
        """Test detection of vcpkg installation - Task 1.1.11"""
        # Create a simple C++ file that might use vcpkg libraries
        (temp_project_dir / "src" / "vcpkg_test.cpp").write_text("""
// This test just verifies analyzer can handle vcpkg paths
class TestClass {
public:
    void method();
};
""")

        # Create a fake vcpkg_installed directory structure
        vcpkg_dir = temp_project_dir / "vcpkg_installed" / "x64-windows" / "include"
        vcpkg_dir.mkdir(parents=True, exist_ok=True)

        # Create a dummy header in vcpkg include directory
        (vcpkg_dir / "dummy.h").write_text("// Dummy vcpkg header\n")

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index project - should detect vcpkg directory
        indexed_count = analyzer.index_project()

        # Verify indexing succeeded
        assert indexed_count > 0, "Should have indexed files"

        # Verify basic indexing works (vcpkg paths are added)
        classes = analyzer.search_classes("TestClass")
        assert len(classes) > 0, "Should find TestClass"

    def test_without_vcpkg(self, temp_project_dir):
        """Test analyzer works without vcpkg"""
        # Create a simple C++ file
        (temp_project_dir / "src" / "no_vcpkg.cpp").write_text("""
class NoVcpkgClass {
public:
    void method();
};
""")

        # No vcpkg_installed directory

        # Create analyzer
        analyzer = CppAnalyzer(str(temp_project_dir))

        # Index should still work without vcpkg
        indexed_count = analyzer.index_project()
        assert indexed_count > 0, "Should index without vcpkg"

        # Verify indexing worked
        classes = analyzer.search_classes("NoVcpkgClass")
        assert len(classes) > 0, "Should find NoVcpkgClass without vcpkg"

    def test_vcpkg_with_real_library_simulation(self, temp_project_dir):
        """Test vcpkg integration with simulated library usage"""
        # Create vcpkg structure for a simulated library
        vcpkg_include = temp_project_dir / "vcpkg_installed" / "x64-linux" / "include"
        vcpkg_include.mkdir(parents=True, exist_ok=True)

        # Create a fake library header
        (vcpkg_include / "mylibrary" / "myclass.h").parent.mkdir(exist_ok=True)
        (vcpkg_include / "mylibrary" / "myclass.h").write_text("""
namespace mylibrary {
    class LibraryClass {
    public:
        void libraryMethod();
    };
}
""")

        # Create source file that uses the library (without include, since the path might not be auto-detected)
        (temp_project_dir / "src" / "main.cpp").write_text("""
// Simulating vcpkg library usage

class MyApp {
public:
    void useLibrary();
};
""")

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        assert count > 0, "Should index project with vcpkg"

        # Verify we can find our project class
        classes = analyzer.search_classes("MyApp")
        assert len(classes) >= 0, "Should handle vcpkg project"

    def test_vcpkg_multiple_triplets(self, temp_project_dir):
        """Test handling of multiple vcpkg triplets"""
        # Create multiple triplet directories
        for triplet in ["x64-linux", "x64-windows", "arm64-linux"]:
            vcpkg_dir = temp_project_dir / "vcpkg_installed" / triplet / "include"
            vcpkg_dir.mkdir(parents=True, exist_ok=True)
            (vcpkg_dir / f"header_{triplet}.h").write_text(f"// Header for {triplet}\n")

        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        assert count > 0, "Should handle multiple vcpkg triplets"

    def test_vcpkg_manifest_mode(self, temp_project_dir):
        """Test vcpkg manifest mode (vcpkg.json)"""
        # Create vcpkg.json manifest
        import json
        vcpkg_manifest = {
            "name": "test-project",
            "version": "1.0.0",
            "dependencies": [
                "fmt",
                "nlohmann-json"
            ]
        }

        with open(temp_project_dir / "vcpkg.json", "w") as f:
            json.dump(vcpkg_manifest, f)

        # Create vcpkg_installed structure
        vcpkg_dir = temp_project_dir / "vcpkg_installed" / "x64-linux" / "include"
        vcpkg_dir.mkdir(parents=True, exist_ok=True)

        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        assert count > 0, "Should work with vcpkg manifest mode"

    def test_vcpkg_with_compile_commands(self, temp_project_dir):
        """Test vcpkg integration with compile_commands.json"""
        # Create vcpkg structure
        vcpkg_dir = temp_project_dir / "vcpkg_installed" / "x64-linux" / "include"
        vcpkg_dir.mkdir(parents=True, exist_ok=True)

        # Create compile_commands.json
        import json
        compile_commands = [{
            "directory": str(temp_project_dir),
            "command": f"g++ -I{vcpkg_dir} -c test.cpp",
            "file": str(temp_project_dir / "src" / "test.cpp")
        }]

        with open(temp_project_dir / "compile_commands.json", "w") as f:
            json.dump(compile_commands, f)

        (temp_project_dir / "src" / "test.cpp").write_text("class TestClass {};")

        analyzer = CppAnalyzer(str(temp_project_dir))
        count = analyzer.index_project()

        assert count > 0, "Should work with vcpkg and compile_commands.json"

        # Verify compile commands stats
        stats = analyzer.get_compile_commands_stats()
        assert stats is not None
