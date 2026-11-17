"""I-34 (issue #13, 2026-11-17): saran had a key and 30 GPU hours, but his notebooks got no internet (phone not
verified). Setup with a key already there said "signed in" and never mentioned the phone, and CodeMitra found out
only after a GPU notebook started. Now: one checklist, every step checked live, the done ones shown as done; a small
CPU-only notebook checks the internet before any GPU run; the open step is walked through."""
from datetime import datetime, timezone

import pytest

from app import backend, kaggle
from app import setup_wizard as W
from tests.test_kaggle import FakeApi
from tests.test_setup_d083 import M8, Fake

SARAN_NET = "MITRA|net|ok=False|detail=curl: (28) Resolving timed out after 20000 milliseconds"


@pytest.fixture
def fake_quota(monkeypatch):
    q = {"used_h": 0.0, "total_h": 30.0, "left_h": 30.0, "refresh": datetime(2026, 11, 21, tzinfo=timezone.utc)}
    monkeypatch.setattr(kaggle, "quota", lambda api: dict(q))
    return q


def test_the_internet_check_is_a_private_cpu_only_notebook_that_only_tries_ollama():
    api = FakeApi([])
    ok, detail = kaggle.check_internet(api, "someone", echo=lambda s: None, sleep=lambda s: None)
    assert ok is True and detail == "internet works"
    push = api.net_pushed[0]
    assert push["acc"] is None and push["meta"]["enable_gpu"] is False and push["meta"]["enable_internet"] is True
    assert push["meta"]["is_private"] is True and push["meta"]["id"] == "someone/codemitra-net-check"
    assert "https://ollama.com" in push["code"] and "MITRA|net|ok=" in push["code"]
    assert api.pushed == []  # no GPU notebook
    assert not (kaggle._home() / "kaggle-net").exists()


def test_no_internet_is_found_named_and_remembered():
    api = FakeApi([], net=SARAN_NET)
    ok, detail = kaggle.check_internet(api, "saisarann", echo=lambda s: None, sleep=lambda s: None)
    assert ok is False and "Resolving timed out" in detail
    assert kaggle.internet_known("saisarann") is False and kaggle.internet_known("someone") is None


def test_a_check_that_cannot_tell_is_not_a_failure():
    class Broken(FakeApi):
        def kernels_output(self, ref, path):
            raise OSError("network down")
    ok, detail = kaggle.check_internet(Broken([]), "someone", echo=lambda s: None, sleep=lambda s: None)
    assert ok is None and "network down" in detail
    assert kaggle.internet_known("someone") is None


def test_start_checks_internet_first_and_never_starts_a_gpu_run_without_it(fake_quota):
    api = FakeApi(["MITRA|ready|url=x"], net=SARAN_NET)
    with pytest.raises(kaggle.NoInternet, match="Kaggle account someone: its notebooks get no internet"):
        kaggle.start("m", echo=lambda s: None, api=api, sleep=lambda s: None)
    assert len(api.net_pushed) == 1 and api.pushed == []  # issue #13: no GPU notebook, no GPU hours


def test_start_skips_the_check_once_it_passed(fake_quota):
    backend.save_prefs(kaggle_account="someone")
    kaggle._remember_internet("someone", True)
    api = FakeApi(["MITRA|error|detail=stop here"])
    with pytest.raises(kaggle.KaggleError, match="stop here"):
        kaggle.start("m", echo=lambda s: None, api=api, sleep=lambda s: None)
    assert api.net_pushed == [] and len(api.pushed) == 1


def _lines(steps):
    return "\n".join(kaggle.render(steps))


def test_the_checklist_shows_done_steps_as_done_and_guides_the_first_open_one(fake_quota):
    steps = kaggle.checklist(api=FakeApi([], net=SARAN_NET), probe=True, echo=lambda s: None, sleep=lambda s: None)
    text = _lines(steps)
    assert "✓ 1. Kaggle account  someone" in text
    assert "✓ 2. API key" in text
    assert "✗ 3. Phone verified  its notebooks get no internet, checked just now" in text
    assert "→ " + kaggle.PHONE_FIX in text
    assert "✓ 4. GPU hours" in text and "30.0 h left" in text
    assert "· 5. First GPU run   not yet" in text
    assert "Ready" not in text


def test_everything_done_says_ready(fake_quota):
    kaggle._remember_internet("someone", True)
    kaggle.save_state({"ref": "someone/codemitra-gpu-server", "started": 1_763_000_000})
    text = _lines(kaggle.checklist(api=FakeApi([])))
    assert text.count("✓") == 5 and "✗" not in text and "Ready: CodeMitra starts Kaggle by itself" in text


def test_without_a_key_the_key_step_is_the_open_one(monkeypatch):
    monkeypatch.setattr(kaggle, "has_key", lambda: False)
    text = _lines(kaggle.checklist())
    assert "· 1. Kaggle account" in text and "sign up free" in text
    assert "✗ 2. API key" in text and "Generate New Token" in text
    assert "· 3. Phone verified" in text and "✓" not in text


def test_zero_gpu_hours_marks_the_phone_without_a_check(fake_quota):
    fake_quota.update(total_h=0.0, left_h=0.0)
    api = FakeApi([])
    text = _lines(kaggle.checklist(api=api))
    assert "✗ 3. Phone verified  not yet (Kaggle shows 0 GPU hours)" in text and api.net_pushed == []


def test_status_shows_the_checklist(fake_quota):
    said = []
    kaggle.status(echo=said.append, api=FakeApi([]))
    assert said[0] == "Kaggle setup" and any("✓ 1. Kaggle account" in s for s in said)
    assert any("not checked yet: `codemitra kaggle check`" in s for s in said)


class Flip(FakeApi):
    """No internet until the user verifies the phone (the second check)."""

    def kernels_output(self, ref, path):
        self.net = SARAN_NET if len(self.net_pushed) < 2 else "MITRA|net|ok=True|detail="
        super().kernels_output(ref, path)


def test_the_guide_opens_the_page_waits_for_done_and_checks_again(fake_quota):
    api, said, opened = Flip([]), [], []
    answers = iter(["", "done"])
    assert kaggle.guide(echo=said.append, ask=lambda q: next(answers), open_url=opened.append,
                        api_factory=lambda: api, sleep=lambda s: None)
    assert opened == [kaggle.SETTINGS_URL] and len(api.net_pushed) == 2
    text = "\n".join(said)
    assert "✗ 3. Phone verified" in text and "✓ 3. Phone verified  notebooks get internet (checked just now)" in text


def test_the_guide_stops_politely_when_you_say_later(fake_quota):
    said = []
    assert not kaggle.guide(echo=said.append, ask=lambda q: "n" if "browser" in q else "",
                            open_url=lambda u: None, api_factory=lambda: FakeApi([], net=SARAN_NET),
                            sleep=lambda s: None)
    assert "later: `codemitra kaggle check`" in said[-1]


def test_setup_with_a_key_already_there_checks_the_phone_too(monkeypatch, tmp_path, fake_quota):
    """The path saran took: a key on the machine. It used to say "signed in" and stop."""
    key = tmp_path / "kaggle.json"
    key.write_text('{"username": "someone", "key": "k"}', encoding="utf-8")
    monkeypatch.setattr(kaggle, "key_path", lambda: key)
    monkeypatch.setattr(kaggle, "token_path", lambda: tmp_path / "access_token")
    api = FakeApi([], net=SARAN_NET)
    monkeypatch.setattr(kaggle, "client", lambda: api)
    f = Fake(answers=["y", "n", ""])  # use Kaggle: yes · open the page: no · done: later
    r = W.step_kaggle(f.io(), M8, auto=False)
    said = "\n".join(f.said)
    assert r.ok is False and "codemitra kaggle check" in r.note
    assert "✓ 1. Kaggle account" in said and "✗ 3. Phone verified" in said and kaggle.PHONE_FIX in said


def test_setup_yes_mode_shows_the_checklist_and_asks_nothing(monkeypatch, tmp_path, fake_quota):
    key = tmp_path / "kaggle.json"
    key.write_text('{"username": "someone", "key": "k"}', encoding="utf-8")
    monkeypatch.setattr(kaggle, "key_path", lambda: key)
    monkeypatch.setattr(kaggle, "token_path", lambda: tmp_path / "access_token")
    monkeypatch.setattr(kaggle, "client", lambda: FakeApi([]))
    f = Fake()
    r = W.step_kaggle(f.io(), M8, auto=True, want=True)
    assert f.asked == [] and r.ok is True and "✓ 3. Phone verified" in "\n".join(f.said)
