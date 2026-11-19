"""Stage 1.2-1.8: what a chat turn's record holds, and that `trace check` can answer all 8 questions for it."""
import json

from langchain_core.messages import AIMessage

from app.core import chat as C
from app.core import grounding
from app.core import trace_check as TC
from app.core import turnfacts as TF
from tests.test_chat_core import Model, call, fake_hooks, msgs, project, tc


def _rows(tmp_path, kind=None):
    rec = next((tmp_path / ".codemitra" / "runs").glob("chat-*.jsonl"))
    rows = [json.loads(line) for line in rec.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if kind is None or r["kind"] == kind]


def _trace(tmp_path):
    rec = next((tmp_path / ".codemitra" / "runs").glob("chat-*.jsonl"))
    return [json.loads(line) for line in TC.trace_path(rec).read_text(encoding="utf-8").splitlines()]


def _session(tmp_path, *replies, hooks=None):
    hooks = hooks or fake_hooks()[0]
    return C.ChatSession(workspace=tmp_path, llm=Model(*replies), hooks=hooks, mode="auto-edit")


def test_ids_and_schema_on_every_row(tmp_path):
    project(tmp_path)
    s = _session(tmp_path, AIMessage(content="Hi."))
    s.turn(msgs("hello"))
    rows = _rows(tmp_path)
    assert rows and all(r["session_id"] == s.session_id and r["v"] == 2 for r in rows)
    start = _rows(tmp_path, "turn_start")[0]
    assert {k: start[k] for k in ("spec", "feature", "task_id")} == {"spec": "", "feature": "", "task_id": ""}
    assert start["files"] == {"tests/test_calc.py": TF._hash_bytes((tmp_path / "tests" / "test_calc.py").read_bytes())}


def test_tool_rows_have_time_full_output_and_mcp(tmp_path):
    project(tmp_path)
    (tmp_path / "big.txt").write_text("\n".join(f"line {i}" for i in range(1500)), encoding="utf-8")
    hooks, _ = fake_hooks()
    s = _session(tmp_path, call(tc("read_file", 1, path="big.txt"), tc("mcp_call", 2, server="github", tool="list_issues",
                                                                         arguments={})),
                 AIMessage(content="Read it."), hooks=hooks)
    s.turn(msgs("read big.txt and list issues"))
    tools = {r["name"]: r for r in _rows(tmp_path, "tool")}
    assert all("seconds" in r and "output_chars" in r for r in tools.values())
    assert (tools["mcp_call"]["server"], tools["mcp_call"]["tool"]) == ("github", "list_issues")
    end = _rows(tmp_path, "turn_end")[0]
    assert end["used"]["mcp"] == ["github.list_issues"]
    long = tools["read_file"]
    if long["output_chars"] > C.OUTPUT_CAP:  # cut on the row: the full text is in the trace
        full = [r for r in _trace(tmp_path) if r["kind"] == "tool_output"]
        assert full and len(full[0]["output"]) == long["output_chars"]


def test_a_write_gives_a_change_row_with_its_diff(tmp_path):
    project(tmp_path)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    s = _session(tmp_path, call(tc("read_file", 1, path="calc.py")),
                 call(tc("edit_file", 2, path="calc.py", old="    return a - b", new="    return a + b")),
                 AIMessage(content="I fixed add in calc.py."))
    s.turn(msgs("fix add in calc.py"))
    (change,) = [r for r in _rows(tmp_path, "change") if r["rel"] == "calc.py"]
    assert change["via"] == "tool" and "-    return a - b" in change["diff"] and "+    return a + b" in change["diff"]
    assert change["after"] == TF.text_hash((tmp_path / "calc.py").read_text(encoding="utf-8"))  # the text written
    report = TC.answer(TC.turns(next((tmp_path / ".codemitra" / "runs").glob("chat-*.jsonl")))[0])
    assert {a.question: a.ok for a in report}["files"]


def test_a_file_made_by_a_command_is_seen(tmp_path):
    project(tmp_path)
    hooks, _ = fake_hooks()

    def run_shell(cmd):
        (tmp_path / "out.xlsx").write_bytes(b"PK fake")
        return "ran", True

    hooks.run_shell = run_shell
    s = _session(tmp_path, call(tc("run_command", 1, command="python make.py")), AIMessage(content="Made out.xlsx."),
                 hooks=hooks)
    s.turn(msgs("make out.xlsx"))
    rows = [r for r in _rows(tmp_path, "change") if r["rel"] == "out.xlsx"]
    assert rows and rows[0]["via"] == "command" and rows[0]["created"]
    assert _rows(tmp_path, "turn_end")[0]["changed_by_commands"] == ["out.xlsx"]


def test_claim_row_and_false_done_tag(tmp_path):
    project(tmp_path)
    s = _session(tmp_path, AIMessage(content="I fixed the bug in calc.py."))
    s.turn(msgs("fix the bug in calc.py"))
    (claim,) = _rows(tmp_path, "claim")
    assert claim["verdict"] == "false" and claim["claims"][0]["kind"] == "changed"
    assert {"changed", "tests_run", "last_test_ok"} <= set(claim["evidence"])
    tags = _rows(tmp_path, "turn_end")[0]["tags"]
    assert "false_done" in tags and "no_action" in tags


def test_time_split_and_wait(tmp_path):
    project(tmp_path)
    s = _session(tmp_path, AIMessage(content="One."), AIMessage(content="Two."))
    s.turn(msgs("first"))
    s.turn(msgs("second"))
    first, second = _rows(tmp_path, "turn_end")
    assert first["wait_s"] is None and second["wait_s"] is not None and second["wait_s"] >= 0
    for end in (first, second):
        assert end["model_s"] >= 0 and end["tools_s"] >= 0
        assert end["model_s"] + end["tools_s"] <= end["seconds"] + 1


def test_machine_on_the_session_row(tmp_path, monkeypatch):
    from app.core import runinfo
    monkeypatch.setattr(runinfo, "machine", lambda: {"os": "TestOS", "gpu": "G", "ollama_version": "1.0"})
    s = _session(tmp_path)
    s.note_session(model="m")
    (row,) = _rows(tmp_path, "session")
    assert (row["os"], row["gpu"], row["ollama_version"]) == ("TestOS", "G", "1.0")


def test_a_recorded_turn_answers_all_8_questions(tmp_path, monkeypatch):
    from app.core import runinfo
    monkeypatch.setattr(runinfo, "machine", lambda: {"os": "TestOS", "gpu": "G", "ollama_version": "1.0"})
    project(tmp_path)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    s = _session(tmp_path, call(tc("read_file", 1, path="calc.py")),
                 call(tc("edit_file", 2, path="calc.py", old="    return a - b", new="    return a + b")),
                 AIMessage(content="Fixed add; the tests pass."))
    s.request_kind = "change"
    s.note_session(model="m")
    s.turn(msgs("fix add in calc.py"))
    rec = next((tmp_path / ".codemitra" / "runs").glob("chat-*.jsonl"))
    (turn,) = TC.turns(rec)
    missing = {a.question: a.missing for a in TC.answer(turn) if not a.ok}
    assert missing == {}, missing


def test_claims_verdicts():
    tools_ok = [("run_tests", True, "3 passed")]
    tools_fail = [("run_tests", False, "1 failed")]
    assert grounding.claims("All tests pass.", tools_ok)[0]["verdict"] == "true"
    assert grounding.claims("All tests pass.", tools_fail)[0]["verdict"] == "false"
    assert grounding.claims("Done.", [], changed=True)[0]["verdict"] == "unchecked"
    assert grounding.claims("I added a pause key.", [], changed=False)[0]["verdict"] == "false"
    assert grounding.claims("Should I add a pause key?", []) == []
    assert grounding.verdict([]) == "none"


def test_mistake_tags_rules():
    tags = TF.mistake_tags(claims_verdict="none", asked_change=False, did_work=True, last_test_ok=False,
                           tools=[("run_command", False, "SyntaxError: x"), ("edit_file", False, ""),
                                  ("edit_file", False, "")],
                           kinds=["repeat", "model_error_stall", "missing_output"], outcome="answered")
    assert set(tags) == {"tests_fail", "broken_code", "loop", "tool_misuse", "stall", "missing_output"}
    assert set(tags) <= set(TF.TAGS)


def test_snapshot_skips_codemitra_dirs_and_caps(tmp_path, monkeypatch):
    (tmp_path / ".codemitra").mkdir()
    (tmp_path / ".codemitra" / "x.jsonl").write_text("x")
    (tmp_path / "a.py").write_text("a")
    assert TF.snapshot(tmp_path) == {"a.py": TF.text_hash("a")}
    monkeypatch.setattr(TF, "MAX_FILES", 1)
    (tmp_path / "b.py").write_text("b")
    snap = TF.snapshot(tmp_path)
    assert snap["_count"] == 2 and "_tree" in snap


def test_a_long_tool_output_is_kept_in_full_in_the_trace(tmp_path):
    project(tmp_path)
    hooks, _ = fake_hooks()
    hooks.run_shell = lambda cmd: ("x" * 5000, True)
    s = _session(tmp_path, call(tc("run_command", 1, command="python big.py")), AIMessage(content="It printed x."),
                 hooks=hooks)
    s.turn(msgs("run big.py"))
    (row,) = _rows(tmp_path, "tool")
    assert len(row["output"]) == C.OUTPUT_CAP and row["output_chars"] >= 5000
    (full,) = [r for r in _trace(tmp_path) if r["kind"] == "tool_output"]
    assert full["output"].startswith("x" * 5000) and full["name"] == "run_command"


def test_replay_first_call_and_start_check(tmp_path):
    from app.core import replay as R
    project(tmp_path)
    s = _session(tmp_path, call(tc("read_file", 1, path="tests/test_calc.py")), AIMessage(content="It tests add."))
    s.turn(msgs("what does the test check?"))
    rec = next((tmp_path / ".codemitra" / "runs").glob("chat-*.jsonl"))
    (turn,) = TC.turns(rec)
    first = R.first_call(rec, turn)
    assert first and first["messages"][-1]["content"] == "what does the test check?"

    class Again:  # a model that makes the same first call again
        def bind_tools(self, tools):
            assert [t["name"] for t in tools]
            return self

        def invoke(self, messages):
            assert messages[-1].content == "what does the test check?"
            return call(tc("read_file", 9, path="tests/test_calc.py"))

    out = R.replay_first(rec, turn, Again())
    assert out["same"] and out["same_tool"] and out["recorded"].startswith("read_file(")
    chk = R.start_check(turn.start["files"], tmp_path)
    assert chk["same"] == ["tests/test_calc.py"] and not chk["differ"]
    (tmp_path / "tests" / "test_calc.py").write_text("changed", encoding="utf-8")
    assert R.start_check(turn.start["files"], tmp_path)["differ"] == ["tests/test_calc.py"]


def test_a_benchmark_run_records_the_request_kind_and_traces(tmp_path):
    """Live check 2026-11-18: runs (score / practice) left request_kind empty and had no traces."""
    from app.core import harness as H
    from app.core import score as S
    project(tmp_path)
    r = S.Runner(llm=Model(AIMessage(content="It tests add.")), harness=H.load(), num_ctx=8192,
                 records=tmp_path / "records", arch="phased")
    ws = tmp_path
    s = r.session(ws, "case1")
    r.respond(s, [r.system(ws=ws), msgs("what does the test check?")[-1]], ws)
    assert s.request_kind
    rec = tmp_path / "records" / "case1.jsonl"
    assert TC.turns(rec)[0].start["request_kind"] == s.request_kind
    assert (tmp_path / "records" / "traces" / "case1.jsonl").is_file()


def test_claims_about_earlier_turns_are_not_false():
    """Live check 2026-11-18 turns 3, 6, 10: true claims about an earlier turn were marked false."""
    got = grounding.claims("The docstring I added to utils.py is complete.", [], changed=False,
                           earlier={"changed": True, "tests_ok": True})
    assert got[0]["verdict"] == "earlier"
    got = grounding.claims("Yes, all tests are passing!", [], earlier={"changed": True, "tests_ok": True})
    assert got[0]["verdict"] == "earlier" and grounding.verdict(got) == "true"
    got = grounding.claims("Yes, all tests are passing!", [], earlier={"changed": True, "tests_ok": False})
    assert got[0]["verdict"] == "false"


def test_session_memory_backs_a_later_claim(tmp_path):
    project(tmp_path)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    s = _session(tmp_path, call(tc("read_file", 1, path="calc.py")),
                 call(tc("edit_file", 2, path="calc.py", old="    return a - b", new="    return a + b")),
                 AIMessage(content="I fixed add."), AIMessage(content="I fixed add in calc.py earlier."))
    s.turn(msgs("fix add in calc.py"))
    s.turn(msgs("did you fix it?"))
    second = _rows(tmp_path, "claim")[-1]
    assert second["claims"][0]["verdict"] == "earlier" and "false_done" not in _rows(tmp_path, "turn_end")[-1]["tags"]


def test_script_not_run_tag_only_when_never_run():
    base = dict(claims_verdict="none", asked_change=False, did_work=True, last_test_ok=None, kinds=["script_not_run"])
    assert "script_not_run" in TF.mistake_tags(tools=[("write_file", True, "")], **base)
    assert "script_not_run" not in TF.mistake_tags(tools=[("run_command", True, "ok")], **base)
