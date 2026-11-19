"""Stage 1.1: the logs audit answers the 8 questions per turn, and reports what is missing."""
import json

from typer.testing import CliRunner

from app.core import trace_check as TC


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _full(tmp_path):
    rec = tmp_path / "runs" / "chat-20261118.jsonl"
    _write(rec, [
        {"t": 1, "kind": "session", "os": "Windows", "gpu": "RTX", "ollama_version": "0.13"},
        {"t": 2, "kind": "turn_start", "turn": 1, "user": "add a pause key", "request_kind": "change",
         "backend": "laptop", "session_id": "s1", "spec": "", "feature": "", "task_id": "",
         "files": {"game.py": "abc"}},
        {"t": 3, "kind": "model", "turn": 1, "step": 1, "tokens_in": 10, "tokens_out": 5},
        {"t": 4, "kind": "tool", "turn": 1, "name": "edit_file", "args": {}, "ok": True, "output": "ok", "seconds": 0.1},
        {"t": 4.1, "kind": "change", "turn": 1, "path": "game.py", "diff": "-a\n+b", "before": "abc", "after": "def"},
        {"t": 5, "kind": "claim", "turn": 1, "claims": ["done"], "evidence": [], "verdict": "unchecked"},
        {"t": 6, "kind": "turn_end", "turn": 1, "text": "Done.", "changed": ["game.py"], "model_s": 1, "tools_s": 0.1,
         "wait_s": 0, "used": {"skills": [], "mcp": [], "lessons": []}, "tags": []},
    ])
    _write(TC.trace_path(rec), [
        {"t": 2.5, "kind": "prompt", "hash": "p1", "system": "s", "tools": []},
        {"t": 3.1, "kind": "call", "prompt": "p1", "tokens_in": 10, "tokens_out": 5, "model": "q", "seconds": 1.0},
    ])
    return rec


def test_full_turn_answers_all(tmp_path):
    (t,) = TC.turns(_full(tmp_path))
    answers = TC.answer(t)
    assert [a.question for a in answers] == list(TC.QUESTIONS)
    assert all(a.ok for a in answers), [a for a in answers if not a.ok]


def test_bare_turn_names_what_is_missing(tmp_path):
    rec = tmp_path / "chat-1.jsonl"
    _write(rec, [
        {"t": 1, "kind": "session"},
        {"t": 2, "kind": "turn_start", "turn": 1, "user": "fix it"},
        {"t": 3, "kind": "model", "turn": 1, "step": 1},
        {"t": 4, "kind": "tool", "turn": 1, "name": "write_file", "args": {}, "ok": True, "output": "x" * TC.OUTPUT_CAP},
        {"t": 5, "kind": "turn_end", "turn": 1, "text": "Done.", "changed": ["a.py"]},
    ])
    got = {a.question: a.missing for a in TC.answer(TC.turns(rec)[0])}
    assert "request kind" in got["request"] and "id spec" in got["request"]
    assert any(m.startswith("traced calls") for m in got["model"]) and "backend" in got["model"]
    assert "tool seconds" in got["tools"] and "full output of cut results" in got["tools"]
    assert "files at turn start" in got["files"] and any(m.startswith("diff per change") for m in got["files"])
    assert got["claims"] == ["claim row"]
    assert "machine gpu" in got["time"] and "wait_s" in got["time"]
    assert "mistake tags" in got["replay"]


def test_not_applicable_facts_count_as_answered(tmp_path):
    rec = tmp_path / "chat-2.jsonl"
    _write(rec, [{"t": 1, "kind": "session"}, {"t": 2, "kind": "turn_start", "turn": 1, "user": "hi"},
                 {"t": 3, "kind": "turn_end", "turn": 1, "text": ""}])
    got = {a.question: a for a in TC.answer(TC.turns(rec)[0])}
    assert got["claims"].ok  # no reply text: nothing claimed
    assert got["tools"].ok   # no tool call: nothing to time


def test_turns_split_by_session_and_calls_by_time(tmp_path):
    rec = tmp_path / "chat-3.jsonl"
    _write(rec, [
        {"t": 1, "kind": "session"}, {"t": 2, "kind": "turn_start", "turn": 1, "user": "a"},
        {"t": 3, "kind": "turn_end", "turn": 1},
        {"t": 10, "kind": "session"}, {"t": 11, "kind": "turn_start", "turn": 1, "user": "b"},
        {"t": 12, "kind": "turn_end", "turn": 1},
    ])
    _write(TC.trace_path(rec), [{"t": 2.5, "kind": "call"}, {"t": 11.5, "kind": "call"}, {"t": 11.6, "kind": "call"}])
    a, b = TC.turns(rec)
    assert (a.start["user"], len(a.calls)) == ("a", 1)
    assert (b.start["user"], len(b.calls)) == ("b", 2)


def test_report_counts_and_cli(tmp_path):
    rec = _full(tmp_path)
    rep = TC.check(TC.chat_files([tmp_path]))
    assert (rep.turns, rep.complete, rep.answered["files"]) == (1, 1, 1)
    from app.main import cli
    res = CliRunner().invoke(cli, ["trace", "check", str(tmp_path), "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["complete"] == 1
    res = CliRunner().invoke(cli, ["trace", "last", str(rec)])
    assert res.exit_code == 0 and "add a pause key" in res.output
