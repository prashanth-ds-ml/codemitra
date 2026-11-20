"""Stage 2.6: the evidence report at the end of a change, from the turn's records, not the model."""
import json

from langchain_core.messages import AIMessage

from app.core import chat as C
from app.core import evidence as EV
from tests.test_chat_core import Model, fake_hooks, msgs, tc

DIFF = """--- a/utils.py
+++ b/utils.py
@@ -70,3 +70,8 @@
 def f():
+    '''doc'''
+    x = 1
+    y = 2
+    z = 3
+    return x
@@ -120,2 +125,2 @@
-old
+new
"""


def test_line_ranges_and_counts_from_the_diff():
    assert EV.line_ranges(DIFF) == "71-75, 125"  # changed lines only
    assert EV.counts(DIFF) == (6, 1)


def test_changed_line_names_files_new_files_and_command_made_files():
    rows = [{"rel": "utils.py", "via": "tool", "created": False, "diff": DIFF},
            {"rel": "tests/test_a.py", "via": "tool", "created": True, "diff": "+++ b\n+a\n+b\n"},
            {"rel": "report.pdf", "via": "command", "created": True, "diff": ""}]
    line = EV.changed_line(rows)
    assert "`utils.py:71-75, 125` (+6 -1)" in line and "new `tests/test_a.py` (2 lines)" in line
    assert "made by a command: `report.pdf`" in line


def test_not_checked_names_the_gaps():
    rows = [{"rel": "README.md", "via": "tool", "created": False, "diff": "+x"}]
    gaps = EV.not_checked(rows, [("run_tests", False, "1 failed")],
                          [{"verdict": "false", "text": "All tests pass."}], ran_after_last_change=False)
    assert "nothing ran after the last change" in gaps and "the last test run failed" in gaps
    assert any("`README.md` has no test" in g for g in gaps) and any("All tests pass." in g for g in gaps)
    assert EV.not_checked(rows, [], [], has_tests=False)[0] == "this project has no tests: the change is untested"


def test_report_is_empty_when_nothing_changed_or_ran():
    assert EV.report([], [("read_file", True, "x")], []) == ""


def test_a_change_turn_records_and_keeps_its_evidence(tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
                                                     encoding="utf-8")
    s = C.ChatSession(workspace=tmp_path, llm=Model(
        AIMessage(content="", tool_calls=[tc("read_file", 1, path="calc.py")]),
        AIMessage(content="", tool_calls=[tc("edit_file", 2, path="calc.py", old="    return a - b",
                                             new="    return a + b")]),
        AIMessage(content="Fixed add in calc.py.")), hooks=fake_hooks()[0], mode="auto-edit")
    s.turn(msgs("fix add in calc.py"))
    ev = s.last_evidence
    assert ev.startswith("**Evidence**") and "`calc.py:2` (+1 -1)" in ev
    assert "- Ran: tests: 1 passed" in ev  # the chat's own test run after the change
    rows = [json.loads(x) for x in s.rec.path.read_text(encoding="utf-8").splitlines()]
    assert [r["text"] for r in rows if r["kind"] == "evidence"] == [ev]


def test_a_question_turn_has_no_evidence(tmp_path):
    s = C.ChatSession(workspace=tmp_path, llm=Model(AIMessage(content="It adds.")), hooks=fake_hooks()[0])
    s.turn(msgs("what does add do?"))
    assert s.last_evidence == ""


# ── found by the 2.6 live check ─────────────────────────────────────────────────────────────────────────────

def test_ranges_are_the_changed_lines_not_the_context():
    """Live: a docstring at 48-72 was reported as 51-76 (the hunk's context lines counted)."""
    diff = "@@ -46,3 +46,5 @@\n def f():\n+    '''a'''\n+    '''b'''\n     x = 1\n     return x\n"
    assert EV.line_ranges(diff) == "47-48"


def test_a_question_is_not_a_claim_and_a_command_decides_runs():
    from app.core import grounding as G
    tools = [("run_tests", False, "2 failed"), ("run_command", True, "ok")]
    got = G.claims("Fix the Streamlit app file issue so the tests pass? My script runs successfully.", tools)
    assert [(c["kind"], c["verdict"]) for c in got] == [("runs", "true")]


def test_the_failing_tests_are_named():
    out = "FAILED tests/test_trip_splitter.py::test_streamlit_app_loads - X\nFAILED tests/t.py::test_db - Y\n2 failed"
    gaps = EV.not_checked([{"rel": "a.py", "via": "tool"}], [("run_tests", False, out)], [])
    assert gaps[0] == "the last test run failed (test_streamlit_app_loads, test_db)"


def test_a_description_is_not_a_claim():
    from app.core import grounding as G
    assert G.claims("3. How the net balance formula works", [], changed=True) == []
    assert G.claims("The README section works.", [], changed=True)[0]["verdict"] == "unchecked"
