"""`codemitra improve --chat` (Phase B, first part): a rule is proposed from failed score cases and your signals, and the
score decides whether it stays. No model: a scripted proposer and a scripted score."""
import json

from langchain_core.messages import AIMessage

from app.core import harness as H
from app.core import improve as I
from app.core import improve_chat as IC


class Proposer:
    model = "qwen3.5:latest"

    def __init__(self, *texts):
        self.texts, self.seen = list(texts), []

    def invoke(self, messages):
        self.seen.append(messages[-1].content)
        return AIMessage(content=self.texts.pop(0) if self.texts else "")


def _rule(text, why="fixes small talk"):
    return json.dumps({"kind": "rule", "text": text, "why": why})


def _row(score, failed=()):
    cases = [{"id": i, "category": c, "passed": False, "why": w} for i, c, w in failed]
    return {"date": "2026-11-11 16:28", "model": "qwen3.5:latest", "arch": "phased", "only": None,
            "categories": list(IC.JUDGE_CATEGORIES), "score": score, "cases": cases}


BASE = {"behaviour": [7, 10], "writing": [2, 3], "explain": [3, 4], "ideas": [1, 2]}
FAILED = [("B3_how_are_you", "behaviour", "should not match: (?i)\\bsnake\\b"),
          ("W3_summary", "writing", "missing: 1 Feb")]


def _ids(cat, total):
    """Stable case ids per category; the base's first failing case of a category is its FAILED id (a target)."""
    ids = [f"{cat}{k}" for k in range(total)]
    named = {c: i for i, c, _ in reversed(FAILED)}
    if cat in named and cat in BASE and BASE[cat][0] < total:
        ids[BASE[cat][0]] = named[cat]
    return ids


def _score_row(score):
    """A score row whose cases follow the totals: the first `passed` cases of each category pass."""
    cases = [{"id": i, "category": cat, "passed": k < p, "why": "" if k < p else "failed"}
             for cat, (p, n) in score.items() for k, i in enumerate(_ids(cat, n))]
    return {**_row(score), "cases": cases}


class Scores:
    """Scripted `score.run`: call 1 is the current harness, call 2 the candidate; then the repeats of the cases that
    changed, base and candidate in turn, as in the first runs unless `repeats` says otherwise: {arm: [{id: passed}]}."""

    def __init__(self, *scores, repeats=None):
        self.scores, self.harnesses, self.only, self.repeats = list(scores), [], [], repeats or {}
        self.first = []

    def __call__(self, cats, *, runner, model, cwd, on_case, results, only=None):
        self.harnesses.append(runner.harness)
        self.only.append(only)
        if not only:
            row = _score_row(self.scores.pop(0))
            self.first.append(row)
            return row
        arm = ("base", "candidate")[(len(self.only) - 3) % 2]
        n = (len(self.only) - 3) // 2
        first = self.first[0 if arm == "base" else 1]
        over = (self.repeats.get(arm) or [{}] * 9)[n]
        cases = [{**c, "passed": over.get(c["id"], c["passed"])} for c in first["cases"] if c["id"] in only]
        return {**first, "cases": cases}


def _run(proposer, scores, row, files=(), **kw):
    return IC.improve_chat(proposer=proposer, make_runner=lambda h, rec: type("R", (), {"harness": h})(),
                           model="qwen3.5:latest", arch="phased", score_row=row, files=list(files),
                           instructions=lambda h: H.apply_prompt("You are CodeMitra.", h), run_score=scores,
                           say=lambda t: None, **kw)


def test_a_rule_that_adds_cases_without_a_drop_is_kept_and_can_be_undone():
    better = {**BASE, "behaviour": [9, 10]}
    scores = Scores(BASE, better)
    entry = _run(Proposer(_rule("When the user makes small talk, reply without mentioning their work.")), scores,
                 _row(BASE, FAILED))
    assert entry["result"] == "kept" and entry["new_version"] == 1
    assert H.load().rules == ["When the user makes small talk, reply without mentioning their work."]
    assert scores.harnesses[0].rules == [] and scores.harnesses[1].rules == H.load().rules  # A then B
    assert entry["next_row"]["score"] == better                                              # next round's evidence
    assert [a["result"] for a in I.attempts()] == ["kept"] and I.attempts()[0]["kind"] == "chat"


def test_a_rule_that_breaks_a_passing_case_is_dropped_even_with_more_fixed():
    scores = Scores(BASE, {"behaviour": [10, 10], "writing": [1, 3], "explain": [3, 4], "ideas": [1, 2]})
    entry = _run(Proposer(_rule("When the user writes, answer short.")), scores, _row(BASE, FAILED))
    assert entry["result"] == "dropped" and "now fails in all 3 runs: writing1 (writing)" in entry["reason"]
    assert H.load().rules == [] and entry["next_row"]["score"] == BASE


def test_a_gain_only_outside_the_cases_it_was_proposed_for_is_not_enough():
    entry = _run(Proposer(_rule("When the user thinks aloud, ask one question.")),
                 Scores(BASE, {**BASE, "ideas": [2, 2]}), _row(BASE, FAILED))
    assert entry["result"] == "dropped" and "0 of the cases it was proposed for passed reliably" in entry["reason"]
    assert "gains elsewhere: ideas1" in entry["reason"]


def test_a_rule_naming_the_test_set_is_refused_and_asked_again():
    p = Proposer(_rule("Never mention the snake game in small talk."),
                 _rule("In small talk, never bring up the project."))
    entry = _run(p, Scores(BASE, BASE), _row(BASE, FAILED), dry_run=True)
    assert entry["result"] == "dry_run" and entry["change"] == "rule: In small talk, never bring up the project."
    assert "names the test set (snake)" in p.seen[1]


def test_only_rules_and_never_a_rule_already_tried():
    I.log_attempt({"kind": "chat", "result": "dropped", "change": "rule: Ask one question back."})
    p = Proposer(json.dumps({"kind": "limit", "name": "max_repeats", "value": 3, "why": "x"}),
                 _rule("Ask one question back."))
    entry = _run(p, Scores(), _row(BASE, FAILED), dry_run=True)
    assert entry["result"] == "no_proposal" and "already tried" in entry["reason"]
    assert "Ask one question back." in p.seen[0]                      # the proposer was told what failed before


def test_nothing_to_learn_from_changes_nothing():
    entry = _run(Proposer(), Scores(), None)
    assert entry["result"] == "skipped" and I.attempts() == [] and H.load().version == 0


def test_a_broken_model_is_not_judged():
    class Broken(Scores):
        def __call__(self, cats, **kw):
            row = _row({"behaviour": [0, 2]})
            row["cases"] = [{"id": "B1", "category": "behaviour", "passed": False, "why": "TimeoutError: 600 s"},
                            {"id": "B2", "category": "behaviour", "passed": False, "why": "ConnectError: refused"}]
            return row

    entry = _run(Proposer(_rule("Ask one question back.")), Broken(), _row(BASE, FAILED))
    assert entry["result"] == "bench_error" and H.load().version == 0


def test_signals_from_your_conversations_are_evidence(tmp_path):
    rec = tmp_path / "chat-1.jsonl"
    rows = [{"t": 1, "kind": "turn_start", "turn": 1, "user": "good what about you"},
            {"t": 2, "kind": "turn_end", "turn": 1, "text": "Fine! Shall we fix the snake tests?"},
            {"t": 3, "kind": "feedback", "of_turn": 1, "verdict": "bad", "note": "I did not ask about work"},
            {"t": 4, "kind": "turn_start", "turn": 2, "user": "/copy"},
            {"t": 5, "kind": "signal", "of_turn": 2, "signal": "undo"},              # a command: not evidence
            {"t": 6, "kind": "feedback", "of_turn": 1, "verdict": "good", "note": ""}]
    rec.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sigs = IC.conversation_signals([rec])
    assert [s["signal"] for s in sigs] == ["bad"] and sigs[0]["note"] == "I did not ask about work"
    text = IC.evidence_text([], sigs)
    assert 'the user said "good what about you"' in text and "I did not ask about work" in text
    p = Proposer(_rule("In small talk, never bring up the project."))
    entry = _run(p, Scores(), None, files=[rec], dry_run=True)        # signals alone are enough to start
    assert entry["result"] == "dry_run" and entry["evidence"] == {"score": "", "failed_cases": 0, "signals": 1}


def test_failed_cases_carry_what_the_user_typed():
    f = IC.score_failures(_row(BASE, FAILED))
    assert f[0]["asked"] == "good what about you" and f[1]["asked"].startswith("summarise this:")
    assert IC.last_score_row([_row(BASE), {**_row(BASE), "arch": "one"}], model="qwen3.5:latest",
                             arch="phased")["arch"] == "phased"


# ── must-have 7: the fair gate ───────────────────────────────────────────────────────────────────────────────────
BETTER = {**BASE, "behaviour": [8, 10]}          # B3_how_are_you (a target) passes with the rule


def test_only_the_cases_that_changed_run_again_on_both_arms():
    scores = Scores(BASE, BETTER)
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), scores, _row(BASE, FAILED))
    assert entry["result"] == "kept" and entry["gate"]["targeted_gains"] == ["B3_how_are_you"]
    assert scores.only[:2] == [None, None] and scores.only[2:] == [{"B3_how_are_you"}] * (2 * (IC.REPEATS - 1))
    assert [h.rules != [] for h in scores.harnesses[2:4]] == [False, True]          # base, then candidate


def test_a_fix_that_holds_in_one_run_of_three_is_noise():
    scores = Scores(BASE, BETTER, repeats={"candidate": [{"B3_how_are_you": False}] * 2})
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), scores, _row(BASE, FAILED))
    assert entry["result"] == "dropped" and "0 of the cases it was proposed for passed reliably in 3 runs" in \
        entry["reason"]


def test_one_bad_run_of_a_passing_case_is_not_a_loss():
    worse_once = {**BETTER, "explain": [2, 4]}                                       # explain2 fails once
    scores = Scores(BASE, worse_once, repeats={"candidate": [{"explain2": True}, {"explain2": False}]})
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), scores, _row(BASE, FAILED))
    assert entry["result"] == "kept" and entry["gate"]["losses"] == []


def test_no_change_at_all_runs_nothing_again():
    scores = Scores(BASE, BASE)
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), scores, _row(BASE, FAILED))
    assert entry["result"] == "dropped" and len(scores.only) == 2


def test_a_held_out_case_that_breaks_drops_the_rule(monkeypatch):
    monkeypatch.setattr(IC, "has_held_out", lambda: True)
    cats = []
    scores = Scores({**BASE, "real": [1, 1]}, {**BETTER, "real": [0, 1]})
    orig = scores.__call__

    def spy(c, **kw):
        cats.append(tuple(c))
        return orig(c, **kw)
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), spy, _row(BASE, FAILED))
    assert "real" in cats[0] and entry["result"] == "dropped" and "real0 (held out)" in entry["reason"]


def test_held_out_cases_are_never_the_evidence():
    row = _score_row({**BASE, "real": [0, 1]})
    assert all(f["category"] != "real" for f in IC.score_failures(row))



def test_targets_are_only_the_failures_the_judge_runs():
    """Review: coding failures from a full score were targets the judge never runs, so every rule was dropped."""
    row = _row(BASE, [("small_1", "small", "failed"), ("B3_how_are_you", "behaviour", "x")])
    entry = _run(Proposer(_rule("In small talk, never bring up the project.")), Scores(BASE, BETTER), row)
    assert entry["result"] == "kept" and entry["gate"]["targeted_gains"] == ["B3_how_are_you"]


def test_a_queued_coach_rule_counts_any_reliable_fix():
    IC.queue_rules([{"text": "Ask one short question back when the user is deciding.", "why": "1"}])
    entry = _run(Proposer(), Scores(BASE, {**BASE, "ideas": [2, 2]}), _row(BASE, FAILED))
    assert entry["result"] == "kept" and entry["source"] == "coach"


def test_a_rule_that_quotes_a_test_case_is_refused():
    """Live 2026-11-15: the proposer wrote 'questions like "what is the difference between LoRA and QLoRA?"', the
    exact message of case B6; banned words caught only project names and case ids."""
    cases = {"B6_general": "what is the difference between LoRA and QLoRA?"}
    quoted = "When answering questions like 'what is the difference between LoRA and QLoRA?', keep it short."
    assert "quotes a test case (B6_general" in IC.check_rule(quoted, set(), cases)
    assert IC.check_rule("When the user asks a general knowledge question, answer in under 150 words.", set(),
                         cases) == ""
