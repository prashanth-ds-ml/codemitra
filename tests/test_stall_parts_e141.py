"""E-141 (live 2026-11-17, mitra-try turn 6): "update all this in a markdown file and save it" went to the change phase,
and the 9B (partly on the CPU, 1.3 GB RAM free, 8.5 tokens/s) started writing the whole document as ONE write_file
call. Ollama sends a tool call only when it is complete, so nothing arrived for 5 min and the turn stopped with
"Ollama may be stuck", which it was not. A tester hit the same on Kaggle, where the tunnel cuts a call silent for 120 s.
Now long files are written in parts of ~60 lines, and a stall gets one retry asking for smaller parts."""
import httpx
from langchain_core.messages import AIMessage

from app.core import chat as C
from app.core import tools as T
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard

ASK = "great why dont you update all this in a markdown file and save it so we can continue later"


class StallsOnce(Heard):
    """The first call sends nothing until httpx's read timeout (the whole file in one call); the next one answers."""

    def stream(self, messages):
        if not self.heard:
            self.heard.append([m.content for m in messages])
            raise httpx.ReadTimeout("timed out")
        return super().stream(messages)


def test_a_laptop_stall_is_retried_once_in_smaller_parts(tmp_path):
    m = StallsOnce(AIMessage(content="Saved the first part to NOTES.md; adding the rest next."))
    s = _session(tmp_path, m)
    s.backend_kind = "laptop"
    res = s.turn(_msgs(ASK))
    assert not res.stopped and "first part" in res.text
    assert len(m.heard) == 2 and m.heard[1][-1] == C.SLOW_NOTE      # the retry asked for parts
    rows = _rows(s)
    assert any(r["kind"] == "model_error" and r.get("stalled") and r.get("retry") for r in rows)


def test_the_parts_are_small_enough_for_a_slow_laptop_and_the_tunnel():
    """~60 lines of a document is about 1,000-1,500 tokens: under 3 min at 8.5 tokens/s, and well under the tunnel's
    120 s on Kaggle. The old advice (~150 lines, 2-3K tokens) was itself too long for the laptop."""
    append = next(t for t in T.TOOL_SPECS if t["name"] == "append_file")["description"]
    for text in (C.SLOW_NOTE, append, C.PHASES["make_change"]["note"]):
        assert "~60 lines" in text and "150" not in text


def test_the_change_phase_says_so_before_the_first_write():
    note = C.PHASES["make_change"]["note"]
    assert "append_file" in note and "write_file" in note


def test_a_second_stall_stops_with_the_likely_cause_first():
    text = C.STALL_STOP.format(min=20)
    assert text.startswith("the model sent nothing for 20 min twice")
    assert "in parts" in text and "/free" in text


# ── the laptop: a stall limit from this machine's measured speed ─────────────────────────────────────────────────
def test_the_stall_limit_allows_the_longest_reply_at_this_machines_speed():
    from app import llm as L
    assert L.stall_for(None) == L.STREAM_STALL_S == 300            # unknown speed: as before
    assert L.stall_for(28) == int(1.3 * L.MAX_OUTPUT_TOKENS / 28)  # this laptop with the 9B on the GPU: ~6 min
    assert L.stall_for(8.5) == L.STALL_MAX_S == 1200               # the live turn: 9B partly on the CPU
    assert L.stall_for(500) == 300                                 # never below the old limit


def test_set_stall_changes_the_clients_read_timeout():
    from app import llm as L
    m = L.get_local_llm("qwen3.5:4b", reasoning=None)
    assert L.set_stall(m, 900) and m._client._client.timeout.read == 900
    assert not L.set_stall(object(), 900)


class Timed(Heard):
    """Replies that carry Ollama's timing metadata, as a real stream's last chunk does."""

    def __init__(self, *replies):
        super().__init__(*replies)
        self.timeouts = []
        self._client = type("C", (), {"_client": type("H", (), {"timeout": None})()})()

    def stream(self, messages):
        self.timeouts.append(self._client._client.timeout)
        return super().stream(messages)


def test_the_chat_measures_the_speed_and_sets_the_next_calls_limit(tmp_path):
    first = AIMessage(content="", tool_calls=[{"name": "list_files", "args": {"path": "."}, "id": "1"}],
                      response_metadata={"eval_count": 97, "eval_duration": int(11.48e9)})   # the live step 1
    m = Timed(first, AIMessage(content="done"))
    s = _session(tmp_path, m)
    s.backend_kind = "laptop"
    s.turn(_msgs("list the files"))
    assert round(s.gen_tps, 1) == 8.4 and s.stall_s == 1200
    assert m.timeouts[0].read == 300 and m.timeouts[1].read == 1200


# ── Kaggle: the proxy keeps the tunnel open while a tool call is written ─────────────────────────────────────────
import importlib.util  # noqa: E402
import json  # noqa: E402
import pathlib  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import pytest  # noqa: E402

KAGGLE = pathlib.Path(__file__).resolve().parents[1] / "remote" / "kaggle"
CALL = {"name": "write_file", "arguments": {"path": "NOTES.md", "content": "# Notes\n" + "line\n" * 500}}


class SilentToolCall(BaseHTTPRequestHandler):
    """Like Ollama writing a whole file as one tool call: no headers, no bytes for `silent` s, then the call at once."""
    protocol_version = "HTTP/1.1"
    silent = 1.6
    status = 200

    def log_message(self, *a):
        pass

    def handle(self):
        try:
            super().handle()
        except ConnectionError:
            pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        time.sleep(self.silent)
        if self.status != 200:
            body = json.dumps({"error": "model 'nope' not found"}).encode()
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for part in ({"model": "m", "created_at": "2026-11-17T10:00:00Z",
                      "message": {"role": "assistant", "content": "", "tool_calls": [{"function": CALL}]}, "done": False},
                     {"model": "m", "created_at": "2026-11-17T10:00:01Z", "message": {"role": "assistant", "content": ""},
                      "done": True, "done_reason": "stop"}):
            line = json.dumps(part).encode() + b"\n"
            self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")


@pytest.fixture
def slow_stack():
    spec = importlib.util.spec_from_file_location("kaggle_proxy_e141", KAGGLE / "proxy.py")
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    proxy.KEEPALIVE_S = 0.3
    SilentToolCall.status = 200
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), SilentToolCall)]
    servers.append(proxy.serve("tok", 0, f"127.0.0.1:{servers[0].server_address[1]}"))
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servers[1].server_address[1]}/tok"
    for srv in servers:
        srv.shutdown()


def test_the_proxy_answers_at_once_and_keeps_the_line_alive(slow_stack):
    import httpx
    t0 = time.time()
    with httpx.stream("POST", slow_stack + "/api/chat", json={"model": "m", "messages": []}, timeout=1.0) as r:
        first = time.time() - t0
        lines = [json.loads(x) for x in r.iter_lines() if x]
    assert r.status_code == 200 and first < 1.0          # headers before Ollama sends anything (it waits 1.6 s)
    assert sum(1 for x in lines if x["message"]["content"] == "" and not x["message"].get("tool_calls")
               and not x["done"]) >= 3                    # keep-alives while it was silent (read timeout 1 s never hit)
    assert lines[-2]["message"]["tool_calls"][0]["function"] == CALL and lines[-1]["done"]


def test_ollamas_own_client_reads_it_and_gets_the_tool_call_intact(slow_stack):
    import ollama
    parts = list(ollama.Client(host=slow_stack, timeout=1.0).chat(model="m", messages=[], stream=True))
    calls = [tc for p in parts for tc in (p.message.tool_calls or [])]
    assert len(calls) == 1 and calls[0].function.arguments == CALL["arguments"]
    assert "".join(p.message.content or "" for p in parts) == ""


def test_an_ollama_error_still_reaches_codemitra_as_an_error(slow_stack):
    import ollama
    SilentToolCall.status = 404
    with pytest.raises(ollama.ResponseError, match="not found"):
        list(ollama.Client(host=slow_stack, timeout=5).chat(model="nope", messages=[], stream=True))


def test_only_streamed_chat_is_kept_alive():
    spec = importlib.util.spec_from_file_location("kaggle_proxy_e141b", KAGGLE / "proxy.py")
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    assert proxy.streamed_chat("POST", "/api/chat", b'{"model": "m"}') == "m"
    assert proxy.streamed_chat("POST", "/api/chat", b'{"model": "m", "stream": false}') is None
    assert proxy.streamed_chat("GET", "/api/tags", None) is None
    assert proxy.streamed_chat("POST", "/api/generate", b'{"model": "m"}') is None
