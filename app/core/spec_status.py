"""Stage 2.7 (ROADMAP, SPEC_DRIVEN S4): `codemitra status`, where the project's features stand.

Read from what is already on disk, never from the model:

    specs/F-nnn-*.md                     the features, their criteria and their tasks
    .codemitra/runs/criteria.jsonl       every criteria check (after a build, `solve --plan`, `status --check`)
    .codemitra/runs/<run>/T1.jsonl ...   the step runner's task records (their `end` row: status, tokens, time)
    .codemitra/runs/chat-*.jsonl         chat turns; a turn that changed files outside any feature is "unplanned"

Nothing here runs a test except `check_now` (`codemitra status --check`), which runs every feature's criteria once
and records the result, so drift (a criterion that passed before and fails now) shows after later changes too.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core import specs as S

CRITERIA_FILE = "criteria.jsonl"
_FID = re.compile(r"^(F-\d{3})", re.I)


def runs_dir(root: Path) -> Path:
    return Path(root) / ".codemitra" / "runs"


def feature_of(path: Path | str) -> str:
    """'F-001' from 'specs/F-001-pdf-export.md'; '' for a plan that is not a feature spec."""
    m = _FID.match(Path(str(path)).name)
    return m.group(1).upper() if m else ""


def record_criteria(root: Path, spec_name: str, feature: str, results: list[dict], answers: dict | None = None,
                    source: str = "build") -> None:
    """One row per check of a feature's criteria, in the project's runs folder (mirrored to the store)."""
    from app.core.loop import Recorder
    Recorder(runs_dir(root) / CRITERIA_FILE, traces=False).write(
        "criteria", spec=spec_name, feature=feature, source=source,
        results=[{k: r.get(k) for k in ("id", "status", "summary")} for r in results], answers=answers or {})


def _rows(path: Path, kinds: set[str]):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        if '"kind"' not in line or not any(f'"{k}"' in line for k in kinds):
            continue  # cheap skip: records hold big model rows
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") in kinds:
            yield row


@dataclass
class Feature:
    id: str
    title: str
    file: str
    status_line: str
    criteria: list = field(default_factory=list)       # specs.Criterion
    tasks: list[str] = field(default_factory=list)       # T1, T2 ... from the spec
    latest: dict = field(default_factory=dict)           # AC-1 -> passed | failed | you
    answers: dict = field(default_factory=dict)          # AC-3 -> yes | no
    checked_at: float = 0.0
    drift: list[str] = field(default_factory=list)
    task_state: dict = field(default_factory=dict)       # T1 -> first_try | replanned | done | help | env | not_run
    tokens: int = 0
    outside: list[str] = field(default_factory=list)  # E-164: 'T3 u.py:144 settle'
    seconds: float = 0.0

    @property
    def state(self) -> str:
        cmd = [c.id for c in self.criteria if not c.by_you]
        if self.latest and cmd and all(self.latest.get(a) == "passed" for a in cmd) \
                and "no" not in self.answers.values():
            return "done"
        if self.latest or any(v != "not_run" for v in self.task_state.values()):
            return "in progress"
        return "not started"


def _task_states(root: Path) -> dict[str, dict]:
    """feature -> {task_id -> state, '_tokens', '_seconds'} from every step-runner record of the project."""
    out: dict[str, dict] = {}
    runs = runs_dir(root)
    if not runs.is_dir():
        return out
    for run in sorted(p for p in runs.iterdir() if p.is_dir() and p.name not in ("traces", "output")):
        attempts: dict[tuple[str, str], list] = {}   # (feature, T1) -> [(t, status)]
        replans: dict[str, list[str]] = {}           # feature -> statuses of its re-planned (R) tasks in this run
        for rec in sorted(run.glob("*.jsonl")):
            for row in _rows(rec, {"end"}):
                fid = str(row.get("feature") or "")
                if not fid:
                    continue
                f = out.setdefault(fid, {"_tokens": 0, "_seconds": 0.0, "_tries": {}, "_outside": {}})
                f["_tokens"] += int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
                f["_seconds"] += float(row.get("seconds") or 0)
                if str(row.get("status")) == "passed":  # the newest passing run of a task says what it kept
                    f["_outside"][str(row.get("task_id") or rec.stem)] = list(row.get("outside_task") or [])
                tid = str(row.get("task_id") or rec.stem)
                if row.get("replan"):
                    replans.setdefault(fid, []).append(str(row.get("status")))
                else:
                    attempts.setdefault((fid, tid), []).append((row.get("t", 0), str(row.get("status"))))
        for (fid, tid), tries in attempts.items():
            hist = out[fid]["_tries"].setdefault(tid, [])
            hist.extend(s for _, s in sorted(tries))
            rescued = replans.get(fid)
            if hist[-1] != "passed" and rescued and all(s == "passed" for s in rescued):
                hist.append("passed_by_replan")
    for fid, f in out.items():
        f["_outside"] = [f"{t} {x}" for t, xs in sorted(f["_outside"].items()) for x in xs]
        for tid, hist in f.pop("_tries").items():
            last = hist[-1]
            if last == "passed":
                f[tid] = "first_try" if all(h == "passed" for h in hist) else "done"  # a rebuild keeps it
            elif last == "passed_by_replan":
                f[tid] = "replanned"
            elif last == "needs_env":
                f[tid] = "env"
            else:
                f[tid] = "help"
    return out


def _criteria_history(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in _rows(runs_dir(root) / CRITERIA_FILE, {"criteria"}):
        fid = str(row.get("feature") or feature_of(row.get("spec") or ""))
        if fid:
            out.setdefault(fid, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: r.get("t", 0))
    return out


def _unplanned(root: Path) -> tuple[int, int]:
    """(chat turns that changed files outside any feature, all chat turns that changed files)."""
    starts: dict[tuple, str] = {}
    ends: list[tuple] = []
    for rec in sorted(runs_dir(root).glob("chat-*.jsonl")):
        for row in _rows(rec, {"turn_start", "turn_end"}):
            key = (row.get("session_id"), row.get("turn"), rec.name)
            if row["kind"] == "turn_start":
                starts[key] = str(row.get("feature") or "")
            elif row.get("changed"):
                ends.append(key)
    return sum(1 for k in ends if not starts.get(k)), len(ends)


def collect(root: Path) -> dict:
    root = Path(root)
    tasks = _task_states(root)
    hist = _criteria_history(root)
    features = []
    for p in sorted(S.spec_dir(root).glob("F-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fid = feature_of(p)
        spec = S.parse(text, fid)
        from app.core.loop import parse_plan
        _, ptasks = parse_plan(text)
        status = re.search(r"^Status:\s*(.+)$", text, re.M)
        f = Feature(fid, spec.title, p.name, status.group(1).strip() if status else "", spec.criteria,
                    [t.id for t in ptasks])
        rows = hist.get(fid, [])
        seen_pass: set[str] = set()
        for row in rows:
            for r in row.get("results") or []:
                f.latest[r.get("id")] = r.get("status")
                if r.get("status") == "passed":
                    seen_pass.add(r.get("id"))
            f.answers.update(row.get("answers") or {})
            f.checked_at = row.get("t", 0)
        f.drift = [a for a, s in f.latest.items() if s == "failed" and a in seen_pass]
        ts = tasks.get(fid, {})
        f.tokens, f.seconds = ts.get("_tokens", 0), ts.get("_seconds", 0.0)
        f.outside = list(ts.get("_outside") or [])
        f.task_state = {t: ts.get(t, "not_run") for t in f.tasks}
        features.append(f)
    unplanned, changed_turns = _unplanned(root)
    return {"root": root, "features": features, "unplanned": unplanned, "changed_turns": changed_turns}


def _tok(n: int) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}K" if n >= 1e3 else str(n)


def _hours(s: float) -> str:
    return f"{s / 3600:.1f} h" if s >= 3600 else f"{s / 60:.0f} min"


def render(data: dict) -> str:
    feats: list[Feature] = data["features"]
    root: Path = data["root"]
    head = f"{root.name} · specs/ · {time.strftime('%d %b %H:%M')}"
    if not feats:
        return (f"{head}\nNo feature specs yet. Ask for a feature in the chat (or `/spec`): CodeMitra drafts its "
                "spec, you approve it, then it builds it.")
    states = [f.state for f in feats]
    crit = [(f, c) for f in feats for c in f.criteria]

    def cstate(f: Feature, c) -> str:
        return "you" if c.by_you else f.latest.get(c.id, "unchecked")
    cs = [cstate(f, c) for f, c in crit]
    ts = [s for f in feats for s in f.task_state.values()]
    done = sum(s in ("first_try", "done", "replanned") for s in ts)
    drift = [f"{f.id} {a}" for f in feats for a in f.drift]
    lines = [head,
             f"Features  {len(feats):>3}   ✓ done {states.count('done')} · ◐ in progress {states.count('in progress')}"
             f" · ○ not started {states.count('not started')}",
             f"Criteria  {len(crit):>3}   ✓ passing {cs.count('passed')} · ✗ failing {cs.count('failed')} · "
             f"you check {cs.count('you')}" + (f" · not checked yet {cs.count('unchecked')}" if 'unchecked' in cs else ""),
             f"Tasks     {len(ts):>3}   ✓ done {done} (first try {ts.count('first_try')} · re-planned "
             f"{ts.count('replanned')}) · needs help {ts.count('help')}"
             + (f" · waiting for an install {ts.count('env')}" if "env" in ts else "")
             + f" · not run {ts.count('not_run')}",
             f"Drift     {len(drift):>3}   " + (", ".join(drift) + " passed before and fail now" if drift
                                                 else "no criterion that passed before fails now"),
             *([f"Outside   {sum(len(f.outside) for f in feats):>3}   existing code changed outside its task: "
                + "; ".join(f"{f.id} {x}" for f in feats for x in f.outside[:3])] if any(f.outside for f in feats) else []),
             f"Unplanned {data['unplanned']:>3}   chat turns that changed files outside any feature"
             f" (of {data['changed_turns']} that changed files)",
             f"Cost            {_tok(sum(f.tokens for f in feats))} tokens · "
             f"{_hours(sum(f.seconds for f in feats))} CodeMitra time on planned builds",
             ""]
    mark = {"done": "✓ done", "in progress": "◐ in progress", "not started": "○ not started"}
    width = min(36, max(len(f.title) for f in feats))
    for f in feats:
        marks = []
        for c in f.criteria:
            s = cstate(f, c)
            if s == "you":
                marks.append(f"{c.id} yours: {f.answers.get(c.id, 'open')}")
            else:
                marks.append(f"{c.id} {'✓' if s == 'passed' else '✗' if s == 'failed' else '·'}"
                             + (" (drift)" if c.id in f.drift else ""))
        when = time.strftime(" · checked %d %b %H:%M", time.localtime(f.checked_at)) if f.checked_at else ""
        lines.append(f"{f.id} {f.title[:width]:<{width}}  {mark[f.state]:<14} {' · '.join(marks)}{when}")
        if f.status_line.lower().startswith("waiting"):
            lines.append(f"      {f.status_line}")
    if any(s == "unchecked" for s in cs):
        lines.append("\n`codemitra status --check` runs every criterion's check now (no model) and records it.")
    return "\n".join(lines)


def active_plan(root: Path | str, limit: int = 6000) -> str:
    """The plan to put back word for word after the chat compacts (Mingbird re-injects it; our summary used to be
    the 9B's paraphrase): the newest feature spec that is not built yet, and `.codemitra/resume.md` (what the last
    build did). "" when neither exists."""
    root = Path(root)
    open_specs = []
    for p in S.spec_dir(root).glob("F-*.md"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        status = re.search(r"^Status:\s*(.+)$", text, re.M)
        if not (status and status.group(1).lower().startswith("built")):
            open_specs.append((p.stat().st_mtime, p, text))
    parts = []
    if open_specs:
        _, p, text = max(open_specs, key=lambda x: x[0])
        parts.append(f"[The active feature spec, word for word: specs/{p.name}]\n\n{text[:limit]}")
    try:
        resume = (root / ".codemitra" / "resume.md").read_text(encoding="utf-8")
    except OSError:
        resume = ""
    if resume.strip():
        parts.append(f"[Where the last build stopped: .codemitra/resume.md]\n\n{resume[:2000]}")
    return "\n\n".join(parts)


def check_now(root: Path, on_feature=None) -> int:
    """Run every feature's criteria checks once (no model) and record them; returns how many features ran."""
    from app.core import tools as T
    root = Path(root)
    ws = T.Workspace(root)
    n = 0
    for p in sorted(S.spec_dir(root).glob("F-*.md")):
        try:
            spec = S.parse(p.read_text(encoding="utf-8"), feature_of(p))
        except OSError:
            continue
        if not any(not c.by_you for c in spec.criteria):
            continue
        if on_feature:
            on_feature(spec.feature, spec.title)
        record_criteria(root, p.name, spec.feature, S.verify(spec, ws), source="status --check")
        n += 1
    return n
