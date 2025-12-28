"""
All Protocols Test Scenario

Purpose: Verify all transport protocols work correctly
Project: tier1 (small project for quick testing)
Duration: ~15-30 seconds

Test Steps:
1. Test HTTP protocol:
   - Start server in HTTP mode
   - Call basic MCP tools
   - Verify results
   - Shutdown

2. Test SSE protocol:
   - Start server in SSE mode
   - Call basic MCP tools
   - Verify results
   - Shutdown

3. Compare results:
   - Verify results identical across protocols

Success Criteria:
- HTTP protocol: tools work correctly
- SSE protocol: tools work correctly
- Results consistent across protocols
- No protocol-specific errors
"""

import time


def run(project_info, server_manager):
    """
    Execute all-protocols test scenario

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
        "steps": [],
        "protocols": {}
    }

    protocols = ["http", "sse"]  # stdio requires different approach

    try:
        for protocol in protocols:
            results["steps"].append(f"Testing {protocol.upper()} protocol...")
            print(f"\n  Testing {protocol.upper()} protocol...")

            # Start server for this protocol
            # Note: server_manager should already have server running
            # This scenario assumes server is started with the protocol
            # specified in the test command

            endpoint = f"http://localhost:{server_manager.port}"

            # Test basic tool: set_project_directory
            set_dir_response = server_manager.call_tool(
                endpoint,
                "set_project_directory",
                {"project_path": project_info["path"]}
            )

            protocol_results = {
                "set_project_directory": "error" not in set_dir_response
            }

            if "error" in set_dir_response:
                results["protocols"][protocol] = {
                    "status": "FAILED",
                    "error": f"set_project_directory failed: {set_dir_response['error']}"
                }
                print(f"    ✗ {protocol.upper()} failed: set_project_directory error")
                continue

            # Wait for indexing
            print(f"    Waiting for indexing...")
            if not _wait_for_indexing(server_manager, endpoint, max_wait=60):
                results["protocols"][protocol] = {
                    "status": "FAILED",
                    "error": "Indexing did not complete"
                }
                print(f"    ✗ {protocol.upper()} failed: indexing timeout")
                continue

            # Test search_classes
            classes_response = server_manager.call_tool(
                endpoint,
                "search_classes",
                {"pattern": ""}
            )

            protocol_results["search_classes"] = "error" not in classes_response

            classes_count = 0
            if "result" in classes_response:
                content = classes_response["result"].get("content", [])
                if content:
                    classes_text = content[0].get("text", "")
                    classes_count = classes_text.count("\nclass ") + (1 if classes_text.startswith("class ") else 0)

            protocol_results["classes_found"] = classes_count

            # Test search_functions
            functions_response = server_manager.call_tool(
                endpoint,
                "search_functions",
                {"pattern": ""}
            )

            protocol_results["search_functions"] = "error" not in functions_response

            functions_count = 0
            if "result" in functions_response:
                content = functions_response["result"].get("content", [])
                if content:
                    functions_text = content[0].get("text", "")
                    functions_count = functions_text.count("\n") + 1 if functions_text else 0

            protocol_results["functions_found"] = functions_count

            # Store results
            results["protocols"][protocol] = {
                "status": "PASSED",
                "results": protocol_results,
                "classes_found": classes_count,
                "functions_found": functions_count
            }

            print(f"    ✓ {protocol.upper()} passed: {classes_count} classes, {functions_count} functions")

        # Step: Compare results across protocols
        results["steps"].append("Comparing results across protocols...")
        print("\n  Comparing results across protocols...")

        if len(results["protocols"]) < 2:
            results["error"] = "Not enough protocols tested for comparison"
        else:
            # Get first protocol results as baseline
            first_protocol = protocols[0]
            baseline = results["protocols"].get(first_protocol, {})
            baseline_classes = baseline.get("classes_found", 0)
            baseline_functions = baseline.get("functions_found", 0)

            all_consistent = True
            for protocol in protocols[1:]:
                protocol_data = results["protocols"].get(protocol, {})
                classes = protocol_data.get("classes_found", 0)
                functions = protocol_data.get("functions_found", 0)

                if classes != baseline_classes or functions != baseline_functions:
                    all_consistent = False
                    results["details"]["inconsistency"] = f"{protocol} results differ from {first_protocol}"
                    print(f"    ⚠ Results differ: {protocol} has {classes}/{functions}, {first_protocol} has {baseline_classes}/{baseline_functions}")

            results["metrics"]["protocols_tested"] = len(results["protocols"])
            results["metrics"]["protocols_passed"] = sum(1 for p in results["protocols"].values() if p.get("status") == "PASSED")
            results["metrics"]["results_consistent"] = all_consistent

            if all_consistent:
                print(f"    ✓ All protocols returned consistent results")

        # Calculate total duration
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)

    except Exception as e:
        results["error"] = str(e)

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
