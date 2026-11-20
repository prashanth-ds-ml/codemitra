"""Stage 2.2: feature specs (criteria with checks, needs, tasks) and fail-first checks (E-151)."""
import json

from langchain_core.messages import AIMessage

from app import main
from app.core import loop as L
from app.core import planner as P
from app.core import specs as S
from app.core import tools as T
from tests.test_backend_chat import Inputs, harness  # noqa: F401 - the driven chat fixture
from tests.test_chat_core import Model, tc

SPEC = """# Feature: README links the how-it-works page

## Goal
Readers find the explanation of balances from the README.

## Out of scope
- rewriting the README

## Criteria
- AC-1: docs/how_it_works.md explains balances · check: `python -m pytest -q tests/test_ac1_docs.py`
- AC-2: README.md links docs/how_it_works.md · check: `python -m pytest -q tests/test_ac2_link.py`
- AC-3: the page reads well · check: you check

## Needs
- none

## Tasks

### T1: the page
- Files: `tests/test_ac1_docs.py`, `docs/how_it_works.md`
- Criteria: AC-1
- Do: first write the test, then the page.
- Done when: `python -m pytest -q tests/test_ac1_docs.py` passes
- Needs: -

### T2: the link
- Files: `tests/test_ac2_link.py`, `README.md`
- Criteria: AC-2
- Do: first write the test that reads README.md, then add the link.
- Done when: `python -m pytest -q tests/test_ac2_link.py` passes
- Needs: T1
"""


def test_a_good_spec_parses_and_checks():
    spec, problem = S.check(SPEC)
    assert problem == "", problem
    assert [c.id for c in spec.criteria] == ["AC-1", "AC-2", "AC-3"]
    assert [c.id for c in S.you_check(spec)] == ["AC-3"]
    assert spec.task_criteria == {"T1": ["AC-1"], "T2": ["AC-2"]} and spec.packages == []
    assert spec.title == "README links the how-it-works page"
    _, tasks = L.parse_plan(SPEC)  # the tasks are a runnable plan, unchanged
    assert [t.test_command for t in tasks] == ["python -m pytest -q tests/test_ac1_docs.py",
                                              "python -m pytest -q tests/test_ac2_link.py"]


def test_spec_problems_are_named():
    _, p = S.check(SPEC.replace("- Criteria: AC-2\n", ""))
    assert "T2 names no criteria" in p and "no task makes AC-2 true" in p
    _, p = S.check(SPEC.split("## Criteria")[0] + SPEC.split("## Needs")[1].join(["## Needs", ""]))
    assert "no acceptance criteria" in p
    _, p = S.check(SPEC.replace("- Criteria: AC-1", "- Criteria: AC-9"))
    assert "AC-9" in p


def test_needs_lists_packages():
    spec = S.parse(SPEC.replace("- none", "- fpdf2 (PDF tables)\n- `reportlab`"))
    assert spec.packages == ["fpdf2", "reportlab"]
    missing = S.missing_packages(spec, lambda n: "fpdf2 2.7" if n == "fpdf2" else f"'{n}' is not installed")
    assert missing == ["reportlab"]


def test_save_numbers_specs_and_writes_project_md(tmp_path):
    p1, f1 = S.save(tmp_path, SPEC)
    p2, f2 = S.save(tmp_path, SPEC)
    assert (f1, f2) == ("F-001", "F-002") and p1.name == "F-001-readme-links-the-how-it-works.md"
    text = p1.read_text(encoding="utf-8")
    assert text.startswith("# Feature F-001: README links") and "Status: approved" in text
    assert (tmp_path / "specs" / "project.md").is_file()
    assert S.project_rules(tmp_path) == ""  # the untouched template is not sent to the planner


def test_listing_and_status(tmp_path):
    p1, _ = S.save(tmp_path, SPEC)
    S.save(tmp_path, SPEC)
    S.set_status(p1, "built")
    rows = S.listing(tmp_path)
    assert [r[0][:5] for r in rows] == ["F-001", "F-002"]
    assert rows[0][2].startswith("built (") and rows[1][2].startswith("approved")


class Planner:
    def __init__(self, *texts):
        self.texts, self.asked = list(texts), []

    def stream(self, messages):
        self.asked.append(messages)
        yield AIMessage(content=self.texts.pop(0))


def test_make_spec_repairs_once():
    bad = SPEC.replace("- Criteria: AC-2\n", "")
    m = Planner("Sure, here it is:\n" + bad, SPEC)
    text, problem = P.make_spec(m, "link the docs", "pack")
    assert problem == "" and text.startswith("# Feature:") and len(m.asked) == 2
    assert "T2 names no criteria" in m.asked[1][-1].content


class Invoked(Model):
    def invoke(self, messages):
        return next(self.stream(messages))


PLAN_OK = """### T1: the page
- Files: `tests/test_ac1.py`
- Done when: `python -m pytest -q tests/test_ac1.py` passes
- Needs: -
"""


def test_fail_first_stops_a_check_that_passes_before_the_work(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ac1.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    m = Invoked(AIMessage(content="", tool_calls=[tc("finish", 1, summary="done")]))
    out = L.run_plan(PLAN_OK, T.Workspace(tmp_path, read_only=()), m, full_test_command="python -m pytest -q",
                     git=False, fail_first=True)
    assert out["tasks"]["T1"]["status"] == "check_passes" and out["check_passes"] == ["T1"]
    assert m.calls == 0  # not built: its check tests nothing
    assert "passes before the work" in out["needs_help"][0]


def test_fail_first_lets_a_failing_check_run(tmp_path):
    m = Invoked(AIMessage(content="", tool_calls=[tc("write_file", 1, path="tests/test_ac1.py",
                                                     content="def test_ok():\n    assert True\n")]),
                AIMessage(content="", tool_calls=[tc("finish", 2, summary="done")]))
    out = L.run_plan(PLAN_OK, T.Workspace(tmp_path, read_only=()), m, full_test_command="python -m pytest -q",
                     git=False, fail_first=True)
    assert out["tasks"]["T1"]["status"] == "passed" and out["check_passes"] == []


def test_without_fail_first_nothing_changes(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ac1.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    m = Invoked(AIMessage(content="", tool_calls=[tc("finish", 1, summary="done")]))
    out = L.run_plan(PLAN_OK, T.Workspace(tmp_path, read_only=()), m, full_test_command="python -m pytest -q",
                     git=False)
    assert out["tasks"]["T1"]["status"] == "passed"


def test_the_chat_writes_a_spec_you_approve(harness, monkeypatch):  # noqa: F811
    state, ws = harness
    (ws / "codemitra.toml").write_text('architecture = "phased"\n', encoding="utf-8")
    made = []
    monkeypatch.setattr(P, "make_spec", lambda llm, task, pack, **k: made.append(task) or (SPEC, ""))
    monkeypatch.setattr(main.ui.menu, "choose", lambda *a, **k: "save")
    Inputs.script = ["build a new feature: export the settlements to a PDF report and add a download button in the app, with tests", "/spec", "exit"]
    main._chat()
    assert made
    files = sorted((ws / "specs").glob("F-*.md"))
    assert [f.name[:5] for f in files] == ["F-001"] and (ws / "specs" / "project.md").is_file()
    rows = [json.loads(x) for f in (ws / ".codemitra" / "runs").glob("chat-*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    end = [r for r in rows if r["kind"] == "turn_end"][-1]
    assert end["outcome"] == "plan_saved" and end["feature"] == "F-001"


def test_a_missing_library_is_offered_for_install(harness, monkeypatch):  # noqa: F811
    state, ws = harness
    (ws / "codemitra.toml").write_text('architecture = "phased"\n', encoding="utf-8")
    spec = SPEC.replace("- none", "- surely_not_a_real_pkg_xyz")
    monkeypatch.setattr(P, "make_spec", lambda llm, task, pack, **k: (spec, ""))
    asked = []

    def choose(console, title, options, default=None):
        asked.append(title)
        return "no" if "Install it?" in title else "save"

    monkeypatch.setattr(main.ui.menu, "choose", choose)
    Inputs.script = ["build a new feature: export the settlements to a PDF report and add a download button in the app, with tests", "exit"]
    main._chat()
    assert any("surely_not_a_real_pkg_xyz" in a and "Install it?" in a for a in asked)


def test_template_placeholders_are_a_problem():
    """Live 2026-11-20: the 9B kept "<one or two sentences>" from the template in every task."""
    _, p = S.check(SPEC.replace("then the page.", "then the page. <one or two sentences>"))
    assert "placeholders" in p and "<one or two sentences>" in p
