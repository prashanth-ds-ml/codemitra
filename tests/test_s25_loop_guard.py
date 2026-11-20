"""Stage 2.5: the anti-loop ladder (ported from Mingbird, Apache-2.0): change strategy, streak nudge, tool off,
re-reading blocked, the same file changed again and again without the tests passing."""
import json

from langchain_core.messages import AIMessage

from app.agents.limits import LoopGuard
from app.core import chat as C
from app.core import loop as L
from app.core import tools as T
from tests.test_chat_core import Model, fake_hooks, msgs, tc


def test_three_failures_of_a_tool_suggest_another_way():
    g = LoopGuard(max_repeats=9, max_failures=5)
    hints = [g.hint("edit_file", {"path": "a.py", "old": str(i)}, "✗ no match", False) for i in range(3)]
    assert hints[:2] == ["", ""] and "write the whole file with write_file" in hints[2] and g.last == "change_strategy"
    assert g.hint("edit_file", {"path": "a.py", "old": "x"}, "Edited a.py.", True) == ""  # a success resets


def test_a_streak_is_nudged_and_mostly_identical_calls_turn_the_tool_off():
    g = LoopGuard(max_repeats=99, max_failures=99)
    out = [g.hint("search", {"pattern": "x" if i % 2 else "y"}, "found", True) for i in range(8)]
    assert "5 times in a row" in out[4] and g.off == {"search"} and "turned off" in out[7]
    assert g.before("search", {"pattern": "z"}).startswith("✗ Not run: search is turned off")
    assert g.before("read_file", {"path": "a.py"}) is None  # other tools still work


def test_the_tests_are_never_turned_off():
    g = LoopGuard(max_repeats=99, max_failures=99)
    for _ in range(9):
        g.hint("run_tests", {}, "1 failed", False)
    assert g.off == set()


def test_re_reading_the_same_part_is_blocked_other_parts_are_not():
    g = LoopGuard(max_repeats=99, max_failures=99)
    a = {"path": "app.py", "start": 1, "end": 50}
    for i in range(5):
        assert g.before("read_file", a) is None
        g.hint("read_file", a, "lines", True)
        g.hint("edit_file", {"path": "x.py", "old": str(i)}, "Edited", True)  # writes between: not an exact repeat
    assert g.before("read_file", a).startswith("✗ Not run: you keep reading") and g.last == "read_loop"
    assert g.before("read_file", {"path": "app.py", "start": 51, "end": 99}) is None


def test_flip_flopping_between_two_reads_is_blocked():
    g = LoopGuard(max_repeats=99, max_failures=99)
    a, b = {"path": "a.py"}, {"path": "b.py"}
    for args in (a, b, a, b):
        g.hint("read_file", args, "x", True)
    assert g.before("read_file", a).startswith("✗ Not run: you keep reading")


def test_the_live_t2_pattern_gets_the_root_cause_hint():
    """Live 2026-11-20, T2: the test file rewritten 8 times until it passed (steps 7-32)."""
    g = LoopGuard(max_repeats=99, max_failures=99)
    path = "tests/test_ac2_streamlit_pdf_button.py"
    hints = [g.hint("write_file", {"path": path, "content": str(i)}, "Wrote it.", True) for i in range(8)]
    assert "find the root cause" in hints[3] and "do not change what it checks" in hints[3]
    assert "say in one line what you think the cause is" in hints[7]
    g.tests_passed()
    assert g.hint("write_file", {"path": path, "content": "9"}, "Wrote it.", True) == ""  # counts start again


def test_the_chat_adds_the_hint_and_records_it(tmp_path):
    hooks = fake_hooks()[0]
    replies = [AIMessage(content="", tool_calls=[tc("edit_file", i, path="a.py", old=f"x{i}", new="y")])
               for i in range(1, 4)] + [AIMessage(content="I could not edit a.py.")]
    (tmp_path / "a.py").write_text("z = 1\n", encoding="utf-8")
    s = C.ChatSession(workspace=tmp_path, llm=Model(*replies), hooks=hooks, mode="auto-edit")
    seen = []
    real = C.ToolMessage

    def spy(content="", **k):
        seen.append(content)
        return real(content=content, **k)

    C.ToolMessage = spy
    try:
        s.turn(msgs("change a.py"))
    finally:
        C.ToolMessage = real
    assert any("write the whole file with write_file" in c for c in seen)
    rows = [json.loads(x) for x in s.rec.path.read_text(encoding="utf-8").splitlines()]
    assert [r["check"] for r in rows if r["kind"] == "loop_guard"] == ["change_strategy"]
    assert "loop" in [r for r in rows if r["kind"] == "turn_end"][0]["tags"]


class Invoked(Model):
    def invoke(self, messages):
        return next(self.stream(messages))


def test_the_step_runner_adds_the_edit_loop_hint(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("from a import f\n\ndef test_f():\n    assert f() == 2\n",
                                                  encoding="utf-8")
    writes = [AIMessage(content="", tool_calls=[tc("write_file", i, path="a.py", content=f"def f():\n    return {i}\n")])
              for i in range(10, 14)]
    m = Invoked(*writes, *[AIMessage(content="", tool_calls=[tc("finish", 99, summary="x")])] * 4)
    seen = []
    real = L.ToolMessage

    def spy(content="", **k):
        seen.append(content)
        return real(content=content, **k)

    L.ToolMessage = spy
    try:
        L.solve("make f return 2", T.Workspace(tmp_path), m, record_path=tmp_path / "rec.jsonl", rollback=False)
    finally:
        L.ToolMessage = real
    assert any("changed a.py 4 times" in c for c in seen)
    rows = [json.loads(x) for x in (tmp_path / "rec.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["kind"] == "loop_guard" and r["check"] == "edit_loop" for r in rows)


# ── found by the 2.5 live check ─────────────────────────────────────────────────────────────────────────────

def test_package_info_names_the_module_a_package_installs(tmp_path, monkeypatch):
    """E-158: fpdf2 installs `fpdf`; "importing fpdf2 failed" sent the 9B to fix a library that was fine."""
    import sys
    real = sys.executable
    monkeypatch.setattr(T, "project_python", lambda root: real)
    monkeypatch.setattr(T.sys, "executable", "elsewhere")  # the check skips CodeMitra's own Python: pretend it differs
    out = T.package_info(T.Workspace(tmp_path), "PyYAML")  # installs the module `yaml` (a langchain-core dependency)
    assert "Import it as `import yaml`" in out and "importing it failed" not in out


def test_a_missing_test_file_says_write_it_first(tmp_path):
    """E-159: a test-first task ran its check 3 times before writing the test."""
    ws = T.Workspace(tmp_path, test_command="python -m pytest -q tests/test_ac1.py")
    run = T.run_tests(ws)
    assert not run.passed and "does not exist yet" in run.output and "write it now with write_file" in run.output


def test_run_tests_cannot_install():
    import pytest
    with pytest.raises(T.ToolError):
        T.test_args(T.Workspace("."), keyword="pip install fpdf2")


def test_edit_counts_last_across_fresh_rounds(tmp_path):
    """Live 2026-11-20: utils.py changed 7 times across 3 rounds and the edit hint never fired."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("from a import f\n\ndef test_f():\n    assert f() == 2\n",
                                                  encoding="utf-8")
    calls = []
    for i in range(6):
        calls.append(AIMessage(content="", tool_calls=[tc("write_file", i, path="a.py",
                                                          content=f"def f():\n    return {10 + i}\n")]))
        calls.append(AIMessage(content="", tool_calls=[tc("run_tests", 50 + i)]))
    m = Invoked(*calls)
    seen = []
    real = L.ToolMessage

    def spy(content="", **k):
        seen.append(content)
        return real(content=content, **k)

    L.ToolMessage = spy
    try:  # fresh rounds after 3 failing runs: the 4th change (in round 2) still gets the hint
        L.solve("make f return 2", T.Workspace(tmp_path), m, record_path=tmp_path / "rec.jsonl", rollback=False,
                fresh_round_after=3, max_rounds=3, max_steps=12)
    finally:
        L.ToolMessage = real
    assert any("changed a.py 4 times" in c for c in seen)
