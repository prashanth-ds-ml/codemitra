"""Must-have 11 (D-077): CodeMitra knows its tools and limits (which Python, which programs, what to do when one is
refused) and checks an installed library before using its API, in the project's Python, never from memory."""
import sys
from pathlib import Path

import pytest

from app.agents import shell
from app.core import chat as C
from app.core import tools as T


def test_the_machine_note_names_the_projects_python_and_the_allowed_programs(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tools.project_python", lambda root: str(tmp_path / ".venv" / "python"))
    text = shell.limits_text(tmp_path)
    assert "The project's Python: .venv/python" in text
    for exe in ("python", "pip", "pytest", "git", "node", "npx", "playwright"):
        assert exe in text
    assert "curl" not in text and "! <command>" in text and "package_info" in text
    assert len(text) < 900                                   # a few lines: the prompt stays small


def test_with_only_codemitras_python_it_says_the_first_install_makes_a_venv(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tools.project_python", lambda root: sys.executable)
    assert "first `pip install` makes the project's own .venv" in shell.limits_text(tmp_path)


def _project_python_is(monkeypatch, py):
    """The project has its own Python (here: the same interpreter, under another name for the check)."""
    monkeypatch.setattr("app.core.tools.project_python", lambda root: py)
    monkeypatch.setattr(T.sys, "executable", "codemitra-own-python")


def test_package_info_reads_the_installed_version_in_the_projects_python(tmp_path, monkeypatch):
    _project_python_is(monkeypatch, sys.executable)
    out = T.package_info(T.Workspace(tmp_path), "httpx")
    import httpx
    assert out.startswith(f"httpx {httpx.__version__}") and "Client" in out and "Source:" in out


def test_a_missing_package_says_how_to_install_it(tmp_path, monkeypatch):
    _project_python_is(monkeypatch, sys.executable)
    out = T.package_info(T.Workspace(tmp_path), "surely_not_installed_pkg")
    assert "is not installed for the project's Python" in out and "pip install surely_not_installed_pkg" in out


def test_package_info_refuses_anything_but_a_name(tmp_path):
    with pytest.raises(T.ToolError):
        T.package_info(T.Workspace(tmp_path), "os; rm -rf /")


def test_the_look_phase_and_plan_mode_can_check_a_package():
    assert "package_info" in C.PHASES["look_at_code"]["tools"] and "package_info" in C.READ_ONLY_TOOLS
    assert any(s["name"] == "package_info" for s in T.TOOL_SPECS)


def test_codemitra_no_longer_says_it_cannot_read_outside_the_project():
    assert "you cannot read\nfiles outside" not in C.ABOUT_CODEMITRA
    assert "read a file outside this project folder (read-only, after a yes)" in C.ABOUT_CODEMITRA


def test_the_chat_prompt_carries_the_machine_note():
    import inspect

    from app import main
    assert "limits_text(pathlib.Path(cfg[\"workspace\"]))" in inspect.getsource(main)


# -- review 2026-11-15 --

def test_the_projects_own_module_is_never_imported(tmp_path, monkeypatch):
    """A read tool must not run the project's code (a game window, file writes)."""
    _project_python_is(monkeypatch, sys.executable)
    (tmp_path / "game.py").write_text("open('ran.txt', 'w').write('x')\n", encoding="utf-8")
    out = T.package_info(T.Workspace(tmp_path), "game")
    assert "this project's own code (game.py)" in out and not (tmp_path / "ran.txt").exists()


def test_codemitras_own_packages_are_never_reported_as_the_projects(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.tools.project_python", lambda root: sys.executable)
    out = T.package_info(T.Workspace(tmp_path), "langchain_core")
    assert "no Python of its own yet" in out and "· installed for" not in out
    assert "· installed for" in T.package_info(T.Workspace(tmp_path), "json")   # the standard library still answers
