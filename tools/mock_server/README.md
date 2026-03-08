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
      - tool: find_usage_sites
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
  "expected_tool": "find_usage_sites",
  "actual_tool": "get_functions_called_by",
  "tool_match": false,
  "llm_explanation": "I chose get_functions_called_by because the description says 'find all functions called BY' which matched the query pattern..."
}
```

## Automated Optimization Loop

`optimize.py` automates the test→analyze→fix→retest workflow:

```bash
# Full automated loop (requires ANTHROPIC_API_KEY)
python tools/mock_server/optimize.py --model qwen3-4b

# From existing test results
python tools/mock_server/optimize.py --from-results mock_test_results.json

# Manual mode: prints Claude prompt, you apply suggestions yourself
python tools/mock_server/optimize.py --from-results results.json --manual

# Apply saved suggestions
python tools/mock_server/optimize.py --apply-suggestions suggestions.json

# Multiple iterations
python tools/mock_server/optimize.py --max-iterations 3 --model qwen3-4b

# Dry run: show what would change
python tools/mock_server/optimize.py --from-results results.json --dry-run
```

### How it works

1. **Run tests** — executes all scenarios via `runner.py` with `--explain-failures`
2. **Analyze failures** — extracts patterns (wrong tool, wrong params, missing calls)
3. **Generate suggestions** — sends failure patterns + current tool definitions to
   Claude API, which returns precise find-and-replace edits for `consolidated_tools.py`
4. **Apply fixes** — applies suggestions with backup (`.py.bak`)
5. **Re-run tests** — verifies improvement, auto-reverts if regressions detected
6. **Report** — shows before/after comparison with fixed/broken scenarios

Results are saved per-iteration in `optimization_runs/iteration_NN/`.

### Manual workflow (no API key needed)

```bash
# Step 1: Run tests
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/basic.yaml \
  --explain-failures --output results.json

# Step 2: Generate prompt for manual Claude analysis
python tools/mock_server/optimize.py --from-results results.json --manual

# Step 3: Copy prompt → paste into Claude → save response as suggestions.json

# Step 4: Apply suggestions
python tools/mock_server/optimize.py --apply-suggestions suggestions.json

# Step 5: Re-run tests to verify
python tools/mock_server/runner.py --scenarios tools/mock_server/scenarios/basic.yaml
```
