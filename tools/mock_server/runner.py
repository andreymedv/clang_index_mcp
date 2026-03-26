#!/usr/bin/env python3
"""LLM test runner with tool-call mediation loop.

Loads test scenarios from YAML, runs each through an LLM via OpenAI-compat
API (LM Studio /v1/chat/completions), mediates the tool call loop using
canned fixture responses, and evaluates correctness.

Usage:
    python tools/mock_server/runner.py --scenarios scenarios/basic.yaml
    python tools/mock_server/runner.py --scenarios scenarios/basic.yaml --model qwen3-4b
    python tools/mock_server/runner.py --dry-run
"""

import argparse
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from mcp_server.consolidated_tools import list_tools_b  # noqa: E402
from tools.mock_server.fixtures import FixtureStore  # noqa: E402

DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_SCENARIOS = Path(__file__).parent / "scenarios" / "basic.yaml"

# Tools that models legitimately call as a "discovery" step before the
# actual expected tool.  In relaxed eval mode these calls are skipped
# (not counted as mismatches) when they appear before the expected tool.
DISCOVERY_TOOLS = frozenset({"find_symbols_by_pattern"})


# ---------------------------------------------------------------------------
# MCP Tool → OpenAI function-calling format conversion
# ---------------------------------------------------------------------------


def mcp_tools_to_openai(tools: list) -> List[Dict[str, Any]]:
    """Convert MCP Tool objects to OpenAI function-calling format."""
    result = []
    for tool in tools:
        # Skip set_project and sync_project — mock server is "always indexed"
        if tool.name in ("set_project", "sync_project"):
            continue
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
        )
    return result


# ---------------------------------------------------------------------------
# LM Studio OpenAI-compat client
# ---------------------------------------------------------------------------


@dataclass
class OpenAIClient:
    """Thin wrapper around OpenAI-compat /v1/chat/completions."""

    base_url: str = "http://localhost:1234"
    token: str = ""
    timeout: int = 300

    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """Send a chat completion request with tool definitions."""
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        body = json.dumps(payload).encode()
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]

    def list_models(self) -> List[str]:
        """GET /v1/models — return list of model IDs."""
        url = f"{self.base_url}/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("data", [])
        return [m["id"] for m in models if not m.get("id", "").startswith("text-embedding-")]


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------


def load_scenarios(path: str | Path) -> List[Dict[str, Any]]:
    """Load test scenarios from YAML.

    Supports both single-query and multi-query scenarios:
      - query: "single query"        → 1 scenario
      - queries: ["q1", "q2", "q3"]  → 3 scenarios (same expected_steps)

    Multi-query scenarios are expanded into separate entries with
    scenario_id suffixed by /1, /2, etc. and a query_variant index.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    raw = data.get("scenarios", [])
    expanded: List[Dict[str, Any]] = []

    for scenario in raw:
        queries = scenario.get("queries")
        if queries and isinstance(queries, list):
            for idx, q in enumerate(queries):
                variant = dict(scenario)
                variant["query"] = q
                variant["query_variant"] = idx + 1
                variant["query_variant_total"] = len(queries)
                variant["base_id"] = scenario["id"]
                variant["id"] = f"{scenario['id']}/{idx + 1}"
                variant.pop("queries", None)
                expanded.append(variant)
        else:
            scenario.setdefault("query_variant", 0)
            scenario.setdefault("query_variant_total", 1)
            scenario.setdefault("base_id", scenario["id"])
            expanded.append(scenario)

    return expanded


# ---------------------------------------------------------------------------
# Step evaluation
# ---------------------------------------------------------------------------


def evaluate_step(
    expected: Dict[str, Any],
    actual_tool: str,
    actual_args: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate a single step: compare actual tool call vs expected.

    Returns a step result dict with pass/fail details.
    """
    result: Dict[str, Any] = {
        "expected_tool": expected["tool"],
        "actual_tool": actual_tool,
        "tool_match": actual_tool == expected["tool"],
        "param_assertions": {},
        "params_pass": True,
    }
    if expected.get("optional"):
        result["optional"] = True

    expected_params = expected.get("params", {})
    for param_name, assertion in expected_params.items():
        actual_value = actual_args.get(param_name)
        param_result = _check_param(assertion, actual_value)
        result["param_assertions"][param_name] = param_result
        if not param_result["pass"]:
            result["params_pass"] = False

    return result


def _align_steps(
    expected_steps: List[Dict[str, Any]],
    recorded_calls: List[Dict[str, Any]],
    eval_mode: str = "strict",
) -> List[Dict[str, Any]]:
    """Align recorded tool calls against expected steps, respecting optional.

    Uses greedy matching: for each recorded call, try to match it against the
    current expected step. If the current step is optional and the call doesn't
    match it, skip the optional step and try the next expected step.

    Args:
        eval_mode: "strict" (default) — first call must match first expected
            step. "relaxed" — calls to DISCOVERY_TOOLS before the expected
            tool are silently skipped (not counted as mismatches).

    Returns a list of result dicts, one per expected step. Optional steps that
    were skipped get ``"skipped_optional": True``. In relaxed mode, skipped
    discovery calls are counted in ``"discovery_calls_skipped"``.
    """
    results: List[Dict[str, Any]] = []
    call_idx = 0
    discovery_skipped = 0

    for i, expected in enumerate(expected_steps):
        is_optional = expected.get("optional", False)

        # In relaxed mode, skip over discovery tool calls that don't match
        # the current expected step.
        if eval_mode == "relaxed":
            while (
                call_idx < len(recorded_calls)
                and recorded_calls[call_idx]["tool"] in DISCOVERY_TOOLS
                and recorded_calls[call_idx]["tool"] != expected["tool"]
            ):
                discovery_skipped += 1
                call_idx += 1

        if call_idx < len(recorded_calls):
            call = recorded_calls[call_idx]
            step_eval = evaluate_step(expected, call["tool"], call["arguments"])
            step_eval["step"] = i + 1
            step_eval["call_index"] = call_idx

            if step_eval["tool_match"]:
                # Matches — consume this call
                call_idx += 1
                results.append(step_eval)
            elif is_optional:
                # Optional step not matched — skip it (don't consume call)
                results.append({
                    "step": i + 1,
                    "expected_tool": expected["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "optional": True,
                    "skipped_optional": True,
                    "call_index": None,
                })
            else:
                # Required step, wrong tool — consume call, report mismatch
                call_idx += 1
                results.append(step_eval)
        else:
            # No more recorded calls
            if is_optional:
                results.append({
                    "step": i + 1,
                    "expected_tool": expected["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "optional": True,
                    "skipped_optional": True,
                    "call_index": None,
                })
            else:
                results.append({
                    "step": i + 1,
                    "expected_tool": expected["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "missing": True,
                    "call_index": None,
                })

    # Attach discovery skip count to first result for reporting
    if discovery_skipped and results:
        results[0]["discovery_calls_skipped"] = discovery_skipped

    return results


def _check_param(assertion: Dict[str, Any], actual: Any) -> Dict[str, Any]:
    """Check a single parameter assertion."""
    assert_type = assertion.get("type", "any")
    expected_val = assertion.get("value")

    if assert_type == "any":
        return {"expected": "any", "actual": actual, "pass": actual is not None}

    if assert_type == "absent":
        return {"expected": "absent", "actual": actual, "pass": actual is None}

    actual_str = str(actual) if actual is not None else ""

    if assert_type == "exact":
        match = actual_str.lower() == str(expected_val).lower()
        return {
            "expected": f"exact:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "contains":
        match = str(expected_val).lower() in actual_str.lower()
        return {
            "expected": f"contains:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "regex":
        match = bool(re.search(str(expected_val), actual_str, re.IGNORECASE))
        return {
            "expected": f"regex:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    if assert_type == "one_of":
        values = [str(v).lower() for v in expected_val]
        match = actual_str.lower() in values
        return {
            "expected": f"one_of:{expected_val}",
            "actual": actual,
            "pass": match,
        }

    return {"expected": f"unknown:{assert_type}", "actual": actual, "pass": False}


# ---------------------------------------------------------------------------
# Failure explanation
# ---------------------------------------------------------------------------


def _build_explanation_prompt(
    step_eval: Dict[str, Any],
    recorded_call: Optional[Dict[str, Any]],
) -> str:
    """Build a targeted question asking the LLM to explain its tool choice.

    Generates different questions based on failure type:
    - No tool call at all
    - Wrong tool selected
    - Right tool, wrong parameters (per-param detail)
    """
    # Case 1: LLM didn't call any tool
    if recorded_call is None:
        expected = step_eval["expected_tool"]
        return (
            "Explain why you chose not to use any tool. "
            "If you could not find suitable tool, quote an EXACT part (or parts) "
            f"of '{expected}' tool description that made you decide against calling one."
            "Be concise. Do not output any fluff. "
        )

    actual_tool = recorded_call["tool"]
    actual_args = recorded_call["arguments"]

    if not step_eval:
        return (
            f"Quote an EXACT part (or parts) of {actual_tool} description "
            "and/or hints from previous tools' responses that made you decide to call "
            f"{actual_tool} with {actual_args} arguments. "
            "Be concise. Do not output any fluff."
        )

    expected_tool = step_eval["expected_tool"]

    # Case 2: Wrong tool
    if not step_eval["tool_match"]:
        return (
            f"Quote an EXACT part (or parts) of {actual_tool} and {expected_tool} "
            " descriptions and/or hints from previous tools' responses that made you decide "
            f"to chose {actual_tool} against {expected_tool}? "
            "Be concise. Do not output any fluff."
        )

    # Case 3: Right tool, wrong parameters
    issues: List[str] = []
    for param_name, assertion in step_eval.get("param_assertions", {}).items():
        if assertion["pass"]:
            continue

        expected_desc = assertion["expected"]
        actual_val = assertion["actual"]

        if expected_desc == "absent":
            # LLM passed a parameter that shouldn't be there
            issues.append(
                f"- Quote an EXACT part or parts of {actual_tool} description and/or hints "
                "from previous tools' responses that made you to pass parameter "
                f"{param_name} = {actual_val!r}? "
                "Be concise. Do not output any fluff."
            )
        elif actual_val is None:
            # LLM omitted a required parameter
            issues.append(
                f"- Quote an EXACT part or parts of {actual_tool} description and/or hints "
                f"from previous tools' responses that made you to omit parameter {param_name} "
                f"(expected: {expected_desc})? "
                "Be concise. Do not output any fluff."
            )
        else:
            # LLM passed wrong value
            issues.append(
                f"- Quote an EXACT part or parts of {actual_tool} description and/or hints "
                f"from previous tools' responses that made you to pass {actual_val!r} value "
                f"in '{param_name}' parameter (expected: {expected_desc})? "
                "Be concise. Do not output any fluff."
            )

    if not issues:
        return (
            f"- Quote an EXACT part or parts of {actual_tool} description and/or hints "
            f"from previous tools' responses that made you to call {actual_tool} with "
            f"THESE specific {actual_args} arguments? "
            "Be concise. Do not output any fluff."
        )

    issues_text = "\n".join(issues)
    return (
        f"- Quote an EXACT part or parts of {actual_tool} description and/or hints "
        "from previous tools' responses that made you to pass THESE specific "
        f"{actual_args} arguments to the {actual_tool}? "
        "Be concise. Do not output any fluff."
    )


def _request_explanation(
    client: OpenAIClient,
    model: str,
    messages: List[Dict[str, Any]],
    explanation_prompt: str,
    temperature: float = 0,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Ask the LLM to explain its tool choice. Returns explanation text."""
    explain_messages = list(messages)
    explain_messages.append({"role": "user", "content": explanation_prompt})

    try:
        response = client.chat_completion(
            model=model,
            messages=explain_messages,
            tools=[],  # No tools — force text response
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.get("choices", [{}])[0]
        return choice.get("message", {}).get("content", "")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _explanation_payload(
    prompt: str,
    response: Optional[str],
) -> Dict[str, Any]:
    """Build a serializable explanation payload."""
    return {
        "prompt": prompt,
        "response": response,
    }


def _is_step_mismatch(step_eval: Dict[str, Any]) -> bool:
    """Return True when a step evaluation represents a mismatch."""
    if step_eval.get("skipped_optional"):
        return False
    return not (step_eval.get("tool_match") and step_eval.get("params_pass"))


def _find_interesting_calls(
    step_results: List[Dict[str, Any]],
    recorded_calls: List[Dict[str, Any]],
    overall_pass: bool,
    explain_scope: str,
) -> List[Dict[str, Any]]:
    """Identify which calls or missing steps should receive explanations."""
    interesting: List[Dict[str, Any]] = []

    if explain_scope == "all":
        for call in recorded_calls:
            interesting.append({"call_record": call, "step_eval": None})
        return interesting

    if overall_pass:
        return interesting

    matched_call_indexes = {
        step_eval["call_index"]
        for step_eval in step_results
        if step_eval.get("call_index") is not None
    }

    if explain_scope == "all_failed":
        for call in recorded_calls:
            interesting.append({"call_record": call, "step_eval": None})
        return interesting

    step_calls = set()
    for step_eval in step_results:
        call_index = step_eval.get("call_index")
        if call_index is None:
            if _is_step_mismatch(step_eval):
                interesting.append({
                    "call_record": None,
                    "step_eval": step_eval,
                })
            continue
        step_calls.add(call_index)
        if _is_step_mismatch(step_eval):
            interesting.append({
                "call_record": recorded_calls[call_index],
                "step_eval": step_eval,
            })

    for call_index, call_record in enumerate(recorded_calls):
        if call_index in step_calls or call_index in matched_call_indexes:
            continue
        interesting.append({"call_record": call_record, "step_eval": None})

    return interesting


def _collect_posthoc_explanations(
    client: OpenAIClient,
    model: str,
    messages: List[Dict[str, Any]],
    step_results: List[Dict[str, Any]],
    recorded_calls: List[Dict[str, Any]],
    overall_pass: bool,
    explain_scope: str = "mismatches",
    temperature: float = 0,
    max_tokens: int = 2048,
) -> None:
    """Mutate step_results and recorded_calls in-place with explanations."""
    interesting = _find_interesting_calls(
        step_results=step_results,
        recorded_calls=recorded_calls,
        overall_pass=overall_pass,
        explain_scope=explain_scope,
    )

    interesting.sort(
        key=lambda item: (
            item["call_record"].get("message_index", -1)
            if item["call_record"] is not None
            else len(messages) - 1
        ),
        reverse=True,
    )

    for item in interesting:
        call_record = item["call_record"]
        step_eval = item.get("step_eval")
        if call_record is None:
            truncated_messages = list(messages)
        else:
            message_index = call_record.get("message_index")
            if message_index is None:
                continue
            truncated_messages = messages[:message_index + 1]

        prompt = _build_explanation_prompt(step_eval or {}, call_record)
        explanation_text = _request_explanation(
            client=client,
            model=model,
            messages=truncated_messages,
            explanation_prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        explanation = _explanation_payload(prompt, explanation_text)
        if call_record is not None:
            call_record["explanation"] = explanation

        if step_eval is not None:
            step_eval["llm_explanation"] = explanation_text
        elif call_record is not None and "llm_explanation" not in call_record:
            call_record["llm_explanation"] = explanation_text


# ---------------------------------------------------------------------------
# Tool-call mediation loop
# ---------------------------------------------------------------------------


def run_scenario(
    client: OpenAIClient,
    model: str,
    scenario: Dict[str, Any],
    openai_tools: List[Dict[str, Any]],
    store: FixtureStore,
    system_prompt: str,
    max_turns: int = 10,
    temperature: float = 0,
    max_tokens: int = 4096,
    explain_failures: bool = False,
    explain_all: bool = False,
    explain_scope: str = "mismatches",
    verbose_messages: bool = False,
    eval_mode: str = "strict",
) -> Dict[str, Any]:
    """Run a single scenario through the LLM tool-call mediation loop.

    Args:
        explain_failures: If True, on first mismatch stop the scenario and
            ask the LLM to explain its reasoning. The explanation is included
            in the result under step_results[i]["llm_explanation"].
        explain_all: If True, perform a post-hoc explanation pass after
            evaluation and attach explanations to selected tool calls.
        explain_scope: Which calls receive post-hoc explanations:
            "mismatches", "all_failed", or "all".
        eval_mode: "strict" or "relaxed". Can be overridden per-scenario
            via ``eval_mode`` key in the scenario YAML. In relaxed mode,
            calls to DISCOVERY_TOOLS before the expected tool are skipped.

    Returns a result dict with step-by-step evaluation.
    """
    # Per-scenario eval_mode override
    effective_eval_mode = scenario.get("eval_mode", eval_mode)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": scenario["query"]},
    ]

    expected_steps = scenario.get("expected_steps", [])
    recorded_calls: List[Dict[str, Any]] = []
    step_results: List[Dict[str, Any]] = []
    start_time = time.time()
    error: Optional[str] = None
    final_answer = ""
    stopped_for_explanation = False
    total_prompt_tokens = 0
    total_completion_tokens = 0
    peak_context_tokens = 0
    # Cursor into expected_steps for inline eval (explain_failures mode)
    next_expected_idx = 0

    for turn in range(max_turns):
        if verbose_messages:
            print(f"\n--- Turn {turn + 1}: messages sent to LLM ---")
            print(json.dumps(messages, indent=2, ensure_ascii=False))
            print("--- end messages ---\n")
        try:
            response = client.chat_completion(
                model=model,
                messages=messages,
                tools=openai_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            error = f"api_error: {e}"
            break
        except json.JSONDecodeError as e:
            error = f"json_error: {e}"
            break

        usage = response.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        total_prompt_tokens += pt
        total_completion_tokens += ct
        if pt > peak_context_tokens:
            peak_context_tokens = pt

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            # LLM responded with text — conversation done
            final_answer = message.get("content", "") or ""
            messages.append(message)

            # Check if LLM should have called a tool but didn't
            if explain_failures and next_expected_idx < len(expected_steps):
                # Skip any remaining optional steps to find next required
                while (
                    next_expected_idx < len(expected_steps)
                    and expected_steps[next_expected_idx].get("optional")
                ):
                    step_results.append({
                        "step": next_expected_idx + 1,
                        "expected_tool": expected_steps[next_expected_idx]["tool"],
                        "actual_tool": None,
                        "tool_match": False,
                        "param_assertions": {},
                        "params_pass": False,
                        "optional": True,
                        "skipped_optional": True,
                        "call_index": None,
                    })
                    next_expected_idx += 1

                if next_expected_idx < len(expected_steps):
                    step_eval = {
                        "step": next_expected_idx + 1,
                        "expected_tool": expected_steps[next_expected_idx]["tool"],
                        "actual_tool": None,
                        "tool_match": False,
                        "param_assertions": {},
                        "params_pass": False,
                        "missing": True,
                        "call_index": None,
                    }
                    prompt = _build_explanation_prompt(step_eval, None)
                    explanation = _request_explanation(
                        client,
                        model,
                        messages,
                        prompt,
                        temperature=temperature,
                        max_tokens=2048,
                    )
                    step_eval["llm_explanation"] = explanation
                    step_results.append(step_eval)
                    stopped_for_explanation = True
            break

        # Append assistant message with tool calls
        call_message_index = len(messages)
        messages.append(message)

        # Process each tool call
        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                tool_args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            call_record = {
                "tool": tool_name,
                "arguments": tool_args,
                "message_index": call_message_index,
                "call_index": len(recorded_calls),
            }
            recorded_calls.append(call_record)

            # Get canned response
            canned = store.match(tool_name, tool_args)
            canned_str = json.dumps(canned, indent=2)

            # Append tool result
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": canned_str,
                }
            )

            # Inline evaluation for explain_failures mode
            if explain_failures and next_expected_idx < len(expected_steps):
                expected = expected_steps[next_expected_idx]
                step_eval = evaluate_step(expected, tool_name, tool_args)
                step_eval["step"] = next_expected_idx + 1
                step_eval["call_index"] = call_record["call_index"]

                if step_eval["tool_match"]:
                    # Matched current expected step
                    if not step_eval["params_pass"]:
                        prompt = _build_explanation_prompt(step_eval, call_record)
                        explanation = _request_explanation(
                            client, model, messages, prompt,
                            temperature=temperature, max_tokens=2048,
                        )
                        step_eval["llm_explanation"] = explanation
                        step_results.append(step_eval)
                        stopped_for_explanation = True
                        break
                    step_results.append(step_eval)
                    next_expected_idx += 1
                elif expected.get("optional"):
                    # Optional step not matched — skip it, try next
                    step_results.append({
                        "step": next_expected_idx + 1,
                        "expected_tool": expected["tool"],
                        "actual_tool": None,
                        "tool_match": False,
                        "param_assertions": {},
                        "params_pass": False,
                        "optional": True,
                        "skipped_optional": True,
                        "call_index": None,
                    })
                    next_expected_idx += 1
                    # Re-evaluate same call against next expected step
                    if next_expected_idx < len(expected_steps):
                        expected2 = expected_steps[next_expected_idx]
                        step_eval2 = evaluate_step(
                            expected2, tool_name, tool_args,
                        )
                        step_eval2["step"] = next_expected_idx + 1
                        step_eval2["call_index"] = call_record["call_index"]
                        if not step_eval2["tool_match"] or not step_eval2["params_pass"]:
                            prompt = _build_explanation_prompt(
                                step_eval2, call_record,
                            )
                            explanation = _request_explanation(
                                client, model, messages, prompt,
                                temperature=temperature, max_tokens=2048,
                            )
                            step_eval2["llm_explanation"] = explanation
                            step_results.append(step_eval2)
                            stopped_for_explanation = True
                            break
                        step_results.append(step_eval2)
                        next_expected_idx += 1
                else:
                    # Required step, wrong tool — fail
                    prompt = _build_explanation_prompt(step_eval, call_record)
                    explanation = _request_explanation(
                        client, model, messages, prompt,
                        temperature=temperature, max_tokens=2048,
                    )
                    step_eval["llm_explanation"] = explanation
                    step_results.append(step_eval)
                    stopped_for_explanation = True
                    break

        if stopped_for_explanation:
            break

        if finish_reason == "length":
            error = "max_tokens_exceeded"
            break
    else:
        error = "max_turns_exceeded"

    wall_time = time.time() - start_time

    # Post-hoc evaluation (only for steps not already evaluated inline)
    if not explain_failures:
        step_results = _align_steps(expected_steps, recorded_calls, effective_eval_mode)
    else:
        # In explain mode, add remaining unevaluated steps
        for i in range(next_expected_idx, len(expected_steps)):
            is_opt = expected_steps[i].get("optional", False)
            if is_opt:
                step_results.append({
                    "step": i + 1,
                    "expected_tool": expected_steps[i]["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "optional": True,
                    "skipped_optional": True,
                    "call_index": None,
                })
            else:
                step_results.append({
                    "step": i + 1,
                    "expected_tool": expected_steps[i]["tool"],
                    "actual_tool": None,
                    "tool_match": False,
                    "param_assertions": {},
                    "params_pass": False,
                    "missing": True,
                    "skipped": True,
                    "call_index": None,
                })

    # Overall pass: all required (non-optional) steps matched
    required_steps = [s for s in step_results if not s.get("skipped_optional")]
    overall_pass = (
        len(required_steps) > 0
        and all(s["tool_match"] and s["params_pass"] for s in required_steps)
        and error is None
    )

    if explain_all and not explain_failures:
        _collect_posthoc_explanations(
            client=client,
            model=model,
            messages=messages,
            step_results=step_results,
            recorded_calls=recorded_calls,
            overall_pass=overall_pass,
            explain_scope=explain_scope,
            temperature=temperature,
            max_tokens=2048,
        )

    result: Dict[str, Any] = {
        "scenario_id": scenario["id"],
        "category": scenario.get("category", ""),
        "query": scenario["query"],
        "eval_mode": effective_eval_mode,
        "steps": step_results,
        "overall_pass": overall_pass,
        "total_tool_calls": len(recorded_calls),
        "all_tool_calls": recorded_calls,
        "final_answer": final_answer[:500],
        "wall_time_seconds": round(wall_time, 2),
        "tokens": {
            "total_prompt": total_prompt_tokens,
            "total_completion": total_completion_tokens,
            "peak_context": peak_context_tokens,
        },
        "error": error,
    }

    # Include query variant metadata if present
    if scenario.get("query_variant"):
        result["base_scenario_id"] = scenario.get("base_id", scenario["id"])
        result["query_variant"] = scenario["query_variant"]
        result["query_variant_total"] = scenario.get("query_variant_total", 1)

    return result


# ---------------------------------------------------------------------------
# Results export
# ---------------------------------------------------------------------------


def export_results(
    results: List[Dict[str, Any]],
    model: str,
    output_path: str,
    scenarios_file: str,
    fixtures_file: str,
    eval_mode: str = "strict",
) -> None:
    """Export results as structured JSON."""
    passed = sum(1 for r in results if r["overall_pass"])
    total = len(results)

    report = {
        "run_id": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "eval_mode": eval_mode,
        "scenarios_file": scenarios_file,
        "fixtures_file": fixtures_file,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 3) if total > 0 else 0,
        },
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Default system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a C++ code analysis assistant. You have access to tools that can \
search and analyze an indexed C++ codebase.

The project is already indexed. Do NOT call set_project or sync_project. \
Go directly to answering the question using the available tools.

Use the available tools to answer the user's question. Be precise with tool \
arguments -- use class/function names, not signatures. For regex patterns, \
remember that patterns are anchored (matched against full name).

When you need a tool, you MUST emit a native tool call via the tool-calling \
API. Do NOT write tool invocations as plain text, markdown, code fences, or \
```tool_code``` blocks. Do NOT describe the tool call you plan to make; make \
the actual tool call instead.

When you find what you need, provide a concise answer summarizing the results.
"""

# Short addition for --validate-intent mode.
# Intentionally brief to avoid distracting small models from the main task.
VALIDATE_INTENT_ADDITION = (
    "\n\nBefore using any tool: if the request does not contain a specific C++ symbol name "
    "(a class name, function name, or filename), reply with a clarification question "
    "asking which specific class or function to look up. Do not guess or search broadly."
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@dataclass
class RunnerState:
    """Mutable state for graceful interrupt handling."""

    interrupted: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM test runner for MCP tool description optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --scenarios scenarios/basic.yaml\n"
            "  %(prog)s --scenarios scenarios/basic.yaml --model qwen3-4b\n"
            "  %(prog)s --dry-run\n"
            "  %(prog)s --list-models\n"
        ),
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=str(DEFAULT_SCENARIOS),
        help=f"Scenarios YAML file (default: {DEFAULT_SCENARIOS})",
    )
    parser.add_argument(
        "--fixtures",
        type=str,
        default=str(DEFAULT_FIXTURES_DIR),
        help="Fixtures YAML file or directory (default: fixtures/)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model ID (substring match). Default: first loaded model.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="mock_test_results.json",
        help="Output JSON file (default: mock_test_results.json)",
    )
    parser.add_argument(
        "--lm-url",
        default=os.environ.get("LM_STUDIO_URL", "http://localhost:1234"),
        help="LM Studio base URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("LM_STUDIO_TOKEN", ""),
        help="LM Studio auth token",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Temperature (default: 0)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Max output tokens per turn (default: 4096)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--scenario-id",
        action="append",
        dest="scenario_ids",
        help="Run only this scenario (repeat for multiple).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show scenarios without running",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models from LM Studio",
    )
    explain_group = parser.add_mutually_exclusive_group()
    explain_group.add_argument(
        "--explain-failures",
        action="store_true",
        help=(
            "On first mismatch, stop the scenario and ask the LLM "
            "to explain its reasoning. Adds 'llm_explanation' field "
            "to failed steps in the output."
        ),
    )
    explain_group.add_argument(
        "--explain-all",
        action="store_true",
        help=(
            "After evaluation, collect post-hoc explanations for selected "
            "tool calls and attach them to the output."
        ),
    )
    parser.add_argument(
        "--explain-scope",
        choices=["mismatches", "all_failed", "all"],
        default="mismatches",
        help=(
            "Which calls to explain in post-hoc mode: 'mismatches' "
            "(default), 'all_failed', or 'all'."
        ),
    )
    parser.add_argument(
        "--verbose-messages",
        action="store_true",
        help=(
            "Print the exact messages array sent to the LLM before each API call. "
            "Useful for debugging context presentation issues (e.g. call_chain step-2 failures)."
        ),
    )
    parser.add_argument(
        "--eval-mode",
        choices=["strict", "relaxed"],
        default="strict",
        help=(
            "Step evaluation mode. 'strict' (default): first call must match "
            "first expected step. 'relaxed': calls to discovery tools "
            "(find_symbols_by_pattern) before the expected tool are skipped."
        ),
    )
    parser.add_argument(
        "--validate-intent",
        action="store_true",
        help=(
            "Append a short instruction telling the model to ask for clarification "
            "when the request lacks a specific symbol name. "
            "Scenarios where the model asks for clarification instead of searching "
            "are marked as 'clarification_requested' (not PASS, not FAIL)."
        ),
    )
    args = parser.parse_args()

    client = OpenAIClient(
        base_url=args.lm_url,
        token=args.token,
        timeout=args.timeout,
    )

    # --list-models
    if args.list_models:
        try:
            models = client.list_models()
        except urllib.error.URLError as e:
            print(f"Error connecting to LM Studio: {e}")
            sys.exit(1)
        print(f"Available models ({len(models)}):")
        for m in models:
            print(f"  - {m}")
        return

    # Load scenarios
    scenarios = load_scenarios(args.scenarios)
    if args.scenario_ids:
        ids = set(args.scenario_ids)
        scenarios = [s for s in scenarios if s["id"] in ids]

    if not scenarios:
        print("No scenarios to run.")
        sys.exit(1)

    # --dry-run
    if args.dry_run:
        print(f"Scenarios ({len(scenarios)}):")
        for s in scenarios:
            variant_tag = ""
            if s.get("query_variant"):
                variant_tag = f" [variant {s['query_variant']}/{s['query_variant_total']}]"
            print(f"  [{s['id']}] ({s.get('category', '')}){variant_tag} " f"{s['query'][:70]}")
        return

    # Resolve model
    try:
        available_models = client.list_models()
    except urllib.error.URLError as e:
        print(f"Error connecting to LM Studio: {e}")
        sys.exit(1)

    if not available_models:
        print("No models loaded in LM Studio.")
        sys.exit(1)

    if args.model:
        matches = [m for m in available_models if args.model in m]
        if not matches:
            print(f"No model matching '{args.model}'. Available: {available_models}")
            sys.exit(1)
        model = matches[0]
    else:
        model = available_models[0]

    # Load fixtures and tools
    store = FixtureStore()
    fixtures_path = Path(args.fixtures)
    if fixtures_path.is_dir():
        fixture_files = sorted(fixtures_path.glob("*.yaml"))
        for ff in fixture_files:
            store.load(ff)
        fixtures_label = f"{len(fixture_files)} files from {args.fixtures}"
    else:
        store.load(args.fixtures)
        fixtures_label = args.fixtures
    openai_tools = mcp_tools_to_openai(list_tools_b())

    # Interrupt handler
    state = RunnerState()

    def handle_interrupt(signum: int, frame: Any) -> None:
        if state.interrupted:
            print("\nForced exit.")
            sys.exit(1)
        print("\nInterrupted — finishing current scenario...")
        state.interrupted = True

    signal.signal(signal.SIGINT, handle_interrupt)

    # Run
    print(f"Model: {model}")
    print(f"Scenarios: {len(scenarios)} from {args.scenarios}")
    print(f"Fixtures: {fixtures_label}")
    print(f"Output: {args.output}")
    if args.explain_failures:
        print("Explain failures: ON")
    if args.explain_all:
        print(f"Explain all: ON ({args.explain_scope})")
    if args.verbose_messages:
        print("Verbose messages: ON (printing messages array each turn)")
    if args.eval_mode != "strict":
        print(f"Eval mode: {args.eval_mode}")
    if args.validate_intent:
        print("Validate intent: ON (model asked to clarify vague requests)")
    print()

    system_prompt = SYSTEM_PROMPT
    if args.validate_intent:
        system_prompt = SYSTEM_PROMPT + VALIDATE_INTENT_ADDITION

    results: List[Dict[str, Any]] = []
    for i, scenario in enumerate(scenarios):
        if state.interrupted:
            break

        print(f"[{i + 1}/{len(scenarios)}] {scenario['id']}: {scenario['query'][:60]}...")

        result = run_scenario(
            client=client,
            model=model,
            scenario=scenario,
            openai_tools=openai_tools,
            store=store,
            system_prompt=system_prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            explain_failures=args.explain_failures,
            explain_all=args.explain_all,
            explain_scope=args.explain_scope,
            verbose_messages=args.verbose_messages,
            eval_mode=args.eval_mode,
        )
        results.append(result)

        # Detect clarification_requested: no tool calls, model responded with text
        clarification = (
            args.validate_intent
            and not result["all_tool_calls"]
            and not result["overall_pass"]
            and result.get("final_answer", "").strip()
        )
        if clarification:
            result["clarification_requested"] = True

        if clarification:
            status = "CLAR"
        elif result["overall_pass"]:
            status = "PASS"
        else:
            status = "FAIL"
        tools_used = [tc["tool"] for tc in result["all_tool_calls"]]
        print(f"  {status} | Tools: {tools_used} | {result['wall_time_seconds']}s")
        if clarification:
            answer_preview = result.get("final_answer", "")[:120].replace("\n", " ")
            print(f"  CLARIFY: {answer_preview}")
        if result["error"]:
            print(f"  ERROR: {result['error']}")
        if args.explain_failures and not result["overall_pass"]:
            for step in result["steps"]:
                explanation = step.get("llm_explanation")
                if explanation:
                    short = explanation[:200].replace("\n", " ")
                    if len(explanation) > 200:
                        short += "..."
                    print(f"  EXPLAIN: {short}")
        elif args.explain_all:
            for call in result["all_tool_calls"]:
                explanation = call.get("explanation", {}).get("response")
                if explanation:
                    short = explanation[:200].replace("\n", " ")
                    if len(explanation) > 200:
                        short += "..."
                    print(f"  EXPLAIN[{call['tool']}]: {short}")

    # Export
    export_results(
        results=results,
        model=model,
        output_path=args.output,
        scenarios_file=args.scenarios,
        fixtures_file=fixtures_label,
        eval_mode=args.eval_mode,
    )

    # Summary
    passed = sum(1 for r in results if r["overall_pass"])
    clarified = sum(1 for r in results if r.get("clarification_requested"))
    total = len(results)
    print(f"\n{'=' * 50}")
    if clarified:
        print(f"Results: {passed}/{total} passed ({passed / total * 100:.0f}%), "
              f"{clarified} clarification requested")
    else:
        print(f"Results: {passed}/{total} passed ({passed / total * 100:.0f}%)")

    total_wall = sum(r["wall_time_seconds"] for r in results)
    total_prompt = sum(r["tokens"]["total_prompt"] for r in results)
    total_compl = sum(r["tokens"]["total_completion"] for r in results)
    if total_prompt:
        tps = total_compl / total_wall if total_wall else 0
        print(f"Tokens:  prompt={total_prompt:,}  completion={total_compl:,}  "
              f"~{tps:.0f} tok/s completion")

    # Per-base-scenario variant summary (only if multi-query scenarios exist)
    has_variants = any(r.get("query_variant") for r in results)
    if has_variants:
        from collections import OrderedDict

        base_groups: Dict[str, List[Dict[str, Any]]] = OrderedDict()
        for r in results:
            base_id = r.get("base_scenario_id", r["scenario_id"])
            base_groups.setdefault(base_id, []).append(r)

        print("\nPer-scenario robustness:")
        for base_id, group in base_groups.items():
            if len(group) <= 1:
                continue
            group_passed = sum(1 for r in group if r["overall_pass"])
            group_total = len(group)
            pct = group_passed / group_total * 100
            bar = "+" * group_passed + "-" * (group_total - group_passed)
            print(f"  {base_id}: {group_passed}/{group_total} ({pct:.0f}%) [{bar}]")
            for r in group:
                if not r["overall_pass"]:
                    print(f"    FAIL: {r['query'][:70]}")

    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
