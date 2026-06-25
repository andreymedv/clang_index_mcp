"""Query policy helpers for the C++ MCP server."""

from ..context import ctx
from ..state_manager import QueryBehaviorPolicy
from ..._core import diagnostics


def _parse_query_policy(policy_str: str) -> QueryBehaviorPolicy:
    """Parse a query behavior policy string with fallback to ALLOW_PARTIAL."""
    try:
        return QueryBehaviorPolicy(policy_str)
    except ValueError:
        diagnostics.warning(
            f"Invalid query_behavior_policy: {policy_str}, defaulting to allow_partial"
        )
        return QueryBehaviorPolicy.ALLOW_PARTIAL


def _build_block_message(progress) -> str:
    """Build a message explaining that queries are blocked due to indexing."""
    if progress:
        return (
            f"Query blocked: Indexing in progress ({progress.completion_percentage:.1f}% complete, "
            f"{progress.indexed_files:,}/{progress.total_files:,} files). Waiting for indexing to complete...\n\n"
            f"Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial "
            f"to allow queries during indexing."
        )
    return (
        "Query blocked: Indexing in progress. Waiting for completion...\n\n"
        "Use 'sync_project' tool or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial."
    )


def _build_reject_message(progress) -> str:
    """Build a message explaining that queries are rejected due to indexing."""
    if progress:
        return (
            f"ERROR: Query rejected - indexing in progress ({progress.completion_percentage:.1f}% complete, "
            f"{progress.indexed_files:,}/{progress.total_files:,} files).\n\n"
            f"Queries are not allowed until indexing completes. Options:\n"
            f"1. Use 'sync_project' tool to wait for completion\n"
            f"2. Check progress with 'sync_project'\n"
            f"3. Set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial to allow partial results\n"
            f"4. Set CPP_ANALYZER_QUERY_BEHAVIOR=block to auto-wait for completion"
        )
    return (
        "ERROR: Query rejected - indexing in progress.\n\n"
        "Use 'sync_project' or set CPP_ANALYZER_QUERY_BEHAVIOR=allow_partial/block."
    )


def check_query_policy(tool_name: str) -> tuple[bool, str]:
    """
    Check if query is allowed based on current indexing state and policy.

    Args:
        tool_name: Name of the tool being called

    Returns:
        Tuple of (allowed: bool, message: str)
        - If allowed=True, query can proceed (message will be empty)
        - If allowed=False, query should be blocked/rejected (message contains error/wait info)
    """
    if ctx.state_manager.is_fully_indexed():
        return (True, "")

    if not ctx.state_manager.is_ready_for_queries():
        return (True, "")

    if ctx.analyzer is None:
        return (True, "")

    policy = _parse_query_policy(ctx.analyzer.config.get_query_behavior_policy())

    if policy == QueryBehaviorPolicy.ALLOW_PARTIAL:
        return (True, "")

    if policy == QueryBehaviorPolicy.BLOCK:
        message = _build_block_message(ctx.state_manager.get_progress())
        completed = ctx.state_manager.wait_for_indexed(timeout=30.0)
        if completed:
            return (True, "")
        return (
            False,
            message
            + "\n\nTimeout waiting for indexing (30s). Try again later or use 'sync_project'.",
        )

    if policy == QueryBehaviorPolicy.REJECT:
        return (False, _build_reject_message(ctx.state_manager.get_progress()))

    return (True, "")
