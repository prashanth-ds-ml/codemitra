"""E-145 (xlsx practice 2026-11-18, inventory-value 0/4 after E-144): "In inventory.xlsx add a column Value ...": it
wrote a script, never ran it, and said done. The file existed already, so E-144 (a named output must exist) could not
see it. A script written for a requested output file must be run after its last change before the answer."""
from langchain_core.messages import AIMessage

from app.core import chat as C
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard


def tc(name, n, **args):
    return {"name": name, "args": args, "id": str(n)}


ASK = "In inventory.xlsx add a column Value (Qty times Price) as a formula for every item row."


def test_requests_name_their_output_files():
    assert C.wants_output_file(ASK) == ["inventory.xlsx"]
    assert C.wants_output_file("Write a Python function add in solution.py") == []


def test_a_script_written_and_not_run_gets_one_nudge(tmp_path):
    (tmp_path / "inventory.xlsx").write_bytes(b"PK")
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="add Value")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="add_value.py", content="print(1)\n")]),
              AIMessage(content="I've added the Value column to inventory.xlsx."),
              AIMessage(content="", tool_calls=[tc("run_command", 3, command="python add_value.py")]),
              AIMessage(content="Ran add_value.py: Value column added."))
    s = _session(tmp_path, m)
    s.phased(_msgs(ASK))
    rows = [r for r in _rows(s) if r["kind"] == "script_not_run"]
    assert rows and rows[0]["script"] == "add_value.py" and rows[0]["outputs"] == ["inventory.xlsx"]
    assert any("you wrote `add_value.py` but did not run it" in x for x in m.heard[3])


def test_a_script_that_was_run_is_not_nudged(tmp_path):
    (tmp_path / "inventory.xlsx").write_bytes(b"PK")
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="add Value")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="add_value.py", content="print(1)\n")]),
              AIMessage(content="", tool_calls=[tc("run_command", 3, command="python add_value.py")]),
              AIMessage(content="Ran add_value.py: done."))
    s = _session(tmp_path, m)
    s.phased(_msgs(ASK))
    assert not any(r["kind"] == "script_not_run" for r in _rows(s))


def test_a_module_for_a_python_request_is_not_nudged(tmp_path):
    m = Heard(AIMessage(content="", tool_calls=[tc("make_change", 1, what="add")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="solution.py", content="def add(a, b):\n"
                                                                                            "    return a + b\n")]),
              AIMessage(content="Wrote add in solution.py."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Write a Python function add in solution.py"))
    assert not any(r["kind"] == "script_not_run" for r in _rows(s))
