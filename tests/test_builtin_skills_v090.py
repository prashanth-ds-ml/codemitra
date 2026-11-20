"""v0.9.0 (BUILD_V09 F-0..F-3): built-in skills reach every project, CodeMitra loads the one that fits a turn by
rules (a small model rarely opens an optional skill itself), and `codemitra practice --skill` runs a skill's tasks
without and with it. The 23 old local-codex skills were removed: never used (0 use_skill calls in real logs), never
reached a user's project, and too vague for a small model."""
import json
import pathlib
import subprocess
import sys

import pytest

from app import skills as SK
from app.core import practice as P
from app.core import skill_tasks as ST

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── F-1: built-in skills in every project ────────────────────────────────────────────────────────────────────────
def test_a_built_in_skill_is_found_in_an_empty_project(tmp_path):
    found = {s.name: s for s in SK.discover(str(tmp_path))}
    assert found["xlsx"].source == "builtin"


def test_the_project_and_yours_win_a_name_over_the_built_in_one(tmp_path):
    proj = tmp_path / "skills" / "xlsx"
    proj.mkdir(parents=True)
    (proj / "SKILL.md").write_text("---\nname: xlsx\ndescription: Mine.\n---\nmine\n", encoding="utf-8")
    s = next(x for x in SK.discover(str(tmp_path)) if x.name == "xlsx")
    assert s.source == "project" and s.description == "Mine."


def test_use_skill_reads_a_built_in_skill(tmp_path):
    out = SK.use_skill(str(tmp_path), SK.discover(str(tmp_path)), "xlsx")
    assert out.startswith("Skill xlsx (built in)") and "openpyxl" in out


def test_every_built_in_skill_meets_f0_and_says_where_it_came_from():
    for s in SK.builtin_skills():
        folder = pathlib.Path(s.path).parent
        body = (folder / "SKILL.md").read_text(encoding="utf-8")
        assert len(body) <= 2600, (s.name, len(body))                     # F-0: short enough for a small model
        assert s.triggers or s.when, s.name                                # it can be chosen by rules
        assert "source:" in body.split("---")[1] and (folder / "LICENSE").is_file(), s.name   # adapted: credit kept


def test_the_built_in_skills_ship_in_the_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'app = ["builtin_skills/*/*"]' in text


# ── F-2: the skill that fits is loaded into the turn ─────────────────────────────────────────────────────────────
def _skill(name, triggers=(), when=""):
    return SK.Skill(name, "d", f"{name}/SKILL.md", source="builtin", triggers=tuple(triggers), when=when)


def test_triggers_pick_a_skill_in_the_look_and_change_phases_only():
    xlsx = _skill("xlsx", ["excel", "xlsx", "spreadsheet"])
    assert SK.turn_skills([xlsx], "make an Excel sheet of my expenses", "make_change") == [xlsx]
    assert SK.turn_skills([xlsx], "make an Excel sheet of my expenses", "look_at_code") == [xlsx]
    assert SK.turn_skills([xlsx], "make an Excel sheet of my expenses", "look_up") == []
    assert SK.turn_skills([xlsx], "excellent work", "make_change") == []           # whole words only


def test_a_when_change_skill_comes_with_every_change_and_request_matches_go_first():
    verify, xlsx, dbg = _skill("verify", when="change"), _skill("xlsx", ["excel"]), _skill("debug", ["bug"])
    assert SK.turn_skills([verify], "rename the button", "make_change") == [verify]
    assert SK.turn_skills([verify], "what does this do", "look_at_code") == []
    assert SK.turn_skills([verify, xlsx, dbg], "fix the bug in the excel export", "make_change") == [xlsx, dbg]


def test_the_note_has_the_skill_text_without_its_front_matter(tmp_path):
    chosen = [s for s in SK.builtin_skills() if s.name == "xlsx"]
    note = SK.skill_note(str(tmp_path), chosen)
    assert note.startswith("[CodeMitra: skill `xlsx` fits this request. Follow it:]")
    assert "triggers:" not in note and "openpyxl" in note


def test_the_chat_loads_it_once_per_turn_and_records_it(tmp_path):
    from tests.test_live_20261113_b import _rows, _session
    from tests.test_phased import Heard
    from langchain_core.messages import AIMessage
    s = _session(tmp_path, Heard(AIMessage(content="ok")))
    calls = []
    s.hooks.skill_note = lambda request, phase: (calls.append(phase) or ["verify-before-done"], "SKILL TEXT")
    s._prev_user_full, s._skills_given = "fix greet.py", set()
    assert s._turn_skills("make_change") == "SKILL TEXT"
    assert s._turn_skills("make_change") == ""                              # once per turn
    rows = [r for r in _rows(s) if r["kind"] == "skill"]
    assert rows == [{**rows[0], "phase": "make_change", "names": ["verify-before-done"], "chars": 10}]


def test_no_hook_means_no_skills(tmp_path):
    from tests.test_live_20261113_b import _session
    from tests.test_phased import Heard
    from langchain_core.messages import AIMessage
    s = _session(tmp_path, Heard(AIMessage(content="ok")))
    s._prev_user_full = "make an excel sheet"
    assert s._turn_skills("make_change") == ""


# ── F-0: practice tasks without and with a skill ─────────────────────────────────────────────────────────────────
REFERENCE = {   # a correct solution per task: the hidden check must pass it and fail the seeded files
    "greet-cli": {"greet.py": "import sys\nprint(f\"Hello, {sys.argv[1] if len(sys.argv) > 1 else 'world'}!\")\n"},
    "price-parser": {"prices.py": "import re\n\ndef parse_price(text):\n    return float(re.sub(r'[^0-9.]', '', "
                                  "re.sub(r'^\\D*?(\\d)', r'\\1', text.strip())))\n"},
    "stats-empty": {"stats.py": "def mean(xs):\n    return sum(xs) / len(xs) if xs else 0.0\n\n\ndef median(xs):\n"
                                "    s = sorted(xs)\n    n = len(s)\n    mid = n // 2\n"
                                "    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2\n"},
    "csv-total": {"report.py": "import csv\nwith open('sales.csv', newline='') as f:\n"
                               "    total = sum(float(r['amount'].replace(',', '')) for r in csv.DictReader(f))\n"
                               "print(f'Total: {total:.2f}')\n"},
}


@pytest.mark.parametrize("task", ST.for_skill("verify-before-done"), ids=lambda t: t.id.split("/")[-1])
def test_each_hidden_check_fails_the_seeded_project_and_passes_a_correct_one(task, tmp_path):
    ws = tmp_path / "task"
    P.prepare(task, ws)
    assert not P.grade(task, ws).passed                      # the request is not already done
    for rel, text in REFERENCE[task.id.split("/")[-1]].items():
        (ws / rel).write_text(text, encoding="utf-8")
    check = P.grade(task, ws)
    assert check.passed, check.detail


GOOD_TESTS = {
    "discount": "import pytest\nfrom discount import discount\n\n"
                "def test_normal():\n    assert discount(200, 10) == 180.0\n\n"
                "def test_rounding():\n    assert discount(9.99, 33) == 6.69\n\n"
                "def test_bounds():\n    assert discount(50, 100) == 0.0\n    assert discount(50, 0) == 50.0\n\n"
                "def test_errors():\n    with pytest.raises(ValueError):\n        discount(50, 101)\n"
                "    with pytest.raises(ValueError):\n        discount(-1, 10)\n",
    "slugify": "from text_utils import slugify\n\n"
               "def test_basic():\n    assert slugify('  Hello, World!  ') == 'hello-world'\n\n"
               "def test_runs():\n    assert slugify('a  --  b') == 'a-b'\n",
    "stack": "import pytest\nfrom stack import Stack\n\n"
             "def test_push_pop_peek_len():\n    s = Stack()\n    assert len(s) == 0\n    s.push(1)\n    s.push(2)\n"
             "    assert s.peek() == 2 and len(s) == 2\n    assert s.pop() == 2 and len(s) == 1\n\n"
             "def test_empty():\n    with pytest.raises(IndexError):\n        Stack().pop()\n"
             "    with pytest.raises(IndexError):\n        Stack().peek()\n",
}
WEAK_TESTS = {"discount": "from discount import discount\n\ndef test_normal():\n    assert discount(200, 10) == 180\n",
              "slugify": "from text_utils import slugify\n\ndef test_it():\n    assert slugify('abc') == 'abc'\n",
              "stack": "from stack import Stack\n\ndef test_push():\n    s = Stack()\n    s.push(1)\n"
                       "    assert s.pop() == 1\n"}


@pytest.mark.parametrize("task", ST.for_skill("writing-tests"), ids=lambda t: t.id.split("/")[-1])
def test_mutation_checks_tell_good_tests_from_weak_ones(task, tmp_path):
    name = task.id.split("/")[-1]
    ws = tmp_path / "task"
    P.prepare(task, ws)
    assert not P.grade(task, ws).passed                                     # no tests yet
    (ws / "tests").mkdir()
    (ws / "tests" / f"test_{name}.py").write_text(WEAK_TESTS[name], encoding="utf-8")
    weak = P.grade(task, ws)
    assert not weak.passed and "did not catch" in weak.detail
    (ws / "tests" / f"test_{name}.py").write_text(GOOD_TESTS[name], encoding="utf-8")
    good = P.grade(task, ws)
    assert good.passed, good.detail


def test_each_mutant_really_differs_from_the_correct_code():
    for task in ST.for_skill("writing-tests"):
        assert "MUTANTS = [" in task.test
        ns: dict = {}
        exec(task.test.split("def run")[0].replace("import os, pathlib, shutil, subprocess, sys, tempfile\n", ""), ns)
        assert len(ns["MUTANTS"]) == 3 and all(m != ns["CORRECT"] for m in ns["MUTANTS"]), task.id


def test_only_one_skill_is_built_in_while_skills_are_added_one_at_a_time():
    """2026-11-18: skills come in one at a time, each measured; the others' tasks stay for their turn."""
    assert [s.name for s in SK.builtin_skills()] == ["xlsx"]
    assert {"verify-before-done", "writing-tests", "debugging"} <= set(ST.TASKS)


FIXES = {
    "cart-coupon": ("cart.py", "        if off:\n            line = line * (1 - off)\n", ""),
    "config-keyerror": ("app.py", "cfg['port']", "cfg['PORT']"),
    "leap-days": ("dates.py", None, "import datetime\n\n\ndef days_between(a, b):\n"
                                    "    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days\n"),
}


@pytest.mark.parametrize("task", ST.for_skill("debugging"), ids=lambda t: t.id.split("/")[-1])
def test_each_debugging_check_fails_the_bug_and_passes_a_real_fix(task, tmp_path):
    name = task.id.split("/")[-1]
    ws = tmp_path / "task"
    P.prepare(task, ws)
    assert not P.grade(task, ws).passed
    rel, old, new = FIXES[name]
    f = ws / rel
    f.write_text(new if old is None else f.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    check = P.grade(task, ws)
    assert check.passed, check.detail


def test_a_patch_for_the_reported_example_only_does_not_pass_the_leap_task(tmp_path):
    task = next(t for t in ST.for_skill("debugging") if t.id.endswith("leap-days"))
    ws = tmp_path / "task"
    P.prepare(task, ws)
    f = ws / "dates.py"
    f.write_text(f.read_text(encoding="utf-8").replace(
        "    return _day_number(b) - _day_number(a)",
        "    if (a, b) == ('2024-02-28', '2024-03-01'):\n        return 2\n    return _day_number(b) - _day_number(a)"),
        encoding="utf-8")
    assert not P.grade(task, ws).passed               # "fix the cause, not the symptom"


ANSWERS = {   # fragments of a task's answer that a skill must never contain (found after two leaks slipped through)
    "greet-cli": ["greet", "hello, "], "price-parser": ["1,00,000", "₹1,234"], "stats-empty": ["mean("],
    "csv-total": ["4374.75", "1,250.50"], "discount": ["discount("], "slugify": ["slugify("], "stack": ["stack()"],
    "cart-coupon": ["coupon", "save10"], "config-keyerror": ["'port'", "config.json"], "leap-days": ["days_between"],
    "expenses": ["1,250.50", "expenses"], "marks": ["students", "maths"], "inventory-value": ["=b2*c2", "inventory"],
    "design-shop": ["shop.xlsx", "flower", "fruit"], "add-rows": ["mango", "lily", "stock.xlsx"],
    "delete-rows": ["quantity 0", "orchid", "stock.xlsx"],
}


@pytest.mark.parametrize("skill", [s.name for s in SK.builtin_skills()])
def test_no_skill_gives_away_a_task_of_any_skill(skill):
    body = (SK.builtin_dir() / skill / "SKILL.md").read_text(encoding="utf-8").lower()
    for tasks in ST.TASKS.values():
        for task in tasks:
            name = task.id.split("/")[-1]
            files = [f for f in task.extra.get("files", {}) if not f.startswith("tests/")]
            assert name not in body and not any(f.lower() in body for f in files), (skill, task.id)
            assert not [a for a in ANSWERS[name] if a in body], (skill, task.id, ANSWERS[name])


def test_every_task_has_its_answer_fragments_listed():
    assert {t.id.split("/")[-1] for ts in ST.TASKS.values() for t in ts} == set(ANSWERS)


XLSX_REF = {
    "expenses": "import csv\nfrom openpyxl import Workbook\nwb = Workbook(); ws = wb.active; ws.title = 'Expenses'\n"
                "ws.append(['Date', 'Item', 'Amount'])\n"
                "for r in csv.DictReader(open('expenses.csv', newline='')):\n"
                "    a = float(r['amount'].replace(',', '')); ws.append([r['date'], r['item'], int(a) if a.is_integer() else a])\n"
                "ws.append(['Total', None, '=SUM(C2:C5)'])\nwb.save('expenses.xlsx')\n",
    "marks": "from openpyxl import Workbook\nwb = Workbook(); st = wb.active; st.title = 'Students'\n"
             "for r in [['Name', 'Maths', 'Science'], ['Asha', 91, 84], ['Ravi', 78, 88], ['Meena', 85, 79]]:\n"
             "    st.append(r)\n"
             "sm = wb.create_sheet('Summary'); sm.append(['Subject', 'Average'])\n"
             "sm.append(['Maths', '=AVERAGE(Students!B2:B4)']); sm.append(['Science', '=AVERAGE(Students!C2:C4)'])\n"
             "wb.save('marks.xlsx')\n",
    "design-shop": "from openpyxl import Workbook\nwb = Workbook(); ws = wb.active; ws.title = 'Inventory'\n"
                   "ws.append(['Item', 'Category', 'Quantity', 'Price (Rs)', 'Supplier'])\n"
                   "for r in [['Rose', 'Flower', 40, 10, 'A'], ['Tulip', 'Flower', 15, 25, 'A'], ['Lily', 'Flower', 20, 15, 'B'],\n"
                   "          ['Apple', 'Fruit', 50, 60, 'C'], ['Banana', 'Fruit', 120, 5, 'C'], ['Mango', 'Fruit', 30, 40, 'D']]:\n"
                   "    ws.append(r)\nwb.save('shop.xlsx')\n",
    "add-rows": "from openpyxl import load_workbook\nwb = load_workbook('stock.xlsx'); ws = wb['Stock']\n"
                "ws.insert_rows(8, 2)\nws['A8'], ws['B8'], ws['C8'], ws['D8'] = 'mango', 'fruit', 30, 40\n"
                "ws['A9'], ws['B9'], ws['C9'], ws['D9'] = 'lily', 'flower', 25, 15\n"
                "ws['C10'] = '=SUM(C2:C9)'\nwb.save('stock.xlsx')\n",
    "delete-rows": "from openpyxl import load_workbook\nwb = load_workbook('stock.xlsx'); ws = wb['Stock']\n"
                   "for r in range(ws.max_row - 1, 1, -1):\n    if ws.cell(r, 3).value == 0:\n        ws.delete_rows(r)\n"
                   "ws.cell(ws.max_row, 3).value = f'=SUM(C2:C{ws.max_row - 1})'\nwb.save('stock.xlsx')\n",
    "inventory-value": "from openpyxl import load_workbook\nwb = load_workbook('inventory.xlsx'); ws = wb['Stock']\n"
                       "ws['D1'] = 'Value'\nfor r in (2, 3, 4):\n    ws[f'D{r}'] = f'=B{r}*C{r}'\nwb.save('inventory.xlsx')\n",
}


@pytest.mark.parametrize("task", ST.for_skill("xlsx"), ids=lambda t: t.id.split("/")[-1])
def test_each_xlsx_check_fails_before_and_passes_a_correct_workbook(task, tmp_path):
    ws = tmp_path / "task"
    P.prepare(task, ws)
    assert not P.grade(task, ws).passed
    script = ws.parent / "ref.py"
    script.write_text(XLSX_REF[task.id.split("/")[-1]], encoding="utf-8")
    subprocess.run([sys.executable, str(script)], cwd=ws, check=True, timeout=60)
    check = P.grade(task, ws)
    assert check.passed, check.detail


def test_a_total_written_as_a_number_fails_the_expenses_task(tmp_path):
    task = next(t for t in ST.for_skill("xlsx") if t.id.endswith("expenses"))
    ws = tmp_path / "task"
    P.prepare(task, ws)
    (ws.parent / "ref.py").write_text(XLSX_REF["expenses"].replace("'=SUM(C2:C5)'", "4374.75"), encoding="utf-8")
    subprocess.run([sys.executable, str(ws.parent / "ref.py")], cwd=ws, check=True, timeout=60)
    assert not P.grade(task, ws).passed


TRAPS = {   # what a small model typically does wrong: each must fail the hidden check
    "add-rows": "from openpyxl import load_workbook\nwb = load_workbook('stock.xlsx'); ws = wb['Stock']\n"
                "ws.append(['mango', 'fruit', 30, 40]); ws.append(['lily', 'flower', 25, 15])\nwb.save('stock.xlsx')\n",
    "delete-rows": "from openpyxl import load_workbook\nwb = load_workbook('stock.xlsx'); ws = wb['Stock']\n"
                   "for r in range(2, ws.max_row):\n    if ws.cell(r, 3).value == 0:\n"
                   "        for c in range(1, 5):\n            ws.cell(r, c).value = None\nwb.save('stock.xlsx')\n",
    "design-shop": "from openpyxl import Workbook\nwb = Workbook(); ws = wb.active\n"
                   "ws.append(['Item', 'Category', 'Quantity', 'Price'])\n"
                   "for r in [['Rose', 'Flower', '40', '10'], ['Tulip', 'Flower', '15', '25'], ['Lily', 'Flower', '20', '15'],\n"
                   "          ['Apple', 'Fruit', '50', '60'], ['Banana', 'Fruit', '120', '5'], ['Mango', 'Fruit', '30', '40']]:\n"
                   "    ws.append(r)\nwb.save('shop.xlsx')\n",
}


@pytest.mark.parametrize("name", sorted(TRAPS))
def test_the_usual_small_model_mistakes_fail(name, tmp_path):
    """Appending below the Total, blanking cells instead of deleting rows, numbers stored as text."""
    task = next(t for t in ST.for_skill("xlsx") if t.id.endswith(name))
    ws = tmp_path / "task"
    P.prepare(task, ws)
    (ws.parent / "trap.py").write_text(TRAPS[name], encoding="utf-8")
    subprocess.run([sys.executable, str(ws.parent / "trap.py")], cwd=ws, check=True, timeout=60)
    assert not P.grade(task, ws).passed


def test_a_file_name_picks_its_skill():
    xlsx = _skill("xlsx", ["xlsx", "excel"])
    assert SK.turn_skills([xlsx], "add a Value column to inventory.xlsx", "make_change") == [xlsx]


def test_the_hidden_check_is_never_inside_the_task_folder(tmp_path):
    task = ST.for_skill("verify-before-done")[0]
    ws = tmp_path / "task"
    P.prepare(task, ws)
    P.grade(task, ws)
    assert not any("hidden" in p.name for p in ws.rglob("*"))


def _record(tmp_path, *tools):
    f = tmp_path / "rec.jsonl"
    f.write_text("\n".join(json.dumps({"kind": "tool", "name": n, "ok": True}) for n in tools), encoding="utf-8")
    return f


def test_checked_after_its_last_change(tmp_path):
    assert P.checked_after_last_change(_record(tmp_path, "read_file", "edit_file", "run_tests")) is True
    assert P.checked_after_last_change(_record(tmp_path, "run_tests", "edit_file")) is False   # E-126's false "done"
    assert P.checked_after_last_change(_record(tmp_path, "read_file")) is None


def test_the_comparison_shows_both_arms_and_each_task():
    def row(passes, checked, skills):
        return {"skills": skills, "results": [{"id": f"skill/x/t{i}", "passed": p, "checked_last": c, "seconds": 10}
                                              for i, (p, c) in enumerate(zip(passes, checked))]}
    text = P.skill_compare(row([False, True], [False, True], []), row([True, True], [True, True], ["x"]))
    assert "passed               1/2 -> 2/2" in text and "checked after change 1/2 -> 2/2" in text
    assert "t0" in text and "0/1 -> 1/1" in text


def test_the_practice_command_has_the_skill_option():
    import os
    out = subprocess.run([sys.executable, "-c", "from app.main import cli; cli()", "practice", "--help"],
                         capture_output=True, text=True, cwd=ROOT, timeout=60, encoding="utf-8", errors="replace",
                         env={**os.environ, "PYTHONUTF8": "1", "COLUMNS": "200", "NO_COLOR": "1",
                              "TERM": "dumb"}).stdout
    import re
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", out)  # CI forces colour: the codes split "--skill" (E-157)
    assert "--skill" in plain
