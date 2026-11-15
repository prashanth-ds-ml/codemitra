# Using CodeMitra

Start it in a project folder: `cd ~/my-project` then `codemitra`. The header shows the model, where it runs (laptop
or Kaggle) and a memory check (**✓** fine; **⚠ / ✗** not enough free memory: see `/free` below).

## Just type
- **Questions about your code:** *"explain the game logic"*, *"where is the API defined?"* are answered read-only,
  with `file:line` references; nothing is changed. So are brainstorms and reviews (*"ideas to make the game
  harder"*); *"go with option 2"* then builds the one you pick.
- **Changes:** *"add a --verbose flag to cli.py, with a test"*, *"the tests in tests/test_api.py fail, fix them"*.
  CodeMitra reads before it edits, runs your tests after every change and fixes what fails (up to 3 rounds, then it
  says honestly what still fails). A project without tests is called untested, never "done".
- **Bigger work** (*"build a snake game with a web page"*, a pasted spec) is planned first: a short plan, then
  *"Should I start?"*; a **yes** starts it. Long builds run in small steps, each checked by a test; `/plan <task>`
  forces a plan, `/do <task>` skips it, `/run plan.md 4` builds a plan unattended for up to 4 hours.
- **Everyday help:** *"draft a mail to the team about …"*, *"make it shorter"*, *"summarise this: …"*, *"translate
  …"*, general questions get one quick answer. Mails use your name and signature from `~/.codemitra/me.md`.
- **"where did we stop?"** is answered at once from CodeMitra's records (last requests, plan progress, git).
- **Web:** *"look up the latest pygame version"* searches and cites what it found (the whole web while Kaggle
  runs; on the laptop Wikipedia, GitHub, arXiv, Hugging Face and the Ollama library).
- **Files outside the project:** *"read C:\notes\api.md"*: CodeMitra asks first, then only reads it (once per
  folder per session). Secret files (.env, keys, ~/.ssh, ~/.kaggle) are never read.

## Modes and keys
| Key | |
|---|---|
| **enter** / **shift+enter** | send / new line |
| **shift+tab** | ask before each change (default) → auto-edit → plan only (reads, changes nothing) |
| **esc** | stop the model (what you typed meanwhile is kept) |
| **+** / **-** | right after an answer, on the empty prompt: it went well / badly (one key, no Enter) |
| **ctrl+o** | show the last folded output in full |
| **ctrl+c** twice | quit (or type `exit`) |

## Commands
| Command | What it does |
|---|---|
| `/help` | all commands and keys |
| `/model use <name>` · `/context 64k\|128k\|auto` | switch model or context size, live |
| `/free` | close programs to make RAM room for the model (you tick which) |
| `/undo` | undo CodeMitra's last changes |
| `/good` · `/bad <why>` | how the last answer was, with a reason |
| `/copy` | the last answer to the clipboard |
| `/kaggle start\|stop\|status` · `/kaggle use now\|when-needed\|never` | the free Kaggle GPU ([guide](KAGGLE.md)) |
| `/plan <task>` · `/do <task>` · `/run plan.md 4` | plan first / skip planning / build a plan unattended |
| `! <command>` | run a shell command yourself |

In the terminal (not inside the chat): `codemitra update` (the newest release), `codemitra setup` (setup again),
`codemitra kaggle start|stop|status`,
`codemitra share --push` ([guide](SHARING.md)), `codemitra dashboard` (a local page with your sessions: what worked,
what failed), `codemitra score` (the measuring set: how good it is today, kept in `results/scores.jsonl`),
`codemitra --help` for everything.

## Skills and MCP servers
A **skill** is a folder with a `SKILL.md`: a playbook (how to review a PR, set up FastAPI, ...) that CodeMitra opens
when your request matches. It is the same format Claude Code uses. A skill is only text: nothing in it is run.

| Command | What it does |
|---|---|
| `codemitra skills` | list them: this project's (`skills/`, `.codemitra/skills/`) and yours (`~/.codemitra/skills/`, every project) |
| `codemitra skills add <folder or git URL> [name]` | add to yours; a repo of skills adds all, or only `name`; `--project` adds to this project, `--replace` updates |
| `codemitra skills remove <name> [--project]` | remove one |
| `codemitra skills import claude` | copy your Claude Code skills (`~/.claude/skills`) |
| `/skills show <name>` | read one in the chat |

CodeMitra's instructions carry only a short list (one line per skill, the whole list about 230 tokens however many you
add); the model opens a skill with `use_skill` when it needs it.

An **MCP server** gives CodeMitra more tools (git, GitHub, docs, a database, ...). git, GitHub, context7 and semgrep
are built in.

| Command | What it does |
|---|---|
| `codemitra mcp add <name> -- <command> [args]` | a server that runs on your machine, e.g. `codemitra mcp add time -- uvx mcp-server-time` |
| `codemitra mcp add <name> --url <https://...> [--header 'Authorization=Bearer ${TOKEN}']` | a server on the web; `--env K=V` for a command's environment |
| `codemitra mcp remove <name>` | remove one you added (`/mcp off <name>` turns a built-in off) |
| `codemitra mcp import [cursor\|vscode]` | copy servers from Claude Code (default), Cursor or VS Code |
| `/mcp` · `/mcp test <name>` · `/mcp tools <name>` | list them, start one, see its tools |

They go into `~/.codemitra/mcp.json` and start once straight away so you see they work. Every tool of a server you
add asks you first until you add `allow` patterns to its entry (for example `"allow": ["get_*", "list_*"]`).
`--project` writes the project's `.codemitra/mcp.json` instead: CodeMitra uses it only after `/mcp trust`, and refuses a
secret typed into it (write `${VAR}` and set VAR in your environment).

## Feedback, without extra work
Your **next message** tells CodeMitra how the last answer went, and it records that by itself: *"why don't you…"*,
*"did you do that?"*, a pasted error → it went wrong; *"thanks"*, *"works"*, a yes to its offer → it went right.
Anything else is not counted. **+** / **-** says it in one key; once in a while, after a change, a dim *"worked?"* line
reminds you (just keep typing to skip). At `exit` after a few turns: *"rate this session 1-5"* (any other key skips).
CodeMitra's learning round uses these to improve.

## Your notes
- `~/.codemitra/me.md`: your name, role, mail signature, tone, stack. Read every turn.
- `.codemitra/notes.md` in a project: facts about that project (how to run it, conventions). Read every turn there.

## What stays on your machine
Everything CodeMitra records stays in `~/.codemitra/` (sessions, traces for the dashboard, settings). Nothing is
uploaded, except: a once-a-day check for a new release (a plain request to GitHub; `codemitra update --check
never` stops it), web searches you ask for, MCP servers you use (git, GitHub, docs lookups; `/mcp` lists them), your
prompts and code while you use Kaggle ([guide](KAGGLE.md)), and sessions you choose to share ([guide](SHARING.md)).
