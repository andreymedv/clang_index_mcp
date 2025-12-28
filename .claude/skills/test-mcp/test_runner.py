"""
Test Runner - Orchestrates test execution
"""

import importlib
from pathlib import Path
from typing import Dict, Optional
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

    def __init__(self) -> None:
        self.project_manager = ProjectManager()

    def run_test(
        self,
        test_name: str,
        project: str,
        protocol: str = "http",
        scenario_path: Optional[str] = None
    ) -> str:
        """
        Run a test scenario

        Args:
            test_name: Name of test scenario (e.g., "basic-indexing" or "custom")
            project: Project name (e.g., "tier1", "tier2")
            protocol: Protocol to use (sse, stdio, http)
            scenario_path: Path to YAML scenario file (for custom scenarios)

        Returns:
            str: Formatted test result
        """
        # Handle custom YAML scenarios
        if test_name == "custom" or scenario_path:
            if not scenario_path:
                return (
                    "❌ Custom scenarios require scenario= parameter with YAML file path\n"
                    "  Hint: /test-mcp test=custom scenario=my-test.yaml tier=1\n"
                    "        Place YAML files in .test-scenarios/ directory"
                )
            return self.run_custom_scenario(scenario_path, project, protocol)

        # Validate built-in scenario
        if test_name not in self.AVAILABLE_TESTS:
            return (
                f"❌ Unknown test scenario: {test_name}\n"
                f"  Available built-in scenarios: {', '.join(self.AVAILABLE_TESTS.keys())}\n"
                f"  Hint: Use 'test=custom scenario=file.yaml' for custom scenarios"
            )

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

    def run_custom_scenario(self, scenario_path: str, project: str, protocol: str = "http") -> str:
        """
        Run a custom YAML scenario

        Args:
            scenario_path: Path to YAML scenario file
            project: Project name
            protocol: Protocol to use

        Returns:
            str: Formatted test result
        """
        scenario_path = Path(scenario_path)

        # Check if path is absolute, otherwise look in .test-scenarios/
        if not scenario_path.is_absolute():
            repo_root = Path(__file__).parent.parent.parent.parent
            scenarios_dir = repo_root / ".test-scenarios"
            scenario_path = scenarios_dir / scenario_path

        if not scenario_path.exists():
            return (
                f"❌ Scenario file not found: {scenario_path}\n"
                f"  Hint: Place YAML scenarios in .test-scenarios/ directory\n"
                f"        Use relative path from .test-scenarios/ or absolute path"
            )

        project_info = self.project_manager.get_project(project)
        if not project_info:
            return f"❌ Project '{project}' not found. Run '/test-mcp list-projects' to see available projects."

        # Validate project
        is_valid, issues = self.project_manager.validate_project(project)
        if not is_valid:
            error_msg = f"❌ Project '{project}' validation failed:\n"
            for issue in issues:
                error_msg += f"  - {issue}\n"
            return error_msg

        # Mark project as used
        self.project_manager.mark_project_used(project)

        # Execute custom scenario
        return self._execute_custom_scenario(scenario_path, project, project_info, protocol)

    def _execute_test(self, test_name: str, project_name: str, project_info: Dict, protocol: str) -> str:
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

    def _execute_custom_scenario(self, scenario_path: Path, project_name: str, project_info: Dict, protocol: str) -> str:
        """
        Execute custom YAML scenario with full orchestration

        Args:
            scenario_path: Path to YAML scenario file
            project_name: Project name (for reporting)
            project_info: Project configuration dict
            protocol: Protocol to use

        Returns:
            str: Formatted test result
        """
        server_manager = None
        test_name = f"custom:{scenario_path.stem}"
        result_analyzer = ResultAnalyzer(test_name, project_name, protocol)

        try:
            # Step 1: Start MCP server
            server_manager = ServerManager(protocol=protocol, port=8000)
            print(f"⏳ Starting MCP server ({protocol.upper()} mode)...")
            server_info = server_manager.start_server(timeout=30)
            print(f"✓ Server started (PID: {server_info['pid']})")

            # Step 2: Load and execute YAML scenario
            print(f"⏳ Running custom scenario '{scenario_path.name}'...")
            from scenarios.yaml_scenario import run as run_yaml

            # Execute YAML scenario
            test_results = run_yaml(project_info, server_manager, yaml_path=str(scenario_path))

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

    def run_pytest(self) -> str:
        """
        Run existing pytest suite

        Returns:
            str: Formatted pytest results
        """
        import subprocess

        repo_root = Path(__file__).parent.parent.parent.parent

        print("⏳ Running pytest suite...")
        try:
            result = subprocess.run(
                ["pytest", "-v", "--tb=short"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout + result.stderr
            exit_code = result.returncode

            if exit_code == 0:
                return f"✅ Pytest suite passed\n\n{output}"
            else:
                return f"❌ Pytest suite failed (exit code: {exit_code})\n\n{output}"

        except subprocess.TimeoutExpired:
            return "❌ Pytest suite timed out (>5 minutes)"
        except FileNotFoundError:
            return "❌ pytest not found. Install with: pip install pytest"
        except Exception as e:
            return f"❌ Pytest execution error: {e}"
