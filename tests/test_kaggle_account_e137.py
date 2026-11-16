"""E-137 (issue #13, 2026-11-16, after E-136): on the tester's account the notebook had no internet at all ("curl: (28)
Resolving timed out"): Kaggle gives notebooks internet only once the account's phone is verified, and the GPU hours
show before that. CodeMitra found out only after 7 minutes, blamed nothing, and never said which Kaggle account (or
which of the keys on the machine) it was using."""
import json
import pathlib
from datetime import datetime, timezone

import pytest

from app import backend, kaggle
from remote.kaggle import build_notebook
from tests.test_kaggle import FakeApi


@pytest.fixture
def fake_quota(monkeypatch):
    q = {"used_h": 0.0, "total_h": 30.0, "left_h": 30.0, "refresh": datetime(2026, 11, 21, tzinfo=timezone.utc)}
    monkeypatch.setattr(kaggle, "quota", lambda api: dict(q))
    return q


def _source(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def test_the_notebook_checks_its_internet_before_installing():
    src = _source(build_notebook.build({"model": "m", "ctx": 262144, "token": "t"}))
    i = src.index('say("net", ok=not _net_problem)')
    assert i < src.index("apt-get -qq update") and i < src.index("ollama.com/install.sh")
    assert 'say("error", detail="no internet on this notebook: "' in src


def test_no_internet_names_the_account_and_the_fix():
    api = FakeApi(["MITRA|started|model=m|context=262144", "MITRA|net|ok=False",
                   "MITRA|error|detail=no internet on this notebook: curl: (6) Could not resolve host: ollama.com"])
    with pytest.raises(kaggle.KaggleError) as exc:
        kaggle._follow(api, "saisarann/codemitra-gpu-server", {"token": "t", "url": "u"}, 262144, 20,
                       lambda s: None, lambda s: None)
    assert "Kaggle account saisarann" in str(exc.value) and "Phone verification" in str(exc.value)
    assert backend.prefs()["kaggle_internet"]["user"] == "saisarann"
    assert backend.prefs()["kaggle_internet"]["ok"] is False
    assert "internet: none" in kaggle.account_line("saisarann")


def test_start_names_the_account_and_saves_it_first_time(fake_quota):
    api = FakeApi(["MITRA|net|ok=True", "MITRA|error|detail=stop here"])
    said = []
    with pytest.raises(kaggle.KaggleError, match="stop here"):
        kaggle.start("m", echo=said.append, api=api, sleep=lambda s: None)
    assert any(s.strip().startswith("Kaggle account: someone (key: ") for s in said)
    assert backend.prefs()["kaggle_account"] == "someone"
    assert backend.prefs()["kaggle_internet"]["ok"] is True


def test_a_key_for_another_account_does_not_start(fake_quota):
    backend.save_prefs(kaggle_account="saisarann")
    api = FakeApi([])
    with pytest.raises(kaggle.KaggleError, match="set up with Kaggle account saisarann, but the key it finds now is "
                                                 "for someone"):
        kaggle.start("m", echo=lambda s: None, api=api, sleep=lambda s: None)
    assert api.pushed == []


class InternetOffApi(FakeApi):
    """Kaggle saved the pushed notebook without internet."""

    def kernels_pull(self, ref, path, metadata=False):
        p = pathlib.Path(path)
        p.mkdir(parents=True, exist_ok=True)
        (p / "kernel-metadata.json").write_text(json.dumps({"id": ref, "enable_internet": False}), encoding="utf-8")


def test_a_notebook_saved_without_internet_is_reported_at_once(fake_quota):
    api = InternetOffApi([])
    with pytest.raises(kaggle.KaggleError, match="Kaggle account someone: its notebooks get no internet"):
        kaggle.start("m", echo=lambda s: None, api=api, sleep=lambda s: None)
    assert len(api.pushed) == 1
    assert not (kaggle._home() / "kaggle-check").exists()  # the pulled copy (it holds the token) is gone
