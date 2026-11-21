"""Stage 2.4 (ROADMAP): one finish gate, the checks a turn or a task must pass before "done" is accepted.

Ported from Mingbird's finish gate (Apache-2.0, references/Mingbird-agent ollama_agent.py 4804-4995, see
docs/MINGBIRD_REFERENCE.md): checks in a fixed order, each refusal at most once, every refusal names the NEXT action,
questions exempt. CodeMitra's own end-of-turn checks (E-133, E-143, E-144, E-145) are steps of the same gate.

    1 no_work          a change was asked; nothing was written or run, but the answer says done / will / cannot
    2 script_not_run   a script written for a requested file was not run after the last change (E-145)
    3 environment      the last run failed because a library is not installed: the setup, not the code (E-152)
    4 tests_failed     the last test run failed and the answer claims done / passing
    5 missing_output   a file the answer names does not exist (E-144)
    6 broken_json      a .json file the turn wrote does not parse
    7 recheck          once, for a long request: the request again, "check every requirement"

The pure helpers live here; the chat (`ChatSession._finish_gate`) and the step runner (`loop.solve`) call them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ORDER = ("no_work", "script_not_run", "environment", "tests_failed", "missing_output", "broken_json", "recheck")
MAX_REFUSALS = 3            # per turn: the gate never deadlocks (Mingbird caps each check at 2-3)
RECHECK_MIN_WORDS = 40      # a request this long, or with 3+ lines, gets the one re-read
_NO_MODULE = re.compile(r"No module named ['\"]([A-Za-z0-9_][A-Za-z0-9_.]*)['\"]")

ENV_NOTE = ("[CodeMitra: the last run failed because `{module}` is not installed for this project's Python. That is the "
            "setup, not your code: do not rewrite or retry the code for it. Next: run `python -m pip install {module}` "
            "with run_command (the user approves it), then run the tests again; or, if you should not install, tell "
            "the user plainly that `{module}` must be installed and stop.]")
TESTS_FAILED_NOTE = ("[CodeMitra: your answer says it is done or passing, but the last test run failed ({summary}). Next: "
                     "fix the cause and run the tests again; or, if you cannot, tell the user plainly what still fails. "
                     "Do not say it is done.]")
JSON_NOTE = ("[CodeMitra: {files} is not valid JSON ({error}). Next: write it again from a short Python script with "
             "json.dump (then run the script), not by hand, and check it loads.]")
RECHECK_NOTE = ("[CodeMitra: before you finish, here is the request again:\n\n{request}\n\nCheck every requirement in it "
                "(names, files, formats, numbers, wording). If one is missing, do it now with the tools; if all are "
                "done, give your answer.]")


_FRAME = re.compile(r"(?:File \"([^\"]+\.py)\"|^([^\s:][^:\n]*\.py):\d+: in )", re.M)


def missing_module(output: str, root: Path | None = None, declared: str = "") -> str:
    """The library a run could not import ("No module named 'fpdf'" -> "fpdf"), or "" when it is not the setup:
    - the project's own code (trip_splitter, src/trip_splitter): a path problem, not an install;
    - code the task has not written yet (tests import `calc` before calc.py exists): the work, not the setup.
    It is the setup when the library is declared (requirements*.txt, pyproject.toml, or `declared`: the spec's
    Needs), or when the failing import is in the project's own source code rather than only in a test."""
    m = None
    for m in _NO_MODULE.finditer(output or ""):
        pass  # the last one: the import that finally failed
    if not m:
        return ""
    top = m.group(1).split(".")[0]
    if root is None:
        return top
    r = Path(root)
    local = [r / f"{top}.py", r / top, r / "src" / top, r / "src" / f"{top}.py"]
    if any(p.exists() for p in local):
        return ""
    deps = declared
    for name in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.cfg"):
        try:
            deps += "\n" + (r / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    if re.search(rf"(?<![\w-]){re.escape(top)}", deps, re.I):
        return top
    frames = [a or b for a, b in _FRAME.findall(output or "")]
    for f in frames:
        name = Path(f).name
        if name.endswith(".py") and not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"):
            if "site-packages" not in f.replace("\\", "/"):
                return top  # the project's own code imports it: a library to install
    return ""


_LIB_PHRASE = re.compile(r"\b([A-Za-z][\w.-]*)\s+(?:library|package|module)\b|\b(?:pip install|install)\s+([A-Za-z][\w.-]*)",
                         re.I)
_NEEDS = re.compile(r"^##\s*Needs\s*\n(.*?)(?=^##\s|^###\s|\Z)", re.I | re.M | re.S)


def declared_libraries(text: str) -> str:
    """The libraries a request or task names as libraries ("with the fpdf library", "pip install x") and a spec's
    `## Needs` list, as one line: what missing_module may treat as declared. Not every word of the text."""
    names = [a or b for a, b in _LIB_PHRASE.findall(text or "")]
    for block in _NEEDS.findall(text or ""):
        names += [re.split(r"[\s(:,]", line.strip().lstrip("-* ").strip("`"), maxsplit=1)[0]
                  for line in block.splitlines() if line.strip().lstrip("-* ")]
    return " ".join(n for n in names if n and n.lower() not in ("the", "a", "this", "that", "python", "none", "-"))


def broken_json(journal: list[dict], root: Path) -> list[tuple[str, str]]:
    """(relative path, error) for each .json file the turn wrote that does not parse (its last content)."""
    last: dict[str, str] = {}
    for e in journal or []:
        p = str(e.get("path", ""))
        if p.lower().endswith(".json") and e.get("after") is not None:
            last[p] = e["after"]
    out = []
    for p, text in last.items():
        try:
            json.loads(text)
        except ValueError as exc:
            try:
                rel = Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
            except (ValueError, OSError):
                rel = Path(p).name
            out.append((rel, str(exc)[:120]))
    return out


def wants_recheck(request: str) -> bool:
    words = len((request or "").split())
    lines = sum(1 for line in (request or "").splitlines() if line.strip())
    return words >= RECHECK_MIN_WORDS or lines >= 3


def env_note(module: str) -> str:
    return ENV_NOTE.format(module=module)


def tests_failed_note(summary: str) -> str:
    return TESTS_FAILED_NOTE.format(summary=(summary or "failed")[:160])


def json_note(bad: list[tuple[str, str]]) -> str:
    return JSON_NOTE.format(files=", ".join(f"`{p}`" for p, _ in bad[:3]), error=bad[0][1] if bad else "")


def recheck_note(request: str) -> str:
    return RECHECK_NOTE.format(request=(request or "").strip()[:2000])


# ── 8 outside_task (step runner): an existing function the task does not name was changed (E-164) ─────────────
# Live 2026-11-21: T3 (a CLI command) also "fixed" optimize_settlements, which it did not name; every check stayed
# green and the settlements came out wrong (C paid 15 of the 10 it owed). Refused once per task; then it is listed.

SCOPE_NOTE = ("[CodeMitra: the tests pass, but you also changed {names}, which your task does not name. Changing "
              "existing code outside the task can break what worked, and no test of this task checks it. Next: undo "
              "those changes with edit_file unless the task really needs them; if it does, say why in one line, then "
              "run_tests again.]")


def _functions(source: str) -> dict[str, tuple[str, int]]:
    """qualified name -> (its source, its first line) for every function and method of a Python file."""
    import ast
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    out: dict[str, tuple[str, int]] = {}

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    out[name] = (ast.get_source_segment(source, child) or "", child.lineno)
                walk(child, name + ".")
    walk(tree)
    return out


def outside_task(journal: list[dict], root: Path, task_text: str) -> list[tuple[str, str, int]]:
    """(path, function, line) of every function that existed before the task and changed, unless the task names it
    and its file is in the task's `- Files:` line (when it has one). Only the task's own text counts, not the plan's
    shared notes (they name everything). Test files are the task's own; new functions are fine."""
    files_line = re.search(r"^\s*-\s*Files:\s*(.+)$", task_text or "", re.M)
    listed = {f.strip().strip("`").replace("\\", "/") for f in files_line.group(1).split(",")} if files_line else set()
    first: dict[str, str | None] = {}
    last: dict[str, str] = {}
    for e in journal or []:
        p = str(e.get("path") or "")
        if not p.endswith(".py") or e.get("kind") != "create_file":
            continue
        first.setdefault(p, e.get("before") if e.get("existed") else None)
        last[p] = e.get("after") or ""
    out = []
    for p, before in first.items():
        try:
            rel = Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            rel = Path(p).name
        if before is None or rel.startswith("tests/") or Path(rel).name.startswith("test_"):
            continue
        old, new = _functions(before), _functions(last[p])
        for name, (src, _) in old.items():
            if name not in new or " ".join(new[name][0].split()) == " ".join(src.split()):
                continue
            if (not listed or rel in listed) and \
                    re.search(rf"\b{re.escape(name.split('.')[-1])}\b", task_text or ""):
                continue  # live T3 said "using optimize_settlements": named, but not its file, so still outside
            out.append((rel, name, new[name][1]))
    return out


def scope_note(items: list[tuple[str, str, int]]) -> str:
    names = ", ".join(f"`{n}` ({p}:{line})" for p, n, line in items[:4])
    return SCOPE_NOTE.format(names=names)
