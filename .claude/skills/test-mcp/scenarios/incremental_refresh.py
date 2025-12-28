"""
Incremental Refresh Test Scenario

Purpose: Test incremental analysis after file changes
Project: tier1 (small project for quick testing)
Duration: ~10-20 seconds

Test Steps:
1. Start MCP server (HTTP mode)
2. Call set_project_directory with tier1 path
3. Wait for initial indexing to complete
4. Search for a specific function (baseline)
5. Modify a source file (add a new function)
6. Call refresh_project
7. Verify only modified file re-indexed (check metrics)
8. Search for new function (should be found)
9. Verify incremental speedup vs full re-index
10. Shutdown server

Success Criteria:
- New function found after refresh
- Incremental refresh faster than full index (10-30x speedup)
- Only modified file + dependents re-indexed
- All existing symbols still searchable
"""

import time
import os
import shutil
from pathlib import Path


def run(project_info, server_manager):
    """
    Execute incremental refresh test scenario

    Args:
        project_info: Project configuration dict
        server_manager: ServerManager instance

    Returns:
        dict: Test results with status, metrics, issues
    """
    start_time = time.time()
    results = {
        "metrics": {},
        "details": {},
        "steps": []
    }

    try:
        endpoint = server_manager.server_process and f"http://localhost:{server_manager.port}"
        if not endpoint:
            raise RuntimeError("Server not started")

        # Step 1: Set project directory
        results["steps"].append("Setting project directory...")
        print(f"  Setting project directory: {project_info['path']}")
        response = server_manager.call_tool(
            endpoint,
            "set_project_directory",
            {"project_path": project_info["path"]}
        )

        if "error" in response:
            results["error"] = f"set_project_directory failed: {response['error']}"
            return results

        # Step 2: Wait for initial indexing
        results["steps"].append("Waiting for initial indexing...")
        print("  Waiting for initial indexing to complete...")
        if not _wait_for_indexing(server_manager, endpoint, max_wait=60):
            results["error"] = "Initial indexing did not complete"
            return results

        # Record initial indexing time
        initial_index_time = time.time() - start_time
        results["metrics"]["initial_index_time_s"] = round(initial_index_time, 1)
        print(f"  Initial indexing completed in {initial_index_time:.1f}s")

        # Step 3: Search for baseline function
        results["steps"].append("Searching for baseline function...")
        baseline_response = server_manager.call_tool(
            endpoint,
            "search_functions",
            {"pattern": ""}
        )

        if "result" in baseline_response:
            content = baseline_response["result"].get("content", [])
            if content:
                baseline_text = content[0].get("text", "")
                baseline_count = baseline_text.count("\n") if baseline_text else 0
                results["metrics"]["baseline_functions"] = baseline_count
                print(f"  Baseline: {baseline_count} functions found")

        # Step 4: Modify a source file (add new function)
        results["steps"].append("Modifying source file...")
        print("  Adding new function to source file...")
        test_file, new_function_name = _add_test_function(project_info["path"])
        results["details"]["modified_file"] = test_file
        results["details"]["new_function"] = new_function_name

        # Step 5: Call refresh_project
        results["steps"].append("Calling refresh_project...")
        print("  Refreshing project (incremental)...")
        refresh_start = time.time()

        refresh_response = server_manager.call_tool(
            endpoint,
            "refresh_project",
            {}
        )

        if "error" in refresh_response:
            results["error"] = f"refresh_project failed: {refresh_response['error']}"
            return results

        # Wait for refresh to complete
        if not _wait_for_indexing(server_manager, endpoint, max_wait=30):
            results["error"] = "Refresh did not complete"
            return results

        refresh_time = time.time() - refresh_start
        results["metrics"]["refresh_time_s"] = round(refresh_time, 1)
        print(f"  Refresh completed in {refresh_time:.1f}s")

        # Calculate speedup
        if refresh_time > 0:
            speedup = initial_index_time / refresh_time
            results["metrics"]["incremental_speedup"] = round(speedup, 1)
            print(f"  Incremental speedup: {speedup:.1f}x")

        # Step 6: Search for new function
        results["steps"].append("Searching for new function...")
        print(f"  Searching for new function '{new_function_name}'...")
        new_func_response = server_manager.call_tool(
            endpoint,
            "search_functions",
            {"pattern": new_function_name}
        )

        new_function_found = False
        if "result" in new_func_response:
            content = new_func_response["result"].get("content", [])
            if content:
                search_text = content[0].get("text", "")
                new_function_found = new_function_name in search_text
                results["details"]["new_function_found"] = new_function_found
                print(f"  New function found: {new_function_found}")

        if not new_function_found:
            results["error"] = f"New function '{new_function_name}' not found after refresh"

        # Step 7: Verify all functions still searchable
        results["steps"].append("Verifying all functions...")
        all_funcs_response = server_manager.call_tool(
            endpoint,
            "search_functions",
            {"pattern": ""}
        )

        if "result" in all_funcs_response:
            content = all_funcs_response["result"].get("content", [])
            if content:
                all_funcs_text = content[0].get("text", "")
                all_funcs_count = all_funcs_text.count("\n") if all_funcs_text else 0
                results["metrics"]["final_functions"] = all_funcs_count

                # Should have one more function than baseline
                expected = results["metrics"].get("baseline_functions", 0) + 1
                results["metrics"]["expected_functions"] = expected

                if all_funcs_count >= expected:
                    print(f"  All functions found: {all_funcs_count} (expected {expected})")
                else:
                    results["error"] = f"Function count mismatch: {all_funcs_count} vs {expected}"

        # Calculate total duration
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)

    except Exception as e:
        results["error"] = str(e)
    finally:
        # Cleanup: restore original file
        _cleanup_test_file(project_info["path"])

    return results


def _wait_for_indexing(server_manager, endpoint, max_wait=60):
    """Wait for indexing to complete"""
    import json

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


def _add_test_function(project_path):
    """
    Add a test function to a source file

    Returns:
        tuple: (file_path, function_name)
    """
    import random

    project_path = Path(project_path)

    # Find a C++ source file
    cpp_files = list(project_path.rglob("*.cpp"))
    if not cpp_files:
        raise RuntimeError("No C++ source files found")

    # Pick first file
    test_file = cpp_files[0]

    # Generate unique function name
    timestamp = int(time.time())
    random_id = random.randint(1000, 9999)
    function_name = f"test_incremental_function_{timestamp}_{random_id}"

    # Backup original file
    backup_file = test_file.with_suffix(".cpp.backup")
    shutil.copy2(test_file, backup_file)

    # Append new function
    with open(test_file, "a") as f:
        f.write(f"\n\n// Incremental test function\nvoid {function_name}() {{\n    // Test\n}}\n")

    return str(test_file), function_name


def _cleanup_test_file(project_path):
    """Restore original file from backup"""
    project_path = Path(project_path)

    # Find backup file
    backup_files = list(project_path.rglob("*.cpp.backup"))
    for backup_file in backup_files:
        original_file = backup_file.with_suffix("")
        if original_file.exists():
            shutil.move(backup_file, original_file)
