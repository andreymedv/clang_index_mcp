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

## Iteration Workflow

1. Run scenarios → review results JSON
2. Identify failing scenarios (wrong tool or wrong params)
3. Adjust tool descriptions in `consolidated_tools.py`
4. Re-run → compare pass rates
5. When satisfied, apply changes to real MCP server and validate with real project
