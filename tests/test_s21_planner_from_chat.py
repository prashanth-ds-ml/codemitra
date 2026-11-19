"""Stage 2.1 (SPEC_DRIVEN S0): a bigger build in the normal (phased) chat goes to the real planner (runnable plan,
Go / Change / Save) and Go runs the step runner, instead of a chat-text plan whose "yes" starts one long turn."""
import json

from langchain_core.messages import AIMessage

from app import main
from app.core import chat as C
from app.core import loop as L
from app.core import tools as T
from tests.test_backend_chat import Inputs, harness  # noqa: F401 - the driven chat fixture
from tests.test_chat_core import Model, fake_hooks, tc
from tests.test_phased import _msgs, _rows

PLAN = """# Plan: feedback app

### T1: the store
- Files: store.py
- Done when: `python -c "import store"` passes
"""


class Invoked(Model):
    """The step runner calls invoke(), the chat stream()."""

    def invoke(self, messages):
        return next(self.stream(messages))


def _session(tmp_path, m, planner=True):
    hooks = fake_hooks()[0]
    hooks.planner = planner
    return C.ChatSession(workspace=tmp_path, llm=m, hooks=hooks)


def test_a_plan_decision_hands_the_request_to_the_planner(tmp_path):
    m = Model(AIMessage(content="", tool_calls=[tc("propose_plan", 1, goal="feedback app")]))
    s = _session(tmp_path, m)
    res = s.phased(_msgs("build a feedback app with a store and a form"))
    assert res.plan_goal == "build a feedback app with a store and a form"  # the whole request, not the summary
    assert res.text == "" and m.calls == 1  # no chat-text plan was written
    rows = _rows(s)
    assert any(r["kind"] == "phase" and r.get("to_planner") and r["goal"] == "feedback app" for r in rows)
    assert [r["outcome"] for r in rows if r["kind"] == "turn_end"] == ["to_planner"]


def test_without_the_planner_the_plan_phase_is_text_as_before(tmp_path):
    m = Model(AIMessage(content="", tool_calls=[tc("propose_plan", 1, goal="x")]),
              AIMessage(content="Goal: x.\n1. a.py\nShall I build it?"))
    res = _session(tmp_path, m, planner=False).phased(_msgs("build x"))
    assert res.plan_goal == "" and res.text.endswith("Shall I build it?")


def test_planned_steps_carry_session_plan_and_task_ids(tmp_path):
    ws = T.Workspace(tmp_path)
    m = Invoked(AIMessage(content="", tool_calls=[tc("write_file", 1, path="store.py", content="X = 1\n")]),
              AIMessage(content="", tool_calls=[tc("finish", 2, summary="store made")]))
    L.run_plan(PLAN, ws, m, full_test_command='python -c "import store"', record_dir=tmp_path / "rec",
               git=False, record_ctx={"session_id": "s1", "plan": "plan-x.md"})
    rows = [json.loads(x) for x in (tmp_path / "rec" / "T1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and all((r["session_id"], r["plan"], r["task_id"]) == ("s1", "plan-x.md", "T1") for r in rows)
    tools = [r for r in rows if r["kind"] == "tool"]
    assert tools and all("seconds" in r and "output_chars" in r for r in tools)


def test_the_chat_runs_the_planner_after_a_plan_decision(harness, monkeypatch):  # noqa: F811
    state, ws = harness
    (ws / "codemitra.toml").write_text('architecture = "phased"\n', encoding="utf-8")

    def fake_llm(model, temperature=0.2, *, base_url=None, num_ctx=None, **kw):
        m = Model(AIMessage(content="", tool_calls=[tc("propose_plan", 1, goal="feedback app")]),
                  *[AIMessage(content=f"answer {i}") for i in range(20)])
        m.base_url, m.model = base_url, model
        return m

    monkeypatch.setattr(main, "get_local_llm", fake_llm)
    made = []
    from app.core import planner
    monkeypatch.setattr(planner, "make_plan", lambda llm, task, pack, **k: made.append(task) or (PLAN, ""))
    monkeypatch.setattr(main.ui.menu, "choose", lambda *a, **k: "save")
    Inputs.script = ["build a feedback app with a store and a form", "exit"]
    main._chat()
    assert made and made[0].startswith("build a feedback app with a store and a form")
    rows = [json.loads(x) for f in (ws / ".codemitra" / "runs").glob("chat-*.jsonl")
            for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    starts = [(r["path"], r.get("request_kind")) for r in rows if r["kind"] == "turn_start"]
    assert [p for p, _ in starts] == ["phased", "plan_first"]
    ends = [r for r in rows if r["kind"] == "turn_end"]
    assert [e["outcome"] for e in ends] == ["to_planner", "plan_saved"] and ends[1]["via"] == "decide"
    assert list(ws.glob("*.plan.md"))  # saved in the project, so /run runs it there
