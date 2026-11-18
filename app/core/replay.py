"""Replay a recorded run without Ollama (M1 record/replay, dsh llm-replay).

Every run writes `.codemitra/runs/<time>/*.jsonl`; its "model" rows hold what the model said and which tools it called.
`ReplayModel(path)` answers with those replies in order, so a real run can become a regression test.
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage


class ReplayModel:
    def __init__(self, path: str | Path):
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.replies = [AIMessage(content=r.get("text") or "", tool_calls=r.get("tool_calls") or [])
                        for r in rows if r.get("kind") == "model"]
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if self.calls >= len(self.replies):
            raise RuntimeError(f"replay exhausted after {len(self.replies)} recorded replies")
        reply = self.replies[self.calls]
        self.calls += 1
        return reply

    def stream(self, messages):
        yield self.invoke(messages)


# ── Stage 1.10: replay one recorded chat turn ─────────────────────────────────────────────────────────────────────
def to_message(d: dict):
    """Plain data from a trace back to a LangChain message (the reverse of loop.message_dict)."""
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    role, content = d.get("role"), d.get("content") or ""
    if role == "system":
        return SystemMessage(content=content)
    if role == "assistant":
        return AIMessage(content=content, tool_calls=[{"name": c.get("name"), "args": c.get("args") or {},
                                                       "id": c.get("id") or f"r{i}"}
                                                      for i, c in enumerate(d.get("tool_calls") or [])])
    if role == "tool":
        return ToolMessage(content=content, tool_call_id=d.get("tool_call_id") or "r0")
    return HumanMessage(content=content)


def start_check(snapshot: dict, folder: str | Path) -> dict:
    """Does `folder` hold the files the turn started with? {same, differ, missing, extra} (relative paths).
    A snapshot that kept only the tree hash (a big project) is compared as a whole."""
    from app.core import turnfacts as TF
    now = TF.snapshot(Path(folder))
    if "_tree" in snapshot or "_tree" in now:
        same = snapshot.get("_tree") == now.get("_tree")
        return {"same": ["(all)"] if same else [], "differ": [] if same else ["(tree)"], "missing": [], "extra": []}
    return {"same": sorted(p for p in snapshot if now.get(p) == snapshot[p]),
            "differ": sorted(p for p in snapshot if p in now and now[p] != snapshot[p]),
            "missing": sorted(p for p in snapshot if p not in now),
            "extra": sorted(p for p in now if p not in snapshot)}


def first_call(record: str | Path, turn) -> dict | None:
    """The turn's first model call exactly as it was sent: {messages, tools, model, num_ctx, reply}."""
    from app.core import loop as core_loop
    from app.core import trace_check as TC
    rows = [json.loads(line) for line in TC.trace_path(Path(record)).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    calls = core_loop.rebuild_calls(rows)
    ids = {c.get("id") for c in turn.calls}
    mine = [c for c in calls if c.get("id") in ids and c.get("t") in {x.get("t") for x in turn.calls}]
    return mine[0] if mine else None


def first_tool_call(reply) -> str:
    """`name(args)` of a reply's first tool call, or `text` when it answered in words."""
    calls = (reply.get("tool_calls") if isinstance(reply, dict) else getattr(reply, "tool_calls", None)) or []
    if not calls:
        return "text"
    c = calls[0]
    return f"{c.get('name')}({json.dumps(c.get('args') or {}, sort_keys=True)})"


def replay_first(record: str | Path, turn, llm) -> dict:
    """Send the turn's first call again to `llm` (bound to the recorded tools) and compare the first tool call."""
    call = first_call(record, turn)
    if call is None:
        return {"ok": False, "error": "this turn's first call is not in the trace"}
    messages = [to_message(m) for m in call["messages"]]
    bound = llm.bind_tools(call["tools"]) if call.get("tools") else llm
    reply = bound.invoke(messages)
    was, now = first_tool_call(call.get("reply") or {}), first_tool_call(reply)
    return {"ok": True, "recorded": was, "replayed": now, "same": was == now, "model": call.get("model"),
            "messages": len(messages)}
