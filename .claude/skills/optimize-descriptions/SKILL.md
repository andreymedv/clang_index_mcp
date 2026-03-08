---
name: optimize-descriptions
description: Run tool description optimization loop — test LLM tool selection against mock scenarios, analyze failures, improve descriptions, verify improvement
---

# Tool Description Optimization Skill

Optimizes MCP tool descriptions in `mcp_server/consolidated_tools.py` by testing
how well a local LLM (via LM Studio) selects tools based on natural language queries.

## Usage

```
/optimize-descriptions                     # Run full loop: test, analyze, fix, verify
/optimize-descriptions run                 # Run tests only, show compact report
/optimize-descriptions run model=qwen3-4b  # Specify LM Studio model
/optimize-descriptions analyze <file>      # Analyze existing results file
/optimize-descriptions compare <f1> <f2>   # Compare before/after results
/optimize-descriptions restore             # Restore consolidated_tools.py from backup
```

## Instructions for Claude Code

When this skill is invoked, follow the workflow below. Use Haiku model if
available (cost-efficient for iteration). The key script is
`tools/mock_server/optimize.py`.

### Prerequisites Check

Before starting, verify:
1. LM Studio is running at localhost:1234 (or custom URL)
2. A model is loaded: `curl -s http://localhost:1234/v1/models | python3 -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data']]"`

If LM Studio is not accessible, tell the user and stop.

### Command: `/optimize-descriptions` or `/optimize-descriptions run`

**Step 1: Run tests**
```bash
python tools/mock_server/optimize.py run [--model MODEL] [--explain-failures]
```
- Use `--explain-failures` if the user wants detailed LLM reasoning on failures
- Use `--model` if the user specified one, otherwise the script picks the first loaded model
- The script runs ALL scenario files in `tools/mock_server/scenarios/` and prints a compact report

**Step 2: Read and analyze the report**

The compact report shows:
- Pass rate (e.g., "22/24 (91.7%)")
- Failures grouped by expected tool
- For each failure: scenario ID, failure type, query, LLM explanation

Analyze the failures and identify patterns:
- **wrong_tool**: LLM chose the wrong tool. Check if the tool descriptions are ambiguous.
- **wrong_param**: Right tool, wrong parameters. Check parameter descriptions.
- **missing_call**: LLM didn't call any tool. The query may not clearly suggest a tool action.

**Step 3: Improve descriptions**

Edit `mcp_server/consolidated_tools.py` directly. Focus on:
1. Clarifying when to use tool A vs tool B (for wrong_tool failures)
2. Clarifying parameter semantics (for wrong_param failures)
3. Adding disambiguation hints where the LLM got confused
4. Keeping descriptions concise — smaller LLMs have limited context

Rules:
- Only modify description strings, never change tool names or parameter schemas
- Keep descriptions concise — smaller LLMs need clear, short text
- The LLM explanation (if available) tells you exactly what confused it

**Step 4: Verify improvement**

Re-run the same tests:
```bash
python tools/mock_server/optimize.py run [--model MODEL]
```

Compare pass rates. If regressions appear (previously passing tests now fail),
reconsider the changes.

Optionally compare results files:
```bash
python tools/mock_server/optimize.py compare <before.json> <after.json>
```

**Step 5: Report to user**

Show a concise summary:
- Before/after pass rates
- Which scenarios were fixed
- Any regressions
- What description changes were made and why

### Command: `/optimize-descriptions analyze <file>`

Load and analyze an existing results JSON file:
```bash
python tools/mock_server/optimize.py analyze <file>
```
Read the output and provide analysis to the user.

### Command: `/optimize-descriptions compare <before> <after>`

Compare two results files:
```bash
python tools/mock_server/optimize.py compare <before> <after>
```
Show the comparison to the user.

### Command: `/optimize-descriptions restore`

Restore `consolidated_tools.py` from the `.py.bak` backup:
```bash
python tools/mock_server/optimize.py restore
```

### Important Notes

- The test results directory is `tools/mock_server/optimization_runs/` (gitignored)
- Backup of consolidated_tools.py is saved as `.py.bak` before changes
- Run `make check` after editing consolidated_tools.py to ensure no formatting/lint issues
- All scenario files are in `tools/mock_server/scenarios/*.yaml`
- Fixture responses are in `tools/mock_server/fixtures/responses.yaml`
- The mock server uses tool schemas from `consolidated_tools.list_tools_b()` — changes to descriptions are reflected immediately on next test run
