"""`codemitra kaggle start | stop | status` (D-061): use your Kaggle GPU hours from CodeMitra, without opening Kaggle.

start: checks your weekly GPU quota, uploads a PRIVATE notebook (remote/kaggle/, GPU T4 x2, internet on) with this
       session's random token in it, follows its live log (lines `MITRA|stage|key=value`), and when it says `ready`
       points CodeMitra at it (`app.remote`, every workspace). Typically 4-8 minutes (install, model download, load).
stop:  asks the notebook to shut down (POST /<token>/mitra/stop), so the Kaggle run ends and stops using hours;
       CodeMitra goes back to this machine. The notebook also stops by itself after `idle_min` unused minutes, and the
       run has a hard time limit (`max_hours`), so a forgotten session cannot eat the week.
status: the run's state, whether it answers, and Kaggle's own count of your GPU hours (used / total / reset).

Works for any Kaggle account: credentials from ~/.kaggle/kaggle.json (Kaggle → Settings → API → Create New Token) or
KAGGLE_USERNAME / KAGGLE_KEY. Needs the `kaggle` package (a CodeMitra dependency).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue

SLUG = "codemitra-gpu-server"
ACCELERATOR = "NvidiaTeslaT4"   # Kaggle's "GPU T4 x2"
API_TIMEOUT_S = 60
STAGE_RE = re.compile(r"MITRA\|([a-z_]+)((?:\|[a-z_]+=[^|\r\n\"\\]*)*)")
STAGE_TEXT = {
    "started": "notebook started",
    "installing": "installing Ollama (a 1.5 GB download, usually 1-3 minutes)",
    "pulling": "downloading the model",
    "loading": "loading it at full context",
    "loaded": "model loaded",
    "tunnel": "opening the tunnel",
    "ready": "ready",
}


class KaggleError(Exception):
    """A problem the user can fix; the message says how."""


class NoInternet(KaggleError):
    """This account's notebooks get no internet (phone not verified): the guide can walk the user through it (I-34)."""


def _home() -> Path:
    from app import config
    return config._codemitra_home()


def _state_file() -> Path:
    return _home() / "kaggle.json"


def load_state() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(data: dict) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _timed(fn, *args, timeout: float = API_TIMEOUT_S, **kw):
    """Every Kaggle API call gets a timeout (CLAUDE.md non-negotiable)."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn, *args, **kw).result(timeout=timeout)
    except FutureTimeout as exc:
        raise KaggleError(f"Kaggle did not answer within {timeout:.0f} s; try again in a minute.") from exc
    finally:
        pool.shutdown(wait=False)


def client():
    """An authenticated KaggleApi, or KaggleError saying what to do."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:  # missing, or one of its own packages missing (E-065: six)
        raise KaggleError(f"The `kaggle` package cannot load ({exc}). With CodeMitra closed, reinstall CodeMitra: "
                          "`uv tool install --reinstall -e <codemitra folder>` (forward slashes in Git Bash).") from exc
    except (SystemExit, OSError) as exc:  # older kaggle versions authenticate on import
        raise KaggleError(_CREDS_HELP) from exc
    api = KaggleApi()
    # E-129: the library reads KAGGLE_CONFIG_DIR once, at import, and keeps its values in one dict shared by every
    # client: a key saved (or a folder set) after the first import was ignored. Read them fresh, per client.
    api.config_dir, api.config, api.config_values = str(key_path().parent), str(key_path()), {}
    import contextlib
    import io
    quiet = io.StringIO()  # the library prints its own 15-line sign-in help (twice): ours is shorter and CodeMitra's
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            _timed(api.authenticate)
    except (SystemExit, OSError, ValueError, KaggleError) as exc:
        detail = "" if isinstance(exc, SystemExit) or str(exc).strip().isdigit() else f" ({exc})"
        raise KaggleError(_CREDS_HELP + detail) from exc
    return api


_CREDS_HELP = ("No Kaggle API key found. On kaggle.com: your picture → Settings → API → Generate New Token, copy it and "
               "run `codemitra kaggle setup <token>` (if your browser downloaded kaggle.json instead: `codemitra kaggle setup`). "
               "Also verify your phone in Settings (notebooks need it for GPUs and internet).")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-]{20,}$")


def token_path() -> Path:
    """Where Kaggle's newer API tokens live (kagglesdk reads ~/.kaggle/access_token before kaggle.json)."""
    return Path(os.path.expanduser("~")) / ".kaggle" / "access_token"


def key_path() -> Path:
    """Where the kaggle library looks: $KAGGLE_CONFIG_DIR/kaggle.json, else ~/.kaggle/kaggle.json."""
    base = os.environ.get("KAGGLE_CONFIG_DIR")
    return Path(base) / "kaggle.json" if base else Path.home() / ".kaggle" / "kaggle.json"


def find_download() -> Path | None:
    """The newest kaggle.json / kaggle (1).json in Downloads (Kaggle's Create New Token saves it there)."""
    downloads = Path.home() / "Downloads"
    try:
        found = sorted(downloads.glob("kaggle*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return found[0] if found else None


def setup(source: str = "", *, echo=print, api_factory=None, next_hint: bool = True) -> bool:
    """`codemitra kaggle setup [path]`: put the downloaded API key where Kaggle looks, check it, show the hours.
    Any Kaggle account; the key stays on this machine."""
    import shutil
    target = key_path()
    src = Path(source).expanduser() if source else None
    if source and not src.exists() and TOKEN_RE.match(source.strip()):  # the newer token: a string, not a file
        tp = token_path()
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text(source.strip(), encoding="utf-8")
        try:
            os.chmod(tp, 0o600)
        except OSError:
            pass
        echo(f"✓ API token saved to {tp}")
        src = None
    elif source and not src.exists():
        echo(f"✗ `{source}` is neither a file nor a Kaggle token. On kaggle.com: Settings → API → Generate New "
             "Token, copy it, then `codemitra kaggle setup <token>`.")
        return False
    elif src is None:
        # E-131: also a download newer than the key in use (an expired key was kept and the new one never read)
        found = find_download()
        saved = max((p.stat().st_mtime for p in (target, token_path()) if p.exists()), default=None)
        if found is not None and (saved is None or found.stat().st_mtime > saved):
            src = found
    if src is not None:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            echo(f"✗ cannot read {src}: {exc}")
            return False
        if not (isinstance(data, dict) and data.get("username") and data.get("key")):
            echo(f"✗ {src} is not a Kaggle API key (it needs \"username\" and \"key\").")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        try:
            os.chmod(target, 0o600)  # the kaggle library warns about a key readable by others
        except OSError:
            pass
        echo(f"✓ API key for {data['username']} saved to {target}")
    elif not target.exists() and not token_path().exists():
        echo("On kaggle.com: your picture → Settings → API → Generate New Token, copy it, then "
             "`codemitra kaggle setup <token>`. (A downloaded kaggle.json works too: `codemitra kaggle setup` finds it in "
             "Downloads, or `codemitra kaggle setup <path>`.)")
        return False
    try:
        api = (api_factory or client)()
        q = quota(api)
    except KaggleError as exc:
        echo(f"✗ {exc}")
        return False
    from app import backend
    user = username(api)
    if backend.prefs().get("kaggle_account") != user:
        backend.save_prefs(kaggle_account=user, kaggle_internet={})  # E-137: this is the account CodeMitra uses now
    echo(f"✓ signed in to Kaggle as {user} (key: {key_source()}) · " + quota_line(q))
    if not q.get("total_h"):
        echo("⚠ no GPU hours shown: verify your phone on kaggle.com → Settings (GPU and internet need it)")
    if not next_hint:  # I-34: the caller runs the setup checklist next (it checks the phone itself)
        return True
    if q.get("total_h"):  # E-137: hours are shown before the phone is verified too; notebooks get internet only after it
        echo("  Phone verified? Kaggle gives notebooks internet only then (kaggle.com → Settings → Phone "
             "verification); `codemitra kaggle check` checks it in about a minute, no GPU hours.")
    echo("Next: `codemitra kaggle start` (4-8 minutes), then `codemitra` in any project folder. `codemitra kaggle stop` when done.")
    return True


NO_INTERNET = ("Kaggle account {user}: its notebooks get no internet, so the notebook cannot download Ollama. Kaggle "
               "turns internet on only after the account's phone is verified: kaggle.com → your picture → Settings → "
               "Phone verification. Then `codemitra kaggle start` again.")


def key_source() -> str:
    """Where the Kaggle key in use comes from, in the order the kaggle library reads them (E-137)."""
    if os.environ.get("KAGGLE_API_TOKEN"):
        return "the KAGGLE_API_TOKEN environment variable"
    if token_path().exists() or token_path().with_suffix(".txt").exists():
        return str(token_path())
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return "the KAGGLE_USERNAME / KAGGLE_KEY environment variables"
    if key_path().exists():
        return str(key_path())
    return "Kaggle's saved sign-in"


def _remember_internet(user: str, ok: bool) -> None:
    from app import backend
    backend.save_prefs(kaggle_internet={"user": user, "ok": ok, "checked": datetime.now().strftime("%Y-%m-%d")})


def account_line(user: str) -> str:
    """e.g. 'Kaggle account: saisarann (key: ~/.kaggle/access_token) · internet: none, verify your phone' (E-137)."""
    from app import backend
    net = backend.prefs().get("kaggle_internet") or {}
    note = ""
    if isinstance(net, dict) and net.get("user") == user:
        note = (f" · internet: ok (checked {net.get('checked')})" if net.get("ok") else
                " · internet: none on its notebooks (verify your phone on kaggle.com → Settings)")
    return f"Kaggle account: {user} (key: {key_source()}){note}"


def check_account(api, echo=print) -> str:
    """The account this key signs in to; it must be the one set up (E-137: the key Kaggle's library picks first may be
    another account's, e.g. an old access_token or environment variables, and nothing said which account ran)."""
    from app import backend
    user = username(api)
    saved = backend.prefs().get("kaggle_account")
    if saved and saved != user:
        raise KaggleError(f"CodeMitra was set up with Kaggle account {saved}, but the key it finds now is for {user} "
                          f"(from {key_source()}). To use {user} on purpose: `codemitra kaggle setup`; to keep {saved}: "
                          f"remove that key.")
    if not saved:
        backend.save_prefs(kaggle_account=user)
    echo("  " + account_line(user))
    return user


def granted(api, ref: str) -> dict:
    """The settings Kaggle actually saved for the notebook ({} if it cannot tell): enable_internet, machine_shape, ..."""
    import shutil
    folder = _home() / "kaggle-check"
    shutil.rmtree(folder, ignore_errors=True)
    try:
        _timed(lambda: api.kernels_pull(ref, path=str(folder), metadata=True), timeout=60)
        data = json.loads((folder / "kernel-metadata.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - only a quick look; the notebook checks its internet itself
        return {}
    finally:
        shutil.rmtree(folder, ignore_errors=True)  # it holds the notebook, with this session's token


def username(api) -> str:
    for getter in (lambda: api.get_config_value("username"), lambda: api.config_values.get("username")):
        try:
            name = getter()
            if name:
                return str(name)
        except Exception:
            continue
    raise KaggleError("Could not read your Kaggle username from the API key.")


def quota(api) -> dict:
    """Kaggle's own GPU numbers: {"used_h", "total_h", "left_h", "refresh"} (refresh = UTC datetime or None)."""
    from kagglesdk.kernels.types.kernels_api_service import ApiGetAcceleratorQuotaStatisticsRequest

    def ask():
        with api.build_kaggle_client() as k:
            return k.kernels.kernels_api_client.get_accelerator_quota_statistics(
                ApiGetAcceleratorQuotaStatisticsRequest())

    r = _timed(ask)
    g = r.gpu_quota
    used = g.time_used.total_seconds() / 3600 if g and g.time_used else 0.0
    total = g.total_time_allowed.total_seconds() / 3600 if g and g.total_time_allowed else 0.0
    refresh = r.quota_refresh_time
    if refresh is not None and refresh.tzinfo is None:
        refresh = refresh.replace(tzinfo=timezone.utc)
    return {"used_h": round(used, 2), "total_h": round(total, 2), "left_h": round(max(total - used, 0.0), 2),
            "refresh": refresh}


def quota_line(q: dict, now: datetime | None = None) -> str:
    """e.g. 'Kaggle GPU: 1.0 h used of 30 · 29.0 h left · resets Sat 14 Nov 05:30' (reset in local time)."""
    when = ""
    if q.get("refresh"):
        local = q["refresh"].astimezone()
        when = f" · resets {local.strftime('%a %d %b %H:%M')}"
    return f"Kaggle GPU: {q['used_h']:.1f} h used of {q['total_h']:.0f} · {q['left_h']:.1f} h left{when}"


def run_status(api, ref: str) -> tuple[str, str]:
    """(QUEUED | RUNNING | COMPLETE | ERROR | CANCEL_... | UNKNOWN, failure message)."""
    try:
        r = _timed(api.kernels_status, ref)
    except KaggleError:
        raise
    except Exception as exc:  # noqa: BLE001 - e.g. never pushed yet
        return "UNKNOWN", f"{type(exc).__name__}: {exc}"
    status = getattr(getattr(r, "status", None), "name", None) or str(getattr(r, "status", "UNKNOWN"))
    return status.upper(), str(getattr(r, "failure_message", "") or "")


def parse_stages(text: str) -> list[tuple[str, dict]]:
    """Every `MITRA|stage|k=v` line in a piece of log (also inside JSON-escaped log blobs)."""
    out = []
    for m in STAGE_RE.finditer(text or ""):
        fields = {k: v.strip() for k, v in (part.split("=", 1) for part in m.group(2).split("|")[1:]
                                            if "=" in part)}
        out.append((m.group(1), fields))
    return out


def notebook_folder(model: str, ctx: int, token: str, idle_min: int, user: str) -> Path:
    """Write the notebook + kernel-metadata.json Kaggle's push needs; returns the folder."""
    import importlib.util
    root = Path(__file__).resolve().parents[1] / "remote" / "kaggle"
    spec = importlib.util.spec_from_file_location("mitra_kaggle_nb", root / "build_notebook.py")
    nb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nb)
    folder = _home() / "kaggle-push"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{SLUG}.ipynb").write_text(
        json.dumps(nb.build({"model": model, "ctx": ctx, "token": token, "idle_min": idle_min}), indent=1),
        encoding="utf-8")
    meta = {"id": f"{user}/{SLUG}", "title": SLUG, "code_file": f"{SLUG}.ipynb", "language": "python",
            "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_internet": True,
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}
    (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return folder


def _log_lines(api, ref: str, q: Queue, stop: threading.Event) -> None:
    """Background thread: the live log, chunk by chunk, into `q` (None at the end)."""
    try:
        for event in api.kernels_logs_stream(ref):
            if stop.is_set():
                break
            q.put(str(event.get("data", "")) if isinstance(event, dict) else str(event))
    except Exception as exc:  # noqa: BLE001 - the caller polls the status as well
        q.put(f"__error__ {type(exc).__name__}: {exc}")
    q.put(None)


def start(model: str, ctx: int = 262_144, *, idle_min: int = 30, max_hours: float = 11.5, wait_min: float = 20,
          echo=print, api=None, sleep=time.sleep) -> dict:
    """Upload and run the notebook, follow it until ready, point CodeMitra at it. Returns the remote settings."""
    from app import remote
    api = api or client()
    user = check_account(api, echo)  # E-137: name the account; refuse one that is not the account set up
    ref = f"{user}/{SLUG}"
    state = load_state()
    if state.get("ref") == ref and state.get("token"):
        status, _ = run_status(api, ref)
        if status in ("QUEUED", "RUNNING"):
            r = remote.active()
            if _connected(r, state):
                echo("☁ already running: CodeMitra uses it (`codemitra kaggle stop` ends it).")
                return r
            echo(f"⏳ a run is already {status.lower()}: following it")
            return _follow(api, ref, state, ctx, wait_min, echo, sleep)
    q = quota(api)
    echo("  " + quota_line(q))
    if q["total_h"] and q["left_h"] < 0.25:
        raise KaggleError("Less than 15 minutes of GPU time left this week: " + quota_line(q))
    hours = min(max_hours, max(q["left_h"], 0.25) if q["total_h"] else max_hours)
    if internet_known(user) is not True:  # I-34: a GPU run without internet only times out; check first, no GPU hours
        ok, detail = check_internet(api, user, echo=echo, sleep=sleep)
        if ok is False:
            raise NoInternet(NO_INTERNET.format(user=user) + f" (checked just now: {detail})")
    token = secrets.token_urlsafe(24)
    folder = notebook_folder(model, ctx, token, idle_min, user)
    echo(f"  uploading a private notebook ({ACCELERATOR}, {model} at {ctx // 1024}K, stops after {idle_min} min "
         f"unused or {hours:.1f} h) …")
    # kernels_push's own `timeout` is the run's time limit (seconds); ours (120 s) is for the upload call
    resp = _timed(lambda: api.kernels_push(str(folder), timeout=str(int(hours * 3600)), acc=ACCELERATOR),
                  timeout=120)
    err = str(getattr(resp, "error", "") or "")
    if err:
        raise KaggleError(f"Kaggle refused the notebook: {err}")
    state = {"ref": ref, "token": token, "model": model, "ctx": ctx, "pushed": time.time(),
             "url": str(getattr(resp, "url", "") or f"https://www.kaggle.com/code/{ref}"), "idle_min": idle_min}
    save_state(state)
    if granted(api, ref).get("enable_internet") is False:  # E-137: Kaggle saved it without internet: say so now
        _remember_internet(user, False)
        raise NoInternet(NO_INTERNET.format(user=user) + " (Kaggle saved this notebook with internet off; the run "
                          "ends by itself within a minute of starting.)")
    return _follow(api, ref, state, ctx, wait_min, echo, sleep)


READY_MAX_MIN = 45   # E-136: the notebook stops itself if it is not ready this long after it starts
TICK_S = 60          # E-136: a long step says it is still going every minute (it looked stuck)
QUEUE_MAX_MIN = 120  # E-135: Kaggle may hold a GPU run in its queue for over an hour; no hours are used meanwhile


def _connected(r: dict | None, state: dict) -> bool:
    """CodeMitra points at THIS run (E-135: an address left from an earlier run is not this one)."""
    public = (state.get("public") or "").rstrip("/")
    return bool(r and r.get("name") == "kaggle" and public and str(r.get("url", "")).startswith(public))


def _follow(api, ref: str, state: dict, ctx: int, wait_min: float, echo, sleep, queue_min: float = QUEUE_MAX_MIN,
            clock=time.time) -> dict:
    """Follow the run: up to queue_min in Kaggle's queue, then wait_min from when it runs (E-135: the queue time
    used to count against the 20 minutes, so a long queue gave up and the server that came up later sat unused)."""
    from app import remote
    deadline = clock() + queue_min * 60
    running = False
    step, step_t, tick = "", 0.0, 0.0  # E-136: the step it is on, since when, and the last "still ..." line
    seen: set[str] = set()
    search_ok = False  # must-have 10: set by the notebook's "search" line
    while clock() < deadline:
        status, failure = run_status(api, ref)
        if status in ("ERROR", "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED", "COMPLETE"):
            raise KaggleError(f"The Kaggle run ended ({status.lower()}{': ' + failure if failure else ''}). "
                              f"Its log: {state.get('url')}")
        if status != "RUNNING":
            if "queued" not in seen:
                echo("  ⏳ queued on Kaggle …")
                seen.add("queued")
            sleep(10)
            continue
        if not running:
            running = True
            deadline = clock() + wait_min * 60
        q: Queue = Queue()
        stop = threading.Event()
        threading.Thread(target=_log_lines, args=(api, ref, q, stop), daemon=True).start()
        buffer = ""
        while clock() < deadline:
            if step and clock() - tick >= TICK_S:  # E-136: a long step shows it is still going
                tick = clock()
                echo(f"  · still {step.split(' (')[0]} · {int((tick - step_t) // 60)} min")
            try:
                chunk = q.get(timeout=15)
            except Empty:
                continue
            if chunk is None or chunk.startswith("__error__"):
                break
            buffer = (buffer + chunk)[-20000:]
            for stage, fields in parse_stages(buffer):
                key = stage + json.dumps(fields, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                if stage == "net":  # E-137: the notebook's own internet check, remembered for this account
                    _remember_internet(ref.split("/")[0], fields.get("ok") == "True")
                if stage == "error":
                    stop.set()
                    detail = fields.get("detail", "?")
                    if detail.startswith("no internet"):
                        raise NoInternet(NO_INTERNET.format(user=ref.split("/")[0]) + f" (the notebook: {detail}.) "
                                          f"Log: {state.get('url')}")
                    raise KaggleError(f"The notebook failed: {detail}. Log: {state.get('url')}")
                if stage == "search":  # must-have 10: SearXNG on the notebook passed its engine test, or not
                    search_ok = fields.get("ok") == "True"
                    echo(f"  ✓ web search ready ({fields.get('results')} results in a test)" if search_ok else
                         "  · web search did not start on Kaggle: CodeMitra uses its own sources")
                elif stage == "loaded":
                    echo(f"  ✓ {fields.get('model')} {fields.get('gb')} GB at {fields.get('context')} context, "
                         f"{fields.get('where')}")
                elif stage == "ready" and fields.get("url"):
                    stop.set()
                    url = fields["url"].rstrip("/") + "/" + state["token"]
                    models, problem = remote.probe(url, timeout=30)
                    for _ in range(6):
                        if not problem:
                            break
                        sleep(5)
                        models, problem = remote.probe(url, timeout=30)
                    if problem:
                        raise KaggleError(f"The notebook is ready but its address does not answer: {problem}")
                    data = remote.set_remote(url, ctx, "kaggle")
                    state.update(started=time.time(), public=fields["url"], search=search_ok)
                    save_state(state)
                    echo(f"  ☁ ready: every CodeMitra window now uses Kaggle ({state.get('model')} at {ctx // 1024}K)")
                    return data
                elif stage in STAGE_TEXT:
                    echo(f"  · {STAGE_TEXT[stage]}")
                    step, step_t, tick = STAGE_TEXT[stage], clock(), clock()
        stop.set()
        sleep(5)
    if not running:
        raise KaggleError(f"Still in Kaggle's queue after {queue_min:.0f} minutes (no GPU hours used). "
                          "`codemitra kaggle start` follows it again; `codemitra kaggle stop` cancels it.")
    raise KaggleError(f"Not ready {wait_min:.0f} minutes after it started running. It stops itself if it is not ready "
                      f"{READY_MAX_MIN} minutes after it started; `codemitra kaggle stop` ends it now, `codemitra kaggle "
                      f"start` follows it again. The log: {state.get('url')}")


def stop(*, echo=print, api=None, sleep=time.sleep, wait_s: float = 90) -> None:
    """Ask the notebook to shut down; CodeMitra goes back to this machine; show the hours."""
    import urllib.request

    from app import remote
    state = load_state()
    r = remote.active()
    url = r["url"] if r and r.get("name") == "kaggle" else (
        (state.get("public", "").rstrip("/") + "/" + state["token"]) if state.get("public") and state.get("token")
        else "")
    asked = False
    if url:
        try:
            req = urllib.request.Request(url + "/mitra/stop", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30):
                asked = True
        except Exception as exc:  # noqa: BLE001
            echo(f"  ⚠ the notebook did not answer ({type(exc).__name__}); it stops by itself after "
                 f"{state.get('idle_min', 30)} min unused")
    if remote.active() and remote.active().get("name") == "kaggle":
        remote.clear()
    echo("  ✓ CodeMitra is back on this machine's Ollama")
    if asked:
        echo("  asked the Kaggle notebook to stop …")
    try:
        api = api or client()
        if state.get("ref") and asked:
            end = time.time() + wait_s
            while time.time() < end:
                status, _ = run_status(api, state["ref"])
                if status not in ("QUEUED", "RUNNING"):
                    echo(f"  ✓ the Kaggle run ended ({status.lower()}): no more GPU hours used")
                    break
                sleep(5)
            else:
                echo(f"  ⏳ still shutting down; check with `codemitra kaggle status` ({state.get('url')})")
        echo("  " + quota_line(quota(api)))
    except KaggleError as exc:
        echo(f"  ({exc})")
    state.update(stopped=time.time())
    save_state(state)


def status(*, echo=print, api=None) -> None:
    from app import remote
    state = load_state()
    r = remote.active()
    try:
        api = api or client()
        for line in render(checklist(api=api)):  # I-34: every setup step, the done ones shown as done
            echo(line)
        if state.get("ref"):
            run, failure = run_status(api, state["ref"])
            echo(f"Kaggle run: {run.lower()}{' · ' + failure if failure else ''} · {state.get('model', '?')} at "
                 f"{int(state.get('ctx') or 0) // 1024}K · {state.get('url', '')}")
            if run in ("QUEUED", "RUNNING") and not _connected(r, state):
                # E-135: a run nobody is following never gets used; say how to connect to it
                echo("  not connected to this run yet: `codemitra kaggle start` follows it and switches CodeMitra "
                     "to it when it is ready")
    except KaggleError as exc:
        echo(f"Kaggle: {exc}")
    if r:
        models, err = remote.probe(r["url"], timeout=15)
        echo(f"CodeMitra uses: ☁ {r.get('name')} · {remote.shown(r['url'])} · " +
             (f"✗ not answering ({err})" if err else "✓ answering"))
    else:
        echo("CodeMitra uses: this machine's Ollama")


def has_key() -> bool:
    """A Kaggle key is on this machine (kaggle.json, the newer access_token, or environment variables)."""
    return bool(key_path().exists() or token_path().exists() or os.environ.get("KAGGLE_API_TOKEN")
                or (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")))


def readiness(api_factory=None) -> dict:
    """Can CodeMitra use Kaggle right now? {key, ok, user, left_h, total_h, refresh, problem} (D-064).
    problem is one plain line with the fix, or ""."""
    out = {"key": has_key(), "ok": False, "user": "", "left_h": None, "total_h": None, "refresh": None, "problem": ""}
    if not out["key"]:
        out["problem"] = "no Kaggle key on this machine: `/kaggle setup` (2 minutes)"
        return out
    try:
        api = (api_factory or client)()
        out["user"] = username(api)
        q = quota(api)
    except KaggleError as exc:
        text = str(exc)
        out["problem"] = ("the Kaggle key does not work any more: make a new one (kaggle.com → Settings → API) and "
                          "`/kaggle setup <token>`") if "API key" in text or "Generate New Token" in text else \
            f"Kaggle did not answer ({text[:120]}); this machine for now"
        return out
    out.update(left_h=q["left_h"], total_h=q["total_h"], refresh=q["refresh"])
    if not q["total_h"]:
        out["problem"] = ("Kaggle shows 0 GPU hours: verify your phone on kaggle.com → Settings (GPUs need it), "
                          "then restart CodeMitra")
    elif q["left_h"] < 0.25:
        when = q["refresh"].astimezone().strftime("%a %H:%M") if q.get("refresh") else "next week"
        out["problem"] = f"Kaggle GPU hours are used up this week (resets {when}): this machine until then"
    else:
        out["ok"] = True
    return out


# ── I-34: the setup checklist (issue #13: a key, GPU hours and still no internet, found out only after a GPU start) ─
NET_SLUG = "codemitra-net-check"
NET_WAIT_S = 300
SIGNUP_URL = "https://www.kaggle.com/account/login?phase=startRegisterTab"
SETTINGS_URL = "https://www.kaggle.com/settings"
PHONE_FIX = "kaggle.com → your picture → Settings → Phone verification (Kaggle turns notebook internet on after it)"
KEY_FIX = "kaggle.com → your picture → Settings → API → Generate New Token, copy it, then `codemitra kaggle setup <token>`"
NET_SCRIPT = (
    "# CodeMitra's internet check (I-34): CPU only, no GPU hours. It only tries to reach ollama.com.\n"
    "import subprocess\n"
    "try:\n"
    "    r = subprocess.run(['curl', '-sS', '-o', '/dev/null', '--max-time', '20', 'https://ollama.com'],\n"
    "                       capture_output=True, text=True, timeout=40)\n"
    "    p = '' if r.returncode == 0 else (r.stderr.strip() or f'curl exit {r.returncode}')\n"
    "except Exception as exc:\n"
    "    p = f'{type(exc).__name__}: {exc}'\n"
    "p = p[-160:].replace('|', '/').replace('\\n', ' ')\n"
    "print(f'MITRA|net|ok={not p}|detail={p}', flush=True)\n")


def internet_known(user: str) -> bool | None:
    """What the last check said about this account's notebook internet (None: never checked)."""
    from app import backend
    net = backend.prefs().get("kaggle_internet") or {}
    if isinstance(net, dict) and net.get("user") == user and "ok" in net:
        return bool(net["ok"])
    return None


def check_internet(api, user: str, *, echo=print, sleep=time.sleep, clock=time.time,
                   wait_s: int = NET_WAIT_S) -> tuple[bool | None, str]:
    """Do this account's notebooks get internet? A tiny CPU-only script that only tries ollama.com: no GPU hours,
    25 s with internet and 46 s without in the live check on 2026-11-17 (the second gave issue #13's exact error).
    (True/False, detail), remembered for the account; (None, why) when it could not tell."""
    import shutil
    folder = _home() / "kaggle-net"
    shutil.rmtree(folder, ignore_errors=True)
    ref = f"{user}/{NET_SLUG}"
    echo("  checking that this account's notebooks get internet (a small CPU notebook, about 1 min, no GPU hours) …")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "check.py").write_text(NET_SCRIPT, encoding="utf-8")
        meta = {"id": ref, "title": NET_SLUG, "code_file": "check.py", "language": "python", "kernel_type": "script",
                "is_private": True, "enable_gpu": False, "enable_internet": True, "dataset_sources": [],
                "competition_sources": [], "kernel_sources": [], "model_sources": []}
        (folder / "kernel-metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        resp = _timed(lambda: api.kernels_push(str(folder), timeout=str(wait_s)), timeout=120)
        err = str(getattr(resp, "error", "") or "")
        if err:
            return None, f"Kaggle refused the check: {err}"
        deadline, status = clock() + wait_s, "UNKNOWN"
        while clock() < deadline:
            status, _ = run_status(api, ref)
            if status not in ("QUEUED", "RUNNING", "UNKNOWN"):
                break
            sleep(5)
        else:
            return None, f"the check did not finish in {wait_s // 60} min ({status.lower()})"
        out = folder / "out"
        _timed(lambda: api.kernels_output(ref, path=str(out)), timeout=60)
        text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in out.rglob("*") if p.is_file())
        for stage, fields in parse_stages(text):
            if stage == "net":
                ok = fields.get("ok") == "True"
                _remember_internet(user, ok)
                return ok, "internet works" if ok else (fields.get("detail") or "no internet")
        return None, f"the check ended ({status.lower()}) without an answer"
    except KaggleError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 - a check that cannot tell is not a failure; the GPU notebook checks again
        return None, f"{type(exc).__name__}: {exc}"[:200]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _step(key: str, title: str) -> dict:
    return {"key": key, "title": title, "ok": None, "detail": "", "fix": "", "url": ""}


def checklist(api=None, *, probe: bool = False, echo=print, sleep=time.sleep, api_factory=None) -> list[dict]:
    """The five setup steps, each checked now: ok True (done), False (needs you: `fix`, `url`) or None (not yet / not
    known). probe=True runs the internet check when no earlier check passed (about a minute, no GPU hours)."""
    steps = [_step("account", "Kaggle account"), _step("key", "API key"), _step("phone", "Phone verified"),
             _step("hours", "GPU hours"), _step("run", "First GPU run")]
    s = {x["key"]: x for x in steps}

    def key_problem(detail: str) -> list[dict]:
        s["key"].update(ok=False, detail=detail, fix=KEY_FIX, url=SETTINGS_URL)
        return steps

    if api is None:
        if api_factory is None and not has_key():  # E-140: a given factory is the key (tests, the wizard's fakes)
            s["account"].update(detail="sign up free if you have none (Google or email)", url=SIGNUP_URL)
            return key_problem("no key on this machine yet")
        try:
            api = (api_factory or client)()
        except KaggleError:
            return key_problem("the key on this machine does not sign in (make a new one)")
    try:
        user = username(api)
    except KaggleError:
        return key_problem("the key does not name a Kaggle account (make a new one)")
    s["account"].update(ok=True, detail=user)
    s["key"].update(ok=True, detail=key_source())
    try:
        q = quota(api)
    except KaggleError as exc:
        q = None
        s["hours"].update(detail=f"Kaggle did not answer ({exc})")
    if q is not None:
        if not q["total_h"]:
            s["hours"].update(ok=False, detail="0 GPU hours shown", fix="verify your phone (step 3); the hours show after it",
                              url=SETTINGS_URL)
        elif q["left_h"] < 0.25:
            s["hours"].update(ok=False, detail=quota_line(q).removeprefix("Kaggle GPU: "),
                              fix="used up this week: CodeMitra uses this machine until the reset")
        else:
            s["hours"].update(ok=True, detail=quota_line(q).removeprefix("Kaggle GPU: "))
    from app import backend
    checked = (backend.prefs().get("kaggle_internet") or {}).get("checked", "")
    known = internet_known(user)
    phone = s["phone"]
    if known is True:
        phone.update(ok=True, detail=f"notebooks get internet (checked {checked})")
    elif probe:
        ok, detail = check_internet(api, user, echo=echo, sleep=sleep)
        if ok:
            phone.update(ok=True, detail="notebooks get internet (checked just now)")
        elif ok is False:
            phone.update(ok=False, detail=f"its notebooks get no internet, checked just now ({detail})", fix=PHONE_FIX,
                         url=SETTINGS_URL)
        else:
            phone.update(detail=f"could not check ({detail})", fix="`codemitra kaggle check` again in a few minutes")
    elif known is False:
        phone.update(ok=False, detail=f"its notebooks got no internet (checked {checked})",
                     fix=PHONE_FIX + "; then `codemitra kaggle check`", url=SETTINGS_URL)
    elif q is not None and not q["total_h"]:
        phone.update(ok=False, detail="not yet (Kaggle shows 0 GPU hours)", fix=PHONE_FIX, url=SETTINGS_URL)
    else:
        phone.update(detail="not checked yet: `codemitra kaggle check` (about 1 min, no GPU hours)")
    state = load_state()
    if state.get("ref") == f"{user}/{SLUG}" and state.get("started"):
        when = datetime.fromtimestamp(state["started"]).strftime("%d %b %H:%M")
        s["run"].update(ok=True, detail=f"reached ready ({when})")
    else:
        s["run"].update(detail="not yet: `codemitra kaggle start` (4-8 min)")
    return steps


def first_open(steps: list[dict]) -> dict | None:
    """The first step that needs the user (ok False), or None."""
    return next((x for x in steps if x["ok"] is False), None)


def render(steps: list[dict]) -> list[str]:
    """e.g. '  ✓ 1. Kaggle account   saisarann' per step; the first open step's fix under it; 'ready' when all done."""
    mark = {True: "✓", False: "✗", None: "·"}
    width = max(len(x["title"]) for x in steps)
    first = first_open(steps)
    lines = ["Kaggle setup"]
    for i, x in enumerate(steps, 1):
        lines.append(f"  {mark[x['ok']]} {i}. {x['title']:<{width}}  {x['detail']}".rstrip())
        if x is first and x["fix"]:
            lines.append(f"       → {x['fix']}")
    if first is None and all(x["ok"] for x in steps[:4]):
        lines.append("  Ready: CodeMitra starts Kaggle by itself when you need it" +
                     ("." if steps[4]["ok"] else " (or now: `codemitra kaggle start`)."))
    return lines


def guide(*, echo=print, ask=input, open_url=None, api_factory=None, sleep=time.sleep, tries: int = 3) -> bool:
    """The checklist, then the first open step walked through: what to do, the page opened on request, a wait for
    'done', checked again. True when Kaggle is ready to use. The token step stays with the caller (setup / wizard)."""
    for attempt in range(tries + 1):
        steps = checklist(probe=True, echo=echo, sleep=sleep, api_factory=api_factory)
        for line in render(steps):
            echo(line)
        first = first_open(steps)
        phone = next(x for x in steps if x["key"] == "phone")
        if first is None:
            return phone["ok"] is True
        if first["key"] in ("account", "key") or (first["key"] == "hours" and phone["ok"]):
            return False  # a token to paste (the caller asks for it) or hours used up: nothing to wait for here
        if attempt == tries:
            echo("  Still no internet? Kaggle can take a while to turn it on after you verify; `codemitra kaggle check` "
                 "later shows this list again.")
            return False
        try:
            if open_url and first["url"] and ask("  Open that page in your browser now? (Y/n) ").strip().lower() in (
                    "", "y", "yes"):
                open_url(first["url"])
            answer = ask("  Type done when it is done (enter = later) ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("done", "d", "yes", "y", "ok"):
            echo("  later: `codemitra kaggle check` shows this list again and checks it")
            return False
    return False
