# CodeMitra roadmap: a proper coding partner on small local models (2026-11-18, order revised the same day)

**This is the one plan.** It replaces the "Next up" list in [PLAN.md](PLAN.md) (2026-11-07) and puts the other plans
in order: [SPEC_DRIVEN.md](SPEC_DRIVEN.md) (I-37), [BUILD_V09.md](BUILD_V09.md) (skills, MCP, logging, dashboard,
friends' logs), [SELF_IMPROVEMENT.md](SELF_IMPROVEMENT.md) §14-15. Nothing in them is dropped; each has its stage.
Evidence behind it: `reports/Proper coding partner research 2026-11-18.md`, [MINGBIRD_REFERENCE.md](MINGBIRD_REFERENCE.md),
EVALS.md (2026-11-18 skill runs).

**The goal (unchanged):** a coding assistant and partner for my own projects that runs on local models (8 GB laptop,
Kaggle for heavy work), like Claude Code but built for small models, and that gets better with use.

**The three priorities (2026-11-18):** proper spec-driven development as the backbone; logs and traces that answer
everything we need; use the MCP servers that already exist instead of building new tools.

**The one rule:** a stage starts only when the one before it holds. From Stage 3 on, every stage ends with a number on
the spec benchmark, on **qwen3.5:9b** (the model CodeMitra uses), 3 repeats.

## Stage 1 · Logs and traces that answer every question
"Complete" means: for **any** task, the logs answer each question below, and each answer is covered by a test.

| # | Question the logs must answer |
|---|---|
| 1 | What was asked; which spec, feature and task it belongs to; what kind of task it was |
| 2 | Every model call: prompt, reply, tokens in / out, time to first token, total time, model, backend (laptop / Kaggle) |
| 3 | Every tool call (our tools **and** MCP tools): arguments, output, ok / failed, time |
| 4 | Files changed: snapshot before, diff after; and what the user changed afterwards |
| 5 | Checks run and their results; was the final claim ("done", "tests pass") true |
| 6 | Skills, MCP tools and lessons used in the turn |
| 7 | Time split: model / tools / waiting for the user; machine |
| 8 | What went wrong (mistake tag), and can the task be replayed exactly |

| Step | What |
|---|---|
| 1.1 | Audit: `codemitra trace check` (every recorded turn, % per question) and `codemitra trace last`. Baseline 2026-11-18: 0 of 226 turns answer all 8 (EVALS) |
| 1.2 | IDs on every turn: session, turn, step; spec / feature / task (empty until Stage 2); schema version |
| 1.3 | Tool rows: seconds; the full output in the trace when the row is cut; MCP calls in the same record |
| 1.4 | File changes: a `change` row per write (diff, before / after hashes); file hashes at turn start |
| 1.5 | Claims: what the reply claims, the evidence rows, a true / false / unchecked verdict |
| 1.6 | Used: skills, MCP tools and lessons on `turn_end` |
| 1.7 | Time and machine: model / tools / wait seconds on `turn_end`; OS, GPU, RAM, Ollama version on the session |
| 1.8 | Mistake tags: a fixed list (~10), set by rules; model labels marked as such |
| 1.10 | Replay: one turn rebuilt from its records and rerun on the same start files |

**Status 2026-11-18: done.** Live check 10 of 10 turns answer all 8 (EVALS). Known limits: replay re-sends the first
call and checks the start files by hash (no file contents); rule tags miss intent (misread request, wrong file);
the step runner's records (`/plan`, nights) get these facts in Stage 2.

**Delivers:** task records tied to spec / feature / task IDs; `codemitra trace` to look them up.
**Done when:** a test per question passes, and `trace check` scores 100% on ~10 new live turns (qwen3.5:9b, a demo
project: a question, an edit, a new file, a failing test, a false "done", Kaggle if up).

## Stage 2 · Spec-driven core, made reliable
**Status 2026-11-19:** 2.1 done (a request the rules sort "big" goes to the planner; Go runs the step runner). Live check (EVALS): the 9B never chose to plan itself (E-150, rules decide), Done-when checks can test nothing (E-151: the fail-first check moves into 2.2 with the spec format), a missing package loops (E-152: 2.4 and a plan check for uninstalled imports before Go). Decisions: specs live in the project's `specs/`; you approve every spec before code. **2.2 + fail-first done 2026-11-20** (F-143, F-144): specs with criteria and their own new tests, `/spec`, missing libraries offered for install; live: the docs feature built with the README link really there. Next: 2.4 finish gate.

| Step | What | From |
|---|---|---|
| 2.1 | I-37 S0: a bigger request in the normal chat goes through the planner (runnable plan, Go / Change / Save) and the step runner (fresh context per task, checks, one re-plan), not one long free-form turn | SPEC_DRIVEN |
| 2.2 | Specs: `specs/` with features, acceptance criteria and their checks, stable IDs, written before code | SPEC_DRIVEN S1-S2 |
| 2.3 | **One finish gate = the spec's checks**, plus: no work done / tests fail (run by CodeMitra; "can't run tests here" is not a failure) / named files missing / plan files missing / broken JSON / once: re-show the task. Replaces the scattered end-of-turn nudges (E-133, E-143, E-144, E-145). Each refusal gives the next action; questions are exempt | Mingbird finish gate |
| 2.4 | **Anti-loop ladder**: 3 failures of a tool -> change strategy; 5 calls in a row -> nudge; 8 with 4 identical -> disable; repeated reads blocked; 4 edits of one file without progress -> "find the root cause" | Mingbird; our RepeatGuard |
| 2.5 | **Evidence report** at the end of every change: what changed (path:line), what ran and its result, what is not checked; built from the Stage 1 records | CTXGAP, false-success studies |
| 2.6 | The plan is re-shown after compaction; the gate checks every plan step | Mingbird |

**Done when:** a multi-step feature on a demo project is built from a spec and passes its checks, unattended.

## Stage 3 · Specs as the benchmark
Specs on the demo projects (neon_chomp, Trip_splitter, brick-breaker) plus the 13 skill tasks, each with acceptance
checks. Scored from the Stage 1 logs on the process (milestones: started, ran, checked) and the result (hidden checks),
held-out split, 3 repeats, qwen3.5:9b. One number per run; first run = the baseline. Then: fix the top failure in code,
with its test, and rerun (the E-142..E-147 method).

**Done when:** the score is stable over 3 repeats, at or above an agreed bar (proposed 0.7), and false "done" is near 0.

## Stage 4 · Skills and existing MCP servers, by trigger
| Step | What |
|---|---|
| 4.1 | Remove `mcp_find` / `mcp_call` (121 tokens every call, never used). A server's 2-4 relevant tools appear as normal tools only when a trigger or the spec calls for them; every MCP call is logged like our own tools (Stage 1) |
| 4.2 | Measure the servers already set up, one at a time: GitHub, Context7, Semgrep (check it runs on Windows), git (keep only if better than `run_command git`) |
| 4.3 | Playwright (Microsoft's official server) for web apps: 3-4 tools, trimmed snapshots |
| 4.4 | Skills, one at a time, only where the benchmark shows a knowledge gap (writing-tests: 4/6 -> 6/6; next the xlsx ladder) |

**Done when:** each kept skill or server raises the score; the rest are off.

## Stage 5 · Learns by itself and proves it
See "How self-improvement fits" below. Steps: mistake tags and the replay set from real failures (I-32, I-35);
CodeMitra's learning round (D-082) proposing changes that the benchmark judges; best-of-N on Kaggle with tests as the
judge; the dashboard; later a rejection-sampling LoRA on the 4B.

**Done when:** the held-out score rises from CodeMitra's own learning, beyond the noise, and drops when the learning is
removed.

## Tools and MCP servers: what is built in, what comes from servers
**The rule:** a tool is built in only if (1) the finish gate or the logs must see it exactly, or (2) the small model
needs a shorter, simpler version than any server gives, or (3) no maintained official server does it. Everything else
comes from an existing MCP server, shown by trigger, logged, and kept only if it raises the score.

**Built in (keep):**
| Group | Tools |
|---|---|
| Read the project | `list_files`, `read_file` (outline for big files), `search`, `package_info` |
| Change the project | `write_file`, `edit_file`, `append_file`, `make_dir` |
| Check the work | `check_code`, `run_tests`, `run_command`; `finish` comes into the chat as the gate (2.3) |
| Look things up | `web_search`, `fetch_url` (official web-search servers need an API key) |
| Plans and skills | `run_plan`, `use_skill`, the 4 phase tools |
| To remove | `mcp_find`, `mcp_call` (4.1) |

**MCP servers already set up (`app/mcp.py`):**
| Server | Now | Plan |
|---|---|---|
| GitHub (official) | on, read-only | measure (4.2): issues, PRs, CI runs |
| Context7 (official) | on | measure (4.2): current library docs |
| Semgrep (official) | on | check on Windows, then measure (4.2) |
| git (official reference) | on, read-only | measure against `run_command git`; drop if no gain |
| filesystem, fetch (official reference) | off | stay off: they duplicate our tools (D-049) |
| Serena (community) | off | later, for bigger codebases |
| aws-docs | off | stays off |

**New:** Playwright only (4.3).

## What to expect when the plan is done
**You can expect:**
- It acts on a request, runs what it wrote, checks the result, and says plainly what it did not check. False "done"
  is blocked by the finish gate, not by hope.
- Small and medium projects (games, Streamlit apps, scripts, APIs, data files) on your 8 GB laptop, heavy work on
  Kaggle; a multi-step feature from a spec, task by task, while you do other things.
- Logs that answer what happened on any task, and why.
- Skills and MCP tools that each earned their place by a number.
- A score you can trust (process + result, held out, 3 repeats), and a learning curve that shows whether it improves.

**Do not expect:**
- Frontier-level work on big codebases, or system design it cannot test. A 9B is the limit; the harness makes it
  reliable, not genius.
- Speed like a cloud model on the laptop (8-30 tokens/s); Kaggle helps, within 30 h a week.
- Large self-improvement jumps. The evidence (2026-11-15 reports, Mingbird, our runs) says single-digit to low
  double-digit points from learning, more from the harness.

**What would change the plan:** if after Stage 3 the 9B stays under about 0.5, the model is the limit: test Gemma 4
12B and best-of-N before more scaffolding.

## How self-improvement fits, and how it differs from Mingbird
**Mingbird is improved by its author.** Each of its 18 mechanisms was designed by a person from failure transcripts,
then probed and measured. It is a fixed harness: it does not change itself between releases.

**CodeMitra is meant to run that loop itself.** The same cycle Mingbird's author ran by hand (a failure -> a cause -> a
mechanism or lesson -> a measured check) becomes CodeMitra's job, fed by your sessions and your friends':

```
real session -> task record (verified label, mistake tag) -> replay case
        -> CodeMitra proposes one change -> the benchmark + replay set judge it -> keep or retire
        -> stuck? a coach writes guidance only (D-082) -> CodeMitra proposes again
```

**What it can change by itself, ordered by what the evidence says works for small models:**
| Level | What changes | Evidence |
|---|---|---|
| 1. Selection | best-of-N: several tries, tests pick the winner | strongest for small models (2026-11-15 report: 7B beating 32B) |
| 2. Examples | its own verified successful runs, retrieved for similar tasks | short, verified, pruned memory helps an 8B (ReMe) |
| 3. Knowledge | lessons and skill text where it lacked know-how | worked for writing-tests; failed for habits (verify skill) |
| 4. Guards | thresholds and triggers of the finish gate and ladder, tuned on the replay set | Mingbird's mechanisms are where the score moves |
| 5. Weights | rejection-sampling LoRA on the 4B from verified passes | fits a Kaggle T4; single-digit gains reported |

**What it should not do by itself:** rewrite its own core code (proposals only, your OK); learn "habits" from prompts
(they do not stick on a 4-9B); grade itself with a model judge (near chance).

**Why it comes last:** learning needs verified outcomes. Today 413 of about 490 real turns end as "answered" with
nothing verified, and the score cannot yet see a few points of gain. Stages 1-4 make the outcomes verifiable and the
score trustworthy; only then can a learning gain be told apart from noise. Until then the honest line is the one in
§15: measured gain from learning, none yet.

**The difference, in one line:** Mingbird shows a hand-built harness can make a small model reliable; CodeMitra aims to
be that reliable and then to keep getting better on your own projects without you hand-building each fix.

## Parked (not dropped)
**MongoDB, for now (2026-11-18):** the MongoDB MCP server, the MongoDB upload API on Vercel for friends' logs, and the
dashboard update that reads from it. Friends' logs keep using the current way until this is picked up again.
Also parked: the rest of BUILD_V09 v0.9.1 logging beyond Stage 1 · SPEC_DRIVEN S3-S6 (after Stage 2) · MCP servers
beyond Playwright · I-31 exam and I-33 usage report (Stage 5) · model change (only if Stage 3 says so).
