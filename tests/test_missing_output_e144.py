"""E-144 (skill practice 2026-11-18, xlsx after E-143): CodeMitra wrote build_expenses.py, never ran it, and answered
"Created `expenses.xlsx` with a "Expenses" sheet ..." for a file that did not exist (all 9 runs that wrote something
were "not checked after its last change"). The verify-before-done skill did not change that habit, so it is a check
in code: an output file the change phase's answer names must exist, else one nudge to run what makes it."""
from langchain_core.messages import AIMessage

from app.core import chat as C
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard

LIVE = ('Created `expenses.xlsx` with a "Expenses" sheet containing Date, Item, Amount columns and a Total row with '
        'the formula `=SUM(C2:C4)`.')


def tc(name, n, **args):
    return {"name": name, "args": args, "id": str(n)}


def test_a_named_output_file_that_does_not_exist_is_found(tmp_path):
    assert C.missing_outputs(LIVE, tmp_path) == ["expenses.xlsx"]
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "expenses.xlsx").write_bytes(b"x")
    assert C.missing_outputs(LIVE, tmp_path) == []                 # found by name anywhere in the project


def test_scripts_and_formulas_are_not_output_files(tmp_path):
    assert C.missing_outputs("Wrote build_expenses.py; run `python build_expenses.py`. =SUM(C2:C4)", tmp_path) == []


def test_the_note_names_the_script_that_was_not_run():
    note = C.missing_note(["expenses.xlsx"], ["build_expenses.py"])
    assert "`expenses.xlsx`" in note and "You wrote `build_expenses.py` but did not run it" in note


def test_the_live_turn_gets_one_nudge_and_runs_the_script(tmp_path):
    script = "open('expenses.xlsx', 'wb').write(b'PK')\n"
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="create expenses.xlsx")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="build_expenses.py", content=script)]),
              AIMessage(content=LIVE),
              AIMessage(content="", tool_calls=[tc("run_command", 3, command="python build_expenses.py")]),
              AIMessage(content="Ran `python build_expenses.py`: expenses.xlsx exists now."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Create expenses.xlsx from expenses.csv."))
    rows = _rows(s)
    # E-145 (a script written for a requested output and not run) fires first here; either nudge names the script
    # (this test's fake shell does not really run it, so the file stays missing and E-144 also fires, once)
    assert [r["kind"] for r in rows if r["kind"] in ("missing_output", "script_not_run")] == [
        "script_not_run", "missing_output"]
    assert any("wrote `build_expenses.py` but did not run it" in x for x in m.heard[3])


def test_an_answer_whose_files_exist_is_not_nudged(tmp_path):
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="notes")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="notes.md", content="# Notes\n")]),
              AIMessage(content="Created `notes.md`."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Create notes.md with a heading."))
    assert not any(r["kind"] == "missing_output" for r in _rows(s)) and len(m.heard) == 3
