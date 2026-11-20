"""Stage 2.2 (ROADMAP, SPEC_DRIVEN S1-S2): feature specs with acceptance criteria and their checks.

A feature spec is one Markdown file in the project's `specs/` folder, written before any code and approved by you:

    specs/project.md               vision · must-haves · project rules (written once, by you)
    specs/F-001-pdf-export.md      goal · out of scope · criteria AC-n with checks · needs · tasks T1..

Its `## Tasks` part is a runnable plan in the format the step runner and `/run` already read (`### T1:` ... `- Done
when: `<command>``), so a spec runs unchanged. Each task names the criteria it makes true (`- Criteria: AC-1`).
A criterion's check is a command (usually the test the task writes first) or "you check" (looks, wording): those are
asked at the end and never count as verified.

Fail-first (S2, E-151): before a task runs, its check is run; a check that already passes tests nothing about the
task (live 2026-11-19: "add a README link" passed on the old test suite with no link) and sends the spec back.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

SPEC_DIR = "specs"
YOU_CHECK = "you check"
_ID = re.compile(r"^F-(\d{3})-", re.I)
_AC = re.compile(r"^\s*-\s*\**(AC-\d+)\**\s*[:.]?\s*(.+?)\s*(?:·|\||—|--)\s*check:\s*(.+?)\s*$", re.I | re.M)
_NEEDS_PKG = re.compile(r"^##\s*Needs\s*\n(.*?)(?=^##\s|\Z)", re.I | re.M | re.S)

PROJECT_TEMPLATE = """# Project: {name}

## Vision
<one or two lines: what this project is for>

## Must-haves
- <what must always work>

## Rules
- tests: pytest
- no new library without asking
"""


@dataclass
class Criterion:
    id: str
    text: str
    check: str  # a command, or "you check"

    @property
    def by_you(self) -> bool:
        return self.check.strip().lower().startswith(YOU_CHECK)


@dataclass
class Spec:
    feature: str          # "F-001" (empty until saved)
    title: str
    text: str             # the whole spec, as written
    criteria: list[Criterion] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    task_criteria: dict[str, list[str]] = field(default_factory=dict)  # T1 -> [AC-1]


def parse(text: str, feature: str = "") -> Spec:
    title = re.search(r"^#\s*(?:Feature|Spec)\s*(?:F-\d+)?\s*[:\-]?\s*(.+)$", text, re.M | re.I)
    crit = [Criterion(m.group(1).upper(), m.group(2).strip(), m.group(3).strip().strip("`"))
            for m in _AC.finditer(text)]
    needs = _NEEDS_PKG.search(text)
    pkgs: list[str] = []
    if needs:
        for line in needs.group(1).splitlines():
            line = line.strip().lstrip("-* ").strip("`")
            if line and line.lower() not in ("-", "none", "nothing"):
                pkgs.append(re.split(r"[\s(:,]", line, maxsplit=1)[0])
    from app.core.loop import parse_plan
    _, tasks = parse_plan(text)
    tc = {}
    for t in tasks:
        line = re.search(r"Criteria:\s*(.*)", t.body)
        tc[t.id] = [a.upper() for a in re.findall(r"AC-\d+", line.group(1) if line else "", re.I)]
    return Spec(feature=feature, title=(title.group(1).strip() if title else ""), text=text, criteria=crit,
                packages=pkgs, task_criteria=tc)


def check(text: str) -> tuple[Spec, str]:
    """(spec, problem); problem is "" when the spec can be approved and run. The plan rules (plans.check_text)
    plus: 2-7 criteria, each with a check; every criterion with a command is made true by a task; every task
    names its criteria; a task's Done-when is a criterion's check or a test the task writes."""
    from app.core import plans
    from app.core.loop import parse_plan
    spec = parse(text)
    problems = []
    if not spec.criteria:
        problems.append("no acceptance criteria: write `- AC-1: <what is true when done> · check: <command or "
                        "'you check'>` lines under '## Criteria'")
    elif len(spec.criteria) > 7:
        problems.append(f"{len(spec.criteria)} criteria: keep 2-7 (split the feature)")
    n, plan_problem = plans.check_text(text)
    if plan_problem:
        problems.append(plan_problem.rstrip("."))
    _, tasks = parse_plan(text)
    ids = {c.id for c in spec.criteria}
    for t in tasks:
        named = spec.task_criteria.get(t.id) or []
        if not named:
            problems.append(f"{t.id} names no criteria (`- Criteria: AC-1`)")
        elif set(named) - ids:
            problems.append(f"{t.id} names criteria that do not exist: {', '.join(sorted(set(named) - ids))}")
    left = sorted(set(re.findall(r"<(?:one or two sentences|one line|small piece|what [^>]{0,40}|a fact[^>]{0,40}|"
                                 r"another fact|path|name)>", text)))
    if left:  # live 2026-11-20: "<one or two sentences>" copied from the template into every task
        problems.append(f"template placeholders left in: {', '.join(left[:3])}")
    covered = {a for v in spec.task_criteria.values() for a in v}
    open_ = [c.id for c in spec.criteria if not c.by_you and c.id not in covered]
    if open_:
        problems.append(f"no task makes {', '.join(open_)} true")
    return spec, ("; ".join(problems[:6]) + ".") if problems else ""


def spec_dir(root: Path) -> Path:
    return Path(root) / SPEC_DIR


def next_id(root: Path) -> str:
    nums = [int(m.group(1)) for p in spec_dir(root).glob("F-*.md") if (m := _ID.match(p.name))]
    return f"F-{(max(nums) + 1) if nums else 1:03d}"


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "feature").lower()).strip("-")
    return "-".join(s.split("-")[:6]) or "feature"


def save(root: Path, text: str) -> tuple[Path, str]:
    """Write the spec as specs/F-nnn-<slug>.md (the next free number) and specs/project.md if it is missing.
    Returns (path, feature id). The feature id is written into the title line."""
    root = Path(root)
    d = spec_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    project = d / "project.md"
    if not project.exists():
        project.write_text(PROJECT_TEMPLATE.format(name=root.name), encoding="utf-8")
    fid = next_id(root)
    spec = parse(text)
    body = re.sub(r"^#\s*(?:Feature|Spec)\s*(?:F-\d+)?\s*[:\-]?\s*", f"# Feature {fid}: ", text, count=1,
                  flags=re.M | re.I)
    if not body.lstrip().startswith("# Feature"):
        body = f"# Feature {fid}: {spec.title or 'feature'}\n\n{body}"
    if "Status:" not in body:
        body = body.replace("\n", f"\nStatus: approved {time.strftime('%Y-%m-%d')}\n", 1)
    path = d / f"{fid}-{slug(spec.title)}.md"
    path.write_text(body, encoding="utf-8")
    return path, fid


def project_rules(root: Path) -> str:
    """specs/project.md for the planner's context, or ""."""
    p = spec_dir(root) / "project.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    return "" if "<one or two lines" in text and "<what must always work>" in text else text[:2000]


def missing_packages(spec: Spec, package_info) -> list[str]:
    """The spec's `## Needs` packages that are not installed for the project's Python. `package_info(name)` is
    tools.package_info bound to the workspace (its text says "is not installed")."""
    out = []
    for name in spec.packages:
        try:
            info = package_info(name)
        except Exception:  # noqa: BLE001
            info = "is not installed"
        # E-157 (CI 2026-11-20): a project with no Python of its own gets "nothing is installed for it"
        if "not installed" in str(info) or "nothing is installed" in str(info):
            out.append(name)
    return out


def verify(spec: Spec, ws) -> list[dict]:
    """Stage 2.3: every criterion's check, run once after the build: {id, text, check, status, summary};
    status passed | failed | you (yours to judge, never verified here). A later task that broke an earlier
    criterion shows here, not only in the task that made it pass."""
    from app.core import tools as T
    out = []
    for c in spec.criteria:
        if c.by_you:
            out.append({"id": c.id, "text": c.text, "check": YOU_CHECK, "status": "you", "summary": ""})
            continue
        run = T.run_tests(ws, command=c.check)
        out.append({"id": c.id, "text": c.text, "check": c.check, "status": "passed" if run.passed else "failed",
                    "summary": run.summary})
    return out


def verdict_line(results: list[dict], answers: dict | None = None) -> str:
    """'AC-1 ✓ · AC-2 ✗ · AC-3 yours: yes' for the spec's Status line and the end of a build."""
    answers = answers or {}
    marks = []
    for r in results:
        if r["status"] == "you":
            marks.append(f"{r['id']} yours: {answers.get(r['id'], 'open')}")
        else:
            marks.append(f"{r['id']} {'✓' if r['status'] == 'passed' else '✗'}")
    return " · ".join(marks)


def you_check(spec: Spec) -> list[Criterion]:
    return [c for c in spec.criteria if c.by_you]


def listing(root: Path) -> list[tuple[str, str, str]]:
    """(file name, title, status line) of every feature spec, oldest first, for /spec."""
    rows = []
    for p in sorted(spec_dir(root).glob("F-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        t = re.search(r"^#\s*Feature\s*F-\d+\s*:\s*(.+)$", text, re.M)
        s = re.search(r"^Status:\s*(.+)$", text, re.M)
        rows.append((p.name, t.group(1).strip() if t else "", s.group(1).strip() if s else ""))
    return rows


def set_status(path: Path, status: str) -> None:
    """Update the `Status:` line (approved / built / built, 1 task needs help ...)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return
    line = f"Status: {status} ({time.strftime('%Y-%m-%d %H:%M')})"
    text = re.sub(r"^Status:.*$", line, text, count=1, flags=re.M) if re.search(r"^Status:", text, re.M) \
        else text.replace("\n", f"\n{line}\n", 1)
    Path(path).write_text(text, encoding="utf-8")
