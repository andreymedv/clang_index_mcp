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
            results["error"] = f"Scenario file not found: {yaml_path}\n" \
                             f"  Hint: Place YAML files in .test-scenarios/ directory"
            return results

        with open(yaml_path, "r") as f:
            scenario = yaml.safe_load(f)

        # Validate scenario schema
        validation_error = _validate_scenario_schema(scenario)
        if validation_error:
            results["error"] = validation_error
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


def _validate_scenario_schema(scenario):
    """
    Validate YAML scenario schema

    Args:
        scenario: Parsed YAML scenario dict

    Returns:
        str: Error message if validation fails, None otherwise
    """
    # Check root structure
    if not isinstance(scenario, dict):
        return "Invalid YAML scenario: must be a dictionary\n" \
               "  Hint: Ensure YAML starts with field definitions, not a list"

    # Check required fields
    if "steps" not in scenario:
        return "Scenario missing required 'steps' field\n" \
               "  Hint: Add 'steps:' followed by a list of test steps"

    # Validate steps
    steps = scenario.get("steps")
    if not isinstance(steps, list):
        return "Scenario 'steps' must be a list\n" \
               "  Hint: Use YAML list syntax:\n" \
               "    steps:\n" \
               "      - tool: tool_name\n" \
               "        args: {...}"

    if len(steps) == 0:
        return "Scenario must have at least one step\n" \
               "  Hint: Add at least one tool call in the steps list"

    # Supported MCP tools
    supported_tools = {
        "set_project_directory", "get_indexing_status", "wait_for_indexing",
        "search_classes", "search_functions", "search_symbols",
        "get_class_info", "get_function_signature", "find_in_file",
        "refresh_project", "get_server_status", "get_class_hierarchy",
        "get_derived_classes", "find_callers", "find_callees",
        "get_call_sites", "get_files_containing_symbol", "get_call_path"
    }

    # Validate each step
    for i, step in enumerate(steps):
        step_num = i + 1

        if not isinstance(step, dict):
            return f"Step {step_num}: must be a dictionary\n" \
                   f"  Hint: Each step needs 'tool' and optionally 'args', 'expect', 'description'"

        # Check required tool field
        if "tool" not in step:
            return f"Step {step_num}: missing required 'tool' field\n" \
                   f"  Hint: Add 'tool: tool_name' to specify which MCP tool to call"

        tool_name = step.get("tool")
        if not isinstance(tool_name, str):
            return f"Step {step_num}: 'tool' must be a string"

        # Validate tool name
        if tool_name not in supported_tools:
            return f"Step {step_num}: unknown tool '{tool_name}'\n" \
                   f"  Supported tools: {', '.join(sorted(supported_tools))}"

        # Validate args (if present)
        if "args" in step:
            args = step.get("args")
            if not isinstance(args, dict):
                return f"Step {step_num}: 'args' must be a dictionary\n" \
                       f"  Hint: Use YAML dictionary syntax:\n" \
                       f"    args:\n" \
                       f"      param1: value1\n" \
                       f"      param2: value2"

        # Validate expectations (if present)
        if "expect" in step:
            expect_error = _validate_expectations(step.get("expect"), step_num)
            if expect_error:
                return expect_error

        # Validate timeout (if present for wait_for_indexing)
        if tool_name == "wait_for_indexing" and "timeout" in step:
            timeout = step.get("timeout")
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                return f"Step {step_num}: 'timeout' must be a positive number\n" \
                       f"  Hint: Use timeout: 30 for 30 seconds"

    # Validate optional fields
    if "protocol" in scenario:
        protocol = scenario.get("protocol")
        if protocol not in ["http", "sse", "stdio"]:
            return f"Invalid protocol '{protocol}'\n" \
                   f"  Supported: http, sse, stdio"

    return None


def _validate_expectations(expectations, step_num):
    """
    Validate expectation list for a step

    Args:
        expectations: List of expectations
        step_num: Step number for error messages

    Returns:
        str: Error message if validation fails, None otherwise
    """
    if not isinstance(expectations, list):
        return f"Step {step_num}: 'expect' must be a list\n" \
               f"  Hint: Use YAML list syntax:\n" \
               f"    expect:\n" \
               f"      - type: count\n" \
               f"        operator: '>'\n" \
               f"        value: 0"

    supported_types = ["count", "content_includes", "content_matches", "has_field", "no_error"]

    for i, expectation in enumerate(expectations):
        exp_num = i + 1

        if not isinstance(expectation, dict):
            return f"Step {step_num}, expectation {exp_num}: must be a dictionary"

        # Check required type field
        if "type" not in expectation:
            return f"Step {step_num}, expectation {exp_num}: missing required 'type' field\n" \
                   f"  Supported types: {', '.join(supported_types)}"

        exp_type = expectation.get("type")
        if exp_type not in supported_types:
            return f"Step {step_num}, expectation {exp_num}: unknown type '{exp_type}'\n" \
                   f"  Supported types: {', '.join(supported_types)}"

        # Validate type-specific fields
        if exp_type == "count":
            if "operator" not in expectation:
                return f"Step {step_num}, expectation {exp_num}: 'count' type requires 'operator' field\n" \
                       f"  Supported operators: ==, !=, >, >=, <, <="
            if "value" not in expectation:
                return f"Step {step_num}, expectation {exp_num}: 'count' type requires 'value' field"

            operator = expectation.get("operator")
            if operator not in ["==", "!=", ">", ">=", "<", "<="]:
                return f"Step {step_num}, expectation {exp_num}: invalid operator '{operator}'\n" \
                       f"  Supported: ==, !=, >, >=, <, <="

            value = expectation.get("value")
            if not isinstance(value, (int, float)):
                return f"Step {step_num}, expectation {exp_num}: 'value' must be a number"

        elif exp_type == "content_includes":
            if "value" not in expectation:
                return f"Step {step_num}, expectation {exp_num}: 'content_includes' type requires 'value' field\n" \
                       f"  Hint: value: 'expected text'"

        elif exp_type == "content_matches":
            if "pattern" not in expectation:
                return f"Step {step_num}, expectation {exp_num}: 'content_matches' type requires 'pattern' field\n" \
                       f"  Hint: pattern: 'regex_pattern'"

            # Validate regex pattern
            pattern = expectation.get("pattern")
            try:
                re.compile(pattern)
            except re.error as e:
                return f"Step {step_num}, expectation {exp_num}: invalid regex pattern: {e}"

        elif exp_type == "has_field":
            if "field" not in expectation:
                return f"Step {step_num}, expectation {exp_num}: 'has_field' type requires 'field' field\n" \
                       f"  Hint: field: 'field_name'"

    return None


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
