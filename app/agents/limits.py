"""Limits for agent loops: a small model that keeps calling tools must stop (E-002, E-023)."""
from __future__ import annotations

import json

MAX_AGENT_STEPS = 20  # model calls per agent run


def stopped_message(steps: int = MAX_AGENT_STEPS) -> str:
    return (f"✗ Stopped after {steps} model calls without a final answer (step limit). "
            "The task may be too big for one request; split it, or ask again with more detail.")


class RepeatGuard:
    """Stops the same call being made over and over (E-023: 100+ identical web searches).

    before(): returns a tool result to send instead of running a call already made `max_repeats` times.
    after(): returns a stop message once one tool has failed `max_failures` times in a row.
    """

    # Checking again is never a pointless repeat: tests and commands are re-run after changes (E-026).
    # Re-running the tests is never a pointless repeat (E-026). A shell command is: the same failing command was run
    # 30+ times (E-033), so it is a repeat unless a file changed since (writes clear the memory below).
    EXEMPT = frozenset({"run_tests"})
    # Tools that change files: after one of them, earlier reads may give a different answer.
    WRITES = frozenset({"write_file", "edit_file", "make_dir", "run_plan", "mcp_call"})

    def __init__(self, *, max_repeats: int = 1, max_failures: int = 3) -> None:
        self.max_repeats, self.max_failures = max_repeats, max_failures
        self._calls: dict[str, int] = {}
        self._fail_tool = ""
        self._fail_count = 0
        self._repeats_refused = 0

    @staticmethod
    def _key(name: str, args: dict) -> str:
        try:
            return name + json.dumps(args or {}, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return name + repr(args)

    def before(self, name: str, args: dict) -> str | None:
        if name in self.EXEMPT:
            return None
        key = self._key(name, args)
        self._calls[key] = self._calls.get(key, 0) + 1
        if self._calls[key] > self.max_repeats:
            return (f"✗ Not run: {name} was already called with these exact arguments; the result will not change. "
                    "Use the result you have, try different arguments, or give your answer now.")
        return None

    def after(self, name: str, output: str, ok: bool | None = None) -> str | None:
        """ok: whether the call worked (a shell command's output does not start with ✗; E-033)."""
        if name in self.WRITES and not str(output).lstrip().startswith("✗"):
            self._calls.clear()  # the files changed: re-reading them is not a repeat (E-026)
        if str(output).startswith("✗ Not run:"):
            self._repeats_refused += 1
            if self._repeats_refused >= self.max_failures:
                return (f"✗ Stopped: the model kept repeating the same {name} call "
                        f"({self._repeats_refused} repeats refused) instead of answering.")
            return None
        failed = (not ok) if ok is not None else str(output).lstrip().startswith("✗")
        if not failed:
            self._fail_tool, self._fail_count = "", 0
            return None
        if name == self._fail_tool:
            self._fail_count += 1
        else:
            self._fail_tool, self._fail_count = name, 1
        if self._fail_count >= self.max_failures:
            first = str(output).strip().splitlines()[0][:200]
            return f"✗ Stopped: {name} failed {self._fail_count} times in a row. Last error: {first.lstrip('✗ ')}"
        return None


# ── Stage 2.5: the anti-loop ladder (ported from Mingbird, Apache-2.0: ollama_agent.py agent_loop 4995-5135 and
# _EditConvergenceGuard 3961; see docs/MINGBIRD_REFERENCE.md). It steers before the RepeatGuard stops. ────────────

READS = frozenset({"read_file", "search", "list_files", "package_info"})
CHANGES = frozenset({"write_file", "edit_file", "append_file"})
NEVER_OFF = frozenset({"run_tests", "finish"})  # the checks themselves are never turned off

TOOL_HINTS = {
    "edit_file": ("edit_file failed 3 times: the `old` text does not match the file. Next: read_file the exact lines "
                  "again and copy them, or write the whole file with write_file."),
    "run_command": ("run_command failed 3 times. Next: read the error line, change the cause (a missing file, a "
                    "wrong path, a typo) or try a different command; do not repeat the same one."),
    "run_tests": ("the tests failed 3 times in a row. Next: read the first failure's error and the line it points "
                  "to, and fix that one cause before running them again."),
}
STREAK_NOTE = ("[CodeMitra: you called {name} {n} times in a row. Use what you have learned: make the change, run the "
               "tests, or answer.]")
EDIT_NOTE = ("[CodeMitra: you changed {path} {n} times and the tests still do not pass. Stop guessing: read the "
             "failure message, find the root cause, then make one change that fixes it.{test}]")
HYPOTHESIS_NOTE = ("[CodeMitra: {path} changed {n} times without the tests passing. Before the next change, say in one "
                   "line what you think the cause is and why, then make one change for it.{test}]")
TEST_FILE_NOTE = " This is a test file: do not change what it checks to make it pass; fix the code it tests."


def _is_test_path(path: str) -> bool:
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in "/" + str(path).replace("\\", "/")


class LoopGuard(RepeatGuard):
    """RepeatGuard plus the ladder. before() also refuses turned-off tools and re-reading loops; hint(), called after
    a tool ran, returns text to add to its result (or ""); `last` names what fired, for the record."""

    def __init__(self, *, max_repeats: int = 1, max_failures: int = 3, hint_failures: int = 3, streak: int = 5,
                 max_streak_nudges: int = 3, off_at: int = 8, off_identical: int = 4, window: int = 12,
                 window_max: int = 6, edits_hint: int = 4, edits_hypothesis: int = 8) -> None:
        super().__init__(max_repeats=max_repeats, max_failures=max_failures)
        self.hint_failures, self.streak, self.max_streak_nudges = hint_failures, streak, max_streak_nudges
        self.off_at, self.off_identical, self.window, self.window_max = off_at, off_identical, window, window_max
        self.edits_hint, self.edits_hypothesis = edits_hint, edits_hypothesis
        self.history: list[tuple[str, str]] = []  # (tool, call key), every call that ran or was refused
        self.off: set[str] = set()
        self.edits: dict[str, int] = {}           # file -> successful changes since the tests last passed
        self._tool_fails: dict[str, int] = {}
        self._nudges = 0
        self.last = ""

    def before(self, name: str, args: dict) -> str | None:
        self.last = ""
        if name in self.off:
            self.last = "tool_off"
            return (f"✗ Not run: {name} is turned off for this task (called {self.off_at} times in a row, most of them "
                    "the same). Use the other tools, or give your answer.")
        if name in READS:
            key = self._key(name, args)
            recent = [k for _, k in self.history[-self.window:]]
            ab = [k for n, k in self.history[-4:] if n in READS]
            flip = len(ab) == 4 and ab[0] == ab[2] and ab[1] == ab[3] and ab[0] != ab[1] and key in (ab[0], ab[1])
            if recent.count(key) >= self.window_max - 1 or flip:
                self.last = "read_loop"  # the caller's hint() records the refused call in the history
                return (f"✗ Not run: you keep reading the same thing ({name} with these arguments). Use what you read; "
                        "other files and other parts of this file can be read normally.")
        return super().before(name, args)

    def hint(self, name: str, args: dict, output: str, ok: bool) -> str:
        """Track the call that just ran and return the ladder's hint for it ("" for none)."""
        key = self._key(name, args)
        self.history.append((name, key))
        notes: list[str] = []
        self.last = ""
        # 1. the same tool failing: change strategy (the RepeatGuard stops it at max_failures)
        if ok:
            self._tool_fails[name] = 0
        else:
            self._tool_fails[name] = self._tool_fails.get(name, 0) + 1
            if self._tool_fails[name] == self.hint_failures:
                notes.append(f"[CodeMitra: {TOOL_HINTS.get(name, f'{name} failed 3 times. Next: change your approach; do not repeat the same call.')}]")
                self.last = "change_strategy"
        # 2. one tool over and over: a nudge; 3. mostly identical: turned off for the task
        run = 0
        for n, _ in reversed(self.history):
            if n != name:
                break
            run += 1
        if run >= self.off_at and name not in NEVER_OFF:
            last = [k for _, k in self.history[-self.off_at:]]
            if max(last.count(k) for k in set(last)) >= self.off_identical:
                self.off.add(name)
                notes.append(f"[CodeMitra: {name} is now turned off for this task: it was called {run} times in a row, "
                             "mostly the same. Use the other tools, or answer.]")
                self.last = "tool_off"
        elif run >= self.streak and run % self.streak == 0 and self._nudges < self.max_streak_nudges \
                and name not in NEVER_OFF:
            self._nudges += 1
            notes.append(STREAK_NOTE.format(name=name, n=run))
            self.last = self.last or "streak"
        # 4. the same file changed again and again without the tests passing
        if name in CHANGES and ok:
            path = str(args.get("path", ""))
            self.edits[path] = self.edits.get(path, 0) + 1
            n = self.edits[path]
            extra = TEST_FILE_NOTE if _is_test_path(path) else ""
            if n == self.edits_hint:
                notes.append(EDIT_NOTE.format(path=path, n=n, test=extra))
                self.last = "edit_loop"
            elif n == self.edits_hypothesis:
                notes.append(HYPOTHESIS_NOTE.format(path=path, n=n, test=extra))
                self.last = "edit_loop"
        if name == "run_tests" and ok:
            self.tests_passed()
        return ("\n\n" + "\n".join(notes)) if notes else ""

    def tests_passed(self) -> None:
        """The goal moved forward: the edit counts start again (also called when the chat's own test run passes)."""
        self.edits.clear()
