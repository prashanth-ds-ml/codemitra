"""E-142 (skill practice 2026-11-18, qwen3.5 4B): clear change requests ("Add pytest tests for discount() in
discount.py. Do not change discount.py.", "mean() in stats.py crashes on an empty list. Make it return 0.0 ...") went to
the look phase: CodeMitra read the file and answered with how to fix it; nothing was written (all 6 test-writing runs
"changed nothing", with or without the skill). Two causes: "do not change discount.py" counted as "only look", and a
look picked by the decide call was never moved to the change phase, even for a clear change request."""
from langchain_core.messages import AIMessage

from app.core import chat as C
from app.core import skill_tasks as ST
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard


def test_every_practice_request_is_a_change_request():
    for tasks in ST.TASKS.values():
        for task in tasks:
            assert C.asks_change(task.prompt), task.id


def test_do_not_change_a_named_file_is_not_look_only():
    assert C.asks_change("Add pytest tests for discount() in discount.py. Do not change discount.py.")
    assert C.asks_change("Write tests for slugify() in text_utils.py. Don't change text_utils.py.")


def test_look_only_requests_stay_look_only():
    for text in ("first tell me where we are having issues", "don't change anything, just explain the bug",
                 "do not change the code yet, explain why it fails", "explain how to add tests here"):
        assert not C.asks_change(text), text


def _decide_look_then_answer():
    return Heard(AIMessage(content="", tool_calls=[{"name": "look_at_code", "args": {"what": "stats.py"}, "id": "1"}]),
                 AIMessage(content="done"))


def test_a_change_request_that_the_model_sent_to_look_starts_in_the_change_phase(tmp_path):
    s = _session(tmp_path, _decide_look_then_answer())
    s.phased(_msgs("mean() in stats.py crashes on an empty list. Make it return 0.0 for an empty list and keep "
                   "everything else working."))
    rows = _rows(s)
    assert s.last_phase == "make_change"
    assert any(r["kind"] == "phase_override" and r["to"] == "make_change" for r in rows)


def test_a_question_about_a_fix_stays_a_look(tmp_path):
    s = _session(tmp_path, _decide_look_then_answer())
    s.phased(_msgs("how would I fix the crash in stats.py?"))
    assert s.last_phase == "look_at_code"
    assert not any(r["kind"] == "phase_override" for r in _rows(s))


def test_an_explain_request_stays_a_look(tmp_path):
    s = _session(tmp_path, _decide_look_then_answer())
    s.phased(_msgs("explain what mean() does with an empty list"))
    assert s.last_phase == "look_at_code"
