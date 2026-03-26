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
| `scenarios/basic.yaml` | 1-step test scenarios |
| `scenarios/multi_step.yaml` | 2-3 step chained scenarios |
| `scenarios/edge_cases.yaml` | Edge cases (empty results, direction confusion) |
| `optimize.py` | Automated test→analyze→fix→retest loop |

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

# Run specific scenario by ID
python tools/mock_server/runner.py --scenario-id A-01 --scenario-id C-02

# List available models
python tools/mock_server/runner.py --list-models
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
      - tool: search_codebase
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
  - tool: search_codebase
    match:
      pattern:
        contains: "Manager"        # match when pattern contains "Manager"
      target_type: "classes_and_structs_only"  # exact match
    response:
      results:
        - qualified_name: "app::DataManager"
          kind: "class"
          # ...

  - tool: search_codebase
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
          "expected_tool": "search_codebase",
          "actual_tool": "search_codebase",
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
