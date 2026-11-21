"""E-165 (Stage 2 done-line check, run 3): a bare `assert result.exit_code == 0` hides why a CLI failed."""
from app.core import tools as T

LIVE = """    def test_summary_command_with_expenses():
        runner = CliRunner()
        result = runner.invoke(app, ["summary", expenses_file, "--out", output_file])

        # Check that the command ran without errors
>       assert result.exit_code == 0
E       assert 2 == 0
E        +  where 2 = <Result SystemExit(2)>.exit_code

tests\\test_ac3_cli_summary.py:37: AssertionError
"""


def test_a_bare_exit_code_assert_gets_the_message_hint_and_the_usage_error():
    hint = T.exit_code_hint(LIVE)
    assert "`assert result.exit_code == 0, result.output`" in hint
    assert "usage error" in hint and 'typer.Option(..., "--out")' in hint


def test_a_returncode_assert_without_a_cli_runner_gets_only_the_message_hint():
    out = ">       assert proc.returncode == 0\nE       assert 1 == 0\n"
    hint = T.exit_code_hint(out)
    assert "`assert proc.returncode == 0, proc.stderr`" in hint and "usage error" not in hint


def test_an_assert_with_a_message_or_another_failure_gets_nothing():
    assert T.exit_code_hint(">       assert result.exit_code == 0, result.output\nE  assert 2 == 0") == ""
    assert T.exit_code_hint(">       assert total == 3\nE  assert 2 == 3") == ""


def test_run_tests_adds_it(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "class R:\n    exit_code = 2\n\n\ndef test_x():\n    result = R()\n    assert result.exit_code == 0\n",
        encoding="utf-8")
    run = T.run_tests(T.Workspace(tmp_path), command="python -m pytest -q tests/test_x.py")
    assert not run.passed and "`assert result.exit_code == 0, result.output`" in run.output
