# Spec-driven development for CodeMitra (I-37) · in progress (ROADMAP Stage 2)

**2026-11-19:** S0 done as ROADMAP 2.1 (918391c, 5e975a1): a big request goes to the planner and Go runs the step runner; the 9B does not choose to plan by itself, so the rules' "big" decides (E-150). Agreed: specs in the project's `specs/`, you approve each spec before code. S2's fail-first check comes with S1 (E-151).
**2026-11-20:** S1 + S2 done (F-143): `specs/project.md` (template, read by the planner once you fill it), `specs/F-nnn-<slug>.md`, `/spec`, fail-first; live check in EVALS. Records carry spec + feature IDs. Next from this plan: S3 (linked records: mostly done in Stage 1), S4 `codemitra status` (ROADMAP 2.7).
**2026-11-21:** S4 done (F-155): `codemitra status [--check]`; per-feature cost is planned builds only; the dashboard section is not built (parked with the dashboard).

**Your words (2026-11-17):** "if we can have spec driven development i feel we can have all the features there test
cases and all possible things or must have things that will help codemitra to work properly and i also believe we can
have proper logs and traces and tasks like some thing to measure how many features, how many tasks", "for small
models ... we can focus on particular feature and its related tasks and tests".

**Why it fits small models:** a 4-9B model loses track in a big, mixed context and does not know when it is done. One
feature, one task, its files and its checks is a small context with a clear end. Evidence so far: the same 4B scored
71/72 with a good plan and tests and looped without one (SELF_IMPROVEMENT §10); E-126 drifted to another project and
claimed "fixed" with failing tests during one long free-form turn; the Trip Splitter turn (E-141) carried 24.7K tokens
of history before writing a line. Limits: writing the spec and splitting it into tasks is where small models are
weakest (so you approve it, later a bigger model may guide it, D-082); a task that is still too big fails anyway;
changes across features need their own handling; UI and "feels right" criteria need a person. Not proven for small
models until measured (§15: spec vs. no spec on the same tasks).

## 1. What exists, what is half-built, what is missing (checked 2026-11-17)

| Piece | State |
|---|---|
| Planner: context pack, runnable plan (`### T1:` … `- Done when:`), plan check, Go / Change / Save / Cancel, saved in `.codemitra/plans/` (D-065 P4) | built v0.3.0, **reached only by typing `/plan`** since the phased chat became the default (v0.7.0, `request_kind == "big" and (force_kind or not one_codemitra)`). Real logs: `/plan` typed 0 times |
| Step runner: one task at a time with a fresh small context, its Done-when check, rollback of a failed step, one re-plan, `.codemitra/resume.md` (P5) | built, same: only after `/plan`; `run_plan` as a tool 12 times |
| The default chat's `propose_plan` phase | writes a short plan **as chat text** (no runnable format, no check, no menu); used once. A "yes" to "Shall I proceed with this plan?" starts the **free-form change phase** (one long turn with the whole history), not the step runner: the path of E-125 / E-126 |
| Resume brief, "where did we stop" (P1) | built |
| Spec layer: features, acceptance criteria with checks, stable IDs, project rules | missing |
| Records linked to feature / task / criterion, tokens and time per task (§15 Phase 1, I-32) | missing |
| `codemitra status`: counts, per-feature cost, drift | missing |

## 2. The structure

```
specs/project.md               vision · must-haves · project rules ("pytest", "no new library without asking")
specs/F-003-expense-form.md    goal · out of scope · status
                               AC-1..n acceptance criteria, each with its check (test or command) or "you check"
                               T-1..n tasks, each small, "Done when: <check> passes", the files it touches
tests/test_F003_AC2_*.py       tests named after their criterion
.codemitra/runs/...            every turn and task record carries feature, task and criterion IDs
```
Small changes and questions skip specs; they are recorded as "unplanned work". The plan format of D-065 stays: a
feature's tasks are a runnable plan, so `/run` and the step runner work on them unchanged.

## 3. Build order (each step: tests that fail without it, the full suite, a live check; then the next)

| Step | What | Size |
|---|---|---|
| **S0. Reconnect what exists** | A bigger build in the default chat goes through the real planner (runnable plan, plan check, Go / Change / Save / Cancel) instead of a chat-text plan; Go runs the step runner (fresh context per task, checks, re-plan, resume.md) instead of the free-form change phase. The plan check also refuses a task that is too big (too many files, no single check). Live check: the Neon Chomp PRD and the Trip Splitter doc request | 1 day |
| **S1. Spec format** | `specs/project.md` + feature specs with stable IDs (F-, AC-, T-), short templates with an example; for a new feature or a project from scratch the planner drafts the spec first (goal, 3-7 criteria each with a check, out of scope), you approve it, then its tasks; `/spec` to view or edit | 1-2 days |
| **S2. Criteria become checks first** | each criterion gets its test or command before the code (red before green: it must fail first); "you check" criteria are asked at the end and never count as verified by themselves | 1 day |
| **S3. Linked records** | task records (§15 Phase 1, I-32) carry feature / task / criterion IDs, outcome from the checks, tokens and time (model / tools / your time); chat work outside any feature is "unplanned" | 1-2 days |
| **S4. `codemitra status`** | features done / in progress / not started; criteria passing / failing / you check; tasks done, first try, re-planned, needs help; tests; drift (a criterion that passed and fails now); unplanned work; tokens and time per feature and task; also a dashboard section | 1 day |
| **S5. Read existing specs** | a project with GitHub Spec Kit or Kiro files: CodeMitra reads them instead of asking again | ½ day |
| **S6. Measure it** | §15's exam and replay set run with and without specs on the same from-scratch tasks: verified success, tokens, time. Keep it only if it helps | with §15 Phase 3 |

About 5-7 days for S0-S5. S0 is a fix of something already built and helps today, with or without the rest.

## 4. Example of `codemitra status` (illustrative)
```
Trip Splitter · specs/                                    v0.9.2 · 17 Nov
Features      12   ✓ done 7 · ◐ in progress 3 · ○ not started 2
Criteria      48   ✓ passing 39 · ✗ failing 6 · 👤 you check 3
Tasks         61   ✓ done 52 (first try 38 · re-planned 9) · needs help 2
Drift          2   criteria that passed before and fail now (F-002 AC-3, F-005 AC-1)
Unplanned     14   chat requests outside any feature
Cost               1.9M tokens · 6.4 h CodeMitra time · 2.1 h your time · Kaggle 3.0 h
```

## 5. CodeMitra itself
The same structure can hold CodeMitra's own must-haves (D-077) and features with their acceptance tests, so
`codemitra status` on this repo shows what works. Optional, after S4.
