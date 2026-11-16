# Changelog

All notable changes, newest first. Versions follow the milestones in [docs/PLAN.md](docs/PLAN.md).

## [Unreleased]

## [0.8.7] - 2026-11-16 · Kaggle: which account, and does it have internet
- **No internet on Kaggle is found in seconds and named (E-137, issue #13):** the notebook checks its internet before
  installing anything; without it the run ends at once with "Kaggle account <name>: its notebooks get no internet ...
  verify your phone" (Kaggle gives notebooks internet only after the phone is verified, but shows the GPU hours
  before). CodeMitra also reads back the settings Kaggle saved for the notebook and says so straight away if
  internet is off.
- **CodeMitra says which Kaggle account it uses:** `kaggle start`, `kaggle status` and `kaggle setup` show
  `Kaggle account: <name> (key: <where the key is>)` and whether that account's notebooks have internet. A key for
  a different account than the one set up (an old token, environment variables) stops the start and says how to
  switch on purpose (`codemitra kaggle setup`).

## [0.8.6] - 2026-11-16 · Kaggle start that cannot get stuck, skills and MCP servers
- **Kaggle start no longer looks stuck or burns your hours (E-136, issue #13):** "installing Ollama" is a 1.5 GB
  download; CodeMitra now says so and shows `still installing Ollama · 3 min` every minute. The download has a time
  limit and is tried twice; if it fails, the run ends and tells you why. A notebook that is not ready 45 minutes after
  it starts stops itself, so a stuck run can no longer use your GPU hours until Kaggle's 11.5 h limit.
- **A long Kaggle queue no longer wastes a run (E-135):** `kaggle start` waits up to 2 hours in Kaggle's queue
  (no hours used) and then 20 minutes from when it runs; `kaggle status` says how to connect to a run nobody follows.
- **Add skills and MCP servers (E-134):** `codemitra skills add <folder or git URL>` / `remove` / `import claude`;
  `codemitra mcp add <name> -- <command>` or `--url <address>` / `remove` / `import cursor|vscode`. Skills in
  `~/.codemitra/skills` work in every project. A new server starts once to show it works, and every tool of it asks
  you first.
- **Skills cost less and are opened on demand:** the instructions carry a short list (about 230 tokens, was about
  1,440 with the 23 skills in this repo, over the 3K budget); the model opens one with the new `use_skill` tool.
  The list no longer claims that skills run by themselves or skip approval (that was never built).
- **A promise is not an answer (E-133):** "I'll create `query.sql` now" with nothing done is sent back once with
  "do it now"; tool calls in Qwen's XML form, or written only in the thinking, are run; old thinking is not sent back.
- **Shorter test output:** a long failing run shows the first failure's end and the FAILED lines, not every line.
- **`codemitra practice --repeats 3`:** pass^3, the tasks that flip, a margin, and a task-by-task comparison with
  the last run.
- **Rules earn their keep:** each kept rule counts how often its own cases pass again; a rule that keeps failing
  them is retired (`codemitra harness` shows the counts).
- **`scripts/coder_parser_tag.py`:** a qwen3.5 tag with Ollama's qwen3-coder parser, to compare (ollama#14493);
  Kaggle makes it too.

## [0.8.5] - 2026-11-15 · codemitra improve works on a friend's machine
- **`codemitra improve` (E-132, issue #12):** errors that come from your machine (a refused program, a missing
  package or interpreter, no network) are named as such and never get a rule like "retry 3 times"; the
  benchmark has its own Python with what it needs (made once with uv, about a minute), so grading works on any
  machine.

## [0.8.4] - 2026-11-15 · every must-have built (D-077)
- **Review fixes (E-130):** labels per session; scoring never reads outside its folder; `package_info` never
  runs the project's code; a yes to read outside covers one folder, not the folders below it.
- **Whole-code review fixes (E-131):** `pip install -r requirements.txt` is no longer refused as inline code;
  `npm` / `npx` work on Windows; long installs get 15 minutes and a cut-off one is not reported as running;
  `ls -la` / `dir /b` work; a failed `git commit` in `share --push` is an error, not "shared"; `.env` and key
  files are never read or searched; a bare `pytest` uses the project's Python; `kaggle setup` picks up a newly
  downloaded key; scoring runs commands with the chat's own rules.
- **The prompt stays small (E-106):** the default chat is now measured too; learned rules are capped at 4 and
  learned tool texts at 1 (the newest are kept, and a drop is said), so the worst case fits the 3K budget.
- **Reads outside the project (must-have 12):** give a full path and CodeMitra asks first, then reads it
  (read-only; once per folder per session). Secret files (.env, keys, ~/.ssh, ~/.kaggle) are never read.
- **Knows its machine (must-have 11):** it knows which Python the project uses, which programs it may run and what
  to do when one is refused; `package_info` checks the installed version of a library before using it.
- **Whole-web search on Kaggle (must-have 10):** the Kaggle notebook now runs SearXNG, so web search finds news,
  blogs and docs while Kaggle is up; on the laptop alone it uses its own sources as before.
- **How each answer went (must-have 9):** at exit, one model call reads your next messages for the answers the
  simple rules could not judge ("none" when unsure).
- **Never waits forever (E-081, must-have 13):** if the model sends nothing for 5 minutes, CodeMitra stops the
  turn and says why and what to do (`/free`, or restart Ollama). Before, a stuck Ollama or tunnel hung the chat.
- **Offline is not "Kaggle ended":** with no internet on your machine, the turn runs on the laptop and Kaggle keeps
  running; it is used again when you are back online. The status line says offline.
- **A fair keep/drop gate (must-have 7):** `codemitra improve --chat` judges at temperature 0, runs every case whose
  result changed 3 times on both the current and the proposed rules, and keeps a rule only if a case it was proposed
  for passes in most runs and nothing that passed fails in every run, your held-out /bad cases included. One lucky or
  unlucky run no longer decides.
- **Threads add, never overwrite (must-have 8):** continuing a discussion keeps its earlier versions in the same file
  (`## Earlier`); a decision stays until a new one replaces it, and earlier decisions come back with the thread.

## [0.8.3] - 2026-11-14 · codemitra update, installs in the project's Python
- **Updates reach you (D-084):** when a new release is out, the chat says so in one line at start (it asks GitHub at
  most once a day, 2 seconds at most, silent offline; nothing about you is sent). `codemitra update` pulls it into
  your `codemitra` folder and shows what changed; the next `codemitra` runs it. It never overwrites files you changed
  there, and says when the install must run again. `codemitra update --check never` turns the check off.
- **Installs land where they are used (E-128, issue #11):** `pip install`, `python -m pip` and `playwright` now run in
  the project's Python; a project with no usable Python gets its own `.venv` (made with uv, with pytest) on the first
  install. `node`, `npx` and `playwright` are allowed by default. A refused command is not retried in other forms:
  CodeMitra tells you the exact `! <command>` to run it yourself.
- A Kaggle key saved during a run is used (E-129).

## [0.8.2] - 2026-11-14 · setup finds a fresh Ollama
- **Setup on a fresh Windows machine (E-127, issue #10):** after winget installs Ollama, the terminal that runs the
  setup does not see the new PATH, so the model download failed, and a second run tried to install Ollama again and
  opened the download page. The setup now finds Ollama in its install folder and uses it from there for the rest of
  the run; it never installs an Ollama that is already on disk, and it tells you to open a new terminal so `ollama`
  works there too.
- In the chat, `/codemitra <command>` fills in the chat's own `/<command>`; the tip line shows `+ / - rate an answer`.
- A Kaggle session's length ends at its last turn and long ones read in hours (it showed "1258 min" after the rename).

## [0.8.1] - 2026-11-14 · one-command setup, share your sessions
- **One command after cloning (D-083):** `setup.ps1` (Windows) / `setup.sh` (macOS, Linux) installs uv and CodeMitra,
  then `codemitra setup` does the rest, asking before each step: Ollama (winget / Homebrew / the official script) and
  its memory saver, the model that fits your machine (4B or 9B, read from your GPU and RAM; a model you chose is
  kept), the free Kaggle GPU (it opens the page, says what to click, takes the token, checks hours and phone), your
  name for mails, sharing. Run it again any time: it only does what is missing.
- **Clean README and guides:** the README is clone + one command + first steps; details in `docs/guide/` (SETUP,
  USING, KAGGLE, SHARING) with a troubleshooting table.
- **`codemitra share` (D-081):** share a session so CodeMitra learns from everyone's. `--setup` once (your name,
  the private logs repo `prashanth-ds-ml/codemitra-logs`, ask at exit: ask / always / never); `--push` shows a preview
  and pushes the light, scrubbed copy (messages, answers, which tools ran and failed, test summaries, labels; never
  file contents, tool outputs, code, notes or paths; tokens, emails, user name and home folder replaced) with your own
  git login. Without GitHub it writes the file to `~/.codemitra/share/out/`. The maintainer's `--pull` brings
  everyone's sessions into the store, where CodeMitra's own learning round reads them (`coach --shared` too).

## [0.8.0] - 2026-11-14 · CodeMitra (renamed from Mitra), trust fixes, feedback on every turn
- **Mitra is now CodeMitra (D-080).** The command is `codemitra`; `~/.mitra`, `~/.config/mitra`, each project's
  `.mitra/`, `mitra.toml` and `MITRA.md` move to the new names once, on the first `codemitra` run, with nothing lost
  (a folder Windows keeps open is moved on a later run; old `MITRA_*` env names still work). Upgrading: see the
  README. The GitHub repo is now `prashanth-ds-ml/codemitra` (the old link redirects).
- **Feedback on every turn, no extra work (D-079):** your next message is read as the verdict on the last answer
  ("why don't you…", "did you do that?", a pasted error → went wrong; "thanks", "works", a yes to its offer → went
  right); `+` / `-` on the empty prompt rates with one key; a rare "worked?" line after changes; a 1-5 key at exit.
  These feed `codemitra improve` and the coach.
- **A yes starts the work (E-125, E-126):** after CodeMitra offers ("**Should I start building now?**") a short yes
  starts it at once, without another "should I?"; a repeated answer is not accepted; a pasted spec or PRD is planned.
- **Change requests stay changes (E-126):** "fix it" that begins by reading a file now gets the tools to change it
  (it no longer says "I can't edit files, apply it manually").
- **The right tests (E-126):** in a folder of several projects, the tests after a change run in the project that
  changed, never another project's.
- **Honest answers (E-126):** "fixed" when nothing changed, or "running successfully" while tests fail, is caught;
  the next answer corrects it. CodeMitra stays on the project you are working on.
- **Kaggle (E-126):** one model call over 120 s (Cloudflare 524) is retried in smaller steps instead of ending the
  Kaggle session.

**Also in 0.8.0 (built since 0.7.0):**
- **`codemitra practice` (D-078 step 5):** `codemitra practice --download` builds 100 Python (MBPP+, HumanEval+) and 50
  SQL (Spider) tasks in ~/.codemitra/practice once (works offline after that); `codemitra practice --n 20 [--kind sql]
  [--split held_out] [--remote]` lets CodeMitra solve each in a fresh folder with its own tests, and a hidden check
  decides. The report counts "misread" tasks (its own tests passed, the hidden check failed). Results in
  results/practice.jsonl (task ids and outcomes only).
- **Your /bad becomes a test case (D-078 step 6):** `codemitra cases` drafts a score case from each new /bad (the coach
  writes it when Claude Code is there, otherwise a template from your note); `codemitra cases review` keeps, edits or
  drops each one. Kept cases form the private "real" category of `codemitra score` (~/.codemitra/score/real.toml, never in
  the repo), held out: `codemitra improve` never learns from them. Fixed: improve and the coach matched a /bad to the
  wrong turn when a day had several sessions (E-120).
- **Phase 1 of D-078 (trust):** after every code change the project's tests run by themselves; on a failure CodeMitra
  gets the failing output and up to 3 rounds to fix it, then stops and says honestly what still fails (a project
  without tests is called untested). A "done" / "fixed" after a change without a passing run gets the ⚠ Unverified
  line. `write_file` refuses to shrink a file of 20+ lines to under half (use `edit_file`). A "deep dive" now
  searches at least 3 times and opens 4-5 pages; CodeMitra no longer opens with "You're absolutely right" and says what
  it cannot do yet. Switches in `harness.toml`: `auto_test_rounds`, `deep_min_searches`, `deep_min_pages` (1 = off).
- **No claim without proof (D-077 #1, E-109, E-110):** a search CodeMitra asks for while deciding now really runs (it
  was dropped, and the model was told "ok"); an answer that says "confirmed", "verified", "I found" or "tests pass"
  without a tool result in the same turn to back it gets a ⚠ Unverified line, a record row, and a flag in the coach's
  digest. Offline, web search and fetch say "Offline: nothing was searched" at once instead of timing out.
- **Four conversation misses fixed (E-101):** small talk no longer brings up the project; "I am thinking" gets a
  question back; ideas about the project's code read the code first (3-5 options tied to file:line); continuing an
  earlier conversation stays on that topic; summaries keep names, numbers and dates as written.
- **Formatted answers, your messages in amber (D-076):** CodeMitra formats every answer (bold, code, steps, tables, short headings); mails stay plain. What you type is amber, so your side of the conversation stands out; code blocks use Phosphor colours.
- **Self-improvement in two layers (D-075):** CodeMitra runs one learning round by itself in the background when you leave with 3+ new signals (/bad, "I said …", rephrasing) and shows what it learned at the next start, with the undo; `codemitra coach` has Claude review your recorded conversations and queues its suggested rules for that round, where `codemitra score` decides. The header reminds you when a review is due.
- **A quiet start after Kaggle ended (E-107):** one line ("Kaggle ended while CodeMitra was closed · last session 111 min, 30 turns, no files changed · report in .codemitra/reports/") instead of the whole last session; a report during a session shows the last 8 turns, one fact per line. Kaggle starts when you ask for work, never for a hello.
- **Talk on the laptop, work on Kaggle (D-074):** while Kaggle is up, plain conversation is answered by the laptop model (kept loaded); reading code, web look-ups, changes and plans run on Kaggle. A conversation too long for the laptop's context stays on Kaggle whole, never cut.
- **From your live session (E-102..E-105):** asking CodeMitra to find or pull information now searches the web (a new look-up phase); CodeMitra knows what it is and what it can already do; "I said ... why aren't you following" counts as a correction for `codemitra improve --chat`; reports written at start-up no longer claim a failed summary. `codemitra score` behaviour set: 14 cases (look-up, knows itself, already has it, your pick then mine).
- **`codemitra improve --chat` (D-073):** CodeMitra learns one conversation rule from the failed `codemitra score` cases and
  your `/bad` / rephrase / interrupt / undo signals, scores the quick set with and without it, and keeps it only if
  it passes at least 2 more cases with no category lower. `--rounds N`, `--dry-run`; undo with `codemitra harness revert`.

## [0.7.0] - 2026-11-11 · One CodeMitra (D-071) + qwen3.5 as the model (D-072)
- **qwen3.5:latest is CodeMitra's model** (chat, all roles, Kaggle at 256K); mimo turned conversation into builds.
- **One conversational loop** behind `architecture = "one"` or `"phased"` in codemitra.toml: the model decides whether
  to talk, look or change (phased: decide first with no file tools, then act in that phase with only its tools).
  The router stays the default until the A/B decides (EVALS).
- **Conversation memory as threads** (~/.codemitra/threads): said / decided / open per discussion, written at exit.
- **Every model call has an output cap (8,192 tokens) and a runaway guard;** an empty answer is asked for once.
- `codemitra score`: a *behaviour* category (10 cases), `--arch router|one|phased`, `--ctx`.

## [0.6.4] - 2026-11-11
- Long answers no longer vanish while they are written: a long list, table or code block scrolls normally.
- While CodeMitra works, a footer under the answer shows the time, the live speed and this machine (CPU, RAM, GPU).

## [0.6.3] - 2026-11-11 · the status line shows this machine
- Right side of the status line: the last answer's speed (tok/s, from Ollama's own timing), CPU, RAM free, GPU
  memory / load / temperature; sampled every 2 s in the background. Orange only when you should act: a much
  slower answer than this machine's best (spilled to the CPU), RAM below 2 GB or below what the model needs, a
  GPU at 85 C or more. A shorter block on narrow terminals, none on very narrow ones.
- The token count left the status line (no cost, no limit on a local model); ctx % stays (D-070).

## [0.6.2] - 2026-11-11
- `codemitra score` (or any `codemitra <command>`) typed in the chat now says to run it in another terminal, instead of being explained as a question.

## [0.6.1] - 2026-11-11 · deep dive: code review of steps 0-3 + debugging on real records
- Follow-ups keep their tools: "still not working", "try again", "no, use pytest" after a fix; "why?" after
  a code question reads the code. "run the tests", "commit the changes", "the tests are failing" work with
  tools; "write a prd" / "rewrite this paragraph" are writing; "rename X" is a small change.
- `/plan` never gets an old discussion; "can you fix X? think it through" fixes it.
- `thinking = "on"|"off"` in codemitra.toml wins again; your notes are no longer sent twice.
- `codemitra report` no longer counts planned or "where did we stop" turns as empty answers.
- Test and dev workspaces never reach your ~/.codemitra store; a timed-out score case stops for real.
- 10 review findings + 3 from debugging: E-083..E-095.

## [0.6.0] - 2026-11-11 · `codemitra score`: the measuring set (D-068 step 3) + fixes from a live session
- `codemitra score` runs the measuring set and keeps one row per run in results/scores.jsonl: sorting (no model),
  writing, explain, ideas/review, small and medium coding tasks (hidden tests). `--quick` skips the coding
  tasks, `--remote` runs on Kaggle, `--validate` checks the set, `--history` shows past scores. First: sorting 46/46 · writing 0/3 · explain 4/4 · ideas 1/2 (15 min, 2026-11-11 01:03).
- Talking an idea through ("can we brainstorm on this", "i feel ...") is answered, not planned; "ok lets build
  it" then plans it with the discussion.
- The planner streams, so the Kaggle tunnel no longer cuts it after 120 s (Cloudflare 524).
- The Kaggle-ended report no longer names an old night run.
- A mail to your manager "for a family function" is writing, not code.

## [0.5.1] - 2026-11-10 · brainstorming and reviews about your code (D-068 step 2b)
- "brainstorm ideas to make the game harder", "review game.py", "pros and cons of …" read the code first
  (explainer); ideas come as 3-5 options with trade-offs, and "go with option 2" builds the one you pick.
- "update the plan with …" / "add a task to plan.md" edit the plan in place instead of planning a feature.

## [0.5.0] - 2026-11-10 · questions about code (D-068 step 2)
- A question about the project ("explain the game logic", "where is the API defined?") gets read-only tools
  (list_files, search, read_file) and 6 steps; the last step has no tools, so there is always an answer, with
  path:line references. A vague one may be answered with up to 2 short questions. Live: 8-22 s on a small project.
- Recorded per question: steps used, budget hit, files read, files cited, line references, asked back.

## [0.4.0] - 2026-11-10 · everyday chat + records for self-improvement (D-068, docs/BUILD_ORDER.md)
- Small talk, writing (mails, messages, summaries, rewrites, translations, "make it shorter" after one) and general
  questions are sorted without a model and answered in one call with no tools and thinking off. Live on mimo-v2.6:9b:
  "hi" 1.0 s, a team mail 3.1 s, first word 0.3-0.5 s.
- `~/.codemitra/me.md` (name, signature, tone, stack; created on the first start) and `.codemitra/notes.md`, read every turn.
- `/copy`: the last answer to the clipboard.
- Thinking off by default; on only for the planner and the debugger.
- Every turn records its kind, path, machine, thinking, notes version and time to the first word; quiet signals
  (asked again, stopped, `/undo`, `/copy`); plan-first and "where did we stop" are counted as turns.

## [0.3.0] - 2026-11-10 · plan first, then small steps (D-065, docs/PLAN_FIRST.md)
- "Where did we stop?" answered from CodeMitra's records (resume brief, also in the prompt), no model call.
- Requests sorted without a model: resume / question / small / big; `/plan <task>`, `/do <task>`.
- Bigger changes: a short runnable plan from a small context pack (file tree + outlines), Go / Change / Save /
  Cancel, steps run one at a time with fresh context and their own test, failed steps re-planned once,
  `.codemitra/resume.md` written.
- Large files read without a range give an outline first.
- Fixed: slash commands were stored as project-memory topics (a model chased `/logs/...` paths); wrong paths
  now suggest the real file; `run_command` states its rules; Python warning blocks folded on screen.

## [0.2.2] - 2026-11-10 · CodeMitra asks before using Kaggle (D-064)
- At every start: one check (key valid, phone verified, hours left) and one of five cases: no key → offer to
  connect; key works but not decided → "Use it? when I need it (default) / start now / later / no"; decided →
  one line or a background start; a problem → one line with the fix; already running → the status line.
- `/kaggle use now|when-needed|never` and `codemitra kaggle use ...`; `/kaggle` shows the setting.
- 'when-needed' starts Kaggle on the first write work without asking again; 'Later' asks again the next day.

## [0.2.1] - 2026-11-10
- Fixed: the memory line suggested closing Windows' own `MemCompression` (E-068).

## [0.2.0] - 2026-11-10 · Kaggle and laptop, seamlessly (D-062, docs/BACKENDS.md)
- Status line shows where the model runs and the Kaggle hours left (`☁ kaggle · … · 28.1 h left` / `💻 laptop`).
- Read work (plan mode, planner, reviewer) on the laptop, write work on Kaggle; switches between turns.
- Kaggle ends (idle, time limit, quota, tunnel): laptop model (quietly smaller if RAM is short), a report of what
  was done in `.codemitra/reports/`, and CodeMitra stops; also when it ended while CodeMitra was closed, and mid-turn.
- A long chat is compacted before moving to the laptop's smaller context.
- Write work with no Kaggle running: start it in the background (asked once per session).
- First start: CodeMitra offers to connect a free Kaggle GPU (guided).

## [0.1.2] - 2026-11-10
- Fixed: after a Kaggle run stopped by itself, `codemitra` said "no compatible local Ollama models"; it now says the Kaggle GPU has stopped and uses this machine (E-067).

## [0.1.1] - 2026-11-10
- `codemitra kaggle setup <token>`: Kaggle's Settings → API now gives a token string (saved to ~/.kaggle/access_token); a downloaded kaggle.json still works (`codemitra kaggle setup` finds it).
- No more 15-line Kaggle library sign-in help printed twice: CodeMitra's own short steps only.
- README Kaggle steps follow the current Kaggle Settings page.

## [0.1.0] - 2026-11-10 · colleague preview
First version for other people to try on their own projects.
- Terminal chat on local models (Ollama): reads code, edits with your approval, runs tests and fixes failures;
  `/undo`, ask / auto-edit / plan modes, role routing (`/role`), live `/model use` and `/context`.
- Unattended plans: `/plan template`, `/plan check`, `/run plan.md <hours>` (background night runs, report).
- `/free`: tick big programs, CodeMitra closes them to make RAM room for the model (D-059).
- Kaggle GPU: `codemitra kaggle setup|start|stop|status` and `/kaggle`, your free weekly hours at 256K context, no browser
  (D-060, D-061); `codemitra remote` for any remote Ollama.
- Local dashboard (`codemitra dashboard`), `/good` `/bad` feedback, everything recorded only in `~/.codemitra/`.
- Deep-dive review fixes E-050..E-066 (see docs/FIX_LOG.md).
- README rewritten for first-time users; feedback and bug issue forms; dependencies pinned to tested versions.

- Project docs: scope, checklist plan, decisions, error/fix/lesson logs, progress log, evals, case study, posts.
- Imported local-codex code (561 tests passing); package renamed to `mitra` (`mitra` and `codemitra` commands).
- CI: tests on Linux and Windows, lint gate for syntax errors and undefined names, gitleaks secret scan.
- Fixed: model-advisor command crashed after finishing (E-004).
- Benchmark v0: fake payments SDK, demo shop service, 10 validated tasks with hidden tests (`bench/bench.py`).
- Bench tooling: logging proxy, preflight, run recorder with completion markers (`bench/proxy.py`, `bench/preflight.py`, `bench/run.py`).
