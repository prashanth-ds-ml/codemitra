"""Must-have 12 (D-077): CodeMitra can read a file outside the project, read-only, only after the user says yes;
once per folder per session; never a secret file; never a write."""
from pathlib import Path

import pytest

from app.core import tools as T


@pytest.fixture
def two(tmp_path):
    proj, other = tmp_path / "proj", tmp_path / "other"
    proj.mkdir()
    (other / "sub").mkdir(parents=True)
    (other / "notes.md").write_text("line one\nline two\n", encoding="utf-8")
    (other / "sub" / "more.md").write_text("x\n", encoding="utf-8")
    (other / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    asked = []

    def ask(path, answer=True):
        asked.append(path)
        return answer
    ws = T.Workspace(proj)
    ws.before_read_outside = ask
    return ws, other, asked


def test_without_the_hook_outside_stays_refused(tmp_path):
    ws = T.Workspace(tmp_path)
    with pytest.raises(T.ToolError, match="outside the workspace|relative to the workspace"):
        T.read_file(ws, str(tmp_path.parent / "x.md"))


def test_a_yes_reads_it_read_only_and_names_it_by_its_full_path(two):
    ws, other, asked = two
    out = T.read_file(ws, str(other / "notes.md"))
    assert "line one" in out and str(other / "notes.md") in out and asked == [str(other / "notes.md")]
    assert ws.seen == {}                                         # never counts as "read before edit"
    with pytest.raises(T.ToolError):
        T.write_file(ws, str(other / "notes.md"), "changed")      # writing outside is still refused
    assert (other / "notes.md").read_text(encoding="utf-8") == "line one\nline two\n"


def test_asked_once_per_folder_and_its_subfolders(two):
    ws, other, asked = two
    T.read_file(ws, str(other / "notes.md"))
    T.read_file(ws, str(other / "sub" / "more.md"))
    T.list_files(ws, str(other))
    assert len(asked) == 1


def test_a_no_is_respected_and_said(two):
    ws, other, asked = two
    ws.before_read_outside = lambda p: False
    with pytest.raises(T.ToolError, match="did not allow reading"):
        T.read_file(ws, str(other / "notes.md"))


def test_secrets_are_never_read_nor_listed(two, tmp_path):
    ws, other, asked = two
    with pytest.raises(T.ToolError, match="secret"):
        T.read_file(ws, str(other / ".env"))
    assert asked == []                                           # not even asked
    assert ".env" not in T.list_files(ws, str(other))
    for p in ("~/.ssh/id_rsa", "~/.kaggle/kaggle.json", "C:/x/.aws/credentials"):
        assert T.is_secret_path(Path(p).expanduser())
    assert not T.is_secret_path(Path("notes.md"))


def test_the_chat_asks_in_every_mode_and_records_it(tmp_path):
    from tests.test_live_20261113_b import _rows, _session
    from tests.test_phased import Heard
    (tmp_path / "proj").mkdir()
    (tmp_path / "x.md").write_text("hello\n", encoding="utf-8")
    s = _session(tmp_path / "proj", Heard())
    s.mode = "auto"
    questions = []
    s.hooks.confirm = lambda title, detail, q: questions.append(q) or True
    assert "hello" in T.read_file(s.ws, str(tmp_path / "x.md"))
    assert questions and "Let CodeMitra read" in questions[0]
    assert any(r["kind"] == "outside_read" and r["allowed"] for r in _rows(s))
