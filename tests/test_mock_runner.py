from tools.mock_server import runner
from tools.mock_server.fixtures import FixtureStore


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, model, messages, tools, temperature=0, max_tokens=4096):
        return self._responses.pop(0)


def test_system_prompt_bans_textual_tool_plans():
    assert "native tool call via the tool-calling API" in runner.SYSTEM_PROMPT
    assert "Do NOT write tool invocations as plain text" in runner.SYSTEM_PROMPT
    assert "tool_code" in runner.SYSTEM_PROMPT


def test_find_interesting_calls_mismatches_includes_mismatches_and_extra_calls():
    recorded_calls = [
        {"tool": "wrong_tool", "arguments": {}, "call_index": 0, "message_index": 2},
        {"tool": "right_tool", "arguments": {}, "call_index": 1, "message_index": 4},
        {"tool": "extra_tool", "arguments": {}, "call_index": 2, "message_index": 6},
    ]
    step_results = [
        {
            "step": 1,
            "expected_tool": "expected_tool",
            "actual_tool": "wrong_tool",
            "tool_match": False,
            "params_pass": False,
            "call_index": 0,
        },
        {
            "step": 2,
            "expected_tool": "right_tool",
            "actual_tool": "right_tool",
            "tool_match": True,
            "params_pass": True,
            "call_index": 1,
        },
    ]

    interesting = runner._find_interesting_calls(
        step_results=step_results,
        recorded_calls=recorded_calls,
        overall_pass=False,
        explain_scope="mismatches",
    )

    assert [item["call_record"]["call_index"] for item in interesting] == [0, 2]
    assert interesting[0]["step_eval"]["step"] == 1
    assert interesting[1]["step_eval"] is None


def test_find_interesting_calls_mismatches_includes_missing_steps_without_calls():
    step_results = [
        {
            "step": 1,
            "expected_tool": "find_callers",
            "actual_tool": None,
            "tool_match": False,
            "params_pass": False,
            "missing": True,
            "call_index": None,
        }
    ]

    interesting = runner._find_interesting_calls(
        step_results=step_results,
        recorded_calls=[],
        overall_pass=False,
        explain_scope="mismatches",
    )

    assert len(interesting) == 1
    assert interesting[0]["call_record"] is None
    assert interesting[0]["step_eval"]["step"] == 1


def test_collect_posthoc_explanations_processes_calls_in_reverse_message_order(monkeypatch):
    recorded_calls = [
        {"tool": "wrong_tool", "arguments": {}, "call_index": 0, "message_index": 3},
        {"tool": "extra_tool", "arguments": {}, "call_index": 1, "message_index": 6},
    ]
    step_results = [
        {
            "step": 1,
            "expected_tool": "expected_tool",
            "actual_tool": "wrong_tool",
            "tool_match": False,
            "params_pass": False,
            "call_index": 0,
        }
    ]
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None},
        {"role": "assistant", "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": "thinking"},
        {"role": "assistant", "tool_calls": [{"id": "call-2"}]},
        {"role": "tool", "content": "{}"},
    ]
    calls = []

    def fake_request(client, model, messages, explanation_prompt, temperature=0, max_tokens=2048):
        calls.append({
            "message_count": len(messages),
            "last_role": messages[-1]["role"],
            "prompt": explanation_prompt,
        })
        return f"because-{len(calls)}"

    monkeypatch.setattr(runner, "_request_explanation", fake_request)

    runner._collect_posthoc_explanations(
        client=FakeClient([]),
        model="test-model",
        messages=messages,
        step_results=step_results,
        recorded_calls=recorded_calls,
        overall_pass=False,
        explain_scope="mismatches",
    )

    assert [item["message_count"] for item in calls] == [7, 4]
    assert all(item["last_role"] == "assistant" for item in calls)
    assert step_results[0]["llm_explanation"] == "because-2"
    assert recorded_calls[0]["explanation"]["response"] == "because-2"
    assert recorded_calls[1]["explanation"]["response"] == "because-1"


def test_collect_posthoc_explanations_explains_missing_step_without_tool_call(monkeypatch):
    step_results = [
        {
            "step": 1,
            "expected_tool": "find_callers",
            "actual_tool": None,
            "tool_match": False,
            "params_pass": False,
            "missing": True,
            "call_index": None,
        }
    ]
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "I can answer without tools."},
    ]
    calls = []

    def fake_request(client, model, messages, explanation_prompt, temperature=0, max_tokens=2048):
        calls.append({
            "message_count": len(messages),
            "last_role": messages[-1]["role"],
            "prompt": explanation_prompt,
        })
        return "because-no-tool"

    monkeypatch.setattr(runner, "_request_explanation", fake_request)

    runner._collect_posthoc_explanations(
        client=FakeClient([]),
        model="test-model",
        messages=messages,
        step_results=step_results,
        recorded_calls=[],
        overall_pass=False,
        explain_scope="mismatches",
    )

    assert calls == [
        {
            "message_count": 3,
            "last_role": "assistant",
            "prompt": (
                "Explain why you chose not to use any tool. "
                "If you could not find suitable tool, quote an EXACT part (or parts) "
                "of 'find_callers' tool description that made you decide against calling one."
                "Be concise. Do not output any fluff. "
            ),
        }
    ]
    assert step_results[0]["llm_explanation"] == "because-no-tool"


def test_run_scenario_explain_all_adds_posthoc_explanation(monkeypatch):
    client = FakeClient(
        [
            {
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "function": {
                                        "name": "find_symbols_by_pattern",
                                        "arguments": "{\"pattern\": \"Widget\"}",
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
            {
                "usage": {"prompt_tokens": 12, "completion_tokens": 2},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "done"},
                    }
                ],
            },
        ]
    )
    store = FixtureStore()
    store._defaults["find_symbols_by_pattern"] = {"results": []}

    def fake_request(client, model, messages, explanation_prompt, temperature=0, max_tokens=2048):
        return "posthoc explanation"

    monkeypatch.setattr(runner, "_request_explanation", fake_request)

    result = runner.run_scenario(
        client=client,
        model="test-model",
        scenario={
            "id": "S-01",
            "query": "Find callers of Widget",
            "expected_steps": [
                {
                    "tool": "find_callers",
                    "params": {
                        "function_name": {"type": "contains", "value": "Widget"},
                    },
                }
            ],
        },
        openai_tools=[],
        store=store,
        system_prompt="system",
        explain_all=True,
        explain_scope="mismatches",
    )

    assert result["overall_pass"] is False
    assert result["total_tool_calls"] == 1
    assert result["all_tool_calls"][0]["message_index"] == 2
    assert result["all_tool_calls"][0]["explanation"]["response"] == "posthoc explanation"
    assert result["steps"][0]["llm_explanation"] == "posthoc explanation"


def test_run_scenario_explain_all_explains_missing_tool_call(monkeypatch):
    client = FakeClient(
        [
            {
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "I can answer this directly.",
                        },
                    }
                ],
            }
        ]
    )
    prompts = []

    def fake_request(client, model, messages, explanation_prompt, temperature=0, max_tokens=2048):
        prompts.append({
            "message_count": len(messages),
            "last_role": messages[-1]["role"],
            "prompt": explanation_prompt,
        })
        return "posthoc no-tool explanation"

    monkeypatch.setattr(runner, "_request_explanation", fake_request)

    result = runner.run_scenario(
        client=client,
        model="test-model",
        scenario={
            "id": "S-02",
            "query": "Find callers of Widget",
            "expected_steps": [
                {
                    "tool": "find_callers",
                    "params": {
                        "function_name": {"type": "contains", "value": "Widget"},
                    },
                }
            ],
        },
        openai_tools=[],
        store=FixtureStore(),
        system_prompt="system",
        explain_all=True,
        explain_scope="mismatches",
    )

    assert result["overall_pass"] is False
    assert result["total_tool_calls"] == 0
    assert result["final_answer"] == "I can answer this directly."
    assert result["steps"][0]["missing"] is True
    assert result["steps"][0]["llm_explanation"] == "posthoc no-tool explanation"
    assert prompts == [
        {
            "message_count": 3,
            "last_role": "assistant",
            "prompt": (
                "Explain why you chose not to use any tool. "
                "If you could not find suitable tool, quote an EXACT part (or parts) "
                "of 'find_callers' tool description that made you decide against calling one."
                "Be concise. Do not output any fluff. "
            ),
        }
    ]
