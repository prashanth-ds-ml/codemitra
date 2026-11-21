# Case study: CodeMitra

One page for outside readers (recruiters, clients, engineers). Written at M4 (v1.0); updated only when results change
materially. Details live in [PROGRESS_LOG.md](PROGRESS_LOG.md) and [EVALS.md](EVALS.md).

## Problem
(Coding agents are built for frontier models; on a small local model they break. Evidence from M0.)

## Approach
(Harness built for small models; test-gated escalation; cost meter.)

## Results
(Headline numbers from EVALS.md.)

## What did not work
(Honest list.)

## Lessons
(Top 3-5 from LESSONS.md that other engineers can use.)

## What's next
(Phase 2 items chosen by impact.)

## Sprint log

### 2026-11-12 to 11-14 · from a yes-loop to a one-command friends release (v0.8.0, v0.8.1)
- **Trigger:** the user pasted a game PRD; CodeMitra answered "Should I create all the initial files now?" and the
  user said yes six times: the same question, word for word (E-125). The next 22-turn session found six trust
  faults (E-126): "fix it" stuck in a read-only phase (5 turns of "apply it manually"), another project's tests
  reporting green, false "fixed" / "running successfully", drift to the wrong project, a 524 reported as "Kaggle
  ended".
- **What worked:** reading the user's real records turn by turn; tests built from the real turns (44 for E-126);
  replaying the real conversation, which reproduced the bug where a clean test case could not (old logic started work
  1 of 3 times); replaying the new claim check over the 22 live answers (12 caught).
- **What did not:** E-125's first fix passed 7 tests and never fired live: real answers end in **bold** questions
  and add a line after them (L-049). A blanket rename rule missed `Mitra` after `
`; heredoc and sed edits mangled
  backslashes again (use Edit). A stale `~/.codemitra` from July nearly replaced the real 322 MB home in the
  rename (caught, moved aside).
- **Built:** feedback on every turn from the next message + one key (D-079: 11 unhappy + 13 happy labelled on 169
  old turns with no action); the rename back to CodeMitra (D-080, folders moved with nothing lost); shared sessions,
  light and scrubbed, to a private logs repo (D-081: 0 leaks on all 27 real sessions); one-command setup (D-083,
  end-to-end on a fresh Windows clone).
- **Direction set by the user (D-082):** CodeMitra must learn by itself first; a frontier coach comes in only when it
  is measurably stuck, and then only guides.

### 2026-11-18 to 11-21 · Stage 1 and 2: logs, specs, one finish gate, an honest unattended build
- **Trigger:** the user asked for "proper spec driven development" and traces that answer every question.
- **What worked:** a live check after every step, on the 9B, with the failure traced to its cause in the records
  before any fix; each run found one CodeMitra gap and the next run showed whether its fix held (4 runs for the done
  line). Mingbird's finish gate and loop ladder ported with credit.
- **What did not:** run 2 met every criterion and still broke an existing function the task only had to call; the
  checks and gates were all green. Only reading the diff found it (L-062). My first scope rule would have let that
  exact case through (the task text named the function); the live case became the test.
- **Built:** `codemitra trace`, specs with fail-first criteria, one finish gate (now with `outside_task`), the loop
  guard, the evidence report, `codemitra status`.
