"""
YAML Scenario Loader and Executor

Loads and executes custom test scenarios defined in YAML format.
"""

import yaml
import json
import time
import re
from pathlib import Path


def run(project_info, server_manager, yaml_path=None):
    """
    Execute YAML-defined test scenario

    Args:
        project_info: Project configuration dict
        server_manager: ServerManager instance
        yaml_path: Path to YAML scenario file

    Returns:
        dict: Test results with status, metrics, issues
    """
    if not yaml_path:
        return {
            "error": "YAML scenario path required",
            "metrics": {},
            "details": {}
        }

    start_time = time.time()
    results = {
        "metrics": {},
        "details": {},
        "steps": []
    }

    try:
        # Load YAML scenario
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            results["error"] = f"Scenario file not found: {yaml_path}"
            return results

        with open(yaml_path, "r") as f:
            scenario = yaml.safe_load(f)

        # Validate scenario
        if not isinstance(scenario, dict):
            results["error"] = "Invalid YAML scenario format"
            return results

        if "steps" not in scenario:
            results["error"] = "Scenario missing 'steps' field"
            return results

        # Store scenario metadata
        results["details"]["scenario_name"] = scenario.get("name", "unknown")
        results["details"]["scenario_description"] = scenario.get("description", "")
        results["details"]["yaml_path"] = str(yaml_path)

        endpoint = server_manager.server_process and f"http://localhost:{server_manager.port}"
        if not endpoint:
            raise RuntimeError("Server not started")

        # Execute steps
        step_results = []
        for i, step in enumerate(scenario["steps"]):
            step_num = i + 1
            tool_name = step.get("tool")
            description = step.get("description", f"Step {step_num}: {tool_name}")

            results["steps"].append(description)
            print(f"  [{step_num}/{len(scenario['steps'])}] {description}")

            # Special handling for wait_for_indexing
            if tool_name == "wait_for_indexing":
                timeout = step.get("timeout", 60)
                if not _wait_for_indexing(server_manager, endpoint, max_wait=timeout):
                    results["error"] = f"Step {step_num}: Indexing did not complete within {timeout}s"
                    return results
                step_results.append({"step": step_num, "tool": tool_name, "success": True})
                continue

            # Prepare arguments with variable substitution
            args = step.get("args", {})
            args = _substitute_variables(args, project_info)

            # Execute tool
            try:
                response = server_manager.call_tool(endpoint, tool_name, args)
            except Exception as e:
                results["error"] = f"Step {step_num}: Tool execution failed: {e}"
                return results

            # Check for errors
            if "error" in response:
                results["error"] = f"Step {step_num}: {tool_name} failed: {response['error']}"
                return results

            # Extract response content
            response_text = ""
            if "result" in response:
                content = response["result"].get("content", [])
                if content:
                    response_text = content[0].get("text", "")

            # Validate expectations
            expectations = step.get("expect", [])
            for expectation in expectations:
                passed, message = _check_expectation(expectation, response_text, response)
                if not passed:
                    results["error"] = f"Step {step_num}: Expectation failed: {message}"
                    return results

            step_results.append({
                "step": step_num,
                "tool": tool_name,
                "success": True,
                "response_length": len(response_text)
            })

        # All steps passed
        results["metrics"]["steps_executed"] = len(step_results)
        results["metrics"]["steps_passed"] = len(step_results)
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)
        results["details"]["step_results"] = step_results

    except yaml.YAMLError as e:
        results["error"] = f"YAML parsing error: {e}"
    except Exception as e:
        results["error"] = str(e)

    return results


def _substitute_variables(args, project_info):
    """
    Substitute special variables in arguments

    Args:
        args: Arguments dict
        project_info: Project configuration

    Returns:
        dict: Arguments with substituted values
    """
    substituted = {}
    for key, value in args.items():
        if isinstance(value, str):
            # Substitute variables
            value = value.replace("$PROJECT_PATH", project_info.get("path", ""))
            value = value.replace("$PROJECT_NAME", project_info.get("name", ""))
            value = value.replace("$BUILD_DIR", project_info.get("build_dir", "build"))
        substituted[key] = value
    return substituted


def _wait_for_indexing(server_manager, endpoint, max_wait=60):
    """Wait for indexing to complete"""
    wait_start = time.time()
    while time.time() - wait_start < max_wait:
        status_response = server_manager.call_tool(
            endpoint,
            "get_indexing_status",
            {}
        )

        if "result" in status_response:
            content = status_response["result"].get("content", [])
            if content:
                status_text = content[0].get("text", "")
                try:
                    status_json = json.loads(status_text)
                    if status_json.get("is_fully_indexed", False):
                        return True
                except json.JSONDecodeError:
                    pass

        time.sleep(0.5)

    return False


def _check_expectation(expectation, response_text, response):
    """
    Check if expectation is met

    Args:
        expectation: Expectation dict
        response_text: Response text content
        response: Full response dict

    Returns:
        tuple: (passed, message)
    """
    exp_type = expectation.get("type")

    if exp_type == "count":
        # Count items in response (lines or specific pattern)
        count = response_text.count("\n") + 1 if response_text else 0
        operator = expectation.get("operator", "==")
        expected_value = expectation.get("value", 0)

        if operator == ">":
            passed = count > expected_value
        elif operator == ">=":
            passed = count >= expected_value
        elif operator == "<":
            passed = count < expected_value
        elif operator == "<=":
            passed = count <= expected_value
        elif operator == "==":
            passed = count == expected_value
        elif operator == "!=":
            passed = count != expected_value
        else:
            return False, f"Unknown operator: {operator}"

        if not passed:
            return False, f"Count {count} {operator} {expected_value} failed"
        return True, ""

    elif exp_type == "content_includes":
        value = expectation.get("value", "")
        if value not in response_text:
            return False, f"Content does not include '{value}'"
        return True, ""

    elif exp_type == "content_matches":
        pattern = expectation.get("pattern", "")
        if not re.search(pattern, response_text):
            return False, f"Content does not match pattern '{pattern}'"
        return True, ""

    elif exp_type == "has_field":
        field = expectation.get("field", "")
        # Try to parse response as JSON
        try:
            data = json.loads(response_text)
            if field not in data:
                return False, f"Response missing field '{field}'"
            return True, ""
        except json.JSONDecodeError:
            return False, f"Response is not valid JSON"

    elif exp_type == "no_error":
        if "error" in response:
            return False, f"Response contains error: {response['error']}"
        return True, ""

    else:
        return False, f"Unknown expectation type: {exp_type}"
