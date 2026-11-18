---
name: debugging
description: Find a bug's real cause before fixing it: reproduce it, read the error, test one idea at a time, prove the fix.
triggers: bug, bugs, error, errors, crash, crashes, crashed, broken, wrong, traceback, exception, failing, fails, debug, not working, doesnt work, keyerror, typeerror, valueerror, indexerror, attributeerror
source: adapted from obra/superpowers skills/systematic-debugging (MIT, commit 22f0b463e7a5), shortened for small models
---
# Debugging: cause first, then the fix

Do not change code until you can make the bug happen and you know why it happens.

## Steps
1. **Reproduce it.** Run what the user ran (`run_command`: `python main.py`, or `run_tests`). Or write a tiny test
   with the user's example, e.g. "average of 2 and 4 should be 3": `assert average([2, 4]) == 3`.
   Run it and see it fail.
2. **Read the error from the bottom.** The last line is the error type and message; the line above it is where it
   happened (file and line number). Open that file at that line (`read_file` with start and end).
3. **Follow the value back.** Where does the wrong value come from? Read the function that makes it, then the one
   that calls it. Compare with code that works.
4. **Say one cause in one sentence**: "it divides by len + 1 instead of len". Check it with
   one small change or one print, not five changes at once.
5. **Fix the cause, not the symptom.** No `try/except` that hides the error, no special case only for the example.
6. **Prove it.** Run the reproduction from step 1: it passes now. Then run all the tests (`run_tests`): nothing else
   broke.
7. Tell the user the cause and the evidence: "Cause: ... Fixed in calc.py:14. The repro test passes; 9 tests pass."

## If a fix did not work
Undo it. Go back to step 2 with what you learned. After 3 failed fixes, stop and tell the user what you found.

## Common causes
- a dict key or name spelled differently (`user_id` vs `userId`)
- off by one: `<` vs `<=`, counting both ends, a range end
- the same thing applied twice, or in the wrong order
- a string where a number was expected (`"10" + 5`), or rounding too early
- dates: month lengths, leap years, time zones
