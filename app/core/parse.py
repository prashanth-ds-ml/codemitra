"""Tool calls written as text (M1: tolerant tool-call parsing).

Small models sometimes answer with the call as JSON in the text instead of a native tool call:
    {"name": "read_file", "arguments": {"path": "a.py"}}
    <tool_call>{"name": "run_tests", "arguments": {}}</tool_call>
    ```json {"tool": "edit_file", "parameters": {...}} ```
    <function=write_file><parameter=path>a.py</parameter><parameter=content>...</parameter></function>
The last is the Qwen3-Coder XML form, which Qwen3.5 was trained on (ollama#14493: Ollama's qwen3.5 parser reads
JSON, so a call in this form arrives as plain text). These are turned into real tool calls. Text that clearly tries
to call a tool but is not valid JSON gets a short error back, so the model can try once more.
"""
from __future__ import annotations

import json
import re
import uuid

_TAGGED = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
_FENCED = re.compile(r"```(?:json|tool_call)?\s*(\{.*?\})\s*```", re.S)
# Qwen3-Coder XML: <function=name> <parameter=key>value</parameter> ... </function> (optionally inside <tool_call>)
_XML_FN = re.compile(r"<function=([\w.-]+)>(.*?)</function>", re.S)
_XML_PARAM = re.compile(r"<parameter=([\w.-]+)>\n?(.*?)\n?</parameter>", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


def _objects(text: str) -> list[str]:
    """Top-level {...} blocks in text (brace matching that respects strings)."""
    out, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(text[start:i + 1])
    return out


def _as_call(obj, known: set[str]) -> dict | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    if isinstance(name, dict):  # {"function": {"name": ..., "arguments": ...}}
        obj, name = name, name.get("name")
    if not isinstance(name, str) or name not in known:
        return None
    args = obj.get("arguments", obj.get("parameters", obj.get("args", {})))
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    return {"name": name, "args": args, "id": f"text-{uuid.uuid4().hex[:8]}", "type": "tool_call"}


def _xml_value(raw: str):
    """A parameter's value: JSON when it is a number, list, object or true/false/null, else the text as written."""
    s = raw.strip()
    if s[:1] in "[{" or s in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", s):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
    return raw


def xml_tool_calls(text: str, known: set[str]) -> list[dict]:
    """Calls in the Qwen3-Coder XML form, for known tools only."""
    out = []
    for name, body in _XML_FN.findall(text or ""):
        if name in known:
            args = {k: _xml_value(v) for k, v in _XML_PARAM.findall(body)}
            out.append({"name": name, "args": args, "id": f"text-{uuid.uuid4().hex[:8]}", "type": "tool_call"})
    return out


def text_tool_calls(text: str, known: set[str]) -> tuple[list[dict], str]:
    """Return (tool calls found in the text, error message for a broken attempt or "")."""
    if not text:
        return [], ""
    calls, seen = [], set()
    for call in xml_tool_calls(text, known):
        key = (call["name"], json.dumps(call["args"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            calls.append(call)
    if calls:
        return calls, ""
    if "{" not in text:
        return [], ""
    candidates = [c for c in _TAGGED.findall(text) if not c.lstrip().startswith("<")] + _FENCED.findall(text) \
        + _objects(text)
    broken = False
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            if any(f'"{n}"' in raw for n in known):
                broken = True
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            call = _as_call(o, known)
            if call:
                key = (call["name"], json.dumps(call["args"], sort_keys=True))
                if key not in seen:
                    seen.add(key)
                    calls.append(call)
    if calls:
        return calls, ""
    if broken or _TAGGED.search(text):
        return [], ("✗ Your tool call was written as text and is not valid JSON. Call the tool again as a "
                    "proper tool call, with valid JSON arguments.")
    return [], ""


def for_model(messages: list) -> list:
    """The history as the model gets it: an answer's thinking is kept only after the last user message, and
    `<think>` blocks are taken out of older answers' text (the Qwen3 templates drop old thinking; ollama#14493:
    Ollama's qwen3.5 renderer mangles the thinking it is sent back). The messages kept by CodeMitra (records, traces)
    are not changed: changed ones are copies."""
    from langchain_core.messages import AIMessage, HumanMessage

    last_user = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    out = []
    for i, m in enumerate(messages):
        if isinstance(m, AIMessage) and i < last_user:
            extra = dict(getattr(m, "additional_kwargs", None) or {})
            content = m.content
            changed = extra.pop("reasoning_content", None) is not None
            if isinstance(content, str) and "<think>" in content:
                content, changed = _THINK.sub("", content).strip(), True
            if changed:
                m = m.model_copy(update={"content": content, "additional_kwargs": extra})
        out.append(m)
    return out
