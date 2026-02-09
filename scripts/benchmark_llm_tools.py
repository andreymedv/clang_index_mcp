#!/usr/bin/env python3
"""LLM benchmark harness for MCP tool usage evaluation.

Drives local LLMs (via LM Studio /api/v1/chat) against the C++ MCP server
and records tool call behavior to JSONL for analysis.

Usage:
    python scripts/benchmark_llm_tools.py --dry-run
    python scripts/benchmark_llm_tools.py --list-models
    python scripts/benchmark_llm_tools.py --model gpt-oss-20b --query A-01
    python scripts/benchmark_llm_tools.py  # full run, all models x all queries
"""

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Query definitions
# ---------------------------------------------------------------------------

QUERIES: list[dict[str, Any]] = [
    # Category A: Baseline (basic tool use)
    {
        "id": "A-01",
        "category": "baseline",
        "text": "Find the IEventListener class and show its methods",
        "expected_tools": ["search_classes", "get_class_info"],
    },
    {
        "id": "A-02",
        "category": "baseline",
        "text": "What classes derive from ReporterBase?",
        "expected_tools": ["search_classes", "get_derived_classes"],
    },
    {
        "id": "A-03",
        "category": "baseline",
        "text": ("List all functions defined in catch_session.cpp"),
        "expected_tools": ["search_functions"],
    },
    # Category B: Qualified name edge cases
    {
        "id": "B-01",
        "category": "qualified_names",
        "text": ("Get detailed info about the class " "Catch::Matchers::MatcherUntypedBase"),
        "expected_tools": ["get_class_info"],
    },
    {
        "id": "B-02",
        "category": "qualified_names",
        "text": ("Find the GeneratorWrapper class in the " "Catch::Generators namespace"),
        "expected_tools": ["search_classes"],
    },
    {
        "id": "B-03",
        "category": "qualified_names",
        "text": ("Find all classes in the Catch::Benchmark::Detail namespace"),
        "expected_tools": ["search_classes"],
    },
    # Category C: Signature/prototype confusion
    {
        "id": "C-01",
        "category": "signature_confusion",
        "text": ("Find the function void assertionEnded" "(AssertionStats const&)"),
        "expected_tools": ["search_functions"],
    },
    {
        "id": "C-02",
        "category": "signature_confusion",
        "text": "Where is the method bool match(T const& arg) defined?",
        "expected_tools": ["search_functions"],
    },
    {
        "id": "C-03",
        "category": "signature_confusion",
        "text": ("Find the function that takes an IConfig reference " "and returns ExecutionPlan"),
        "expected_tools": ["search_functions"],
    },
    # Category D: Regex pattern issues
    {
        "id": "D-01",
        "category": "regex_patterns",
        "text": "Find all classes whose name ends with Reporter",
        "expected_tools": ["search_classes"],
    },
    {
        "id": "D-02",
        "category": "regex_patterns",
        "text": (
            "Find all interface classes (names starting with I " "followed by uppercase letter)"
        ),
        "expected_tools": ["search_classes"],
    },
    {
        "id": "D-03",
        "category": "regex_patterns",
        "text": ("Find all functions containing 'benchmark' in their " "name (case-insensitive)"),
        "expected_tools": ["search_functions"],
    },
    # Category E: Multi-tool workflows
    {
        "id": "E-01",
        "category": "multi_tool",
        "text": (
            "Show me the full class hierarchy from IEventListener "
            "down to ConsoleReporter, including intermediate classes"
        ),
        "expected_tools": [
            "search_classes",
            "get_class_info",
            "get_class_hierarchy",
        ],
    },
    {
        "id": "E-02",
        "category": "multi_tool",
        "text": (
            "Find all concrete matcher classes and show what " "MatcherBase they inherit from"
        ),
        "expected_tools": ["search_classes", "get_class_hierarchy"],
    },
    {
        "id": "E-03",
        "category": "multi_tool",
        "text": ("Find all places in the codebase that call the " "assertionEnded method"),
        "expected_tools": ["search_functions", "find_callers"],
    },
]

SYSTEM_PROMPT = """\
You are a C++ code analysis assistant. You have access to MCP tools that can
search and analyze an indexed C++ codebase (the Catch2 testing framework).

IMPORTANT: The project is already indexed. Do NOT call set_project_directory.
Go directly to answering the question using search and query tools.

Use the available tools to answer the user's question. Be precise with tool
arguments -- use class/function names, not signatures. For regex patterns,
remember that patterns are anchored (matched against full name).

When you find what you need, provide a concise answer summarizing the results.\
"""

SETUP_PROMPT = """\
You are a C++ code analysis assistant. Call set_project_directory with the \
path "{project_path}" to index the project. Say "Done" when complete.\
"""

DEFAULT_CHAT_MODELS = [
    "nanbeige4-3b-thinking-2511",
    "qwen/qwen3-4b-2507",
    "qwen3-30b-a3b-thinking-2507",
    "qwen3-next-80b-a3b-instruct",
    "qwen3-coder-30b-a3b-instruct",
    "gpt-oss-20b",
    "gpt-oss-120b",
    "codestral-22b-v0.1",
]


# ---------------------------------------------------------------------------
# LM Studio client
# ---------------------------------------------------------------------------


@dataclass
class LMStudioClient:
    """Thin wrapper around LM Studio /api/v1/chat (non-streaming)."""

    base_url: str = "http://localhost:1234"
    token: str = ""
    timeout: int = 300  # seconds

    def _request(
        self,
        path: str,
        data: Optional[dict[str, Any]] = None,
        method: str = "GET",
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def list_models(self) -> list[dict[str, Any]]:
        """GET /v1/models — return list of loaded models."""
        resp = self._request("/v1/models")
        models: list[dict[str, Any]] = resp.get("data", [])
        # Filter out embedding models
        return [m for m in models if not m.get("id", "").startswith("text-embedding-")]

    def chat(
        self,
        model: str,
        user_input: str,
        system_prompt: str,
        mcp_url: str,
        max_output_tokens: int = 8192,
        temperature: float = 0,
    ) -> dict[str, Any]:
        """POST /api/v1/chat — single turn with MCP integration."""
        payload: dict[str, Any] = {
            "model": model,
            "input": user_input,
            "system_prompt": system_prompt,
            "integrations": [
                {
                    "type": "ephemeral_mcp",
                    "server_label": "cpp-analyzer",
                    "server_url": mcp_url,
                }
            ],
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "stream": False,
            "store": False,
        }
        return self._request("/api/v1/chat", data=payload, method="POST")


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------


def _count_results(tool_output: str) -> Optional[int]:
    """Try to count result items from MCP tool JSON output."""
    try:
        parsed = json.loads(tool_output)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(parsed, list):
        return len(parsed)
    if isinstance(parsed, dict):
        # Some tools return {"count": N} or {"results": [...]}
        if "count" in parsed:
            return int(parsed["count"])
        if "results" in parsed and isinstance(parsed["results"], list):
            return len(parsed["results"])
        # Single result dict
        return 1
    return None


def extract_record(
    model: str,
    query: dict[str, Any],
    response: dict[str, Any],
    wall_time: float,
) -> dict[str, Any]:
    """Extract a benchmark record from the LM Studio v1 API response."""
    tool_calls: list[dict[str, Any]] = []
    final_answer = ""
    error: Optional[str] = None
    empty_result_count = 0

    output_items = response.get("output", [])
    for item in output_items:
        item_type = item.get("type", "")
        if item_type == "tool_call":
            result_count = _count_results(item.get("output", ""))
            tc: dict[str, Any] = {
                "tool": item.get("tool", ""),
                "arguments": item.get("arguments", {}),
            }
            if result_count is not None:
                tc["result_count"] = result_count
                if result_count == 0:
                    empty_result_count += 1
            tool_calls.append(tc)
        elif item_type == "message":
            content = item.get("content", "")
            if isinstance(content, list):
                # content can be list of {type: text, text: ...}
                parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                final_answer = "\n".join(parts)
            elif isinstance(content, str):
                final_answer = content

    # Extract stats
    raw_stats = response.get("stats", {})
    stats: dict[str, Any] = {}
    if raw_stats:
        stats = {
            "input_tokens": raw_stats.get("input_tokens"),
            "output_tokens": raw_stats.get("total_output_tokens"),
            "tokens_per_second": raw_stats.get("tokens_per_second"),
        }

    # Check for max tokens
    if response.get("stop_reason") == "max_tokens":
        error = "max_tokens_exceeded"

    return {
        "source": "benchmark",
        "model_id": model,
        "query_id": query["id"],
        "query_category": query["category"],
        "query_text": query["text"],
        "expected_tools": query["expected_tools"],
        "tool_calls": tool_calls,
        "total_tool_calls": len(tool_calls),
        "empty_result_count": empty_result_count,
        "final_answer": final_answer,
        "stats": stats,
        "wall_time_seconds": round(wall_time, 2),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkRunner:
    """Orchestrates (model x query) benchmark matrix."""

    client: LMStudioClient
    mcp_url: str = "http://127.0.0.1:8123/sse"
    max_tokens: int = 8192
    temperature: float = 0
    output_path: str = "benchmark_results.jsonl"
    _interrupted: bool = field(default=False, init=False, repr=False)

    def _write_record(self, record: dict[str, Any]) -> None:
        with open(self.output_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def run(
        self,
        models: list[str],
        queries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run benchmark matrix. Returns list of records."""
        total = len(models) * len(queries)
        records: list[dict[str, Any]] = []
        count = 0

        for model in models:
            if self._interrupted:
                break

            print(f"\n{'=' * 60}")
            print(f"Model: {model}")
            print(f"{'=' * 60}")

            for query in queries:
                if self._interrupted:
                    break

                count += 1
                print(f"\n[{count}/{total}] {query['id']}: " f"{query['text'][:60]}...")

                record = self._run_single(model, query)
                records.append(record)
                self._write_record(record)

                if record["error"]:
                    print(f"  ERROR: {record['error']}")
                else:
                    tools_used = [tc["tool"] for tc in record["tool_calls"]]
                    print(f"  Tools: {tools_used} " f"({record['wall_time_seconds']}s)")

        return records

    def _run_single(self, model: str, query: dict[str, Any]) -> dict[str, Any]:
        """Run a single (model, query) pair."""
        start = time.time()
        try:
            response = self.client.chat(
                model=model,
                user_input=query["text"],
                system_prompt=SYSTEM_PROMPT,
                mcp_url=self.mcp_url,
                max_output_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            wall_time = time.time() - start
            return extract_record(model, query, response, wall_time)
        except urllib.error.URLError as e:
            wall_time = time.time() - start
            return {
                "source": "benchmark",
                "model_id": model,
                "query_id": query["id"],
                "query_category": query["category"],
                "query_text": query["text"],
                "expected_tools": query["expected_tools"],
                "tool_calls": [],
                "total_tool_calls": 0,
                "empty_result_count": 0,
                "final_answer": "",
                "stats": {},
                "wall_time_seconds": round(wall_time, 2),
                "error": f"connection_error: {e}",
            }
        except json.JSONDecodeError as e:
            wall_time = time.time() - start
            return {
                "source": "benchmark",
                "model_id": model,
                "query_id": query["id"],
                "query_category": query["category"],
                "query_text": query["text"],
                "expected_tools": query["expected_tools"],
                "tool_calls": [],
                "total_tool_calls": 0,
                "empty_result_count": 0,
                "final_answer": "",
                "stats": {},
                "wall_time_seconds": round(wall_time, 2),
                "error": f"json_decode_error: {e}",
            }

    def handle_interrupt(self, signum: int, frame: Any) -> None:  # noqa: ANN401
        """Handle Ctrl-C gracefully."""
        if self._interrupted:
            print("\nForced exit.")
            sys.exit(1)
        print("\nInterrupted — finishing current query and saving results...")
        self._interrupted = True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def filter_queries(
    queries: list[dict[str, Any]],
    query_ids: Optional[list[str]],
    categories: Optional[list[str]],
) -> list[dict[str, Any]]:
    """Filter queries by ID or category."""
    result = queries
    if query_ids:
        ids_upper = [qid.upper() for qid in query_ids]
        result = [q for q in result if q["id"] in ids_upper]
    if categories:
        cats_upper = [c.upper() for c in categories]
        result = [q for q in result if q["id"][0] in cats_upper or q["category"] in categories]
    return result


def filter_models(available: list[str], requested: Optional[list[str]]) -> list[str]:
    """Filter models by substring match."""
    if not requested:
        return available
    result = []
    for req in requested:
        matches = [m for m in available if req in m]
        if matches:
            result.extend(matches)
        else:
            print(f"Warning: no model matching '{req}' found, skipping")
    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for m in result:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    return deduped


def cmd_dry_run(models: list[str], queries: list[dict[str, Any]]) -> None:
    """Print what would be executed without running."""
    print(f"Models ({len(models)}):")
    for m in models:
        print(f"  - {m}")
    print(f"\nQueries ({len(queries)}):")
    for q in queries:
        print(f"  [{q['id']}] ({q['category']}) {q['text'][:70]}")
    print(f"\nTotal runs: {len(models) * len(queries)}")


def cmd_list_models(client: LMStudioClient) -> None:
    """List available chat models from LM Studio."""
    try:
        models = client.list_models()
    except urllib.error.URLError as e:
        print(f"Error connecting to LM Studio: {e}")
        sys.exit(1)

    if not models:
        print("No chat models loaded in LM Studio.")
        return

    print(f"Available chat models ({len(models)}):")
    for m in models:
        model_id = m.get("id", "unknown")
        print(f"  - {model_id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LLM benchmark harness for MCP tool usage evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --dry-run\n"
            "  %(prog)s --list-models\n"
            "  %(prog)s --model gpt-oss-20b --query A-01\n"
            "  %(prog)s --category A --category B\n"
            "  %(prog)s  # full run\n"
        ),
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        metavar="MODEL",
        help="Run only this model (substring match). Repeat for multiple.",
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        metavar="ID",
        help="Run only this query (e.g., A-01). Repeat for multiple.",
    )
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        metavar="CAT",
        help="Run only queries in category (A/B/C/D/E or name).",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.jsonl",
        help="JSONL output file (default: benchmark_results.jsonl)",
    )
    parser.add_argument(
        "--lm-url",
        default=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
        help="LM Studio base URL (default: http://localhost:1234)",
    )
    parser.add_argument(
        "--mcp-url",
        default=os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8123/sse"),
        help="MCP server SSE URL (default: http://127.0.0.1:8123/sse)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("LM_STUDIO_TOKEN", ""),
        help="LM Studio auth token (env: LM_STUDIO_TOKEN)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8192,
        help="Max output tokens (default: 8192)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Temperature (default: 0)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--project-path",
        default=os.environ.get("BENCHMARK_PROJECT_PATH", "/home/andrey/repos/catch2-benchmark"),
        help="C++ project path for MCP indexing (default: catch2-benchmark)",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip project setup (assume already indexed)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List queries and models without executing",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Query LM Studio and list available chat models",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    client = LMStudioClient(
        base_url=args.lm_url,
        token=args.token,
        timeout=args.timeout,
    )

    # --list-models
    if args.list_models:
        cmd_list_models(client)
        return

    # Resolve models
    if args.models:
        models = filter_models(DEFAULT_CHAT_MODELS, args.models)
    else:
        models = list(DEFAULT_CHAT_MODELS)

    # Resolve queries
    queries = filter_queries(QUERIES, args.queries, args.categories)
    if not queries:
        print("No queries match the specified filters.")
        sys.exit(1)

    # --dry-run
    if args.dry_run:
        cmd_dry_run(models, queries)
        return

    if not models:
        print("No models match the specified filters.")
        sys.exit(1)

    # Pre-index project via LM Studio → MCP tool call
    if not args.skip_setup:
        setup_model = models[0]
        print(f"Setting up project: {args.project_path}")
        print(f"  Using model: {setup_model}")
        try:
            setup_resp = client.chat(
                model=setup_model,
                user_input=SETUP_PROMPT.format(project_path=args.project_path),
                system_prompt="",
                mcp_url=args.mcp_url,
                max_output_tokens=1024,
                temperature=0,
            )
            # Check if set_project_directory was called
            setup_tools = [
                item.get("tool", "")
                for item in setup_resp.get("output", [])
                if item.get("type") == "tool_call"
            ]
            if "set_project_directory" in setup_tools:
                print("  Project indexed successfully.")
            else:
                print(f"  Warning: setup did not call set_project_directory (tools: {setup_tools})")
        except urllib.error.URLError as e:
            print(f"  Error during setup: {e}")
            print("  Use --skip-setup if project is already indexed.")
            sys.exit(1)

    # Run benchmark
    runner = BenchmarkRunner(
        client=client,
        mcp_url=args.mcp_url,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        output_path=args.output,
    )

    # Register interrupt handler
    signal.signal(signal.SIGINT, runner.handle_interrupt)

    print(f"Benchmark: {len(models)} models x {len(queries)} queries")
    print(f"Output: {args.output}")
    print(f"LM Studio: {args.lm_url}")
    print(f"MCP Server: {args.mcp_url}")

    records = runner.run(models, queries)

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    total = len(records)
    errors = sum(1 for r in records if r["error"])
    tool_using = sum(1 for r in records if r["total_tool_calls"] > 0)
    empty_results = sum(r["empty_result_count"] for r in records)
    print(f"Total runs:        {total}")
    print(f"With tool calls:   {tool_using}")
    print(f"Errors:            {errors}")
    print(f"Empty results:     {empty_results}")
    print(f"Results written to: {args.output}")


if __name__ == "__main__":
    main()
