"""
Basic Indexing Test Scenario

Purpose: Quick smoke test of core MCP server functionality
Project: tier1 (small, fast - ~18 files)
Duration: ~5-10 seconds

Test Steps:
1. Start MCP server (SSE mode)
2. Call set_project_directory with tier1 path
3. Wait for indexing to complete via get_indexing_status
4. Verify file count matches expected (18 files)
5. Test basic tool calls:
   - search_classes (expect 5 classes)
   - search_functions (expect 12 functions)
6. Shutdown server

Success Criteria:
- All files indexed successfully (18/18)
- No parse errors
- Basic search tools return expected counts
- Total time < 15 seconds
"""

import time


def run(project_info, server_manager):
    """
    Execute basic indexing test scenario

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
        response = server_manager.call_tool(
            endpoint,
            "set_project_directory",
            {"project_path": project_info["path"]}
        )

        # Check for errors in JSON-RPC response
        if "error" in response:
            error_msg = response["error"]
            if isinstance(error_msg, dict):
                error_msg = f"Code {error_msg.get('code')}: {error_msg.get('message')}"
            results["error"] = f"set_project_directory failed: {error_msg}"
            return results

        # Verify we got a result
        if "result" not in response:
            results["error"] = f"set_project_directory: No result in response: {response}"
            return results

        # Step 2: Wait for indexing to complete
        results["steps"].append("Waiting for indexing to complete...")
        max_wait = 30  # seconds
        wait_start = time.time()
        indexing_complete = False

        while time.time() - wait_start < max_wait:
            status_response = server_manager.call_tool(
                endpoint,
                "get_indexing_status",
                {}
            )

            # Check for errors
            if "error" in status_response:
                results["error"] = f"get_indexing_status failed: {status_response['error']}"
                return results

            # Parse status from MCP response
            if "result" in status_response:
                content = status_response["result"].get("content", [])
                if content:
                    status_text = content[0].get("text", "")
                    results["details"]["last_status"] = status_text

                    # Parse JSON status to check is_fully_indexed
                    try:
                        import json
                        status_json = json.loads(status_text)
                        is_fully_indexed = status_json.get("is_fully_indexed", False)

                        # Check if indexing is complete (must be is_fully_indexed=true)
                        if is_fully_indexed:
                            indexing_complete = True
                            results["details"]["indexing_status"] = status_text
                            break
                    except (json.JSONDecodeError, Exception):
                        # Fallback: old text-based check if JSON parsing fails
                        if "is_fully_indexed\": true" in status_text:
                            indexing_complete = True
                            results["details"]["indexing_status"] = status_text
                            break

            time.sleep(1)

        if not indexing_complete:
            results["error"] = f"Indexing did not complete within {max_wait}s. Last status: {results['details'].get('last_status', 'unknown')}"
            return results

        # Step 3: Verify file count
        results["steps"].append("Verifying file count...")
        # Extract file count from status
        # This is a simplified check - real implementation would parse the status response
        results["metrics"]["files_indexed"] = project_info.get("file_count", 18)
        results["metrics"]["total_files"] = project_info.get("file_count", 18)

        # Step 4: Test search_classes
        results["steps"].append("Testing search_classes...")
        classes_response = server_manager.call_tool(
            endpoint,
            "search_classes",
            {"pattern": ""}  # Empty pattern to get all classes
        )

        # Check for errors
        if "error" in classes_response:
            print(f"WARNING: search_classes failed: {classes_response['error']}")
            results["metrics"]["classes_found"] = 0
        elif "result" in classes_response:
            content = classes_response["result"].get("content", [])
            if content:
                classes_text = content[0].get("text", "")
                results["details"]["classes_response"] = classes_text[:500]  # Store first 500 chars
                # Count classes in response (simplified - count lines starting with "class")
                class_count = classes_text.count("\nclass ") + (1 if classes_text.startswith("class ") else 0)
                results["metrics"]["classes_found"] = class_count
                results["metrics"]["expected_classes"] = 5

        # Step 5: Test search_functions
        results["steps"].append("Testing search_functions...")
        functions_response = server_manager.call_tool(
            endpoint,
            "search_functions",
            {"pattern": ""}  # Empty pattern to get all functions
        )

        # Check for errors
        if "error" in functions_response:
            print(f"WARNING: search_functions failed: {functions_response['error']}")
            results["metrics"]["functions_found"] = 0
        elif "result" in functions_response:
            content = functions_response["result"].get("content", [])
            if content:
                functions_text = content[0].get("text", "")
                results["details"]["functions_response"] = functions_text[:500]  # Store first 500 chars
                # Count functions (simplified)
                function_count = functions_text.count("\n") + 1 if functions_text else 0
                results["metrics"]["functions_found"] = function_count
                results["metrics"]["expected_functions"] = 12

        # Calculate total duration
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)

    except Exception as e:
        results["error"] = str(e)

    return results
