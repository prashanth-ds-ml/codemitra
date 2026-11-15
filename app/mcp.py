"""MCP client for CodeMitra: connect to any MCP server (stdio or Streamable HTTP) with the official SDK.

Config is the standard ``mcpServers`` JSON used by Claude Code, Cursor and server READMEs:

* built-in defaults (``DEFAULT_SERVERS`` below)
* ``~/.codemitra/mcp.json`` (yours; trusted)
* ``<project>/.codemitra/mcp.json`` (the project's; ignored until you run ``/mcp trust``, and again after it changes)

CodeMitra-only keys per server: ``enabled``, ``timeout_s``, ``connect_timeout_s``, ``allow`` / ``ask`` (tool-name patterns;
a tool runs freely only if it matches ``allow`` and not ``ask``), ``description``, ``descriptions`` (short text per
tool) and ``env_commands`` (env vars filled from a command, e.g. ``gh auth token``; never logged).

Design notes (D-028): one long-lived session per server in a background event loop (each in its own task, because the
SDK's stdio transport must be opened and closed in the same task); every call has a timeout and is logged with secrets
masked; big results are trimmed to head/tail with the full text saved to a file; write tools always need approval and
are refused when no one can approve (headless runs).
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Callable

# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_CONNECT_TIMEOUT_S = 120.0  # first start may download the server package
MAX_RESULT_CHARS = 6000
HEAD_CHARS = 3500
TAIL_CHARS = 1500

DEFAULT_SERVERS: dict[str, dict[str, Any]] = {
    "git": {
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "${WORKSPACE}"],
        "description": "Git history of this project: status, diffs, log, show a commit",
        "allow": ["git_status", "git_diff*", "git_log", "git_show", "git_branch"],
    },
    "github": {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"},
        "env_commands": {"GITHUB_TOKEN": "gh auth token"},
        "description": "GitHub: issues, pull requests, code search, CI runs",
        "allow": ["get_*", "list_*", "search_*"],
    },
    "context7": {
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "description": "Up-to-date docs and code examples for libraries and frameworks",
        "allow": ["*"],
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE}"],
        "description": "Search for files and read them inside this project",
        "allow": ["read_*", "list_*", "search_files", "directory_tree", "get_file_info"],
        "enabled": False,  # duplicates CodeMitra's own read / list / search tools: confuses a small model (D-049)
    },
    "semgrep": {
        "command": "uvx",
        "args": ["semgrep", "mcp"],
        "description": "Code review: scan code for security issues and bug patterns",
        "allow": ["*"],
    },
    "fetch": {
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "description": "Fetch a web page and return it as markdown",
        "allow": ["fetch"],
        "enabled": False,
    },
    "aws-docs": {
        "command": "uvx",
        "args": ["awslabs.aws-documentation-mcp-server@latest"],
        "description": "Search and read AWS documentation",
        "allow": ["*"],
        "enabled": False,
    },
    "serena": {
        "command": "uvx",
        "args": ["--from", "git+https://github.com/oraios/serena", "serena", "start-mcp-server",
                 "--project", "${WORKSPACE}"],
        "description": "Code navigation by symbol: definitions, references, file overviews",
        "allow": ["find_*", "get_*", "list_*", "search_*", "read_*"],
        "enabled": False,
    },
}

_SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|auth|credential)", re.IGNORECASE)
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ─── Paths ───────────────────────────────────────────────────────────────────

def user_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CODEMITRA_HOME") or pathlib.Path.home() / ".codemitra")


def user_config_path() -> pathlib.Path:
    return user_dir() / "mcp.json"


def project_config_path(workspace: str | os.PathLike) -> pathlib.Path:
    return pathlib.Path(workspace) / ".codemitra" / "mcp.json"


def _trust_path() -> pathlib.Path:
    return user_dir() / "trusted_mcp.json"


def _cache_path() -> pathlib.Path:
    return user_dir() / "mcp_tools_cache.json"


def claude_config_paths(workspace: str | os.PathLike) -> list[pathlib.Path]:
    override = os.environ.get("CODEMITRA_CLAUDE_CONFIG")
    user_file = pathlib.Path(override) if override else pathlib.Path.home() / ".claude.json"
    return [user_file, pathlib.Path(workspace) / ".mcp.json"]


# ─── Specs ───────────────────────────────────────────────────────────────────

@dataclass
class ServerSpec:
    name: str
    kind: str = "stdio"  # "stdio" | "http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    env_commands: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_s: float = DEFAULT_TIMEOUT_S
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    description: str = ""
    descriptions: dict[str, str] = field(default_factory=dict)
    source: str = "default"  # "default" | "user" | "project"
    trusted: bool = True

    @property
    def usable(self) -> bool:
        return self.enabled and self.trusted

    def key(self) -> str:
        """Stable hash of what defines the server (not its secrets), used for the tool cache."""
        raw = json.dumps([self.kind, self.command, self.args, self.url], sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    def arg_summary(self) -> str:
        props = (self.input_schema or {}).get("properties") or {}
        required = set((self.input_schema or {}).get("required") or [])
        return ", ".join(f"{k}{'*' if k in required else ''}" for k in props) or "none"


@dataclass
class CallResult:
    server: str
    tool: str
    ok: bool
    text: str
    full_output_path: str | None = None
    approved: bool | None = None
    seconds: float = 0.0


def _spec_from_entry(name: str, entry: dict[str, Any], source: str) -> ServerSpec:
    kind = str(entry.get("type") or ("http" if entry.get("url") else "stdio")).lower()
    if kind in {"streamable-http", "streamable_http", "sse"}:
        kind = "http"
    return ServerSpec(
        name=name,
        kind=kind,
        command=str(entry.get("command") or ""),
        args=[str(a) for a in entry.get("args") or []],
        env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
        cwd=entry.get("cwd"),
        url=str(entry.get("url") or ""),
        headers={str(k): str(v) for k, v in (entry.get("headers") or {}).items()},
        env_commands={str(k): str(v) for k, v in (entry.get("env_commands") or {}).items()},
        enabled=bool(entry.get("enabled", True)),
        timeout_s=float(entry.get("timeout_s", DEFAULT_TIMEOUT_S)),
        connect_timeout_s=float(entry.get("connect_timeout_s", DEFAULT_CONNECT_TIMEOUT_S)),
        allow=[str(p) for p in entry.get("allow") or []],
        ask=[str(p) for p in entry.get("ask") or []],
        description=str(entry.get("description") or ""),
        descriptions={str(k): str(v) for k, v in (entry.get("descriptions") or {}).items()},
        source=source,
    )


def _read_servers_file(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    return {str(k): v for k, v in servers.items() if isinstance(v, dict)}


def _file_hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _load_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def is_project_trusted(workspace: str | os.PathLike) -> bool:
    path = project_config_path(workspace)
    if not path.is_file():
        return True
    trusted = _load_json(_trust_path(), {})
    return trusted.get(str(pathlib.Path(workspace).resolve())) == _file_hash(path)


def trust_project(workspace: str | os.PathLike) -> None:
    trusted = _load_json(_trust_path(), {})
    trusted[str(pathlib.Path(workspace).resolve())] = _file_hash(project_config_path(workspace))
    _save_json(_trust_path(), trusted)


def discover(workspace: str | os.PathLike | None = None) -> list[ServerSpec]:
    """All configured servers: defaults, then the user file, then the project file (merged per server)."""
    merged: dict[str, tuple[dict[str, Any], str]] = {}
    if not os.environ.get("CODEMITRA_MCP_NO_DEFAULTS"):
        for name, entry in DEFAULT_SERVERS.items():
            merged[name] = (dict(entry), "default")
    for name, entry in _read_servers_file(user_config_path()).items():
        base = merged.get(name, ({}, "user"))[0]
        merged[name] = ({**base, **entry}, "user")
    project_trusted = True
    if workspace is not None:
        project_trusted = is_project_trusted(workspace)
        for name, entry in _read_servers_file(project_config_path(workspace)).items():
            base = merged.get(name, ({}, "project"))[0]
            merged[name] = ({**base, **entry}, "project")
    specs = []
    for name, (entry, source) in merged.items():
        spec = _spec_from_entry(name, entry, source)
        spec.trusted = source != "project" or project_trusted
        specs.append(spec)
    return specs


def find(servers: list[ServerSpec], query: str) -> ServerSpec | None:
    q = (query or "").strip().lower()
    for server in servers:
        if server.name.lower() == q:
            return server
    return None


# ─── Approval, masking, expansion ────────────────────────────────────────────

def needs_approval(spec: ServerSpec, tool: str) -> bool:
    """A tool runs freely only if it matches an `allow` pattern and no `ask` pattern."""
    if any(fnmatch.fnmatchcase(tool, p) for p in spec.ask):
        return True
    return not any(fnmatch.fnmatchcase(tool, p) for p in spec.allow)


def mask(value: Any, secrets: set[str] | None = None) -> Any:
    secrets = {s for s in (secrets or set()) if len(s) >= 6}
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) else mask(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "***")
        return value
    return value


_env_command_cache: dict[str, str] = {}


def _run_env_command(command: str) -> str:
    if command in _env_command_cache:
        return _env_command_cache[command]
    parts = shlex.split(command, posix=os.name != "nt")
    # Windows (non-POSIX) splitting keeps the quotes around a quoted path; drop them.
    parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
    exe = shutil.which(parts[0]) or parts[0]
    proc = subprocess.run([exe, *parts[1:]], capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(f"env command failed: {parts[0]} (exit {proc.returncode})")
    value = proc.stdout.strip()
    _env_command_cache[command] = value
    return value


@dataclass
class _Resolved:
    command: str
    args: list[str]
    env: dict[str, str]
    url: str
    headers: dict[str, str]
    secrets: set[str]


def resolve(spec: ServerSpec, workspace: str | os.PathLike) -> _Resolved:
    """Expand ${VARS} (WORKSPACE, env_commands, process env) in a spec. Raises on a missing variable."""
    variables = {"WORKSPACE": str(pathlib.Path(workspace).resolve())}
    secrets: set[str] = set()
    for var, command in spec.env_commands.items():
        if os.environ.get(var):
            variables[var] = os.environ[var]
        else:
            variables[var] = _run_env_command(command)
        secrets.add(variables[var])

    def expand(text: str) -> str:
        def sub(match: re.Match) -> str:
            name = match.group(1)
            value = variables.get(name, os.environ.get(name))
            if value is None:
                raise KeyError(f"${{{name}}} is not set (needed by MCP server '{spec.name}')")
            return value
        return _VAR.sub(sub, text)

    env = {k: expand(v) for k, v in spec.env.items()}
    headers = {k: expand(v) for k, v in spec.headers.items()}
    secrets.update(v for k, v in {**env, **headers}.items() if _SECRET_KEY.search(k))
    command = spec.command
    if command:
        command = shutil.which(command) or command
    return _Resolved(command=command, args=[expand(a) for a in spec.args], env=env,
                     url=expand(spec.url), headers=headers, secrets=secrets)


# ─── Result handling ─────────────────────────────────────────────────────────

def _result_text(result) -> tuple[str, bool]:
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", "")
        if kind == "text":
            parts.append(item.text)
        elif kind == "image":
            parts.append("[image]")
        elif kind == "resource":
            resource = getattr(item, "resource", None)
            parts.append(getattr(resource, "text", None) or f"[resource {getattr(resource, 'uri', '')}]")
        else:
            parts.append(f"[{kind or 'content'}]")
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False))
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    return "\n".join(parts), is_error


def trim_output(text: str, save_dir: pathlib.Path, label: str) -> tuple[str, str | None]:
    if len(text) <= MAX_RESULT_CHARS:
        return text, None
    save_dir.mkdir(parents=True, exist_ok=True)
    path = save_dir / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.txt"
    path.write_text(text, encoding="utf-8")
    cut = len(text) - HEAD_CHARS - TAIL_CHARS
    short = f"{text[:HEAD_CHARS]}\n\n... [{cut} characters cut; full output: {path}] ...\n\n{text[-TAIL_CHARS:]}"
    return short, str(path)


def _log_call(workspace: str | os.PathLike, record: dict[str, Any]) -> None:
    path = pathlib.Path(workspace) / ".codemitra" / "logs" / "mcp_calls.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ─── Connections (background event loop) ─────────────────────────────────────

class _Connection:
    """One server session, living in its own task on the manager's loop."""

    def __init__(self, spec: ServerSpec, resolved: _Resolved, errlog_path: pathlib.Path):
        self.spec = spec
        self.resolved = resolved
        self.errlog_path = errlog_path
        self.ready: concurrent.futures.Future = concurrent.futures.Future()
        self.done: concurrent.futures.Future = concurrent.futures.Future()
        self.queue: asyncio.Queue | None = None
        self.tools: list[ToolInfo] = []

    async def run(self) -> None:
        from mcp import ClientSession

        self.queue = asyncio.Queue()
        try:
            async with AsyncExitStack() as stack:
                read, write = await self._open(stack)
                session = await stack.enter_async_context(
                    # the session-wide read timeout also caps initialize / list_tools: give it the start time
                    # (a slow server start is not a slow call); each call keeps its own wait_for(timeout_s) (E-045)
                    ClientSession(read, write,
                                  read_timeout_seconds=max(self.spec.timeout_s, self.spec.connect_timeout_s))
                )
                await asyncio.wait_for(session.initialize(), self.spec.connect_timeout_s)
                self.tools = await asyncio.wait_for(self._list_tools(session), self.spec.connect_timeout_s)
                self.ready.set_result(True)
                while True:
                    item = await self.queue.get()
                    if item is None:
                        break
                    tool, arguments, future, timeout = item
                    try:
                        result = await asyncio.wait_for(session.call_tool(tool, arguments), timeout)
                    except BaseException as exc:  # noqa: BLE001 - reported to the caller
                        if not future.done():
                            future.set_exception(exc if isinstance(exc, Exception) else RuntimeError(repr(exc)))
                        if isinstance(exc, asyncio.CancelledError):
                            raise
                    else:
                        if not future.done():
                            future.set_result(result)
        except BaseException as exc:  # noqa: BLE001 - surfaced through ready/done
            error = exc if isinstance(exc, Exception) else RuntimeError(repr(exc))
            if not self.ready.done():
                self.ready.set_exception(error)
            if not self.done.done():
                self.done.set_exception(error)
            return
        if not self.done.done():
            self.done.set_result(True)

    async def _open(self, stack: AsyncExitStack):
        if self.spec.kind == "http":
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

            client = await stack.enter_async_context(create_mcp_http_client(headers=self.resolved.headers))
            streams = await stack.enter_async_context(streamable_http_client(self.resolved.url, http_client=client))
            return streams[0], streams[1]
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.resolved.command,
            args=self.resolved.args,
            env={**os.environ, **self.resolved.env},
            cwd=self.spec.cwd,
        )
        self.errlog_path.parent.mkdir(parents=True, exist_ok=True)
        errlog = stack.enter_context(open(self.errlog_path, "a", encoding="utf-8"))
        read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        return read, write

    async def _list_tools(self, session) -> list[ToolInfo]:
        tools: list[ToolInfo] = []
        cursor = None
        while True:
            page = await session.list_tools() if cursor is None else await session.list_tools(
                params=_paginated(cursor))
            for tool in page.tools:
                tools.append(ToolInfo(
                    server=self.spec.name,
                    name=tool.name,
                    description=self.spec.descriptions.get(tool.name) or _first_sentence(tool.description or ""),
                    input_schema=getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {},
                ))
            cursor = getattr(page, "nextCursor", None) or getattr(page, "next_cursor", None)
            if not cursor:
                return tools

    def alive(self) -> bool:
        return self.ready.done() and not self.ready.exception() and not self.done.done()


def _paginated(cursor: str):
    from mcp import types

    return types.PaginatedRequestParams(cursor=cursor)


def _first_sentence(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    match = re.search(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    return sentence if len(sentence) <= limit else sentence[: limit - 1] + "…"


class MCPManager:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._conns: dict[str, _Connection] = {}
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, name="codemitra-mcp", daemon=True)
                self._thread.start()
            return self._loop

    def connect(self, spec: ServerSpec, workspace: str | os.PathLike) -> _Connection:
        key = f"{pathlib.Path(workspace).resolve()}::{spec.name}"
        conn = self._conns.get(key)
        if conn is not None and conn.alive():
            return conn
        resolved = resolve(spec, workspace)
        errlog = pathlib.Path(workspace) / ".codemitra" / "logs" / f"mcp-{spec.name}.log"
        conn = _Connection(spec, resolved, errlog)
        loop = self._ensure_loop()
        asyncio.run_coroutine_threadsafe(conn.run(), loop)
        try:
            conn.ready.result(timeout=spec.connect_timeout_s + 5)
        except concurrent.futures.TimeoutError as exc:
            self._stop(conn)
            raise TimeoutError(f"MCP server '{spec.name}' did not start within {spec.connect_timeout_s:.0f}s") from exc
        self._conns[key] = conn
        _store_cached_tools(spec, conn.tools)
        return conn

    def call(self, conn: _Connection, tool: str, arguments: dict[str, Any], timeout: float):
        loop = self._ensure_loop()
        future: concurrent.futures.Future = concurrent.futures.Future()
        loop.call_soon_threadsafe(conn.queue.put_nowait, (tool, arguments, future, timeout))
        return future.result(timeout=timeout + 5)

    def _stop(self, conn: _Connection) -> None:
        if self._loop is not None and conn.queue is not None:
            self._loop.call_soon_threadsafe(conn.queue.put_nowait, None)

    def close_all(self) -> None:
        for conn in list(self._conns.values()):
            self._stop(conn)
        for conn in list(self._conns.values()):
            try:
                conn.done.result(timeout=5)
            except Exception:  # noqa: BLE001 - best effort on shutdown
                pass
        self._conns.clear()


_manager = MCPManager()
atexit.register(_manager.close_all)


def manager() -> MCPManager:
    return _manager


# ─── Tool cache (so search works without starting every server) ──────────────

def _store_cached_tools(spec: ServerSpec, tools: list[ToolInfo]) -> None:
    cache = _load_json(_cache_path(), {})
    cache[spec.name] = {
        "key": spec.key(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools],
    }
    try:
        _save_json(_cache_path(), cache)
    except OSError:
        pass


def cached_tools(spec: ServerSpec) -> list[ToolInfo] | None:
    entry = _load_json(_cache_path(), {}).get(spec.name)
    if not entry or entry.get("key") != spec.key():
        return None
    return [ToolInfo(spec.name, t["name"], spec.descriptions.get(t["name"]) or t.get("description", ""),
                     t.get("input_schema") or {}) for t in entry.get("tools", [])]


def tool_tokens(tools: list[ToolInfo]) -> int:
    """Rough prompt cost if every tool were listed (chars / 4)."""
    return sum(len(json.dumps({"name": t.name, "description": t.description, "schema": t.input_schema})) for t in tools) // 4


# ─── Public API ──────────────────────────────────────────────────────────────

def list_tools(workspace: str | os.PathLike, server: str) -> list[ToolInfo]:
    spec = find(discover(workspace), server)
    if spec is None:
        raise KeyError(f"No MCP server named '{server}'")
    if not spec.trusted:
        raise PermissionError(f"'{server}' comes from this project's .codemitra/mcp.json; run /mcp trust first")
    return _manager.connect(spec, workspace).tools


def call_tool(
    workspace: str | os.PathLike,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    approve: Callable[[ServerSpec, str, dict[str, Any]], bool] | None = None,
) -> CallResult:
    """Call one tool. Tools that need approval run only if `approve` returns True."""
    arguments = dict(arguments or {})
    started = time.time()
    spec = find(discover(workspace), server)
    record: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "server": server, "tool": tool}

    def finish(ok: bool, text: str, *, approved=None, secrets=frozenset(), path=None) -> CallResult:
        seconds = round(time.time() - started, 2)
        record.update(ok=ok, approved=approved, chars=len(text), seconds=seconds,
                      args=mask(arguments, set(secrets)), full_output=path)
        if not ok:
            record["error"] = mask(text[:300], set(secrets))
        _log_call(workspace, record)
        return CallResult(server, tool, ok, mask(text, set(secrets)), path, approved, seconds)

    if spec is None:
        return finish(False, f"✗ No MCP server named '{server}'. Use mcp_find to see what is available.")
    if not spec.enabled:
        return finish(False, f"✗ MCP server '{server}' is turned off (/mcp on {server}).")
    if not spec.trusted:
        return finish(False, f"✗ MCP server '{server}' is from this project's .codemitra/mcp.json; run /mcp trust first.")

    try:
        conn = _manager.connect(spec, workspace)
    except Exception as exc:  # noqa: BLE001 - reported as a failed call
        return finish(False, f"✗ Could not start MCP server '{server}': {exc}")
    if tool not in {t.name for t in conn.tools}:
        return finish(False, f"✗ '{server}' has no tool '{tool}'. Use mcp_find to see its tools.",
                      secrets=conn.resolved.secrets)

    approved = None
    if needs_approval(spec, tool):
        approved = bool(approve and approve(spec, tool, arguments))
        if not approved:
            return finish(False, f"✗ Not run: {server}.{tool} needs your approval.", approved=False,
                          secrets=conn.resolved.secrets)
    try:
        result = _manager.call(conn, tool, arguments, spec.timeout_s)
    except (TimeoutError, concurrent.futures.TimeoutError):
        return finish(False, f"✗ {server}.{tool} timed out after {spec.timeout_s:.0f}s", approved=approved,
                      secrets=conn.resolved.secrets)
    except Exception as exc:  # noqa: BLE001 - reported as a failed call
        return finish(False, f"✗ {server}.{tool} failed: {exc}", approved=approved, secrets=conn.resolved.secrets)

    text, is_error = _result_text(result)
    text = mask(text, conn.resolved.secrets)
    short, path = trim_output(text, pathlib.Path(workspace) / ".codemitra" / "mcp-output", f"{server}-{tool}")
    if is_error:
        short = f"✗ tool error: {short}"
    return finish(not is_error, short, approved=approved, secrets=conn.resolved.secrets, path=path)


def search_tools(workspace: str | os.PathLike, query: str, k: int = 5, *, connect_missing: bool = True,
                 servers: tuple[str, ...] | list[str] | None = None) -> list[ToolInfo]:
    """Rank tools on usable servers by keyword overlap with the query (name counts most).
    `servers` limits the search to those servers (role routing); None = every usable server."""
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 2]
    scored: list[tuple[float, ToolInfo]] = []
    for spec in discover(workspace):
        if not spec.usable or (servers is not None and spec.name not in servers):
            continue
        tools = cached_tools(spec)
        if tools is None and connect_missing:
            try:
                tools = _manager.connect(spec, workspace).tools
            except Exception:  # noqa: BLE001 - a broken server is skipped, /mcp shows why
                tools = None
        for tool in tools or []:
            name = tool.name.lower().replace("-", "_")
            desc = tool.description.lower()
            server_text = f"{spec.name} {spec.description}".lower()
            score = sum(3 * (w in name) + 1 * (w in desc) + 0.5 * (w in server_text) for w in words)
            if score > 0:
                scored.append((score, tool))
    scored.sort(key=lambda pair: (-pair[0], pair[1].server, pair[1].name))
    return [tool for _, tool in scored[:k]]


def format_search(workspace: str | os.PathLike, tools: list[ToolInfo]) -> str:
    if not tools:
        servers = ", ".join(f"{s.name} ({s.description})" for s in discover(workspace) if s.usable)
        return f"No matching MCP tool. Servers: {servers or 'none'}"
    specs = {s.name: s for s in discover(workspace)}
    lines = []
    for tool in tools:
        spec = specs.get(tool.server)
        flag = " [needs approval]" if spec and needs_approval(spec, tool.name) else ""
        lines.append(f"- {tool.server} / {tool.name}: {tool.description} (args: {tool.arg_summary()}){flag}")
    return "\n".join(lines)


def summarize(servers: list[ServerSpec]) -> str:
    on = [s.name for s in servers if s.usable]
    pending = [s.name for s in servers if s.enabled and not s.trusted]
    text = f"{len(on)} on ({', '.join(on)})" if on else "none on"
    if pending:
        text += f"; untrusted project servers: {', '.join(pending)} (/mcp trust)"
    return text


def format_prompt(servers: list[ServerSpec]) -> str:
    """Short status for the /mcp list."""
    lines = ["## MCP servers", "", "| Server | State | Source | Tools | Prompt tokens if all listed | What it does |",
             "|---|---|---|---|---|---|"]
    for spec in servers:
        state = "on" if spec.usable else ("untrusted" if spec.enabled else "off")
        tools = cached_tools(spec)
        count = str(len(tools)) if tools is not None else "?"
        tokens = f"~{tool_tokens(tools):,}" if tools is not None else "?"
        lines.append(f"| {spec.name} | {state} | {spec.source} | {count} | {tokens} | {spec.description} |")
    lines += ["", "`/mcp test <name>` starts a server and lists its tools · `/mcp tools <name>` · `/mcp on|off <name>` · "
              "`/mcp trust` · `/mcp import` (from Claude Code) · `/mcp call <server> <tool> {json}`",
              "", "The model sees two small tools (`mcp_find`, `mcp_call`), not every tool above."]
    return "\n".join(lines)


# ─── /mcp command ────────────────────────────────────────────────────────────

def _set_enabled(workspace: str | os.PathLike, name: str, enabled: bool) -> str:
    if find(discover(workspace), name) is None:
        return f"No MCP server named `{name}`."
    path = project_config_path(workspace)
    was_trusted = is_project_trusted(workspace)
    data = _load_json(path, {}) if path.is_file() else {}
    data.setdefault("mcpServers", {}).setdefault(name, {})["enabled"] = enabled
    _save_json(path, data)
    if was_trusted:
        trust_project(workspace)  # our own edit keeps an already-trusted file trusted
    return f"`{name}` turned {'on' if enabled else 'off'} for this project (`.codemitra/mcp.json`)."


def import_claude_code(workspace: str | os.PathLike) -> str:
    """Copy servers from Claude Code configs into ~/.codemitra/mcp.json (never into the repo: they may hold secrets)."""
    found: dict[str, dict[str, Any]] = {}
    for path in claude_config_paths(workspace):
        data = _load_json(path, {}) if path.is_file() else {}
        if not isinstance(data, dict):
            continue
        found.update({k: v for k, v in (data.get("mcpServers") or {}).items() if isinstance(v, dict)})
        project = (data.get("projects") or {}).get(str(pathlib.Path(workspace).resolve()))
        if isinstance(project, dict):
            found.update({k: v for k, v in (project.get("mcpServers") or {}).items() if isinstance(v, dict)})
    if not found:
        return "No MCP servers found in Claude Code's config (`~/.claude.json`, `.mcp.json`)."
    target = user_config_path()
    data = _load_json(target, {}) if target.is_file() else {}
    existing = data.setdefault("mcpServers", {})
    added = [name for name in found if name not in existing]
    for name in added:
        existing[name] = found[name]
    _save_json(target, data)
    skipped = sorted(set(found) - set(added))
    msg = f"Imported {len(added)} server(s) into `{target}`: {', '.join(added) or 'none'}."
    if skipped:
        msg += f" Already there: {', '.join(skipped)}."
    return msg + " Imported tools all need approval until you add `allow` patterns."


# ─── Add / remove / import from other tools (M1, M2) ─────────────────────────

_SAFE_SERVER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ADD_USAGE = ("Usage: `mcp add <name> [--project] [--replace] [--env K=V] -- <command> [args…]` · "
             "`mcp add <name> --url <https://…> [--header K=V] [--project]` · `mcp remove <name> [--project]`")


class McpConfigError(Exception):
    pass


def _literal_secret(key: str, value: str) -> bool:
    """A secret-looking key whose value holds text beyond ${VAR} references (and a Bearer/Basic/token word)."""
    if not _SECRET_KEY.search(key):
        return False
    rest = _VAR.sub("", value)
    rest = re.sub(r"\b(bearer|basic|token)\b", "", rest, flags=re.IGNORECASE)
    return bool(rest.strip())


def parse_add(argv: list[str]) -> tuple[str, dict[str, Any], bool, bool]:
    """`add` arguments -> (name, entry, project, replace). The command is everything after `--`."""
    if not argv:
        raise McpConfigError(ADD_USAGE)
    command: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, command = argv[:cut], argv[cut + 1:]
    name, project, replace, url = "", False, False, ""
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--project":
            project = True
        elif a == "--replace":
            replace = True
        elif a in ("--url", "--env", "--header") and i + 1 < len(argv):
            i += 1
            v = argv[i]
            if a == "--url":
                url = v
            else:
                k, sep, val = v.partition("=" if a == "--env" else ("=" if "=" in v else ":"))
                if not sep or not k.strip():
                    raise McpConfigError(f"{a} takes KEY=VALUE, got '{v}'")
                (env if a == "--env" else headers)[k.strip()] = val.strip()
        elif a.startswith("--"):
            raise McpConfigError(f"unknown option {a}. " + ADD_USAGE)
        elif not name:
            name = a
        else:
            raise McpConfigError(f"put the server's command after `--` (got '{a}'). " + ADD_USAGE)
        i += 1
    if not _SAFE_SERVER.match(name):
        raise McpConfigError("the server name must be letters, digits, '.', '_' or '-'. " + ADD_USAGE)
    if bool(url) == bool(command):
        raise McpConfigError("give either `--url <address>` or `-- <command> [args]`. " + ADD_USAGE)
    if url and not re.match(r"^https?://", url):
        raise McpConfigError(f"--url must start with https:// or http:// (got '{url}')")
    entry: dict[str, Any] = {"type": "http", "url": url} if url else {"command": command[0], "args": command[1:]}
    if env:
        entry["env"] = env
    if headers:
        entry["headers"] = headers
    if project:  # the project file is shared in the repo: secrets only as ${VAR} references
        leaked = [k for k, v in {**env, **headers}.items() if _literal_secret(k, v)]
        if leaked:
            raise McpConfigError(f"{', '.join(leaked)} would put a secret in the repo; write it as ${{VAR}} and set "
                                 "VAR in your environment, or add the server without --project")
    return name, entry, project, replace


def add_server(workspace: str | os.PathLike, name: str, entry: dict[str, Any], project: bool = False,
               replace: bool = False) -> pathlib.Path:
    """Save one server into ~/.codemitra/mcp.json (or the project's file). No `allow`: every tool asks first."""
    path = project_config_path(workspace) if project else user_config_path()
    data = _load_json(path, {}) if path.is_file() else {}
    if not isinstance(data, dict):
        raise McpConfigError(f"{path} is not a JSON object; fix or remove it first")
    servers = data.setdefault("mcpServers", {})
    if name in servers and not replace:
        raise McpConfigError(f"'{name}' is already in {path}; add --replace to change it")
    servers[name] = entry
    _save_json(path, data)
    return path


def remove_server(workspace: str | os.PathLike, name: str, project: bool = False) -> pathlib.Path:
    path = project_config_path(workspace) if project else user_config_path()
    data = _load_json(path, {}) if path.is_file() else {}
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    if name not in servers:
        hint = " It is a built-in: `/mcp off " + name + "` turns it off." if name in DEFAULT_SERVERS else ""
        raise McpConfigError(f"no server '{name}' in {path}.{hint}")
    del servers[name]
    _save_json(path, data)
    return path


def handle_add_remove(workspace: str | os.PathLike, argv: list[str], test: Callable | None = None) -> str:
    """`mcp add …` / `mcp remove …`; after an add to your file, starts the server once to show it works."""
    sub, rest = argv[0].lower(), argv[1:]
    try:
        if sub in {"remove", "rm"}:
            project = "--project" in rest
            names = [a for a in rest if a != "--project"]
            if len(names) != 1:
                return "Usage: `mcp remove <name> [--project]`"
            return f"✓ Removed `{names[0]}` from `{remove_server(workspace, names[0], project)}`."
        name, entry, project, replace = parse_add(rest)
        path = add_server(workspace, name, entry, project=project, replace=replace)
    except McpConfigError as exc:
        return f"✗ {exc}"
    msg = (f"✓ Added `{name}` to `{path}`. Every tool of it asks you first until you add `allow` patterns "
           "to its entry.")
    if project:
        return msg + f" This is the project's file: run `/mcp trust`, then `/mcp test {name}`."
    if test is None:
        return msg + f" `/mcp test {name}` starts it."
    return msg + "\n\n" + test(name)


def cursor_config_paths(workspace: str | os.PathLike) -> list[pathlib.Path]:
    override = os.environ.get("CODEMITRA_CURSOR_CONFIG")
    user_file = pathlib.Path(override) if override else pathlib.Path.home() / ".cursor" / "mcp.json"
    return [user_file, pathlib.Path(workspace) / ".cursor" / "mcp.json"]


def vscode_config_paths(workspace: str | os.PathLike) -> list[pathlib.Path]:
    override = os.environ.get("CODEMITRA_VSCODE_CONFIG")
    if override:
        user_file = pathlib.Path(override)
    elif os.name == "nt":
        user_file = pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home())) / "Code" / "User" / "mcp.json"
    elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        user_file = pathlib.Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    else:
        user_file = pathlib.Path.home() / ".config" / "Code" / "User" / "mcp.json"
    return [user_file, pathlib.Path(workspace) / ".vscode" / "mcp.json"]


def import_other(workspace: str | os.PathLike, tool: str) -> str:
    """Copy servers from Cursor (`mcpServers`) or VS Code (`servers`) into ~/.codemitra/mcp.json (never the repo)."""
    paths = cursor_config_paths(workspace) if tool == "cursor" else vscode_config_paths(workspace)
    key = "mcpServers" if tool == "cursor" else "servers"
    found: dict[str, dict[str, Any]] = {}
    for path in paths:
        data = _load_json(path, {}) if path.is_file() else {}
        if isinstance(data, dict):
            found.update({k: dict(v) for k, v in (data.get(key) or {}).items() if isinstance(v, dict)})
    if not found:
        return f"No MCP servers found in {tool.title()}'s config ({', '.join(f'`{p}`' for p in paths)})."
    for entry in found.values():  # VS Code writes "stdio" / "http" / "sse" in `type`; the rest is the same shape
        if str(entry.get("type", "")).lower() == "stdio":
            entry.pop("type")
    target = user_config_path()
    data = _load_json(target, {}) if target.is_file() else {}
    existing = data.setdefault("mcpServers", {})
    added = [name for name in found if name not in existing]
    for name in added:
        existing[name] = found[name]
    _save_json(target, data)
    skipped = sorted(set(found) - set(added))
    msg = f"Imported {len(added)} server(s) from {tool.title()} into `{target}`: {', '.join(added) or 'none'}."
    if skipped:
        msg += f" Already there: {', '.join(skipped)}."
    vs_inputs = [n for n in added if "${input:" in json.dumps(found[n])]
    if vs_inputs:
        msg += f" {', '.join(vs_inputs)} use VS Code `${{input:…}}` values: replace them with `${{VAR}}` in the file."
    return msg + " Imported tools all need approval until you add `allow` patterns."


def _split_args(argline: str) -> list[str]:
    """Split like a shell but keep Windows backslashes; quotes group words."""
    try:
        parts = shlex.split(argline, posix=False)
    except ValueError:
        parts = argline.split()
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def handle_command(workspace: str | os.PathLike, argline: str = "") -> str:
    parts = argline.strip().split(maxsplit=3)
    sub = parts[0].lower() if parts else ""
    if sub in {"add", "remove", "rm"}:
        return handle_add_remove(workspace, _split_args(argline.strip()),
                                 test=lambda name: handle_command(workspace, f"test {name}"))
    if sub == "import" and len(parts) >= 2 and parts[1].lower() in {"cursor", "vscode", "code"}:
        return import_other(workspace, "cursor" if parts[1].lower() == "cursor" else "vscode")
    servers = discover(workspace)
    if sub in {"", "list"}:
        return format_prompt(servers)
    if sub == "trust":
        trust_project(workspace)
        return "This project's `.codemitra/mcp.json` is trusted. CodeMitra asks again if the file changes."
    if sub == "import":
        return import_claude_code(workspace)
    if sub in {"on", "off"} and len(parts) >= 2:
        return _set_enabled(workspace, parts[1], sub == "on")
    if sub in {"test", "tools"} and len(parts) >= 2:
        name = parts[1]
        try:
            started = time.time()
            tools = list_tools(workspace, name)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            return f"✗ `{name}` failed to start: {exc}\n\nServer log: `.codemitra/logs/mcp-{name}.log`"
        spec = find(servers, name)
        rows = [f"- `{t.name}`{' (asks)' if spec and needs_approval(spec, t.name) else ''}: {t.description}"
                for t in tools]
        head = (f"✓ `{name}` started in {time.time() - started:.1f}s: {len(tools)} tools, "
                f"~{tool_tokens(tools):,} prompt tokens if all were listed.")
        return head + "\n\n" + "\n".join(rows)
    if sub == "call" and len(parts) >= 3:
        server, tool = parts[1], parts[2]
        try:
            arguments = json.loads(parts[3]) if len(parts) > 3 else {}
        except json.JSONDecodeError as exc:
            return f"✗ Arguments must be a JSON object: {exc}"
        # Typed by the user, so it counts as approval.
        result = call_tool(workspace, server, tool, arguments, approve=lambda *_: True)
        return result.text
    return ("Usage: `/mcp` · `/mcp test <name>` · `/mcp tools <name>` · `/mcp on|off <name>` · `/mcp trust` · "
            "`/mcp import [cursor|vscode]` · `/mcp call <server> <tool> {json}` · `/mcp add …` · `/mcp remove <name>`"
            "\n\n" + ADD_USAGE)


def build_reply(workspace: str | os.PathLike, servers: list[ServerSpec] | None = None) -> str:
    """Kept for callers of the old API: the /mcp list."""
    return format_prompt(servers if servers is not None else discover(workspace))
