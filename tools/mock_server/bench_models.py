#!/usr/bin/env python3
"""Multi-model benchmark runner for MCP tool description quality.

Loads each model via lms, runs all scenario files, saves per-model results,
then prints a comparison table. Designed to run unattended overnight.

Usage:
    python tools/mock_server/bench_models.py qwen3-4b qwen3-8b qwen3-14b
    python tools/mock_server/bench_models.py --scenarios real_workflows.yaml qwen3-4b
    python tools/mock_server/bench_models.py --no-unload qwen3-4b   # keep model loaded

Output:
    tools/mock_server/optimization_runs/bench_<timestamp>/
        <model_safe_name>.json    — per-model results
        summary.json             — cross-model comparison
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
RUNNER = SCRIPT_DIR / "runner.py"
SCENARIOS_DIR = SCRIPT_DIR / "scenarios"
FIXTURES_DIR = SCRIPT_DIR / "fixtures"
RUNS_DIR = SCRIPT_DIR / "optimization_runs"

LM_URL = "http://localhost:1234"
MODEL_READY_TIMEOUT = 120   # seconds to wait for model to load
MODEL_READY_POLL = 3        # seconds between polls


# ---------------------------------------------------------------------------
# LM Studio helpers
# ---------------------------------------------------------------------------

def get_loaded_models() -> list[str]:
    """Return list of currently loaded model IDs via `lms ps`."""
    try:
        result = subprocess.run(
            ["lms", "ps"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().splitlines()
        # lms ps output: first line is header, subsequent lines are models
        # e.g.: "  qwen3-8b-mlx  ..."  or just the model id per line
        models = []
        for line in lines[1:]:  # skip header
            line = line.strip()
            if line:
                # first whitespace-separated token is the model identifier
                model_id = line.split()[0]
                models.append(model_id)
        return models
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def unload_all_models() -> None:
    """Unload all loaded models via `lms unload --all`."""
    try:
        subprocess.run(
            ["lms", "unload", "--all"],
            check=False, capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def load_model(model_id: str, timeout: int = MODEL_READY_TIMEOUT) -> bool:
    """Load model via lms CLI and wait until it appears in `lms ps`."""
    print(f"  Loading {model_id}...", flush=True)
    try:
        subprocess.run(
            ["lms", "load", model_id, "--yes"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: lms load failed: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        print("  ERROR: lms CLI not found. Install LM Studio CLI.")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        models = get_loaded_models()
        if any(model_id in m or m in model_id for m in models):
            print(f"  Ready: {models[0] if models else model_id}", flush=True)
            return True
        time.sleep(MODEL_READY_POLL)

    print(f"  ERROR: model not ready after {timeout}s")
    return False


def resolve_model_id(model_arg: str) -> str:
    """Return the actual model ID from `lms ps` matching model_arg."""
    models = get_loaded_models()
    for m in models:
        if model_arg in m or m in model_arg:
            return m
    return model_arg


# ---------------------------------------------------------------------------
# Timing statistics
# ---------------------------------------------------------------------------

def calculate_per_tool_time(results: list[dict]) -> dict:
    """Calculate average time per tool invocation.

    Returns dict with:
        - avg_time_per_tool: average wall_time / total_tool_calls across all tests
        - total_wall_time: sum of all wall_time_seconds
        - total_tool_calls: sum of all tool calls
        - test_count: number of tests with timing data
    """
    total_wall_time = 0.0
    total_tool_calls = 0
    test_count = 0

    for r in results:
        wall_time = r.get("wall_time_seconds")
        tool_calls = r.get("total_tool_calls")

        # Only count tests that have both timing and tool call data
        if wall_time is not None and tool_calls is not None and tool_calls > 0:
            total_wall_time += wall_time
            total_tool_calls += tool_calls
            test_count += 1

    if total_tool_calls == 0:
        return {
            "avg_time_per_tool": 0.0,
            "total_wall_time": 0.0,
            "total_tool_calls": 0,
            "test_count": 0,
        }

    return {
        "avg_time_per_tool": round(total_wall_time / total_tool_calls, 2),
        "total_wall_time": round(total_wall_time, 2),
        "total_tool_calls": total_tool_calls,
        "test_count": test_count,
    }


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------

def safe_filename(model_id: str) -> str:
    """Convert model ID to a safe filename component."""
    return model_id.replace("/", "_").replace(":", "_").replace(" ", "_")


def run_scenarios(
    model_id: str,
    scenario_files: list[Path],
    output_path: Path,
    lm_url: str,
    explain_failures: bool,
    explain_all: bool,
    explain_scope: str,
    token: str = "sk-lm-local",
    eval_mode: str = "strict",
) -> dict:
    """Run all scenario files for one model, merge results, return summary."""
    all_results = []
    total = passed = 0

    for sf in scenario_files:
        print(f"    Scenarios: {sf.name}", flush=True)
        out = output_path.with_suffix(f".{sf.stem}.json")
        cmd = [
            sys.executable, str(RUNNER),
            "--scenarios", str(sf),
            "--fixtures", str(FIXTURES_DIR),
            "--model", model_id,
            "--lm-url", lm_url,
            "--token", token,
            "--output", str(out),
            "--eval-mode", eval_mode,
        ]
        if explain_failures:
            cmd.append("--explain-failures")
        elif explain_all:
            cmd.extend(["--explain-all", "--explain-scope", explain_scope])

        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode != 0:
            print(f"    WARNING: runner exited {result.returncode} for {sf.name}")

        if out.exists():
            data = json.loads(out.read_text())
            all_results.extend(data.get("results", []))
            s = data.get("summary", {})
            total += s.get("total", 0)
            passed += s.get("passed", 0)

    # Calculate timing statistics
    time_stats = calculate_per_tool_time(all_results)

    # Write merged results
    merged = {
        "model": model_id,
        "timestamp": datetime.now().isoformat(),
        "scenario_files": [str(f) for f in scenario_files],
        "results": all_results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "time_stats": time_stats,
        },
    }
    output_path.write_text(json.dumps(merged, indent=2))
    return merged["summary"]


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary_table(summaries: list[dict]) -> None:
    """Print a comparison table across all models."""
    if not summaries:
        return

    print()
    print("=" * 75)
    print("BENCHMARK SUMMARY")
    print("=" * 75)
    header = f"{'Model':<35} {'Pass':>6} {'Total':>6} {'Rate':>7} {'Time/Tool':>10}"
    print(header)
    print("-" * 75)

    best_rate = max(s["pass_rate"] for s in summaries)
    for s in summaries:
        marker = " *" if s["pass_rate"] == best_rate else "  "
        rate_pct = f"{s['pass_rate']*100:.1f}%"
        time_stats = s.get("time_stats", {})
        avg_time = time_stats.get("avg_time_per_tool", 0.0)
        time_str = f"{avg_time:.2f}s" if time_stats.get("test_count", 0) > 0 else "-"
        print(f"{s['model']:<35} {s['passed']:>6} {s['total']:>6} {rate_pct:>7} {time_str:>10}{marker}")

    print("=" * 75)
    print("* best result")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MCP benchmark across multiple LLM models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "models",
        nargs="+",
        help="Model IDs (or substrings) to benchmark",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        metavar="FILE",
        help=(
            "Scenario YAML filenames (relative to scenarios/). "
            "Default: all *.yaml except advanced_*.yaml. "
            "Use --all-scenarios to include advanced_*.yaml too. "
            "NOTE: place model names BEFORE --scenarios to avoid argparse ambiguity."
        ),
    )
    parser.add_argument(
        "--lm-url",
        default=LM_URL,
        help=f"LM Studio base URL (default: {LM_URL})",
    )
    parser.add_argument(
        "--token",
        default="sk-lm-local",
        help="LM Studio auth token",
    )
    parser.add_argument(
        "--no-load",
        action="store_true",
        help="Skip lms load/unload (model already loaded)",
    )
    parser.add_argument(
        "--no-unload",
        action="store_true",
        help="Keep model loaded after run",
    )
    explain_group = parser.add_mutually_exclusive_group()
    explain_group.add_argument(
        "--explain-failures",
        action="store_true",
        help="Ask LLM to explain first failure per scenario",
    )
    explain_group.add_argument(
        "--explain-all",
        action="store_true",
        help="Collect post-hoc explanations after each scenario run",
    )
    parser.add_argument(
        "--explain-scope",
        choices=["mismatches", "all_failed", "all"],
        default="mismatches",
        help="Which calls to explain in post-hoc mode. Passed through to runner.py.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: optimization_runs/bench_<timestamp>)",
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Include advanced_*.yaml scenarios (excluded by default)",
    )
    parser.add_argument(
        "--eval-mode",
        choices=["strict", "relaxed"],
        default="strict",
        help=(
            "Step evaluation mode passed to runner.py. "
            "'relaxed' skips discovery tool calls before expected tool."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve scenario files
    if args.scenarios:
        scenario_files = [SCENARIOS_DIR / f for f in args.scenarios]
        missing = [f for f in scenario_files if not f.exists()]
        if missing:
            print(f"ERROR: scenario files not found: {missing}")
            sys.exit(1)
    else:
        scenario_files = sorted(SCENARIOS_DIR.glob("*.yaml"))
        if not args.all_scenarios:
            before = len(scenario_files)
            scenario_files = [
                f for f in scenario_files if not f.name.startswith("advanced_")
            ]
            skipped = before - len(scenario_files)
            if skipped:
                print(f"Skipping {skipped} advanced scenario file(s) "
                      f"(use --all-scenarios to include)")

    if not scenario_files:
        print(f"ERROR: no scenario files found in {SCENARIOS_DIR}")
        sys.exit(1)

    # Output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else RUNS_DIR / f"bench_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Benchmark run: {timestamp}")
    print(f"Models: {args.models}")
    print(f"Scenarios: {[f.name for f in scenario_files]}")
    print(f"Output: {output_dir}")
    print()

    summaries = []
    start_total = time.time()

    # Clear VRAM before starting: unload any previously loaded models
    if not args.no_load:
        print("Clearing VRAM: unloading all models before benchmark...")
        unload_all_models()
        time.sleep(2)
        print()

    for model_arg in args.models:
        print(f"{'='*50}")
        print(f"Model: {model_arg}")
        start = time.time()

        # Load model
        if not args.no_load:
            ok = load_model(model_arg)
            if not ok:
                print(f"  SKIP: could not load {model_arg}")
                continue
        else:
            print(f"  Skipping load (--no-load)")

        # Resolve actual model ID from lms ps
        actual_id = resolve_model_id(model_arg)
        output_path = output_dir / f"{safe_filename(model_arg)}.json"

        print(f"  Running {len(scenario_files)} scenario file(s)...")
        summary = run_scenarios(
            model_id=actual_id,
            scenario_files=scenario_files,
            output_path=output_path,
            lm_url=args.lm_url,
            explain_failures=args.explain_failures,
            explain_all=args.explain_all,
            explain_scope=args.explain_scope,
            token=args.token,
            eval_mode=args.eval_mode,
        )
        summary["model"] = model_arg  # use original arg for display

        elapsed = time.time() - start
        rate_pct = f"{summary['pass_rate']*100:.1f}%"
        time_stats = summary.get("time_stats", {})
        if time_stats.get("test_count", 0) > 0:
            avg_time = time_stats.get("avg_time_per_tool", 0.0)
            total_calls = time_stats.get("total_tool_calls", 0)
            total_wall = time_stats.get("total_wall_time", 0.0)
            timing_str = f" | {avg_time:.2f}s per tool ({total_calls} calls, {total_wall:.1f}s total)"
        else:
            timing_str = ""
        print(
            f"  Result: {summary['passed']}/{summary['total']} ({rate_pct}) "
            f"in {elapsed:.0f}s{timing_str}"
        )
        summaries.append(summary)

        # Unload model
        if not args.no_unload and not args.no_load:
            print(f"  Unloading {model_arg}...")
            unload_all_models()
            time.sleep(2)  # brief pause before next model

    # Write cross-model summary
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2))

    total_elapsed = time.time() - start_total
    print_summary_table(summaries)
    print(f"\nTotal time: {total_elapsed/60:.1f} min")
    print(f"Results saved to: {output_dir}")


if __name__ == "__main__":
    main()
