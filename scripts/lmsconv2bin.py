#!/usr/bin/env python3

import json
from pathlib import Path


def extract_text_content(block_content):
    """Extract text parts from content[] (type == 'text')."""
    parts = []
    for c in block_content:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts).strip()


def is_analysis_step(step):
    style = step.get("style", {})
    prefix = step.get("prefix", "") or ""
    # is thinking style or explicit analysis-channel in a prefix
    if style.get("type") == "thinking":
        return True
    if "<|channel|>analysis" in prefix:
        return True
    return False


def is_structural_channel_text(text: str) -> bool:
    """Filter out internal use markers like '<|channel|>final<|message|>'"""
    t = text.strip()
    return t.startswith("<|channel|>") and t.endswith("<|message|>")


def format_tool_call(block_content):
    """Try building a short tool call description."""
    lines = []
    for c in block_content:
        if c.get("type") == "toolCallRequest":
            name = c.get("name", "unknown_tool")
            params = c.get("parameters", {})
            plugin = c.get("pluginIdentifier") or ""
            lines.append(f"Tool: `{name}` from `{plugin}`")
            if params:
                pretty = json.dumps(params, ensure_ascii=False, indent=2)
                lines.append("Parameters:")
                lines.append("```json")
                lines.append(pretty)
                lines.append("```")
    return "\n".join(lines).strip()


def format_tool_result(block_content):
    """toolCallResult.content usually has JSON string with array of content-blocks."""
    lines = []
    for c in block_content:
        if c.get("type") == "toolCallResult":
            raw = c.get("content", "")
            # Try to parse; show as-is if failed
            try:
                parsed = json.loads(raw)
                # parsed usually looks like the following: [{ "type": "text", "text": "..."}, ...]
                text_parts = []
                for item in parsed:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                text = "\n".join(text_parts).strip()
            except Exception:
                text = raw
            if text:
                lines.append(text)
    return "\n".join(lines).strip()


def process_assistant_message(msg):
    """Return raw step list [(kind, text)] in an original order.
    kind is one of {"analysis", "tool_call", "tool_result", "final"}.
    """
    version = msg["versions"][msg.get("currentlySelected", 0)]
    if version.get("type") == "singleStep":
        text = extract_text_content(version.get("content", []))
        return [("final", text)] if text else []

    if version.get("type") != "multiStep":
        return []

    ordered_steps = []

    for step in version.get("steps", []):
        stype = step.get("type")
        content = step.get("content", [])

        # analysis/thinking
        if stype == "contentBlock" and is_analysis_step(step):
            text = extract_text_content(content)
            if text:
                ordered_steps.append(("analysis", text))
            continue

        # tool call
        if stype == "contentBlock" and any(c.get("type") == "toolCallRequest" for c in content):
            tool_text = format_tool_call(content)
            if tool_text:
                ordered_steps.append(("tool_call", tool_text))
            continue

        # tool call result
        if stype == "contentBlock" and any(c.get("type") == "toolCallResult" for c in content):
            result_text = format_tool_result(content)
            if result_text:
                ordered_steps.append(("tool_result", result_text))
            continue

        # general assistant response
        if stype == "contentBlock":
            text = extract_text_content(content)
            if text and not is_structural_channel_text(text):
                ordered_steps.append(("final", text))
            continue

    return ordered_steps


def process_user_message(msg: dict) -> str:
    version = msg["versions"][msg.get("currentlySelected", 0)]
    text_parts = []
    for c in version.get("content", []):
        if c.get("type") == "text":
            text_parts.append(c.get("text", ""))
    return "\n".join(text_parts).strip()


def conversation_to_markdown(data: dict) -> str:
    lines = []
    name = data.get("name") or "Conversation"
    lines.append(f"# {name}")
    lines.append("")

    system_prompt = data.get("systemPrompt", "")
    if system_prompt:
        lines.append("## System")
        lines.append("")
        lines.append("```")
        lines.append(system_prompt)
        lines.append("```")
        lines.append("")

    for msg in data.get("messages", []):
        # In LM Studio, main information is in versions[currentlySelected]
        role = msg["versions"][msg.get("currentlySelected", 0)].get("role")

        if role == "user":
            user_text = process_user_message(msg)
            if not user_text:
                continue
            lines.append("### User")
            lines.append("")
            lines.append(user_text)
            lines.append("")
        elif role == "assistant":
            steps = process_assistant_message(msg)
            if not steps:
                continue

            for kind, block in steps:
                if kind == "analysis":
                    lines.append("### Assistant analysis")
                    lines.append("")
                    for line in block.splitlines():
                        lines.append(f"> [ANALYSIS] {line}")
                    lines.append("")
                elif kind == "tool_call":
                    lines.append("### Assistant tools")
                    lines.append("")
                    for line in block.splitlines():
                        lines.append(f"> [TOOL CALL] {line}")
                    lines.append("")
                elif kind == "tool_result":
                    lines.append("### Assistant tools")
                    lines.append("")
                    for line in block.splitlines():
                        lines.append(f"> [TOOL RESULT] {line}")
                    lines.append("")
                elif kind == "final":
                    lines.append("### Assistant")
                    lines.append("")
                    lines.append(block)
                    lines.append("")
        else:
            # show other roles (tool etc.) separately
            version = msg["versions"][msg.get("currentlySelected", 0)]
            text = extract_text_content(version.get("content", []))
            if text:
                lines.append(f"### {role.capitalize()}")
                lines.append("")
                lines.append(text)
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="<LM Studio conversation>.json")
    parser.add_argument(
        "-o", "--output", type=Path, help="Output .md file (default: <LM Studio conversation>.md)"
    )
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as f:
        data = json.load(f)

    md = conversation_to_markdown(data)

    out_path = args.output or args.input.with_suffix(".md")
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
