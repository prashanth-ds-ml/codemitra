---
name: xlsx
description: Make or edit Excel (.xlsx) files with openpyxl.
triggers: excel, xlsx, spreadsheet, spreadsheets, workbook, workbooks, xls
source: CodeMitra's own (ladder v0); later steps take ideas from anthropics/skills skills/xlsx (Apache-2.0)
---
# Excel files
1. Write a short Python script that uses openpyxl, then run it with run_command. A script you did not run changed nothing.
2. An existing file: open it with `load_workbook("name.xlsx")` and change only what was asked. Never start a new `Workbook()` for it: that erases the file.
3. After running it, reopen the file and print what you changed, to check it.
