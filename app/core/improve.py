"""`codemitra improve` (self-improvement step 3): a local model proposes one harness change for the top problem in the
run records; the benchmark's tune half decides whether it stays.

    propose  -> the proposer model (local, default the 9B) gets the top patterns + the current harness and answers with
                one change as JSON: a rule, a tool text, or a limit
    evaluate -> the builder model solves every tune task with the current harness and with the candidate; grading
                uses the hidden tests (bench/bench.py grade)
    decide   -> keep only if more tasks pass and the prompt tokens grow at most 20%; every attempt is logged in
                ~/.codemitra/harness/attempts.jsonl, a kept change becomes the next harness version (revertable)

Local models only (D-025); nothing from Claude goes into the harness (D-022). The held-out half is never used here.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.core import analyze as A
from app.core import harness as H
from app.core import tools as T
from app.core.loop import solve

CODEMITRA_ROOT = Path(__file__).resolve().parents[2]
MAX_COST_GROWTH = 1.2
PROPOSE_TIMEOUT_S = 600

PROPOSER_PROMPT = """You improve a small local coding assistant by changing its settings, never its code.
You get the problems found in its recorded runs and its current settings. Propose ONE change that would most likely
stop the top problem. Answer with JSON only, one of:
{"kind": "rule", "text": "<one short instruction for the assistant, under 200 characters>", "why": "<one line>"}
{"kind": "tool", "name": "<tool name>", "text": "<new description of that tool>", "why": "<one line>"}
{"kind": "limit", "name": "<limit name>", "value": <integer>, "why": "<one line>"}
A rule must be general (no file names from the examples) and must not repeat an existing rule.
Read the examples for the cause: retrying never fixes a refused command or a missing package or program."""


class BenchError(RuntimeError):
    """The benchmark itself broke (not the model): the A/B result would mean nothing."""


BENCH_PACKAGES = ("pytest", "fastapi", "httpx")  # what bench/base imports (pydantic comes with fastapi)
_BENCH_CHECK = "import pytest, fastapi, httpx, fastapi.testclient"


def bench_python(say=print, run=None) -> str:
    """A Python that has the benchmark's packages (E-132, issue #12: grading ran in CodeMitra's own Python, which has
    no fastapi, so every grade broke). The first that works: CodeMitra's own, then ~/.codemitra/bench-env (made once
    with uv). Raises BenchError, saying what to do, when none can be made."""
    import subprocess
    run = run or (lambda args, timeout: subprocess.run(args, capture_output=True, text=True, timeout=timeout))
    venv = H.home() / "bench-env"
    own = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    def works(py) -> bool:
        try:
            return run([str(py), "-c", _BENCH_CHECK], 60).returncode == 0
        except Exception:
            return False
    for py in (sys.executable, own):
        if Path(py).exists() and works(py):
            return str(py)
    uv = shutil.which("uv")
    if not uv:
        raise BenchError("the benchmark needs a Python with " + ", ".join(BENCH_PACKAGES) + " and uv is not "
                         "installed to make one: run the setup script again (it installs uv)")
    say("Preparing the benchmark's own Python (once, about a minute): " + ", ".join(BENCH_PACKAGES))
    try:
        run([uv, "venv", "--python", "3.12", str(venv)], 300)
        run([uv, "pip", "install", "--python", str(own), *BENCH_PACKAGES], 600)
    except Exception as exc:
        raise BenchError(f"could not make the benchmark's Python: {exc}") from exc
    if not works(own):
        raise BenchError("the benchmark's Python was made but cannot import " + ", ".join(BENCH_PACKAGES)
                         + f" (offline?): {own}")
    return str(own)


@dataclass
class Change:
    kind: str
    why: str = ""
    text: str = ""
    name: str = ""
    value: int = 0

    def describe(self) -> str:
        if self.kind == "rule":
            return f"rule: {self.text}"
        if self.kind == "tool":
            return f"tool {self.name}: {self.text}"
        return f"limit {self.name} = {self.value}"

    def apply(self, h: H.Harness) -> H.Harness:
        new = h.copy()
        if self.kind == "rule":
            new.rules = (new.rules + [self.text])[-H.MAX_RULES:]
        elif self.kind == "tool":  # the newest MAX_TOOL_TEXTS are kept (E-106: the prompt budget)
            tools = {k: v for k, v in new.tools.items() if k != self.name}
            new.tools = dict(list({**tools, self.name: self.text}.items())[-H.MAX_TOOL_TEXTS:])
        else:
            new.limits = {**new.limits, self.name: self.value}
        return new


@dataclass
class Score:
    passed: int = 0
    total: int = 0
    tokens_in: int = 0
    seconds: float = 0.0
    tasks: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"passed": self.passed, "total": self.total, "tokens_in": self.tokens_in,
                "seconds": round(self.seconds), "tasks": self.tasks}


def parse_change(text: str, h: H.Harness, tool_names: set[str]) -> tuple[Change | None, str]:
    """The proposer's JSON -> a valid Change, or (None, why not)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None, "no JSON in the answer"
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return None, f"bad JSON: {exc}"
    kind, why = str(d.get("kind", "")), str(d.get("why", ""))[:200]
    if kind == "rule":
        rule = " ".join(str(d.get("text", "")).split())
        if not rule or len(rule) > H.MAX_RULE_CHARS:
            return None, "rule empty or too long"
        if rule.lower() in {r.lower() for r in h.rules}:
            return None, "rule already exists"
        return Change("rule", why, text=rule), ""
    if kind == "tool":
        name, desc = str(d.get("name", "")), " ".join(str(d.get("text", "")).split())
        if name not in tool_names:
            return None, f"unknown tool {name!r}"
        if not desc or len(desc) > H.MAX_TOOL_CHARS:
            return None, "tool text empty or too long"
        return Change("tool", why, text=desc, name=name), ""
    if kind == "limit":
        name = str(d.get("name", ""))
        if name not in H.DEFAULT_LIMITS:
            return None, f"unknown limit {name!r}"
        try:
            value = int(d.get("value"))
        except (TypeError, ValueError):
            return None, "limit value is not a number"
        if not 1 <= value <= 200 or value == h.limit(name):
            return None, "limit value out of range or unchanged"
        return Change("limit", why, name=name, value=value), ""
    return None, f"unknown kind {kind!r}"


def fixable(rep: A.Report, n: int = 5) -> list:
    """The top patterns a settings change can fix (E-132: never the machine's own errors)."""
    return [p for p in rep.top(n + len(A.NOT_FIXABLE)) if p.name not in A.NOT_FIXABLE][:n]


def propose(rep: A.Report, h: H.Harness, llm, tool_names: set[str], tries: int = 2) -> tuple[Change | None, str]:
    patterns = "\n".join(
        f"- {p.count}x {p.name}: {A.PATTERNS.get(p.name, '')}\n" + "".join(f"    e.g. {e}\n" for e in p.examples[:3])
        for p in fixable(rep))
    settings = H.to_toml(h)
    user = (f"Problems found in {rep.units} recorded turns/tasks (most frequent first):\n{patterns}\n"
            f"Current settings:\n{settings}\nTools: {', '.join(sorted(tool_names))}\n"
            f"Limits you may change: {', '.join(H.DEFAULT_LIMITS)}")
    messages = [SystemMessage(content=PROPOSER_PROMPT), HumanMessage(content=user)]
    why = "no answer"
    for _ in range(tries):
        reply = llm.invoke(messages)
        change, why = parse_change(str(reply.content), h, tool_names)
        if change:
            return change, ""
        messages += [reply, HumanMessage(content=f"That was not usable ({why}). Answer with one valid JSON object.")]
    return None, why


def unload(llm) -> None:
    """Free the proposer's memory before the builder loads (one model at a time on this machine)."""
    import urllib.request

    base = (getattr(llm, "base_url", None) or "http://localhost:11434").rstrip("/")
    body = json.dumps({"model": getattr(llm, "model", ""), "keep_alive": 0}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{base}/api/generate", data=body,
                                                      headers={"Content-Type": "application/json"}), timeout=60)
    except OSError:
        pass


HEADROOM_GB = 3.0  # as bench/preflight.py: Ollama maps the model file into RAM on Windows, plus buffers (L-008)


def machine_problems(models: list[str], *, sizes: dict[str, float], loaded: list[str], free_gb: float) -> list[str]:
    """What blocks running these models one at a time: not installed, or not enough free RAM for the biggest."""
    problems = [f"{m} is not installed (ollama pull {m})" for m in models if m not in sizes]
    need = max([sizes[m] for m in models if m in sizes and m not in loaded] or [0.0])
    if need and free_gb < need + HEADROOM_GB:
        problems.append(f"free RAM {free_gb:.1f} GB < {need + HEADROOM_GB:.1f} GB needed; close heavy apps, "
                        "or use the 4B as proposer (--proposer qwen3.5:4b)")
    return problems


def load_bench():
    spec = importlib.util.spec_from_file_location("mitra_bench", CODEMITRA_ROOT / "bench" / "bench.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses in bench.py look their module up here
    spec.loader.exec_module(mod)
    return mod


def evaluate(h: H.Harness, llm, *, tasks=None, bench=None, num_ctx: int = 131072, max_steps: int | None = None,
             record_root: Path | None = None, on_task=None) -> Score:
    """Solve each tune task with harness `h`; the bench's hidden tests grade it."""
    bench = bench or load_bench()
    tasks = tasks if tasks is not None else [t for t in bench.load_tasks() if t.split == "tune"]
    score = Score(total=len(tasks))
    py = bench_python() if tasks else None  # E-132: the model's test runs and the grading use the same Python
    for task in tasks:
        tmp = Path(tempfile.mkdtemp(prefix=f"codemitra-improve-{task.id}-"))
        try:
            ws_dir = tmp / "ws"
            bench.prepare(task, ws_dir)
            ws = T.Workspace(ws_dir, test_command="python -m pytest -q", python=py)
            rec = (record_root / f"{task.id}.jsonl") if record_root else None
            res = solve(task.prompt.strip(), ws, llm, harness=h, num_ctx=num_ctx, max_steps=max_steps,
                        record_path=rec)
            if res.status == "error":  # the model call failed (Ollama down, timeout): not the harness's fault
                raise BenchError(f"{task.id}: {res.summary}")
            g = bench.grade(task, ws_dir, python=py)  # the same Python the model's tests ran with (E-132)
            if getattr(g, "infra_error", None):
                raise BenchError(f"grading {task.id} broke ({g.infra_error}): {g.output_tail[-300:]}")
            score.passed += int(g.passed)
            score.tokens_in += res.tokens_in
            score.seconds += res.seconds
            score.tasks[task.id] = {"passed": g.passed, "status": res.status, "steps": res.steps,
                                    "tokens_in": res.tokens_in,
                                    "failed": "" if g.passed else _failed_tests(getattr(g, "output_tail", ""))}
            if on_task:
                on_task(task.id, g.passed, res)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return score


def _failed_tests(tail: str) -> str:
    """The FAILED lines of a pytest run (which hidden tests the change missed)."""
    lines = [ln.strip() for ln in str(tail).splitlines() if ln.startswith(("FAILED", "ERROR"))]
    return "; ".join(lines)[:400]


def decide(base: Score, cand: Score) -> tuple[bool, str]:
    if cand.passed > base.passed and cand.tokens_in <= base.tokens_in * MAX_COST_GROWTH:
        return True, f"{cand.passed}/{cand.total} passed (was {base.passed}/{base.total})"
    if cand.passed > base.passed:
        return False, (f"more passed ({cand.passed} vs {base.passed}) but prompt tokens grew "
                       f"{cand.tokens_in / max(base.tokens_in, 1):.0%} of before")
    return False, f"{cand.passed}/{cand.total} passed, not more than {base.passed}/{base.total}"


def log_attempt(entry: dict) -> Path:
    path = H.home() / "harness" / "attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return path


def attempts() -> list[dict]:
    path = H.home() / "harness" / "attempts.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def improve(rep: A.Report, *, proposer, builder, builder_name: str = "", proposer_name: str = "",
            dry_run: bool = False, tasks=None, bench=None, num_ctx: int = 131072, max_steps: int | None = None,
            say=print) -> dict:
    """One round: propose -> A/B on the tune half -> keep or drop. Returns the logged entry."""
    current = H.load()
    tool_names = {s["name"] for s in T.TOOL_SPECS}
    top = fixable(rep, 1)
    entry = {"date": time.strftime("%Y-%m-%d %H:%M"), "harness_version": current.version, "builder": builder_name,
             "proposer": proposer_name, "top_pattern": top[0].name if top else ""}
    env = rep.patterns.get("environment") if isinstance(rep.patterns, dict) else None
    if env:  # E-132: said, never "fixed" by a rule
        say(f"Machine problems seen {env.count}x (a refused program, a missing package or interpreter); a rule cannot "
            f"fix these, they need setup or a code fix: " + "; ".join(env.examples[:3]))
    if not top:
        entry.update(result="skipped", reason="no problems a settings change can fix in the run records")
        say("No problems a settings change can fix in the run records: nothing to improve yet.")
        return entry
    say(f"Top problem: {entry['top_pattern']} ({top[0].count}x). Asking {proposer_name or 'the proposer'}...")
    try:
        change, why = propose(rep, current, proposer, tool_names)
    finally:
        if proposer is not builder:
            unload(proposer)
    if not change:
        entry.update(result="no_proposal", reason=why)
        log_attempt(entry)
        say(f"No usable proposal: {why}")
        return entry
    entry["change"] = change.describe()
    entry["why"] = change.why
    say(f"Proposal: {change.describe()}\n  why: {change.why}")
    if dry_run:
        entry.update(result="dry_run")
        return entry
    bench = bench or load_bench()
    runs = H.home() / "harness" / "runs" / time.strftime("%Y%m%d-%H%M%S")

    def on_task(label):
        return lambda tid, ok, res: say(f"  {label} {tid}: {'pass' if ok else 'fail'} · {res.steps} steps · "
                                        f"{res.tokens_in:,} tokens")

    cand_h = change.apply(current)
    cand_run = cand_h.copy()
    cand_run.version = current.version + 1  # its records count as the next version if it is kept
    try:
        say("Benchmark with the current settings:")
        base = evaluate(current, builder, tasks=tasks, bench=bench, num_ctx=num_ctx, max_steps=max_steps,
                        record_root=runs / "base", on_task=on_task("current"))
        say("Benchmark with the proposal:")
        cand = evaluate(cand_run, builder, tasks=tasks, bench=bench, num_ctx=num_ctx, max_steps=max_steps,
                        record_root=runs / "candidate", on_task=on_task("proposal"))
    except BenchError as exc:
        entry.update(result="bench_error", reason=str(exc)[:500])
        log_attempt(entry)
        say(f"Benchmark broke, nothing changed: {exc}")
        return entry
    keep, reason = decide(base, cand)
    entry.update(base=base.to_json(), candidate=cand.to_json(), result="kept" if keep else "dropped", reason=reason,
                 records=str(runs))
    if keep:
        H.save(cand_h, f"{change.describe()} ({reason}; top problem {entry['top_pattern']})")
        entry["new_version"] = current.version + 1
    log_attempt(entry)
    say(f"{'Kept' if keep else 'Dropped'}: {reason}")
    return entry
