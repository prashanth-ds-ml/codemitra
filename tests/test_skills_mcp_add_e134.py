"""E-134: skills and MCP servers can be added, removed and imported; the skill index is short and says only true things;
the model opens a skill with use_skill (also one of yours outside the project) without widening the read guard."""
import json
import math
import pathlib
import subprocess
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app import mcp, skills
from app.core import chat as C


def make_skill(base: pathlib.Path, folder: str, name: str | None = None, desc: str = "Do a thing well. More text.",
               body: str = "# Steps\n1. look\n2. do\n") -> pathlib.Path:
    d = base / folder
    d.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name or folder}\ndescription: {desc}\n---\n" if name != "" else "# no front matter\n"
    (d / "SKILL.md").write_text(front + body, encoding="utf-8")
    return d


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "proj"
    w.mkdir()
    return w


# ─── S1: yours in every project, the project wins a name ─────────────────────

def test_user_skills_are_found_and_project_wins_a_name(ws):
    make_skill(skills.user_dir(), "mine", desc="Mine everywhere.")
    make_skill(skills.user_dir(), "shared", desc="User version.")
    make_skill(ws / "skills", "shared", desc="Project version.")

    found = {s.name: s for s in skills.discover(str(ws))}

    assert found["mine"].source == "user"
    assert found["shared"].source == "project" and found["shared"].description == "Project version."


def test_include_user_false_gives_only_the_project(ws):
    make_skill(skills.user_dir(), "mine")
    assert skills.discover(str(ws), include_user=False) == []


# ─── S2: the index is short and true; use_skill opens any skill ─────────────

def test_index_never_claims_auto_invoke_or_pre_approved_tools(ws):
    """E-134: the old text said auto_invoke skills run by themselves and pre_approved_tools skip approval; neither
    was built."""
    s = skills.Skill("x", "Do x.", "skills/x/SKILL.md", auto_invoke=True, pre_approved_tools=["run_command"])
    text = skills.format_prompt([s])
    assert "invoked automatically" not in text and "without additional approval" not in text
    assert "pre-approved" not in text and "auto-invoke" not in text
    assert "use_skill" in text


def test_index_stays_capped_with_many_skills(ws):
    many = [skills.Skill(f"skill-{i:02d}", "A long description that goes on. " * 20, f"skills/s{i}/SKILL.md")
            for i in range(40)]
    text = skills.format_prompt(many)
    assert len(text) <= skills.INDEX_MAX_CHARS
    assert "more (use_skill takes any name" in text
    assert "skill-00" in text


def test_the_phased_prompt_with_20_skills_stays_under_budget():
    import importlib.util
    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "model_view.py"
    spec = importlib.util.spec_from_file_location("model_view", path)
    mv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mv)
    twenty = [skills.Skill(f"skill-{i:02d}", "Build, modify, or review some kind of system. " * 10, "skills/x/SKILL.md")
              for i in range(20)]
    index_tokens = mv.estimate_tokens(skills.format_prompt(twenty))
    for name, total in mv.totals().items():
        assert total + index_tokens <= mv.BUDGET_TOKENS, (name, total, index_tokens)


def test_the_repo_skills_index_is_small():
    repo = pathlib.Path(__file__).resolve().parents[1]
    text = skills.format_prompt(skills.discover(str(repo), include_user=False))
    assert math.ceil(len(text) / 3.5) < 300  # was ~1,440 tokens with the 23 repo skills


def test_use_skill_reads_a_user_skill_outside_the_workspace(ws):
    make_skill(skills.user_dir(), "deploy-check", body="# Deploy\nrun the smoke test\n")
    found = skills.discover(str(ws))
    out = skills.use_skill(str(ws), found, "deploy-check")
    assert out.startswith("Skill deploy-check (yours)") and "run the smoke test" in out


def test_use_skill_unknown_name_lists_names(ws):
    make_skill(ws / "skills", "alpha")
    out = skills.use_skill(str(ws), skills.discover(str(ws)), "zzz")
    assert out.startswith("✗") and "alpha" in out
    assert skills.use_skill(str(ws), [], "x").startswith("✗ No skills")


def test_read_body_refuses_a_user_skill_path_outside_the_skills_dir(ws, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("nope", encoding="utf-8")
    fake = skills.Skill("evil", "x", secret.as_posix(), source="user")
    assert skills.read_body(str(ws), fake) is None


def test_use_skill_is_read_only_and_in_the_look_phase():
    assert "use_skill" in C.READ_ONLY_TOOLS
    assert "use_skill" in C.PHASES["look_at_code"]["tools"]
    assert any(s["name"] == "use_skill" for s in C.tool_specs("plan"))


def test_chat_dispatches_use_skill_to_the_hook(tmp_path):
    calls = []
    hooks = C.Hooks(stream=lambda chunks, step=1: SimpleNamespace(message=AIMessage(content="ok"), text="ok",
                                                                  stopped=False, printed=True),
                    show=lambda *a: None, confirm=lambda *a: True, run_shell=lambda c: ("", True),
                    web_search=lambda q: "", fetch_url=lambda u: "", mcp_find=lambda q: "", mcp_call=lambda *a: "",
                    use_skill=lambda name: calls.append(name) or f"Skill {name}: body")
    chat = C.ChatSession(workspace=str(tmp_path), llm=None, hooks=hooks)
    out, ok = chat._run("use_skill", {"name": "rag"}, plan_runner=None)
    assert ok and calls == ["rag"] and "body" in out


def test_chat_without_a_skill_hook_says_so(tmp_path):
    hooks = C.Hooks(stream=lambda *a, **k: None, show=lambda *a: None, confirm=lambda *a: True,
                    run_shell=lambda c: ("", True), web_search=lambda q: "", fetch_url=lambda u: "",
                    mcp_find=lambda q: "", mcp_call=lambda *a: "")
    chat = C.ChatSession(workspace=str(tmp_path), llm=None, hooks=hooks)
    out, ok = chat._run("use_skill", {"name": "rag"}, plan_runner=None)
    assert not ok and out.startswith("✗")


# ─── S3: add / remove / import ───────────────────────────────────────────────

def test_add_a_folder_to_yours_then_remove(ws, tmp_path):
    src = make_skill(tmp_path / "dl", "my-skill")
    (src / ".git").mkdir()
    (src / ".git" / "x").write_text("x", encoding="utf-8")

    reply = skills.handle_command(str(ws), f"add {src}")
    assert reply.startswith("✓") and "my-skill" in reply
    assert (skills.user_dir() / "my-skill" / "SKILL.md").is_file()
    assert not (skills.user_dir() / "my-skill" / ".git").exists()

    assert skills.handle_command(str(ws), "remove my-skill").startswith("✓")
    assert not (skills.user_dir() / "my-skill").exists()


def test_add_to_the_project(ws, tmp_path):
    src = make_skill(tmp_path / "dl", "proj-skill")
    assert skills.handle_command(str(ws), f"add {src} --project").startswith("✓")
    assert (ws / ".codemitra" / "skills" / "proj-skill" / "SKILL.md").is_file()
    assert {s.name for s in skills.discover(str(ws), include_user=False)} == {"proj-skill"}


def test_add_refuses_a_clash_unless_replace(ws, tmp_path):
    src = make_skill(tmp_path / "dl", "dup")
    skills.add(str(src), str(ws))
    assert skills.handle_command(str(ws), f"add {src}").startswith("✗")
    assert skills.handle_command(str(ws), f"add {src} --replace").startswith("✓")


def test_add_refuses_a_folder_without_a_proper_skill(ws, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "no SKILL.md" in skills.handle_command(str(ws), f"add {empty}")
    make_skill(tmp_path / "dl", "nofront", name="")
    assert skills.handle_command(str(ws), f"add {tmp_path / 'dl' / 'nofront'}").startswith("✗")
    make_skill(tmp_path / "dl2", "badname", name="../escape")
    assert "must be letters" in skills.handle_command(str(ws), f"add {tmp_path / 'dl2' / 'badname'}")


def test_add_a_repo_of_skills_and_pick_one(ws, tmp_path):
    repo = tmp_path / "repo"
    make_skill(repo / "skills", "one")
    make_skill(repo / "skills", "two")
    assert skills.add(str(repo), str(ws), only="two") == ["two"]
    assert sorted(p.name for p in skills.user_dir().iterdir()) == ["two"]


def test_add_from_a_git_url_clones_and_copies(ws, tmp_path, monkeypatch):
    repo = tmp_path / "gitrepo"
    make_skill(repo, "gitskill")

    def fake_run(cmd, **kw):
        assert cmd[:4] == ["git", "clone", "--depth", "1"] and kw.get("timeout")
        import shutil
        shutil.copytree(repo, cmd[-1], dirs_exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(skills.subprocess, "run", fake_run)
    monkeypatch.setattr(skills.shutil, "which", lambda n: "git")
    assert skills.add("https://github.com/someone/skills.git", str(ws)) == ["gitskill"]


def test_import_claude_skills(ws, tmp_path, monkeypatch):
    claude = tmp_path / "claude-skills"
    make_skill(claude, "from-claude")
    make_skill(claude, "broken", name="")
    monkeypatch.setenv("CLAUDE_SKILLS_DIR", str(claude))
    reply = skills.handle_command(str(ws), "import claude")
    assert "Imported 1" in reply and "from-claude" in reply and "broken" in reply
    assert (skills.user_dir() / "from-claude").is_dir()


def test_other_words_are_not_managed(ws):
    assert skills.handle_command(str(ws), "show x") is None
    assert skills.handle_command(str(ws), "") is None


# ─── M1: mcp add / remove ────────────────────────────────────────────────────

def _user_servers():
    return json.loads(mcp.user_config_path().read_text(encoding="utf-8"))["mcpServers"]


def test_mcp_add_a_command_server_without_allow(ws):
    reply = mcp.handle_add_remove(ws, ["add", "fs", "--env", "DEBUG=1", "--", "npx", "-y",
                                       "@modelcontextprotocol/server-filesystem", r"C:\Users\me\docs"])
    assert reply.startswith("✓")
    entry = _user_servers()["fs"]
    assert entry == {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", r"C:\Users\me\docs"],
                     "env": {"DEBUG": "1"}}
    spec = mcp.find(mcp.discover(ws), "fs")
    assert mcp.needs_approval(spec, "write_file") and mcp.needs_approval(spec, "read_file")


def test_mcp_add_runs_the_test_after_a_user_add(ws):
    seen = []
    reply = mcp.handle_add_remove(ws, ["add", "t", "--", "uvx", "x"], test=lambda n: seen.append(n) or "✓ started")
    assert seen == ["t"] and reply.endswith("✓ started")


def test_mcp_add_http_with_header(ws):
    reply = mcp.handle_add_remove(ws, ["add", "remote", "--url", "https://example.com/mcp",
                                       "--header", "Authorization=Bearer ${MY_TOKEN}"])
    assert reply.startswith("✓")
    assert _user_servers()["remote"] == {"type": "http", "url": "https://example.com/mcp",
                                         "headers": {"Authorization": "Bearer ${MY_TOKEN}"}}


def test_mcp_add_to_the_project_needs_trust_and_refuses_literal_secrets(ws):
    bad = mcp.handle_add_remove(ws, ["add", "p", "--project", "--url", "https://x.dev/mcp",
                                     "--header", "Authorization=Bearer ghp_realsecret123"])
    assert bad.startswith("✗") and "secret" in bad
    assert not mcp.project_config_path(ws).exists()
    ok = mcp.handle_add_remove(ws, ["add", "p", "--project", "--url", "https://x.dev/mcp",
                                    "--header", "Authorization=Bearer ${X_TOKEN}"], test=lambda n: "never")
    assert ok.startswith("✓") and "/mcp trust" in ok and "never" not in ok
    assert not mcp.find(mcp.discover(ws), "p").trusted


def test_mcp_add_refuses_bad_input(ws):
    for argv in (["add"], ["add", "x"], ["add", "../x", "--", "a"], ["add", "x", "--url", "ftp://a"],
                 ["add", "x", "--url", "https://a", "--", "cmd"], ["add", "x", "--bogus", "--", "a"],
                 ["add", "x", "stray", "--", "a"], ["add", "x", "--env", "NOEQUALS", "--", "a"]):
        assert mcp.handle_add_remove(ws, argv).startswith("✗"), argv


def test_mcp_add_clash_and_replace_then_remove(ws):
    assert mcp.handle_add_remove(ws, ["add", "a", "--", "one"]).startswith("✓")
    assert mcp.handle_add_remove(ws, ["add", "a", "--", "two"]).startswith("✗")
    assert mcp.handle_add_remove(ws, ["add", "a", "--replace", "--", "two"]).startswith("✓")
    assert _user_servers()["a"]["command"] == "two"
    assert mcp.handle_add_remove(ws, ["remove", "a"]).startswith("✓")
    assert "a" not in _user_servers()


def test_mcp_remove_a_builtin_points_to_off(ws):
    reply = mcp.handle_add_remove(ws, ["remove", "git"])
    assert reply.startswith("✗") and "/mcp off git" in reply


def test_slash_mcp_add_keeps_windows_paths_and_quotes(ws):
    reply = mcp.handle_command(ws, r'add fs -- npx -y server "C:\My Docs\notes"')
    assert reply.startswith("✓")
    assert _user_servers()["fs"]["args"] == ["-y", "server", r"C:\My Docs\notes"]


def test_cli_raw_tail_keeps_the_double_dash(monkeypatch):
    from app import main
    monkeypatch.setattr(main.sys, "argv", ["codemitra", "mcp", "--cwd", "x", "add", "fs", "--", "npx", "--cwd", "y"])
    assert main._raw_tail_after("mcp") == ["add", "fs", "--", "npx", "--cwd", "y"]


# ─── M2: import from Cursor and VS Code ─────────────────────────────────────

def test_import_cursor(ws, tmp_path, monkeypatch):
    cfg = tmp_path / "cursor.json"
    cfg.write_text(json.dumps({"mcpServers": {"cur": {"command": "x"}}}), encoding="utf-8")
    monkeypatch.setenv("CODEMITRA_CURSOR_CONFIG", str(cfg))
    reply = mcp.handle_command(ws, "import cursor")
    assert "Imported 1" in reply and _user_servers()["cur"] == {"command": "x"}
    assert not mcp.project_config_path(ws).exists()


def test_import_vscode_servers_key_and_inputs_warning(ws, tmp_path, monkeypatch):
    cfg = tmp_path / "vscode.json"
    cfg.write_text(json.dumps({"servers": {
        "vs": {"type": "stdio", "command": "y"},
        "gh": {"type": "http", "url": "https://h", "headers": {"Authorization": "Bearer ${input:tok}"}}}}),
        encoding="utf-8")
    monkeypatch.setenv("CODEMITRA_VSCODE_CONFIG", str(cfg))
    reply = mcp.handle_command(ws, "import vscode")
    assert "Imported 2" in reply and "${input:" in reply
    assert _user_servers()["vs"] == {"command": "y"}
    assert mcp.find(mcp.discover(ws), "gh").kind == "http"


def test_import_nothing_found(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMITRA_CURSOR_CONFIG", str(tmp_path / "none.json"))
    assert mcp.handle_command(ws, "import cursor").startswith("No MCP servers found")
