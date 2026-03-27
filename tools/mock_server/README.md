# Mock MCP Server for Tool Description Optimization

Lightweight mock MCP server and LLM test runner for rapid iteration on
tool descriptions, response formats, and next-step hints.

## Components

| File | Purpose |
|------|---------|
| `server.py` | Standalone mock MCP server (SSE or stdio) |
| `runner.py` | LLM test runner with tool-call mediation loop |
| `fixtures.py` | YAML fixture loader + argument matcher |
| `fixtures/responses.yaml` | Canned tool responses |
| `fixtures/dom_responses.yaml` | Domain-specific response fixtures |
| `scenarios/basic.yaml` | Basic single-step test scenarios |
| `scenarios/multi_step.yaml` | Multi-step chained scenarios |
| `scenarios/edge_cases.yaml` | Edge cases (empty results, direction confusion) |
| `scenarios/advanced_semantic.yaml` | Advanced semantic search scenarios |
| `scenarios/probes_rootcauses.yaml` | Root cause analysis probe scenarios |
| `scenarios/probes_usage_ambiguity.yaml` | Usage ambiguity probe scenarios |
| `scenarios/real_workflows.yaml` | Real-world workflow scenarios |
| `optimize.py` | Automated test→analyze→fix→retest loop |
| `bench_claude.py` | Benchmark Claude Code tool-calling behavior |
| `bench_models.py` | Benchmark multiple model performance |
| `diagnose_looping.py` | Diagnose infinite loop issues in LLM tool calls |

## Quick Start

```bash
# From project root, activate venv
source mcp_env/bin/activate

# List available scenarios
python tools/mock_server/runner.py --dry-run

# Run basic scenarios against loaded LM Studio model
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/basic.yaml

# Run with specific model
python tools/mock_server/runner.py --model qwen3-4b --scenarios tools/mock_server/scenarios/basic.yaml

# Run all scenario files
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/basic.yaml
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/multi_step.yaml
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/edge_cases.yaml
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/advanced_semantic.yaml
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/real_workflows.yaml

# Run specific scenario by ID
python tools/mock_server/runner.py --scenario-id A-01 --scenario-id C-02

# List available models
python tools/mock_server/runner.py --list-models

# Run with custom fixtures directory
python tools/mock_server/runner.py --fixtures tools/mock_server/fixtures/responses.yaml

# Use relaxed evaluation mode (skip discovery tool calls)
python tools/mock_server/runner.py --scenarios basic.yaml --eval-mode relaxed

# Enable intent validation (ask for clarification on ambiguous requests)
python tools/mock_server/runner.py --scenarios basic.yaml --validate-intent

# Custom LM Studio URL and token
python tools/mock_server/runner.py --scenarios basic.yaml --lm-url http://localhost:1234 --token mytoken

# Increase timeout for slow models
python tools/mock_server/runner.py --scenarios basic.yaml --timeout 600
```

## Mock MCP Server (Standalone)

For manual testing or LM Studio native MCP integration:

```bash
# SSE transport
python tools/mock_server/server.py --port 9000

# Stdio transport
python tools/mock_server/server.py

# Custom fixtures
python tools/mock_server/server.py --port 9000 --fixtures my_fixtures.yaml
```

## Writing Scenarios

Scenarios are YAML files with test cases. Each scenario defines:
- User query (natural language)
- Expected tool call sequence (tool name + parameter assertions)

```yaml
scenarios:
  - id: "S-01"
    category: "search"
    query: "Find all classes with Manager in their name"
    expected_steps:
      - tool: find_symbols_by_pattern
        params:
          pattern:
            type: contains       # substring match
            value: "Manager"
          target_type:
            type: exact           # exact match
            value: "classes_and_structs_only"
```

### Multi-query scenarios (robustness testing)

Use `queries` (plural) instead of `query` to test multiple phrasings
of the same intent against the same expected tool calls:

```yaml
scenarios:
  - id: "I-incoming"
    category: "direction"
    queries:
      - "What calls processEvent?"
      - "Find all callers of processEvent"
      - "Where is processEvent used?"
      - "Who invokes processEvent?"
      - "Show me the usage sites of processEvent"
    expected_steps:
      - tool: find_callers
        params:
          function_name:
            type: contains
            value: "processEvent"
```

Each query variant runs as a separate test (`I-incoming/1`, `I-incoming/2`, etc.)
with per-variant pass/fail and a per-scenario robustness summary:

```
Per-scenario robustness:
  I-outgoing: 4/5 (80%) [++++-]
    FAIL: Show me what processEvent invokes
  I-incoming: 5/5 (100%) [+++++]
```

### Parameter assertion types

| Type | Description |
|------|-------------|
| `exact` | Exact match (case-insensitive) |
| `contains` | Substring match |
| `regex` | Regex match |
| `any` | Any non-null value |
| `absent` | Parameter must not be present |
| `one_of` | Must be one of listed values |

## Writing Fixtures

Fixtures define canned responses for tool calls:

```yaml
responses:
  - tool: find_symbols_by_pattern
    match:
      pattern:
        contains: "Manager"        # match when pattern contains "Manager"
      target_type: "classes_and_structs_only"  # exact match
    response:
      results:
        - qualified_name: "app::DataManager"
          kind: "class"
          # ...

  - tool: find_symbols_by_pattern
    default: true                  # fallback when no other match
    response:
      results: []
```

## Output Format

Results are saved as JSON with per-step evaluation:

```json
{
  "run_id": "2026-03-08T14:30:00",
  "model": "qwen3-4b",
  "results": [
    {
      "scenario_id": "A-01",
      "overall_pass": true,
      "steps": [
        {
          "step": 1,
          "expected_tool": "find_symbols_by_pattern",
          "actual_tool": "find_symbols_by_pattern",
          "tool_match": true,
          "param_assertions": { ... },
          "params_pass": true
        }
      ]
    }
  ],
  "summary": {
    "total": 9,
    "passed": 8,
    "failed": 1,
    "pass_rate": 0.889
  }
}
```

## Failure Explanation Mode

When `--explain-failures` is enabled, the runner stops at the first mismatch
in each scenario and asks the LLM to explain its reasoning:

```bash
python tools/mock_server/runner.py \
  --scenarios tools/mock_server/scenarios/basic.yaml \
  --explain-failures
```

The question is tailored to the failure type:

| Failure | Question asked |
|---------|---------------|
| No tool called | "Why did you not call any tool?" |
| Wrong tool | "Why did you choose X instead of Y?" |
| Missing parameter | "Why did you omit parameter Z?" |
| Wrong parameter value | "Why did you pass Z=actual instead of expected?" |
| Unexpected parameter | "Why did you include parameter Z?" |

The LLM's explanation is saved in the output JSON under
`steps[i].llm_explanation` for failed steps. This provides actionable
signal for improving tool descriptions.

Example output:
```json
{
  "step": 1,
  "expected_tool": "find_callers",
  "actual_tool": "get_functions_called_by",
  "tool_match": false,
  "llm_explanation": "I chose get_functions_called_by because the description says 'find all functions called BY' which matched the query pattern..."
}
```

## Post-Hoc Explanation Mode

When `--explain-all` is enabled, the runner completes the full scenario first,
evaluates the result, and only then requests explanations for selected tool
calls. This preserves the full call trace instead of aborting at the first
mismatch.

```bash
python tools/mock_server/runner.py \
  --scenarios tools/mock_server/scenarios/basic.yaml \
  --explain-all
```

Supported scopes:

- `--explain-scope=mismatches` (default): explain mismatching calls plus extra
  calls that did not align to any expected step. Missing expected steps with
  no tool call are also explained and stored on the failed step.
- `--explain-scope=all_failed`: explain every tool call in failed scenarios.
- `--explain-scope=all`: explain every tool call in every scenario, including
  passing runs.

Implementation detail: post-hoc explanations are processed from the last
interesting tool call back to the first one. This maximizes prompt-prefix cache
reuse in LM Studio and similar local servers.

Each annotated tool call gets an `explanation` object in `all_tool_calls[]`:

```json
{
  "tool": "find_symbols_by_pattern",
  "arguments": {"pattern": "Widget"},
  "message_index": 4,
  "explanation": {
    "prompt": "You called 'find_symbols_by_pattern' but the expected tool was 'find_callers'...",
    "response": "I chose the broader search tool first because the query did not mention a concrete function name."
  }
}
```

When the explained call corresponds to a failed expected step, the step also
receives `steps[i].llm_explanation` for compatibility with existing analysis
tools.

If the failure is a missing tool call, there is no `all_tool_calls[]` entry to
annotate, so the explanation is stored only in `steps[i].llm_explanation`.

The default runner system prompt also tells the model to use native
tool-calling only. It explicitly forbids markdown or pseudo-code tool plans
such as fenced `tool_code` blocks.

## Optimization Loop (Claude Code-driven)

`optimize.py` is a helper that runs tests and produces compact failure reports.
The analysis and fix steps are done by **Claude Code** (switch to Haiku for
cost efficiency via `/model`). No external API keys needed.

### Commands

```bash
# Run all scenarios, produce compact failure report
python tools/mock_server/optimize.py run --model qwen3-4b

# Run with LLM self-explanations (more detail, slower)
python tools/mock_server/optimize.py run --model qwen3-4b --explain-failures

# Analyze existing results file
python tools/mock_server/optimize.py analyze results.json

# Compare before/after results
python tools/mock_server/optimize.py compare before.json after.json

# Apply suggestions from JSON file
python tools/mock_server/optimize.py apply suggestions.json [--dry-run]

# Restore consolidated_tools.py from backup
python tools/mock_server/optimize.py restore
```

### Workflow

1. Claude Code runs `optimize.py run --model qwen3-4b` → reads compact report
2. Claude Code analyzes failures and directly edits `consolidated_tools.py`
3. Claude Code runs `optimize.py run --model qwen3-4b` → verifies improvement
4. Claude Code runs `optimize.py compare before.json after.json` → measures delta
5. Repeat until satisfied

### Token efficiency

The compact report is designed to be ~500-1000 tokens, minimizing Claude Code
context usage. Switch to Haiku (`/model`) for routine iteration cycles.

## Multi-Model Benchmark (bench_models.py)

`bench_models.py` runs MCP tool description tests across multiple LLM models and generates comparison reports. Designed for overnight unattended runs to compare model performance.

### Purpose

- Compare tool-calling accuracy across different models (e.g., qwen3-4b vs qwen3-8b vs qwen3-14b)
- Identify which models have better tool description understanding
- Generate standardized reports for model selection decisions

### Basic Usage

```bash
# Benchmark single model
python tools/mock_server/bench_models.py qwen3-4b

# Benchmark multiple models
python tools/mock_server/bench_models.py qwen3-4b qwen3-8b qwen3-14b

# Run specific scenario files
python tools/mock_server/bench_models.py --scenarios basic.yaml multi_step.yaml qwen3-4b

# Include advanced scenarios
python tools/mock_server/bench_models.py --all-scenarios qwen3-4b

# Keep model loaded after run (faster for repeated tests)
python tools/mock_server/bench_models.py --no-unload qwen3-4b

# Skip loading (model already in LM Studio)
python tools/mock_server/bench_models.py --no-load qwen3-4b
```

### Explanation Options

```bash
# Ask LLM to explain first failure per scenario
python tools/mock_server/bench_models.py --explain-failures qwen3-4b

# Collect post-hoc explanations after each run
python tools/mock_server/bench_models.py --explain-all qwen3-4b
```

### Output & Reports

Results are saved to `tools/mock_server/optimization_runs/bench_<timestamp>/`:

```
optimization_runs/
└── bench_2026-03-27_120000/
    ├── summary.json              # Cross-model comparison
    ├── qwen3-4b.json             # Per-model results
    ├── qwen3-8b.json
    └── qwen3-14b.json
```

**summary.json** contains a comparison table:

```
============================================================
BENCHMARK SUMMARY
============================================================
Model                                  Passed  Total    Rate
------------------------------------------------------------
qwen3-14b                             45      50      90.0% *
qwen3-8b                              42      50      84.0%
qwen3-4b                              38      50      76.0%
============================================================
* best result
```

Each per-model JSON file contains detailed results from `runner.py` including pass/fail breakdown per scenario and any explanations if requested.

## Claude Model Benchmark (bench_claude.py)

`bench_claude.py` benchmarks Claude Code's tool selection by presenting tool schemas as text and asking the model to choose the appropriate tool. Uses the `claude -p` (pipe mode) for direct model interaction without actual tool execution.

### Purpose

- Evaluate how well Claude models understand MCP tool descriptions
- Test tool selection without requiring LM Studio or local LLM servers
- Benchmark different Claude models (haiku, sonnet, opus) on tool-calling tasks
- Identify ambiguities in tool descriptions that cause wrong tool selection

### Basic Usage

```bash
# Run all default scenarios (probes_rootcauses.yaml)
python tools/mock_server/bench_claude.py

# Run specific scenario by ID
python tools/mock_server/bench_claude.py --scenario PROBE-RC3-01

# Use specific scenario file
python tools/mock_server/bench_claude.py --scenarios-file scenarios/probes_rootcauses.yaml

# Run all scenario files in scenarios/
python tools/mock_server/bench_claude.py --all

# Specify Claude model
python tools/mock_server/bench_claude.py --model claude-sonnet-4-20250514

# Save results to file
python tools/mock_server/bench_claude.py --output results.json
```

### Available Models

Default model is `claude-haiku-4-5-20251001`. Other options include:
- `claude-sonnet-4-20250514` - Faster, good for iteration
- `claude-opus-4-20250514` - Most capable, for final validation

### How It Works

1. Loads tool schemas from `consolidated_tools.py`
2. Builds a prompt with tool names, descriptions, and parameters
3. Presents each scenario query and asks Claude to select a tool
4. Parses the JSON response and compares with expected tool
5. Reports pass/fail for each scenario

The system prompt instructs Claude to:
- Not use `set_project` or `sync_project` (project already indexed)
- Respond with only JSON (no markdown, no explanation)
- Use `{"tool": null}` if no tool is needed

### Output

Console output shows per-scenario results:

```
=== scenarios/probes_rootcauses.yaml (10 scenarios) ===
Running PROBE-RC3-01... ✓ PASS
Running PROBE-RC3-02... ✗ FAIL
   Query:  What function calls the deprecated setupAPI?
   Tool:  expected=find_callers  actual=find_symbols_by_pattern
  → 7/10 (70%)
```

JSON output (when `--output` specified) includes:
- Per-scenario pass/fail status
- Expected vs actual tool comparison
- Query text and any error messages
