"""CI check: the fixed prompt + tool specs stay under ~3K tokens (SCOPE.md)."""

import importlib.util
import pathlib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "model_view.py"
_spec = importlib.util.spec_from_file_location("model_view", _PATH)
model_view = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(model_view)


def test_estimate_rounds_up():
    assert model_view.estimate_tokens("") == 0
    assert model_view.estimate_tokens("a") == 1
    assert model_view.estimate_tokens("a" * 7) == 2
    assert model_view.estimate_tokens("a" * 8) == 3


def test_views_cover_chat_and_solve():
    totals = model_view.totals()
    assert len(totals) == 3 and any("phased" in name for name in totals)   # E-106: the default chat is measured
    assert all(total > 0 for total in totals.values())


def test_chat_and_solve_under_budget():
    totals = model_view.totals()
    over = {name: total for name, total in totals.items() if total > model_view.BUDGET_TOKENS}
    assert not over, f"over the {model_view.BUDGET_TOKENS:,}-token budget: {over}"


def test_render_lists_every_part():
    text = model_view.render()
    assert "estimate" in text.lower()
    for parts in model_view.views().values():
        for part, _ in parts:
            assert part in text


def test_a_full_harness_stays_under_budget(monkeypatch):
    """Learned rules and tool texts are added to the fixed prompt: the most the harness allows must still fit.
    E-138: the machine note is measured at its longest (a project with no .venv yet, as on CI), not this checkout's."""
    import sys

    from app.core import tools as T
    monkeypatch.setattr(T, "project_python", lambda root: sys.executable)
    from app.core import chat, loop, tools
    from app.core import harness as H

    import pathlib

    from app.agents import shell

    note = shell.limits_text(pathlib.Path.cwd())
    for name, specs, prompt in [("phased chat", chat.tool_specs("approve"), chat.PHASED_PROMPT + "\n\n" + note),
                                ("router chat", chat.tool_specs("approve"), chat.CHAT_PROMPT),
                                ("solve", tools.TOOL_SPECS, loop.SYSTEM_PROMPT)]:
        # the worst case: every rule at full length, and the learned tool texts on the tools with the shortest
        # descriptions (each replaces one); E-106: the phased chat is the default and was never measured
        shortest = sorted(specs, key=lambda s: len(s["description"]))[:H.MAX_TOOL_TEXTS]
        h = H._clean(H.Harness(rules=["x" * H.MAX_RULE_CHARS] * H.MAX_RULES,
                               tools={s["name"]: "y" * H.MAX_TOOL_CHARS for s in shortest}))
        total = (model_view.estimate_tokens(H.apply_prompt(prompt, h))
                 + model_view.estimate_tokens(model_view._specs_text(H.apply_tools(specs, h))))
        assert total <= model_view.BUDGET_TOKENS, f"{name}: {total} tokens with a full harness"


def test_a_harness_keeps_the_newest_rules_and_tool_texts_and_says_so(capsys):
    from app.core import harness as H
    from app.core import improve as I
    h = H._clean(H.Harness(rules=[f"rule {i}" for i in range(6)], tools={"a": "1", "b": "2", "c": "3"}))
    assert h.rules == ["rule 2", "rule 3", "rule 4", "rule 5"] and list(h.tools) == ["c"]
    err = capsys.readouterr().err
    assert "2 oldest rule(s) left out" in err and "2 oldest tool text(s) left out" in err
    h2 = I.Change("tool", "x", text="new", name="d").apply(h)
    assert list(h2.tools) == ["d"]



def test_a_text_over_the_limit_is_cut_at_a_word_and_said(capsys):
    """Review: lowering MAX_TOOL_CHARS cut old tool texts mid-word, silently."""
    from app.core import harness as H
    h = H._clean(H.Harness(version=4, tools={"read_file": "word " * 100}))
    assert h.tools["read_file"].endswith("word…") and len(h.tools["read_file"]) <= H.MAX_TOOL_CHARS
    assert "shortened to fit the prompt budget: tool text read_file" in capsys.readouterr().err
