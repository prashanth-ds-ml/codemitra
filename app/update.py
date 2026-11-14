"""`codemitra update` (D-084): every fix reaches friends who cloned CodeMitra.

- **The notice:** once a day the chat asks GitHub for the newest release (2 s at most, silent when offline) and shows
  one line when it is newer than this copy. Only the request goes out; nothing about you. `codemitra update --check
  never` turns it off.
- **The update:** `git pull` in the folder CodeMitra was installed from (setup installs it editable, so the pulled
  code runs at once), then the changelog lines since your version. It never overwrites your own edits there, and
  says when the dependencies changed so the install must run again.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable

REPO = "prashanth-ds-ml/codemitra"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=5"
CHECK_EVERY_S = 24 * 3600
TIMEOUT_S = 2.0
GIT_TIMEOUT_S = 120
SOURCE = Path(__file__).resolve().parents[1]  # the clone CodeMitra runs from
REINSTALL = "uv tool install --reinstall -e . --python 3.12"


def _settings_path() -> Path:
    from app import migrate
    return migrate.resolve_home() / "update.json"


def settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**kw) -> None:
    s = settings() | kw
    p = _settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s), encoding="utf-8")
    except OSError:
        pass


def current_of(src: Path) -> str:
    """A copy's version, read from its own pyproject (the installed metadata can lag behind a pull)."""
    try:
        import tomllib
        return tomllib.loads((src / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, ValueError):
        return ""


def current() -> str:
    return current_of(SOURCE)


def _v(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def newer(a: str, b: str) -> bool:
    """Is version a newer than b? Unknown versions are never newer."""
    return bool(_v(a)) and bool(_v(b)) and _v(a) > _v(b)


def _fetch() -> tuple[str, str] | None:
    """The newest published release (pre-releases count: every CodeMitra release is one): (version, title)."""
    req = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                         "User-Agent": "codemitra-update-check"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        rows = json.loads(r.read().decode("utf-8"))
    for row in rows:
        if not row.get("draft") and row.get("tag_name"):
            return row["tag_name"].lstrip("v"), row.get("name") or ""
    return None


def latest(fetch: Callable[[], tuple[str, str] | None] = _fetch, now: float | None = None) -> tuple[str, str] | None:
    """The newest release, asked at most once a day; offline or slow → the last answer (or None)."""
    s, now = settings(), time.time() if now is None else now
    if s.get("check") == "never" or os.environ.get("CODEMITRA_NO_UPDATE_CHECK"):
        return None
    if now - s.get("checked", 0) >= CHECK_EVERY_S:
        try:
            got = fetch()
        except Exception:
            got = None
        if got:
            save_settings(checked=now, latest=got[0], title=got[1])
            return got
        save_settings(checked=now)  # offline: try again tomorrow, never slow every start
    return (s["latest"], s.get("title", "")) if s.get("latest") else None


def notice(mine: str | None = None, **kw) -> str | None:
    """One line for the chat's header when a newer release exists."""
    mine = current() if mine is None else mine
    got = latest(**kw)
    if not got or not newer(got[0], mine):
        return None
    title = re.sub(r"^v?[\d.]+\s*[:·-]\s*", "", got[1]).strip()
    return f"v{got[0]} is out" + (f": {title}" if title else "") + " · run `codemitra update`"


# ── the update itself ──────────────────────────────────────────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path = SOURCE) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _deps(src: Path) -> str:
    try:
        text = (src / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    return m.group(1) if m else ""


def changes_since(old: str, src: Path = SOURCE) -> str:
    """The CHANGELOG sections newer than `old`, as they are written."""
    try:
        text = (src / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    out = []
    for part in re.split(r"(?m)^(?=## \[)", text):
        m = re.match(r"## \[([^\]]+)\]", part)
        if m and newer(m.group(1), old):
            out.append(part.strip())
    return "\n\n".join(out)


def update(git: Callable[..., tuple[int, str]] = _git, src: Path = SOURCE) -> tuple[bool, str]:
    """Pull the newest CodeMitra into the clone it runs from. (ok, what happened, for the user)."""
    if not (src / ".git").exists():
        return False, f"{src} is not a git clone; download the newest release from github.com/{REPO}"
    code, out = git(["status", "--porcelain", "--untracked-files=no"], src)
    if code != 0:
        return False, f"git could not read {src}: {out[:200]}"
    if out.strip():
        return False, (f"you changed files in {src}, so nothing was pulled (your edits are kept). Save them "
                       "elsewhere or `git stash`, then run `codemitra update` again")
    old, deps = current_of(src), _deps(src)
    code, out = git(["pull", "--ff-only", "origin", "main"], src)
    if code != 0:
        return False, f"the pull failed: {out[:300]}"
    new = current_of(src)
    if not newer(new, old):
        return True, f"already the newest (v{old})"
    msg = f"updated v{old} → v{new}; the next `codemitra` you start runs it"
    if _deps(src) != deps:
        msg += f"\nIts dependencies changed: in {src} run `{REINSTALL}` (or the setup script again)"
    notes = changes_since(old, src)
    return True, msg + (f"\n\n{notes}" if notes else "")
