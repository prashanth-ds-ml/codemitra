"""E-128 (GitHub issue #11): building a landing page, CodeMitra could not install or use Playwright. pip installed
into another Python than the one `python` ran, CodeMitra's own Python has no pip, `playwright` was refused, and the
model kept trying refused variants instead of telling the user what to run."""
import sys
from pathlib import Path

import pytest

from app.agents import shell
from app.policy import Action, Scope, load_policy


@pytest.fixture
def ws(tmp_path):
    shell.configure(workspace=str(tmp_path), allowed_roots=[str(tmp_path)])
    yield tmp_path
    shell.configure(workspace=None, allowed_roots=[])


def _venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


@pytest.fixture
def only_codemitras_python(monkeypatch):
    """Issue #11's machine: no project venv, and `python` on PATH is unusable (Store Python), so the project's
    Python would be CodeMitra's own. The fake uv makes the venv file; nothing is downloaded."""
    import app.core.tools as T
    monkeypatch.setattr(T, "_has_pytest", lambda p: False)
    monkeypatch.setattr(shell.shutil, "which", lambda name: "/fake/uv" if name == "uv" else None)
    ran = []

    def fake_run(args, cwd=None, **kw):
        ran.append(list(args))
        if args[1:2] == ["venv"]:
            p = _venv_python(Path(args[-1]).parent)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")
    monkeypatch.setattr(shell.subprocess, "run", fake_run)
    return ran


def test_pip_without_a_project_python_makes_the_projects_venv_first(ws, only_codemitras_python):
    args = shell._model_command_args("pip install playwright", str(ws))
    py = str(_venv_python(ws))
    assert args == [py, "-m", "pip", "install", "playwright"]
    assert ["/fake/uv", "venv", "--seed", str(ws / ".venv")] in only_codemitras_python
    assert any(a[1:3] == ["pip", "install"] and "pytest" in a for a in only_codemitras_python)  # its tests still run


def test_python_dash_m_pip_goes_to_the_same_python(ws, only_codemitras_python):
    assert shell._model_command_args("python -m pip install requests", str(ws)) == [
        str(_venv_python(ws)), "-m", "pip", "install", "requests"]


def test_playwright_runs_in_the_python_it_was_installed_into(ws, only_codemitras_python):
    shell._model_command_args("pip install playwright", str(ws))
    assert shell._model_command_args("playwright install chromium", str(ws)) == [
        str(_venv_python(ws)), "-m", "playwright", "install", "chromium"]


def test_playwright_alone_never_makes_a_venv(ws, only_codemitras_python):
    assert shell._model_command_args("playwright install chromium", str(ws))[0] == "playwright"
    assert not (ws / ".venv").exists()


def test_a_python_the_tests_already_use_gets_the_installs(ws, monkeypatch):
    monkeypatch.setattr("app.core.tools.project_python", lambda root: "/usr/bin/python3")
    assert shell._model_command_args("pip3 install flask", str(ws)) == ["/usr/bin/python3", "-m", "pip", "install",
                                                                        "flask"]
    assert not (ws / ".venv").exists()


def test_web_commands_are_allowed_and_others_still_refused():
    p = load_policy()
    for exe in ("playwright", "node", "npx", "python", "pip"):
        assert p.evaluate(Scope.COMMAND, exe) == Action.ALLOW, exe
    for exe in ("curl", "uv", "powershell", "rm"):
        assert p.evaluate(Scope.COMMAND, exe) == Action.DENY, exe


def test_a_refused_command_says_what_the_user_can_run(ws):
    shell.configure(workspace=str(ws), allowed_roots=[str(ws)], session_mode="auto")
    r = shell.execute("curl https://example.com", cwd=str(ws))
    text = "\n".join(r.output_lines)
    assert r.exit_code == 1 and "Do not try other forms" in text and "! curl https://example.com" in text
