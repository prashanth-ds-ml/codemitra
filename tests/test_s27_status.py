"""Stage 2.7: `codemitra status` (features, criteria, tasks, drift, unplanned, cost) and the plan put back word for
word after the chat compacts."""
import json
import time

from app import main
from app.core import spec_status as SS
from app.core import specs as S
from tests.test_s22_specs import SPEC


def _spec(root, name, status="approved 2026-11-21", text=SPEC):
    d = root / "specs"
    d.mkdir(exist_ok=True)
    body = text.replace("# Feature: README links the how-it-works page",
                        f"# Feature {name[:5]}: {name[6:]}\nStatus: {status}")
    (d / f"{name}.md").write_text(body, encoding="utf-8")


def _end(root, run, task_id, status, feature, t, replan=False, tokens=1000, seconds=60):
    p = root / ".codemitra" / "runs" / run / f"{task_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "kind": "model", "feature": feature, "task_id": task_id, "text": "x"}) + "\n")
        f.write(json.dumps({"t": t, "kind": "end", "status": status, "feature": feature, "task_id": task_id,
                            "tokens_in": tokens, "tokens_out": 0, "seconds": seconds,
                            **({"replan": True} if replan else {})}) + "\n")


def _crit(root, feature, statuses, t, answers=None):
    p = root / ".codemitra" / "runs" / SS.CRITERIA_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "kind": "criteria", "feature": feature, "spec": f"{feature}-x.md",
                            "results": [{"id": a, "status": s} for a, s in statuses.items()],
                            "answers": answers or {}}) + "\n")


def test_features_criteria_tasks_drift_and_cost(tmp_path):
    _spec(tmp_path, "F-001-docs-link", "built: AC-1 ✓ · AC-2 ✓ · AC-3 yours: yes")
    _spec(tmp_path, "F-002-pdf-export", "in progress: AC-1 ✗ · AC-2 ✓")
    _spec(tmp_path, "F-003-dark-mode")
    # F-001: both tasks passed first time
    _end(tmp_path, "plan-1", "T1", "passed", "F-001", 1)
    _end(tmp_path, "plan-1", "T2", "passed", "F-001", 2)
    _crit(tmp_path, "F-001", {"AC-1": "passed", "AC-2": "passed", "AC-3": "you"}, 3, {"AC-3": "yes"})
    # F-002: T1 passed, T2 failed then rescued by its re-plan; AC-1 passed once, fails now (drift)
    _end(tmp_path, "plan-2", "T1", "passed", "F-002", 10)
    _end(tmp_path, "plan-2", "T2", "failed", "F-002", 11)
    _end(tmp_path, "plan-2", "R1", "passed", "F-002", 12, replan=True)
    _crit(tmp_path, "F-002", {"AC-1": "passed", "AC-2": "passed", "AC-3": "you"}, 13)
    _crit(tmp_path, "F-002", {"AC-1": "failed", "AC-2": "passed", "AC-3": "you"}, 20)
    data = SS.collect(tmp_path)
    f1, f2, f3 = data["features"]
    assert [f.state for f in (f1, f2, f3)] == ["done", "in progress", "not started"]
    assert f1.task_state == {"T1": "first_try", "T2": "first_try"}
    assert f2.task_state == {"T1": "first_try", "T2": "replanned"}
    assert f3.task_state == {"T1": "not_run", "T2": "not_run"}
    assert f2.drift == ["AC-1"] and f1.drift == []
    assert f1.tokens == 2000 and f2.tokens == 3000 and f2.seconds == 180
    out = SS.render(data)
    assert "✓ done 1 · ◐ in progress 1 · ○ not started 1" in out
    assert "✓ passing 3 · ✗ failing 1 · you check 3 · not checked yet 2" in out
    assert "✓ done 4 (first try 3 · re-planned 1) · needs help 0" in out and "not run 2" in out
    assert "F-002 AC-1 passed before and fail now" in out
    assert "AC-1 ✗ (drift)" in out and "AC-3 yours: yes" in out
    assert "5K tokens" in out


def test_a_failed_task_without_a_rescue_needs_help_and_a_missing_library_waits(tmp_path):
    _spec(tmp_path, "F-001-pdf", "waiting: install fpdf2")
    _end(tmp_path, "plan-1", "T1", "needs_env", "F-001", 1)
    _end(tmp_path, "plan-1", "T2", "failed", "F-001", 2)
    _end(tmp_path, "plan-1", "R1", "failed", "F-001", 3, replan=True)
    f = SS.collect(tmp_path)["features"][0]
    assert f.task_state == {"T1": "env", "T2": "help"}
    out = SS.render(SS.collect(tmp_path))
    assert "needs help 1 · waiting for an install 1" in out and "waiting: install fpdf2" in out


def test_a_later_pass_after_a_fail_is_done_not_first_try(tmp_path):
    _spec(tmp_path, "F-001-pdf")
    _end(tmp_path, "plan-1", "T1", "failed", "F-001", 1)
    _end(tmp_path, "plan-2", "T1", "passed", "F-001", 5)
    assert SS.collect(tmp_path)["features"][0].task_state["T1"] == "done"


def test_a_task_that_passed_in_two_builds_is_still_first_try(tmp_path):
    _spec(tmp_path, "F-001-pdf")
    _end(tmp_path, "plan-1", "T1", "passed", "F-001", 1)
    _end(tmp_path, "plan-2", "T1", "passed", "F-001", 5)
    assert SS.collect(tmp_path)["features"][0].task_state["T1"] == "first_try"


def test_unplanned_counts_chat_turns_that_changed_files_outside_a_feature(tmp_path):
    p = tmp_path / ".codemitra" / "runs" / "chat-20261121.jsonl"
    p.parent.mkdir(parents=True)
    rows = [{"kind": "turn_start", "session_id": "s", "turn": 1},
            {"kind": "turn_end", "session_id": "s", "turn": 1, "changed": ["a.py"]},
            {"kind": "turn_start", "session_id": "s", "turn": 2, "feature": "F-001"},
            {"kind": "turn_end", "session_id": "s", "turn": 2, "changed": ["b.py"]},
            {"kind": "turn_start", "session_id": "s", "turn": 3},
            {"kind": "turn_end", "session_id": "s", "turn": 3, "changed": []}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    _spec(tmp_path, "F-001-x")
    data = SS.collect(tmp_path)
    assert (data["unplanned"], data["changed_turns"]) == (1, 2)


def test_no_specs_says_how_to_start(tmp_path):
    assert "No feature specs yet" in SS.render(SS.collect(tmp_path))


def test_check_now_runs_the_criteria_and_records_them(tmp_path):
    _spec(tmp_path, "F-001-docs-link", "built")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ac1_docs.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_ac2_link.py").write_text("def test_no():\n    assert False\n", encoding="utf-8")
    _crit(tmp_path, "F-001", {"AC-1": "passed", "AC-2": "passed", "AC-3": "you"}, 1)
    assert SS.check_now(tmp_path) == 1
    f = SS.collect(tmp_path)["features"][0]
    assert f.latest == {"AC-1": "passed", "AC-2": "failed", "AC-3": "you"}
    assert f.drift == ["AC-2"]  # a later change broke it: shows without a new build
    row = json.loads((tmp_path / ".codemitra" / "runs" / SS.CRITERIA_FILE).read_text(encoding="utf-8")
                     .splitlines()[-1])
    assert row["source"] == "status --check" and row["feature"] == "F-001"


def test_codemitra_status_shows_the_specs_then_the_old_table(tmp_path, monkeypatch, capsys):
    _spec(tmp_path, "F-001-docs-link")
    monkeypatch.setattr(main, "_resolve_phase0_workspace", lambda cwd: tmp_path)
    shown = []
    monkeypatch.setattr(main, "_print_phase0_status", lambda cwd: shown.append("old"))
    main.cmd_status(cwd=str(tmp_path), check=False)
    out = capsys.readouterr().out
    assert "F-001" in out and "○ not started" in out and shown == ["old"]


def test_an_unattended_spec_run_is_tagged_and_recorded(tmp_path, monkeypatch):
    from app.core import cli
    seen = {}

    def fake_run_plan(text, ws, llm, **kw):
        seen.update(kw)
        return {"tasks": {}, "passed_tasks": 0, "total_tasks": 2, "final_tests_passed": True, "final_tests": "ok",
                "needs_help": [], "check_passes": []}

    monkeypatch.setattr(cli, "run_plan", fake_run_plan)
    monkeypatch.setattr(cli, "get_local_llm", lambda *a, **k: object())
    monkeypatch.setattr(cli.config, "load", lambda: {})
    from app import remote
    monkeypatch.setattr(remote, "check_alive", lambda *a, **k: None)
    (tmp_path / "specs").mkdir()
    spec_file = tmp_path / "specs" / "F-004-docs.md"
    spec_file.write_text(SPEC, encoding="utf-8")
    cli.cmd_solve(plan=str(spec_file), workspace=str(tmp_path), model="m", as_json=True)
    assert seen["record_ctx"] == {"plan": "F-004-docs.md", "spec": "F-004-docs.md", "feature": "F-004"}
    rows = (tmp_path / ".codemitra" / "runs" / SS.CRITERIA_FILE).read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[-1])["source"] == "solve --plan"
    assert "Status: in progress: AC-1 ✗ · AC-2 ✗ · AC-3 yours: open" in spec_file.read_text(encoding="utf-8")


def test_active_plan_is_the_newest_unbuilt_spec_and_the_resume_note(tmp_path):
    _spec(tmp_path, "F-001-old", "built: AC-1 ✓")
    time.sleep(0.01)
    _spec(tmp_path, "F-002-new", "in progress: AC-1 ✗")
    (tmp_path / ".codemitra").mkdir(exist_ok=True)
    (tmp_path / ".codemitra" / "resume.md").write_text("# Plan: x\n- T1 ✓\n", encoding="utf-8")
    text = SS.active_plan(tmp_path)
    assert "specs/F-002-new.md" in text and "F-001" not in text
    assert "- AC-2: README.md links docs/how_it_works.md" in text  # word for word
    assert "Where the last build stopped" in text and "- T1 ✓" in text
    assert SS.active_plan(tmp_path / "nothing") == ""


def test_compaction_puts_the_active_spec_back_word_for_word(tmp_path, monkeypatch):
    _spec(tmp_path, "F-002-new", "in progress")
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    class LLM:
        def invoke(self, msgs):
            return AIMessage(content="the user wants a PDF; some steps done")  # a paraphrase, no criteria

    monkeypatch.setattr(main.session_agent, "ensure_session", lambda ws: {})
    monkeypatch.setattr(main.memory, "save_session_metadata", lambda ws, meta: None)
    out = main._compact(LLM(), [SystemMessage(content="sys"), HumanMessage(content="hi"), AIMessage(content="ok")],
                        "sys", workspace=str(tmp_path))
    assert len(out) == 3 and "AC-1: docs/how_it_works.md explains balances" in out[2].content


def test_parse_keeps_feature_ids_from_file_names():
    assert SS.feature_of("specs/F-012-pdf-export.md") == "F-012" and SS.feature_of("plan.md") == ""
    assert S.parse(SPEC, "F-001").feature == "F-001"


def test_an_unattended_spec_run_may_write_its_tests_and_a_plain_plan_may_not(tmp_path, monkeypatch):
    """E-162: `solve --plan <spec>` kept tests/ read-only, so its tasks could never write their criteria's tests."""
    from app.core import cli
    from tests.test_s22_specs import PLAN_OK
    seen = []
    monkeypatch.setattr(cli, "run_plan", lambda text, ws, llm, **kw: seen.append(ws.read_only) or {
        "tasks": {}, "passed_tasks": 0, "total_tasks": 1, "final_tests_passed": True, "final_tests": "ok",
        "needs_help": [], "check_passes": []})
    monkeypatch.setattr(cli, "get_local_llm", lambda *a, **k: object())
    monkeypatch.setattr(cli.config, "load", lambda: {})
    from app import remote
    monkeypatch.setattr(remote, "check_alive", lambda *a, **k: None)
    (tmp_path / "F-001-x.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "plain.plan.md").write_text(PLAN_OK, encoding="utf-8")
    cli.cmd_solve(plan=str(tmp_path / "F-001-x.md"), workspace=str(tmp_path), model="m", as_json=True)
    cli.cmd_solve(plan=str(tmp_path / "plain.plan.md"), workspace=str(tmp_path), model="m", as_json=True)
    assert seen == [(), ("tests",)]


def test_a_missing_own_src_package_gets_the_projects_own_import_line(tmp_path):
    """E-163: the 9B imported `src.trip_splitter` and looped 3 rounds on "No module named 'trip_splitter'"."""
    from app.core import tools as T
    (tmp_path / "src" / "trip_splitter").mkdir(parents=True)
    (tmp_path / "src" / "trip_splitter" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_old.py").write_text(
        "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).parent.parent / 'src'))\n",
        encoding="utf-8")
    out = "E   ModuleNotFoundError: No module named 'trip_splitter'"
    hint = T.own_package_hint(tmp_path, out)
    assert "this project's own package (src/trip_splitter/)" in hint and "tests/test_old.py:4" in hint
    assert "never `src.trip_splitter" in hint and "pip" not in hint
    (tmp_path / "tests" / "test_old.py").unlink()
    assert "sys.path.insert(0, str(Path(__file__).resolve().parents[1]" in T.own_package_hint(tmp_path, out)
    assert T.own_package_hint(tmp_path, "No module named 'fpdf'") == ""  # a real library: the finish gate's job


def test_run_tests_adds_the_own_package_hint(tmp_path):
    from app.core import tools as T
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import pkg\n\ndef test_x():\n    pass\n", encoding="utf-8")
    run = T.run_tests(T.Workspace(tmp_path), command="python -m pytest -q tests/test_x.py")
    assert not run.passed and "this project's own package (src/pkg/)" in run.output


def test_status_lists_code_a_task_kept_changed_outside_its_task(tmp_path):
    _spec(tmp_path, "F-001-cli")
    p = tmp_path / ".codemitra" / "runs" / "r1" / "T3.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"t": 1, "kind": "end", "status": "passed", "feature": "F-001", "task_id": "T3",
                             "outside_task": ["src/u.py:144 optimize_settlements"]}) + "\n", encoding="utf-8")
    f = SS.collect(tmp_path)["features"][0]
    assert f.outside == ["T3 src/u.py:144 optimize_settlements"]
    assert "Outside     1   existing code changed outside its task: F-001 T3 src/u.py:144" in SS.render(SS.collect(tmp_path))
