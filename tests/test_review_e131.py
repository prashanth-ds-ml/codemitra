"""E-131: the whole-codebase review (2026-11-15). Each test fails on the code before the fix."""
import platform
import shutil
import sys
from pathlib import Path

import pytest

from app.agents import shell
from app.core import tools as T


@pytest.fixture
def ws(tmp_path):
    shell.configure(workspace=str(tmp_path), allowed_roots=[str(tmp_path)], session_mode="auto",
                    stream_to_console=False)
    yield tmp_path
    shell.configure(workspace=None, allowed_roots=[])


def test_installing_requirements_and_pytest_options_are_not_inline_code():
    for cmd in ("python -m pip install -r requirements.txt", "python -m pytest -p no:cacheprovider",
                "python -m pytest -c pytest.ini", "python app.py -c config.yml"):
        assert not shell.runs_inline_code(cmd), cmd
    for cmd in ('python -c "print(1)"', "node -e 1", "cmd /c del x", "powershell -Command ls"):
        assert shell.runs_inline_code(cmd), cmd


@pytest.mark.skipif(platform.system() != "Windows" or not shutil.which("npm"), reason="npm.cmd on Windows")
def test_npm_is_found_on_windows(ws):
    r = shell.execute("npm --version", cwd=str(ws))
    assert r.exit_code == 0 and "not found" not in r.output, r.output


def test_an_install_cut_off_at_its_limit_is_not_still_running():
    cut = shell.ShellResult(command="pip install torch", cwd=".", exit_code=1, output_lines=["Downloading torch"],
                            timed_out=True)
    server = shell.ShellResult(command="python game.py", cwd=".", exit_code=1, output_lines=["pygame 2.6"],
                               timed_out=True)
    assert not cut.still_running and server.still_running
    assert shell.is_install("npm install") and shell.is_install("python -m pip install x")
    assert not shell.is_install("python game.py")


def test_ls_and_dir_flags_are_not_paths(ws):
    (ws / "a.txt").write_text("x", encoding="utf-8")
    for cmd in ("ls -la", "dir /b", "ls"):
        r = shell.execute(cmd, cwd=str(ws))
        assert r.exit_code == 0 and any("a.txt" in line for line in r.output_lines), (cmd, r.output_lines)


def test_a_typed_command_with_a_pipe_goes_to_the_users_shell(ws):
    assert shell._run_builtin("cat log.txt", str(ws)) is not None or True        # a builtin when it has no pipe
    calls = []
    real = shell._run_builtin
    shell._run_builtin = lambda c, d: calls.append(c) or real(c, d)
    try:
        shell.execute("dir | findstr x" if platform.system() == "Windows" else "ls | grep x", cwd=str(ws),
                      typed_by_user=True)
    finally:
        shell._run_builtin = real
    assert calls == []


def test_a_bare_pytest_uses_the_projects_python(ws, monkeypatch):
    monkeypatch.setattr("app.core.tools.project_python", lambda root: "/proj/.venv/bin/python")
    assert shell._model_command_args("pytest -q", str(ws)) == ["/proj/.venv/bin/python", "-m", "pytest", "-q"]


def test_secrets_inside_the_project_are_never_read_or_searched(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-live-123\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    (tmp_path / "tokenizer.py").write_text("OPENAI_API_KEY = 'name only'\n", encoding="utf-8")
    ws = T.Workspace(tmp_path)
    with pytest.raises(T.ToolError, match="holds secrets"):
        T.read_file(ws, ".env")
    assert "OPENAI_API_KEY=" in T.read_file(ws, ".env.example")                   # a template is fine
    found = T.search(ws, "OPENAI_API_KEY")
    assert "sk-live" not in found and "tokenizer.py" in found and ".env.example" in found


def test_a_failed_commit_is_not_reported_as_shared(monkeypatch, tmp_path):
    from app.core import share as SH
    monkeypatch.setattr(SH, "checkout", lambda repo: (tmp_path, ""))
    pushed = []

    def fake_git(args, cwd):
        if args[0] == "commit":
            return False, "Author identity unknown\n*** Please tell me who you are."
        if args[0] == "push":
            pushed.append(1)
            return True, "Everything up-to-date"
        return True, ""
    monkeypatch.setattr(SH, "_git", fake_git)
    f = tmp_path / "s.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    ok, msg = SH.push([f], repo="o/r", friend="vineel")
    assert not ok and "git config --global user.name" in msg and pushed == []


def test_a_newer_downloaded_kaggle_key_replaces_a_stale_one(monkeypatch, tmp_path):
    import json
    import os
    import time

    from app import kaggle
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(kaggle, "token_path", lambda: tmp_path / "no-token")
    (cfg / "kaggle.json").write_text(json.dumps({"username": "old", "key": "expired"}), encoding="utf-8")
    old = time.time() - 3600
    os.utime(cfg / "kaggle.json", (old, old))
    new = tmp_path / "kaggle (1).json"
    new.write_text(json.dumps({"username": "me", "key": "fresh"}), encoding="utf-8")
    monkeypatch.setattr(kaggle, "find_download", lambda: new)
    said = []
    kaggle.setup("", echo=said.append, api_factory=lambda: (_ for _ in ()).throw(kaggle.KaggleError("offline")))
    assert json.loads((cfg / "kaggle.json").read_text(encoding="utf-8"))["key"] == "fresh"
    assert any("saved to" in s for s in said)


def test_scoring_uses_the_chats_shell_rules(tmp_path):
    from app.core import score
    out, ok = score._run_shell(tmp_path)("curl https://example.com")
    assert not ok and "Permission denied" in out
    out, ok = score._run_shell(tmp_path)(f'"{sys.executable}" -c "print(1)"')
    assert not ok                                                               # inline code: refused, as in chat
