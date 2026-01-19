"""
Cross-Tool Workflow Tests

Tests that verify MCP tools work correctly when chained together.
These tests catch integration issues where Tool A's output doesn't work as Tool B's input.

Historical context (Jan 2026): 4 fix commits in 2 days after qualified names feature,
each fixing the SAME issue (qualified names not accepted) in different tools.
These workflow tests prevent such regressions.

Key principle: If Tool A returns qualified_name, and Tool B accepts class_name parameter,
there MUST be a test that uses A's output as B's input.
"""

import pytest
from pathlib import Path

import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from mcp_server.cpp_analyzer import CppAnalyzer
from tests.utils.test_helpers import temp_compile_commands


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def namespaced_project(temp_project_dir):
    """
    Create a project with namespaced classes for workflow testing.

    Structure:
    - outer::inner::Base (base class)
    - outer::inner::Derived (derives from Base)
    - outer::Helper (utility class)
    - GlobalClass (no namespace)
    """
    (temp_project_dir / "src" / "classes.cpp").write_text("""
namespace outer {
namespace inner {

class Base {
public:
    virtual ~Base() {}
    virtual void baseMethod() {}
};

class Derived : public Base {
public:
    void baseMethod() override {}
    void derivedMethod() {}
};

}  // namespace inner

class Helper {
public:
    void helperMethod() {}
};

void outerFunction() {}

}  // namespace outer

class GlobalClass {
public:
    void globalMethod() {}
};

void globalFunction() {}
""")

    temp_compile_commands(temp_project_dir, [
        {
            "file": "src/classes.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }
    ])

    analyzer = CppAnalyzer(str(temp_project_dir))
    analyzer.index_project()

    yield analyzer

    if hasattr(analyzer, 'cache_manager'):
        analyzer.cache_manager.close()


@pytest.fixture
def template_project(temp_project_dir):
    """
    Create a project with template classes for workflow testing.
    """
    (temp_project_dir / "src" / "templates.cpp").write_text("""
namespace lib {

template<typename T>
class Container {
public:
    void add(const T& item) {}
    T get() { return T(); }
};

template<typename T>
class DerivedContainer : public Container<T> {
public:
    void extra() {}
};

// Explicit instantiation
template class Container<int>;
template class DerivedContainer<int>;

}  // namespace lib
""")

    temp_compile_commands(temp_project_dir, [
        {
            "file": "src/templates.cpp",
            "directory": str(temp_project_dir),
            "arguments": ["-std=c++17"]
        }
    ])

    analyzer = CppAnalyzer(str(temp_project_dir))
    analyzer.index_project()

    yield analyzer

    if hasattr(analyzer, 'cache_manager'):
        analyzer.cache_manager.close()


# =============================================================================
# Workflow Tests: search_classes → get_class_info
# =============================================================================

@pytest.mark.workflow
class TestSearchClassesToGetClassInfo:
    """Test workflow: search_classes output → get_class_info input"""

    def test_qualified_name_from_search_works_in_get_info(self, namespaced_project):
        """
        search_classes returns qualified_name (e.g., "outer::inner::Base").
        get_class_info MUST accept this qualified_name as input.

        This was broken in PR #131.
        """
        analyzer = namespaced_project

        # Step 1: Search for classes
        search_results = analyzer.search_classes("Base")
        assert len(search_results) > 0, "search_classes should find Base"

        base_result = next(r for r in search_results if r["name"] == "Base")
        qualified_name = base_result["qualified_name"]
        assert "::" in qualified_name, "qualified_name should include namespace"

        # Step 2: Use qualified_name from search as input to get_class_info
        class_info = analyzer.search_engine.get_class_info(qualified_name)
        assert class_info is not None, \
            f"get_class_info failed for qualified name '{qualified_name}'"
        assert class_info["name"] == "Base"

    def test_all_search_results_work_with_get_info(self, namespaced_project):
        """
        Every class returned by search_classes should work with get_class_info.
        """
        analyzer = namespaced_project

        # Search all classes
        all_classes = analyzer.search_classes(".*")
        assert len(all_classes) > 0, "Should find some classes"

        for cls in all_classes:
            qualified_name = cls["qualified_name"]
            class_info = analyzer.search_engine.get_class_info(qualified_name)
            assert class_info is not None, \
                f"get_class_info failed for '{qualified_name}' from search_classes"


# =============================================================================
# Workflow Tests: search_classes → get_class_hierarchy
# =============================================================================

@pytest.mark.workflow
class TestSearchClassesToGetHierarchy:
    """Test workflow: search_classes output → get_class_hierarchy input"""

    def test_qualified_name_from_search_works_in_hierarchy(self, namespaced_project):
        """
        get_class_hierarchy MUST accept qualified names from search_classes.

        This was broken in PR #132.
        """
        analyzer = namespaced_project

        # Step 1: Search for Derived class
        search_results = analyzer.search_classes("Derived")
        derived_results = [r for r in search_results if r["name"] == "Derived"]
        assert len(derived_results) > 0, "Should find Derived class"

        qualified_name = derived_results[0]["qualified_name"]

        # Step 2: Get hierarchy using qualified name
        hierarchy = analyzer.get_class_hierarchy(qualified_name)
        assert hierarchy is not None, \
            f"get_class_hierarchy failed for '{qualified_name}'"
        # Hierarchy should have name or class_info
        assert "name" in hierarchy or "class_info" in hierarchy, \
            "Hierarchy should contain class information"

    def test_hierarchy_returns_qualified_base_classes(self, namespaced_project):
        """
        get_class_hierarchy should return qualified names for base classes.
        """
        analyzer = namespaced_project

        # Find Derived and get its hierarchy
        search_results = analyzer.search_classes("Derived")
        derived = next((r for r in search_results if r["name"] == "Derived"), None)
        assert derived is not None

        hierarchy = analyzer.get_class_hierarchy(derived["qualified_name"])
        assert hierarchy is not None

        # Check base_classes exists and contains information
        # base_classes can be a list of strings (qualified names) or dicts
        if hierarchy.get("base_classes"):
            for base in hierarchy["base_classes"]:
                if isinstance(base, str):
                    # String format: should be qualified name
                    assert base, "base_classes entry should not be empty"
                elif isinstance(base, dict):
                    # Dict format: should have name
                    assert base.get("name") or base.get("base_class"), \
                        "base_classes dict should contain name information"


# =============================================================================
# Workflow Tests: search_classes → get_derived_classes
# =============================================================================

@pytest.mark.workflow
class TestSearchClassesToGetDerived:
    """Test workflow: search_classes output → get_derived_classes input"""

    def test_qualified_name_from_search_works_in_derived(self, namespaced_project):
        """
        get_derived_classes MUST accept qualified names from search_classes.

        This was broken in PR #134.
        """
        analyzer = namespaced_project

        # Step 1: Search for Base class
        search_results = analyzer.search_classes("Base")
        base_results = [r for r in search_results if r["name"] == "Base"]
        assert len(base_results) > 0, "Should find Base class"

        qualified_name = base_results[0]["qualified_name"]

        # Step 2: Get derived classes using qualified name
        derived = analyzer.get_derived_classes(qualified_name)
        assert derived is not None, \
            f"get_derived_classes failed for '{qualified_name}'"

        # Should find Derived class
        derived_names = [d.get("name", d.get("class_name", "")) for d in derived]
        assert any("Derived" in name for name in derived_names), \
            f"Should find Derived class, got: {derived_names}"


# =============================================================================
# Workflow Tests: search_functions → get_function_signature
# =============================================================================

@pytest.mark.workflow
class TestSearchFunctionsToGetSignature:
    """Test workflow: search_functions output → get_function_signature input"""

    def test_qualified_name_from_search_works_in_signature(self, namespaced_project):
        """
        get_function_signature MUST accept qualified names from search_functions.

        This was broken in PR #132.
        """
        analyzer = namespaced_project

        # Step 1: Search for functions
        search_results = analyzer.search_functions(".*Function")
        assert len(search_results) > 0, "Should find functions"

        for func in search_results:
            qualified_name = func.get("qualified_name", func["name"])

            # Step 2: Get signature using qualified name (if available)
            if "::" in qualified_name:
                signature = analyzer.search_engine.get_function_signature(qualified_name)
                # Should not return None for qualified names
                assert signature is not None, \
                    f"get_function_signature failed for '{qualified_name}'"


# =============================================================================
# Workflow Tests: get_class_info → get_class_hierarchy
# =============================================================================

@pytest.mark.workflow
class TestGetInfoToGetHierarchy:
    """Test workflow: get_class_info output → get_class_hierarchy input"""

    def test_info_qualified_name_works_in_hierarchy(self, namespaced_project):
        """
        qualified_name from get_class_info should work in get_class_hierarchy.
        """
        analyzer = namespaced_project

        # Step 1: Get class info
        class_info = analyzer.search_engine.get_class_info("Derived")
        assert class_info is not None

        qualified_name = class_info.get("qualified_name", "Derived")

        # Step 2: Use in get_class_hierarchy
        hierarchy = analyzer.get_class_hierarchy(qualified_name)
        assert hierarchy is not None, \
            f"get_class_hierarchy failed for '{qualified_name}' from get_class_info"


# =============================================================================
# Workflow Tests: Partial/Suffix Qualified Names
# =============================================================================

@pytest.mark.workflow
class TestPartialQualifiedNames:
    """Test that partial qualified names work across tools.

    Example: "inner::Base" should match "outer::inner::Base"
    This was broken in PR #135.
    """

    def test_partial_qualified_name_in_get_info(self, namespaced_project):
        """
        get_class_info should accept partial qualified names.
        "inner::Base" should find "outer::inner::Base".
        """
        analyzer = namespaced_project

        # Partial qualified name
        class_info = analyzer.search_engine.get_class_info("inner::Base")
        assert class_info is not None, \
            "get_class_info should accept partial qualified name 'inner::Base'"

    def test_partial_qualified_name_in_hierarchy(self, namespaced_project):
        """
        get_class_hierarchy should accept partial qualified names.
        """
        analyzer = namespaced_project

        hierarchy = analyzer.get_class_hierarchy("inner::Derived")
        assert hierarchy is not None, \
            "get_class_hierarchy should accept partial qualified name 'inner::Derived'"

    def test_partial_qualified_name_in_derived(self, namespaced_project):
        """
        get_derived_classes should accept partial qualified names.
        """
        analyzer = namespaced_project

        derived = analyzer.get_derived_classes("inner::Base")
        assert derived is not None, \
            "get_derived_classes should accept partial qualified name 'inner::Base'"


# =============================================================================
# Workflow Tests: Template Classes
# =============================================================================

@pytest.mark.workflow
class TestTemplateWorkflows:
    """Test workflows with template classes."""

    def test_search_template_to_get_info(self, template_project):
        """
        Template classes from search should work in get_class_info.
        """
        analyzer = template_project

        # Search for Container
        search_results = analyzer.search_classes("Container")
        container_results = [r for r in search_results
                           if "Container" in r["name"] and "Derived" not in r["name"]]

        if container_results:
            qualified_name = container_results[0]["qualified_name"]
            class_info = analyzer.search_engine.get_class_info(qualified_name)
            assert class_info is not None, \
                f"get_class_info failed for template class '{qualified_name}'"

    def test_search_template_to_get_derived(self, template_project):
        """
        Template base classes should work with get_derived_classes.
        """
        analyzer = template_project

        # Search for base Container
        search_results = analyzer.search_classes("Container")
        container_results = [r for r in search_results
                           if r["name"] == "Container" or
                           r["qualified_name"].endswith("::Container")]

        for container in container_results:
            qualified_name = container["qualified_name"]
            derived = analyzer.get_derived_classes(qualified_name)
            # Should not fail
            assert derived is not None, \
                f"get_derived_classes failed for template '{qualified_name}'"


# =============================================================================
# Workflow Tests: Complete Chains
# =============================================================================

@pytest.mark.workflow
class TestCompleteChains:
    """Test complete multi-step workflows."""

    def test_full_chain_search_info_hierarchy_derived(self, namespaced_project):
        """
        Test complete chain: search → info → hierarchy → derived.
        Each step uses output from previous step.
        """
        analyzer = namespaced_project

        # Step 1: Search
        search_results = analyzer.search_classes("Base")
        base = next((r for r in search_results if r["name"] == "Base"), None)
        assert base is not None, "Step 1 failed: search_classes"

        # Step 2: Get info using search result
        class_info = analyzer.search_engine.get_class_info(base["qualified_name"])
        assert class_info is not None, \
            f"Step 2 failed: get_class_info for '{base['qualified_name']}'"

        # Step 3: Get hierarchy using info result
        hierarchy = analyzer.get_class_hierarchy(class_info["qualified_name"])
        assert hierarchy is not None, \
            f"Step 3 failed: get_class_hierarchy for '{class_info['qualified_name']}'"

        # Step 4: Get derived using original qualified name
        derived = analyzer.get_derived_classes(base["qualified_name"])
        assert derived is not None, \
            f"Step 4 failed: get_derived_classes for '{base['qualified_name']}'"

    def test_method_lookup_from_class_info(self, namespaced_project):
        """
        Methods returned by get_class_info should have correct qualified names.
        """
        analyzer = namespaced_project

        # Get class info with methods
        search_results = analyzer.search_classes("Helper")
        helper = next((r for r in search_results if r["name"] == "Helper"), None)
        assert helper is not None

        class_info = analyzer.search_engine.get_class_info(helper["qualified_name"])
        assert class_info is not None

        # Check methods have qualified names
        if class_info.get("methods"):
            for method in class_info["methods"]:
                # Method should have name at minimum
                assert method.get("name"), "Method should have name"


