---
name: verify-before-done
description: Before saying work is done, fixed or working, run the command that proves it and read its output.
when: change
source: adapted from obra/superpowers skills/verification-before-completion (MIT, commit 22f0b463e7a5), shortened for small models
---
# Verify before you say "done"

Never say done, fixed, works or passes unless you ran the check in THIS turn, after your LAST edit, and saw it pass.

## Steps
1. Pick the command that proves the work:
   - tests exist: `run_tests` (or `python -m pytest -q`)
   - a script: `run_command` with `python <file>.py <the inputs from the request>`
   - a file you made (xlsx, pdf, json, csv): `run_command` with one line of Python that opens it and prints what matters
2. Run it after your last edit. A run before that edit does not count.
3. Read the output: the exit code, the failures, the printed values. Compare them with what was asked.
4. It failed: fix, then run it again. Answer only when it passes, or say plainly that you are stuck.
5. Answer with the evidence, e.g. `ran python -m pytest -q: 12 passed`.

## Say this, not that
| Not this | This |
|---|---|
| "Done! It should work now." | "Ran `python count_lines.py notes.txt`: printed `3 lines`" |
| "Fixed the bug." | "test_empty_list passes now (pytest: 5 passed)" |
| "Tests pass." with no run this turn | run them, then give the count |

## When you cannot run it
Say so: "Not checked: <why>. To check: `<command>`". Never guess a result.

## Words that mean you have not checked yet
should, probably, seems, looks right, "Done!", "Perfect!": run the check first.
