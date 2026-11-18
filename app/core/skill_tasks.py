"""v0.9.0: practice tasks for the built-in skills (BUILD_V09 F-0). Each skill has a few small seeded projects and a
request; a hidden check script (kept outside the task folder) decides. `codemitra practice --skill <name>` runs them
without and with that one skill, so a skill is kept only when it helps.

The tasks are ours (MIT). Each is easy to get almost right, so a model that never runs anything tends to fail it.
"""
from __future__ import annotations

from app.core.practice import Task

_SRC, _LIC = "codemitra", "MIT (CodeMitra's own)"


def _task(skill: str, name: str, prompt: str, files: dict[str, str], check: str) -> Task:
    return Task(id=f"skill/{skill}/{name}", kind="skill", source=_SRC, licence=_LIC, prompt=prompt, test=check,
                extra={"files": files, "skill": skill})


VERIFY = [
    _task("verify-before-done", "greet-cli",
          "Make greet.py print `Hello, <name>!` when run as `python greet.py <name>`, and `Hello, world!` when "
          "it is run with no name.",
          {"greet.py": "import sys\n\n# TODO: greet the person named on the command line\n"},
          "import subprocess, sys\n"
          "def run(*a):\n"
          "    return subprocess.run([sys.executable, 'greet.py', *a], capture_output=True, text=True, timeout=20)"
          ".stdout.strip()\n"
          "assert run('Asha') == 'Hello, Asha!', run('Asha')\n"
          "assert run() == 'Hello, world!', run()\n"),
    _task("verify-before-done", "price-parser",
          "Implement parse_price in prices.py so the tests in tests/test_prices.py pass.",
          {"prices.py": "def parse_price(text: str) -> float:\n"
                        "    \"\"\"'₹1,234.50' -> 1234.5, 'Rs. 99' -> 99.0, '1,00,000' -> 100000.0\"\"\"\n"
                        "    raise NotImplementedError\n",
           "tests/test_prices.py": "from prices import parse_price\n\n\n"
                                   "def test_rupee_symbol():\n    assert parse_price('₹1,234.50') == 1234.5\n\n\n"
                                   "def test_rs_prefix():\n    assert parse_price('Rs. 99') == 99.0\n\n\n"
                                   "def test_indian_grouping():\n    assert parse_price('1,00,000') == 100000.0\n"},
          "import sys; sys.path.insert(0, '.')\n"
          "from prices import parse_price\n"
          "cases = {'₹1,234.50': 1234.5, 'Rs. 99': 99.0, '1,00,000': 100000.0, ' ₹ 12,345 ': 12345.0, "
          "'Rs.0.75': 0.75, 'INR 2,50,000.25': 250000.25}\n"
          "for text, want in cases.items():\n"
          "    got = parse_price(text)\n"
          "    assert abs(got - want) < 1e-9, (text, got, want)\n"),
    _task("verify-before-done", "stats-empty",
          "mean() in stats.py crashes on an empty list. Make it return 0.0 for an empty list and keep everything else "
          "working.",
          {"stats.py": "def mean(xs):\n    return sum(xs) / len(xs)\n\n\n"
                       "def median(xs):\n    s = sorted(xs)\n    n = len(s)\n    mid = n // 2\n"
                       "    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2\n",
           "tests/test_stats.py": "from stats import mean, median\n\n\n"
                                  "def test_mean():\n    assert mean([1, 2, 3]) == 2\n\n\n"
                                  "def test_median():\n    assert median([3, 1, 2]) == 2\n    "
                                  "assert median([4, 1, 3, 2]) == 2.5\n"},
          "import sys; sys.path.insert(0, '.')\n"
          "from stats import mean, median\n"
          "assert mean([]) == 0.0\n"
          "assert mean([1, 2, 3]) == 2 and mean([2.5]) == 2.5\n"
          "assert median([3, 1, 2]) == 2 and median([4, 1, 3, 2]) == 2.5\n"),
    _task("verify-before-done", "csv-total",
          "report.py should read sales.csv and print the total of the amount column, with 2 decimals, e.g. "
          "`Total: 123.45`. Finish it.",
          {"report.py": "import csv\n\n# TODO: print the total of the amount column of sales.csv\n",
           "sales.csv": "date,item,amount\n2026-11-01,chai,40\n2026-11-02,laptop stand,\"1,250.50\"\n"
                        "2026-11-03,notebook,85.25\n2026-11-04,headphones,\"2,999\"\n"},
          "import subprocess, sys\n"
          "out = subprocess.run([sys.executable, 'report.py'], capture_output=True, text=True, timeout=20)"
          ".stdout.strip()\n"
          "assert out.splitlines()[-1].strip() == 'Total: 4374.75', out\n"),
]

def _mutation_check(module: str, correct: str, mutants: list[str]) -> str:
    """The hidden check for a "write tests" task: CodeMitra's tests run in a copy of the folder, first with the correct
    module (they must pass, and there must be some), then with each broken version (each must make a test fail).
    The module CodeMitra may have edited is replaced by ours, so changing the code does not help."""
    return (
        "import os, pathlib, shutil, subprocess, sys, tempfile\n"
        f"MODULE = {module!r}\nCORRECT = {correct!r}\nMUTANTS = {mutants!r}\n"
        "def run(source):\n"
        "    with tempfile.TemporaryDirectory() as tmp:\n"
        "        dst = pathlib.Path(tmp) / 'p'\n"
        "        shutil.copytree('.', dst, ignore=shutil.ignore_patterns('__pycache__', '.codemitra', '.pytest_cache'))\n"
        "        (dst / MODULE).write_text(source, encoding='utf-8')\n"
        "        p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'], cwd=dst,\n"
        "                           capture_output=True, text=True, timeout=120)\n"
        "        return p.returncode, p.stdout[-600:]\n"
        "rc, out = run(CORRECT)\n"
        "assert rc == 0 and ' passed' in out, 'tests do not pass on the correct code: ' + out\n"
        "missed = [i for i, m in enumerate(MUTANTS) if run(m)[0] != 1]\n"
        "assert not missed, f'tests did not catch broken version(s) {missed} of {len(MUTANTS)}'\n")


_DISCOUNT = ("def discount(price, percent):\n"
             "    \"\"\"price after `percent` off, rounded to 2 decimals. percent must be 0-100 and price >= 0,\n"
             "    else ValueError.\"\"\"\n"
             "    if not 0 <= percent <= 100:\n        raise ValueError('percent must be 0-100')\n"
             "    if price < 0:\n        raise ValueError('price must be >= 0')\n"
             "    return round(price * (1 - percent / 100), 2)\n")
_SLUG = ("import re\n\n\ndef slugify(text):\n"
         "    \"\"\"'  Hello, World!  ' -> 'hello-world': lower case, every run of other characters becomes one '-',\n"
         "    no '-' at the ends.\"\"\"\n"
         "    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n")
_STACK = ("class Stack:\n"
          "    \"\"\"push(x); pop() and peek() raise IndexError when empty; peek() does not remove; len() is the size.\"\"\"\n"
          "    def __init__(self):\n        self._items = []\n\n"
          "    def push(self, x):\n        self._items.append(x)\n\n"
          "    def pop(self):\n        if not self._items:\n            raise IndexError('pop from empty stack')\n"
          "        return self._items.pop()\n\n"
          "    def peek(self):\n        if not self._items:\n            raise IndexError('peek at empty stack')\n"
          "        return self._items[-1]\n\n"
          "    def __len__(self):\n        return len(self._items)\n")

TESTS = [
    _task("writing-tests", "discount",
          "Add pytest tests for discount() in discount.py. Do not change discount.py.",
          {"discount.py": _DISCOUNT},
          _mutation_check("discount.py", _DISCOUNT, [
              _DISCOUNT.replace("if not 0 <= percent <= 100:", "if not 0 <= percent <= 1000:"),
              _DISCOUNT.replace("return round(price * (1 - percent / 100), 2)", "return price * (1 - percent / 100)"),
              _DISCOUNT.replace("if price < 0:", "if price < -1000:")])),
    _task("writing-tests", "slugify",
          "Write tests for slugify() in text_utils.py. Do not change text_utils.py.",
          {"text_utils.py": _SLUG},
          _mutation_check("text_utils.py", _SLUG, [
              _SLUG.replace("text.lower()", "text"),
              _SLUG.replace("r'[^a-z0-9]+'", "r'[^a-z0-9]'"),
              _SLUG.replace(".strip('-')", "")])),
    _task("writing-tests", "stack",
          "Add unit tests for the Stack class in stack.py. Do not change stack.py.",
          {"stack.py": _STACK},
          _mutation_check("stack.py", _STACK, [
              _STACK.replace("raise IndexError('pop from empty stack')", "return None"),
              _STACK.replace("return self._items[-1]", "return self._items.pop()"),
              _STACK.replace("return len(self._items)", "return len(self._items) + 0 if self._items else 1")])),
]

_CART = ("PRICES = {'pen': 100, 'book': 250, 'bag': 900}\nCOUPONS = {'SAVE10': 0.10, 'SAVE25': 0.25}\n\n\n"
         "def total(items, coupon=None):\n"
         "    \"\"\"items: {name: quantity}. A coupon takes its percent off the whole order once.\"\"\"\n"
         "    off = COUPONS.get(coupon, 0)\n"
         "    amount = 0\n"
         "    for name, qty in items.items():\n"
         "        line = PRICES[name] * qty\n"
         "        if off:\n            line = line * (1 - off)\n"
         "        amount += line\n"
         "    return round(amount * (1 - off), 2)\n")
_DAYS = ("MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]\n\n\n"
         "def _day_number(date):\n"
         "    y, m, d = (int(x) for x in date.split('-'))\n"
         "    days = y * 365 + y // 4 - y // 100 + y // 400\n"
         "    days += sum(MONTH_DAYS[:m - 1])\n"
         "    return days + d\n\n\n"
         "def days_between(a, b):\n"
         "    \"\"\"Days from date a to date b ('YYYY-MM-DD').\"\"\"\n"
         "    return _day_number(b) - _day_number(a)\n")

DEBUG = [
    _task("debugging", "cart-coupon",
          "The cart total is wrong with a coupon: 2 pens with SAVE10 should cost 180 but total() gives 162. Fix it.",
          {"cart.py": _CART,
           "tests/test_cart.py": "from cart import total\n\n\ndef test_no_coupon():\n"
                                 "    assert total({'pen': 2, 'book': 1}) == 450\n"},
          "import sys; sys.path.insert(0, '.')\nfrom cart import total\n"
          "assert total({'pen': 2}, 'SAVE10') == 180, total({'pen': 2}, 'SAVE10')\n"
          "assert total({'pen': 2, 'book': 1}) == 450\n"
          "assert total({'bag': 1, 'book': 2}, 'SAVE25') == 1050\n"
          "assert total({'pen': 1}, 'NOPE') == 100\n"),
    _task("debugging", "config-keyerror",
          "`python app.py` crashes with KeyError: 'port'. It should print `Serving on localhost:8080`. Fix it.",
          {"app.py": "import json\n\nwith open('config.json') as f:\n    cfg = json.load(f)\n\n"
                     "print(f\"Serving on {cfg['host']}:{cfg['port']}\")\n",
           "config.json": "{\n  \"host\": \"localhost\",\n  \"PORT\": 8080\n}\n"},
          "import json, subprocess, sys\n"
          "out = subprocess.run([sys.executable, 'app.py'], capture_output=True, text=True, timeout=20)\n"
          "assert out.stdout.strip() == 'Serving on localhost:8080', out.stdout + out.stderr\n"
          "json.load(open('config.json'))  # still valid JSON\n"),
    _task("debugging", "leap-days",
          "days_between('2024-02-28', '2024-03-01') returns 1, but it should be 2. Fix days_between in dates.py.",
          {"dates.py": _DAYS},
          "import sys; sys.path.insert(0, '.')\nfrom dates import days_between\n"
          "cases = {('2024-02-28', '2024-03-01'): 2, ('2026-03-01', '2026-03-05'): 4, ('2023-02-28', '2023-03-01'): 1,"
          " ('2024-01-01', '2025-01-01'): 366, ('2025-01-01', '2026-01-01'): 365, ('2000-02-28', '2000-03-01'): 2,"
          " ('1900-02-28', '1900-03-01'): 1}\n"
          "for (a, b), want in cases.items():\n"
          "    assert days_between(a, b) == want, (a, b, days_between(a, b), want)\n"),
]

_OPEN = "import sys\nfrom openpyxl import load_workbook\n"

XLSX = [
    _task("xlsx", "expenses",
          "Create expenses.xlsx from expenses.csv: one sheet named Expenses with the columns Date, Item, Amount, the "
          "rows from the CSV, and a Total row at the bottom whose Amount is a SUM formula.",
          {"expenses.csv": "date,item,amount\n2026-11-01,chai,40\n2026-11-02,laptop stand,\"1,250.50\"\n"
                           "2026-11-03,notebook,85.25\n2026-11-04,headphones,\"2,999\"\n"},
          _OPEN + "wb = load_workbook('expenses.xlsx')\n"
          "assert wb.sheetnames == ['Expenses'], wb.sheetnames\n"
          "ws = wb['Expenses']\n"
          "assert [c.value for c in ws[1]][:3] == ['Date', 'Item', 'Amount'], [c.value for c in ws[1]]\n"
          "amounts = [ws.cell(r, 3).value for r in range(2, 6)]\n"
          "assert amounts == [40, 1250.5, 85.25, 2999], amounts\n"
          "assert str(ws.cell(6, 1).value).strip().lower() == 'total', ws.cell(6, 1).value\n"
          "f = str(ws.cell(6, 3).value).replace(' ', '').upper()\n"
          "assert f in ('=SUM(C2:C5)', '=SUM(C$2:C$5)', '=SUM($C$2:$C$5)'), f\n"),
    _task("xlsx", "marks",
          "Make marks.xlsx with a sheet Students (columns Name, Maths, Science) for Asha 91 84, Ravi 78 88 and "
          "Meena 85 79, and a sheet Summary that shows the average of Maths and of Science as formulas that use the "
          "Students sheet.",
          {},
          _OPEN + "wb = load_workbook('marks.xlsx')\n"
          "assert set(wb.sheetnames) >= {'Students', 'Summary'}, wb.sheetnames\n"
          "st = wb['Students']\n"
          "rows = [[c.value for c in r][:3] for r in st.iter_rows(min_row=1, max_row=4)]\n"
          "assert rows[0] == ['Name', 'Maths', 'Science'], rows\n"
          "assert sorted(rows[1:]) == sorted([['Asha', 91, 84], ['Ravi', 78, 88], ['Meena', 85, 79]]), rows\n"
          "fs = [str(c.value).replace(' ', '').upper() for r in wb['Summary'].iter_rows() for c in r\n"
          "      if isinstance(c.value, str) and c.value.startswith('=')]\n"
          "assert any('AVERAGE(STUDENTS!B2:B4)' in f.replace('$', '') for f in fs), fs\n"
          "assert any('AVERAGE(STUDENTS!C2:C4)' in f.replace('$', '') for f in fs), fs\n"),
    _task("xlsx", "inventory-value",
          "In inventory.xlsx add a column Value (Qty times Price) as a formula for every item row, with the header "
          "Value. Keep everything else in the file as it is.",
          {},
          _OPEN + "wb = load_workbook('inventory.xlsx')\n"
          "ws = wb['Stock']\n"
          "assert [c.value for c in ws[1]][:4] == ['Item', 'Qty', 'Price', 'Value'], [c.value for c in ws[1]]\n"
          "assert ws['A2'].value == 'pen' and ws['B3'].value == 4 and ws['C4'].value == 900\n"
          "assert ws['F1'].value == 'checked by: Asha'\n"
          "for r in (2, 3, 4):\n"
          "    f = str(ws.cell(r, 4).value).replace(' ', '').upper().replace('$', '')\n"
          "    assert f in (f'=B{r}*C{r}', f'=C{r}*B{r}'), (r, f)\n"
          "assert ws.max_row == 4, ws.max_row\n",
          ) ,
]
_STOCK_SETUP = ("from openpyxl import Workbook\nwb = Workbook()\nws = wb.active\nws.title = 'Stock'\n"
                "ws.append(['Item', 'Category', 'Qty', 'Price'])\n"
                "for row in [['rose', 'flower', 40, 10], ['apple', 'fruit', 0, 60], ['tulip', 'flower', 15, 25],\n"
                "            ['banana', 'fruit', 120, 5], ['orchid', 'flower', 0, 150], ['grapes', 'fruit', 35, 80]]:\n"
                "    ws.append(row)\n"
                "ws.append(['Total', None, '=SUM(C2:C7)', None])\nwb.save('stock.xlsx')\n")
_ROWS = ("import re\nfrom openpyxl import load_workbook\n"
         "ws = load_workbook('stock.xlsx')['Stock']\n"
         "rows = [[c.value for c in r][:4] for r in ws.iter_rows(min_row=2, max_row=ws.max_row)]\n"
         "assert [c.value for c in ws[1]][:4] == ['Item', 'Category', 'Qty', 'Price'], [c.value for c in ws[1]]\n"
         "assert all(any(v not in (None, '') for v in r) for r in rows), ('a blank row', rows)\n"
         "total = rows[-1]\n"
         "assert str(total[0]).strip().lower() == 'total', ('the Total row must stay last', rows)\n"
         "items = rows[:-1]\n"
         "f = str(total[2]).replace(' ', '').replace('$', '').upper()\n"
         "assert f == f'=SUM(C2:C{len(items) + 1})', ('the total must add every item row', f, len(items))\n")

XLSX += [
    _task("xlsx", "design-shop",
          "Make shop.xlsx: an inventory for a small shop that sells flowers and fruits, with sample data.",
          {},
          "from openpyxl import load_workbook\n"
          "ws = load_workbook('shop.xlsx').worksheets[0]\n"
          "head = [str(c.value).strip().lower() for c in ws[1] if c.value not in (None, '')]\n"
          "assert len(head) >= 4, ('at least 4 columns', head)\n"
          "def col(*words):\n"
          "    for i, h in enumerate(head):\n"
          "        if any(w in h for w in words):\n"
          "            return i\n"
          "    raise AssertionError(('no column for', words, head))\n"
          "name, cat = col('item', 'name', 'product'), col('categ', 'type', 'kind')\n"
          "qty, price = col('qty', 'quant', 'stock', 'units', 'count'), col('price', 'cost', 'rate', 'mrp')\n"
          "rows = []\n"
          "for r in ws.iter_rows(min_row=2, values_only=True):\n"
          "    if r[name] in (None, ''):\n"
          "        break\n"
          "    if str(r[name]).strip().lower().startswith(('total', 'grand total', 'sum')):  # 'Total Stock' too\n"
          "        break\n"
          "    rows.append(r)\n"
          "assert len(rows) >= 6, ('at least 6 items', len(rows))\n"
          "cats = ' '.join(str(r[cat]).lower() for r in rows)\n"
          "assert 'flower' in cats and 'fruit' in cats, ('both flowers and fruits', cats)\n"
          "for r in rows:\n"
          "    assert isinstance(r[qty], (int, float)) and isinstance(r[price], (int, float)), ('numbers, not text', r)\n"),
    _task("xlsx", "add-rows",
          "Add two items to stock.xlsx: mango (fruit, quantity 30, price 40) and lily (flower, quantity 25, price 15). "
          "Keep the Total right.",
          {},
          _ROWS + "names = [r[0] for r in items]\n"
          "assert names[:6] == ['rose', 'apple', 'tulip', 'banana', 'orchid', 'grapes'], ('old rows changed', names)\n"
          "got = {r[0]: r[1:] for r in items}\n"
          "assert got.get('mango') == ['fruit', 30, 40] and got.get('lily') == ['flower', 25, 15], got\n"
          "assert len(items) == 8, names\n"),
    _task("xlsx", "delete-rows",
          "Remove every item with quantity 0 from stock.xlsx. Keep the Total right.",
          {},
          _ROWS + "assert [r[0] for r in items] == ['rose', 'tulip', 'banana', 'grapes'], [r[0] for r in items]\n"
          "assert [r[2] for r in items] == [40, 15, 120, 35], [r[2] for r in items]\n"),
]
XLSX[4].extra["setup"] = _STOCK_SETUP
XLSX[5].extra["setup"] = _STOCK_SETUP
XLSX[2].extra["setup"] = ("from openpyxl import Workbook\nwb = Workbook()\nws = wb.active\nws.title = 'Stock'\n"
                          "ws.append(['Item', 'Qty', 'Price'])\nws.append(['pen', 10, 100])\nws.append(['book', 4, 250])\n"
                          "ws.append(['bag', 1, 900])\nws['F1'] = 'checked by: Asha'\nwb.save('inventory.xlsx')\n")

TASKS: dict[str, list[Task]] = {"verify-before-done": VERIFY, "writing-tests": TESTS, "debugging": DEBUG,
                                "xlsx": XLSX}


def for_skill(name: str) -> list[Task]:
    return list(TASKS.get(name, []))
