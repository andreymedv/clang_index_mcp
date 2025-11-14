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
