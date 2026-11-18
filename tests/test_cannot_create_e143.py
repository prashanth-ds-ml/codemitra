"""E-143 (skill practice 2026-11-18, qwen3.5 4B, 9 of 12 xlsx runs): asked to make an Excel file, the decide call
answered "I can't directly create an `.xlsx` file or manipulate Excel formats right now. I can only read text files"
and offered code to copy; one run in the change phase answered "I've created marks.xlsx" with no tool call. CodeMitra
can: it writes a Python script and runs it. Such answers now get one nudge to do it."""
from langchain_core.messages import AIMessage

from app.core import chat as C
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard

LIVE_CANT = ["I can't directly create an `.xlsx` file or manipulate Excel formats right now. I can only read text "
             "files like `expenses.csv`.",
             "I can't directly create an `.xlsx` file or manipulate it within this environment. However, I can help "
             "you generate the Python code to do exactly that.",
             "I can't create files directly in your local environment through this interface."]
ASK = ("Create expenses.xlsx from expenses.csv: one sheet named Expenses with the columns Date, Item, Amount, the rows "
       "from the CSV, and a Total row at the bottom whose Amount is a SUM formula.")


def tc(name, n, **args):
    return {"name": name, "args": args, "id": str(n)}


def test_the_live_refusals_are_seen():
    assert all(C.says_cannot(t) for t in LIVE_CANT)
    assert C.claims_made("I've created `marks.xlsx` with two sheets")


def test_honest_or_unrelated_answers_are_not():
    for text in ("I can't find a file named report.py here.", "The function can't handle empty lists.",
                 "You can't divide by zero.", "Here is what the code does."):
        assert not C.says_cannot(text), text
    assert not C.claims_made("You have created a list.")


def test_a_refusal_to_a_change_request_gets_one_nudge_and_the_work_is_done(tmp_path):
    # E-147: no second decision (it picked a web search and said "I can't" again): straight to the change phase
    m = Heard(AIMessage(content=LIVE_CANT[0]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="build_sheet.py", content="print('ok')\n")]),
              AIMessage(content="", tool_calls=[tc("run_command", 3, command="python build_sheet.py")]),
              AIMessage(content="Ran build_sheet.py."))
    s = _session(tmp_path, m)
    s.phased(_msgs(ASK))
    rows = _rows(s)
    assert any(r["kind"] == "cannot" for r in rows)
    assert any(r["kind"] == "phase" and r.get("after_cannot") for r in rows) and s.last_phase == "make_change"
    assert any(C.CANT_NOTE in str(x) for x in m.heard[1])   # the change phase was told it can
    assert (tmp_path / "build_sheet.py").is_file()


def test_a_refusal_to_a_question_is_left_alone(tmp_path):
    m = Heard(AIMessage(content="I can't run Excel here, but openpyxl can read it."))
    s = _session(tmp_path, m)
    s.phased(_msgs("what library reads xlsx files?"))
    assert not any(r["kind"] == "cannot" for r in _rows(s)) and len(m.heard) == 1


def test_done_with_nothing_written_in_the_change_phase_gets_one_nudge(tmp_path):
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="create marks.xlsx")]),
              AIMessage(content="I've created `marks.xlsx` with two sheets."),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="make_marks.py", content="print(1)\n")]),
              AIMessage(content="Wrote make_marks.py."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Make marks.xlsx with a sheet Students and a sheet Summary."))
    assert any(r["kind"] == "nothing_written" for r in _rows(s))
    assert C.NOTHING_WRITTEN_NOTE in m.heard[2]
    assert (tmp_path / "make_marks.py").is_file()


def test_done_after_a_real_write_is_not_nudged(tmp_path):
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="create notes.md")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="notes.md", content="# Notes\n")]),
              AIMessage(content="I've created notes.md."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Create notes.md with a heading."))
    assert not any(r["kind"] == "nothing_written" for r in _rows(s))
