---
name: xlsx
description: Make or edit Excel files (.xlsx) with openpyxl: exact sheet and column names, numbers as numbers, totals as formulas, checked by reopening.
triggers: excel, xlsx, spreadsheet, spreadsheets, workbook, workbooks, xls
source: adapted from anthropics/skills skills/xlsx (Apache-2.0), shortened for small models; LibreOffice recalculation left out
---
# Excel files with openpyxl

## Steps
1. If `import openpyxl` fails: `run_command` with `python -m pip install openpyxl`.
2. Write a small script (e.g. `build_sheet.py`) and run it, so the file can be made again:
```python
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Sales"                      # the exact name the user asked for
ws.append(["Month", "Units", "Revenue"])  # exact headers, in the asked order
for row in [["Jan", 12, 3400.5], ["Feb", 9, 2210.0]]:
    ws.append(row)
last = ws.max_row
ws.append(["Total", f"=SUM(B2:B{last})", f"=SUM(C2:C{last})"])  # a formula, not a number you computed
for cell in ws["C"][1:]:
    cell.number_format = "#,##0.00"
ws.freeze_panes = "A2"
wb.save("sales.xlsx")
```
3. Edit an existing file: `wb = load_workbook("file.xlsx")`, change only what was asked, keep the other cells and
   formulas, `wb.save` under the same name.
4. Check it: `run_command` with one line that reopens it and prints what matters:
   `python -c "from openpyxl import load_workbook; wb = load_workbook('sales.xlsx'); ws = wb.active; print(wb.sheetnames, [c.value for c in ws[1]], ws.max_row, ws.cell(ws.max_row, 3).value)"`

## Rules
- Sheet names and headers exactly as asked (same words, same case).
- Numbers as numbers: "2,400.75" in a CSV becomes `2400.75`, not the text "2,400.75".
- Totals, averages and per-row values as formulas (`=SUM(...)`, `=AVERAGE(...)`, `=D2-E2`), so they update.
- Another sheet in a formula: `=MAX(Inputs!B2:B9)`; quote names with spaces: `='Raw Data'!A1`.
- Dates: write `datetime.date` values and set `cell.number_format = "yyyy-mm-dd"`.

## Pitfalls
- openpyxl does not calculate formulas: a new file reopened with `data_only=True` shows `None`. Check the formula
  text (`=SUM(B2:B5)`) instead.
- Never save a workbook opened with `data_only=True`: its formulas are lost.
- Merged cells: write only the top-left cell. `.xlsm` files: `load_workbook(path, keep_vba=True)`.
