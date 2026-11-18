"""Facts recorded with every turn so before/after comparisons are fair (item 0, SELF_IMPROVEMENT.md section 4):
which CodeMitra code ran, and the machine's state. Read once per process where it is costly; never raises."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

CODEMITRA_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """Short git commit of the CodeMitra repo, `-dirty` with uncommitted changes to tracked files; `unknown` without git."""
    try:
        head = subprocess.run(["git", "-C", str(CODEMITRA_ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5)
        if head.returncode != 0 or not head.stdout.strip():
            return "unknown"
        dirty = subprocess.run(["git", "-C", str(CODEMITRA_ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5)
        return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def ram_free_gb() -> float | None:
    try:
        import psutil
        return round(psutil.virtual_memory().available / 2**30, 1)
    except Exception:
        return None


@lru_cache(maxsize=1)
def machine() -> dict:
    """Stage 1.7: the machine a session ran on: OS, GPU (name, memory), CPU count, total RAM, local Ollama version.
    Missing facts are empty strings / None, never an error. A Kaggle session also records `remote`."""
    import os
    import platform
    out: dict = {"os": f"{platform.system()} {platform.release()}".strip(), "cpus": os.cpu_count(),
                 "ram_gb": None, "gpu": "", "ollama_version": ""}
    try:
        import psutil
        out["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            out["gpu"] = r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
        words = (r.stdout + r.stderr).split()
        out["ollama_version"] = next((w for w in reversed(words) if w[:1].isdigit()), "")
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def ollama_timings(reply) -> dict:
    """Prompt processing, generation and model-load time from Ollama's reply metadata (seconds; A5).
    A large `load_s` means Ollama (re)loaded the model for this call."""
    meta = getattr(reply, "response_metadata", None) or {}
    out = {}
    for key, name in (("prompt_eval_count", "prompt_tokens"), ("eval_count", "gen_tokens")):
        if meta.get(key) is not None:
            out[name] = int(meta[key])
    for key, name in (("prompt_eval_duration", "prompt_s"), ("eval_duration", "gen_s"),
                      ("load_duration", "load_s"), ("total_duration", "total_s")):
        if meta.get(key) is not None:
            out[name] = round(int(meta[key]) / 1e9, 2)
    return out
