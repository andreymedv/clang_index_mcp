"""
Result Analyzer - Analyzes test results and formats output

Responsibilities:
- Compare actual vs expected results
- Detect issues and anomalies
- Format output for user (✅/❌ with metrics)
- Save detailed logs
"""

import json
from datetime import datetime
from pathlib import Path


class ResultAnalyzer:
    """Analyzes test results and formats output"""

    def __init__(self, test_name, project_name, protocol):
        """
        Initialize ResultAnalyzer

        Args:
            test_name: Name of test scenario
            project_name: Name of project being tested
            protocol: Protocol used (sse, stdio, http)
        """
        self.test_name = test_name
        self.project_name = project_name
        self.protocol = protocol

        # Create results directory
        self.repo_root = Path(__file__).parent.parent.parent.parent
        self.results_dir = self.repo_root / ".test-results"
        self.results_dir.mkdir(exist_ok=True)

        # Create timestamped directory for this test
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.test_dir = self.results_dir / f"{timestamp}_{test_name}_{project_name}_{protocol}"
        self.test_dir.mkdir(exist_ok=True)

    def analyze(self, results, expected=None):
        """
        Analyze test results

        Args:
            results: Test execution results dict
            expected: Expected results dict (optional)

        Returns:
            dict: Analysis result with status, issues, metrics
        """
        analysis = {
            "status": "PASS",
            "issues": [],
            "metrics": results.get("metrics", {}),
            "details": results.get("details", {})
        }

        # Check for errors in results
        if "error" in results:
            analysis["status"] = "FAIL"
            analysis["issues"].append(f"Test execution error: {results['error']}")

        # Check expected values if provided
        if expected:
            for key, expected_value in expected.items():
                actual_value = results.get(key)
                if actual_value != expected_value:
                    analysis["status"] = "FAIL"
                    analysis["issues"].append(
                        f"{key}: expected {expected_value}, got {actual_value}"
                    )

        # Save detailed results
        self._save_results(results, analysis)

        return analysis

    def format_output(self, analysis):
        """
        Format analysis result for user output

        Args:
            analysis: Analysis result dict

        Returns:
            str: Formatted output string
        """
        # Status line
        status_icon = "✅" if analysis["status"] == "PASS" else "❌"
        metrics = analysis.get("metrics", {})
        duration = metrics.get("duration_s", "?")

        output = f"{status_icon} Test: {self.test_name} ({self.project_name}, {self.protocol.upper()}, {duration}s)\n"

        # Metrics
        if "files_indexed" in metrics:
            output += f"   Files indexed: {metrics['files_indexed']}"
            if "total_files" in metrics:
                output += f"/{metrics['total_files']}"
            output += "\n"

        if "classes_found" in metrics:
            output += f"   Classes found: {metrics['classes_found']}"
            if "expected_classes" in metrics:
                output += f" (expected: {metrics['expected_classes']})"
            output += "\n"

        if "functions_found" in metrics:
            output += f"   Functions found: {metrics['functions_found']}"
            if "expected_functions" in metrics:
                output += f" (expected: {metrics['expected_functions']})"
            output += "\n"

        # Issues
        if analysis["issues"]:
            output += "   Issues:\n"
            for issue in analysis["issues"]:
                output += f"     - {issue}\n"
        else:
            output += "   Issues: None\n"

        # Logs location
        output += f"   Logs: {self.test_dir.relative_to(self.repo_root)}/\n"

        return output

    def _save_results(self, results, analysis):
        """Save detailed results to files"""
        # Save raw results
        with open(self.test_dir / "results.json", "w") as f:
            json.dump(results, f, indent=2)

        # Save analysis
        with open(self.test_dir / "analysis.json", "w") as f:
            json.dump(analysis, f, indent=2)

        # Save test config
        config = {
            "test_name": self.test_name,
            "project_name": self.project_name,
            "protocol": self.protocol,
            "timestamp": datetime.now().isoformat()
        }
        with open(self.test_dir / "test-config.json", "w") as f:
            json.dump(config, f, indent=2)
