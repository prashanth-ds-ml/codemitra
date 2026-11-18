"""Step 0 before the xlsx skill ladder (2026-11-18): three things that hid what a skill does.
- the design-shop check counted a "Total Stock" row as an item (the check's bug, not CodeMitra's)
- E-145 lost the unrun script when the turn switched from look to change (delete-rows: "I've removed all items" with
  the script never run)
- E-146: the decide call answered "*make_change*: Add two items to stock.xlsx ..." as text and the turn ended"""
import subprocess
import sys

from langchain_core.messages import AIMessage

from app.core import chat as C
from app.core import practice as P
from app.core import skill_tasks as ST
from tests.test_live_20261113_b import _msgs, _rows, _session
from tests.test_phased import Heard


def tc(name, n, **args):
    return {"name": name, "args": args, "id": str(n)}


def test_a_design_with_a_total_stock_row_passes(tmp_path):
    task = next(t for t in ST.for_skill("xlsx") if t.id.endswith("design-shop"))
    ws = tmp_path / "task"
    P.prepare(task, ws)
    script = ("from openpyxl import Workbook\nwb = Workbook(); ws = wb.active\n"
              "ws.append(['Item', 'Category', 'Quantity', 'Unit Price'])\n"
              "for r in [['Rose', 'Flower', 40, 10], ['Tulip', 'Flower', 15, 25], ['Lily', 'Flower', 20, 15],\n"
              "          ['Apple', 'Fruit', 50, 60], ['Banana', 'Fruit', 120, 5], ['Mango', 'Fruit', 30, 40]]:\n"
              "    ws.append(r)\nws.append(['Total Stock', None, '=SUM(C2:C7)', None])\nwb.save('shop.xlsx')\n")
    (tmp_path / "ref.py").write_text(script, encoding="utf-8")
    subprocess.run([sys.executable, str(tmp_path / "ref.py")], cwd=ws, check=True, timeout=60)
    check = P.grade(task, ws)
    assert check.passed, check.detail


def test_the_live_text_phase_is_read_as_that_phase():
    live = ("*make_change*: Add two items to stock.xlsx: mango (fruit, quantity 30, price 40) and lily (flower, "
            "quantity 25, price 15). Keep the Total right.")
    assert C.text_phase(live)[0] == "make_change" and C.text_phase(live)[1].startswith("Add two items")
    assert C.text_phase("look_at_code: the stock file")[0] == "look_at_code"
    assert C.text_phase("I will make_change: later") is None and C.text_phase("Here is the plan.") is None


def test_a_text_phase_starts_the_change(tmp_path):
    m = Heard(AIMessage(content="*make_change*: Add two items to stock.xlsx."),
              AIMessage(content="", tool_calls=[tc("write_file", 1, path="notes.md", content="x\n")]),
              AIMessage(content="Created `notes.md`."))
    s = _session(tmp_path, m)
    s.phased(_msgs("Add two items to stock.xlsx and create notes.md"))
    assert s.last_phase == "make_change" and (tmp_path / "notes.md").is_file()
    assert any(r["kind"] == "phase" and r.get("from_text") for r in _rows(s))


def test_an_unrun_script_is_caught_after_a_look_to_change_switch(tmp_path):
    (tmp_path / "stock.xlsx").write_bytes(b"PK")
    m = Heard(AIMessage(content="", tool_calls=[tc("look_at_code", 1, what="stock.xlsx")]),
              AIMessage(content="", tool_calls=[tc("write_file", 2, path="clean.py", content="print(1)\n")]),
              AIMessage(content="I've removed all items with quantity 0 from `stock.xlsx`."),
              AIMessage(content="", tool_calls=[tc("run_command", 3, command="python clean.py")]),
              AIMessage(content="Ran clean.py."))
    s = _session(tmp_path, m)
    s.phased(_msgs("how many items have quantity 0 in stock.xlsx? remove every one of them"))
    assert any(r["kind"] == "script_not_run" and r["script"] == "clean.py" for r in _rows(s))
