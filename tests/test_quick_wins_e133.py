"""E-133 and the quick wins of the 2026-11-15 research ("CodeMitra next features research"):
1. tool calls in the Qwen3-Coder XML form, or written only in the thinking, are run; old thinking is not sent back;
2. an answer that says "I'll create query.sql now" and does nothing is not accepted (practice: mbpp/68,
   spider/network_1/899 ended in 1 step with no file);
3. the coder-parser variant tag; 4. only the failing part of a long test run; 5. practice repeats, pass^k, the paired
   comparison and the margin; 6. helpful/harmful counters on kept rules, and retiring bad ones."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core import chat as C
from app.core import improve_chat as IC
from app.core import practice as P
from app.core import tools as T
from app.core.parse import for_model, text_tool_calls
from tests.test_chat_core import Model, fake_hooks, tc

ROOT = Path(__file__).resolve().parents[1]
KNOWN = {"write_file", "read_file", "run_tests"}

# the two answers from the practice run of 2026-11-15 (records in ~/.codemitra/data/practice-runs/20261115-122828)
SQL_ANSWER = ("Got it. I'll write a single SQL query that returns IDs of students who both have at least one friend and "
              "are liked by someone.\n\nHere's the plan:\n- Use `EXISTS` or `JOIN`s to filter students who satisfy "
              "both conditions.\n- Return only the `ID` column, in order.\n\nI'll create `query.sql` with the query now.")
PY_ANSWER = ("Alright, let's tackle this task step by step. First, I need to understand what a monotonic array is.\n\n"
             "Let's write this function and then create tests in `test_solution.py`.\n\nFirst, I'll look at the "
             "current state of the project files to see if there are any existing files or structures I should be "
             "aware of.")


# 1. parsing --------------------------------------------------------------------------------------------------------

def test_a_qwen_xml_call_is_a_real_call():
    text = ("I'll write it now.\n<tool_call>\n<function=write_file>\n<parameter=path>\nquery.sql\n</parameter>\n"
            "<parameter=content>\nSELECT id FROM t;\n</parameter>\n</function>\n</tool_call>")
    calls, err = text_tool_calls(text, KNOWN)
    assert err == "" and [(c["name"], c["args"]) for c in calls] == [
        ("write_file", {"path": "query.sql", "content": "SELECT id FROM t;"})]


def test_xml_values_keep_numbers_and_unknown_tools_are_ignored():
    calls, _ = text_tool_calls("<function=read_file><parameter=path>a.py</parameter><parameter=start>3</parameter>"
                               "</function><function=rm_rf><parameter=path>/</parameter></function>", KNOWN)
    assert [(c["name"], c["args"]) for c in calls] == [("read_file", {"path": "a.py", "start": 3})]


def test_json_calls_still_work():
    calls, _ = text_tool_calls('<tool_call>{"name": "run_tests", "arguments": {}}</tool_call>', KNOWN)
    assert [c["name"] for c in calls] == ["run_tests"]


def test_old_thinking_is_not_sent_back_and_the_kept_messages_are_unchanged():
    old = AIMessage(content="<think>plan</think>Hi", additional_kwargs={"reasoning_content": "r1"})
    new = AIMessage(content="", additional_kwargs={"reasoning_content": "r2"})
    msgs = [HumanMessage(content="a"), old, HumanMessage(content="b"), new]
    sent = for_model(msgs)
    assert sent[1].content == "Hi" and "reasoning_content" not in sent[1].additional_kwargs
    assert sent[3].additional_kwargs == {"reasoning_content": "r2"}     # this turn's thinking stays
    assert old.additional_kwargs == {"reasoning_content": "r1"} and old.content.startswith("<think>")


class Thinks(Model):
    """Scripted model whose replies come with thinking (the stream hook below hands it on)."""


def _thinking_hooks(thoughts):
    hooks, shown = fake_hooks()

    def stream(chunks):
        msg = None
        for c in chunks:
            msg = c
        return SimpleNamespace(message=msg, text=(msg.content if msg else ""), stopped=False, printed=True,
                               thinking=thoughts.pop(0) if thoughts else "")
    hooks.stream = stream
    return hooks


def test_a_call_written_only_in_the_thinking_is_run(tmp_path):
    thoughts = ["", "<function=write_file><parameter=path>query.sql</parameter><parameter=content>SELECT 1;"
                    "</parameter></function>", ""]
    m = Model(AIMessage(content="", tool_calls=[tc("make_change", 1, what="write the query")]),
              AIMessage(content=""),
              AIMessage(content="Wrote query.sql."))
    s = C.ChatSession(workspace=tmp_path, llm=m, hooks=_thinking_hooks(thoughts))
    s.phased([SystemMessage(content=C.PHASED_PROMPT), HumanMessage(content="write query.sql that selects 1")])
    assert (tmp_path / "query.sql").read_text(encoding="utf-8").strip() == "SELECT 1;"


# 2. the promise guard ----------------------------------------------------------------------------------------------

def test_the_practice_answers_are_promises():
    assert C.promised(SQL_ANSWER) == "I'll create query.sql with the query now."
    assert C.promised(PY_ANSWER).startswith("First, I'll look at the current state")


def test_offers_small_talk_and_reports_are_not_promises():
    for text in ("Should I create the files now?", "Hi! Let me know what you want to work on.",
                 "I changed game.py:2 and the 3 tests pass.", "Both are good. Which matters more this week?", ""):
        assert not C.promises_action(text), text


def _rows(s):
    return [json.loads(x) for x in s.rec.path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_a_decide_answer_that_only_promises_is_asked_to_act(tmp_path):
    m = Model(AIMessage(content=SQL_ANSWER),                                                    # promised, no phase
              AIMessage(content="", tool_calls=[tc("make_change", 1, what="write query.sql")]),  # told: act now
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="query.sql", content="SELECT 1;")]),
              AIMessage(content="Wrote query.sql."))
    s = C.ChatSession(workspace=tmp_path, llm=m, hooks=fake_hooks()[0])
    s.phased([SystemMessage(content=C.PHASED_PROMPT), HumanMessage(content="Practice task. Save the query in query.sql")])
    assert (tmp_path / "query.sql").exists()
    assert [r["kind"] for r in _rows(s)].count("promise") == 1


def test_the_promise_guard_asks_once_only(tmp_path):
    m = Model(AIMessage(content=SQL_ANSWER), AIMessage(content=SQL_ANSWER))
    s = C.ChatSession(workspace=tmp_path, llm=m, hooks=fake_hooks()[0])
    res = s.phased([SystemMessage(content=C.PHASED_PROMPT), HumanMessage(content="write query.sql")])
    assert m.calls == 2 and res.text == SQL_ANSWER        # asked once, then the answer stands (never a loop)


def test_a_change_phase_that_ends_on_a_promise_is_nudged_to_write(tmp_path):
    m = Model(AIMessage(content="", tool_calls=[tc("make_change", 1, what="write solution.py")]),
              AIMessage(content="I'll create solution.py now."),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="solution.py", content="x = 1\n")]),
              AIMessage(content="Wrote solution.py."))
    s = C.ChatSession(workspace=tmp_path, llm=m, hooks=fake_hooks()[0])
    s.phased([SystemMessage(content=C.PHASED_PROMPT), HumanMessage(content="write solution.py")])
    assert (tmp_path / "solution.py").exists()


# 3. the coder-parser tag --------------------------------------------------------------------------------------------

def _script():
    spec = importlib.util.spec_from_file_location("coder_parser_tag", ROOT / "scripts" / "coder_parser_tag.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_variant_modelfile_switches_renderer_and_parser():
    mod = _script()
    out = mod.variant_modelfile("FROM /blobs/x\nRENDERER qwen3.5\nPARSER qwen3.5\nPARAMETER top_k 20\n")
    assert "RENDERER qwen3-coder" in out and "PARSER qwen3-coder" in out and "qwen3.5" not in out
    assert "RENDERER qwen3-coder" in mod.variant_modelfile("FROM /blobs/x\n")
    assert mod.variant_name("qwen3.5:latest") == "qwen3.5-coderparse:latest"


def test_the_kaggle_notebook_makes_the_variant():
    from remote.kaggle import build_notebook as B
    assert "coderparse" in B.PULL and "RENDERER qwen3-coder" in B.PULL


# 4. the failing part of a test run ----------------------------------------------------------------------------------

def _pytest_output(failures=2, noise=60):
    lines = ["============================= test session starts =============================="]
    lines += [f"test_mod.py::test_ok_{i} PASSED" for i in range(noise)]
    lines += ["=================================== FAILURES ==================================="]
    for n in range(failures):
        lines += [f"________________________________ test_bad_{n} ________________________________",
                  "    def test_bad():"] + [f"        x = {i}" for i in range(40)] + [
                  ">       assert add(2, 2) == 5", "E       assert 4 == 5", "test_mod.py:9: AssertionError"]
    lines += ["=========================== short test summary info ============================",
              "FAILED test_mod.py::test_bad_0 - assert 4 == 5", "FAILED test_mod.py::test_bad_1 - assert 4 == 5",
              f"========================= 2 failed, {noise} passed in 0.31s ========================="]
    return "\n".join(lines)


def test_a_long_failure_shows_the_first_failure_end_and_the_failed_lines():
    shown = T.failing_part(_pytest_output(), ok=False)
    assert "E       assert 4 == 5" in shown and "test_mod.py:9: AssertionError" in shown
    assert "FAILED test_mod.py::test_bad_1" in shown and "1 more failure(s) not shown" in shown
    assert "PASSED" not in shown and "2 failed, 60 passed" in shown
    assert len(shown.splitlines()) < 45


def test_a_long_pass_is_its_result_line_and_short_output_is_unchanged():
    out = "\n".join([f"test_{i} PASSED" for i in range(50)] + ["===== 50 passed in 0.2s ====="])
    assert T.failing_part(out, ok=True) == "50 passed in 0.2s"
    short = "FAILED x\n1 failed in 0.1s"
    assert T.failing_part(short, ok=False) == short


# 5. practice repeats ------------------------------------------------------------------------------------------------

def _r(i, passed, run=1, split="learn"):
    return P.Result(i, "python", split, passed, run=run)


def test_repeats_give_pass_k_and_the_flaky_tasks():
    s = P.summary([_r("a", True, 1), _r("b", True, 1), _r("a", True, 2), _r("b", False, 2)])
    assert s["tasks"] == 2 and s["pass_all"] == 1 and s["flaky"] == ["b"] and s["all"] == [3, 4]
    row = {"summary": s, "seconds": 60, "repeats": 2, "results": []}
    assert "passed every run 1/2 (pass^2)" in P.report(row) and "(b)" in P.report(row)


def test_the_margin_says_how_wide_a_small_split_is():
    assert P.margin(5, 9) == 32 and P.margin(16, 20) == 18 and P.margin(0, 0) == 0


def test_runs_are_compared_task_by_task():
    prev = {"date": "2026-11-15 12:28", "harness_version": 0,
            "results": [{"id": "a", "passed": False}, {"id": "b", "passed": True}, {"id": "c", "passed": True}]}
    row = {"results": [{"id": "a", "passed": True}, {"id": "b", "passed": False}, {"id": "c", "passed": True}]}
    assert P.compare(prev, row) == "vs 2026-11-15 12:28 (harness v0): 1 better (a), 1 worse (b), 1 the same"
    assert P.compare(None, row) == ""


def test_run_repeats_every_task(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(P, "solve", lambda task, runner, timeout_s: (seen.append(task.id),
                                                                       P.Result(task.id, "python", "learn", True))[1])
    runner = SimpleNamespace(harness=SimpleNamespace(version=0), arch="phased", backend="laptop", num_ctx=1,
                             records=tmp_path)
    tasks = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    row = P.run(tasks, runner, results=tmp_path / "p.jsonl", repeats=3)
    assert seen == ["a", "b"] * 3 and row["repeats"] == 3 and [r["run"] for r in row["results"]] == [1, 1, 2, 2, 3, 3]


# 6. rule counters ---------------------------------------------------------------------------------------------------

def test_kept_rules_count_their_own_cases_and_bad_ones_retire(tmp_path, monkeypatch):
    from app.core import harness as H
    monkeypatch.setattr(H, "home", lambda: tmp_path)
    h = H.Harness(rules=["Ask back when the user is deciding."])
    H.save(h, "kept", path=None)
    stats = IC.note_kept("Ask back when the user is deciding.", ["B5"])
    assert stats["Ask back when the user is deciding."]["helpful"] == 1
    rules = H.load().rules
    _, retire = IC.count_rules(rules, [{"B5": True}, {"B5": True}, {"B5": False}])      # passed in most runs
    assert retire == [] and IC.rule_stats()[rules[0]]["helpful"] == 2
    for _ in range(3):                                                                     # failed in every run
        _, retire = IC.count_rules(rules, [{"B5": False}, {"B5": False}])
    assert retire == rules and IC.rule_stats()[rules[0]]["harmful"] == 3
    assert IC.retire_rules(retire, say=lambda t: None) and H.load().rules == []


def test_a_rule_without_counters_is_left_alone(tmp_path, monkeypatch):
    from app.core import harness as H
    monkeypatch.setattr(H, "home", lambda: tmp_path)
    _, retire = IC.count_rules(["an old rule"], [{"B1": False}])
    assert retire == [] and IC.rule_stats() == {}
