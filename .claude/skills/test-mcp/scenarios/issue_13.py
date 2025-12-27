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


def run(project_info, server_endpoint, protocol):
    """
    Execute Issue #13 test scenario

    Args:
        project_info: Project configuration dict
        server_endpoint: Server endpoint (e.g., "http://localhost:8000")
        protocol: Protocol type (sse, stdio, http)

    Returns:
        dict: Test results with status, metrics, issues
    """
    # TODO: Implement via Task agents
    # This will be implemented in Phase 1

    return {
        "status": "NOT_IMPLEMENTED",
        "message": "Test scenario implementation pending (Phase 1)",
        "expected_steps": [
            "Start MCP server (SSE)",
            "set_project_directory (tier2)",
            "Wait for indexing complete (~5700 files)",
            "Search for boost symbols",
            "Check parse error logs",
            "Verify symbol presence",
            "Shutdown server"
        ],
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
