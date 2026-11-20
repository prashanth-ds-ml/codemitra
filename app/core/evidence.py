"""Stage 2.6 (ROADMAP): the evidence report at the end of a change, written by CodeMitra from the turn's records,
not by the model (CTXGAP and the false-success studies: a report the model writes is where "done" gets invented).

    Changed:      src/trip_splitter/utils.py:74-99 (+26 -0) · new tests/test_ac1.py · made by a command: report.pdf
    Ran:          tests (python -m pytest -q tests/test_ac1.py): 3 passed · python make_report.py: ok
    Not checked:  README.md has no test: look at it yourself · "all tests pass" was not backed by a run

Pure functions over the Stage 1 rows: `change` rows (diff, via), the turn's tool calls, the claim verdicts.
"""
from __future__ import annotations

import re

MAX_FILES = 6
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)
CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".cs", ".rb", ".php")


def line_ranges(diff: str) -> str:
    """'48-72, 120' : the new file's lines that were added or changed (context lines left out: live 2026-11-20 the
    hunk ranges said 51-76 for a docstring at 48-72)."""
    lines: list[int] = []
    new_no = 0
    for line in (diff or "").splitlines():
        m = _HUNK.match(line)
        if m:
            new_no = int(m.group(1))
            continue
        if not new_no or line.startswith(("+++", "---")):
            continue
        if line.startswith("+"):
            lines.append(new_no)
            new_no += 1
        elif line.startswith("-"):
            continue  # removed: no line in the new file
        else:
            new_no += 1
    ranges: list[str] = []
    for n in lines:
        if ranges and n == int(ranges[-1].split("-")[-1]) + 1:
            ranges[-1] = f"{ranges[-1].split('-')[0]}-{n}"
        else:
            ranges.append(str(n))
    return ", ".join(ranges[:4]) + (" …" if len(ranges) > 4 else "")


def counts(diff: str) -> tuple[int, int]:
    plus = sum(1 for line in (diff or "").splitlines() if line.startswith("+") and not line.startswith("+++"))
    minus = sum(1 for line in (diff or "").splitlines() if line.startswith("-") and not line.startswith("---"))
    return plus, minus


def _is_test(rel: str) -> bool:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in "/" + rel.replace("\\", "/")


def changed_line(rows: list[dict]) -> str:
    parts, made = [], []
    for r in rows[:MAX_FILES]:
        rel = r.get("rel") or r.get("path", "")
        if r.get("via") == "command":
            made.append(rel)
            continue
        if r.get("created"):
            plus, _ = counts(r.get("diff", ""))
            parts.append(f"new `{rel}` ({plus} lines)")
            continue
        plus, minus = counts(r.get("diff", ""))
        where = line_ranges(r.get("diff", ""))
        parts.append(f"`{rel}{':' + where if where else ''}` (+{plus} -{minus})")
    if made:
        parts.append("made by a command: " + ", ".join(f"`{m}`" for m in made))
    if len(rows) > MAX_FILES:
        parts.append(f"… and {len(rows) - MAX_FILES} more")
    return " · ".join(parts)


def ran_line(tools: list[tuple[str, bool, str]], args_of: list[dict] | None = None) -> str:
    """The tests and commands of the turn, the last result of each distinct one."""
    seen: dict[str, str] = {}
    for i, (name, ok, out) in enumerate(tools):
        if name not in ("run_tests", "run_command"):
            continue
        a = (args_of[i] if args_of and i < len(args_of) else {}) or {}
        label = "tests" if name == "run_tests" else f"`{str(a.get('command', 'a command'))[:60]}`"
        if name == "run_tests" and (a.get("path") or a.get("folder")):
            label = f"tests ({a.get('path') or a.get('folder')})"
        first = (out or "").strip().splitlines()[0][:90] if (out or "").strip() else ""
        result = _summary(first, out) if name == "run_tests" else ("ok" if ok else f"failed: {first}")
        seen[label] = result
    return " · ".join(f"{k}: {v}" for k, v in seen.items())


def _summary(first: str, out: str) -> str:
    m = re.search(r"\d+ (?:failed|passed)[^\n]*?in [\d.]+s", out or "")
    return m.group(0) if m else first


def not_checked(rows: list[dict], tools: list[tuple[str, bool, str]], claims: list[dict], *,
                has_tests: bool = True, ran_after_last_change: bool = True) -> list[str]:
    out = []
    changed = [r for r in rows if r.get("via") != "command"]
    if changed and not ran_after_last_change:
        out.append("nothing ran after the last change")
    tests = [(ok, o) for n, ok, o in tools if n == "run_tests"]
    if tests and not tests[-1][0]:
        names = re.findall(r"FAILED\s+\S*?::(\w+)", tests[-1][1] or "")
        out.append("the last test run failed" + (f" ({', '.join(dict.fromkeys(names[:3]))})" if names else ""))
    if changed and not has_tests:
        out.append("this project has no tests: the change is untested")
    elif changed and not tests and ran_after_last_change:
        out.append("no tests ran this turn")
    plain = [r.get("rel", "") for r in changed if not str(r.get("rel", "")).lower().endswith(CODE_EXT)
             and not _is_test(str(r.get("rel", "")))]
    if plain:
        out.append(", ".join(f"`{p}`" for p in plain[:3]) + " has no test: look at it yourself")
    for c in claims or []:
        if c.get("verdict") == "false":
            out.append(f"\"{c.get('text', '')[:80]}\" is not true by this turn's results")
        elif c.get("verdict") == "unchecked":
            out.append(f"\"{c.get('text', '')[:80]}\" was not checked")
    return out[:5]


def report(rows: list[dict], tools: list[tuple[str, bool, str]], claims: list[dict], *, args_of=None,
           has_tests: bool = True, ran_after_last_change: bool = True) -> str:
    """The Markdown block for the end of a change turn ("" when nothing changed and nothing ran)."""
    if not rows and not any(n in ("run_tests", "run_command") for n, _, _ in tools):
        return ""
    lines = ["**Evidence** (from CodeMitra's records, not the model)"]
    ch = changed_line(rows)
    if ch:
        lines.append(f"- Changed: {ch}")
    ran = ran_line(tools, args_of)
    lines.append(f"- Ran: {ran}" if ran else "- Ran: nothing")
    gaps = not_checked(rows, tools, claims, has_tests=has_tests, ran_after_last_change=ran_after_last_change)
    lines.append("- Not checked: " + ("; ".join(gaps) if gaps else "nothing left open that CodeMitra can see"))
    return "\n".join(lines)
