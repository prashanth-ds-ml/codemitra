"""Must-have 10 (D-077): general web search by SearXNG on the Kaggle notebook. The proxy sends /<token>/search to
SearXNG and everything else to Ollama; the chat uses it only when the notebook's engine test passed, and falls back
to its own sources (Wikipedia, GitHub, arXiv, Hugging Face, Ollama) otherwise. Nothing here may stop the model."""
import importlib.util
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import kaggle, remote
from app.agents import web
from tests.test_kaggle import FakeApi, fake_quota  # noqa: F401 (a fixture)

KAGGLE_DIR = Path(__file__).resolve().parents[1] / "remote" / "kaggle"
HITS = {"results": [
    {"url": "https://blog.example.com/qwen", "title": "Qwen 3.5 review", "content": "A long  review.",
     "engines": ["duckduckgo", "brave"]},
    {"url": "https://blog.example.com/qwen", "title": "duplicate", "content": ""},
    {"url": "https://news.example.org/x", "title": "News", "content": "Today", "engine": "bing"},
    {"url": "javascript:alert(1)", "title": "bad"}]}


class _Fake(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        _Fake.seen.append(self.path)
        body = json.dumps(HITS if self.path.startswith("/search") else {"models": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def stack():
    """The real proxy, with a fake SearXNG and a fake Ollama behind it."""
    fake_search = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    fake_ollama = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    spec = importlib.util.spec_from_file_location("kaggle_proxy10", KAGGLE_DIR / "proxy.py")
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    px = proxy.serve("tok", 0, f"127.0.0.1:{fake_ollama.server_address[1]}", None,
                     search=f"127.0.0.1:{fake_search.server_address[1]}")
    for s in (fake_search, fake_ollama, px):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    _Fake.seen = []
    yield f"http://127.0.0.1:{px.server_address[1]}/tok"
    for s in (fake_search, fake_ollama, px):
        s.shutdown()


def test_the_proxy_sends_search_to_searxng_and_the_rest_to_ollama(stack):
    with urllib.request.urlopen(stack + "/search?q=x&format=json", timeout=10) as r:
        assert json.loads(r.read())["results"]
    with urllib.request.urlopen(stack + "/api/tags", timeout=10) as r:
        assert json.loads(r.read()) == {"models": []}
    assert _Fake.seen == ["/search?q=x&format=json", "/api/tags"]


def test_results_are_the_whole_web_deduplicated_and_labelled(stack):
    found = web.searx_search("qwen 3.5 review", url=stack + "/search")
    assert [r.url for r in found] == ["https://blog.example.com/qwen", "https://news.example.org/x"]
    assert found[0].source == "web: duckduckgo/brave" and found[0].snippet == "A long review."


def test_the_chat_uses_it_only_when_the_notebooks_test_passed(stack, monkeypatch):
    monkeypatch.setattr(web, "is_online", lambda timeout=1.5: True)
    remote.set_remote(stack, 262144, "kaggle")
    try:
        kaggle.save_state({"token": "tok", "search": False})
        monkeypatch.setattr("app.agents.search_sources.search", lambda q, per_source=4: ([], {"x": "offline"}))
        assert "blog.example.com" not in web.search_web.invoke({"query": "qwen review"})
        kaggle.save_state({"token": "tok", "search": True})
        out = web.search_web.invoke({"query": "qwen review"})
        assert "blog.example.com/qwen" in out and "[web: duckduckgo/brave]" in out
    finally:
        remote.clear()


def test_a_broken_search_falls_back_to_the_open_apis():
    assert web.searx_search("x", url="http://127.0.0.1:9/search") == []
    assert web.searx_search("x") == []                           # no Kaggle session: not even tried


def test_the_notebooks_search_line_is_remembered(monkeypatch, fake_quota):
    api = FakeApi(["MITRA|started|model=m|context=262144", "MITRA|search|ok=True|results=27",
                   "MITRA|ready|url=https://a-b.trycloudflare.com|model=m"])
    monkeypatch.setattr(remote, "probe", lambda url, timeout=20: ([{"name": "m"}], ""))
    said = []
    kaggle.start("m", 262144, echo=said.append, api=api, sleep=lambda s: None)
    assert kaggle.load_state()["search"] is True and any("web search ready (27 results" in s for s in said)
    remote.clear()


def test_the_notebook_starts_search_in_the_background_and_never_lets_it_stop_the_model():
    spec = importlib.util.spec_from_file_location("build_nb10", KAGGLE_DIR / "build_notebook.py")
    nb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nb)
    cells = ["".join(c["source"]) for c in nb.build()["cells"]]
    start = next(i for i, c in enumerate(cells) if "SearXNG (metasearch)" in c)
    check = next(i for i, c in enumerate(cells) if "an engine test" in c)
    pull = next(i for i, c in enumerate(cells) if "ollama pull" in c)
    tunnel = next(i for i, c in enumerate(cells) if "cloudflared" in c)
    assert start < pull < check < tunnel                        # installs while the model downloads
    assert "subprocess.Popen" in cells[start] and "except Exception" in cells[start]
    assert "searx is not None" in cells[check] and "raise" not in cells[check]
    assert "format: [html, json]" not in cells[start] and "formats: [html, json]" in nb.SEARX_SETTINGS
    for c in (cells[start], cells[check]):
        compile(c, "cell", "exec")                              # plain Python (no ! lines)


def test_searxng_is_installed_with_uv_not_a_plain_venv():
    """Live on Kaggle 2026-11-15: Kaggle's Python 3.13 cannot make a plain venv (ensurepip failed); uv can."""
    spec = importlib.util.spec_from_file_location("build_nb10b", KAGGLE_DIR / "build_notebook.py")
    nb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nb)
    script = next("".join(c["source"]) for c in nb.build()["cells"] if "SearXNG (metasearch)" in "".join(c["source"]))
    assert "python -m uv venv" in script and "python -m venv" not in script and "ensurepip" not in script
