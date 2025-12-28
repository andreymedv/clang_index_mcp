"""
Test Runner - Orchestrates test execution
"""

import importlib
from pathlib import Path
from project_manager import ProjectManager
from server_manager import ServerManager
from result_analyzer import ResultAnalyzer


class TestRunner:
    """Orchestrates test scenario execution"""

    AVAILABLE_TESTS = {
        "basic-indexing": "scenarios.basic_indexing",
        "issue-13": "scenarios.issue_13",
        "incremental-refresh": "scenarios.incremental_refresh",
        "all-protocols": "scenarios.all_protocols",
    }

    def __init__(self):
        self.project_manager = ProjectManager()

    def run_test(self, test_name, project, protocol="http"):
        """
        Run a test scenario

        Args:
            test_name: Name of test scenario (e.g., "basic-indexing")
            project: Project name (e.g., "tier1", "tier2")
            protocol: Protocol to use (sse, stdio, http)

        Returns:
            str: Formatted test result
        """
        # Validate inputs
        if test_name not in self.AVAILABLE_TESTS:
            return f"❌ Unknown test scenario: {test_name}\nAvailable: {', '.join(self.AVAILABLE_TESTS.keys())}"

        project_info = self.project_manager.get_project(project)
        if not project_info:
            return f"❌ Project '{project}' not found. Run '/test-mcp list-projects' to see available projects."

        # Validate project before running test
        is_valid, issues = self.project_manager.validate_project(project)
        if not is_valid:
            error_msg = f"❌ Project '{project}' validation failed:\n"
            for issue in issues:
                error_msg += f"  - {issue}\n"
            return error_msg

        # Mark project as used
        self.project_manager.mark_project_used(project)

        # Execute test scenario
        result = self._execute_test(test_name, project, project_info, protocol)

        return result

    def _execute_test(self, test_name, project_name, project_info, protocol):
        """
        Execute test scenario with full orchestration

        Args:
            test_name: Test scenario name
            project_name: Project name (for reporting)
            project_info: Project configuration dict
            protocol: Protocol to use

        Returns:
            str: Formatted test result
        """
        server_manager = None
        result_analyzer = ResultAnalyzer(test_name, project_name, protocol)

        try:
            # Step 1: Start MCP server
            server_manager = ServerManager(protocol=protocol, port=8000)
            print(f"⏳ Starting MCP server ({protocol.upper()} mode)...")
            server_info = server_manager.start_server(timeout=30)
            print(f"✓ Server started (PID: {server_info['pid']})")

            # Step 2: Load and execute test scenario
            print(f"⏳ Running test scenario '{test_name}'...")
            scenario_module_path = self.AVAILABLE_TESTS[test_name]
            scenario_module = importlib.import_module(scenario_module_path)

            # Execute test
            test_results = scenario_module.run(project_info, server_manager)

            # Step 3: Analyze results
            print("⏳ Analyzing results...")
            analysis = result_analyzer.analyze(test_results)

            # Step 4: Format output
            formatted_output = result_analyzer.format_output(analysis)

            return formatted_output

        except Exception as e:
            error_result = {
                "error": str(e),
                "metrics": {}
            }
            analysis = result_analyzer.analyze(error_result)
            return result_analyzer.format_output(analysis)

        finally:
            # Always cleanup server
            if server_manager:
                print("⏳ Stopping MCP server...")
                server_manager.stop_server()
                print("✓ Server stopped")
