"""Token proxy in front of Ollama, for the Kaggle notebook (D-060). Standard library only.

Ollama has no login, and the Cloudflare quick tunnel makes it public. This proxy answers only requests whose path
starts with /<token>/ (e.g. /<token>/api/chat), strips the token and forwards the rest to Ollama, streaming the reply
back as it comes (chat replies arrive token by token). Anything else gets 404, so a found URL without the token is
useless.

    python proxy.py <token> [port=8000] [ollama=127.0.0.1:11434] [state_dir]

With a state_dir (the notebook passes /kaggle/working): `POST /<token>/mitra/stop` writes `stop` there (the notebook
then shuts everything down, which ends the Kaggle run), and every model request touches `last_request`, so the
notebook can stop by itself when CodeMitra has not used it for a while.
"""
from __future__ import annotations

import hmac
import json
import http.client
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

QUIET = {"/api/tags", "/api/ps", "/api/version", "/api/show"}  # status checks: not "CodeMitra is using it"
SEARCH_UPSTREAM = "127.0.0.1:8888"  # SearXNG, started by the notebook (must-have 10); /<token>/search goes there

HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "host", "content-length"}


KEEPALIVE_S = 30  # E-141: well under Cloudflare's ~100 s and CodeMitra's 300 s read timeout


def streamed_chat(command: str, tail: str, body: bytes | None) -> str | None:
    """The model name when this is a streamed POST /api/chat (Ollama streams unless "stream": false), else None."""
    if command != "POST" or tail.split("?")[0] != "/api/chat" or not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("stream") is False:
        return None
    return str(data.get("model") or "")


def keepalive_line(model: str) -> bytes:
    """An empty assistant chunk: Ollama's client parses it, it adds no text, and it is not the last one."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return (json.dumps({"model": model, "created_at": now, "message": {"role": "assistant", "content": ""},
                        "done": False}) + "\n").encode()


def error_line(status: int, raw: bytes) -> bytes:
    """Ollama's own {"error": ...} when it sent one, else the status; one line, so the client raises it."""
    try:
        data = json.loads(raw or b"{}")
        msg = data.get("error") if isinstance(data, dict) else None
    except ValueError:
        msg = None
    text = msg or (raw.decode("utf-8", "replace").strip()[:300] or f"ollama answered {status}")
    return (json.dumps({"error": text}) + "\n").encode()


def _touch(path: str) -> None:
    with open(path, "a", encoding="utf-8"):
        pass
    os.utime(path, None)


def make_handler(token: str, upstream: str, state_dir: str | None = None, search: str = SEARCH_UPSTREAM):
    host, _, port = upstream.partition(":")
    port_n = int(port or 11434)
    s_host, _, s_port = search.partition(":")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the notebook quiet; the token must not appear in logs
            pass

        def handle(self) -> None:  # a client that hangs up on a kept-open connection is normal, not an error
            try:
                super().handle()
            except ConnectionError:
                pass

        def _refuse(self) -> None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _forward(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None  # read first: a refused client gets a clean 404
            parts = self.path.split("/", 2)  # "", token, rest
            if len(parts) < 2 or not hmac.compare_digest(parts[1].encode(), token.encode()):
                self._refuse()
                return
            tail = "/" + (parts[2] if len(parts) > 2 else "")
            if tail.startswith("/mitra/"):  # CodeMitra's own commands, never forwarded to Ollama
                ok = tail == "/mitra/ping" or (tail == "/mitra/stop" and state_dir is not None)
                if ok and tail == "/mitra/stop":
                    _touch(os.path.join(state_dir, "stop"))
                msg = (b'{"ok": true, "time": %d}' % int(time.time())) if ok else b'{"ok": false}'
                self.send_response(200 if ok else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            if state_dir is not None and tail.split("?")[0] not in QUIET:
                _touch(os.path.join(state_dir, "last_request"))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            model = streamed_chat(self.command, tail, body)
            if model is not None:  # E-141: keep the tunnel open while a long tool call is being written
                self._forward_chat(headers, tail, body, model)
                return
            if tail.split("?")[0] == "/search":  # must-have 10: web search by SearXNG on this machine
                conn = http.client.HTTPConnection(s_host, int(s_port or 8888), timeout=60)
            else:
                conn = http.client.HTTPConnection(host, port_n, timeout=3600)  # a long generation is normal
            try:
                conn.request(self.command, tail, body=body, headers=headers)
                resp = conn.getresponse()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (ConnectionError, OSError) as exc:
                try:
                    msg = f'{{"error": "proxy: {type(exc).__name__}"}}'.encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(msg)))
                    self.end_headers()
                    self.wfile.write(msg)
                except OSError:
                    pass
            finally:
                conn.close()

        def _chunk(self, data: bytes) -> None:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        def _forward_chat(self, headers: dict, tail: str, body: bytes, model: str) -> None:
            """E-141: a streamed /api/chat. Ollama sends a tool call only when it is complete and sends no headers until
            its first chunk, so a whole file written as one tool call was silent for minutes and Cloudflare's tunnel
            closed it (524 after ~100 s). Headers go out at once, then an empty chunk every KEEPALIVE_S while Ollama is
            silent; an upstream failure arrives as an {"error": ...} line, which Ollama's client raises."""
            q: queue.Queue = queue.Queue()

            def pump() -> None:
                conn = http.client.HTTPConnection(host, port_n, timeout=3600)
                try:
                    conn.request(self.command, tail, body=body, headers=headers)
                    resp = conn.getresponse()
                    if resp.status != 200:
                        q.put(("error", error_line(resp.status, resp.read())))
                        return
                    while True:
                        data = resp.read1(65536)
                        if not data:
                            break
                        q.put(("data", data))
                except (ConnectionError, OSError) as exc:
                    q.put(("error", error_line(502, f"proxy: {type(exc).__name__}".encode())))
                finally:
                    conn.close()
                    q.put(("end", b""))

            threading.Thread(target=pump, daemon=True).start()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.flush()
                at_line_start = True
                while True:
                    try:
                        kind, data = q.get(timeout=KEEPALIVE_S)
                    except queue.Empty:
                        if at_line_start:
                            self._chunk(keepalive_line(model))
                        continue
                    if kind == "end":
                        break
                    self._chunk(data)
                    at_line_start = data.endswith(b"\n")
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError:
                pass  # CodeMitra went away; the pump thread ends with Ollama's reply

        do_GET = do_POST = do_DELETE = do_PUT = _forward

    return Handler


def serve(token: str, port: int = 8000, upstream: str = "127.0.0.1:11434",
          state_dir: str | None = None, search: str = SEARCH_UPSTREAM) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, upstream, state_dir, search))
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    tok = sys.argv[1]
    prt = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    up = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1:11434"
    state = sys.argv[4] if len(sys.argv) > 4 else None
    print(f"proxy on 127.0.0.1:{prt} -> {up}", flush=True)
    serve(tok, prt, up, state).serve_forever()
