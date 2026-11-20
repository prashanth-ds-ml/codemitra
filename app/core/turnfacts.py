"""Stage 1 (ROADMAP): the facts a turn's record needs that the chat loop does not keep by itself.

- snapshot(): the project's files (path -> short hash) at turn start and end, so a replay can check it starts from
  the same files, and changes made by commands (a script that writes an .xlsx) are seen, not only tool writes
- change_rows(): one `change` row per file written in the turn: the diff and before / after hashes
- mistake_tags(): a fixed list of what went wrong, set by rules (no model call)

Pure functions over paths and plain data; never raise into the chat.
"""
from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

SKIP_DIRS = {".git", ".codemitra", "node_modules", "__pycache__", ".venv", "venv", "env", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", ".idea", ".vscode", "dist", "build", ".tox", ".next"}
MAX_FILES = 500            # beyond this the snapshot keeps only the tree hash and the count
MAX_HASH_BYTES = 5 * 2**20  # bigger files: hashed by size + mtime, not content
DIFF_CHARS = 8000

# The fixed mistake list (Stage 1.8). Rules set them at turn end; a model label, when added, says source "model".
TAGS = {
    "false_done": "the reply claimed something the turn's results contradict",
    "no_action": "a change was asked, nothing was changed or run",
    "tests_fail": "the last test run of the turn failed",
    "broken_code": "the last run crashed (syntax, name or import error)",
    "loop": "the repeat guard stopped repeated calls",
    "tool_misuse": "3 or more tool calls failed or were malformed",
    "stall": "the model sent nothing for too long",
    "environment": "not the model: a missing package, the remote GPU, the connection",
    "missing_output": "a file the user asked for was not made",
    "script_not_run": "a script was written for a requested file and never run",
}


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def text_hash(text: str | None) -> str | None:
    return None if text is None else _hash_bytes(text.encode("utf-8", errors="replace"))


def snapshot(root: Path, cache: dict | None = None) -> dict:
    """{rel path: hash} of the project's files. `cache` ({path: (size, mtime_ns, hash)}) skips unchanged files.
    More than MAX_FILES: {"_tree": hash of all, "_count": n}."""
    root = Path(root)
    cache = cache if cache is not None else {}
    files: dict[str, str] = {}
    try:
        from app.core import harness as H
        own = os.path.normcase(str(H.home().resolve()))  # CodeMitra's own records: never project files
    except Exception:  # noqa: BLE001
        own = ""
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")
                                 and not (own and os.path.normcase(os.path.realpath(os.path.join(dirpath, d))) == own))
            for name in sorted(filenames):
                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except OSError:
                    continue
                key = str(full)
                hit = cache.get(key)
                if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
                    h = hit[2]
                elif st.st_size > MAX_HASH_BYTES:
                    h = "big-" + _hash_bytes(f"{st.st_size}:{st.st_mtime_ns}".encode())
                else:
                    try:
                        h = _hash_bytes(full.read_bytes())
                    except OSError:
                        continue
                cache[key] = (st.st_size, st.st_mtime_ns, h)
                files[full.relative_to(root).as_posix()] = h
    except OSError:
        pass
    if len(files) > MAX_FILES:
        tree = _hash_bytes("\n".join(f"{k}:{v}" for k, v in files.items()).encode())
        return {"_tree": tree, "_count": len(files)}
    return files


def changed_between(before: dict, after: dict) -> list[str]:
    """Paths added, removed or changed between two snapshots (empty when either is only a tree hash)."""
    if "_tree" in before or "_tree" in after:
        return []
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def change_rows(journal: list[dict], root: Path, before: dict | None = None, after: dict | None = None) -> list[dict]:
    """One row per file the turn changed. Tool writes (the journal) carry a diff; files changed by a command
    (in the snapshots, not in the journal) carry before / after hashes and `via: command`."""
    rows, seen = [], set()
    root = Path(root)
    last: dict[str, dict] = {}
    first: dict[str, dict] = {}
    for e in journal or []:
        if "after" not in e or "path" not in e:
            continue
        first.setdefault(e["path"], e)
        last[e["path"]] = e
    for path, e in last.items():
        old, new = first[path].get("before"), e.get("after")
        try:
            rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            rel = str(path)
        seen.add(rel)
        diff = "".join(difflib.unified_diff((old or "").splitlines(True), (new or "").splitlines(True),
                                            fromfile=f"a/{rel}", tofile=f"b/{rel}", n=2))
        rows.append({"path": str(path), "rel": rel, "via": "tool", "created": old is None,
                     "before": text_hash(old), "after": text_hash(new), "diff": diff[:DIFF_CHARS],
                     "diff_chars": len(diff)})
    if before is not None and after is not None:
        for rel in changed_between(before, after):
            if rel in seen:
                continue
            rows.append({"path": str(root / rel), "rel": rel, "via": "command", "created": rel not in before,
                         "before": before.get(rel), "after": after.get(rel), "diff": ""})
    return rows


def mistake_tags(*, claims_verdict: str, asked_change: bool, did_work: bool, last_test_ok: bool | None,
                 tools: list[tuple[str, bool, str]], kinds: list[str], stop_reason: str = "",
                 outcome: str = "") -> list[str]:
    """The fixed tags (TAGS) that apply to a finished turn, by rules only."""
    tags = []
    if claims_verdict == "false":
        tags.append("false_done")
    if asked_change and not did_work:
        tags.append("no_action")
    if last_test_ok is False:
        tags.append("tests_fail")
    runs = [out for name, _, out in tools if name in ("run_command", "run_tests")]
    if runs and any(e in runs[-1] for e in ("SyntaxError", "NameError", "ImportError", "IndentationError")):
        tags.append("broken_code")
    if {"repeat", "runaway", "loop_guard"} & set(kinds):  # Stage 2.5: the ladder fired
        tags.append("loop")
    failed = sum(1 for _, ok, _ in tools if not ok) + kinds.count("bad_tool_call")
    if failed >= 3:
        tags.append("tool_misuse")
    reason = (stop_reason or "").lower()
    if "stall" in reason or "sent nothing" in reason or "model_error_stall" in kinds:
        tags.append("stall")
    outs = " ".join(out for _, _, out in tools)
    if outcome in ("kaggle_ended", "error") or "ModuleNotFoundError" in outs or "model_error" in kinds:
        tags.append("environment")
    if "missing_output" in kinds:
        tags.append("missing_output")
    # the nudge rows say it happened during the turn; the tag is for how the turn ended (live check 2026-11-18:
    # nudged, then the script ran and made the file)
    if "script_not_run" in kinds and not any(ok for name, ok, _ in tools if name == "run_command"):
        tags.append("script_not_run")
    return tags
