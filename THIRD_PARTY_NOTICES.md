# Third-party notices

CodeMitra's built-in skills (`app/builtin_skills/`) include material adapted from the projects below. Each adapted
skill keeps the original license file next to it and says in its `source:` line where it came from and that it was
changed (shortened and rewritten for small local models).

| Skill | Adapted from | License | Upstream commit |
|---|---|---|---|
| `xlsx` | [anthropics/skills](https://github.com/anthropics/skills) `skills/xlsx` (LibreOffice recalculation and the financial-model section left out) | Apache-2.0, Copyright Anthropic | 2026-11 copy |

## Harness code

| Part | Adapted from | License | Upstream commit |
|---|---|---|---|
| The finish gate (`app/core/finish_gate.py`, `ChatSession._finish_gate`, the step runner's environment stop) | [Mingbird/Mingbird-agent](https://github.com/Mingbird/Mingbird-agent) `ollama_agent.py` finish gate (checks in order, each capped, every refusal names the next action, questions exempt). Rewritten for CodeMitra: our own check list and notes, no code copied verbatim | Apache-2.0, Copyright the Mingbird authors | db9897f (v3.1.11) |

The practice tasks for these skills (`app/core/skill_tasks.py`) are CodeMitra's own. Skills are added one at a time (2026-11-18): verify-before-done, writing-tests and debugging (adapted from obra/superpowers, MIT) were taken out until their turn; their tasks stay.
