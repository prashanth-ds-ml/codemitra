# Third-party notices

CodeMitra's built-in skills (`app/builtin_skills/`) include material adapted from the projects below. Each adapted
skill keeps the original license file next to it and says in its `source:` line where it came from and that it was
changed (shortened and rewritten for small local models).

| Skill | Adapted from | License | Upstream commit |
|---|---|---|---|
| `xlsx` | [anthropics/skills](https://github.com/anthropics/skills) `skills/xlsx` (LibreOffice recalculation and the financial-model section left out) | Apache-2.0, Copyright Anthropic | 2026-11 copy |

The practice tasks for these skills (`app/core/skill_tasks.py`) are CodeMitra's own. Skills are added one at a time (2026-11-18): verify-before-done, writing-tests and debugging (adapted from obra/superpowers, MIT) were taken out until their turn; their tasks stay.
