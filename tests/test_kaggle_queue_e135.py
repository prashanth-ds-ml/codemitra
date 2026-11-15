"""E-135 (live 2026-11-15): Kaggle held the run in its queue for over 20 minutes; `kaggle start` counted the queue time
against its 20-minute wait and gave up; the server came up later, nobody connected, and it stopped itself after 30
minutes unused (0.4 GPU hours). A second `kaggle start` would have said "already running: CodeMitra uses it" because
an address from an earlier run was still saved."""
from datetime import datetime, timezone

import pytest

from app import kaggle, remote
from tests.test_kaggle import FakeApi


@pytest.fixture
def fake_quota(monkeypatch):
    q = {"used_h": 1.0, "total_h": 30.0, "left_h": 29.0, "refresh": datetime(2026, 11, 21, tzinfo=timezone.utc)}
    monkeypatch.setattr(kaggle, "quota", lambda api: dict(q))
    return q


class Clock:
    """Time moves only when the code sleeps: 10 s per queued poll."""

    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


READY = ["MITRA|loaded|model=m|gb=6|context=262144|where=fully on GPU",
         "MITRA|ready|url=https://new-run.trycloudflare.com|model=m"]


def test_queue_time_does_not_eat_the_ready_wait(monkeypatch, fake_quota):
    """35 minutes queued (more than wait_min=20), then it runs and gets ready: connected, not given up."""
    clock = Clock()
    api = FakeApi(READY, statuses=["QUEUED"] * 210 + ["RUNNING"])  # 210 polls x 10 s = 35 min in the queue
    monkeypatch.setattr(remote, "probe", lambda url, timeout=20: ([{"name": "m"}], ""))
    state = {"ref": "someone/codemitra-gpu-server", "token": "tok", "model": "m", "url": "u"}
    data = kaggle._follow(api, state["ref"], state, 262144, 20, lambda s: None, clock.sleep, clock=clock)
    assert data["url"] == "https://new-run.trycloudflare.com/tok"
    assert clock.t - 1_000_000.0 >= 35 * 60
    remote.clear()


def test_a_queue_longer_than_the_limit_says_so_plainly(fake_quota):
    clock = Clock()
    api = FakeApi([], statuses=["QUEUED"])
    state = {"ref": "r", "token": "t", "url": "u"}
    with pytest.raises(kaggle.KaggleError, match="Still in Kaggle's queue after 5 minutes .no GPU hours used"):
        kaggle._follow(api, "r", state, 262144, 20, lambda s: None, clock.sleep, queue_min=5, clock=clock)


def test_an_old_address_is_not_this_run():
    old = {"name": "kaggle", "url": "https://old-run.trycloudflare.com/oldtok"}
    assert not kaggle._connected(old, {"public": "https://new-run.trycloudflare.com"})
    assert not kaggle._connected(old, {})  # the new run is not ready yet: no public address
    assert kaggle._connected({"name": "kaggle", "url": "https://new-run.trycloudflare.com/tok"},
                             {"public": "https://new-run.trycloudflare.com/"})
    assert not kaggle._connected(None, {"public": "https://x"})


def test_start_again_follows_a_running_run_left_with_an_old_address(monkeypatch, fake_quota):
    remote.set_remote("https://old-run.trycloudflare.com/oldtok", 262144, "kaggle")
    # the new run's state (a push writes it fresh: no `public` until the run is ready)
    kaggle.save_state({"ref": "someone/codemitra-gpu-server", "token": "tok", "model": "m", "ctx": 262144, "url": "u"})
    api = FakeApi(READY, statuses=["RUNNING"])
    monkeypatch.setattr(remote, "probe", lambda url, timeout=20: ([{"name": "m"}], ""))
    said = []
    data = kaggle.start("m", echo=said.append, api=api, sleep=lambda s: None)
    assert not any("CodeMitra uses it" in s for s in said) and any("following it" in s for s in said)
    assert api.pushed == []  # followed, not pushed again
    assert data["url"] == "https://new-run.trycloudflare.com/tok"
    remote.clear()


def test_status_says_how_to_connect_to_a_run_nobody_follows(monkeypatch, fake_quota):
    remote.set_remote("https://old-run.trycloudflare.com/oldtok", 262144, "kaggle")
    kaggle.save_state({"ref": "someone/codemitra-gpu-server", "token": "tok", "model": "m", "ctx": 262144, "url": "u"})
    monkeypatch.setattr(remote, "probe", lambda url, timeout=15: ([], "not answering"))
    said = []
    kaggle.status(echo=said.append, api=FakeApi([], statuses=["RUNNING"]))
    assert any("not connected to this run yet" in s and "codemitra kaggle start" in s for s in said)
    remote.clear()
