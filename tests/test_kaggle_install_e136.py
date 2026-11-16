"""E-136 (issue #13, 2026-11-16): a tester's `kaggle start` showed "installing Ollama" and then nothing. The install
downloads 1.5 GB with no time limit and CodeMitra printed nothing while it ran; a stuck install would have run until
Kaggle's 11.5 h limit, because the idle stop starts only once the server is ready."""
import json

from app import kaggle, remote
from remote.kaggle import build_notebook
from tests.test_kaggle import FakeApi


def _source(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def test_the_notebook_stops_itself_when_not_ready_in_time():
    for nb in (build_notebook.build(), build_notebook.build({"model": "m", "ctx": 262144, "token": "t"})):
        src = _source(nb)
        assert "threading.Thread(target=_ready_watchdog" in src
        assert "os.kill(os.getpid(), signal.SIGKILL)" in src
        # the watchdog starts before the install and stands down only when ready
        assert src.index("_ready_watchdog, daemon=True).start()") < src.index('say("installing"')
        assert src.index("open(READY_FILE, \"w\").close()") < src.index('say("ready"')
    assert kaggle.READY_MAX_MIN == 45 and "READY_MAX_MIN = 45" in _source(build_notebook.build())


def test_the_install_has_time_limits_a_retry_and_says_why_it_failed():
    src = _source(build_notebook.build())
    assert "!curl -fsSL https://ollama.com/install.sh | sh" not in src  # no unlimited download any more
    assert "timeout=minutes * 60" in src and "for attempt in (1, 2):" in src
    assert 'say("error", detail="could not install Ollama (tried twice): "' in src


def test_the_saved_notebook_matches_the_builder():
    saved = json.loads((build_notebook.HERE / "codemitra_kaggle_server.ipynb").read_text(encoding="utf-8"))
    assert _source(saved) == _source(build_notebook.build())


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        self.t += 20  # every look at the clock is 20 s later: the install takes minutes
        return self.t


def test_a_long_step_says_it_is_still_going(monkeypatch):
    api = FakeApi(["MITRA|started|model=m|context=262144", "MITRA|installing|gb=1.5"] + [""] * 30,
                  statuses=["RUNNING"])
    said = []
    state = {"ref": "r", "token": "t", "url": "u"}
    try:
        kaggle._follow(api, "r", state, 262144, 20, said.append, lambda s: None, clock=Clock())
    except kaggle.KaggleError as exc:
        assert "stops itself if it is not ready 45 minutes" in str(exc) and "codemitra kaggle stop" in str(exc)
    assert any("installing Ollama (a 1.5 GB download" in s for s in said)
    assert any(s.startswith("  · still installing Ollama · ") for s in said)
    remote.clear()


def test_the_notebook_reports_a_failed_install():
    api = FakeApi(["MITRA|installing|gb=1.5",
                   "MITRA|error|detail=could not install Ollama (tried twice): curl: (28) Operation timed out"])
    try:
        kaggle._follow(api, "r", {"ref": "r", "token": "t", "url": "u"}, 262144, 20, lambda s: None, lambda s: None)
    except kaggle.KaggleError as exc:
        assert "could not install Ollama" in str(exc)
    else:
        raise AssertionError("a failed install must stop the wait")
