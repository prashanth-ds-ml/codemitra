"""D-071 conversation memory as threads: what was said, decided and left open, written by the model from the chat
records at exit (or the next start), loaded per turn when your message is about it."""
import json

from langchain_core.messages import AIMessage

from app.core import threads as T

WEB = {"slug": "feedback-web-app", "title": "Web app that collects ratings to fine-tune a model", "project": "-",
       "said": "People chat in Roman Telugu and rate answers 1-5; ratings become fine-tuning data.",
       "decided": "FastAPI + SQLite.", "open": "Who rates first."}


def test_save_load_and_index(tmp_path):
    T.save(WEB, tmp_path)
    T.save({"title": "Brick breaker plan", "project": "mitra-try", "said": "Rewrite the stale plan."}, tmp_path)
    got = {t["slug"]: t for t in T.load(tmp_path)}
    assert got["feedback-web-app"]["decided"] == "FastAPI + SQLite." and got["brick-breaker-plan"]["open"] == "-"
    index = T.index_text(tmp_path)
    assert index.startswith("## Our earlier conversations") and "Web app that collects ratings" in index
    assert T.index_text(tmp_path / "none") == ""


def test_relevant_threads_follow_the_message(tmp_path):
    T.save(WEB, tmp_path)
    T.save({"title": "Brick breaker plan", "project": "mitra-try", "said": "Rewrite the stale plan."}, tmp_path)
    text = T.relevant_text("lets continue the web app idea from yesterday", tmp_path)
    assert "## Thread: Web app that collects ratings" in text and "Brick breaker" not in text
    assert T.relevant_text("hi", tmp_path) == "" and T.relevant_text("what about lunch", tmp_path) == ""


def _record(path, turns):
    rows = []
    for n, (user, answer) in enumerate(turns, 1):
        rows += [{"t": n * 10, "kind": "turn_start", "turn": n, "user": user},
                 {"t": n * 10 + 1, "kind": "turn_end", "turn": n, "text": answer}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_pending_turns_skip_commands_and_empty_answers(tmp_path):
    rec = tmp_path / "chat.jsonl"
    _record(rec, [("hi", "Hi!"), ("/help", "x"), ("build it", ""), ("web app with ratings?", "Yes: rate 1-5.")])
    assert [t["user"] for t in T.pending_turns(rec, tmp_path / "th")] == ["hi", "web app with ratings?"]


def test_summarize_writes_threads_once_from_the_models_json(tmp_path):
    rec, root = tmp_path / "chat.jsonl", tmp_path / "th"
    _record(rec, [("lets build a web app where users rate answers to fine tune", "Good idea: store ratings.")])
    reply = 'Here you go:\n[{"slug": "feedback-web-app", "title": "Ratings web app", "project": "-", ' \
            '"said": "Users rate answers; ratings fine-tune the model.", "decided": "-", "open": "Who rates"}]'

    class LLM:
        calls = 0

        def invoke(self, messages):
            LLM.calls += 1
            assert "lets build a web app" in messages[0].content
            return AIMessage(content=reply)

    assert T.summarize(LLM(), rec, "mitra-try", root) == ["Ratings web app"]
    assert T.load(root)[0]["said"].startswith("Users rate answers")
    assert T.summarize(LLM(), rec, "mitra-try", root) == [] and LLM.calls == 1   # nothing new: no model call


def test_bad_model_output_writes_nothing(tmp_path):
    assert T.parse_threads("sure, here are the threads") == [] and T.parse_threads("[{not json}]") == []
    assert T.parse_threads('[{"title": "x"}]') == []                              # no summary: not a thread


def test_the_score_seeds_a_thread_and_one_codemitra_gets_it(tmp_path):
    from app.core import chat as C
    from app.core import score as S
    from app.core import store
    from tests.test_chat_core import Model

    seen = []

    class Watch(Model):
        def stream(self, messages):
            seen.append(" ".join(str(m.content) for m in messages))
            return super().stream(messages)

    ref = ("Sure. Where we left it: people chat in Roman Telugu, rate each answer, and the ratings become "
           "fine-tuning data. Want to start with the ratings table?")
    r = S.Runner(llm=Watch(AIMessage(content=ref)), harness=C.H.Harness(), num_ctx=8192,
                 records=store.root() / "score-runs" / "th", arch="one")
    out = S.run_behaviour(r, only={"B10_remembers"})
    assert [(c.id, c.passed) for c in out] == [("B10_remembers", True)]
    assert "## Thread: Web app that collects ratings" in seen[0] and "Our earlier conversations" in seen[0]


def test_a_matched_thread_is_marked_as_its_own_topic_not_the_folders_project(tmp_path):
    """E-101 (B10): continuing the web-app thread inside the snake folder, a 9B mixed in the snake game."""
    T.save(WEB, tmp_path)
    text = T.relevant_text("lets continue the web app idea from yesterday", tmp_path)
    assert text.startswith("[Earlier conversation(s) this message is about.") and "not about the files" in text
    assert T.relevant_text("hi", tmp_path) == ""                              # no header without a thread


# ── must-have 8: threads add, never overwrite ────────────────────────────────────────────────────────────────────

def test_continuing_a_thread_keeps_what_was_said_before(tmp_path):
    T.save(WEB, tmp_path)
    T.save({"slug": WEB["slug"], "title": "Web app", "project": "-",
            "said": "Picked the login page first.", "decided": "-", "open": "Which database?"}, tmp_path)
    t = T.load(tmp_path)[0]
    assert t["said"] == "Picked the login page first." and t["open"] == "Which database?"
    assert t["title"] == WEB["title"] and t["project"] == WEB["project"]          # kept as first set
    assert t["decided"] == " ".join(WEB["decided"].split())                       # a decision stays until replaced
    assert [h["said"] for h in t["history"]] == [" ".join(WEB["said"].split())]  # the old version is in the file


def test_every_session_adds_one_history_line_and_none_is_lost(tmp_path):
    slug = T._slug(WEB["title"])
    for n in range(4):
        T.save({"slug": slug, "title": WEB["title"], "said": f"session {n}", "decided": f"choice {n}"}, tmp_path)
    t = T.load(tmp_path)[0]
    assert t["said"] == "session 3" and t["decided"] == "choice 3"
    assert [h["said"] for h in t["history"]] == ["session 0", "session 1", "session 2"]
    text = T.relevant_text(f"{WEB['title']} again", tmp_path)
    assert "Decided earlier: choice 2 | choice 1 | choice 0" in text


def test_a_new_decision_replaces_the_old_one_at_the_top_only(tmp_path):
    slug = T._slug(WEB["title"])
    T.save({"slug": slug, "title": WEB["title"], "said": "a", "decided": "use SQLite"}, tmp_path)
    T.save({"slug": slug, "title": WEB["title"], "said": "b", "decided": "use Postgres"}, tmp_path)
    t = T.load(tmp_path)[0]
    assert t["decided"] == "use Postgres" and t["history"][0]["decided"] == "use SQLite"


def test_old_thread_files_without_history_still_load(tmp_path):
    (tmp_path / "old.md").write_text("---\ntitle: Old\nproject: -\nupdated: 2026-11-11 10:00\n---\nSaid: x\n"
                                     "Decided: -\nOpen: -\n", encoding="utf-8")
    t = T.load(tmp_path)[0]
    assert t["said"] == "x" and t["history"] == []
    T.save({"slug": "old", "title": "Old", "said": "y"}, tmp_path)
    assert [h["said"] for h in T.load(tmp_path)[0]["history"]] == ["x"]
    assert not list(tmp_path.glob("*.tmp"))



def test_a_history_line_without_a_date_is_kept(tmp_path):
    """Review: an old version saved with no 'updated' was written as '- - · said: ...' and dropped next time."""
    (tmp_path / "t.md").write_text("---\ntitle: T\nproject: -\nupdated: \n---\nSaid: first\nDecided: -\nOpen: -\n",
                                   encoding="utf-8")
    T.save({"slug": "t", "title": "T", "said": "second"}, tmp_path)
    T.save({"slug": "t", "title": "T", "said": "third"}, tmp_path)
    assert [h["said"] for h in T.load(tmp_path)[0]["history"]] == ["first", "second"]



# -- links are kept (partial -> done, 2026-11-15) --

def test_links_come_from_the_conversation_not_the_summary(tmp_path):
    """A small model dropped the links from its summary; they are taken from the turns themselves now."""
    rec, root = tmp_path / "chat.jsonl", tmp_path / "th"
    _record(rec, [("read https://fastapi.tiangolo.com/tutorial/ for the ratings api",
                   "Done: the route is in api/ratings.py:14, tests in tests/test_ratings.py.")])
    reply = '[{"slug": "ratings-api", "title": "Ratings API", "said": "We built the ratings route.", "decided": "-"}]'

    class LLM:
        def invoke(self, messages):
            return AIMessage(content=reply)

    T.summarize(LLM(), rec, "proj", root)
    links = T.load(root)[0]["links"]
    assert links == ["https://fastapi.tiangolo.com/tutorial/", "api/ratings.py:14", "tests/test_ratings.py"]
    assert "Links: https://fastapi.tiangolo.com/tutorial/" in T.relevant_text("the ratings api again", root)


def test_links_are_only_ever_added(tmp_path):
    T.save({**WEB, "links": ["https://a.example/1"]}, tmp_path)
    T.save({**WEB, "said": "later", "links": ["https://b.example/2", "https://a.example/1"]}, tmp_path)
    assert T.load(tmp_path)[0]["links"] == ["https://a.example/1", "https://b.example/2"]
    T.save({**WEB, "said": "even later"}, tmp_path)                       # a summary with no links keeps them
    assert T.load(tmp_path)[0]["links"] == ["https://a.example/1", "https://b.example/2"]


def test_with_two_threads_each_gets_the_links_of_its_own_turns(tmp_path):
    turns = [{"user": "the ratings web app: see https://fastapi.tiangolo.com", "answer": "ratings stored in db.py"},
             {"user": "the snake game speed", "answer": "snake speed is in snake/game.py:40"}]
    web = T._links_for({"title": "Ratings web app", "said": "ratings web app with fastapi"}, turns, alone=False)
    snake = T._links_for({"title": "Snake speed", "said": "snake game speed"}, turns, alone=False)
    assert web == ["https://fastapi.tiangolo.com", "db.py"] and snake == ["snake/game.py:40"]


def test_codemitra_no_longer_says_threads_lose_links():
    from app.core import chat as C
    assert "lose details such as links" not in C.ABOUT_CODEMITRA
