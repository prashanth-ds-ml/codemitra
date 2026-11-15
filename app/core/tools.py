"""The core loop's tools (M1): small, workspace-confined, built for small models.

    list_files · read_file · search · write_file · edit_file · run_tests · finish

Rules the tools enforce (not the prompt):
- every path stays inside the workspace (fail closed, E-003);
- a file must be read before it is edited, and it must not have changed since (dsh fs-observation-policy);
- `tests/` is read-only: the builder makes tests pass, it never edits them;
- edit_file matches exactly first, then ignoring indentation and trailing spaces (forgiving match);
- test output is trimmed to head + tail for the model; the full output is saved to a file (spill policy).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".codemitra", ".mitra", ".mypy_cache",
             ".ruff_cache", "dist", "build"}
MAX_READ_LINES = 400
MAX_OUTPUT_CHARS = 4000
TEST_TIMEOUT_S = 120


class ToolError(Exception):
    """A mistake the model can fix; the message is sent back as the tool result."""


@dataclass
class Workspace:
    root: Path
    test_command: str = "python -m pytest -q"
    read_only: tuple[str, ...] = ("tests",)
    seen: dict[str, float] = field(default_factory=dict)  # path -> mtime when last read or written
    spill_dir: Path | None = None
    changed: set[str] = field(default_factory=set)
    # before_write(rel, old_text_or_None, new_text): raise ToolError to refuse (the chat's ask mode uses it)
    before_write: object = None
    journal: list | None = None  # undo entries in the /undo format, when the caller wants them
    # must-have 12: (absolute path) -> bool, asked before reading anything outside the project; None = never
    before_read_outside: object = None
    allowed_outside: set = field(default_factory=set)  # folders the user allowed this session (asked once each)
    python: str = ""  # E-132: the Python its tests use when the caller knows it (the benchmark's own)

    def __post_init__(self):
        self.root = Path(self.root).resolve()

    def read_path(self, rel: str) -> Path:
        """A path to READ: inside the project as `path()`; outside it only after the user says yes (read-only,
        must-have 12). Secret files are never read, inside or out."""
        raw = (rel or "").strip().strip("\"'")
        try:
            if raw.startswith("~") and callable(self.before_read_outside):
                raise ToolError("a home path")  # path() would read '~/x' as a folder named ~ in the project
            full = self.path(rel)
        except ToolError:
            if not callable(self.before_read_outside):
                raise
            p = Path(os.path.expanduser(raw))
            full = (p if p.is_absolute() else self.root / p).resolve()
            if self._inside(full) is not None:
                raise
            if is_secret_path(full):
                raise ToolError(f"'{raw}' looks like a secret (keys, tokens, passwords): CodeMitra never reads it.") \
                    from None
            if not full.exists():
                raise ToolError(f"'{raw}' does not exist." + self.suggest(raw)) from None
            # a yes covers the files directly in that folder, never its subfolders; in the home folder or a drive
            # root only that one file (review: one yes in ~ opened every project and AppData)
            folder = full if full.is_dir() else full.parent
            broad = folder == Path.home().resolve() or folder == Path(folder.anchor)
            key = full if broad else folder
            if key not in self.allowed_outside:
                if not self.before_read_outside(str(full)):
                    raise ToolError(f"The user did not allow reading {full} (outside the project). Work with the "
                                    "project's files, or ask them for what you need.") from None
                self.allowed_outside.add(key)
            return full
        if is_secret_path(full) and not full.name.lower().endswith((".example", ".sample", ".template")):
            # E-131: inside the project too: keys never go into the chat, the traces or the Kaggle tunnel
            raise ToolError(f"'{self.rel(full)}' holds secrets (keys, tokens, passwords): CodeMitra does not read it. "
                            "Ask the user for the names it needs, never the values.")
        return full

    def show(self, full: Path) -> str:
        """How a path is named to the model: relative inside the project, absolute outside it."""
        return self.rel(full) if self._inside(full) is not None else str(full)

    # ── paths ────────────────────────────────────────────────────────────
    def path(self, rel: str) -> Path:
        rel = (rel or ".").strip().strip("\"'")
        p = Path(rel)
        if p.is_absolute() or rel.startswith(("/", "\\")):  # '/logs/x' has no drive on Windows: rooted, not ours
            inside = self._inside(p)
            if inside is not None:  # an absolute path into this workspace: use it
                return inside
            raise ToolError(f"Use a path relative to the workspace, not '{rel}'." + self.suggest(rel))
        parts = p.parts
        if len(parts) > 1 and parts[0].lower() == self.root.name.lower() and not (self.root / parts[0]).exists():
            p = Path(*parts[1:])  # E-019: model repeated the workspace folder name
        full = (self.root / p).resolve()
        try:
            full.relative_to(self.root)
        except ValueError:
            raise ToolError(f"'{rel}' is outside the workspace." + self.suggest(rel)) from None
        return full

    def _inside(self, p: Path) -> Path | None:
        try:
            full = p.resolve()
            full.relative_to(self.root)
            return full
        except (ValueError, OSError):
            return None

    def suggest(self, rel: str) -> str:
        """' Did you mean brick-breaker/plan.md?' when a file in the workspace matches the end of a wrong path
        (D-065 P0: seven calls to made-up /logs/brick-breaker/... paths), else ''."""
        parts = [x for x in Path(rel.replace("\\", "/")).parts if x not in ("/", "\\") and not x.endswith(":\\")]
        for i in range(len(parts)):
            cand = self.root.joinpath(*parts[i:])
            if parts[i:] and cand.exists():
                return f" Did you mean '{cand.relative_to(self.root).as_posix()}'?"
        if parts:
            name = parts[-1]
            hits = []
            for found in self.root.rglob(name):
                if any(x in found.parts for x in (".git", ".venv", "node_modules", "__pycache__", ".codemitra")):
                    continue
                hits.append(found.relative_to(self.root).as_posix())
                if len(hits) > 3:
                    break
            if hits:
                return " Did you mean " + " or ".join(f"'{h}'" for h in hits[:3]) + "?"
        return " Use list_files to see what exists."

    def rel(self, full: Path) -> str:
        return full.relative_to(self.root).as_posix() or "."

    def check_writable(self, full: Path) -> None:
        rel = self.rel(full)
        for ro in self.read_only:
            if rel == ro or rel.startswith(ro + "/"):
                raise ToolError(f"'{rel}' is a test file; tests are read-only. Change the code so the tests pass.")
        name = full.name.lower()
        if name.startswith(".env") or name.endswith((".pem", ".key")):
            raise ToolError(f"'{rel}' looks like a secret file; CodeMitra does not write those.")


def _commit(ws: Workspace, full: Path, new_text: str) -> None:
    """Write a file after the approval hook, recording an undo entry."""
    rel = ws.rel(full)
    old = full.read_text(encoding="utf-8", errors="replace") if full.exists() else None
    if callable(ws.before_write):
        ws.before_write(rel, old, new_text)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(new_text, encoding="utf-8")
    if ws.journal is not None:
        ws.journal.append({"kind": "create_file", "path": str(full), "existed": old is not None,
                           "before": old, "after": new_text})
    ws.seen[rel] = full.stat().st_mtime
    ws.changed.add(rel)


# ── tools ────────────────────────────────────────────────────────────────────

# E-131: names that hold keys, not every file with "token" in it (tokenizer.py, secret_santa.py are code)
_SECRET_NAMES = re.compile(r"^(\.env(\..+)?|.*\.(pem|key|p12|pfx)|id_(rsa|ed25519|ecdsa|dsa)(\.pub)?|\.netrc|"
                           r"\.git-credentials|\.pypirc|\.npmrc|credentials(\.json)?|kaggle\.json|access_token|"
                           r"(client_)?secrets?\.(json|ya?ml|toml|txt)|(auth_)?tokens?\.(json|txt))$", re.I)
_SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".kaggle", ".azure", ".docker", ".kube"}


def is_secret_path(p: Path) -> bool:
    """Keys, tokens and password files, and the folders that hold them: never read outside the project."""
    return bool(_SECRET_NAMES.match(p.name)) or any(part.lower() in _SECRET_DIRS for part in p.parts)


# must-have 11: the installed package, read in the project's own Python (not CodeMitra's), never from memory
_PKG_SCRIPT = r"""
import importlib, importlib.metadata as md, inspect, json, sys
name = sys.argv[1].strip()
out = {"python": sys.executable}
dist_name = name.split(".")[0]
try:
    d = md.distribution(dist_name)
    out["version"], out["summary"] = d.version, (d.metadata.get("Summary") or "")
except md.PackageNotFoundError:
    out["version"] = None
try:
    m = importlib.import_module(name.replace("-", "_"))
    out["file"] = getattr(m, "__file__", "") or ""
    out["version"] = out.get("version") or str(getattr(m, "__version__", "") or "") or None
    out["doc"] = "\n".join((inspect.getdoc(m) or "").splitlines()[:6])
    out["names"] = [n for n in dir(m) if not n.startswith("_")][:60]
except Exception as exc:
    out["import_error"] = f"{type(exc).__name__}: {exc}"[:300]
print(json.dumps(out))
"""
PKG_TIMEOUT_S = 30


def package_info(ws: Workspace, name: str) -> str:
    name = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", name):
        raise ToolError("Give a package or module name, for example 'pygame' or 'fastapi.testclient'.")
    top = name.split(".")[0].replace("-", "_")
    own = [f for f in (ws.root / f"{top}.py", ws.root / top / "__init__.py") if f.is_file()]
    if own:  # review: importing the project's own module runs its code (a game window, file writes) in a read tool
        return f"'{name}' is this project's own code ({ws.rel(own[0])}): read_file it instead."
    py = project_python(ws.root)
    if py == sys.executable and top not in getattr(sys, "stdlib_module_names", ()):
        # review: CodeMitra's private Python is not the project's; its packages would mislead
        return (f"This project has no Python of its own yet, so nothing is installed for it. `pip install {top}` "
                "makes the project's .venv and installs it there.")
    import tempfile
    try:  # run outside the project folder, so only installed packages (and the standard library) are imported
        with tempfile.TemporaryDirectory() as away:
            p = subprocess.run([py, "-c", _PKG_SCRIPT, name], cwd=away, capture_output=True, text=True,
                               timeout=PKG_TIMEOUT_S, encoding="utf-8", errors="replace")
        info = json.loads((p.stdout or "").strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        raise ToolError(f"Could not ask the project's Python ({py}) about '{name}': {exc}") from None
    where = ws.show(Path(info["python"])) if info.get("python") else py
    if not info.get("version") and info.get("import_error"):
        return (f"'{name}' is not installed for the project's Python ({where}). Install it with "
                f"`pip install {name.split('.')[0]}` (it goes into the project's Python), or use what is installed.")
    lines = [f"{name} {info.get('version') or '(version unknown)'} · installed for {where}"
             + (f" · {info['summary']}" if info.get("summary") else "")]
    if info.get("import_error"):
        lines.append(f"Installed, but importing it failed: {info['import_error']}")
    if info.get("doc"):
        lines.append("Module doc: " + info["doc"])
    if info.get("names"):
        lines.append("Public names: " + ", ".join(info["names"]))
    if info.get("file"):
        lines.append(f"Source: {info['file']} (read_file it for exact signatures)")
    return "\n".join(lines)


def list_files(ws: Workspace, path: str = ".") -> str:
    base = ws.read_path(path)
    if not base.exists():
        raise ToolError(f"'{path}' does not exist." + ws.suggest(path))
    if base.is_file():
        return ws.show(base)
    if ws._inside(base) is None:  # outside the project (allowed): one level, no secrets
        names = sorted(e.name + ("/" if e.is_dir() else "") for e in base.iterdir() if not is_secret_path(e))
        return f"{base} (outside the project, read-only)\n" + ("\n".join(names[:300]) or "(empty)")
    lines: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth > 4:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            lines.append(ws.rel(Path(dirpath) / name))
        if len(lines) > 300:
            lines.append("… (more files not shown)")
            break
    return "\n".join(lines) if lines else "(empty)"


def read_file(ws: Workspace, path: str, start: int = 1, end: int = 0) -> str:
    full = ws.read_path(path)
    if not full.is_file():
        raise ToolError(f"'{path}' is not a file." + ws.suggest(path))
    text = full.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    name = ws.show(full)
    if ws._inside(full) is not None:
        ws.seen[name] = full.stat().st_mtime  # only project files can be edited after a read
    if int(start or 1) <= 1 and not int(end or 0) and len(lines) > OUTLINE_OVER:
        return outline(name, text)  # D-065 P2: a map of a large file, then read only the part needed
    start = max(1, int(start or 1))
    end = int(end or 0) or min(len(lines), start + MAX_READ_LINES - 1)
    shown = lines[start - 1:end]
    body = "\n".join(f"{i:4} | {line}" for i, line in enumerate(shown, start))
    more = f"\n… {len(lines) - end} more lines (read_file with start={end + 1})" if end < len(lines) else ""
    return f"{name} ({len(lines)} lines)\n{body}{more}" if lines else f"{name} (empty file)"


OUTLINE_OVER = 150     # lines: a larger file read without a range gives its outline first (D-065 P2)
OUTLINE_MAX = 80       # outline entries shown
HEAD_LINES = 20        # plus the first lines (imports, constants)
_DEF_LINE = re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?(def|class|function|interface|type|struct|enum|fn|func|"
                       r"impl|trait|module)\b")


def outline_entries(rel: str, text: str) -> list[tuple[int, str]]:
    """(line, entry) for the definitions of a file: Python via ast (classes, functions, methods), Markdown headings,
    other code by a definition pattern."""
    lines = text.splitlines()
    if rel.endswith(".py"):
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            out = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((node.lineno, f"def {node.name}({ast.unparse(node.args)})"))
                elif isinstance(node, ast.ClassDef):
                    out.append((node.lineno, f"class {node.name}"))
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            out.append((sub.lineno, f"    def {sub.name}({ast.unparse(sub.args)})"))
            return out
    if rel.lower().endswith((".md", ".markdown", ".rst", ".txt")):
        return [(i, line.strip()) for i, line in enumerate(lines, 1) if line.startswith("#")]
    return [(i, line.strip()[:120]) for i, line in enumerate(lines, 1) if _DEF_LINE.match(line)]


def outline(rel: str, text: str) -> str:
    lines = text.splitlines()
    entries = outline_entries(rel, text)
    head = "\n".join(f"{i:4} | {line}" for i, line in enumerate(lines[:HEAD_LINES], 1))
    shown = "\n".join(f"{i:4} : {entry}" for i, entry in entries[:OUTLINE_MAX])
    more = f"\n     … {len(entries) - OUTLINE_MAX} more" if len(entries) > OUTLINE_MAX else ""
    return (f"{rel} ({len(lines)} lines: large, so its outline first. Read only the part you need: read_file with "
            f"start and end, e.g. start={entries[0][0] if entries else 1} end="
            f"{min(len(lines), (entries[0][0] if entries else 1) + 60)}.)\n"
            f"First lines:\n{head}\n"
            + (f"Outline (line : definition):\n{shown}{more}" if entries else "(no definitions found: read a part)"))


def search(ws: Workspace, pattern: str, path: str = ".") -> str:
    base = ws.path(path)
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    hits: list[str] = []
    files = [base] if base.is_file() else [Path(d) / f for d, ds, fs in os.walk(base)
                                           for f in fs if not any(s in Path(d).parts for s in SKIP_DIRS)]
    for f in sorted(files):
        if is_secret_path(f) and not f.name.lower().endswith((".example", ".sample", ".template")):
            continue  # E-131: a search never prints a key from .env or a credentials file
        try:
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{ws.rel(f)}:{n}: {line.strip()[:160]}")
                    if len(hits) >= 60:
                        return "\n".join(hits) + "\n… (more matches not shown)"
        except OSError:
            continue
    return "\n".join(hits) if hits else f"No matches for '{pattern}'."


def make_dir(ws: Workspace, path: str) -> str:
    """Create a folder (and its parents) inside the workspace. Without it the model tried `mkdir` in the shell,
    was refused, and told the user it could not create folders (2026-11-06 session)."""
    full = ws.path(path)
    ws.check_writable(full / "x")
    existed = full.is_dir()
    full.mkdir(parents=True, exist_ok=True)
    return f"{'Folder already exists' if existed else 'Created folder'}: {ws.rel(full)}"


def syntax_note(rel: str, text: str) -> str:
    """A warning when a written .py / .json / .toml file does not parse, so the model fixes it right away
    (2026-11-06: CodeMitra wrote level.toml as Markdown bullets)."""
    suffix = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    from app.core import plans
    if plans.is_plan_file(rel):  # a plan CodeMitra writes must run with /run (D-055)
        return plans.write_note(rel, text)
    try:
        if suffix == "py":
            compile(text, rel, "exec")
        elif suffix == "json":
            import json
            json.loads(text)
        elif suffix == "toml":
            import tomllib
            tomllib.loads(text)
        else:
            return ""
    except SyntaxError as exc:
        return f"\n⚠ {rel} is not valid Python: line {exc.lineno}: {exc.msg}. Fix it before going on."
    except ValueError as exc:  # json.JSONDecodeError and tomllib.TOMLDecodeError are ValueErrors
        kind = "JSON" if suffix == "json" else "TOML"
        return f"\n⚠ {rel} is not valid {kind}: {exc}. Fix it before going on."
    if suffix == "py":  # parses: now the errors that crash it at run time (A2 / E4)
        problems = flake(text, rel)
        if problems:
            shown = "; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else "")
            return f"\n⚠ {rel} will likely fail when it runs: {shown}. Fix these before going on."
    return ""


# Errors that crash a program when it runs (E4: most brick-breaker crashes were these); unused imports etc. are noise.
_RUNTIME_ERRORS = ("UndefinedName", "UndefinedLocal", "UndefinedExport", "ReturnOutsideFunction",
                   "YieldOutsideFunction", "ContinueOutsideLoop", "BreakOutsideLoop", "DuplicateArgument")


def flake(text: str, rel: str) -> list[str]:
    """`line N: message` for errors pyflakes finds that would crash at run time; [] if clean or pyflakes is missing."""
    try:
        import ast

        from pyflakes import checker
    except ImportError:
        return []
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: {exc.msg}"]
    w = checker.Checker(tree, filename=rel)
    out = []
    for m in sorted(w.messages, key=lambda m: m.lineno):
        if type(m).__name__ in _RUNTIME_ERRORS:
            out.append(f"line {m.lineno}: {m.message % m.message_args}")
    return out


def check_code(ws: Workspace, path: str = ".") -> str:
    """Quick check of Python files for errors that crash at run time (undefined names, variables used before
    assignment, syntax), before running the program (A2 / E4)."""
    base = ws.path(path)
    files = [base] if base.is_file() else [Path(d) / f for d, ds, fs in os.walk(base)
                                           if not any(s in Path(d).parts for s in SKIP_DIRS)
                                           for f in fs if f.endswith(".py")]
    files = sorted(files)[:300]
    found = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found += [f"{ws.rel(f)}: {p}" for p in flake(text, ws.rel(f))]
    if not files:
        return f"No Python files under '{path}'."
    if not found:
        return f"✓ No run-time errors found in {len(files)} Python file{'s' if len(files) != 1 else ''}."
    more = f"\n… {len(found) - 40} more" if len(found) > 40 else ""
    return f"Found {len(found)} likely run-time error(s):\n" + "\n".join(found[:40]) + more


# Frames outside the project: installed packages, the standard library (Windows: ...\Python312\Lib\json\...,
# uv: ...\cpython-3.12-windows-x86_64-none\Lib\...; POSIX: /usr/lib/python3.12/...), frozen modules (E-059).
_LIBRARY_FRAME = re.compile(r"site-packages|dist-packages|python[^\\/]*[\\/]lib[\\/]|[\\/]lib[\\/]python|<frozen",
                            re.IGNORECASE)


def crash_hint(output: str) -> str:
    """When a program crashed with a traceback: where and why, and what to do next (E4)."""
    if "Traceback (most recent call last)" not in (output or ""):
        return ""
    locs = re.findall(r'File "([^"]+)", line (\d+)', output)
    last = next((ln.strip() for ln in reversed(output.strip().splitlines())
                 if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt)\b", ln.strip())), "")
    where = ""
    for f, n in reversed(locs):  # the deepest frame in the project, not in a library
        if not _LIBRARY_FRAME.search(f):
            where = f"{os.path.basename(f)} line {n}"
            break
    return (f"\n\n⚠ It crashed ({where + ': ' if where else ''}{last or 'see the traceback'}). Fix this before running "
            "it again; check_code or run_tests would have caught it first.")


def append_file(ws: Workspace, path: str, content: str) -> str:
    """Add content to the end of a file written or read this turn: long files in parts (E3, E-044)."""
    full = ws.path(path)
    ws.check_writable(full)
    rel = ws.rel(full)
    if not full.is_file():
        raise ToolError(f"'{rel}' does not exist. Create it with write_file first, then append the rest.")
    if rel not in ws.seen:
        raise ToolError(f"Read '{rel}' (or write it) before appending to it.")
    if full.stat().st_mtime != ws.seen[rel]:
        raise ToolError(f"'{rel}' changed since you read it. Read it again, then append.")
    old = full.read_text(encoding="utf-8")
    sep = "" if (not old or old.endswith("\n")) else "\n"
    text = old + sep + str(content)
    _commit(ws, full, text)
    # the whole file, as write_file does: syntax / run-time errors for .py, the /run check for plans (E-060)
    return (f"Appended {len(str(content).splitlines())} lines to {rel} (now {len(text.splitlines())} lines)."
            + syntax_note(rel, text))


def write_file(ws: Workspace, path: str, content: str) -> str:
    full = ws.path(path)
    ws.check_writable(full)
    rel = ws.rel(full)
    if full.exists() and rel not in ws.seen:
        raise ToolError(f"'{rel}' already exists. Read it first, then use edit_file (or write_file to replace it).")
    if isinstance(content, (dict, list)):
        import json
        content = json.dumps(content, indent=2) + "\n"
    if full.is_file():  # D-078 #4: a small model rewriting a whole file often drops most of it
        old_lines = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
        new_lines = len(str(content).splitlines())
        if old_lines >= SHRINK_MIN_LINES and new_lines < old_lines * SHRINK_RATIO:
            raise ToolError(f"write_file would replace '{rel}' ({old_lines} lines) with {new_lines} lines and drop "
                            f"most of it. Use edit_file to change part of it; write_file replaces the whole file.")
    _commit(ws, full, str(content))
    return f"Wrote {rel} ({len(str(content).splitlines())} lines)." + syntax_note(rel, str(content))


def _loose(s: str) -> str:
    return "\n".join(line.strip() for line in s.strip().splitlines())


def edit_file(ws: Workspace, path: str, old: str, new: str) -> str:
    full = ws.path(path)
    ws.check_writable(full)
    rel = ws.rel(full)
    if not full.is_file():
        raise ToolError(f"'{rel}' does not exist. Use write_file to create it.")
    if rel not in ws.seen:
        raise ToolError(f"Read '{rel}' with read_file before editing it.")
    if full.stat().st_mtime != ws.seen[rel]:
        raise ToolError(f"'{rel}' changed since you read it. Read it again, then edit.")
    text = full.read_text(encoding="utf-8")
    if old and text.count(old) == 1:
        text = text.replace(old, new, 1)
    elif old and text.count(old) > 1:
        raise ToolError(f"The old text appears {text.count(old)} times in '{rel}'. Include more lines to make it unique.")
    else:
        # forgiving match: compare lines ignoring indentation and trailing spaces
        lines = text.splitlines()
        want = _loose(old).splitlines()
        if not want:
            raise ToolError("old is empty. Give the exact lines to replace.")
        starts = [i for i in range(len(lines) - len(want) + 1)
                  if [line.strip() for line in lines[i:i + len(want)]] == want]
        if len(starts) != 1:
            raise ToolError(f"Could not find the old text in '{rel}'"
                            + (" exactly once" if starts else "") + ". Read the file again and copy the lines exactly.")
        i = starts[0]
        indent = re.match(r"\s*", lines[i]).group(0)
        first_new_indent = re.match(r"\s*", new.splitlines()[0]).group(0) if new.strip() else ""
        new_lines = [indent + line[len(first_new_indent):] if line.startswith(first_new_indent) else line
                     for line in new.splitlines()]
        lines[i:i + len(want)] = new_lines
        text = "\n".join(lines) + "\n"
    _commit(ws, full, text)
    return f"Edited {rel}." + syntax_note(rel, text)


def rollback(entries: list[dict]) -> int:
    """Undo journal entries (newest first): restore old content, delete files that did not exist. Returns count."""
    n = 0
    for e in reversed(entries):
        p = Path(e["path"])
        try:
            if e.get("existed"):
                p.write_text(e.get("before") or "", encoding="utf-8")
            elif p.exists():
                p.unlink()
            n += 1
        except OSError:
            continue
    return n


_PYTEST_CHECK: dict[str, bool] = {}


SHRINK_MIN_LINES = 20   # D-078 #4: write_file refuses to shrink a file this long ...
SHRINK_RATIO = 0.5      # ... to under half its lines (an accidental whole-file overwrite)
_TEST_SKIP = {".git", ".codemitra", ".mitra", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}


def has_tests(root: Path, max_depth: int = 4) -> bool:
    """D-078 #2: the project has pytest-style tests (test_*.py or *_test.py, at most 4 folders deep)."""
    root = Path(root)
    for d, dirs, names in os.walk(root):
        rel = Path(d).relative_to(root)
        if len(rel.parts) >= max_depth:
            dirs[:] = []
        dirs[:] = [x for x in dirs if x not in _TEST_SKIP and not x.startswith(".")]
        if any(n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py")) for n in names):
            return True
    return False


_PROJECT_MARKS = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "conftest.py", "tests", "test")


def is_multi_project(root: Path) -> bool:
    """A folder of projects: the root has no project files of its own and at least one top-level folder does
    (mitra-try: brick-breaker/tests). The snake game's snake/ and web/ are parts of one project, not projects."""
    root = Path(root)
    if any((root / m).exists() for m in _PROJECT_MARKS):
        return False
    try:
        tops = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name not in _TEST_SKIP]
    except OSError:
        return False
    return any(any((d / m).exists() for m in _PROJECT_MARKS) for d in tops)


def project_dir(root: Path, path: str) -> str:
    """E-126 (live 2026-11-13): mitra-try holds two projects, brick-breaker/ and neon_chomp/. After CodeMitra wrote
    neon_chomp files, the tests that ran were brick-breaker's ("37 passed"), so broken code looked green. The project
    a file belongs to: its top-level folder when the workspace root is not itself one project (no tests or project
    files of its own at the top); '' when the root is the project."""
    root = Path(root).resolve()
    if any((root / m).exists() for m in _PROJECT_MARKS) or not is_multi_project(root):
        return ""
    try:
        p = (root / path).resolve()
        rel = (p if p.is_dir() else p.parent).relative_to(root)
    except (ValueError, OSError):
        return ""
    return rel.parts[0] if rel.parts and (root / rel.parts[0]).is_dir() else ""


def _has_pytest(python: str) -> bool:
    if python not in _PYTEST_CHECK:
        try:
            p = subprocess.run([python, "-c", "import pytest"], capture_output=True, timeout=30)
            _PYTEST_CHECK[python] = p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _PYTEST_CHECK[python] = False
    return _PYTEST_CHECK[python]


def project_python(root: Path) -> str:
    """The Python a test command's `python` should mean (E-028).

    Installed as a command, CodeMitra runs in its own private Python without the project's packages, so tests failed
    with "No module named pytest". Use, in order: the project's .venv / venv, then `python` on PATH if it has
    pytest, then CodeMitra's own Python (which ships pytest for small projects without a venv).
    """
    import shutil

    for venv in (".venv", "venv", "env"):
        for exe in ("Scripts/python.exe", "bin/python"):
            cand = Path(root) / venv / exe
            if cand.is_file():
                return str(cand)
    on_path = shutil.which("python") or shutil.which("python3")
    if on_path and "WindowsApps" not in on_path and _has_pytest(on_path):
        return on_path
    return sys.executable


_PYTEST_SUMMARY = re.compile(r"\b\d+ (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b|no tests ran")


def test_summary(out: str) -> str:
    """pytest's result line ("2 failed, 30 passed in 1.2s"), not the last line (often a warning, E-047)."""
    for line in reversed((out or "").splitlines()):
        if _PYTEST_SUMMARY.search(line):
            return line.strip().strip("=").strip()
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


FAIL_TAIL_LINES = 30   # quick win 4: of a long failing run the model sees the first failure's last lines
SHORT_OUTPUT_LINES = 40  # shorter output is shown as it is
_SECTION = re.compile(r"^_{3,} .+ _{3,}$")


def failing_part(out: str, ok: bool) -> str:
    """What the model needs from a long test run (the 'context rot' finding: long, similar-looking output hurts small
    models): a pass is its result line; a pytest failure is the first failure's last FAIL_TAIL_LINES lines (the
    assertion and where it failed), the FAILED lines and the result line; other output its last lines. Short output
    is unchanged; the full output is kept in the spill file."""
    lines = (out or "").splitlines()
    if len(lines) <= SHORT_OUTPUT_LINES:
        return out
    summary = test_summary(out)
    if ok:
        return summary or lines[-1]
    starts = [i for i, ln in enumerate(lines) if _SECTION.match(ln)]
    if starts:
        first = starts[0]
        end = next((i for i in range(first + 1, len(lines)) if _SECTION.match(lines[i]) or lines[i].startswith("==")),
                   len(lines))
        block = lines[first:end]
        if len(block) > FAIL_TAIL_LINES + 1:
            block = [block[0], f"… {len(block) - 1 - FAIL_TAIL_LINES} lines cut …"] + block[-FAIL_TAIL_LINES:]
        failed = [ln for ln in lines if ln.startswith(("FAILED ", "ERROR "))]
        more = f"({len(starts) - 1} more failure(s) not shown)" if len(starts) > 1 else ""
        return "\n".join(block + [""] + failed[:20] + [x for x in (more, summary) if x])
    cut = len(lines) - FAIL_TAIL_LINES
    return f"… {cut} lines cut …\n" + "\n".join(lines[-FAIL_TAIL_LINES:])


@dataclass
class TestRun:
    passed: bool
    summary: str       # last line, e.g. "3 failed, 9 passed in 0.4s"
    output: str        # what the model sees (head + tail)
    full_path: str = ""
    seconds: float = 0.0


def test_args(ws: Workspace, path: str = "", keyword: str = "", first_failure: bool = False) -> list[str]:
    """Extra pytest arguments for one file / a selection (A3); paths must stay inside the workspace."""
    extra = []
    if path:
        extra.append(ws.rel(ws.path(path)))
    if keyword:
        extra += ["-k", str(keyword)]
    if first_failure:
        extra += ["-x", "--tb=long"]
    return extra


def run_tests(ws: Workspace, command: str | None = None, extra: list[str] | None = None,
              folder: str = "") -> TestRun:
    """`folder`: run inside one project folder of the workspace (E-126), as you would run that project's tests."""
    cmd = command or ws.test_command
    cwd = ws.path(folder) if folder else ws.root
    args = cmd.split()
    if extra:
        if "pytest" not in cmd:
            raise ToolError(f"The test command '{cmd}' is not pytest: run_tests cannot select a file or keyword.")
        args += extra
    if args and args[0] in ("python", "python3", "py"):
        args[0] = ws.python or project_python(cwd if any((cwd / v).is_dir() for v in (".venv", "venv", "env")) else ws.root)
    t0 = time.monotonic()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=TEST_TIMEOUT_S,
                              encoding="utf-8", errors="replace", env=env)
        out, ok = (proc.stdout + proc.stderr).strip(), proc.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = f"Tests timed out after {TEST_TIMEOUT_S}s.", False
    except OSError as exc:
        out, ok = f"Could not run '{cmd}': {exc}", False
    secs = time.monotonic() - t0
    last = test_summary(out) or ("passed" if ok else "failed")
    full_path = ""
    if ws.spill_dir is not None:
        ws.spill_dir.mkdir(parents=True, exist_ok=True)
        f = ws.spill_dir / f"tests-{int(time.time() * 1000)}.txt"
        f.write_text(out, encoding="utf-8")
        full_path = str(f)
    shown = failing_part(out, ok)
    if len(shown) > MAX_OUTPUT_CHARS:
        head, tail = shown[: MAX_OUTPUT_CHARS // 3], shown[-(MAX_OUTPUT_CHARS * 2 // 3):]
        shown = f"{head}\n… {len(shown) - len(head) - len(tail)} characters cut …\n{tail}"
    return TestRun(ok, last, shown, full_path, secs)


# ── tool specs for the model (kept short: the whole prompt stays under ~3K tokens) ──────────────────────────

TOOL_SPECS = [
    {"name": "list_files", "description": "List files in the workspace (or a folder).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "read_file", "description": "Read a text file with line numbers (large files: an outline first, then "
                                        "read a part with start/end). Read a file before editing it. Outside the "
                                        "project: its full path (asks the user).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start": {"type": "integer"},
                                                     "end": {"type": "integer"}}, "required": ["path"]}},
    {"name": "search", "description": "Find a regex in files; returns file:line: text.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                    "required": ["pattern"]}},
    {"name": "package_info", "description": "An installed library's version and names; check before using its API.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "make_dir", "description": "Create a folder (and parent folders) in the project.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Create a file, or replace a file you have read, with the full content.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace one exact block of lines `old` with `new` in a file you have read.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"},
                                                     "new": {"type": "string"}}, "required": ["path", "old", "new"]}},
    {"name": "append_file", "description": "Add content to the end of a file you wrote or read. Write long files "
     "in parts: write_file with the first ~150 lines, then append_file for the rest.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}},
    {"name": "check_code", "description": "Find Python errors that crash at run time (undefined names, unbound "
     "variables). Use before running a program.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "run_tests", "description": "Run the tests (all, or one file / a keyword; first_failure stops at the "
     "first failure with the full traceback). Returns pass/fail and the output.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "keyword": {"type": "string"},
                                                     "first_failure": {"type": "boolean"}}}},
    {"name": "finish", "description": "Call when the tests pass, with a one-line summary of what you did.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]
