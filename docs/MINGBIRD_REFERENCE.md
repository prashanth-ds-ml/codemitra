# Mingbird: reference harness for small local models

**What it is:** an open-source local-first agent harness for 1-9B models on a consumer GPU, with a paper
([arXiv 2610.02001](https://arxiv.org/abs/2610.02001)). Checked on Windows with an RTX 5060 8 GB, the same class of
machine as ours. Code: [Mingbird/Mingbird-agent](https://github.com/Mingbird/Mingbird-agent), **Apache-2.0** (task suites
CC BY 4.0). Clone: `references/Mingbird-agent` (read only, never run from there; `git pull` for the author's updates).
Read on 2026-11-18 at **db9897f (v3.1.11, 2026-11-11)**, 117 commits, still active. Comments in the code are in Chinese.

Why it matters: it is CodeMitra's thesis, measured. At 4B it scored 0.876 against goose 0.801 and opencode 0.465;
turning off five of six completion checks cost 0.152; a "verify your work" prompt did not help (our verify skill: same).
See `reports/Proper coding partner research 2026-11-18.md`.

How to borrow: port ideas and small functions with credit (Apache-2.0: keep the notice, say what changed, list it in
THIRD_PARTY_NOTICES.md). Its core is one 5,249-line file (`ollama_agent.py`), so we port pieces, not the loop.

## The finish gate (the part that moves the score)
Mingbird makes "done" an explicit tool, `finish(summary)` (`ollama_agent.py:440`), and gates it in `agent_loop`
(`ollama_agent.py:4804-4995`). Checks run in this order; each has a cap (2-3 refusals) so it can never deadlock:

| # | Check | Code | CodeMitra today |
|---|---|---|---|
| 1 | No work done (no file written, no command run, no answer text) and not a question -> refuse | 4804 | E-143 `nothing_written` (only in the change phase) |
| 2 | Tests exist -> **the harness runs them itself**: pytest, else unittest, else **skip** (environment, not failure) | `_run_test_guard` 3654 | tests after a change (D-078); no "environment missing" vs "failed" split |
| 3 | Files the summary names do not exist -> refuse | `_missing_files_in_text` 3805 | E-144 (same idea) |
| 4 | Files the plan names do not exist -> refuse (plan rebuilt or files made) | `_plan_named_missing` 3914 | none |
| 5 | A `.json` deliverable does not parse -> refuse ("regenerate it with a script") | `_artifact_content_problems` 3923 | none |
| 6 | Plan progress not updated -> refuse once or twice | todo gate | none (no todo in the chat) |
| 7 | Once: re-show the original task text, "check every requirement (format, units, names), then finish again" | `_task_original_text` 3538 | none |

Rules worth copying exactly:
- A refusal always gives the **next executable action** (two or three choices, with the real working directory path),
  never only the reason; small models otherwise repeat the call or drift into unparsable text.
- A refused call is answered as refused (`[finish rejected: ...]`), never with success words.
- After all checks pass, the user always gets a short summary (one tool-less call if the model gave none).
- Questions ("qa" sessions) are exempt from the work gates.

## The anti-loop ladder (`agent_loop`, 4995-5135)
| Trigger | Action |
|---|---|
| 3 consecutive failures of one tool (a success of that tool resets) | "stop retrying, change strategy" with a tool-specific hint; `edit_file` is disabled -> write the whole file with `create_file` |
| 5 calls in a row of one tool | nudge (at most 3) |
| 8 in a row and 4 with identical arguments | disable that tool for the task |
| read window: the same read 6 times in the last 12, or A->B->A->B | block those exact reads ("other parts read normally") |
| the same web query fingerprint 6 times with no file written | disable research tools |
| 4 successful edits of the same file without the goal met (`_EditConvergenceGuard` 3961) | hint: stop guessing, read the failure, find the root cause; second time: state a hypothesis first |
| empty turns (also an unclosed `<think>`, `_semantically_empty` 3588) | reminder, then context reset |

## Smaller pieces
- **Text tool-call rescue** (`try_parse_tool_calls` 3740): JSON, `{"name","arguments"}`, lists, ```json fences,
  `<tool_call>` tags, `name(k="v")` call expressions with three gates (the whole text is one call, simple values only,
  known tool name). Compare with our `parse.py` + E-146.
- **Backup before shell rewrites** (`_bash_snapshot` 3879): `sed -i`, `>`, `cp`, `mv` on files in the workspace -> a
  `.bak` first; deletes go to a trash folder.
- **Small-model teaching**: Python code sent to `cmd` -> "write a .py with create_file, then run it" (at most twice).
- **Disabled-tool message with a progress snapshot** (`_disabled_tool_message` 3844): the plan and the files present, so
  the model can find its way back.
- **Context compaction** (`compact_history` 3092) with the plan re-injected after compression.
- **Tests**: 44 test files, including `tests/test_guards.py` (1,013 lines) for the gates and ladder.

## The benchmark (LRAB, `bench/lrab/`)
Tasks declare their checks in JSON (`exists`, `contains_any`, `contains_groups` with partial credit,
`contains_ordered`, `not_contains`, `min_words`, `structure`, `python_compiles`, `script_pass`, `file_min_bytes`).
Scores: milestones (intermediate files, the process) 40%, final artifacts 30%, an optional fixed-model judge 30%
(the paper renormalises without the judge to 4/7 and 3/7). Held-out tasks live apart (`tasks_heldout/`). Their
advice: score the process as well as the artifact; probe each mechanism; replicate (3 runs per cell).

## What to port into CodeMitra, in order (stage 1)
1. An explicit finish step and **one finish gate** with checks 1-5 and 7 above, replacing the scattered end-of-turn
   nudges (E-133, E-143, E-144, E-145) in `app/core/chat.py`; questions exempt.
2. The anti-loop ladder, extending `RepeatGuard`: per-tool failure counts, streaks, the read window, the
   edit-convergence hint.
3. "Environment missing" vs "tests failed" in our test runs.
4. Milestone + final scoring in our core benchmark (`app/core/skill_tasks.py` checks become declared checks plus
   scripts), held-out split, 3 repeats, qwen3.5:9b.

## Not to port
- The single-file loop, the GUI (`agent_gui.py`, 4,097 lines), voice and telemetry (M11, M13).
- Sub-agent dispatch (M18): its 2B never reached the trigger; one GPU makes it slow.
- The Windows-specific safety rings (the paper calls them the least portable).
- An LLM judge as the main scorer (the false-success study: judges near chance).
