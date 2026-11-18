---
name: writing-tests
description: Write pytest tests that would fail if the code were wrong: normal cases, edge cases and errors, run red then green.
triggers: test, tests, pytest, unit test, unit tests, testing, coverage, tested
source: adapted from obra/superpowers skills/test-driven-development (MIT, commit 22f0b463e7a5), shortened for small models
---
# Writing tests that catch bugs

A test is good only if it FAILS when the code is wrong. Passing on correct code is not enough.

## Steps
1. Read the code under test and its docstring. List what it promises: normal results, edge cases, errors.
2. Put tests in `tests/test_<module>.py`, one behaviour per test, named for it: `test_rejects_percent_over_100`.
3. Cover, for each function:
   - a normal case with an exact expected value
   - edges: empty input, 0, 1, negative, the largest allowed value, the boundary itself (100 when the limit is 100)
   - errors: `with pytest.raises(ValueError):` for every input the code must refuse
   - every rule in the docstring (rounding, order, case, spaces): one test each
4. Use exact values (`== 12.35`), not just `is not None` or `> 0`.
5. Run them: `python -m pytest tests/test_<module>.py -q`. Read the result.
   - New feature or bug fix: write the test first, run it, see it FAIL for the right reason, then change the code, run
     again, see it PASS.
   - Only asked to add tests: do not change the code. A test that fails on the current code is a bug you found: say so.
6. Run the whole suite once at the end: `python -m pytest -q`.

## Example
For `grade(score)`: "A" from 90, "B" from 75, else "C"; ValueError outside 0-100.
```python
import pytest
from grades import grade

def test_high_score_is_a():
    assert grade(95) == "A"

def test_boundaries():
    assert grade(90) == "A"
    assert grade(89) == "B"
    assert grade(75) == "B"
    assert grade(74) == "C"
    assert grade(0) == "C"

def test_rejects_scores_outside_0_to_100():
    with pytest.raises(ValueError):
        grade(101)
    with pytest.raises(ValueError):
        grade(-1)
```

## Pitfalls
- `ModuleNotFoundError` in tests: run pytest from the project folder; import the module by its file name.
- Never test with random data, the clock or the network; use `tmp_path` for files.
- A test that passes with any code (`assert True`, no assert) catches nothing.
