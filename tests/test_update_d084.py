"""D-084: fixes reach friends. A once-a-day notice of a newer release, and `codemitra update` pulls it into the clone
CodeMitra runs from, without ever overwriting the friend's own edits."""
import subprocess
from pathlib import Path

import pytest

from app import update as U

DAY = U.CHECK_EVERY_S


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.delenv("CODEMITRA_NO_UPDATE_CHECK", raising=False)
    calls = []

    def fetch():
        calls.append(1)
        return "0.9.0", "v0.9.0: codemitra update"
    return calls, fetch


def test_versions_compare_as_numbers():
    assert U.newer("0.10.0", "0.9.9") and U.newer("0.8.2", "0.8.1")
    assert not U.newer("0.8.1", "0.8.1") and not U.newer("dev", "0.8.1") and not U.newer("0.9.0", "")


def test_a_newer_release_is_one_line_naming_the_command(checks):
    calls, fetch = checks
    line = U.notice("0.8.2", fetch=fetch, now=1e9)
    assert line == "v0.9.0 is out: codemitra update · run `codemitra update`"
    assert U.notice("0.9.0", fetch=fetch, now=1e9 + 60) is None          # up to date: nothing


def test_github_is_asked_at_most_once_a_day(checks):
    calls, fetch = checks
    for t in (1e9, 1e9 + 60, 1e9 + DAY - 1):
        U.notice("0.8.2", fetch=fetch, now=t)
    assert len(calls) == 1
    U.notice("0.8.2", fetch=fetch, now=1e9 + DAY)
    assert len(calls) == 2


def test_offline_is_silent_and_not_retried_every_start(checks):
    calls = []

    def down():
        calls.append(1)
        raise OSError("no network")
    assert U.notice("0.8.2", fetch=down, now=1e9) is None
    assert U.notice("0.8.2", fetch=down, now=1e9 + 60) is None and len(calls) == 1


def test_never_turns_the_check_off(checks):
    calls, fetch = checks
    U.save_settings(check="never")
    assert U.notice("0.8.2", fetch=fetch, now=1e9) is None and calls == []


def test_tests_never_ask_github():
    assert U.latest(fetch=lambda: pytest.fail("asked GitHub"), now=1e9) is None


# ── the update: a real clone of a local "origin" ──────────────────────────────────────────────────────────────────
def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _release(repo: Path, version: str, deps: str = '"typer"', note: str = ""):
    (repo / "pyproject.toml").write_text(f'[project]\nname = "codemitra"\nversion = "{version}"\n'
                                         f"dependencies = [{deps}]\n", encoding="utf-8")
    log = repo / "CHANGELOG.md"
    old = log.read_text(encoding="utf-8") if log.exists() else "# Changelog\n\n"
    head, _, rest = old.partition("\n\n")
    log.write_text(f"{head}\n\n## [{version}] - 2026-11-14\n- {note or 'release ' + version}\n\n{rest}",
                   encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", version, cwd=repo)


@pytest.fixture
def clone(tmp_path):
    origin, friend = tmp_path / "origin", tmp_path / "friend"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    _release(origin, "0.8.2")
    _git("clone", "-q", str(origin), str(friend), cwd=tmp_path)
    return origin, friend


def test_update_pulls_the_new_release_and_shows_what_changed(clone):
    origin, friend = clone
    _release(origin, "0.9.0", note="setup finds a fresh Ollama")
    ok, msg = U.update(src=friend)
    assert ok and "v0.8.2 → v0.9.0" in msg and "setup finds a fresh Ollama" in msg
    assert "release 0.8.2" not in msg                                    # only what is new to them
    assert "dependencies changed" not in msg
    assert U.current_of(friend) == "0.9.0"


def test_already_new_says_so(clone):
    ok, msg = U.update(src=clone[1])
    assert ok and "already the newest" in msg


def test_your_own_edits_are_never_overwritten(clone):
    origin, friend = clone
    _release(origin, "0.9.0")
    (friend / "CHANGELOG.md").write_text("my notes", encoding="utf-8")
    ok, msg = U.update(src=friend)
    assert not ok and "your edits are kept" in msg
    assert (friend / "CHANGELOG.md").read_text(encoding="utf-8") == "my notes" and U.current_of(friend) == "0.8.2"


def test_new_dependencies_say_to_install_again(clone):
    origin, friend = clone
    _release(origin, "0.9.0", deps='"typer", "httpx"')
    ok, msg = U.update(src=friend)
    assert ok and "dependencies changed" in msg and U.REINSTALL in msg


def test_a_copy_that_is_not_a_clone_points_to_the_releases(tmp_path):
    ok, msg = U.update(src=tmp_path)
    assert not ok and "github.com/prashanth-ds-ml/codemitra" in msg


def test_the_command_exists():
    from typer.testing import CliRunner

    from app.main import cli
    out = CliRunner().invoke(cli, ["update", "--help"]).output
    assert "--check" in out
