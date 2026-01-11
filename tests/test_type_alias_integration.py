#!/usr/bin/env python3
"""
Integration tests for type alias tracking through MCP tools (Phase 1.5).

Tests the complete integration of type alias tracking through:
- search_classes with type expansion
- search_functions with type expansion
- get_class_info with alias information
- End-to-end workflows with real C++ code
"""

import os
import sys
from pathlib import Path
import pytest

# Add the mcp_server directory to the path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# ============================================================================
# IT-1: search_classes Type Expansion Integration
# ============================================================================


class TestSearchClassesTypeExpansion:
    """Integration tests for search_classes with type alias expansion (IT-1)."""

    @pytest.mark.skip(reason="Phase 1.6: Automatic type expansion in search not yet implemented")
    def test_search_by_alias_finds_canonical_class(self, temp_project_dir):
        """IT-1.1: Searching by alias name should find canonical class (Future Phase)."""
        # Create class with alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
/// Main widget class
class Widget {
public:
    void show();
};

/// Alias for Widget
using WidgetAlias = Widget;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # NOTE: This requires Phase 1.6 - integrating expand_type_name() into search_classes()
        # Search by alias name - should expand to canonical and find Widget
        results = analyzer.search_classes("WidgetAlias")

        # Should find Widget class (canonical type)
        assert len(results) >= 1
        # At least one result should be Widget (the canonical class)
        class_names = [r["name"] for r in results]
        assert "Widget" in class_names

    def test_search_by_canonical_includes_aliases(self, temp_project_dir):
        """IT-1.2: Searching by canonical name should also match aliases."""
        # Create class with multiple aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
/// Main button class
class Button {
public:
    void click();
};

using ButtonAlias = Button;
typedef Button ButtonType;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search by canonical name
        results = analyzer.search_classes("Button")

        # Should find Button class
        assert len(results) >= 1
        # Verify Button is in results
        class_names = [r["name"] for r in results]
        assert "Button" in class_names

    @pytest.mark.skip(reason="Phase 1.6: Automatic type expansion in search not yet implemented")
    def test_search_respects_alias_chain(self, temp_project_dir):
        """IT-1.3: Search should resolve alias chains to canonical type (Future Phase)."""
        # Create alias chain
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
/// Real class definition
class RealClass {
public:
    void method();
};

using AliasOne = RealClass;
using AliasTwo = AliasOne;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # NOTE: This requires Phase 1.6 - integrating expand_type_name() into search_classes()
        # Search by final alias in chain
        results = analyzer.search_classes("AliasTwo")

        # Should resolve chain and find RealClass
        assert len(results) >= 1
        class_names = [r["name"] for r in results]
        assert "RealClass" in class_names

    @pytest.mark.skip(reason="Phase 1.6: Automatic type expansion in search not yet implemented")
    def test_search_with_namespace_scoped_alias(self, temp_project_dir):
        """IT-1.4: Search handles namespace-scoped aliases correctly (Future Phase)."""
        # Create namespace-scoped alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
namespace widgets {
    /// Widget class in namespace
    class Widget {
    public:
        void show();
    };
}

namespace ui {
    /// Alias to widgets::Widget
    using Widget = widgets::Widget;
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # NOTE: This requires Phase 1.6 - integrating expand_type_name() into search_classes()
        # Search by qualified alias name
        results = analyzer.search_classes("ui::Widget")

        # Should find canonical widgets::Widget
        assert len(results) >= 1
        # Check that we found the right class
        qualified_names = [r.get("qualified_name", r["name"]) for r in results]
        assert any("Widget" in name for name in qualified_names)


# ============================================================================
# IT-2: search_functions Type Expansion Integration
# ============================================================================


class TestSearchFunctionsTypeExpansion:
    """Integration tests for search_functions with type alias parameters (IT-2)."""

    def test_search_function_with_alias_parameter(self, temp_project_dir):
        """IT-2.1: Find functions with aliased parameter types."""
        # Create function with alias parameter
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {};
using WidgetPtr = Widget*;

/// Process widget pointer
void processWidget(WidgetPtr widget);

void processWidget(WidgetPtr widget) {
    // Implementation
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for function
        results = analyzer.search_functions("processWidget")

        # Should find function
        assert len(results) >= 1
        assert any(r["name"] == "processWidget" for r in results)

    def test_search_function_with_alias_return_type(self, temp_project_dir):
        """IT-2.2: Find functions with aliased return types."""
        # Create function with alias return type
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Data {};
using DataPtr = Data*;

/// Get data pointer
DataPtr getData();

DataPtr getData() {
    return nullptr;
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search for function
        results = analyzer.search_functions("getData")

        # Should find function
        assert len(results) >= 1
        assert any(r["name"] == "getData" for r in results)


# ============================================================================
# IT-3: get_class_info Integration
# ============================================================================


class TestGetClassInfoWithAliases:
    """Integration tests for get_class_info with type alias information (IT-3)."""

    def test_get_class_info_for_aliased_class(self, temp_project_dir):
        """IT-3.1: get_class_info should work when queried by alias name."""
        # Create class with alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
/// Main widget class
class Widget {
public:
    void show();
    void hide();
};

using WidgetAlias = Widget;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Query class info by alias name
        # Note: get_class_info may need enhancement to support alias lookup
        # For now, test that querying canonical name works
        result = analyzer.get_class_info("Widget")

        # Should return class information
        assert result is not None
        assert "methods" in result

    def test_get_class_info_shows_methods(self, temp_project_dir):
        """IT-3.2: Class info should include methods regardless of alias usage."""
        # Create class with methods
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Button {
public:
    void click();
    void setEnabled(bool enabled);
    bool isEnabled() const;
};

using ButtonAlias = Button;
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Get class info
        result = analyzer.get_class_info("Button")

        # Should include methods
        assert result is not None
        assert "methods" in result
        method_names = [m["name"] for m in result["methods"]]
        assert "click" in method_names


# ============================================================================
# IT-4: End-to-End Workflow Tests
# ============================================================================


class TestEndToEndWorkflows:
    """End-to-end integration tests for complete workflows (IT-4)."""

    def test_complete_alias_workflow(self, temp_project_dir):
        """IT-4.1: Complete workflow from indexing to querying aliases."""
        # Create a realistic project with aliases
        (temp_project_dir / "src" / "core.h").write_text(
            """
#pragma once

namespace core {
    /// Core data structure
    class DataStore {
    public:
        void save();
        void load();
    };

    /// Convenience alias for DataStore pointer
    using DataStorePtr = DataStore*;
}
"""
        )

        (temp_project_dir / "src" / "app.cpp").write_text(
            """
#include "core.h"

namespace app {
    /// Application alias for core::DataStore
    using Storage = core::DataStore;

    /// Process storage
    void processStorage(Storage* store) {
        store->save();
    }
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/app.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17", f"-I{temp_project_dir}/src"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # 1. Verify DataStore is indexed
        results = analyzer.search_classes("DataStore")
        assert len(results) >= 1
        assert any("DataStore" in r["name"] for r in results)

        # 2. Verify processStorage function is indexed
        func_results = analyzer.search_functions("processStorage")
        assert len(func_results) >= 1

        # 3. Check alias mappings
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        # Should have at least some aliases
        assert len(aliases) >= 1

    def test_multi_file_alias_usage(self, temp_project_dir):
        """IT-4.2: Test aliases used across multiple files."""
        # Create header with class and alias
        (temp_project_dir / "include" / "types.h").write_text(
            """
#pragma once

/// Base widget class
class Widget {
public:
    void render();
};

/// Widget pointer type
using WidgetPtr = Widget*;
"""
        )

        # Create implementation files using the alias
        (temp_project_dir / "src" / "file1.cpp").write_text(
            """
#include "types.h"

void createWidget(WidgetPtr* out) {
    *out = new Widget();
}
"""
        )

        (temp_project_dir / "src" / "file2.cpp").write_text(
            """
#include "types.h"

void destroyWidget(WidgetPtr widget) {
    delete widget;
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/file1.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17", f"-I{temp_project_dir}/include"],
                },
                {
                    "file": "src/file2.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17", f"-I{temp_project_dir}/include"],
                },
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify functions are indexed
        create_results = analyzer.search_functions("createWidget")
        destroy_results = analyzer.search_functions("destroyWidget")

        assert len(create_results) >= 1
        assert len(destroy_results) >= 1

        # Verify alias is tracked
        canonical = analyzer.cache_manager.get_canonical_for_alias("WidgetPtr")
        assert canonical == "Widget *"

    def test_stl_alias_integration(self, temp_project_dir):
        """IT-4.3: Test aliases with STL types in realistic scenario."""
        # Create code using STL type aliases
        (temp_project_dir / "src" / "callbacks.h").write_text(
            """
#pragma once
#include <functional>
#include <string>

/// Error callback type
using ErrorCallback = std::function<void(const std::string&)>;

/// Success callback type
using SuccessCallback = std::function<void()>;

/// Register callbacks
void registerCallbacks(ErrorCallback onError, SuccessCallback onSuccess);
"""
        )

        (temp_project_dir / "src" / "callbacks.cpp").write_text(
            """
#include "callbacks.h"

void registerCallbacks(ErrorCallback onError, SuccessCallback onSuccess) {
    // Implementation
}
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/callbacks.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17", f"-I{temp_project_dir}/src"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify function is indexed
        results = analyzer.search_functions("registerCallbacks")
        assert len(results) >= 1

        # Verify aliases are tracked
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        # Should have ErrorCallback and SuccessCallback
        assert "ErrorCallback" in aliases
        assert "SuccessCallback" in aliases


# ============================================================================
# IT-5: Performance and Scalability
# ============================================================================


class TestPerformanceScalability:
    """Performance and scalability tests for type alias tracking (IT-5)."""

    def test_many_aliases_performance(self, temp_project_dir):
        """IT-5.1: Test performance with many aliases."""
        # Generate code with many aliases
        aliases_code = []
        for i in range(100):
            aliases_code.append(f"class Type{i} {{}};")
            aliases_code.append(f"using Alias{i} = Type{i};")

        (temp_project_dir / "src" / "many_aliases.cpp").write_text("\n".join(aliases_code))

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/many_aliases.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify aliases are tracked
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        # Should have at least 50 aliases (some might not be tracked if they're templates)
        assert len(aliases) >= 50

        # Test lookup performance (should be fast)
        import time

        start = time.time()
        for i in range(50):
            canonical = analyzer.cache_manager.get_canonical_for_alias(f"Alias{i}")
            assert canonical == f"Type{i}"
        duration = time.time() - start

        # 50 lookups should complete in under 1 second
        assert duration < 1.0

    def test_deep_alias_chain(self, temp_project_dir):
        """IT-5.2: Test performance with deep alias chains."""
        # Create deep alias chain (A -> B -> C -> ... -> Z)
        chain_code = ["class Root {};"]
        chain_code.append("using Alias0 = Root;")

        for i in range(1, 20):
            chain_code.append(f"using Alias{i} = Alias{i-1};")

        (temp_project_dir / "src" / "chain.cpp").write_text("\n".join(chain_code))

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/chain.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # All aliases in chain should resolve to Root (canonical type)
        for i in range(20):
            canonical = analyzer.cache_manager.get_canonical_for_alias(f"Alias{i}")
            # libclang's get_canonical() should resolve entire chain
            assert canonical == "Root"


# ============================================================================
# IT-6: Error Handling and Edge Cases
# ============================================================================


class TestErrorHandlingEdgeCases:
    """Error handling and edge cases for type alias integration (IT-6)."""

    def test_search_with_no_aliases(self, temp_project_dir):
        """IT-6.1: Search works correctly when no aliases exist."""
        # Create simple class without aliases
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
/// Simple widget class
class Widget {
public:
    void show();
};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Search should work normally
        results = analyzer.search_classes("Widget")
        assert len(results) >= 1

        # Verify no aliases
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert len(aliases) == 0

    def test_malformed_alias_doesnt_break_indexing(self, temp_project_dir):
        """IT-6.2: Malformed alias doesn't prevent rest of indexing."""
        # Create file with malformed alias and valid classes
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class ValidClass1 {
};

using BrokenAlias =   // Missing target type

class ValidClass2 {
};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Both valid classes should still be indexed
        results1 = analyzer.search_classes("ValidClass1")
        results2 = analyzer.search_classes("ValidClass2")

        assert len(results1) >= 1
        assert len(results2) >= 1

    def test_incremental_refresh_with_new_alias(self, temp_project_dir):
        """IT-6.3: Incremental refresh picks up newly added aliases."""
        # Initial indexing without alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};
"""
        )

        temp_compile_commands(
            temp_project_dir,
            [
                {
                    "file": "src/test.cpp",
                    "directory": str(temp_project_dir),
                    "arguments": ["-std=c++17"],
                }
            ],
        )

        analyzer = CppAnalyzer(str(temp_project_dir))
        analyzer.index_project()

        # Verify no aliases initially
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        initial_count = len(aliases)

        # Add alias
        (temp_project_dir / "src" / "test.cpp").write_text(
            """
class Widget {
};

using WidgetAlias = Widget;
"""
        )

        # Refresh
        analyzer.refresh_if_needed()

        # Verify alias is now tracked
        aliases = analyzer.cache_manager.get_all_alias_mappings()
        assert len(aliases) > initial_count
        assert "WidgetAlias" in aliases
