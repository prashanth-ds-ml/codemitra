"""Stage 1 (ROADMAP): can the logs answer every question about a task? The audit that measures it.

For each recorded chat turn it checks the facts behind the 8 questions in docs/ROADMAP.md Stage 1 and reports, per
question, how many turns the logs can answer. "Complete" logging means 100% on new turns. Read only: it never writes
a record or the store.

    1 request   what was asked, which spec / feature / task, what kind
    2 model     every model call: tokens, time, model; the backend
    3 tools     every tool call (MCP too): arguments, result, time, full output
    4 files     what changed: a diff per change, the files at turn start
    5 claims    what the reply claimed, the evidence, true / false / unchecked
    6 used      skills, MCP tools and lessons used
    7 time      model / tools / waiting-for-you split; the machine
    8 replay    mistake tags; the turn can be replayed (start files + every call traced)

A fact a turn cannot have (no tool call -> nothing to time) counts as answered.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

QUESTIONS = {
    "request": "what was asked, which spec / feature / task, what kind",
    "model": "every model call: tokens, time, model; the backend",
    "tools": "every tool call (MCP too): arguments, result, time, full output",
    "files": "what changed: a diff per change, the files at turn start",
    "claims": "what the reply claimed, the evidence, true / false / unchecked",
    "used": "skills, MCP tools and lessons used",
    "time": "model / tools / waiting-for-you split; the machine",
    "replay": "mistake tags; replayable (start files + every call traced)",
}
OUTPUT_CAP = 3000          # tool rows keep this many characters of the output (chat.py)
TRACE_SLACK_S = 2.0        # a trace call is written just after its record rows
MACHINE_KEYS = ("os", "gpu", "ollama_version")
ID_KEYS = ("session_id", "spec", "feature", "task_id")
TIME_KEYS = ("model_s", "tools_s", "wait_s")
USED_KEYS = ("skills", "mcp", "lessons")


@dataclass
class Turn:
    file: str
    no: int
    start: dict
    end: dict | None = None
    rows: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    session: dict = field(default_factory=dict)
    prompts: set = field(default_factory=set)


@dataclass
class Answer:
    question: str
    ok: bool
    missing: list[str]


def _read(path: Path) -> list[dict]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def trace_path(record: Path) -> Path:
    return record.parent / "traces" / f"{record.stem}.jsonl"


def turns(record: Path) -> list[Turn]:
    """The chat turns of one record file, each with its rows and its trace calls (matched by time)."""
    rows = _read(record)
    out: list[Turn] = []
    session: dict = {}
    cur: Turn | None = None
    for r in rows:
        k = r.get("kind")
        if k == "session":
            session, cur = r, None
            continue
        if k == "turn_start":
            cur = Turn(file=record.name, no=int(r.get("turn") or 0), start=r, session=session)
            out.append(cur)
            continue
        if cur is None:
            continue
        if k == "turn_end" and cur.end is None and r.get("turn") in (None, cur.no):
            cur.end = r
            continue
        cur.rows.append(r)
    trace = _read(trace_path(record))
    prompts = {r.get("hash") for r in trace if r.get("kind") == "prompt"}
    calls = [r for r in trace if r.get("kind") == "call"]
    for i, t in enumerate(out):
        t0 = float(t.start.get("t") or 0)
        nxt = float(out[i + 1].start.get("t") or 0) if i + 1 < len(out) else float("inf")
        t1 = min(float(t.end.get("t") or 0) + TRACE_SLACK_S, nxt) if t.end else nxt
        t.calls = [c for c in calls if t0 <= float(c.get("t") or 0) <= t1]
        t.prompts = prompts
    return out


def _has(d: dict | None, *keys: str) -> list[str]:
    """The keys missing from d (present with any value, even empty, counts)."""
    return [k for k in keys if not d or k not in d]


def _of(t: Turn, kind: str) -> list[dict]:
    return [r for r in t.rows if r.get("kind") == kind]


def answer(t: Turn) -> list[Answer]:
    out = []

    def add(q: str, missing: list[str]) -> None:
        out.append(Answer(q, not missing, missing))

    # 1 request
    m = [] if str(t.start.get("user") or "").strip() else ["request text"]
    m += [] if t.start.get("request_kind") else ["request kind"]
    m += [f"id {k}" for k in _has(t.start, *ID_KEYS)]
    add("request", m)

    # 2 model calls
    models = _of(t, "model")
    m = []
    if not t.end:
        m.append("turn end")
    if len(t.calls) < len(models) or (models and not t.calls):
        m.append(f"traced calls ({len(t.calls)} of {len(models)})")
    for c in t.calls:
        timed = c.get("seconds") is not None or c.get("total_s") is not None
        miss = _has(c, "tokens_in", "tokens_out", "model") + ([] if timed else ["seconds"])
        if miss:
            m.append("call " + "/".join(miss))
            break
    m += [] if t.start.get("backend") else ["backend"]
    add("model", m)

    # 3 tool calls
    tools = _of(t, "tool")
    m = []
    for r in tools:
        miss = _has(r, "args", "ok", "output", "seconds")
        if miss:
            m.append("tool " + "/".join(miss))
            break
    if any(len(str(r.get("output") or "")) >= OUTPUT_CAP and "output_chars" not in r for r in tools):
        m.append("full output of cut results")
    if any(str(r.get("name", "")).startswith("mcp") and "server" not in r for r in tools):
        m.append("MCP server/tool on the row")
    add("tools", m)

    # 4 files
    changed = list((t.end or {}).get("changed") or [])
    m = [] if "files" in t.start else ["files at turn start"]
    diffs = {str(r.get("path")) for r in _of(t, "change") if "diff" in r and "before" in r and "after" in r}
    if changed and not all(str(p) in diffs for p in changed):
        m.append(f"diff per change ({len([p for p in changed if str(p) in diffs])} of {len(changed)})")
    add("files", m)

    # 5 claims
    m = []
    if str((t.end or {}).get("text") or "").strip():
        claims = _of(t, "claim")
        if not claims:
            m.append("claim row")
        elif any("verdict" not in c or "evidence" not in c for c in claims):
            m.append("claim verdict/evidence")
    add("claims", m)

    # 6 used
    add("used", [f"used {k}" for k in USED_KEYS if k not in ((t.end or {}).get("used") or {})])

    # 7 time + machine
    m = [k for k in TIME_KEYS if k not in (t.end or {})]
    m += [f"machine {k}" for k in _has(t.session, *MACHINE_KEYS)]
    add("time", m)

    # 8 replay
    m = [] if "tags" in (t.end or {}) else ["mistake tags"]
    m += [] if "files" in t.start else ["start files"]
    if len(t.calls) < len(models) or any(c.get("prompt") and c.get("prompt") not in t.prompts for c in t.calls):
        m.append("every call traced with its prompt")
    add("replay", m)
    return out


@dataclass
class Report:
    turns: int = 0
    files: int = 0
    answered: dict = field(default_factory=lambda: {q: 0 for q in QUESTIONS})
    missing: dict = field(default_factory=lambda: {q: {} for q in QUESTIONS})
    complete: int = 0

    def add(self, answers: list[Answer]) -> None:
        self.turns += 1
        self.complete += all(a.ok for a in answers)
        for a in answers:
            self.answered[a.question] += a.ok
            for item in a.missing:
                key = item.split(" (")[0]
                self.missing[a.question][key] = self.missing[a.question].get(key, 0) + 1

    def to_json(self) -> dict:
        return {"turns": self.turns, "files": self.files, "complete": self.complete,
                "answered": self.answered, "missing": self.missing}


def check(files: list[Path]) -> Report:
    rep = Report()
    for f in files:
        ts = turns(f)
        if ts:
            rep.files += 1
        for t in ts:
            rep.add(answer(t))
    return rep


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "-"


def format_report(rep: Report) -> str:
    lines = [f"Logs audit: {rep.turns} turns in {rep.files} chat records. "
             f"All 8 questions answered: {rep.complete} ({pct(rep.complete, rep.turns)})", ""]
    for i, (q, text) in enumerate(QUESTIONS.items(), 1):
        lines.append(f"{i} {q:<8} {pct(rep.answered[q], rep.turns):>5}  {text}")
        for item, n in sorted(rep.missing[q].items(), key=lambda kv: -kv[1]):
            lines.append(f"             missing in {n}: {item}")
    return "\n".join(lines)


def format_turn(t: Turn) -> str:
    lines = [f"{t.file} turn {t.no}: {str(t.start.get('user') or '')[:100]}"]
    for i, a in enumerate(answer(t), 1):
        lines.append(f"{i} {a.question:<8} {'yes' if a.ok else 'NO '}  " + ("" if a.ok else "missing: " + ", ".join(a.missing)))
    return "\n".join(lines)


def chat_files(paths: list[Path]) -> list[Path]:
    """chat-*.jsonl records under the given files or folders (traces excluded)."""
    out = []
    for p in paths:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [f for f in p.rglob("chat-*.jsonl") if "traces" not in f.parts]
    return sorted(set(out))
