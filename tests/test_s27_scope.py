"""E-164 (Stage 2 done-line check, 2026-11-21): a planned task that changes an existing function it does not name is
refused once before "done", and what stays changed is reported."""
from langchain_core.messages import AIMessage

from app.core import finish_gate as FG
from app.core import loop as L
from app.core import tools as T
from tests.test_chat_core import tc
from tests.test_s25_loop_guard import Invoked

OLD = ("def settle(d):\n    return d - 1\n\n\ndef add(a, b):\n    return a + b\n\n\n"
       "class Box:\n    def size(self):\n        return 1\n")


def _journal(path, before, after, existed=True):
    return [{"kind": "create_file", "path": str(path), "existed": existed, "before": before, "after": after}]


def test_a_changed_function_the_task_does_not_name_is_found(tmp_path):
    new = OLD.replace("return d - 1", "return d + 1").replace("return 1", "return 2") + "\n\ndef fresh():\n    pass\n"
    items = FG.outside_task(_journal(tmp_path / "u.py", OLD, new), tmp_path, "T3: add a command using add()")
    assert [(p, n) for p, n, _ in items] == [("u.py", "settle"), ("u.py", "Box.size")]
    assert items[0][2] == 1
    assert FG.outside_task(_journal(tmp_path / "u.py", OLD, new), tmp_path, "fix settle and Box.size") == []
    assert "`settle` (u.py:1)" in FG.scope_note(items)


def test_new_files_tests_and_whitespace_only_changes_are_not_outside(tmp_path):
    assert FG.outside_task(_journal(tmp_path / "n.py", None, OLD, existed=False), tmp_path, "x") == []
    t = tmp_path / "tests" / "test_u.py"
    assert FG.outside_task(_journal(t, OLD, OLD.replace("d - 1", "d + 1")), tmp_path, "x") == []
    assert FG.outside_task(_journal(tmp_path / "u.py", OLD, OLD.replace("return d - 1", "return  d - 1")),
                           tmp_path, "x") == []


def _project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "u.py").write_text(OLD, encoding="utf-8")
    (tmp_path / "tests" / "test_new.py").write_text("from u import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                                                    encoding="utf-8")


def test_the_step_runner_refuses_once_and_the_undo_passes(tmp_path):
    _project(tmp_path)
    broke = OLD.replace("return d - 1", "return d + 1")
    m = Invoked(AIMessage(content="", tool_calls=[tc("read_file", 0, path="u.py")]),
                AIMessage(content="", tool_calls=[tc("write_file", 1, path="u.py", content=broke)]),
                AIMessage(content="", tool_calls=[tc("finish", 2, summary="done")]),
                AIMessage(content="", tool_calls=[tc("write_file", 3, path="u.py", content=OLD)]),
                AIMessage(content="", tool_calls=[tc("finish", 4, summary="undone")]))
    seen = []
    real = L.ToolMessage

    def spy(content="", **k):
        seen.append(content)
        return real(content=content, **k)

    L.ToolMessage = spy
    try:
        res = L.solve("T1: a test for add()", T.Workspace(tmp_path), m, record_path=tmp_path / "rec.jsonl",
                      record_ctx={"task_id": "T1"}, max_steps=8)
    finally:
        L.ToolMessage = real
    assert any("you also changed `settle` (u.py:1)" in c for c in seen)
    assert res.status == "passed" and res.outside == [] and m.calls == 5


def test_kept_outside_changes_are_reported_and_plain_solve_is_unchanged(tmp_path):
    _project(tmp_path)
    broke = OLD.replace("return d - 1", "return d + 1")
    script = [AIMessage(content="", tool_calls=[tc("read_file", 0, path="u.py")]),
              AIMessage(content="", tool_calls=[tc("write_file", 1, path="u.py", content=broke)]),
              AIMessage(content="", tool_calls=[tc("run_tests", 2)]),
              AIMessage(content="I need it.", tool_calls=[tc("run_tests", 3)])]
    res = L.solve("T1: a test for add()", T.Workspace(tmp_path), Invoked(*script), record_path=tmp_path / "r.jsonl",
                  record_ctx={"task_id": "T1"}, max_steps=8)
    assert res.status == "passed" and res.to_json()["outside_task"] == ["u.py:1 settle"]
    (tmp_path / "u.py").write_text(OLD, encoding="utf-8")
    m = Invoked(*script[:3])
    res = L.solve("make add work", T.Workspace(tmp_path), m, record_path=tmp_path / "r2.jsonl", max_steps=8)
    assert res.status == "passed" and m.calls == 3  # not a planned task: no scope to check


LIVE_OLD = '''def optimize_settlements(balances):
    debtors = {k: -v for k, v in balances.items() if v < 0}
    for d in debtors:
        debtors[d] = round(debtors[d] - 1, 2)
    return debtors
'''
LIVE_T3 = '''T3: the summary command
- Files: `tests/test_ac3_cli_summary.py`, `src/trip_splitter/cli.py`
- Criteria: AC-3
- Do: first write the test with typer's `CliRunner`, then add the `summary` command, using `person_summary`,
  `compute_balances`, `optimize_settlements` and `settlements_to_csv`. Keep the `run` command unchanged.'''


def test_the_live_case_named_but_not_its_file_is_outside(tmp_path):
    """Live 2026-11-21: T3 names optimize_settlements ("using ...") but lists only cli.py; it changed utils.py."""
    path = tmp_path / "src" / "trip_splitter" / "utils.py"
    j = _journal(path, LIVE_OLD, LIVE_OLD.replace("debtors[d] - 1", "debtors[d] + 1"))
    assert [n for _, n, _ in FG.outside_task(j, tmp_path, LIVE_T3)] == ["optimize_settlements"]
    in_scope = LIVE_T3.replace("`src/trip_splitter/cli.py`", "`src/trip_splitter/cli.py`, `src/trip_splitter/utils.py`")
    assert FG.outside_task(j, tmp_path, in_scope) == []  # its file listed and it is named: the task's own
