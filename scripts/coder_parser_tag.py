"""Quick win 3: a second tag of a Qwen3.5 model that uses Ollama's qwen3-coder renderer and parser.

ollama#14493: Qwen3.5 was trained on the Qwen3-Coder XML tool-call format, but Ollama's `qwen3.5` renderer and parser
use a JSON pipeline; one tester's tool calls worked 4/5 instead of 2/5 with `RENDERER qwen3-coder` / `PARSER
qwen3-coder`. This makes that variant next to the original (same weights, no download, no extra disk) so the two can be
compared on the practice set:

    python scripts/coder_parser_tag.py qwen3.5:latest          # -> qwen3.5-coderparse:latest
    codemitra practice --n 20 --repeats 3 --model qwen3.5-coderparse:latest

On Kaggle the notebook makes the same tag after the download (remote/kaggle/build_notebook.py).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_S = 120


def variant_name(model: str) -> str:
    name, _, tag = model.partition(":")
    return f"{name}-coderparse:{tag or 'latest'}"


def variant_modelfile(modelfile: str) -> str:
    """The model's Modelfile with RENDERER / PARSER set to qwen3-coder (added when missing)."""
    out = re.sub(r"(?m)^(RENDERER|PARSER) .*$", lambda m: f"{m.group(1)} qwen3-coder", modelfile)
    for key in ("RENDERER", "PARSER"):
        if not re.search(rf"(?m)^{key} ", out):
            out = re.sub(r"(?m)^(FROM .*)$", rf"\1\n{key} qwen3-coder", out, count=1)
    return out


def main(model: str) -> int:
    shown = subprocess.run(["ollama", "show", "--modelfile", model], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    if shown.returncode != 0:
        print(f"ollama show failed: {shown.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    name = variant_name(model)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "Modelfile"
        f.write_text(variant_modelfile(shown.stdout), encoding="utf-8")
        made = subprocess.run(["ollama", "create", name, "-f", str(f)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    if made.returncode != 0:
        print(f"ollama create failed: {(made.stderr or made.stdout).strip()[-300:]}", file=sys.stderr)
        return 1
    print(f"made {name} (qwen3-coder renderer and parser, same weights as {model})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:latest"))
