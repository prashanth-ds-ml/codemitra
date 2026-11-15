"""E-132 (GitHub issue #12): `codemitra improve` proposed "retry failed installs 3 times" for errors that came from the
machine (a refused program, CodeMitra's own Python without pip), and its benchmark could not grade (no fastapi in
the Python that ran pytest). Machine errors are now their own pattern that no rule targets, and the benchmark has
its own Python, used by the model's test runs and the grading alike."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.core import analyze as A
from app.core import harness as H
from app.core import improve as I
from app.core import tools as T


def test_machine_errors_are_their_own_pattern():
    for out in ("✗ Permission denied: command 'playwright' denied by policy",
                "/usr/bin/python: No module named pip", "ModuleNotFoundError: No module named 'fastapi'",
                "✗ Executable not found: npm", "✗ Offline: there is no internet connection"):
        assert A.is_environment_error(out), out
    assert not A.is_environment_error("✗ 'a.py' is not a file. Did you mean 'b.py'?")
    assert "environment" in A.NOT_FIXABLE and "settings change cannot fix it" in A.PATTERNS["environment"]


class Proposer:
    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def invoke(self, messages):
        self.seen.append(messages[-1].content)
        return AIMessage(content=self.answers.pop(0))


def test_only_machine_errors_means_nothing_to_propose_and_it_is_said(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_HOME", str(tmp_path))
    rep = A.Report(units=3)
    for _ in range(5):
        rep.pattern("environment").add("run_command: ✗ Permission denied: command 'playwright' denied by policy")
    said, p = [], Proposer()
    entry = I.improve(rep, proposer=p, builder=None, bench=object(), say=said.append)
    assert entry["result"] == "skipped" and p.seen == []                       # the proposer is never asked
    assert any("Machine problems seen 5x" in s and "denied by policy" in s for s in said)


def test_the_proposer_never_sees_machine_errors_and_is_told_retry_does_not_fix_them():
    rep = A.Report(units=3)
    rep.pattern("environment").add("run_command: No module named pip")
    rep.pattern("environment").add("run_command: denied by policy")
    rep.pattern("no_tests_after_code").add("turn 3: wrote a.py")
    p = Proposer('{"kind": "rule", "text": "Run the tests after writing code.", "why": "x"}')
    change, _ = I.propose(rep, H.Harness(), p, {"run_tests"})
    assert change and "no_tests_after_code" in p.seen[0] and "No module named pip" not in p.seen[0]
    assert "retrying never fixes a refused command" in I.PROPOSER_PROMPT


def test_the_benchmark_python_is_codemitras_own_when_it_has_the_packages(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_HOME", str(tmp_path))
    run = lambda args, timeout: SimpleNamespace(returncode=0)                   # noqa: E731
    assert I.bench_python(run=run) == sys.executable


def test_without_the_packages_it_makes_its_own_with_uv(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_HOME", str(tmp_path))
    ran = []
    venv_py = tmp_path / "bench-env" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    def run(args, timeout):
        ran.append(args)
        if args[1:2] == ["venv"]:
            venv_py.parent.mkdir(parents=True)
            venv_py.write_text("")
        ok = str(args[0]) == str(venv_py) and len(ran) > 3                    # works once the packages are in
        return SimpleNamespace(returncode=0 if (args[1:2] != ["-c"] or ok) else 1)
    monkeypatch.setattr(I.shutil, "which", lambda n: "/fake/uv" if n == "uv" else None)
    said = []
    assert I.bench_python(say=said.append, run=run) == str(venv_py)
    assert any(a[1:3] == ["pip", "install"] and "fastapi" in a for a in ran)
    assert said and "once" in said[0]


def test_no_uv_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_HOME", str(tmp_path))
    monkeypatch.setattr(I.shutil, "which", lambda n: None)
    with pytest.raises(I.BenchError, match="setup script"):
        I.bench_python(run=lambda args, timeout: SimpleNamespace(returncode=1))


def test_the_models_tests_and_the_grading_use_the_benchmarks_python(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_HOME", str(tmp_path))
    monkeypatch.setattr(I, "bench_python", lambda say=print, run=None: "/bench/python")
    seen = {}

    class Bench:
        def prepare(self, task, dest):
            (dest / "tests").mkdir(parents=True)

        def grade(self, task, ws, python=None):
            seen["grade"] = python
            return SimpleNamespace(passed=True, infra_error=None, output_tail="")

    def solve(prompt, ws, llm, **kw):
        seen["ws"] = ws.python
        return SimpleNamespace(tokens_in=1, seconds=1, status="passed", steps=1)
    monkeypatch.setattr(I, "solve", solve)
    I.evaluate(H.Harness(), None, tasks=[SimpleNamespace(id="T01", prompt="x")], bench=Bench())
    assert seen == {"ws": "/bench/python", "grade": "/bench/python"}


def test_run_tests_uses_the_workspaces_python(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    ws = T.Workspace(tmp_path, python=sys.executable)
    assert T.run_tests(ws).passed
