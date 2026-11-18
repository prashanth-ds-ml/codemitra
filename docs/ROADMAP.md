# CodeMitra roadmap: a proper coding partner on small local models (2026-11-18)

**This is the one plan.** It replaces the "Next up" list in [PLAN.md](PLAN.md) (2026-11-07) and puts the other plans
in order: [SPEC_DRIVEN.md](SPEC_DRIVEN.md) (I-37), [BUILD_V09.md](BUILD_V09.md) (skills, MCP, logging, dashboard,
friends' logs), [SELF_IMPROVEMENT.md](SELF_IMPROVEMENT.md) §14-15. Nothing in them is dropped; each has its stage.
Evidence behind it: `reports/Proper coding partner research 2026-11-18.md`, [MINGBIRD_REFERENCE.md](MINGBIRD_REFERENCE.md),
EVALS.md (2026-11-18 skill runs).

**The goal (unchanged):** a coding assistant and partner for my own projects that runs on local models (8 GB laptop,
Kaggle for heavy work), like Claude Code but built for small models, and that gets better with use.

**The one rule:** a stage starts only when the one before it holds. Every stage ends with a number on the core
benchmark, on **qwen3.5:9b** (the model CodeMitra uses), 3 repeats.

## Stage 1 · A reliable core (about 2 weeks)
A partner that does what you ask, runs and checks its work, and never says "done" when it is not.

| Step | What | From |
|---|---|---|
| 1.1 | **Core benchmark**: 40-60 tasks on the demo projects (neon_chomp, Trip_splitter, brick-breaker) plus the 13 skill tasks: create, edit, add / delete, debug, write tests, make files, multi-file. Scored on the process (milestones: started, ran, checked) and the result (hidden checks), held-out split, 3 repeats, qwen3.5:9b. One number per run; first run = the baseline | Mingbird LRAB; our practice + skill tasks |
| 1.2 | **One finish gate** in place of the scattered end-of-turn nudges (E-133, E-143, E-144, E-145): no work done / tests fail (run by CodeMitra; "can't run tests here" is not a failure) / named files missing / plan files missing / broken JSON / once: re-show the task and check every requirement. Each refusal gives the next action; questions are exempt | Mingbird finish gate |
| 1.3 | **Anti-loop ladder**: 3 failures of a tool -> change strategy; 5 calls in a row -> nudge; 8 with 4 identical -> disable; repeated reads blocked; 4 edits of one file without progress -> "find the root cause" | Mingbird; our RepeatGuard |
| 1.4 | **Evidence report** at the end of every change: what changed (path:line), what ran and its result, what is not checked; built from the turn's records | CTXGAP, false-success studies |
| 1.5 | Fix the top failure the benchmark shows, in code, with its test; rerun | the E-142..E-147 method |

**Delivers:** the core benchmark and its score history; the finish gate; the ladder; evidence reports.
**Done when:** the core benchmark is stable over 3 repeats and at or above an agreed bar (proposed 0.7), and the false
"done" rate on it is near 0.

## Stage 2 · Plans and builds bigger work (about 1 week)
| Step | What |
|---|---|
| 2.1 | I-37 S0: a bigger request in the normal chat goes through the planner (runnable plan, Go / Change / Save) and the step runner (fresh context per task, checks, one re-plan), not one long free-form turn |
| 2.2 | The plan is re-shown after compaction; the finish gate checks every plan step |
| 2.3 | Specs: `specs/` with features, acceptance criteria and their checks, written before code (SPEC_DRIVEN S1-S2) |

**Delivers:** multi-step features built task by task, each task checked. **Done when:** a multi-step feature on a demo
project (e.g. a Neon Chomp level, a Trip_splitter feature) is built from a spec and passes its checks, unattended.

## Stage 3 · Knows more, reaches out (1-2 weeks)
| Step | What |
|---|---|
| 3.1 | Skills, one at a time, only where the benchmark shows a knowledge gap; each kept only if it raises the score (writing-tests already did: 4/6 -> 6/6). Next: the xlsx ladder |
| 3.2 | MCP by task domain: a server's 2-4 relevant tools shown only when the request matches (no always-on `mcp_find`/`mcp_call`, which cost 121 tokens a call and were never used). GitHub and Playwright first, then Context7, MongoDB (local, test database) |

**Delivers:** measured skills and MCP servers. **Done when:** each kept skill or server raises the score; the rest are
off.

## Stage 4 · Learns by itself and proves it (ongoing, from week 4)
See "How self-improvement fits" below. Steps: task records with mistake tags (SELF_IMPROVEMENT §15 Phase 1, I-32);
the replay set from real failures (I-35); CodeMitra's learning round (D-082) proposing changes that the benchmark judges;
best-of-N on Kaggle with tests as the judge; friends' sessions through the MongoDB upload API on Vercel; the dashboard;
later a rejection-sampling LoRA on the 4B.

**Done when:** the held-out score rises from CodeMitra's own learning, beyond the noise, and drops when the learning is
removed.

## What to expect when the plan is done
**You can expect:**
- It acts on a request, runs what it wrote, checks the result, and says plainly what it did not check. False "done"
  is blocked by the finish gate, not by hope.
- Small and medium projects (games, Streamlit apps, scripts, APIs, data files) on your 8 GB laptop, heavy work on
  Kaggle; a multi-step feature from a spec, task by task, while you do other things.
- Skills and MCP tools that each earned their place by a number.
- A score you can trust (process + result, held out, 3 repeats), and a learning curve that shows whether it improves.

**Do not expect:**
- Frontier-level work on big codebases, or system design it cannot test. A 9B is the limit; the harness makes it
  reliable, not genius.
- Speed like a cloud model on the laptop (8-30 tokens/s); Kaggle helps, within 30 h a week.
- Large self-improvement jumps. The evidence (2026-11-15 reports, Mingbird, our runs) says single-digit to low
  double-digit points from learning, more from the harness.

**What would change the plan:** if after Stage 1 the 9B stays under about 0.5, the model is the limit: test Gemma 4
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

**Why Stage 4 comes last:** learning needs verified outcomes. Today 413 of about 490 real turns end as "answered" with
nothing verified, and the score cannot yet see a few points of gain. Stages 1-3 make the outcomes verifiable and the
score trustworthy; only then can a learning gain be told apart from noise. Until then the honest line is the one in
§15: measured gain from learning, none yet.

**The difference, in one line:** Mingbird shows a hand-built harness can make a small model reliable; CodeMitra aims to
be that reliable and then to keep getting better on your own projects without you hand-building each fix.

## Parked until their stage (not dropped)
MongoDB upload API on Vercel and the dashboard update (Stage 4) · the rest of BUILD_V09 v0.9.1 logging (Stage 4) ·
SPEC_DRIVEN S3-S6 (after Stage 2) · new MCP servers beyond GitHub / Playwright (Stage 3) · I-31 exam and I-33 usage
report (Stage 4) · model change (only if Stage 1 says so).
