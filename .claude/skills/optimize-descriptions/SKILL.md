---
name: optimize-descriptions
description: Run tool description optimization loop — test LLM tool selection against mock scenarios, analyze failures, improve descriptions, verify improvement
---

# Tool Description Optimization Skill

Optimizes MCP tool descriptions in `mcp_server/consolidated_tools.py` by testing
how well a local LLM (via LM Studio) selects tools based on natural language queries.

## Usage

```
/optimize-descriptions                     # Run full optimization loop
/optimize-descriptions run                 # Run tests only, show compact report
/optimize-descriptions run model=qwen3-4b  # Specify LM Studio model
/optimize-descriptions analyze <file>      # Analyze existing results file
/optimize-descriptions compare <f1> <f2>   # Compare before/after results
/optimize-descriptions restore             # Restore consolidated_tools.py from backup
```

## Instructions for Claude Code

When this skill is invoked, follow the workflow below. The key script is
`tools/mock_server/optimize.py`.

### Prerequisites Check

Before starting, verify:
1. LM Studio is running at localhost:1234 (or custom URL)
2. A model is loaded: `curl -s http://localhost:1234/v1/models | python3 -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data']]"`

If LM Studio is not accessible, tell the user and stop.

### Command: `/optimize-descriptions` (Full Loop)

#### Phase 1: Run baseline tests

```bash
python tools/mock_server/optimize.py run [--model MODEL] --explain-failures
```

Always use `--explain-failures` in the full loop — LLM explanations are essential
for root cause analysis.

Save the results file path — this is the "before" baseline.

#### Phase 2: Root cause analysis

Read the compact report and the full results JSON. For each failure:
1. Note the failure type (wrong_tool, wrong_param, missing_call)
2. Read the LLM explanation carefully

**Group failures by root cause, not by symptom.** Two failures might show
different wrong tools but share the same root cause (e.g., ambiguous wording
between two tool descriptions). Look for:
- Multiple failures mentioning the same confusing phrase or concept
- Failures where the LLM explanation points to the same ambiguity
- Failures on the same expected tool that share a pattern in LLM reasoning

Document the identified root causes as a list, e.g.:
```
Root cause 1: LLM confuses search_codebase with get_class_info when query
              says "find" + specific class name (affects A-02, J-01)
Root cause 2: LLM uses get_functions_called_by instead of find_usage_sites
              when query mentions "used by" (affects I-incoming/1, I-incoming/3)
```

#### Phase 3: Expand test scenarios (probe generation)

For EACH root cause identified in Phase 2:

1. **Generate 3-5 diverse probe queries** that should trigger the same root cause
   but differ maximally from the original failing query in:
   - Vocabulary (synonyms, different phrasing)
   - Structure (question vs imperative, short vs long)
   - Specificity (concrete symbol names vs abstract descriptions)
   - Domain framing (developer jargon vs plain language)

2. **Write probe scenarios** as a YAML file in `tools/mock_server/scenarios/`
   named `probes_<timestamp>.yaml`. Use the same format as existing scenarios.
   Give them IDs like `P1-01`, `P1-02` (P for probe, 1 for root cause number).

Example probe set for root cause "confuses search_codebase with get_class_info":
```yaml
scenarios:
  - id: "P1-01"
    category: "probe"
    query: "Look up class EventHandler in the codebase"
    expected_steps:
      - tool: search_codebase
        params:
          pattern: { type: contains, value: "EventHandler" }
  - id: "P1-02"
    category: "probe"
    query: "I need to locate the DataProcessor class"
    expected_steps:
      - tool: search_codebase
        params:
          pattern: { type: contains, value: "DataProcessor" }
  - id: "P1-03"
    category: "probe"
    query: "Where is the NetworkClient class defined?"
    expected_steps:
      - tool: search_codebase
        params:
          pattern: { type: contains, value: "NetworkClient" }
```

#### Phase 4: Validate probes on unmodified descriptions

Run ONLY the probe scenarios on the current (unmodified) descriptions:

```bash
python tools/mock_server/optimize.py run [--model MODEL] --explain-failures \
    --scenarios-files tools/mock_server/scenarios/probes_<timestamp>.yaml
```

Evaluate results:
- **Probes that PASS**: These do NOT reproduce the root cause. Remove them from
  the probe file — they would give false confidence that a fix works.
- **Probes that FAIL with the same root cause**: Keep these. They confirm the
  problem is systematic, not query-specific.
- **Probes that FAIL with a DIFFERENT root cause**: Keep these but note the
  additional root cause. Add it to the root cause list from Phase 2.

If NO probes fail for a given root cause, the original failure may be
query-specific or stochastic. In that case, still attempt a fix but be cautious
about over-fitting the description to one specific phrasing.

#### Phase 5: Design minimal fix

For each root cause, design the smallest description change that addresses it.
Follow these principles strictly:

1. **Reformulate before adding.** Can you fix the issue by rewording existing
   text rather than appending new text? Shorter descriptions are better for
   small LLMs.

2. **Target the root cause, not the symptom.** If the LLM confuses tool A
   with tool B, consider changes to BOTH descriptions — sometimes adding a
   "Do NOT use for X" hint to one tool is better than expanding the other.

3. **Generalize the fix.** If the root cause is "LLM interprets 'find' as
   meaning get_class_info", don't add "when user says 'find', use
   search_codebase" — that's overfitting to vocabulary. Instead, clarify the
   conceptual boundary: "Use this tool when you don't yet know if the symbol
   exists" vs "Use this tool when you already have a specific class name."

4. **Batch related root causes.** If two root causes stem from the same
   description being unclear, fix them together with one edit rather than
   two separate patches.

5. **Estimate token impact.** Count the approximate token delta of your change.
   If a fix adds more than ~20 tokens, reconsider whether a reformulation
   could achieve the same with fewer tokens.

#### Phase 6: Apply fix and verify

1. Edit `mcp_server/consolidated_tools.py` with the designed changes.
2. Run ALL tests (original + probes):
   ```bash
   python tools/mock_server/optimize.py run [--model MODEL] --explain-failures
   ```
3. Compare with baseline:
   ```bash
   python tools/mock_server/optimize.py compare <before.json> <after.json>
   ```
4. Check for regressions (previously passing tests now failing).
   - If regressions exist, the fix is too aggressive — refine it.
   - If the fix resolves the original failures AND the probe scenarios
     without regressions, the fix is good.

#### Phase 7: Report to user (DO NOT commit)

Show a concise summary:
- Root causes identified and which scenarios they affected
- Before/after pass rates
- Exact description changes made (as diffs)
- Any regressions
- Probe scenarios that were added to the test suite

**Do NOT commit changes.** The user will review the modifications to both
`consolidated_tools.py` and the new probe scenario files, and decide whether
to apply them.

### Command: `/optimize-descriptions run`

Run tests only, without the full optimization loop:
```bash
python tools/mock_server/optimize.py run [--model MODEL] [--explain-failures]
```
Read the output and present the compact report to the user.

### Command: `/optimize-descriptions analyze <file>`

```bash
python tools/mock_server/optimize.py analyze <file>
```
Read the output and provide analysis to the user.

### Command: `/optimize-descriptions compare <before> <after>`

```bash
python tools/mock_server/optimize.py compare <before> <after>
```
Show the comparison to the user.

### Command: `/optimize-descriptions restore`

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
- Probe scenario files (`probes_*.yaml`) should be kept if they add coverage value, or removed if they only test edge cases already covered
