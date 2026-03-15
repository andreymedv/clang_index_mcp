#!/usr/bin/env python3
"""
Diagnostic script: interview the model about looping behavior (RC-5).

Runs a scenario step-by-step and asks the model to explain:
1. Why it chose a specific tool on the first call
2. Why it keeps calling the same tool after getting empty results

Usage:
    python tools/mock_server/diagnose_looping.py [--scenario SCENARIO_ID]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from mcp_server.consolidated_tools import list_tools_b  # noqa: E402

LM_STUDIO_URL = "http://localhost:1234/v1"
API_TOKEN = "sk-lm-5q4Npqsm:bWwqKV2nNskIxohZnteZ"
MODEL = "qwen/qwen3.5-9b"

# Looping scenarios to investigate
LOOP_SCENARIOS = {
    "RC3-01": {
        "query": "What other functions does initialize() call internally?",
        "expected_tool": "get_functions_called_by",
        "wrong_tool": "find_symbols_by_pattern",
    },
    "RC3-03": {
        "query": "Show all the function calls that happen inside render()",
        "expected_tool": "get_functions_called_by",
        "wrong_tool": "find_symbols_by_pattern",
    },
    "RC1-03": {
        "query": "I need to find all methods defined in files under Tests/ directory",
        "expected_tool": "find_symbols_by_pattern",
        "wrong_tool": "find_in_file",
    },
    "RC2-03": {
        "query": "What functions are called by processData? Show me its dependencies.",
        "expected_tool": "get_functions_called_by",
        "wrong_tool": "find_symbols_by_pattern",
    },
}

EMPTY_RESULTS = {
    "find_symbols_by_pattern": json.dumps({"results": [], "next_steps": [
        "Try a broader pattern",
        "Use find_in_file to search within a specific file",
    ]}),
    "find_in_file": json.dumps({"symbols": [], "message": "No symbols found in specified file"}),
    "get_functions_called_by": json.dumps({"callees": [], "message": "Function not found or has no recorded calls"}),
}


def get_tools_schema():
    tools = list_tools_b()
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.inputSchema,
            },
        }
        for t in tools
    ]


def chat(messages, tools=None, tool_choice="auto"):
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    resp = requests.post(
        f"{LM_STUDIO_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def extract_tool_call(response):
    choice = response["choices"][0]
    msg = choice["message"]
    if msg.get("tool_calls"):
        tc = msg["tool_calls"][0]
        return tc["function"]["name"], json.loads(tc["function"]["arguments"]), msg
    return None, None, msg


def ask_model_text(messages, question):
    """Ask the model a plain text question (no tools) and get its answer."""
    msgs = messages + [{"role": "user", "content": question}]
    resp = chat(msgs, tools=None)
    return resp["choices"][0]["message"]["content"]


def run_diagnosis(scenario_id, scenario):
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario_id}")
    print(f"Query: {scenario['query']}")
    print(f"Expected tool: {scenario['expected_tool']}")
    print(f"{'='*60}")

    tools_schema = get_tools_schema()
    system_msg = (
        "You are a helpful assistant analyzing C++ codebases. "
        "Use the available tools to answer the user's question."
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": scenario["query"]},
    ]

    # --- Step 1: Get first tool call ---
    print("\n[Step 1] Getting first tool call...")
    resp = chat(messages, tools=tools_schema)
    tool_name, tool_args, assistant_msg = extract_tool_call(resp)

    if not tool_name:
        print(f"  No tool call made. Model said: {assistant_msg.get('content', '')[:200]}")
        return

    print(f"  Tool called: {tool_name}")
    print(f"  Arguments: {json.dumps(tool_args, indent=4)}")

    if tool_name == scenario["expected_tool"]:
        print(f"\n  ✅ Correct tool chosen on first call!")
    else:
        print(f"\n  ❌ Wrong tool: expected {scenario['expected_tool']}, got {tool_name}")

    # --- Step 2: Ask why the first tool was chosen ---
    messages.append({"role": "assistant", "content": None, "tool_calls": assistant_msg["tool_calls"]})
    # Add empty tool result to complete the conversation
    empty_result = EMPTY_RESULTS.get(tool_name, '{"result": "empty"}')
    messages.append({
        "role": "tool",
        "tool_call_id": assistant_msg["tool_calls"][0]["id"],
        "content": empty_result,
    })

    print("\n[Step 2] Asking model why it chose that tool...")
    explanation_q1 = (
        f"You just called `{tool_name}` with arguments {json.dumps(tool_args)}. "
        f"Before we continue, please explain: "
        f"(1) Why did you choose `{tool_name}` specifically (not another tool) for this query? "
        f"(2) Did you consider `{scenario['expected_tool']}`? If not, why not? "
        f"Answer in 3-5 sentences."
    )
    explanation1 = ask_model_text(messages, explanation_q1)
    print(f"\n  Model's explanation:\n  {explanation1}\n")

    # --- Step 3: Get second tool call (after empty result) ---
    print("[Step 3] Getting second tool call (after empty result)...")
    messages_for_step3 = messages + [{"role": "user", "content": "Please continue to answer the original question."}]
    resp2 = chat(messages_for_step3, tools=tools_schema)
    tool_name2, tool_args2, assistant_msg2 = extract_tool_call(resp2)

    if not tool_name2:
        print(f"  No second tool call. Model said: {assistant_msg2.get('content', '')[:200]}")
        return

    print(f"  Second tool called: {tool_name2}")
    print(f"  Arguments: {json.dumps(tool_args2, indent=4)}")

    if tool_name2 == tool_name:
        print(f"\n  🔄 Model is LOOPING — called same tool {tool_name} again!")
    elif tool_name2 == scenario["expected_tool"]:
        print(f"\n  ✅ Model CORRECTED itself on retry — now using {scenario['expected_tool']}")
    else:
        print(f"\n  ❓ Model switched to a third tool: {tool_name2}")

    # --- Step 4: Ask why it chose same tool again ---
    print("\n[Step 4] Asking model why it called same/new tool after empty result...")
    explanation_q2 = (
        f"After the first call to `{tool_name}` returned empty results, "
        f"you called `{tool_name2}` with {json.dumps(tool_args2)}. "
        f"Please explain: "
        f"(1) What made you decide to call `{tool_name2}` specifically? "
        f"(2) Why didn't you switch to `{scenario['expected_tool']}`? "
        f"Answer in 3-5 sentences."
    )
    explanation2 = ask_model_text(messages_for_step3, explanation_q2)
    print(f"\n  Model's explanation:\n  {explanation2}\n")

    print(f"\n{'='*60}")
    print("DIAGNOSIS COMPLETE")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Diagnose model looping behavior")
    parser.add_argument(
        "--scenario",
        choices=list(LOOP_SCENARIOS.keys()),
        default=None,
        help="Specific scenario to diagnose (default: run all)",
    )
    args = parser.parse_args()

    scenarios = {args.scenario: LOOP_SCENARIOS[args.scenario]} if args.scenario else LOOP_SCENARIOS

    print(f"Running looping diagnosis for {len(scenarios)} scenario(s)...")
    print(f"Model: {MODEL}")
    print(f"LM Studio: {LM_STUDIO_URL}")

    for scenario_id, scenario in scenarios.items():
        try:
            run_diagnosis(scenario_id, scenario)
            time.sleep(1)
        except Exception as e:
            print(f"\n  ERROR in {scenario_id}: {e}")
            continue


if __name__ == "__main__":
    main()
