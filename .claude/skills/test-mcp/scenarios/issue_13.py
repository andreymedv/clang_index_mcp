"""
Issue #13 Test Scenario - Boost Headers Parsing

Purpose: Reproduce Issue #13 - headers included by multiple sources parsed with wrong args
Project: tier2 (large project with boost dependencies - ~5700 files)
Duration: ~5-15 minutes

Background:
When compile_commands.json is used, headers included by multiple source files
should be processed only once (first-win strategy). If boost headers are parsed
with incorrect compilation arguments, symbols may be missing or incorrect.

Test Steps:
1. Start MCP server (SSE mode)
2. Call set_project_directory with tier2 path
3. Wait for indexing to complete (may take 5-10 minutes)
4. Query specific boost header symbols that were failing:
   - search for boost::mpl::vector
   - search for boost::fusion::vector
5. Check parse error logs for boost headers
6. Verify expected symbols are found
7. Shutdown server

Success Criteria (BEFORE FIX):
- Some boost headers may fail to parse or have missing symbols
- Parse errors in boost/mpl/ or boost/fusion/ headers

Success Criteria (AFTER FIX):
- All boost headers parse successfully
- Expected boost symbols found in search results
- No parse errors in boost headers
"""


def run(project_info, server_manager):
    """
    Execute Issue #13 test scenario

    Args:
        project_info: Project configuration dict
        server_manager: ServerManager instance (server already started)

    Returns:
        dict: Test results with status, metrics, issues
    """
    import time

    start_time = time.time()
    results = {
        "metrics": {},
        "details": {},
        "steps": [],
        "known_issue": {
            "number": 13,
            "title": "Headers with wrong compilation args",
            "symptoms": [
                "Boost headers fail to parse",
                "Missing symbols in boost namespace",
                "Parse errors in boost/mpl/ and boost/fusion/"
            ]
        }
    }

    try:
        endpoint = server_manager.server_process and f"http://localhost:{server_manager.port}"
        if not endpoint:
            raise RuntimeError("Server not started")

        # Step 1: Set project directory
        results["steps"].append("Setting project directory (tier2 - large project)...")
        print(f"  Setting project directory: {project_info['path']}")
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

        # Step 2: Wait for indexing to complete (may take 5-10 minutes for tier2)
        results["steps"].append("Waiting for indexing to complete (this may take 5-15 minutes)...")
        print("  This is a large project (~5700 files), please be patient...")
        max_wait = 900  # 15 minutes max for tier2
        wait_start = time.time()
        indexing_complete = False
        last_status_update = 0

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

                    # Print progress update every 30 seconds
                    if time.time() - last_status_update > 30:
                        elapsed = int(time.time() - wait_start)
                        print(f"  [{elapsed}s] Status: {status_text[:100]}...")
                        last_status_update = time.time()

                    # Check if indexing is complete
                    if "complete" in status_text.lower() or "ready" in status_text.lower():
                        indexing_complete = True
                        results["details"]["indexing_status"] = status_text
                        elapsed_min = (time.time() - wait_start) / 60
                        print(f"  ✓ Indexing completed in {elapsed_min:.1f} minutes")
                        break

            time.sleep(2)  # Check every 2 seconds

        if not indexing_complete:
            elapsed_min = (time.time() - wait_start) / 60
            results["error"] = f"Indexing did not complete within {max_wait/60:.0f} minutes (waited {elapsed_min:.1f}min). Last status: {results['details'].get('last_status', 'unknown')}"
            return results

        # Extract file count from status
        status_text = results["details"].get("indexing_status", "")
        # Try to parse file count (format: "X files indexed")
        import re
        file_match = re.search(r'(\d+)\s+files?\s+indexed', status_text, re.IGNORECASE)
        if file_match:
            results["metrics"]["files_indexed"] = int(file_match.group(1))
            results["metrics"]["total_files"] = project_info.get("file_count", "unknown")

        # Step 3: Search for boost::mpl symbols
        results["steps"].append("Searching for boost::mpl symbols...")
        print("  Searching for boost::mpl::vector...")
        mpl_response = server_manager.call_tool(
            endpoint,
            "search_symbols",
            {"pattern": "boost::mpl::vector", "project_only": False}
        )

        if "error" in mpl_response:
            print(f"  WARNING: search_symbols (mpl) failed: {mpl_response['error']}")
            results["metrics"]["boost_mpl_found"] = 0
        elif "result" in mpl_response:
            content = mpl_response["result"].get("content", [])
            if content:
                mpl_text = content[0].get("text", "")
                results["details"]["boost_mpl_response"] = mpl_text[:500]
                # Count occurrences
                mpl_count = mpl_text.count("boost::mpl::vector")
                results["metrics"]["boost_mpl_found"] = mpl_count
                print(f"  Found {mpl_count} boost::mpl::vector symbols")

        # Step 4: Search for boost::fusion symbols
        results["steps"].append("Searching for boost::fusion symbols...")
        print("  Searching for boost::fusion::vector...")
        fusion_response = server_manager.call_tool(
            endpoint,
            "search_symbols",
            {"pattern": "boost::fusion::vector", "project_only": False}
        )

        if "error" in fusion_response:
            print(f"  WARNING: search_symbols (fusion) failed: {fusion_response['error']}")
            results["metrics"]["boost_fusion_found"] = 0
        elif "result" in fusion_response:
            content = fusion_response["result"].get("content", [])
            if content:
                fusion_text = content[0].get("text", "")
                results["details"]["boost_fusion_response"] = fusion_text[:500]
                # Count occurrences
                fusion_count = fusion_text.count("boost::fusion::vector")
                results["metrics"]["boost_fusion_found"] = fusion_count
                print(f"  Found {fusion_count} boost::fusion::vector symbols")

        # Step 5: Check for parse errors (if available)
        results["steps"].append("Checking for parse errors...")
        # Note: This would require a dedicated MCP tool to expose parse error logs
        # For now, we check if symbols were found as a proxy
        results["details"]["parse_error_check"] = "Manual check required - no automated parse error log access"

        # Calculate total duration
        results["metrics"]["duration_s"] = round(time.time() - start_time, 1)
        results["metrics"]["duration_min"] = round(results["metrics"]["duration_s"] / 60, 1)

        # Determine success/failure based on Issue #13 criteria
        boost_found = results["metrics"].get("boost_mpl_found", 0) + results["metrics"].get("boost_fusion_found", 0)
        if boost_found > 0:
            results["details"]["issue_13_status"] = "FIXED - Boost symbols found successfully"
            print(f"  ✓ Issue #13 appears FIXED: Found {boost_found} boost symbols")
        else:
            results["details"]["issue_13_status"] = "REPRODUCED - No boost symbols found"
            print(f"  ⚠ Issue #13 may be REPRODUCED: No boost symbols found")

    except Exception as e:
        results["error"] = str(e)

    return results
