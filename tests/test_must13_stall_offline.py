"""Must-have 13 (D-077): a model stream never waits forever (E-081), and no internet on this machine is not
"Kaggle ended" (Kaggle keeps running and is used again when you are back online)."""
import httpx
from langchain_core.messages import AIMessage

from app import backend as B
from app import llm as L
from app.core import chat as C
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard


def test_every_model_client_has_a_stall_limit_not_a_total_limit():
    m = L.get_local_llm("qwen3.5:4b", reasoning=None)
    t = m.client_kwargs["timeout"]
    assert t.read == L.STREAM_STALL_S == 300 and t.connect == L.CONNECT_S
    assert L.is_stalled(httpx.ReadTimeout("timed out")) and not L.is_stalled(RuntimeError("boom"))


class Stalls(Heard):
    def stream(self, messages):
        self.heard.append([m.content for m in messages])
        raise httpx.ReadTimeout("timed out")
        yield  # noqa: unreachable: a generator, like a real stream


def test_a_stalled_laptop_model_stops_the_turn_and_says_why(tmp_path):
    m = Stalls(AIMessage(content="never"))
    s = _session(tmp_path, m)
    s.backend_kind = "laptop"
    res = s.turn(_msgs("explain the code"))
    assert res.stopped and "sent nothing for 5 min" in res.stop_reason and "/free" in res.stop_reason
    assert len(m.heard) == 1                                   # no wrap-up call into the same stuck model
    assert any(r["kind"] == "model_error" and r.get("stalled") for r in _rows(s))


def _health(online):
    return B.Health(probe=lambda url: ([], "getaddrinfo failed"), active=lambda: {"url": "u", "name": "kaggle"},
                    clock=lambda: 1000.0, online=lambda: online)


def test_no_internet_here_is_offline_not_down():
    assert _health(online=False).check().state == "offline"
    assert _health(online=True).check().state == "down"       # online and no answer: Kaggle really is gone


def test_the_status_line_says_offline_and_that_kaggle_waits():
    s = B.HealthState(state="offline", name="kaggle")
    text, level = B.status_text(B.REMOTE, "qwen3.5:9b", 262_144, s)
    assert "offline" in text and level == "warn"
    assert "kaggle waits" in B.status_text(B.LAPTOP, "qwen3.5:4b", 65_536, s)[0]


def test_the_chat_moves_to_the_laptop_when_offline_and_keeps_kaggle():
    """The two places in the chat that used to end Kaggle on any failed check now ask: offline, or gone?"""
    import inspect

    from app import main
    src = inspect.getsource(main)
    assert src.count("_to_laptop(OFFLINE_KAGGLE)") == 2 and '_hstate == "offline"' in src
    assert "Kaggle keeps running" in main.OFFLINE_KAGGLE
    assert C.is_remote_down(httpx.ReadTimeout("timed out"))   # a stalled tunnel is still handled as the remote's
