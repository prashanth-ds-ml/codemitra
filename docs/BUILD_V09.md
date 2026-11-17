# v0.9 build plan: skills, MCP, logging for learning, dashboard, friends' logs · PLAN, waiting for your go

**Your words (2026-11-17):** "adding new skills and MCP servers and things in logging and tracing that help with self
improving codemitra from the artifact and complete all those", "update the codemitra dashboard as well", "use mongodb
to store logs directly from friends and run this server on hugging face spaces or vercel". Choices made: **Vercel**,
MCP servers **Playwright, MongoDB, GitHub, Context7**, your existing **MongoDB Atlas** cluster (you put its connection
string into Vercel's settings; it never goes into the repo or a chat).

Written in the spec format of [SPEC_DRIVEN.md](SPEC_DRIVEN.md): each feature has acceptance criteria (AC) with how
they are checked. Four releases, each usable on its own; each one: tests that fail without it, the full suite, CI
green, live checks, then the release on your OK. Not in this batch: SPEC_DRIVEN S0-S6 (I-37); S0 (1 day) could go
first if you want it.

## v0.9.0 · Skills and MCP servers (~3-4 days: batch 1 skills with practice tasks; batch 2 after)

**What exists (checked 2026-11-17):** 23 skills in the repo's `skills/`, found only when the open project has its
own `skills/` folder, so in a user's project there are none; the skill index in the system prompt is cut at 800
characters and ends in "… N more"; no skill makes Excel, PDF or Word files. MCP: GitHub (remote, `gh auth token`) and
Context7 are already in the built-in list (`app/mcp.py`); Playwright and MongoDB are not; none was checked live as a
set.

| Feature | Acceptance criteria (check) |
|---|---|
**Decision (2026-11-17, deep dive):** the 23 skills imported from local-codex on 2026-10-24 are discarded. They were
never changed, never used (0 `use_skill` calls in all real logs), never reached a user's project, and are principles a
small model cannot act on ("make the smallest coherent change"), repeating CodeMitra's own phase notes; four were
duplicate pairs. Git history keeps them. New skills start clean, under the rules in F-0.

| Feature | Acceptance criteria (check) |
|---|---|
| **F-0 What a built-in skill must be** | AC-1 under ~2,500 characters, one clear trigger, exact commands, one small worked example, the pitfalls we have actually hit, and a last step that **checks the result with a command** · AC-2 it ships only if its practice tasks (2-3 each, hidden checks) pass more often **with** it than without it, on qwen3.5 4B and 9B; results in EVALS.md whatever they show · AC-3 a skill that stops helping is dropped (same rule as harness lessons) |
| **F-1 Clean start, built-in skills in every project** | AC-1 the repo's `skills/` (23 old skills) removed; `tests/test_skills.py`'s karapathy test replaced · AC-2 new skills ship inside the package (`app/builtin_skills/`, so clones and wheels both have them) and are found in any folder (unit test with an empty project) · AC-3 order: project skill (`skills/`, `.codemitra/skills`) > yours (`~/.codemitra/skills`) > built-in; the same name wins in that order (unit) · AC-4 `/skills` shows each skill, where it comes from, and whether it is active for this project (driven chat test) |
| **F-2 CodeMitra picks the skill itself** | AC-1 **by project type**: at session start, rules (no model call) read the project's files and dependencies and turn on the matching skills, e.g. `pygame` → python-game, `streamlit` → streamlit-app, `fastapi` → fastapi-service, `pymongo` → mongodb-data, `.html` with no `package.json` → web-page, `.sql` / sqlite → sql-query (unit test per signal with a temp project) · AC-2 **by request**: "make an excel sheet", "export as pdf", "write a word document", "write a long doc" → the file or writing skill for that turn (unit) · AC-3 the system prompt lists only the 1-4 skills active for this project and stays **fixed** for the session (it is Ollama's cached prefix); a request match is a note for that turn, not a prompt change · AC-4 `codemitra.toml` `skills = [...]` pins or turns off skills for a project; `/skill <name>` uses one now · AC-5 every use is recorded (which skill, for which task: feeds F-10 and the with / without comparison) · AC-6 prompt budget test still passes |
| **F-3 Batch 1 skills (v0.9.0)** | **Files:** `xlsx` (openpyxl), `pdf` (reportlab, read back with pypdf), `docx` (python-docx): the last step opens the file and checks it (sheet names and cells; page count and text; headings) · **Project types:** `python-game` (pygame structure and loop, headless tests with `SDL_VIDEODRIVER=dummy`, testing key handling: the Neon Chomp / pause-key failures), `streamlit-app` (layout, `st.session_state`, run headless, test with Streamlit's `AppTest`: Trip Splitter) · **Any project:** `long-document` (outline first, ~60-line parts with `append_file`, check headings at the end: E-141). Each passes F-0 |
| **F-3b Batch 2 skills (after v0.9.0)** | **Project types:** `web-page` (static HTML / CSS / JS, serve locally, check with the Playwright server: issue #11), `fastapi-service` (routes + Pydantic, `TestClient`, uvicorn smoke check), `mongodb-data` (connection from `.env`, `mongomock` in tests, indexes), `sql-query` (query in a `.sql` file, tested with `sqlite3`) · **Any project:** `debugging` (reproduce with a failing test, read the last traceback line, one fix, rerun), `writing-tests` (pytest layout and naming, run one test, red then green), `code-review` (a concrete checklist, findings as path:line), `python-setup` (venv in the project, install with the project's Python, requirements, README run steps: issues #10, #11, E-128) · Later candidates: react-app, cli-tool, docker, pptx, charts, spec-writer (with I-37). Each passes F-0 |
| **F-4 Four MCP servers, one command each** | AC-1 `codemitra mcp add playwright` and `mongodb` added to the built-in list, off until you turn them on (`/mcp on playwright`), versions pinned · AC-2 MongoDB starts **read-only** by default, asks for its connection string and keeps it in this machine's config, never in the project · AC-3 GitHub and Context7: live check that they start and answer · AC-4 no `npx` / Node on the machine: one plain line saying how to install it (unit) · AC-5 every tool still asks before it runs except the read-only ones listed (existing rule, unit) · AC-6 live check: each of the four starts on this laptop and one tool call works |

## v0.9.1 · Logging and tracing for self-improvement (~3 days)

From the artifact and §15 Phase 1. The feature / task / criterion IDs of I-37 get a reserved field now, filled when
specs exist.

| Feature | Acceptance criteria (check) |
|---|---|
| **F-5 Task records** | AC-1 turns join into tasks by rules (I-32): a follow-up on the same files or thread joins; `/new`, another project, `/done`, `/bad`, 24 h idle and session end close one; `/task new` / `/task same` corrects it · AC-2 one `task` row per task: id, kind (fix / feature / new project / question / setup / writing), project, turns, label ✓ verified / ✗ failed / ? unverified with the evidence that decided it, code and harness version, laptop or Kaggle · AC-3 built from your real session logs (mitra-try, 11-13 to 11-17) in unit tests: the tasks and labels a person would give (we check a sample together) |
| **F-6 Tokens and a time split per task** | AC-1 tokens in / out per task and per call · AC-2 time: model (load, prompt, writing), tools (tests, commands: tool rows get their seconds), **your time** (from an answer to your next message) and wall time, kept apart · AC-3 a unit test from a recorded turn adds up |
| **F-7 Snapshot at the start of a task** | AC-1 git commit + "uncommitted changes" flag, else a hash of the files the task touches · AC-2 enough to rebuild the state for a replay case (unit with a temp git repo) |
| **F-8 Your edits after the session** | AC-1 at the next start in that project, files CodeMitra left are compared and a `user_edit` row says which task they belong to, with added / removed counts (the diff stays on this machine) · AC-2 today's in-session check keeps working |
| **F-9 Mistake tags (rules, no model call)** | AC-1 at the end of a task: `claimed_done_without_running`, `tests_failing_at_end`, `wrong_project`, `looped`, `stalled`, `edit_refused`, `unverified_claim`, `undone_by_user`, `user_rephrased` · AC-2 each tag has a unit test from a real logged turn (E-125, E-126, E-141 give several) |
| **F-10 Lessons used** | AC-1 each task records which harness rules were in its prompt (by a stable id per rule, not only the harness version) |
| **F-11 Machine info** | AC-1 the session row: OS, CPU, RAM total / free, GPU and VRAM, Ollama version, laptop or Kaggle |
| **F-12 The shared light copy carries all of it** | AC-1 task rows, tokens, the time split, machine, tags and lessons used go into `codemitra share`'s light copy; texts still scrubbed, still no code (unit: the scrub test on 27 real sessions stays at 0 leaks) |

## v0.9.2 · Dashboard (~1 day)

| Feature | Acceptance criteria (check) |
|---|---|
| **F-13 New sections first, old ones kept** | AC-1 **Tasks**: verified / failed / unverified, by kind and by version · AC-2 **Cost per verified task**: tokens, model / tools / your time, by machine (laptop and Kaggle never mixed) · AC-3 **Top mistakes**: tag counts by version, and "same mistake twice" (a tag that comes back after a lesson for it was kept) · AC-4 **You and friends**: the same numbers per person and machine, from pulled sessions · AC-5 numbers match a separate count script on the real store (test) · AC-6 readable in light and dark, works offline (one HTML file, as today) |

## v0.9.3 · Friends' logs → MongoDB through Vercel (~2 days)

| Feature | Acceptance criteria (check) |
|---|---|
| **F-14 Upload API on Vercel** (`server/logs-api/`, Python) | AC-1 `POST /v1/sessions` with a friend's key: checks the light format, size limit (2 MB), and refuses a session with an absolute path, a key-like string or an email (scrubbed again on the server) · AC-2 `GET /v1/sessions?since=` with the admin key only (for your pull) · AC-3 `DELETE /v1/me`: a friend deletes all of theirs · AC-4 friend keys stored hashed, each can be revoked; the admin key and `MONGODB_URI` only in Vercel's environment · AC-5 simple rate limit per key · AC-6 401 for a wrong key, 413 too big, 422 bad format (tests against a local run with a test database) |
| **F-15 Keys from the CLI** | AC-1 `codemitra share --keys new <friend>` prints the key once; `--keys list`, `--keys revoke <friend>` · AC-2 the admin key lives in `~/.codemitra`, never in a project |
| **F-16 Friends share to it** | AC-1 `codemitra share --setup` takes the server address and the key; `--push` keeps the preview and the yes · AC-2 at exit: "3 sessions not shared · `codemitra share --push`" · AC-3 `codemitra share --delete` · AC-4 the git repo stays as a fallback |
| **F-17 You pull from it** | AC-1 `codemitra share --pull` brings new sessions into the local store in the same layout as today, so the learning round and the dashboard use them unchanged |
| **F-18 Live end to end** | AC-1 deployed on Vercel; a test key pushes a scrubbed session; it is in Atlas; pull brings it back; the dashboard shows it under "friend-test"; delete removes it; a wrong key gets 401 · AC-2 SHARING.md updated (what is stored, where, who can read it, how to delete) |

**What you do for v0.9.3 (once):** `vercel login` (I give the command); in Vercel's project settings add `MONGODB_URI`
(a database user that can only reach the `codemitra_logs` database) and `ADMIN_KEY`; in Atlas → Network Access allow
Vercel (Vercel's addresses change, so this is usually "allow from anywhere", protected by the database user's
password; say if you prefer otherwise).

## Order, size, open choices
v0.9.0 → v0.9.1 → v0.9.2 → v0.9.3, about 9-10 working days (batch 2 skills alongside), each released when its checks pass. To confirm before
starting: (1) built-in skills: decided 2026-11-17 (F-0 to F-3b); (2) MongoDB MCP read-only by default; (3) Atlas network access as
above; (4) whether SPEC_DRIVEN S0 goes first.
