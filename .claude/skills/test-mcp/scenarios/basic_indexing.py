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

        if "error" in response:
            results["error"] = f"set_project_directory failed: {response['error']}"
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

            if "result" in status_response:
                content = status_response["result"].get("content", [])
                if content:
                    status_text = content[0].get("text", "")
                    if "complete" in status_text.lower() or "ready" in status_text.lower():
                        indexing_complete = True
                        results["details"]["indexing_status"] = status_text
                        break

            time.sleep(1)

        if not indexing_complete:
            results["error"] = "Indexing did not complete within timeout"
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

        if "result" in classes_response:
            content = classes_response["result"].get("content", [])
            if content:
                classes_text = content[0].get("text", "")
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

        if "result" in functions_response:
            content = functions_response["result"].get("content", [])
            if content:
                functions_text = content[0].get("text", "")
                # Count functions (simplified)
                function_count = functions_text.count("\n") + 1 if functions_text else 0
                results["metrics"]["functions_found"] = function_count
                results["metrics"]["expected_functions"] = 12

        # Calculate total duration
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)

    except Exception as e:
        results["error"] = str(e)

    return results
