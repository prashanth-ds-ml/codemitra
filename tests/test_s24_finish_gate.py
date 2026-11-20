"""Stage 2.4: one finish gate (ported from Mingbird, Apache-2.0) in the chat's change phase and in the step runner.
Each check refuses at most once per turn, names the next action, and questions are exempt."""
import json

import pytest

from langchain_core.messages import AIMessage

from app import main
from app.core import chat as C
from app.core import finish_gate as FG
from app.core import loop as L
from app.core import tools as T
from tests.test_backend_chat import Inputs, harness  # noqa: F401
from tests.test_chat_core import Model, fake_hooks, msgs, tc

NO_FPDF = ('Traceback (most recent call last):\n  File "make_pdf.py", line 1, in <module>\n    import fpdf\n'
           "ModuleNotFoundError: No module named 'fpdf'")


# ── the pure checks ─────────────────────────────────────────────────────────────────────────────────────────

def test_missing_module_is_a_library_not_the_project(tmp_path):
    assert FG.missing_module(NO_FPDF, tmp_path) == "fpdf"
    assert FG.missing_module("No module named 'yaml.loader'", tmp_path, declared="pyyaml yaml") == "yaml"
    (tmp_path / "src" / "trip_splitter").mkdir(parents=True)
    assert FG.missing_module("No module named 'trip_splitter'", tmp_path) == ""  # the project's own code
    assert FG.missing_module("1 failed: assert 2 == 3", tmp_path) == ""


def test_broken_json_uses_the_last_content(tmp_path):
    j = [{"path": str(tmp_path / "a.json"), "after": "{bad"}, {"path": str(tmp_path / "b.json"), "after": "{}"},
         {"path": str(tmp_path / "c.json"), "after": "{bad"}, {"path": str(tmp_path / "c.json"), "after": "[1]"}]
    assert [p for p, _ in FG.broken_json(j, tmp_path)] == ["a.json"]


def test_recheck_only_for_long_requests():
    assert not FG.wants_recheck("add a docstring to f")
    assert FG.wants_recheck(" ".join(["word"] * 45))
    assert FG.wants_recheck("make a game\n- a maze\n- a score")


# ── the chat's change phase ─────────────────────────────────────────────────────────────────────────────────

def _change(tmp_path, *replies, run_shell=None):
    hooks = fake_hooks()[0]
    if run_shell:
        hooks.run_shell = run_shell
    s = C.ChatSession(workspace=tmp_path, llm=Model(*replies), hooks=hooks, mode="auto-edit")
    s.path, s.last_phase, s.allowed_tools = "phased", "make_change", None
    return s


def _gates(s):
    return [json.loads(x) for x in s.rec.path.read_text(encoding="utf-8").splitlines()
            if json.loads(x)["kind"] == "gate"]


def test_a_missing_library_is_the_setup_not_the_code(tmp_path):
    s = _change(tmp_path, AIMessage(content="", tool_calls=[tc("run_command", 1, command="python make_pdf.py")]),
                AIMessage(content="The PDF export is done."), AIMessage(content="fpdf must be installed first."),
                run_shell=lambda cmd: (NO_FPDF, False))
    res = s.turn(msgs("make report.pdf with make_pdf.py"))
    assert [g["check"] for g in _gates(s)] == ["environment"] and _gates(s)[0]["module"] == "fpdf"
    assert res.text == "fpdf must be installed first."


def test_failing_tests_and_a_done_claim_are_refused_once(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
                                                     encoding="utf-8")
    s = _change(tmp_path, AIMessage(content="", tool_calls=[tc("read_file", 1, path="calc.py")]),
                AIMessage(content="", tool_calls=[tc("edit_file", 2, path="calc.py", old="    return a - b",
                                                     new="    return a * b")]),
                AIMessage(content="Done, all tests pass."), AIMessage(content="Done, all tests pass."))
    res = s.turn(msgs("fix add in calc.py"))
    assert [g["check"] for g in _gates(s)] == ["tests_failed"]  # refused once, then accepted (cap)
    assert res.text == "Done, all tests pass."


def test_broken_json_is_refused(tmp_path):
    s = _change(tmp_path, AIMessage(content="", tool_calls=[tc("write_file", 1, path="config.json", content="{a: 1}")]),
                AIMessage(content="Wrote config.json."),
                AIMessage(content="", tool_calls=[tc("write_file", 2, path="config.json", content='{"a": 1}')]),
                AIMessage(content="Wrote config.json (valid JSON)."))
    res = s.turn(msgs("write config.json with a set to 1"))
    assert [g["check"] for g in _gates(s)] == ["broken_json"] and json.loads((tmp_path / "config.json").read_text())
    assert "valid JSON" in res.text


def test_a_long_request_is_shown_again_once(tmp_path):
    long = ("build a small notes module notes.py with add_note, list_notes and delete_note, keep the notes in "
            "a list in memory, sort list_notes by date, refuse an empty note with ValueError, and write a short README "
            "section about it, with an example of each function and the error it raises")
    s = _change(tmp_path, AIMessage(content="", tool_calls=[tc("write_file", 1, path="notes.py", content="X = 1\n")]),
                AIMessage(content="Made notes.py."), AIMessage(content="Made notes.py; all parts are in."))
    s.turn(msgs(long))
    gates = _gates(s)
    assert [g["check"] for g in gates] == ["recheck"]


def test_a_short_question_is_never_gated(tmp_path):
    s = _change(tmp_path, AIMessage(content="It adds two numbers."))
    s.last_phase = "look_at_code"
    s.turn(msgs("what does add do?"))
    assert _gates(s) == []


def test_the_gate_stops_after_three_refusals(tmp_path):
    s = _change(tmp_path)
    s._gate_done = {"no_work", "script_not_run", "environment"}
    assert s._finish_gate("I've created marks.xlsx", C.TurnResult(), 1) == ""


# ── the step runner ─────────────────────────────────────────────────────────────────────────────────────────

class Invoked(Model):
    def invoke(self, messages):
        return next(self.stream(messages))


PLAN = """### T1: pdf
- Files: `tests/test_pdf.py`, `pdf.py`
- Done when: `python -m pytest -q tests/test_pdf.py` passes
- Needs: -

### T2: button
- Files: `app.py`
- Done when: `python -m pytest -q tests/test_pdf.py` passes
- Needs: T1
"""


def test_a_task_stops_at_once_on_a_missing_library_and_keeps_its_work(tmp_path):
    test = "from pdf import make\n\ndef test_pdf():\n    assert make()\n"
    code = "import surely_missing_lib_xyz\n\ndef make():\n    return True\n"
    m = Invoked(AIMessage(content="", tool_calls=[tc("write_file", 1, path="tests/test_pdf.py", content=test),
                                                  tc("write_file", 2, path="pdf.py", content=code)]),
                AIMessage(content="", tool_calls=[tc("run_tests", 3)]),
                *[AIMessage(content="", tool_calls=[tc("finish", 9, summary="x")])] * 5)
    out = L.run_plan(PLAN, T.Workspace(tmp_path, read_only=()), m, full_test_command="python -m pytest -q",
                     git=False)
    t1 = out["tasks"]["T1"]
    assert t1["status"] == "needs_env" and t1["needs"] == "surely_missing_lib_xyz" and t1["steps"] == 2
    assert (tmp_path / "tests" / "test_pdf.py").is_file()  # not rolled back
    assert out["needs_env"] == {"T1": "surely_missing_lib_xyz"} and "T2" not in out["tasks"]
    assert "needs `surely_missing_lib_xyz` installed" in out["needs_help"][0]


def test_the_chat_offers_the_install_and_runs_the_step_again(harness, monkeypatch):  # noqa: F811
    from app.core import planner as P
    from tests.test_s22_specs import SPEC
    state, ws = harness
    (ws / "codemitra.toml").write_text('architecture = "phased"\n', encoding="utf-8")
    monkeypatch.setattr(P, "make_spec", lambda llm, task, pack, **k: (SPEC, ""))
    runs = []

    def fake_run_plan(text, w, llm, **kw):
        runs.append((text, kw.get("fail_first"), kw["record_ctx"].get("after_install")))
        if len(runs) == 1:
            return {"tasks": {"T1": {"status": "needs_env", "needs": "fpdf", "tests": "", "summary": "x"}},
                    "passed_tasks": 0, "total_tasks": 2, "final_tests_passed": False, "final_tests": "1 failed",
                    "needs_help": [], "check_passes": [], "needs_env": {"T1": "fpdf"}}
        return {"tasks": {"T1": {"status": "passed", "tests": "1 passed", "summary": ""},
                          "T2": {"status": "passed", "tests": "1 passed", "summary": ""}},
                "passed_tasks": 2, "total_tasks": 2, "final_tests_passed": True, "final_tests": "2 passed",
                "needs_help": [], "check_passes": [], "needs_env": {}}

    monkeypatch.setattr(L, "run_plan", fake_run_plan)
    shell = []
    monkeypatch.setattr(main.shell_agent, "execute", lambda command, cwd=None, console=None: shell.append(command) or
                        type("R", (), {"output": "ok", "ok": True, "still_running": False,
                                       "to_llm_summary": lambda self: "installed"})())
    asked = []

    def choose(console, title, options, default=None):
        asked.append(title)
        return "yes" if "Install it?" in title else ("later" if "yours" in title else "go")

    monkeypatch.setattr(main.ui.menu, "choose", choose)
    monkeypatch.setattr(main.ui, "shell_start", lambda c: "", raising=False)
    monkeypatch.setattr(main.ui, "shell_done", lambda r: "", raising=False)
    Inputs.script = ["build a new feature: export the settlements to a PDF report and add a download button in the "
                     "app, with tests", "exit"]
    main._chat()
    assert any("A step needs `fpdf`" in a for a in asked)
    assert shell and "pip install fpdf" in shell[0]
    assert len(runs) == 2 and runs[1][1] is None and runs[1][2] is True  # rerun after install, no fail-first
    assert "### T1:" in runs[1][0] and "### T2:" in runs[1][0]  # T1 and the step that needed it
    assert "- Needs: T1" in runs[1][0].split("### T2:")[1]  # T1 runs again too, so the need stays


def test_code_not_written_yet_is_not_the_setup(tmp_path):
    """Found by an older test: tests import `calc` before calc.py exists; that is the work, not an install."""
    out = ("tests/test_calc.py:1: in <module>\n    from calc import add\n"
           "E   ModuleNotFoundError: No module named 'calc'")
    assert FG.missing_module(out, tmp_path) == ""


def test_a_library_is_the_setup_when_declared_or_imported_by_the_code(tmp_path):
    from_code = ("tests/test_pdf.py:1: in <module>\n    from app.report import make\n"
                 "app/report.py:2: in <module>\n    import fpdf\nE   ModuleNotFoundError: No module named 'fpdf'")
    assert FG.missing_module(from_code, tmp_path) == "fpdf"
    only_test = "tests/test_pdf.py:1: in <module>\n    import fpdf\nE   ModuleNotFoundError: No module named 'fpdf'"
    assert FG.missing_module(only_test, tmp_path) == ""
    assert FG.missing_module(only_test, tmp_path, declared="- fpdf2") == "fpdf"
    (tmp_path / "requirements.txt").write_text("fpdf2\n", encoding="utf-8")
    assert FG.missing_module(only_test, tmp_path) == "fpdf"


def test_declared_libraries_are_named_as_libraries_only():
    assert FG.declared_libraries("write calc.py with add and run the tests") == ""
    assert FG.declared_libraries("make report.pdf with the fpdf library") == "fpdf"
    assert FG.declared_libraries("pip install requests first") == "requests"
    assert FG.declared_libraries("# Feature: x\n\n## Needs\n- fpdf2 (tables)\n\n## Tasks\n") == "fpdf2"
    out = "tests/test_calc.py:1: in <module>\nE   ModuleNotFoundError: No module named 'calc'"
    assert FG.missing_module(out, None and None or __import__("pathlib").Path("."),
                             declared=FG.declared_libraries("write calc.py with add")) == ""


def test_a_benchmark_run_never_installs(tmp_path):
    """E-154 (live 2026-11-20): with nobody to approve, `pip install fpdf` went into the system Python."""
    from app.core import score
    out, ok = score._run_shell(tmp_path)("pip install fpdf")
    assert not ok and "installing packages is off" in out
    assert score.is_install('"C:/py/python.exe" -m pip install fpdf2') and not score.is_install("python make.py")


def test_auto_mode_still_asks_before_an_install(harness, monkeypatch):  # noqa: F811
    state, ws = harness
    asked, ran = [], []
    monkeypatch.setattr(main.ui.menu, "choose", lambda console, title, options, default=None:
                        asked.append(title) or "no")
    monkeypatch.setattr(main.shell_agent, "execute", lambda command, cwd=None, console=None: ran.append(command))
    from app.core import chat as C2
    seen = {}
    real_init = C2.ChatSession.__init__

    def grab(self, *a, **k):
        real_init(self, *a, **k)
        seen["hooks"] = self.hooks
    monkeypatch.setattr(C2.ChatSession, "__init__", grab)
    Inputs.script = ["/mode auto", "exit"]
    main._chat()
    out, ok = seen["hooks"].run_shell("python -m pip install fpdf")
    assert not ok and "declined" in out and ran == [] and any("install packages" in a for a in asked)


def test_a_spec_with_a_missing_library_is_not_built_without_it(harness, monkeypatch):  # noqa: F811
    """E-155: built without its library, a criterion test can be written around the missing library and pass."""
    from app.core import planner as P
    from tests.test_s22_specs import SPEC
    state, ws = harness
    (ws / "codemitra.toml").write_text('architecture = "phased"\n', encoding="utf-8")
    monkeypatch.setattr(P, "make_spec", lambda llm, task, pack, **k: (SPEC.replace("- none", "- surely_missing_xyz"), ""))
    monkeypatch.setattr(L, "run_plan", lambda *a, **k: pytest.fail("not built without its library"))
    monkeypatch.setattr(main.ui.menu, "choose", lambda console, title, options, default=None:
                        "no" if "Install it?" in title else "go")
    Inputs.script = ["build a new feature: export the settlements to a PDF report and add a download button in the "
                     "app, with tests", "exit"]
    main._chat()
    spec_file = next((ws / "specs").glob("F-001-*.md"))
    assert "Status: waiting: install surely_missing_xyz" in spec_file.read_text(encoding="utf-8")
    rows = [json.loads(x) for f in (ws / ".codemitra" / "runs").glob("chat-*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [r for r in rows if r["kind"] == "turn_end"][-1]["outcome"] == "needs_env"
