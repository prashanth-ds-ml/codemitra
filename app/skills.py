"""CodeMitra skills: find them, list them briefly for the model, open one on demand, add / remove / import them.

A skill is a folder with a ``SKILL.md`` (YAML-ish front matter with ``name`` and ``description``, then the playbook),
the same format Claude Code uses. Two places are searched:

* the project: ``skills/`` and ``.codemitra/skills/`` (``skill_dirs`` in the config), inside the workspace only
* yours, in every project: ``~/.codemitra/skills/`` (a project skill wins over yours with the same name)
* built in, in every project: ``app/builtin_skills/`` (shipped with CodeMitra; yours and the project's win a name)

v0.9.0 (BUILD_V09 F-1, F-2): a small model rarely opens an optional skill by itself, so when a request matches a
skill's ``triggers`` (or a skill says ``when: change``), CodeMitra puts the skill's text in that turn's phase note
(``turn_skills`` / ``skill_note``), outside the cached system prompt. Each use is recorded.

The system prompt carries only a short index (one line per skill, capped, E-134); the model opens a skill with the
read-only ``use_skill`` tool, which reads yours too without widening the workspace read guard. Nothing in a skill is
ever run: it is text the model reads.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any


_MAX_DESCRIPTION_CHARS = 700
INDEX_MAX_CHARS = 800       # E-134: the whole index in the system prompt (~230 tokens), whatever is installed
INDEX_LINE_CHARS = 90       # one line per skill: name + the start of its description
MAX_SKILL_CHARS = 12_000    # what use_skill returns at most
GIT_TIMEOUT_S = 120
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: str  # project skills: relative to the workspace (posix); yours: absolute
    args: dict[str, Any] = field(default_factory=dict)
    model_override: str | None = None
    pre_approved_tools: list[str] = field(default_factory=list)
    auto_invoke: bool = False
    invocation_mode: str = "prompt"
    source: str = "project"  # "project" | "user" | "builtin"
    triggers: tuple[str, ...] = ()  # v0.9.0: words in a request that make CodeMitra load this skill for the turn
    when: str = ""                  # v0.9.0: "change" = loaded on every turn that changes files


def builtin_dir() -> pathlib.Path:
    """The skills shipped with CodeMitra (v0.9.0): every project has them."""
    return pathlib.Path(__file__).resolve().parent / "builtin_skills"


def user_dir() -> pathlib.Path:
    """~/.codemitra/skills (CODEMITRA_HOME respected, so tests and dev runs never touch the real one)."""
    from app.core import harness as H
    return H.home() / "skills"


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*", text, flags=re.DOTALL)
    if not match:
        return {}

    values: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in ("args", "pre_approved_tools"):
            try:
                values[key] = json.loads(value)
            except json.JSONDecodeError:
                values[key] = {}
        elif key == "auto_invoke":
            values[key] = value.lower() in ("true", "yes", "1")
        else:
            values[key] = value
    return values


def _read(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _skill_from_file(skill_file: pathlib.Path, path_text: str, source: str) -> Skill | None:
    text = _read(skill_file)
    if text is None:
        return None
    frontmatter = _parse_frontmatter(text)
    name = str(frontmatter.get("name", skill_file.parent.name)).strip()
    description = str(frontmatter.get("description", "")).strip()
    if not name or not description:
        return None
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS].rstrip() + "..."
    args = frontmatter.get("args", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    pre_approved = frontmatter.get("pre_approved_tools", [])
    if isinstance(pre_approved, str):
        try:
            pre_approved = json.loads(pre_approved)
        except json.JSONDecodeError:
            pre_approved = [t.strip() for t in pre_approved.split(",") if t.strip()]
    return Skill(name=name, description=description, path=path_text, args=args,
                 model_override=frontmatter.get("model_override"), pre_approved_tools=pre_approved,
                 auto_invoke=frontmatter.get("auto_invoke", False),
                 invocation_mode=frontmatter.get("invocation_mode", "prompt"), source=source,
                 triggers=tuple(w.strip().lower() for w in str(frontmatter.get("triggers", "")).split(",")
                                if w.strip()),
                 when=str(frontmatter.get("when", "")).strip().lower())


def _project_skills(root: pathlib.Path, entries) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[pathlib.Path] = set()
    for raw_entry in entries:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        base = pathlib.Path(entry)
        target = base if base.is_absolute() else root / base
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_dir():
            continue
        for skill_file in sorted(resolved.glob("*/SKILL.md")):
            try:
                skill_path = skill_file.resolve()
                skill_path.relative_to(root)
            except (OSError, ValueError):
                continue
            if skill_path in seen:
                continue
            skill = _skill_from_file(skill_path, skill_path.relative_to(root).as_posix(), "project")  # E-005
            if skill:
                skills.append(skill)
                seen.add(skill_path)
    return skills


def user_skills() -> list[Skill]:
    base = user_dir()
    if not base.is_dir():
        return []
    out = []
    for skill_file in sorted(base.glob("*/SKILL.md")):
        skill = _skill_from_file(skill_file, skill_file.resolve().as_posix(), "user")
        if skill:
            out.append(skill)
    return out


def builtin_skills() -> list[Skill]:
    base = builtin_dir()
    if not base.is_dir():
        return []
    out = []
    for skill_file in sorted(base.glob("*/SKILL.md")):
        skill = _skill_from_file(skill_file, skill_file.resolve().as_posix(), "builtin")
        if skill:
            out.append(skill)
    return out


def discover(workspace: str, entries=None, include_user: bool = True, include_builtin: bool = True) -> list[Skill]:
    """Project skills (inside the workspace only), then yours (~/.codemitra/skills), then the built-in ones; the first
    one with a name wins."""
    root = pathlib.Path(workspace).resolve()
    if entries is None:
        entries = ["skills", ".codemitra/skills"]
    if isinstance(entries, str):
        entries = [entries]
    skills = _project_skills(root, entries)
    for more in ((user_skills() if include_user else []) + (builtin_skills() if include_builtin else [])):
        if more.name.lower() not in {s.name.lower() for s in skills}:
            skills.append(more)
    return skills


def _skill_path(skill: Skill) -> pathlib.PurePosixPath:
    """Skill paths may have been written on Windows (`skills\\a\\SKILL.md`); read them on any OS (E-005)."""
    return pathlib.PurePosixPath(str(skill.path).replace("\\", "/"))


def find(skills: list[Skill], query: str) -> Skill | None:
    """Find a skill by exact name, folder name, or unambiguous partial text."""
    target = (query or "").strip().lower()
    if not target:
        return None

    for skill in skills:
        folder = _skill_path(skill).parent.name.lower()
        if target in {skill.name.lower(), folder}:
            return skill

    matches = [
        skill for skill in skills
        if target in skill.name.lower() or target in _skill_path(skill).parent.name.lower()
    ]
    return matches[0] if len(matches) == 1 else None


def read_body(workspace: str, skill: Skill) -> str | None:
    """A skill's SKILL.md: project skills only from inside the workspace, yours only from ~/.codemitra/skills."""
    if skill.source in ("user", "builtin"):
        base = (user_dir() if skill.source == "user" else builtin_dir()).resolve()
        target = pathlib.Path(str(skill.path))
    else:
        base = pathlib.Path(workspace).resolve()
        target = base.joinpath(*_skill_path(skill).parts)
    try:
        resolved = target.resolve()
        resolved.relative_to(base)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return _read(resolved)


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return m.group(1) if m else text


def format_prompt(skills: list[Skill]) -> str:
    """The short skill index for the system prompt (E-134): one line each, the whole index capped at INDEX_MAX_CHARS.

    Says only what is true: the model opens a skill with use_skill; nothing runs by itself or skips approval.
    """
    if not skills:
        return ""
    head = ("## Skills\n"
            "Playbooks for common jobs. When the request matches one, call use_skill with its name first and "
            "follow it. Approval rules stay the same.\n")
    lines: list[str] = []
    used = len(head)
    for i, skill in enumerate(skills):
        line = f"- `{skill.name}`: {_first_sentence(skill.description)}"
        if len(line) > INDEX_LINE_CHARS:
            line = line[:INDEX_LINE_CHARS - 1].rstrip() + "…"
        rest = len(skills) - i - 1
        tail = f"\n- … {rest} more (use_skill takes any name; /skills lists them)" if rest else ""
        if used + len(line) + 1 + len(tail) > INDEX_MAX_CHARS and lines:
            lines.append(f"- … {len(skills) - i} more (use_skill takes any name; /skills lists them)")
            break
        lines.append(line)
        used += len(line) + 1
    return head + "\n".join(lines)


def use_skill(workspace: str, skills: list[Skill], name: str) -> str:
    """The use_skill tool: the skill's playbook text, or a plain ✗ with the names there are."""
    if not skills:
        return "✗ No skills are installed (`codemitra skills add <folder or git URL>`)."
    skill = find(skills, name)
    if skill is None:
        names = ", ".join(s.name for s in skills[:40])
        return f"✗ No skill named '{name}'. Skills: {names}"
    body = read_body(workspace, skill)
    if body is None:
        return f"✗ Could not read the skill '{skill.name}'."
    if len(body) > MAX_SKILL_CHARS:
        body = body[:MAX_SKILL_CHARS] + f"\n… (cut at {MAX_SKILL_CHARS:,} characters)"
    return f"Skill {skill.name} ({SOURCE_TEXT.get(skill.source, skill.source)}):\n\n{body}"


SOURCE_TEXT = {"user": "yours", "project": "this project", "builtin": "built in"}
NOTE_SKILL_CHARS = 3500     # v0.9.0: one skill's text in a turn's note (a built-in skill is ~2,500)
NOTE_MAX_SKILLS = 2         # at most this many skills loaded into one turn
LOADED_PHASES = ("make_change", "look_at_code")
_WORD = re.compile(r"[a-z0-9.+#-]+")
_FRONT = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


def turn_skills(skills: list[Skill], request: str, phase: str) -> list[Skill]:
    """The skills to load into this turn (v0.9.0 F-2): rules, no model call. A trigger word or phrase in the request
    picks a skill in the look and change phases; `when: change` skills come with every change phase. Request matches
    first, at most NOTE_MAX_SKILLS."""
    if phase not in LOADED_PHASES:
        return []
    text = " " + " ".join(_WORD.findall((request or "").lower())) + " "
    matched = [s for s in skills if any(f" {w} " in text for w in s.triggers)]
    always = [s for s in skills if s.when == "change" and phase == "make_change" and s not in matched]
    return (matched + always)[:NOTE_MAX_SKILLS]


def skill_note(workspace: str, chosen: list[Skill]) -> str:
    """The text that goes into the turn's phase note for the chosen skills (front matter left out)."""
    parts = []
    for skill in chosen:
        body = read_body(workspace, skill)
        if not body:
            continue
        body = _FRONT.sub("", body, count=1).strip()
        if len(body) > NOTE_SKILL_CHARS:
            body = body[:NOTE_SKILL_CHARS].rstrip() + "\n…"
        parts.append(f"[CodeMitra: skill `{skill.name}` fits this request. Follow it:]\n{body}")
    return "\n\n".join(parts)


# ─── Add / remove / import (S3) ──────────────────────────────────────────────

class SkillError(Exception):
    pass


def check_dir(folder: pathlib.Path) -> tuple[str, str]:
    """(name, description) of a skill folder, or SkillError saying what is missing."""
    skill_file = folder / "SKILL.md"
    if not skill_file.is_file():
        raise SkillError(f"{folder} has no SKILL.md")
    skill = _skill_from_file(skill_file, skill_file.as_posix(), "user")
    if skill is None:
        raise SkillError(f"{skill_file} needs front matter with a name and a description (--- name: … description: … ---)")
    if not _SAFE_NAME.match(skill.name):
        raise SkillError(f"the skill name '{skill.name}' must be letters, digits, '.', '_' or '-' (up to 64)")
    return skill.name, skill.description


def _target_root(workspace: str, project: bool) -> pathlib.Path:
    return pathlib.Path(workspace).resolve() / ".codemitra" / "skills" if project else user_dir()


def _is_git_url(src: str) -> bool:
    return bool(re.match(r"^(https://|git@|ssh://)", src.strip())) or src.strip().endswith(".git")


def _skill_folders(base: pathlib.Path) -> list[pathlib.Path]:
    """base itself if it is a skill, else the skill folders one or two levels down (a repo of skills)."""
    if (base / "SKILL.md").is_file():
        return [base]
    found = sorted({p.parent for p in base.glob("*/SKILL.md")} | {p.parent for p in base.glob("*/*/SKILL.md")})
    return [p for p in found if ".git" not in p.parts]


def _copy_in(folder: pathlib.Path, root: pathlib.Path, replace: bool) -> str:
    name, _ = check_dir(folder)
    dest = root / name
    if dest.exists():
        if not replace:
            raise SkillError(f"a skill named '{name}' is already installed ({dest}); add --replace to update it")
        shutil.rmtree(dest)
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"), symlinks=False)
    return name


def add(src: str, workspace: str, project: bool = False, replace: bool = False, only: str = "") -> list[str]:
    """Install skill(s) from a folder or a git URL; returns the names added. Nothing in them is run."""
    root = _target_root(workspace, project)
    src = src.strip()
    if not src:
        raise SkillError("say what to add: a folder or a git URL")
    tmp = None
    try:
        if _is_git_url(src):
            if not shutil.which("git"):
                raise SkillError("git is not installed; download the skill and add its folder instead")
            tmp = tempfile.mkdtemp(prefix="codemitra-skill-")
            try:
                proc = subprocess.run(["git", "clone", "--depth", "1", "--", src, tmp], capture_output=True,
                                      text=True, timeout=GIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise SkillError(f"git clone took over {GIT_TIMEOUT_S}s") from None
            if proc.returncode != 0:
                raise SkillError(f"git clone failed: {(proc.stderr or proc.stdout).strip()[-300:]}")
            base = pathlib.Path(tmp)
        else:
            base = pathlib.Path(os.path.expanduser(src)).resolve()
            if not base.is_dir():
                raise SkillError(f"{src} is not a folder")
        folders = _skill_folders(base)
        if only:
            folders = [f for f in folders if f.name.lower() == only.lower()
                       or (_skill_from_file(f / "SKILL.md", "", "user") or Skill("", "", "")).name.lower() == only.lower()]
        if not folders:
            raise SkillError(f"no SKILL.md found in {src}" + (f" for '{only}'" if only else ""))
        return [_copy_in(f, root, replace) for f in folders]
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def remove(name: str, workspace: str, project: bool = False) -> pathlib.Path:
    root = _target_root(workspace, project)
    if not _SAFE_NAME.match(name or ""):
        raise SkillError(f"'{name}' is not a skill name")
    for folder in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        skill = _skill_from_file(folder, "", "user")
        if folder.parent.name == name or (skill and skill.name == name):
            shutil.rmtree(folder.parent)
            return folder.parent
    raise SkillError(f"no skill '{name}' in {root}")


def claude_skills_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CLAUDE_SKILLS_DIR") or pathlib.Path.home() / ".claude" / "skills")


def import_claude(workspace: str) -> tuple[list[str], list[str]]:
    """Copy your Claude Code skills (~/.claude/skills) into ~/.codemitra/skills: (added, already there or invalid)."""
    base = claude_skills_dir()
    added, skipped = [], []
    for folder in _skill_folders(base) if base.is_dir() else []:
        try:
            added.append(_copy_in(folder, user_dir(), replace=False))
        except SkillError:
            skipped.append(folder.name)
    return added, skipped


def handle_command(workspace: str, argline: str) -> str | None:
    """`add` / `remove` / `import` (from `codemitra skills …` or `/skills …`); None for anything else."""
    parts = argline.split()
    if not parts or parts[0].lower() not in {"add", "remove", "rm", "import"}:
        return None
    sub, rest = parts[0].lower(), parts[1:]
    project = "--project" in rest
    replace = "--replace" in rest
    rest = [p for p in rest if p not in ("--project", "--replace")]
    where = "this project (.codemitra/skills)" if project else f"your skills ({user_dir()})"
    try:
        if sub == "add":
            if not rest:
                return "Usage: `skills add <folder or git URL> [skill name] [--project] [--replace]`"
            names = add(rest[0], workspace, project=project, replace=replace, only=rest[1] if len(rest) > 1 else "")
            return (f"✓ Added {len(names)} skill(s) to {where}: {', '.join(names)}. Nothing in them was run; "
                    "CodeMitra reads them when a request matches.")
        if sub in {"remove", "rm"}:
            if not rest:
                return "Usage: `skills remove <name> [--project]`"
            path = remove(rest[0], workspace, project=project)
            return f"✓ Removed {path}"
        if not rest or rest[0].lower() != "claude":
            return "Usage: `skills import claude` (copies ~/.claude/skills into ~/.codemitra/skills)"
        added, skipped = import_claude(workspace)
        if not added and not skipped:
            return f"No Claude Code skills found in {claude_skills_dir()}."
        msg = f"✓ Imported {len(added)} skill(s): {', '.join(added) or 'none'}."
        return msg + (f" Skipped (already there or no name/description): {', '.join(skipped)}." if skipped else "")
    except SkillError as exc:
        return f"✗ {exc}"
