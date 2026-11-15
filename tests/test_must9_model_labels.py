"""Must-have 9 (D-077): how each turn went. The rules (D-079) catch clear words; at exit the model reads the rest
against a checklist in one call; "none" when unsure; never a turn twice; the learning round reads them like the
rules' own labels."""
import json

from langchain_core.messages import AIMessage

from app.core import improve_chat as IC
from app.core import signals as SIG


def _record(path, turns, extra=()):
    rows = []
    for n, (user, answer) in enumerate(turns, 1):
        rows += [{"t": n, "kind": "turn_start", "turn": n, "user": user},
                 {"t": n + 0.5, "kind": "turn_end", "turn": n, "text": answer}]
    rows += list(extra)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


TURNS = [("make the snake faster", "Done: speed is 12 now (snake/game.py:40)."),
         ("it still crawls on level 2", "Level 2 uses its own speed; set it to 12 too."),
         ("now add a pause key", "Added P to pause (snake/game.py:88), tests pass."),
         ("draft a mail to Ravi", "Hi Ravi, ...")]


class Labeller:
    model = "qwen3.5:4b"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def invoke(self, messages):
        self.prompts.append(messages[-1].content)
        return AIMessage(content=self.reply)


def test_only_turns_nothing_has_labelled_are_asked(tmp_path):
    rec = _record(tmp_path / "chat-1.jsonl", TURNS,
                  [{"kind": "signal", "of_turn": 1, "signal": "unhappy", "auto": True}])
    pairs = SIG.unlabelled_pairs(rec)
    assert [p["turn"] for p in pairs] == [2, 3]                 # 1: the rules did; 4: no next message yet
    assert pairs[0]["next"] == "now add a pause key"


def test_the_checklist_labels_and_none_is_left_out(tmp_path):
    rec = _record(tmp_path / "chat-1.jsonl", TURNS)
    llm = Labeller('[{"n": 1, "verdict": "unhappy", "why": "it still crawls"}, '
                   '{"n": 2, "verdict": "happy", "why": "now add a pause key"}, {"n": 3, "verdict": "none"}]')
    labels, asked = SIG.model_labels(llm, rec)
    assert asked == [1, 2, 3]
    assert labels == [{"turn": 1, "signal": "unhappy", "why": "it still crawls"},
                      {"turn": 2, "signal": "happy", "why": "now add a pause key"}]
    assert "When you are not sure, none." in llm.prompts[0] and "Pair 1:" in llm.prompts[0]


def test_a_bad_reply_is_a_failure_and_marks_nothing_done(tmp_path):
    """Review: an unusable reply was recorded as 'asked', so those turns were never labelled."""
    import pytest
    from tests.test_live_20261113_b import _rows, _session
    from tests.test_phased import Heard
    rec = _record(tmp_path / "chat-1.jsonl", TURNS)
    for reply in ("I think they were happy.", ""):
        with pytest.raises(ValueError):
            SIG.model_labels(Labeller(reply), rec)
    assert SIG.model_labels(Labeller('[{"n": 99, "verdict": "unhappy"}]'), rec)[0] == []   # valid, out of range
    (tmp_path / "ws").mkdir()
    s = _session(tmp_path / "ws", Heard())
    _record(s.rec.path, TURNS)
    assert s.label_turns(Labeller("not json")) == 0
    assert any(r["kind"] == "model_labels_failed" for r in _rows(s)) and len(SIG.unlabelled_pairs(s.rec.path)) == 3


def test_only_the_last_session_of_the_days_record_is_labelled(tmp_path):
    """Review: one file holds a whole day and every session counts turns from 1: pairs crossed sessions."""
    rec = tmp_path / "chat-1.jsonl"
    rows = [{"kind": "session"}, {"kind": "turn_start", "turn": 1, "user": "a"},
            {"kind": "turn_end", "turn": 1, "text": "A"}, {"kind": "turn_start", "turn": 2, "user": "b"},
            {"kind": "turn_end", "turn": 2, "text": "B"}, {"kind": "turn_start", "turn": 3, "user": "old three"},
            {"kind": "session"}, {"kind": "turn_start", "turn": 1, "user": "x"},
            {"kind": "turn_end", "turn": 1, "text": "X"}, {"kind": "turn_start", "turn": 2, "user": "y"},
            {"kind": "turn_end", "turn": 2, "text": "Y"}]
    rec.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert [(p["turn"], p["answer"], p["next"]) for p in SIG.unlabelled_pairs(rec)] == [(1, "X", "y")]


def test_the_models_labels_are_marked_as_the_models(tmp_path):
    from tests.test_live_20261113_b import _rows, _session
    from tests.test_phased import Heard
    s = _session(tmp_path, Heard())
    _record(s.rec.path, TURNS)
    s.label_turns(Labeller('[{"n": 1, "verdict": "unhappy", "why": "x"}]'))
    assert [r["author"] for r in _rows(s) if r["kind"] == "signal"] == ["mitra"]


def test_the_chat_writes_them_once_and_the_learning_round_reads_them(tmp_path):
    from tests.test_live_20261113_b import _rows, _session
    from tests.test_phased import Heard
    s = _session(tmp_path, Heard())
    rec = _record(s.rec.path, TURNS)
    llm = Labeller('[{"n": 1, "verdict": "unhappy", "why": "it still crawls"}]')
    assert s.label_turns(llm) == 1
    sig = [r for r in _rows(s) if r["kind"] == "signal"]
    assert sig and sig[0]["signal"] == "unhappy" and sig[0]["source"] == "model" and sig[0]["of_turn"] == 1
    assert SIG.unlabelled_pairs(rec) == [] and s.label_turns(llm) == 0 and len(llm.prompts) == 1  # never twice
    ev = IC.conversation_signals([rec])
    assert any(e["signal"] == "unhappy" for e in ev)
