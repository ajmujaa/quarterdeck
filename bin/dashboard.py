#!/usr/bin/env python3
"""Quarterdeck dashboard: what the crew is doing, and the controls to change it.

Loopback only, and deliberately so. This process can start runs, so it is no
longer the strictly read-only window it began as; the boundary that replaces
that property is here rather than in the browser:

  * it binds 127.0.0.1 and nothing else;
  * every mutating request carries a token that only a page served by this
    process has seen, which is what stops a random web page you have open from
    POSTing to your loopback port;
  * it never builds a shell command. A run is argv, the project and duty must
    already be in the registry, and every argument has to match a narrow
    allowlist before it is passed on.

It still performs no privileged action itself. Starting a run means spawning the
same `qtdeck run` a human would type, so the contract discipline in lib.sh is
exactly as it was: the model thinks, the harness acts.
"""
import array
import atexit
import hashlib
import importlib.util
import json
import os
import re
import secrets
import hmac
import shutil
import socket
import struct
import sys
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

import home as _home
import markers as _markers                              # the marks written into GitHub bodies (bin/markers.py)
import safegit as _safegit
import packs as _packs_mod                              # stack and infrastructure packs (bin/packs.py)
import spend as _spend                                  # where the tokens went: the Spend view and `qtdeck spend` share it (bin/spend.py)

ROOT = Path(__file__).resolve().parent.parent           # the program: bin/, duties/, crew/, dashboard/
HOME = _home.resolve()                                  # YOUR data: state/, logs/, workspace/, config/ (see bin/home.py)
os.environ["QUARTERDECK_HOME"] = str(HOME)                  # every duty and tool this process starts agrees on it
STATE = HOME / "state"
LOGS = HOME / "logs"
DUTIES = ROOT / "duties"
CREW = ROOT / "crew"
WORKSPACE = HOME / "workspace"
PANELS = STATE / "panels"
PROJECTS_FILE = HOME / "config" / "projects.json"
SCHEDULES_FILE = STATE / "schedules.json"
MISSIONS_FILE = STATE / "missions.json"
INBOX_ACK_FILE = STATE / "inbox_ack.json"
SHOWCASE_FILE = STATE / "showcase.json"
PORT = int(os.environ.get("QUARTERDECK_DASHBOARD_PORT", "7878"))

TOKEN = secrets.token_urlsafe(24)

# A board snapshot is several GitHub round trips, so it is fetched on demand and
# held briefly rather than joining the three-second poll. Stale-but-labelled
# beats hammering the API on every tick.
BOARD_CACHE = {}
CARD_CACHE = {}      # (repo, kind, number) -> {at, card}; memory only, an issue body is never written to disk
BOARD_TTL = 60
PR_CACHE = {}
PROGRESS_CACHE = {}

SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
SAFE_FLAG = re.compile(r"^--[a-z][a-z-]{0,20}$")
SAFE_VALUE = re.compile(r"^[\w.,/#:@+=][\w .,/#:@+=-]{0,199}$", re.UNICODE)     # never starts with a dash or a space: a value cannot pass for a flag
SAFE_LOCK = re.compile(r"^[a-z0-9_-]{1,60}$")
SAFE_ID = re.compile(r"^[\w.-]{1,80}$")        # a panel id: a file name under state/panels


# ---- pairing: how a browser tab earns the right to read and drive this dashboard --------------------------------------------
# Loopback is not a secret: any program, and any other user on this computer, can open 127.0.0.1:PORT. So the page itself carries
# nothing. `qtdeck dashboard` (or `qtdeck dashboard link`, or `python3 bin/dashboard.py link`) writes a one-time nonce into
# state/pair/ (a folder only the owner can read) and prints a link with the nonce in its #fragment, which no server and no log ever
# sees. The page POSTs the nonce to /api/pair; the server checks it (single use: whoever deletes the file wins; constant-time
# compare; five minutes), then sets an HttpOnly, SameSite=Strict cookie bound to a random session and hands the page that session's
# API token in the response body. The tab keeps it in sessionStorage, which is per origin AND port, so a server on another loopback
# port (which does receive the cookie: cookies are not per port) cannot read it. The token is never given out again: /api/session
# only checks a tab's token, so a reload keeps working and a new tab pairs with a new link. A nonce can only be made by something that can write into
# state/, never over HTTP. The older credential, TOKEN (state/dashboard.token, 0600), still opens READS for the owner's own
# command-line tools and the two Helm endpoints in CLI_WRITES, but only for a request with no Origin header, which a browser always
# sends on a write. Every other write needs a paired session. The file is on the private list (bin/lib.sh), so neither a model's
# shell nor a project command can read it.
PAIR_TTL = 300                  # seconds a one-time link stays good
SESSION_TTL = 86400             # a paired browser stays paired for a day, across dashboard restarts; its own tab (cookie and token) renews it past half-life
SESSIONS_MAX = 20
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
_SESSIONS = {"map": None}       # sha256(session id) -> {"token", "exp"}; loaded from state/dashboard.sessions.json on first use
_SESSIONS_LOCK = threading.Lock()
_PAIR_FAILS = []                # times of recent bad nonces: a guesser is slowed to nothing
_PAIR_LOCK = threading.Lock()
# What a process that only READ state/dashboard.token may write: the two Helm endpoints the owner's evaluation tools (bin/chat-eval.py,
# bin/helm-eval.py) post to. Every other write (run, merge, attach, newproject, connections, capture ...) needs a paired browser session.
CLI_WRITES = ("/api/chat", "/api/understand")


def _sha(x):
    return hashlib.sha256(str(x).encode()).hexdigest()


def _private_write(path, text):
    """Write text so that no one but the owner could ever have read it: a 0600 temp file, then rename."""
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def pair_mint():
    """A fresh one-time nonce. Needs write access to state/pair/, which is the whole point."""
    d = STATE / "pair"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    now = time.time()
    for f in d.iterdir():                                                  # the unused and the stale go
        try:
            if float(f.read_text() or 0) < now:
                f.unlink()
        except (OSError, ValueError):
            pass
    nonce = secrets.token_urlsafe(24)
    fd = os.open(d / _sha(nonce), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(str(now + PAIR_TTL))
    return nonce


def pair_link(nonce=None):
    return f"http://127.0.0.1:{PORT}/#pair={nonce or pair_mint()}"


def pair_redeem(nonce):
    """True once for a good, unexpired nonce; False for anything else (the nonce is gone either way); None when too many wrong ones came lately."""
    now = time.time()
    d = STATE / "pair"
    want, hit = _sha(nonce), None
    try:
        for f in d.iterdir():
            if hmac.compare_digest(f.name, want):                          # constant time over every pending nonce
                hit = f
    except OSError:
        pass
    # The counter slows GUESSING; it must never lock the owner out. Any page can POST junk nonces to this port, so a real link is
    # always tried first and the counter only answers the ones that matched nothing (round-2 audit: a 10-per-minute lockout was a DoS).
    with _PAIR_LOCK:
        _PAIR_FAILS[:] = [t for t in _PAIR_FAILS if now - t < 60]
        if hit is None and len(_PAIR_FAILS) >= 10:
            return None
    ok = False
    if hit is not None:
        try:
            exp = float(hit.read_text() or 0)
            hit.unlink()                                                   # single use: if two requests race, one unlink fails
            ok = exp >= now
        except (OSError, ValueError):
            ok = False
    if not ok:
        with _PAIR_LOCK:
            _PAIR_FAILS.append(now)
    return ok


def _sessions():
    """The sessions, re-read whenever the file changed: `qtdeck dashboard sessions revoke` (another process) rewrites it, and a running server must obey at once."""
    f = STATE / "dashboard.sessions.json"
    try:
        st = f.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    if _SESSIONS["map"] is None or _SESSIONS.get("stamp") != stamp:
        try:
            m = json.loads(f.read_text(errors="replace"))                  # not read_json: sessions are not project data, and pairing must work in demo mode
        except Exception:
            m = {}
        _SESSIONS["map"] = m if isinstance(m, dict) else {}
        _SESSIONS["stamp"] = stamp
    return _SESSIONS["map"]


def _sessions_save(m):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        _private_write(STATE / "dashboard.sessions.json", json.dumps(m))
        st = (STATE / "dashboard.sessions.json").stat()
        _SESSIONS["stamp"] = (st.st_mtime_ns, st.st_size)
    except OSError:
        pass                                                           # the session still works until the next restart


def sessions_revoke():
    """End every paired session: the file is emptied. A running server notices (see _sessions); `qtdeck dashboard sessions revoke` calls this."""
    STATE.mkdir(parents=True, exist_ok=True)
    _private_write(STATE / "dashboard.sessions.json", "{}")


def session_end(sid):
    with _SESSIONS_LOCK:
        m = _sessions()
        m.pop(_sha(sid), None)
        _sessions_save(m)


def session_renew(sid):
    with _SESSIONS_LOCK:
        v = _sessions().get(_sha(sid))
        if isinstance(v, dict):
            v["exp"] = time.time() + SESSION_TTL
            _sessions_save(_sessions())


def session_new():
    """-> (session id for the cookie, API token for the page). Only a hash of the id is kept."""
    sid, token = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with _SESSIONS_LOCK:
        m, now = _sessions(), time.time()
        for k in [k for k, v in m.items() if not isinstance(v, dict) or v.get("exp", 0) < now]:
            del m[k]
        while len(m) >= SESSIONS_MAX:
            del m[min(m, key=lambda k: m[k].get("exp", 0))]
        m[_sha(sid)] = {"token": token, "exp": now + SESSION_TTL}
        _sessions_save(m)
    return sid, token


def session_get(sid):
    """The session behind a cookie value, or None."""
    if not sid or len(sid) > 200:
        return None
    with _SESSIONS_LOCK:
        v = _sessions().get(_sha(sid))
    return v if isinstance(v, dict) and v.get("exp", 0) >= time.time() else None


def project_roots():
    """The folders a project may live under: QUARTERDECK_PROJECT_ROOTS in config/quarterdeck.env (colon-separated), else your home directory."""
    raw = env_flag("QUARTERDECK_PROJECT_ROOTS", "")
    out = []
    for part in [x for x in raw.split(":") if x.strip()] or [str(Path.home())]:
        try:
            out.append(Path(part.strip()).expanduser().resolve())
        except OSError:
            pass
    return out


def check_project_folder(raw, what="a project", whole=True):
    """The real folder `raw` names, or ValueError saying where projects may live. It must sit under an allowed root and no part of
    the path below that root may be a dot folder (.ssh, .aws, .config ...). Symlinks are followed first, so a link cannot lead out.
    With whole (the project folder itself, not the folder a new one goes in): not an allowed root, not the home folder, and neither
    the program folder, the data folder, nor a folder that holds either of them."""
    roots = project_roots()
    try:
        real = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise ValueError(f"{raw} is not a usable folder name")
    for r in roots:
        try:
            rel = real.relative_to(r)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            raise ValueError(f"{raw} is inside a hidden folder, which {what} may not be")
        if whole and (real == r or real == Path.home().resolve()):
            raise ValueError(f"{raw} is a whole folder of projects, not one project. Choose the project's own folder inside it")
        if any(real == x or x in real.parents or (whole and real in x.parents) for x in (ROOT.resolve(), HOME.resolve())):
            raise ValueError(f"{raw} is, holds or sits inside Quarterdeck's own program or data folder, which {what} may not be")
        return real
    where = ", ".join(str(r) for r in roots)
    raise ValueError(f"{raw} is outside the places {what} may live ({where}). To allow another, set QUARTERDECK_PROJECT_ROOTS in your config/quarterdeck.env (folders separated by a colon)")


def log_field(x):
    """One log line stays one line: control characters and line breaks become a space, and the field is cut short."""
    return re.sub(r"[\x00-\x1f\x7f  ]+", " ", str(x))[:120]


# Demo mode: a made-up world (bin/demo.py) answers every /api request instead of
# the real one. It is server-wide, not per request: the page makes a dozen kinds
# of request and one of them forgetting a header would leak the real data onto a
# screen, so there is exactly one switch (QUARTERDECK_DEMO=1, or the token-protected
# POST /api/demo) and every real reader and writer below refuses while it is on.
_spec = importlib.util.spec_from_file_location("quarterdeck_demo", Path(__file__).resolve().parent / "demo.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)
_mspec = importlib.util.spec_from_file_location("quarterdeck_demo_maker", Path(__file__).resolve().parent / "demo_maker.py")
_demo_maker = importlib.util.module_from_spec(_mspec)
_mspec.loader.exec_module(_demo_maker)
demo.World.MAKER = _demo_maker.Maker            # made-up briefs, mock-ups and a sprint plan; in memory, like the rest of the demo world
DEMO = {"world": None}


def demo_on():
    return DEMO["world"] is not None


def no_demo(what):
    if DEMO["world"] is not None:
        raise RuntimeError(f"demo mode is on: refusing to {what}")


def demo_set(on, restart=False):
    if on and (DEMO["world"] is None or restart):
        DEMO["world"] = demo.World()
    elif not on:
        DEMO["world"] = None


# ---- extensions ---------------------------------------------------------------
# An optional add-on is one file, bin/ext_<name>.py, with one function, install(core). It is handed this module's own
# names (read live, so a test that moves STATE moves it too) and fills the hooks below; nothing in this file knows what
# any add-on is, and with none present every list here is empty and the dashboard is exactly what it is without them.
#   state      key -> fn(): added to /api/state          health     key -> fn(now): added to /api/health
#   attention  fn(ack) -> inbox items (see inbox_items)   events     fn(cutoff) -> timeline events
#   post       "/api/path" -> fn(body), raises ValueError for a 400
#   start      fn(): background loops, run when the server starts
#   scripts    "/assets/ext-x.js": page scripts served with the page (the page's own hooks are described in index.html)
#   words, misheard                      speech vocabulary and mishearings
#   commands, describe, rules, schema, shots, vet     what Helm's local model may say beyond the built-in commands
EXT = {"state": {}, "health": {}, "attention": [], "events": [], "post": {}, "start": [], "scripts": [],
       "words": [], "misheard": [], "commands": [], "describe": [], "rules": [], "schema": [], "shots": [], "vet": {}}


class _Core:
    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None


def load_extensions():
    """Import every bin/ext_*.py next to this file and let it install itself. One that fails to load is logged and skipped, never fatal."""
    loaded = []
    for f in sorted(Path(__file__).resolve().parent.glob("ext_*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.install(_Core())
            loaded.append(mod)
        except Exception as e:
            log_error(f"extension {f.stem}", e)
    return loaded


def valid_id(x):
    """Every id that becomes a path under state/ passes here, and nowhere else."""
    return isinstance(x, str) and bool(SAFE_ID.match(x)) and ".." not in x
EVERY = re.compile(r"^(\d{1,4})([mhd])$")
AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path, default):
    """A missing, truncated or garbage file gives the default. So does valid JSON
    of the wrong shape (a list where a dict belongs), and a list drops any entry
    that is not an object: every list kept in state/ is a list of records."""
    no_demo(f"read {path}")
    try:
        got = json.loads(Path(path).read_text(errors="replace"))
    except Exception:
        return default
    if isinstance(default, (list, dict)):
        if not isinstance(got, type(default)):
            return default
        if isinstance(got, list):
            return [x for x in got if isinstance(x, dict)]
    return got


def write_json(path, data):
    no_demo(f"write {path}")
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


STARTED = time.time()
HEARTBEAT = {}                  # loop name -> (last beat, declared seconds between beats)
LOOP_BACKOFF_MAX = 60
LOOP_TICK_MAX = 60              # a run_loop wait is never asked for in one go beyond this,
                                 # so a long interval still notices within one tick that the
                                 # wall clock has already passed its deadline (the machine
                                 # slept through the rest) instead of waiting out the whole interval
LAST_BUILD = {"at": None}       # when /api/state last built successfully


def log_error(where, exc):
    """One timestamped line in logs/dashboard-server.log. Never raises: the
    thing that reports a failure must not be a second failure."""
    try:
        LOGS.mkdir(exist_ok=True)
        with open(LOGS / "dashboard-server.log", "a") as f:
            f.write(f"{iso(now_utc())} ERROR {where}: {type(exc).__name__}: {str(exc)[:300]}\n")
    except Exception:
        pass


def run_loop(name, interval, step, sleep=time.sleep, clock=time.time):
    """Run step() forever. It beats a heartbeat each pass, and an exception is
    logged, backed off (bounded) and survived, never fatal. step may return the
    seconds to sleep; interval is what /api/health expects between beats.
    The wait between passes is taken in ticks bounded by LOOP_TICK_MAX against a
    wall-clock deadline, so a wait the machine slept through is noticed at the
    next tick rather than only after the whole wait has re-elapsed on waking."""
    fails = 0
    while True:
        HEARTBEAT[name] = (clock(), interval)
        delay = interval
        try:
            got = step()
            if isinstance(got, (int, float)):
                delay = got
            fails = 0
        except Exception as e:
            fails += 1
            log_error(f"{name} loop", e)
            delay = max(interval, min(interval * 2 ** (fails - 1), LOOP_BACKOFF_MAX))   # never faster than the normal pace
        deadline = clock() + delay
        remaining = delay
        while remaining > 0:
            if sleep(min(remaining, LOOP_TICK_MAX)):   # a truthy return (e.g. WAKE.wait) means woken early, not just timed out
                break
            remaining = deadline - clock()


def loops_view(now=None):
    now = now or time.time()
    return {n: {"age_seconds": round(now - t), "alive": now - t <= 3 * every}
            for n, (t, every) in sorted(HEARTBEAT.items())}


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return None


_COMMIT = {"at": 0.0, "v": None}


def git_commit():
    """The short commit this program runs. /api/health is answered to any page without pairing, so the answer is kept for 30 seconds instead of
    starting a git process per request (and git runs with the safe flags, in the program's own folder)."""
    now = time.time()
    if now - _COMMIT["at"] < 30:
        return _COMMIT["v"]
    try:
        r = subprocess.run(["git", *_safegit.flags(), "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                           text=True, timeout=2)
        v = r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        v = None
    _COMMIT.update(at=now, v=v)
    return v


def health():
    """Liveness and nothing else: no paths, no contents, no environment."""
    now = time.time()
    loops = loops_view(now)
    writable = {"state": os.access(STATE, os.W_OK), "logs": os.access(LOGS, os.W_OK)}
    age = lambda t: None if t is None else round(now - t)
    return {
        "ok": all(v["alive"] for v in loops.values()) and all(writable.values()),
        "uptime_seconds": round(now - STARTED),
        "commit": git_commit(),
        "loops": loops,
        "writable": writable,
        "disk_free_bytes": free_bytes(STATE if STATE.is_dir() else ROOT),
        "last_state_build_age_seconds": age(LAST_BUILD["at"]),
        "helpers": {"llm": LLM.running(), "tts": TTS.running()},
        **{k: f(now) for k, f in EXT["health"].items()},
    }


def relocate_state(root):
    """Point every state path at root (a temp copy for tests); returns what to
    hand back to restore_state. Logs move too, so a test never writes the real ones."""
    names = {"STATE": root, "LOGS": root.parent / (root.name + "-logs"), "PANELS": root / "panels",
             "SCHEDULES_FILE": root / "schedules.json", "MISSIONS_FILE": root / "missions.json",
             "INBOX_ACK_FILE": root / "inbox_ack.json", "SHOWCASE_FILE": root / "showcase.json",
             "FIXES": root / "fixes", "CYCLES": root / "cycles", "FIXQ": root / "fixqueue", "USAGE_MARK": root / "usage-limit",
             "SPEND": root / "spend.jsonl", "CAPTURE": root / "capture.jsonl",
             "CONNECTORS": root / "connectors"}
    g = globals()
    saved = {k: g[k] for k in names}
    g.update(names)
    return saved


def restore_state(saved):
    globals().update(saved)


def with_file_lock(path, fn):
    """Run fn() with a short mkdir-spinlock held on path — the same lock file
    and the same convention lib.sh's with_file_lock uses, so a dashboard write
    and a duty's own record_run cannot race on the same shared JSON file. The
    dashboard is threaded (a slow GitHub call must not stall the poll), so a
    write it makes itself needs the same guard a concurrent bash writer gets.
    """
    lock = Path(str(path) + ".lock")
    tries = 0
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            tries += 1
            if tries >= 200:
                try:
                    lock.rmdir()   # stale after 10s of contention; always empty
                except OSError:
                    pass
            else:
                time.sleep(0.05)
    try:
        return fn()
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


RUNS_KEPT = 2000      # the ledger keeps this many rows (lib.sh keeps the same), so a 7 day timeline has something to draw


def record_run_row(project, duty, verdict, detail="", url=""):
    """The dashboard's own equivalent of lib.sh's record_run, for the rare
    write the dashboard makes directly rather than through a duty (merging a
    PR is the one so far). Same file, same lock, so it cannot race a duty's
    own write to it."""
    def _append():
        runs = read_json(STATE / "runs.json", [])
        if not isinstance(runs, list):
            runs = []
        runs.append({"project": project, "duty": duty, "verdict": verdict,
                     "detail": detail, "url": url, "at": iso(now_utc())})
        write_json(STATE / "runs.json", runs[-RUNS_KEPT:])
    with_file_lock(STATE / "runs.json", _append)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def running_locks():
    """{lock_name: {pid, since, what}} for locks whose process is actually alive.

    A lock whose pid is dead is stale, not running — reporting it as running is
    how a dashboard starts lying after a crash.
    """
    out = {}
    if not STATE.is_dir():
        return out
    for lock in STATE.glob("*.lock"):
        if not lock.is_dir():
            continue
        pidfile = lock / "pid"
        try:
            pid = pidfile.read_text().strip()
        except Exception:
            continue
        if pid and pid_alive(pid):
            what = ""
            try:
                what = (lock / "what").read_text().strip()
            except Exception:
                pass
            # Set only for a duty a fix pipeline started for itself — the same
            # tag that row's own ledger entries carry — so the dashboard can
            # tell this lock and that fix's own card are the same operation.
            fixrun = ""
            try:
                fixrun = (lock / "fixrun").read_text().strip()
            except Exception:
                pass
            out[lock.stem] = {
                "pid": int(pid),
                "since": iso(datetime.fromtimestamp(pidfile.stat().st_mtime, timezone.utc)),
                "what": what,
                "fixrun": fixrun or None,
            }
    return out


def duty_locks(duty, pname, locks, projects=()):
    """Every live lock belonging to this duty on this project.

    Usually none or one, but several duties now lock per target (an issue, a
    PR) rather than per project, so more than one can be alive at once.
    A lock belongs to the longest registered project name that prefixes it:
    "shipwright-wayfarer-mobile-13" is wayfarer-mobile's, not harvest-pipeline's.
    """
    prefix = f"{duty}-{pname}"
    longer = [f"{duty}-{q}" for q in projects if q != pname and q.startswith(pname + "-")]
    own = lambda k, pre: k == pre or k.startswith(pre + "-")
    return {k: v for k, v in locks.items() if own(k, prefix) and not any(own(k, l) for l in longer)}


def header_summary(path, prefix_strip=True):
    try:
        line = path.read_text().splitlines()[1]
        s = re.sub(r"^#\s*", "", line)
        return re.sub(r"^[\w-]+\s+—\s*", "", s) if prefix_strip else s
    except Exception:
        return ""


def duty_list():
    if not DUTIES.is_dir():
        return []
    return [
        {"name": f.stem, "summary": header_summary(f, prefix_strip=False),
         "role": header_summary(f)}
        for f in sorted(DUTIES.glob("*.sh")) if not f.name.startswith("_")
    ]


def crew_list():
    """Personas are data; the dashboard reads the same files the panel does."""
    out = []
    if not CREW.is_dir():
        return out
    for f in sorted(CREW.glob("*.md")):
        if f.name.startswith("_"):
            continue
        meta = {}
        try:
            text = f.read_text()
            if text.startswith("---"):
                fm = text.split("---", 2)[1]
                for line in fm.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
        except Exception:
            pass
        out.append({
            "name": f.stem,
            "discipline": meta.get("discipline", ""),
            "panels": [d.strip() for d in meta.get("discipline", "").split(",") if d.strip()],
            "seat": meta.get("seat", ""),
            "bias": meta.get("bias", ""),
        })
    return out


def mark_superseded(panels):
    """A newer panel of the same kind, on the same project and target, replaces
    an older one — without anyone having to archive anything.

    A panel is a snapshot of the code the night it ran; nothing crosses items off
    as they get fixed. The next run on the same target re-reads the code, so a
    fixed item simply is not in it. That makes the newest completed panel the
    current list and every earlier attempt history — including one that failed,
    once a later run of the same question succeeded. A failure NEWER than the
    last success stays visible: that is news, not history.
    """
    newest_done = {}
    for p in panels:
        if p["status"] != "done":
            continue
        key = (p["project"], p["discipline"], p["subject"])
        if key not in newest_done or (p["started"] or "") > (newest_done[key]["started"] or ""):
            newest_done[key] = p
    for p in panels:
        cur = newest_done.get((p["project"], p["discipline"], p["subject"]))
        p["superseded_by"] = None
        if cur and cur["id"] != p["id"] and p["status"] != "running" \
                and (p["started"] or "") < (cur["started"] or ""):
            p["superseded_by"] = cur["id"]
    return panels


def panel_list(limit=25, locks=None, filed=None):
    """Recent panels, newest first.

    A transcript records its own status, which means a panel whose process was
    killed still claims to be arguing. Cross-check against the live locks for
    the same reason the lock list is cross-checked against pids: a dashboard
    that keeps a dead run on screen is worse than one that shows nothing.
    """
    if not PANELS.is_dir():
        return []
    locks = locks if locks is not None else running_locks()
    filed = filed or {}
    out = []
    for f in sorted(PANELS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        t = read_json(f, None)
        if not isinstance(t, dict):
            continue
        try:
            status = t.get("status")
            if status == "running" and f"panel-{t.get('project')}" not in locks:
                status = "abandoned"
            items = t.get("items") or []
            stances = t.get("stances") or []
            ruling = t.get("ruling") or []
            # Who disputed whom, and how often. A panel card that says only
            # "3 disputed" hides the one thing a panel is for.
            seat_of = {i.get("id"): i.get("seat") for i in items}
            pairs = {}
            for st in stances:
                if st.get("stance") != "dispute":
                    continue
                target = seat_of.get(st.get("id"))
                if target and st.get("by"):
                    pairs[(st["by"], target)] = pairs.get((st["by"], target), 0) + 1
            top = max(pairs.items(), key=lambda kv: kv[1]) if pairs else None
            out.append({
                "id": t.get("id"),
                "project": t.get("project"),
                "discipline": t.get("discipline"),
                "mode": t.get("mode"),
                "subject": t.get("subject"),
                "headline": t.get("headline"),
                "status": status,
                "phase": t.get("phase"),
                "started": t.get("started"),
                "finished": t.get("finished"),
                "seats": t.get("seats") or [],
                "doc": Path(t["doc"]).name if t.get("doc") else None,
                "filed": filed.get(Path(t["doc"]).name) if t.get("doc") else None,
                "raised": len(items),
                "disputed": sum(1 for s in stances if s.get("stance") == "dispute"),
                "top_dispute": ({"by": top[0][0], "against": top[0][1], "n": top[1]}
                                if top else None),
                "kept": len(ruling),
            })
        except Exception as e:      # one malformed transcript must not hide the rest
            log_error(f"panel {f.name}", e)
    return mark_superseded(out)


FIXES = STATE / "fixes"
CYCLES = STATE / "cycles"


def fix_index(locks):
    """{ "<panel>#<item>": record } for every ruling item anyone tried to fix.

    Cross-checked against the live lock the same way panel transcripts are: a
    record still saying "running" with no live pipeline behind it was killed,
    and a button that keeps saying "Fixing…" about a dead process is how you
    end up waiting for nothing.
    """
    out = {}
    if not FIXES.is_dir():
        return out
    for f in FIXES.glob("*.json"):
        r = read_json(f, None)
        if not isinstance(r, dict) or not r.get("panel"):
            continue
        # Several fixes can now run on the same project at once, each on its own
        # item, so staleness is checked against the exact lock this one took
        # (written alongside it) — a project-wide guess would call item B's
        # record stale just because it's item A that's still running.
        # Records written before this carried no lock name; assume alive rather
        # than falsely marking history as abandoned.
        if r.get("status") == "running" and r.get("lock") and r["lock"] not in locks:
            r["status"] = "abandoned"
        out[f'{r["panel"]}#{r.get("item")}'] = r
    return out


# ---- cycles: the run records `qtdeck cycle` keeps in state/cycles/<id>.json ------------
# The records are read only. The one thing the dashboard can do is start a cycle, and only through POST /api/cycle/start
# (start_cycle below), on a project that opted in with "cycle": true. It cannot resume or stop one. A record that still says
# "running" with no live lock behind it was killed, and is shown as failed, like a fix record in the same position.
def cycle_lock_name(r):
    """The lock `qtdeck cycle` holds while a cycle runs: cycle-<project>-<issue>, or cycle-<project>-t<ticket> for a local ticket (record field "ticket")."""
    key = f"t{r['ticket']}" if isinstance(r.get("ticket"), int) and not isinstance(r.get("ticket"), bool) else r.get("issue")
    return f"cycle-{r.get('project')}-{key}"


def cycle_record(cid, locks):
    if not valid_id(cid):
        return None
    r = read_json(CYCLES / f"{cid}.json", None)
    if not isinstance(r, dict) or r.get("kind") != "cycle":
        return None
    if r.get("status") == "running" and cycle_lock_name(r) not in locks:
        r = {**r, "status": "failed",
             "final": r.get("final") or f"stopped before it finished; resume with: qtdeck cycle --resume {cid}"}
    return r


def cycles_summary(locks, limit=12):
    """The newest cycles, one small row each, for the Mission list. Caulker's own counters live in the same folder and are skipped."""
    out = []
    if CYCLES.is_dir():
        for f in sorted(CYCLES.glob("cyc-*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
            r = cycle_record(f.stem, locks)
            if r:
                out.append({"id": r.get("id"), "project": r.get("project"), "issue": r.get("issue"), "ticket": r.get("ticket"), "branch": r.get("branch"), "title": r.get("title") or "",
                            "status": r.get("status"), "apply": bool(r.get("apply")), "started": r.get("started"),
                            "finished": r.get("finished"), "cost": round(float(r.get("cost") or 0), 4), "pr": r.get("pr")})
    return out


CYCLE_FIXTURE_COST = 7        # the first measured full run (a one-button change) cost about this many dollars; shown only as "about"


def cycle_estimate_calc(totals, ceiling, budget, spent):
    """Pure. What a cycle is expected to cost. `totals` are the totals of this project's own finished cycles. With none, there is no
    number to compute, so the answer says so and gives the one measured run as a rough guide; it never invents a range."""
    out = {"ceiling": ceiling, "daily_budget": budget, "spent_today": round(spent, 2),
           "daily_left": None if budget is None else round(max(0.0, budget - spent), 2)}
    t = sorted(float(x) for x in totals if isinstance(x, (int, float)) and x > 0)
    if t:
        n = len(t)
        out.update(basis="own", runs=n, min=round(t[0], 2), median=round(t[n // 2] if n % 2 else (t[n // 2 - 1] + t[n // 2]) / 2, 2), max=round(t[-1], 2))
    else:
        out.update(basis="default", runs=0, typical=CYCLE_FIXTURE_COST,
                   note="no runs of its own yet; the first measured run cost about 7 dollars for a small change; the ceiling is QUARTERDECK_CYCLE_BUDGET")
    return out


def cycle_ceiling():
    try:
        v = float(env_flag("QUARTERDECK_CYCLE_BUDGET", "") or 15)
        return v if v > 0 else 15.0
    except ValueError:
        return 15.0


def cycle_estimate(project, records=None):
    """Reads this project's finished cycles (a full pass: the record reached 'awaiting-review'), the ceiling and today's budget."""
    if records is None:
        records = []
        if CYCLES.is_dir():
            for f in CYCLES.glob("cyc-*.json"):
                r = read_json(f, None)
                if isinstance(r, dict) and r.get("kind") == "cycle":
                    records.append(r)
    mine = [r.get("cost") for r in records if r.get("project") == project and r.get("apply") and r.get("status") == "awaiting-review"]
    return cycle_estimate_calc(mine, cycle_ceiling(), daily_budget(), spent_today())


def start_cycle(project, issue, confirm, ticket=None):
    """Start `qtdeck cycle <project> --issue <n> --apply`, or `--ticket <n> --apply` for a LOCAL ticket (exactly one of the two), detached, the way a
    duty is started. The record (and so the id) is made by the script a moment after it starts; wait briefly for it. Nothing here merges or
    pushes: that is the script's own rule. A ticket cycle ends at a local branch for the owner to review."""
    no_demo("start a cycle")
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or project not in projects:
        raise ValueError("unknown project")
    if projects[project].get("cycle") is not True:
        raise ValueError(f"'{project}' has not opted in to full cycles: add \"cycle\": true to its registry entry")
    if ticket is not None and issue is not None:
        raise ValueError("start a cycle from an issue or from a ticket, not both")
    if ticket is not None:
        if type(ticket) is not int or not 0 < ticket < 10**9:
            raise ValueError("bad ticket")
        import tickets as _tk
        try:
            t = _tk.get(project, ticket)
        except _tk.TicketError as e:
            raise ValueError(str(e))
        if t.get("source") == "github":
            raise ValueError(f"ticket {ticket} is GitHub issue #{t.get('issue')}: start the cycle from the issue")
        if t.get("status") not in ("open", "building"):
            raise ValueError(f"ticket {ticket} is {t.get('status')}: a cycle starts from an open ticket")
        key, lock, what = f"t{ticket}", f"cycle-{project}-t{ticket}", f"ticket #{ticket}"
    else:
        if type(issue) is not int or not 0 < issue < 10**7:
            raise ValueError("bad issue")
        key, lock, what = str(issue), f"cycle-{project}-{issue}", f"#{issue}"
    if confirm is not True:
        raise ValueError("a cycle spends money and writes a branch" + ("" if ticket is not None else " and a pull request") + ": confirm it")
    if lock in running_locks():
        raise ValueError(f"a cycle for {what} on {project} is already running")
    b = daily_budget()
    if b is not None and spent_today() >= b:
        raise ValueError(f"today's budget is spent (${spent_today():.2f} of ${b:.2f}); a cycle would stop at once")
    if ticket is not None:
        argv = _tk.argv_cycle(project, ticket, apply=True)
    else:
        argv = [str(ROOT / "bin" / "qtdeck"), "cycle", project, "--issue", str(issue), "--apply"]
    LOGS.mkdir(exist_ok=True)
    out = open(LOGS / f"cycle-{project}.log", "a")
    out.write(f"\n[{iso(now_utc())}] started by dashboard: {' '.join(argv[2:])}\n")
    out.flush()
    t0 = time.time()
    subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT), start_new_session=True)
    cid = None
    for _ in range(40):                       # up to 4 s for the script to write its record
        time.sleep(0.1)
        for f in CYCLES.glob(f"cyc-*-{key}-*.json") if CYCLES.is_dir() else []:
            r = read_json(f, None)
            if not isinstance(r, dict) or r.get("project") != project or f.stat().st_mtime < t0 - 1:
                continue
            if (r.get("ticket") == ticket) if ticket is not None else (r.get("issue") == issue and not isinstance(r.get("ticket"), int)):
                cid = r.get("id"); break
        if cid:
            break
    return {"started": f"cycle {project} " + (f"--ticket {ticket}" if ticket is not None else f"--issue {issue}"), "id": cid}


# ---- status from GitHub ---------------------------------------------------------
# A ruling item is done when its pull request merges, whoever opened it. The
# fix pipeline only knows the PRs it opened itself, and only that it opened
# them; so the item's status is read back from GitHub, through links that are
# facts rather than prose: the PR closes the issue Quarterdeck filed for the item,
# it is the PR already on the item's record, or its body names the item as
# <panel-id>#<n>. "Fixes items 21, 24" is not parsed: numbers in prose are
# exactly how an item gets credited for someone else's fix.
PR_STATUS = {"MERGED": "merged", "OPEN": "pr", "CLOSED": "closed"}
SYNC_EVERY = 600
_last_sync = [0.0]


def reconcile_fixes(project, prs, rulings, fixes):
    """Pure: {key: record} for every item whose status GitHub changes.

    prs: `gh pr list --state all` rows. rulings: {panel_id: [ruling items]}.
    fixes: fix_index(). A running fix is left alone; it writes its own record."""
    by_url = {p.get("url"): p for p in prs}
    closing = {}
    for p in prs:
        for i in p.get("closingIssuesReferences") or []:
            closing.setdefault(i.get("number"), []).append(p)
    rank = {"MERGED": 2, "OPEN": 1, "CLOSED": 0}
    out = {}
    for pid, ruling in rulings.items():
        named = {}
        for p in prs:
            # Bounded both sides: "xa#1" and "x-a#1" do not name panel "a".
            for m in re.findall(r"(?<![\w.-])" + re.escape(pid) + r"#(\d+)\b", p.get("body") or ""):
                named.setdefault(int(m), []).append(p)
        for item in range(1, len(ruling) + 1):
            key = f"{pid}#{item}"
            rec = fixes.get(key)
            if rec and rec.get("status") == "running":
                continue
            cands = list(named.get(item, []))
            if rec and rec.get("pr") in by_url:
                cands.append(by_url[rec["pr"]])
            if rec and rec.get("issue"):
                cands += closing.get(rec["issue"], [])
            if not cands:
                continue
            best = max(cands, key=lambda p: (rank.get(p.get("state"), 0), p.get("number", 0)))
            status = PR_STATUS.get(best.get("state"))
            if not status or (rec and rec.get("status") == status and rec.get("pr") == best.get("url")):
                continue
            new = dict(rec) if rec else {
                "project": project, "panel": pid, "item": item,
                "title": ruling[item - 1].get("title", ""), "kind": "change",
                "tier": ruling[item - 1].get("tier"), "issue": None, "verdict": None,
                "started": None, "finished": None,
                "detail": f"fixed outside the fix pipeline, in #{best.get('number')}"}
            new.update(status=status, pr=best.get("url"), merged=best.get("mergedAt"))
            out[key] = new
    return out


_syncing = threading.Lock()


def sync_fix_status_soon():
    """From the scheduler: sync in a thread of its own, so a slow GitHub never
    holds up the fix queue, and never two at once."""
    if time.time() - _last_sync[0] >= SYNC_EVERY and not _syncing.locked():
        threading.Thread(target=sync_fix_status, daemon=True).start()


def sync_fix_status(force=False):
    """Read every project's pull requests once and write what changed."""
    if not force and time.time() - _last_sync[0] < SYNC_EVERY:
        return 0
    if not _syncing.acquire(blocking=False):
        return 0
    try:
        _last_sync[0] = time.time()
        return _sync_fix_status()
    finally:
        _syncing.release()


def _sync_fix_status():
    rulings = {}
    for f in PANELS.glob("*.json") if PANELS.is_dir() else []:
        t = read_json(f, None)
        if isinstance(t, dict) and t.get("ruling") and t.get("project"):
            rulings.setdefault(t["project"], {})[t.get("id") or f.stem] = t["ruling"]
    fixes = fix_index(running_locks())
    written = 0
    for project, repo in ((n, v.get("repo")) for n, v in read_json(PROJECTS_FILE, {}).items()):
        if not repo or project not in rulings:
            continue
        try:
            r = subprocess.run(["gh", "pr", "list", "-R", repo, "--state", "all", "--limit", "100",
                                "--json", "number,url,state,mergedAt,body,closingIssuesReferences"],
                               capture_output=True, text=True, timeout=60)
            prs = json.loads(r.stdout or "[]") if r.returncode == 0 else None
        except Exception:
            prs = None
        if prs is None:
            continue                      # one slow or failing repo does not stop the others
        for key, rec in reconcile_fixes(project, prs, rulings[project], fixes).items():
            f = FIXES / f'{rec["panel"]}-{rec["item"]}.json'
            # A fix may have started or finished while GitHub was being read.
            # Its own record wins; the next sync looks again.
            cur = read_json(f, None)
            if isinstance(cur, dict) and (cur.get("status") == "running"
                                          or cur.get("status") != (fixes.get(key) or {}).get("status")):
                continue
            FIXES.mkdir(parents=True, exist_ok=True)
            write_json(f, rec)
            written += 1
    return written


# ---- the fix queue ------------------------------------------------------------
# Each fix already runs in its own worktree and could go as fast as usage
# allows, but firing a whole batch at once would blow through it in one go —
# so pressing Fix this on several items, or Fix selected, lines them up here
# and the scheduler thread takes one at a time per project, in order, on
# purpose. A fix started some other way (a direct "Start work" click, a
# different queue) is not held up by this — only this queue's own next item
# waits for its own previous one. Kept per project in state/fixqueue/,
# machine-local like schedules.
FIXQ = STATE / "fixqueue"
USAGE_MARK = STATE / "usage-limit"
LIMIT_WAIT = 3600       # after a usage limit, wait this long before the next fix
START_GRACE = 30        # a pipeline just spawned has not taken its lock yet
MAX_LIMIT_RETRIES = 3
QLOCK = threading.Lock()


def load_q(project):
    q = read_json(FIXQ / f"{project}.json", None)
    if not isinstance(q, dict):
        return {"paused": False, "items": []}
    if not isinstance(q.get("items"), list):
        q = {**q, "items": []}
    if not all(isinstance(x, dict) for x in q["items"]):
        q = {**q, "items": [x for x in q["items"] if isinstance(x, dict)]}
    return q


def save_q(project, q):
    FIXQ.mkdir(parents=True, exist_ok=True)
    write_json(FIXQ / f"{project}.json", q)


def usage_hit():
    try:
        return datetime.fromisoformat(USAGE_MARK.read_text().strip().replace("Z", "+00:00"))
    except Exception:
        return None


def limit_until():
    """While set, nothing new starts: a fix begun now would hit the same limit."""
    hit = usage_hit()
    if not hit:
        return None
    until = hit + timedelta(seconds=LIMIT_WAIT)
    return until if until > now_utc() else None


def members(x):
    """The ruling items a queue entry covers: a batch lists them, a single has one."""
    return x.get("items") or [x["item"]]


def spawn_fix(project, panel, items, source):
    item = ",".join(str(int(n)) for n in items)
    _spawn_fix(project, ["--panel", panel, "--item", item], f"item {item} of {panel}", source)


def _spawn_fix(project, args, what, source):
    no_demo("start a fix")
    argv = [str(ROOT / "bin" / "qtdeck"), "fix", project, *args, "--apply"]
    LOGS.mkdir(exist_ok=True)
    out = open(LOGS / f"fix-{project}.log", "a")
    out.write(f"\n[{iso(now_utc())}] started by {source}: {what}\n")
    out.flush()
    subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     cwd=str(ROOT), start_new_session=True)


def start_work(project, issue, action):
    """The two buttons on a board card: analyse an issue, or start work on it.

    Neither takes anything from the request but a project name, an issue number
    and one of two words; the command is built here, as argv, never a shell line.
    Analysing is the purser run through spawn_run's own allowlist. Starting is
    `qtdeck fix --issue`, which is the same pipeline as Fix this from step 2, or
    on a project with a shipwright and no panel, the shipwright alone."""
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or project not in projects:
        raise ValueError("unknown project")
    if type(issue) is not int or not 0 < issue < 10**7:
        raise ValueError("bad issue")
    if action == "analyse":
        return spawn_run(project, "purser", ["--issue", str(issue)], apply_=True)
    if action != "start":
        raise ValueError("bad action")
    duties = projects[project].get("duties") or []
    if "shipwright" not in duties:
        raise ValueError(f"'shipwright' is not enabled for '{project}'")
    if "panel" not in duties:
        # No panel to plan it: the shipwright takes the issue straight to a pull
        # request, which is `qtdeck run <project> shipwright --issue N --apply`.
        return spawn_run(project, "shipwright", ["--issue", str(issue)], apply_=True)
    # what `fix` will run: both duties are enabled
    # One pipeline per issue, not per project — the builder isolates each in its
    # own worktree. Only this exact issue already being worked is refused, and
    # refused loudly here rather than left to die in a log nobody is reading.
    if any(r.get("status") == "running" and r.get("issue") == issue
           for r in fix_index(running_locks()).values()):
        raise ValueError(f"#{issue} is already being fixed")
    _spawn_fix(project, ["--issue", str(issue)], f"issue #{issue}", "the board")
    return f"fix {project} --issue {issue}"


def _ts(x):
    try:
        return datetime.fromisoformat((x or "").replace("Z", "+00:00"))
    except Exception:
        return None


def drain_fix_queues():
    """Start the next queued fix on every project that is free to take one.

    An item is only taken off the queue once its fix has reached a verdict of
    its own. If the usage limit was hit while it ran, it goes back to the head
    and the queue waits — so a limit halfway through twenty fixes costs time,
    not the other nineteen.

    "Free to take one" is per queue, not per project: several fixes can run on
    a project at once, each in its own worktree, so this only waits on ITS OWN
    previous item, never on an unrelated fix (a direct "Start work" click, or
    another project's queue) that happens to be running alongside it."""
    with QLOCK:
        if not FIXQ.is_dir():
            return
        fixes = fix_index(running_locks())
        waiting = limit_until() or over_budget()
        hit = usage_hit()
        for f in sorted(FIXQ.glob("*.json")):
            project, q, changed = f.stem, load_q(f.stem), False
            active = next((x for x in q["items"] if x.get("state") == "active"), None)
            # Any member speaks for its batch: labelling can drop the first
            # item (a decision), and then only the others have records.
            recs = [fixes.get(f'{active["panel"]}#{n}') or {} for n in members(active)] if active else []
            running = active and any(r.get("status") == "running" for r in recs)
            if active and not running:
                started = _ts(active.get("started"))
                if started and (now_utc() - started).total_seconds() < START_GRACE:
                    continue                                  # still starting up
                rec = next((r for r in recs if r.get("status") in ("pr", "merged")),
                           next((r for r in recs if r), {}))
                if hit and started and hit > started and rec.get("status") not in ("pr", "merged") \
                        and active.get("retries", 0) < MAX_LIMIT_RETRIES:
                    active.update(state="pending", started=None,
                                  retries=active.get("retries", 0) + 1)
                else:
                    q["items"].remove(active)
                active, changed = None, True
            if not active and not q.get("paused") and not waiting:
                head = next((x for x in q["items"] if x.get("state") == "pending"), None)
                if head:
                    try:
                        spawn_fix(project, head["panel"], members(head), "the fix queue")
                        head.update(state="active", started=iso(now_utc()))
                    except Exception as e:
                        head["error"] = str(e)[:200]
                        q["items"].remove(head)
                    changed = True
            if changed:
                save_q(project, q)


def queue_view():
    out = {}
    if not FIXQ.is_dir():
        return out
    waiting = limit_until()
    budget = over_budget()
    for f in sorted(FIXQ.glob("*.json")):
        q = load_q(f.stem)
        if not q["items"]:
            continue
        out[f.stem] = {"paused": bool(q.get("paused")),
                       "limit_until": iso(waiting) if waiting else None,
                       "over_budget": budget,
                       "items": [{**x, "position": i + 1} for i, x in enumerate(q["items"])]}
    return out


def enqueue(pid, items):
    """Queue ruling items for fixing. Returns (queued, skipped-with-reasons)."""
    t = read_json(PANELS / f"{pid}.json", None)
    if not t:
        raise ValueError("no such panel")
    project = t.get("project")
    if project not in read_json(PROJECTS_FILE, {}):
        raise ValueError("unknown project")
    ruling = t.get("ruling") or []
    newer = next((p["superseded_by"] for p in panel_list() if p["id"] == pid), None)
    if newer:
        raise ValueError("this panel was superseded by a later run — fix from that one")
    queued, skipped = [], []
    with QLOCK:
        q = load_q(project)
        fixes = fix_index(running_locks())
        inq = {(x["panel"], n) for x in q["items"] for n in members(x)}
        for n in items:
            if not isinstance(n, int) or not 1 <= n <= len(ruling):
                skipped.append({"item": n, "why": "no such item"}); continue
            rec = fixes.get(f"{pid}#{n}") or {}
            st = rec.get("status")
            it = ruling[n - 1]
            kind = it.get("kind") or ("change" if t.get("discipline") in ("design", "dev") else "decision")
            if kind != "change":
                skipped.append({"item": n, "why": f"labelled a {kind}, not a change"}); continue
            if (pid, n) in inq:
                skipped.append({"item": n, "why": "already queued"}); continue
            if st in ("pr", "merged", "taken", "nothing", "running"):
                why = {"pr": f"already has {rec.get('pr')}", "merged": f"fixed in {rec.get('pr')}",
                       "taken": "someone is already fixing it",
                       "nothing": "the crew found nothing to build", "running": "being fixed now"}[st]
                skipped.append({"item": n, "why": why}); continue
            queued.append(n)
        # Related items go out together: one branch, one pull request per area
        # of the ruling (all the copy items, all the accessibility items). One
        # PR per item arrived faster than anyone could verify them, and items
        # touching the same screen conflicted with each other.
        groups = {}
        for n in queued:
            # An item with no area is its own batch: blank is not a category.
            groups.setdefault(ruling[n - 1].get("area") or f"#{n}", []).append(n)
        for area, ns in groups.items():
            title = ruling[ns[0] - 1].get("title", "") if len(ns) == 1 \
                else f"{area or 'related'}: {len(ns)} fixes (items {', '.join(map(str, ns))})"
            q["items"].append({"panel": pid, "item": ns[0], "items": ns, "title": title,
                               "state": "pending", "queued": iso(now_utc()), "started": None})
        save_q(project, q)
    drain_fix_queues()
    return project, queued, skipped


# ---- spend ------------------------------------------------------------------------
SPEND = STATE / "spend.jsonl"


def spend_rows():
    return _spend.rows(SPEND)       # review r9 D4: the same reader as `qtdeck spend`, which drops a name field that is not text


def local_midnight_utc(days_ago=0):
    m = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return iso(m - timedelta(days=days_ago))


def spent_today(rows=None):
    since = local_midnight_utc()
    return sum(_spend._num(r.get("cost")) for r in (rows if rows is not None else spend_rows())
               if (r.get("at") or "") >= since)


def daily_budget():
    try:
        v = float(env_flag("QUARTERDECK_DAILY_BUDGET", "") or 0)
        return v if v > 0 else None
    except ValueError:
        return None


def over_budget():
    """Automatic work — the queue, schedules — starts nothing once today's
    spend reaches the daily budget. A run started by hand is never stopped."""
    b = daily_budget()
    return b is not None and spent_today() >= b


def spend_summary():
    rows = spend_rows()
    week = local_midnight_utc(6)
    wk = [r for r in rows if (r.get("at") or "") >= week]
    def group(key, src):
        return _spend.group(src, lambda r: r.get(key) or "unknown")
    by_day = {}
    for r in wk:
        try:
            day = datetime.fromisoformat(r["at"].replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
        except ValueError:
            continue
        by_day[day] = by_day.get(day, 0) + (r.get("cost") or 0)
    fixes = {}
    for r in rows:
        if r.get("fix"):
            f = fixes.setdefault(r["fix"], {"cost": 0.0, "calls": 0})
            f["cost"] += r.get("cost") or 0; f["calls"] += 1
    roles = {k.replace("QUARTERDECK_MODEL_", "").lower(): env_flag(k, "") or "account default"
             for k in ("QUARTERDECK_MODEL_FOREMAN", "QUARTERDECK_MODEL_SHIPWRIGHT", "QUARTERDECK_MODEL_SURVEYOR",
                       "QUARTERDECK_MODEL_INSPECTOR", "QUARTERDECK_MODEL_JOINER", "QUARTERDECK_MODEL_HARBOURMASTER",
                       "QUARTERDECK_MODEL_TRIALS")}
    tiers = {t: env_flag(f"QUARTERDECK_TIER_{t.upper()}", "") or "account default"
             for t in ("mechanical", "routine", "intricate", "hard")}
    return {
        "today": spent_today(rows), "week": sum(r.get("cost") or 0 for r in wk),
        "all": sum(r.get("cost") or 0 for r in rows), "calls": len(rows),
        "since": min((r["at"] for r in rows if r.get("at")), default=None),
        "daily_budget": daily_budget(), "over_budget": over_budget(),
        "call_budget": env_flag("QUARTERDECK_CALL_BUDGET", "") or None,
        "planning": env_flag("QUARTERDECK_FIX_PLANNING", "tiered"),
        "by_duty": group("duty", wk), "by_model": group("model", wk),
        "by_seat": _spend.group(wk, "seat"), "sinks": _spend.sinks(wk),
        "by_day": dict(sorted(by_day.items())), "fixes": fixes,
        "roles": roles, "tiers": tiers,
        "capped": sum(1 for r in wk if r.get("stopped") == "cap"),
    }


def filing_index(projects, runs):
    """Which document became which issues — and, honestly, which we cannot say.

    Three states, because two would require lying about the third. `filed` means
    we recorded the issue numbers. `filed-untracked` means the run ledger shows
    a foreman filed this document, but before the numbers were recorded.
    Everything else is genuinely unfiled.
    """
    out = {}
    for row in read_json(STATE / "filed.json", []):
        doc = row.get("document")
        if not doc:
            continue
        prev = out.setdefault(doc, {"state": "filed", "issues": [], "at": row.get("at")})
        prev["issues"].extend(row.get("issues") or [])
        prev["at"] = row.get("at")
    for r in runs:
        if r.get("duty") != "foreman" or r.get("verdict") != "FILED":
            continue
        for word in (r.get("detail") or "").split():
            if word.endswith(".md") and word not in out:
                out[word] = {"state": "filed-untracked", "issues": [], "at": r.get("at"),
                             "detail": r.get("detail")}
    return out


def project_of(name, projects):
    """Longest registered name that prefixes the file — "wayfarer-web-x.md" is
    wayfarer-web, not volt."""
    best = ""
    for p in projects:
        if name.startswith(p + "-") and len(p) > len(best):
            best = p
    return best or name.split("-")[0]


def doc_list(projects, filed, limit=60):
    if not WORKSPACE.is_dir():
        return []
    files = sorted(WORKSPACE.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{
        "name": f.name,
        "project": project_of(f.name, projects),
        "at": iso(datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)),
        "size": f.stat().st_size,
        "filed": filed.get(f.name),
    } for f in files[:limit]]


def speech_hints():
    """Words your speech recognizer should expect, and mishearings to correct, from your own optional config/speech.json:
    {"words": ["Acme"], "sounds_like": {"hair vest": "harvest"}}. Nothing is assumed when the file is absent."""
    d = read_json(HOME / "config" / "speech.json", {})
    d = d if isinstance(d, dict) else {}
    words = [w.strip()[:40] for w in (d.get("words") or []) if isinstance(w, str) and w.strip()][:50]
    pairs = d.get("sounds_like") if isinstance(d.get("sounds_like"), dict) else {}
    sounds = {str(k).strip()[:40]: str(v).strip()[:40] for k, v in list(pairs.items())[:20] if str(k).strip() and str(v).strip() and '"' not in str(k) + str(v)}
    return {"words": words, "sounds_like": sounds}


def misheard_note():
    """The sentence that tells the model which names speech to text tends to get wrong."""
    return ("names are often misheard: " + "; ".join(EXT["misheard"] + [f'"{k}" means {v}' for k, v in speech_hints()["sounds_like"].items()]
                                                     + ['"helm" is the assistant itself, not a project']) + ".\n")


def speech_vocab(names):
    return list(names) + speech_hints()["words"] + EXT["words"] + ["Helm", "shipwright", "surveyor", "ledger"]


def env_flag(name, default=""):
    """Read a value out of config/quarterdeck.env without sourcing it. Your own file in your data folder wins over the shipped defaults."""
    for base in dict.fromkeys((HOME, ROOT)):
        try:
            text = (base / "config" / "quarterdeck.env").read_text()
            m = re.search(rf'^{name}="\$\{{{name}:-([^}}]*)\}}"', text, re.M)
            if m:
                return os.environ.get(name, m.group(1))
        except Exception:
            continue
    return os.environ.get(name, default)


# ---- showcase -----------------------------------------------------------------
# The public boundary is enforced by what fields are allowed to exist here at
# all, not by redacting a copy of something richer: every field on a showcase
# item is text a person typed for a stranger to read. Nothing pulled from a
# panel, a run, a log or a prompt is ever in this record, so there is nothing
# in it that publishing could leak by accident. Still served only through this
# loopback-only process — nothing here opens the server to the network.
PUBLIC_SHOWCASE_FIELDS = ("id", "title", "summary", "before", "after", "role", "synthetic", "published_at")


def load_showcase():
    s = read_json(SHOWCASE_FILE, [])
    return s if isinstance(s, list) else []


def save_showcase(items):
    write_json(SHOWCASE_FILE, items)


def public_showcase():
    return [{k: s.get(k) for k in PUBLIC_SHOWCASE_FIELDS} for s in load_showcase() if s.get("status") == "published"]


def showcase_act(action, body, source):
    items = load_showcase()

    if action == "create":
        title = (body.get("title") or "").strip()
        if not title or len(title) > 200:
            raise ValueError("title must be 1-200 characters")
        rec = {
            "id": "s-" + secrets.token_hex(6), "title": title,
            "summary": (body.get("summary") or "").strip()[:1000],
            "before": (body.get("before") or "").strip()[:600],
            "after": (body.get("after") or "").strip()[:600],
            "role": (body.get("role") or "").strip()[:600],
            "synthetic": bool(body.get("synthetic")),
            "mission_id": body.get("mission_id") if isinstance(body.get("mission_id"), str) else None,
            "status": "draft", "published_at": None,
            "created_at": iso(now_utc()), "updated_at": iso(now_utc()),
            "events": [record_event("created", "draft created", source)],
        }
        items.append(rec)
        save_showcase(items)
        return rec

    s = next((x for x in items if x.get("id") == body.get("id")), None)
    if not s:
        raise ValueError("unknown showcase item")

    if action == "update":
        if s["status"] != "draft":
            raise ValueError("unpublish before editing")
        if "title" in body and not (body.get("title") or "").strip():
            raise ValueError("title must be 1-200 characters")
        for field, limit in (("title", 200), ("summary", 1000), ("before", 600), ("after", 600), ("role", 600)):
            if field in body:
                s[field] = (body.get(field) or "").strip()[:limit]
        if "synthetic" in body:
            s["synthetic"] = bool(body.get("synthetic"))
        s["updated_at"] = iso(now_utc())
        s["events"].append(record_event("edited", "draft edited", source))
    elif action == "publish":
        if s["status"] == "published":
            raise ValueError("already published")
        s["status"] = "published"
        s["published_at"] = iso(now_utc())
        s["events"].append(record_event("published", "made public through the showcase endpoint", source))
    elif action == "unpublish":
        if s["status"] != "published":
            raise ValueError("not published")
        s["status"] = "draft"
        s["published_at"] = None
        s["events"].append(record_event("unpublished", "access removed", source))
    else:
        raise ValueError("not something this can do")

    save_showcase(items)
    return s


# ---- inbox --------------------------------------------------------------------
# A deduplicated "needs you" list, computed fresh from the same sources the
# rest of the app already trusts — each add-on's own attention list (EXT["attention"]) and each
# project/duty's own most recent run. Nothing here is a separate ledger of
# problems that can drift from what is actually true right now.
BAD_VERDICTS = {"NEEDS_HUMAN", "BLOCKED", "ERROR", "FAILED", "STOPPED-CAP", "STOPPED-CEILING"}


def load_inbox_ack():
    a = read_json(INBOX_ACK_FILE, {})
    return a if isinstance(a, dict) else {}


def save_inbox_ack(d):
    write_json(INBOX_ACK_FILE, d)


def inbox_items(last_by_pair):
    """`last_by_pair` is already each project/duty's newest run (build_state
    computes it that way already), so a later good verdict is simply not in
    here — that IS how a resolved failure stops being unresolved, without a
    second place recording that it once was. An add-on's own items come from
    its EXT["attention"] source, handed the acknowledgements to mark its own."""
    ack = load_inbox_ack()
    items = []
    for source in EXT["attention"]:
        items += source(ack)
    cutoff = now_utc() - timedelta(hours=24)
    for (project, duty), r in last_by_pair.items():
        if (r.get("verdict") or "") not in BAD_VERDICTS:
            continue
        at = _ts(r.get("at"))
        if not at or at < cutoff:
            continue
        key = f"local:{project}:{duty}:{r['at']}"
        items.append({
            "id": key, "source": "local", "project": project, "duty": duty,
            "severity": r.get("verdict"), "text": r.get("detail") or r.get("verdict"),
            "at": r.get("at"), "stale": False, "acknowledged": key in ack,
        })
    return items


def inbox_act(action, body, source):
    if action != "acknowledge":
        raise ValueError("not something this can do")
    key = body.get("id")
    if not isinstance(key, str) or not key or len(key) > 300:
        raise ValueError("bad id")
    ack = load_inbox_ack()
    ack[key] = {"at": iso(now_utc()), "by": source, "text": (body.get("text") or "")[:500]}
    save_inbox_ack(ack)
    return {"id": key, "acknowledged": True}


# ---- mission focus: one piece of work, read-only -------------------------------
# Composed from state files that already exist (the panel transcript, the fix
# record, the run ledger, the inbox, the fix queue). Nothing is collected for it
# and nothing is written. A mission id names one of four things:
#   fix:<panel>#<item>   a ruling item taken through the fix pipeline
#   panel:<id>           a panel and its ruling
#   run:<at>|<project>|<duty>   one ledger row (a fix run is shown as its fix)
#   attn:<inbox id>      one needs-you entry from a connected source
#   cycle:<id>           one `qtdeck cycle` run, read from its record in state/cycles
NODES = (("brief", "Brief"), ("panel", "Panel"), ("build", "Build"), ("verify", "Verify"), ("review", "Review"))
FIX_STEP_NODE = {"filing": "brief", "planning": "panel", "building": "build", "reviewing": "verify", "verifying": "verify"}
FIX_STEP_TEXT = {
    "filing": "Filing the ruling item as a GitHub issue.",
    "planning": "A developer panel is writing a plan for the change.",
    "building": "The shipwright is building the change in its own worktree.",
    "reviewing": "A second agent is reading the diff.",
    "verifying": "The inspector is checking the change against the issue."}
FIX_FAILED = ("failed", "blocked", "abandoned")


def fix_nodes(r):
    """Pure: the five pipeline nodes of one fix record, or None when the record
    did not come from the fix pipeline (a pull request found on GitHub has no
    steps to show). A node's state is read from what the record holds, never guessed:

      Brief  = the pipeline's "filing" step      done once an issue is filed
      Panel  = "planning"                         done once a plan is recorded
      Build  = "building"                         done once a pull request is recorded
      Verify = "reviewing" + "verifying"          done once the inspector's verdict is recorded
      Review = you                                awaiting while the pull request is open, done when merged

    A running record shows its current step as active and the steps before it
    done. A finished record that stopped early shows the first missing node as
    blocked (failed, blocked, abandoned) or not started (nothing to build,
    taken by someone else). A pull request with no verdict shows Verify as skipped."""
    if not r.get("started"):
        return None
    st = r.get("status")
    out = []
    if st == "running":
        at = [k for k, _ in NODES].index(FIX_STEP_NODE.get(r.get("step"), "brief"))
        states = ["done"] * at + ["active"] + ["notstarted"] * (4 - at)
    else:
        shipped = st in ("pr", "merged", "closed")
        verdict = r.get("verdict") or ""
        have = {"brief": bool(r.get("issue")) or shipped, "panel": bool(r.get("plan")) or shipped,
                "build": bool(r.get("pr")) or shipped,
                "verify": bool(verdict) and not verdict.startswith("skipped")}
        states, stopped = [], False
        for key in ("brief", "panel", "build", "verify"):
            if stopped:
                states.append("notstarted")
            elif have[key]:
                states.append("done")
            elif key == "verify" and shipped:
                states.append("skipped")
            else:
                states.append("blocked" if st in FIX_FAILED else "notstarted")
                stopped = True
        states.append("done" if st == "merged" else "awaiting" if st == "pr"
                      else "skipped" if st == "closed" else "notstarted")
    notes = {
        "brief": f"Issue #{r['issue']} filed" if r.get("issue") else "",
        "panel": ("No developer panel needed" if str(r.get("plan") or "").startswith("the ruling item itself")
                  else "Plan written" if r.get("plan") else ""),
        "build": "Pull request opened" if r.get("pr") else "",
        "verify": f"Inspector: {r['verdict']}" if r.get("verdict") else "",
        "review": "Merged" if st == "merged" else "Pull request is open" if st == "pr"
                  else "Closed without merging" if st == "closed" else ""}
    for (key, label), state in zip(NODES, states):
        out.append({"id": key, "label": label, "state": state, "note": notes[key] if state != "notstarted" else ""})
    return out


def _fix_state(r):
    st = r.get("status")
    return ("running" if st == "running" else "awaiting" if st == "pr"
            else "blocked" if st in FIX_FAILED else "done")


def _fix_detail(r):
    st, d = r.get("status"), r.get("detail") or ""
    if st == "running":
        return "Working", FIX_STEP_TEXT.get(r.get("step"), "The fix is running.")
    if st == "pr":
        return "Waiting for you", "The pull request is open. Review it and merge it yourself; nothing here merges it for you."
    if st == "merged":
        return "Merged", d or "The pull request was merged."
    if st in FIX_FAILED:
        return {"blocked": "Not built"}.get(st, (st or "").capitalize()), d or "No reason was recorded."
    return {"nothing": "Nothing to build", "taken": "Taken by someone else", "closed": "Closed"}.get(st, st or "Recorded"), d


def _item_row(n, it, rec, pid):
    if not isinstance(it, dict):
        return None
    return {"n": n, "title": it.get("title"), "severity": it.get("severity"), "tier": it.get("tier"),
            "kind": it.get("kind") or "change", "claim": it.get("claim"), "where": it.get("where"),
            "action": it.get("action"), "support": it.get("support") or [], "overruled": it.get("overruled") or [],
            "note": it.get("note"), "fix": ({"status": rec.get("status"), "pr": rec.get("pr")} if rec else None),
            "mission": f"fix:{pid}#{n}"}


def _disputes(tx, limit=6):
    """Who disputed which item, in the seat's own words. From the transcript's stances."""
    seat_of = {i.get("id"): i for i in tx.get("items") or [] if isinstance(i, dict)}
    out = []
    for s in tx.get("stances") or []:
        if isinstance(s, dict) and s.get("stance") == "dispute" and s.get("by"):
            tgt = seat_of.get(s.get("id")) or {}
            out.append({"by": s.get("by"), "against": tgt.get("seat"), "item": tgt.get("title"), "note": s.get("note") or ""})
    return out[:limit]


def _open_decision(items):
    d = next((i for i in items if i and i["kind"] == "decision"), None)
    return None if not d else {"title": d["title"], "body": d["claim"], "ask": d["action"], "where": d["where"],
                               "options": [], "mission": d["mission"]}


CYCLE_GROUPS = (("brief", "Brief"), ("build", "Build"), ("review", "Review"), ("seal", "Seal"), ("human", "Human review"))
CYCLE_BAD = ("needs-human", "failed", "stopped-cap", "stopped-ceiling")


def _cycle_group(sid):
    return ("brief" if sid in ("purser", "panel") else "build" if sid in ("shipwright", "assayer")
            else "human" if sid == "human" else "seal" if sid.startswith("caulk") else "review")


def _money(x):
    return f"${float(x or 0):.2f}"


def cycle_nodes(r):
    """Pure: the five pipeline nodes of one cycle record. A node is read from the stages the record holds in it, never guessed:
    failed stage -> blocked, running -> active, nothing recorded or only 'would' -> not started, all skipped -> skipped, else done.
    A cycle that stopped for a person, a cap or a failure shows the group it stopped in as blocked."""
    stages = [x for x in r.get("stages") or [] if isinstance(x, dict)]
    status = r.get("status")
    out, state_of = [], {}
    for key, label in CYCLE_GROUPS:
        mine = [x for x in stages if _cycle_group(str(x.get("id") or "")) == key]
        real = [x for x in mine if x.get("state") not in ("would", "pending", None)]
        sts = [x.get("state") for x in real]
        if key == "human":
            st = "awaiting" if status == "awaiting-review" else "notstarted"
        elif "failed" in sts:
            st = "blocked"
        elif "running" in sts:
            st = "active"
        elif not real:
            st = "notstarted"
        elif all(v == "skipped" for v in sts):
            st = "skipped"
        else:
            st = "done"
        cost = sum(float(x.get("cost") or 0) for x in mine)
        done = [x for x in real if x.get("state") == "done"]
        note = ""
        if real:
            verdicts = sorted({str(x.get("verdict")) for x in done if x.get("verdict") and x.get("verdict") != "SKIPPED"})
            note = " · ".join(([", ".join(verdicts)] if verdicts else []) + ([_money(cost)] if cost else []))
        if key == "human" and st == "awaiting" and not note:
            note = "Read the local branch" if isinstance(r.get("ticket"), int) else "Read the pull request"
        if st == "skipped":
            note = str(next((x.get("detail") for x in real if x.get("detail")), "") or "").split(":")[0][:60]       # the short reason; the whole one is on the stage's own row
        state_of[key] = st
        out.append({"id": key, "label": label, "state": st, "note": note})
    if status in ("stopped-cap", "stopped-ceiling"):
        for n in out:
            if n["state"] in ("notstarted", "active") and n["id"] != "human":
                n["state"], n["note"] = "blocked", "Not started: stopped at the cap" if status == "stopped-cap" else "Not started: cycle ceiling"
                break
    elif status in ("needs-human", "failed"):
        started = [n for n in out if n["state"] in ("done", "blocked", "active") and n["id"] != "human"]
        if started and not any(n["state"] == "blocked" for n in out):
            started[-1]["state"] = "blocked"
    return out


def cycle_mission(r, out):
    """Fill the mission view of one cycle record `r` into `out`."""
    status = r.get("status") or "running"
    stages = [x for x in r.get("stages") or [] if isinstance(x, dict)]
    cost = float(r.get("cost") or 0)
    what = f"ticket #{r.get('ticket')}" if isinstance(r.get("ticket"), int) else f"#{r.get('issue')}"
    out.update(project=r.get("project"), title=f"Cycle · {what} {r.get('title') or ''}".strip(),
               mission_ref=f"cycle {r.get('id')}", pipeline=cycle_nodes(r), issue=r.get("issue") if isinstance(r.get("issue"), int) else None,
               state={"running": "running", "awaiting-review": "awaiting"}.get(status, "blocked" if status in CYCLE_BAD else "done"))
    running = next((x for x in stages if x.get("state") == "running"), None)
    local_done = isinstance(r.get("ticket"), int) and not isinstance(r.get("ticket"), bool) and isinstance(r.get("branch"), str) and r.get("branch")
    body = {"running": f"The cycle is working on {running.get('title') if running else 'its next stage'}.",
            "awaiting-review": (f"The crew built it on the local branch {r['branch']}, as one commit. Nothing was pushed and no pull request exists." if local_done else (r.get("final") or "")) + f" It cost {_money(cost)} in all.",
            "nothing": r.get("final") or "There was nothing to build.",
            "report-only": r.get("final") or "A report-only cycle: nothing was written."}.get(status, r.get("final") or "No reason was recorded.")
    title = {"running": "Working", "awaiting-review": "Waiting for you", "needs-human": "Needs a person", "failed": "Failed",
             "stopped-cap": "Stopped at the cap", "stopped-ceiling": "Stopped at the cycle ceiling", "nothing": "Nothing to build",
             "report-only": "Report only"}.get(status, status)
    if status in CYCLE_BAD:
        out["blocker"] = {"cause": body, "cls": None, "rerun": False}
        body = "The cycle stopped here. The stages that finished are on the record and are not repeated when it resumes."
    out["detail"] = {"title": title, "body": body}
    if isinstance(r.get("ticket"), int) and not isinstance(r.get("ticket"), bool):
        # a ticket cycle ends at a local branch: what the owner needs to review it, and one line of what is next (plain text; the page selects, never links, the command)
        branch = r.get("branch") if isinstance(r.get("branch"), str) else None
        review = str(r.get("review") or "")[:500]
        nxt = {"running": "The crew is working. Nothing is pushed and no pull request is made for a local ticket.",
               "awaiting-review": f"Review the branch {branch or ''}, merge it yourself if you agree, or connect a GitHub repo to run the reviewers on a pull request.".replace("  ", " "),
               "needs-human": "A person has to look at this. The reason is above; the ticket stays on the list.",
               "failed": "The cycle stopped. The ticket stays on the list; resume the cycle from a terminal."}.get(status, "")
        out["ticket"] = {"n": r["ticket"], "branch": branch, "review": review, "next": nxt}
    # the history lens is the stage table: one row per stage, its cost in the detail
    out["history"] = [{"at": x.get("finished") or x.get("started"), "duty": x.get("title") or x.get("id"), "verdict": x.get("verdict") or x.get("state"),
                       "detail": " · ".join(t for t in (_money(x.get("cost")) if x.get("cost") else "", str(x.get("detail") or "")[:300]) if t)}
                      for x in stages]
    done = [x for x in stages if x.get("state") == "done"]
    proof = f"{len(done)} stage(s) finished for {_money(cost)} in total" + (f" over {r.get('seconds')}s" if r.get("seconds") else "") + "."
    if r.get("pr") or stages:
        out["evidence"] = {"pr": r.get("pr"), "verdict": None, "plan": None, "tier": None, "diff": None, "proof": proof}


def brief_mission(r, out):
    """Fill the mission view of one design brief (brief_public form) into `out`. What the owner can answer is decided by the page from
    the record's status; this only says where the brief stands, in plain words."""
    st, m = r.get("status"), r.get("mockups") or {"state": "none"}
    ms = m.get("state", "none")
    title = (r.get("brief") or {}).get("title") or (r.get("idea") or "")[:60] or "A new idea"
    state = ("running" if st == "drafting" or ms == "working" else "blocked" if st == "failed" or ms == "failed"
             else "awaiting" if st in ("proposed", "changes_requested") or ms == "ready" else "done")
    words = {
        "drafting": ("Writing the brief", "Quarterdeck is writing the brief. It takes a minute or two and appears here when it is ready."),
        "failed": ("The brief did not get written", r.get("error") or plain_failure("")),
        "proposed": ("Waiting for you", "Read the brief below. Approve it, or ask for changes. Nothing is drawn or built until you approve."),
        "changes_requested": ("You asked for changes", "Your notes are kept. Write the next version and it will take them into account."),
        "superseded": ("Replaced by a newer version", "A newer version of this brief was written from your notes."),
        "approved": ("Approved", "The brief is approved. Next, you can have a mock-up made of each screen: a picture to look at, not a working page."),
    }[st if st in ("drafting", "failed", "proposed", "changes_requested", "superseded", "approved") else "failed"]
    if st == "approved" and ms == "working":
        words = ("Making the mock-ups", "Quarterdeck is drawing one page for each screen. They appear here when they are ready.")
    elif st == "approved" and ms == "failed":
        words = ("The mock-ups did not get made", m.get("error") or plain_failure(""))
    elif st == "approved" and ms == "ready":
        words = ("Mock-ups ready to look at", "Look at each screen below, then approve the set or ask for changes.")
    elif st == "approved" and ms == "approved":
        words = ("Brief and mock-ups approved", "You are done here. Nothing has been built and nothing in your project has changed. The brief and the pictures stay on this page for whoever builds it.")
    elif st == "approved" and ms == "changes_requested":
        words = ("You asked for changes to the mock-ups", "Your notes are kept. Make the mock-ups again and they will take them into account.")
    node = lambda i, lab, s, note="": {"id": i, "label": lab, "state": s, "note": note}
    out.update(project=r.get("project") or None, title=f"Brief · {title}", mission_ref="design brief", state=state,
               pipeline=[node("brief", "Brief", "active" if st == "drafting" else "blocked" if st == "failed" else "done"),
                         node("approved", "Approved", "done" if st in ("approved",) else "blocked" if st == "changes_requested" else "awaiting" if st == "proposed" else "notstarted"),
                         node("mockups", "Mock-ups", "active" if ms == "working" else "blocked" if ms == "failed" else "done" if ms in ("ready", "approved", "changes_requested") else "notstarted",
                              f"{len(m.get('pages') or [])} screens" if m.get("pages") else ""),
                         node("mockups-ok", "Mock-ups approved", "done" if ms == "approved" else "awaiting" if ms == "ready" else "blocked" if ms == "changes_requested" else "notstarted")]
               if st != "superseded" else None,
               detail={"title": words[0], "body": words[1]}, brief=r)
    if state == "blocked":
        out["blocker"] = {"cause": words[1], "cls": None, "rerun": False}
    if r.get("issue"):
        out["issue"] = r["issue"]


def plan_mission(p, out):
    """Fill the mission view of one sprint plan (the record plan.py wrote) into `out`."""
    st, moved = p.get("status"), [x for x in p.get("moves") or [] if x.get("result") == "moved"]
    n = len(p.get("sprint") or [])
    state = "done" if st == "superseded" or (st == "approved" and moved and len(moved) >= n) else "awaiting"
    words = {"proposed": ("Waiting for you", "Read the plan below. Approve it if the order and the sizes look right. No card moves when you approve."),
             "approved": ("Approved", "No card has moved yet. Move the cards when you are ready: you will see each move first."),
             "superseded": ("Replaced by a newer plan", "A newer plan was written for this project.")}.get(st, ("Recorded", ""))
    if st == "approved" and moved:
        words = (f"{len(moved)} of {n} cards moved", "The cards that could move have moved. The ones left alone, and why, are listed below.")
    node = lambda i, lab, s: {"id": i, "label": lab, "state": s, "note": ""}
    # the cost line is the planner's own sentence: priced by the harness from measured runs, "unknown" when there are none, never invented
    t, runs = p.get("total_cost"), int(p.get("measured_runs") or 0)
    out["cost_line"] = "Expected cost of the sprint: " + ((f"about ${t['low']:.2f}" if abs(t["high"] - t["low"]) < 0.005 else f"${t['low']:.2f} to ${t['high']:.2f}") if t else "unknown (no measurement yet)")
    out["cost_basis"] = (f"Priced from {runs} finished run(s) of this project (cycle records and fix runs). A size is matched to runs only where an approved plan sized that issue; otherwise the range pools all runs and says so."
                         if runs else "No run of this project is measured yet, so every cost is unknown. The only measured reference is from a different project: the first full cycle on a fixture cost about 7.4 dollars for a one-button change. That is a reference from a different project, not an estimate for this one.")
    out.update(project=p.get("project"), title=f"Sprint plan · {p.get('project')} · {(p.get('created') or '')[:10]}", mission_ref="sprint plan", state=state,
               pipeline=[node("plan", "Plan", "done"), node("ok", "Approved", "done" if st == "approved" else "awaiting" if st == "proposed" else "notstarted"),
                         node("moved", "Cards moved", "done" if moved else "notstarted")] if st != "superseded" else None,
               detail={"title": words[0], "body": words[1]}, plan=p)


def compose_mission(mid, get_panel, fixes, runs, inbox, queue, get_cycle=None, get_brief=None, get_plan=None):
    """Pure. get_panel(id) -> transcript or None; fixes = fix_index(); runs = ledger rows,
    newest first; inbox = inbox_items(); queue = queue_view(); get_cycle(id) -> a cycle record or None.
    None when the id names nothing."""
    if not isinstance(mid, str) or len(mid) > 300 or ":" not in mid:
        return None
    kind, ref = mid.split(":", 1)
    out = {"id": mid, "kind": kind, "project": None, "title": "", "state": "idle", "pipeline": None,
           "detail": {"title": "", "body": ""}, "blocker": None, "decision": None, "evidence": None,
           "items": [], "disputes": [], "history": [], "mission_ref": ""}
    if kind in ("fix", "panel"):
        pid, _, n = ref.partition("#")
        if not valid_id(pid) or (kind == "fix" and not n.isdigit()):
            return None
        tx = get_panel(pid) if pid != "issue" else None
        rec = fixes.get(f"{pid}#{n}") if kind == "fix" else None
        if tx is None and rec is None:
            return None
        tx = tx or {}
        project = tx.get("project") or (rec or {}).get("project")
        ruling = tx.get("ruling") or []
        items = [x for x in (_item_row(i + 1, it, fixes.get(f"{pid}#{i + 1}"), pid) for i, it in enumerate(ruling)) if x]
        out.update(project=project, items=items, disputes=_disputes(tx))
        if kind == "panel":
            st = tx.get("status")
            out.update(title=tx.get("headline") or tx.get("subject") or f"{tx.get('discipline')} panel",
                       mission_ref=f"{tx.get('discipline') or 'panel'} panel")
            panel = "active" if st == "running" else "blocked" if st == "abandoned" else "done"
            per = [fix_nodes(fixes[f"{pid}#{i['n']}"]) for i in items if i["kind"] == "change" and f"{pid}#{i['n']}" in fixes]
            per = [p for p in per if p]

            def agg(idx):
                col = [p[idx]["state"] for p in per]
                for s in ("blocked", "awaiting", "active"):
                    if s in col:
                        return s
                return "done" if col and all(s == "done" for s in col) else "notstarted"
            seats = len(tx.get("seats") or [])
            out["pipeline"] = ([{"id": "brief", "label": "Brief", "state": "done", "note": ""},
                                {"id": "panel", "label": "Panel", "state": panel, "note": f"{seats} seats" if seats else ""}]
                               + [{"id": NODES[k][0], "label": NODES[k][1], "state": agg(k), "note": "per item" if per else ""} for k in (2, 3, 4)])
            decision = _open_decision(items) if st == "done" else None
            out["decision"] = decision
            out["state"] = "running" if st == "running" else "blocked" if st == "abandoned" else "awaiting" if decision else "done"
            body = {"running": "The seats are still arguing. The ruling appears here when the chair has made it.",
                    "abandoned": "The panel stopped before it reached a ruling."}.get(st) \
                or f"The chair ruled on {len(items)} {'item' if len(items) == 1 else 'items'}. Each one can be fixed from the Work tab."
            out["detail"] = {"title": {"running": "Panel in progress", "abandoned": "Panel stopped"}.get(st, "Ruled"), "body": body}
            if st == "abandoned":
                out["blocker"] = {"cause": body, "cls": None, "rerun": False}
        else:
            item = next((i for i in items if i["n"] == int(n)), None)
            queued = any(q.get("panel") == pid and str(q.get("item")) == n for q in (queue.get(project) or {}).get("items", []))
            out.update(title=(rec or {}).get("title") or (item or {}).get("title") or f"Item {n}",
                       mission_ref=f"issue #{rec['issue']}" if (rec or {}).get("issue") else f"item {n}",
                       items=[item] if item else [], decision=_open_decision([item]) if item else None)
            if rec:
                if isinstance(rec.get("issue"), int):
                    out["issue"] = rec["issue"]                 # the page offers "Make a brief for this issue"
                out["pipeline"] = fix_nodes(rec)
                out["state"] = _fix_state(rec)
                t, b = _fix_detail(rec)
                out["detail"] = {"title": t, "body": b}
                if rec.get("status") in FIX_FAILED:
                    out["blocker"] = {"cause": b, "cls": None, "rerun": item is not None}
                v = rec.get("verdict") or ""
                diff = rec.get("diff") if isinstance(rec.get("diff"), str) else ""
                if rec.get("pr") or v or diff:
                    out["evidence"] = {"pr": rec.get("pr"), "verdict": v or None, "plan": rec.get("plan"), "tier": rec.get("tier"),
                                       "diff": diff[:6000] or None,
                                       "proof": (f"The inspector recorded {v}. The record does not say which commit it checked, so a later commit is not covered."
                                                 if v and not v.startswith("skipped") else (v or None))}
                if rec.get("fixrun"):
                    out["history"] = [{"at": r.get("at"), "duty": r.get("duty"), "verdict": r.get("verdict"), "detail": r.get("detail")}
                                      for r in runs if r.get("fixrun") == rec["fixrun"]][:20]
            else:
                out["pipeline"] = [{"id": k, "label": lab, "state": "done" if k == "brief" else "notstarted", "note": ""} for k, lab in NODES]
                out["detail"] = ({"title": "Waiting in the fix queue", "body": "It starts when the item ahead of it finishes."} if queued
                                 else {"title": "Not started", "body": "The panel ruled this worth doing. Nothing has been started on it."})
                if out["decision"]:
                    out["state"] = "awaiting"
    elif kind == "run":
        at, _, rest = ref.partition("|")
        project, _, duty = rest.partition("|")
        r = next((x for x in runs if x.get("at") == at and x.get("project") == project and x.get("duty") == duty), None)
        if r is None:
            return None
        hit = next((f for f in fixes.values() if r.get("fixrun") and f.get("fixrun") == r["fixrun"]), None)
        if hit:
            return compose_mission(f"fix:{hit['panel']}#{hit['item']}", get_panel, fixes, runs, inbox, queue)
        bad = (r.get("verdict") or "") in BAD_VERDICTS
        out.update(project=project, title=f"{duty}: {r.get('detail') or r.get('verdict') or 'run'}", mission_ref=f"{duty} run",
                   state="blocked" if bad else "done",
                   detail={"title": r.get("verdict") or "Recorded", "body": r.get("detail") or "No detail was recorded."},
                   history=[{"at": x.get("at"), "duty": x.get("duty"), "verdict": x.get("verdict"), "detail": x.get("detail")}
                            for x in runs if x.get("project") == project and x.get("duty") == duty][:20])
        if bad:
            out["blocker"] = {"cause": r.get("detail") or r.get("verdict"), "cls": None, "rerun": False}
        if r.get("url"):
            out["evidence"] = {"pr": r["url"], "verdict": r.get("verdict"), "plan": None, "tier": None, "diff": None, "proof": None}
    elif kind == "cycle":
        r = get_cycle(ref) if get_cycle and valid_id(ref) else None
        if not r:
            return None
        cycle_mission(r, out)
    elif kind == "brief":
        r = get_brief(ref) if get_brief and isinstance(ref, str) and len(ref) <= 40 else None
        if not r:
            return None
        brief_mission(r, out)
    elif kind == "plan":
        p = get_plan(ref) if get_plan and valid_id(ref) else None
        if not p:
            return None
        plan_mission(p, out)
    elif kind == "attn":
        a = next((x for x in inbox if x.get("id") == ref), None)
        if a is None:
            return None
        out.update(project=a.get("project"), title=a.get("label") or f"{a.get('project') or 'Local'} {a.get('duty') or ''}".strip(),
                   mission_ref=a.get("source") or "attention", state="blocked",
                   detail={"title": "Needs a look", "body": a.get("text") or ""},
                   blocker={"cause": a.get("text") or "", "cls": a.get("blocker"), "rerun": False, "place": a.get("place")})
    else:
        return None
    return out


def mission_view(mid):
    rows = [r for r in read_json(STATE / "runs.json", []) if isinstance(r, dict)]
    last = {(r.get("project"), r.get("duty")): r for r in rows}
    return compose_mission(
        mid, lambda pid: read_json(PANELS / f"{pid}.json", None), fix_index(running_locks()),
        [_split_verdict(r) for r in rows[-400:][::-1]], inbox_items(last), queue_view(),
        get_cycle=lambda cid: cycle_record(cid, running_locks()),
        get_brief=lambda bid: _safe(lambda: brief_public(brief_load(bid))), get_plan=lambda pid: _safe(lambda: plan_load(pid)))


# ---- showcase case study: a private preview of one finished, verified fix ------
# Nothing here is published. The page shows what a public version would say, and
# every string on it passes sanitize_public first, so what is shown is what an
# allowlisted projection would keep: no absolute path, host, user name, token or
# prompt text, whatever the records hold.
_SAN = [
    (re.compile(r"<untrusted\b.*?</untrusted>", re.S | re.I), "[removed]"),                                 # text handed to a model as data
    (re.compile(r"^[ \t]*(?:SYSTEM|PROMPT|INSTRUCTIONS?|You are\b|STANCES_JSON|RULING_JSON|FIXES_JSON)[^\n]*$", re.M), "[removed]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[removed]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat|glpat|xox[abprs]|sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"), "[removed]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[removed]"),
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), "[removed]"),                                       # a JWT
    (re.compile(r"(?i)\bbearer\s+\S{6,}"), "[removed]"),
    (re.compile(r"(?i)\b(bearer|token|secret|password|passwd|api[_-]?key|authorization)\b(\s*[:=]\s*|\s+)\S{6,}"), r"\1 [removed]"),
    (re.compile(r"https?://\S+"), "[link]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"), "[host]"),
    (re.compile(r"(?i)\b(?:localhost|[\w-]+(?:\.[\w-]+)*\.(?:local|internal|lan|home|corp|ts\.net))(?::\d+)?\b"), "[host]"),
    (re.compile(r"(?i)\b[\w-]+(?:\.[\w-]+)*\.(?:com|net|org|io|dev|app|ai|co|cloud)\b(?::\d+)?(?:/\S*)?"), "[host]"),
    (re.compile(r"(?<![\w.:-])(?:~|/(?:Users|home|root|private|var|tmp|opt|etc|mnt|Volumes))(?:/[^\s'\"`),;:]*)?"), "[path]"),
    (re.compile(r"\b[A-Za-z]:\\[^\s'\"`)]*"), "[path]"),
    (re.compile(r"\b[0-9a-f]{40}\b|\b[A-Za-z0-9_-]{40,}\b"), "[removed]"),                               # a long opaque string
]


_HANDLE = re.compile(r"(?<![\w.@])@[A-Za-z0-9][\w-]{1,38}\b")


def sanitize_public(text, names=(), code=False):
    """Pure. `text` with everything a stranger must not see replaced by a plain
    marker. `names` are extra words to remove whole (the owner's user name, the
    machine's name): passed in so this stays a function of its inputs."""
    out = str(text or "")
    for rx, to in _SAN:
        out = rx.sub(to, out)
    if not code:                    # in a diff an @ is a CSS rule or a decorator, not a person
        out = _HANDLE.sub("@[user]", out)
    for n in names:
        if isinstance(n, str) and len(n) >= 3:
            out = re.sub(r"(?i)(?<![\w])" + re.escape(n) + r"(?![\w])", "[user]", out)
    return out


STAGE_CAPTION = {
    "brief": lambda m: "The panel's ruling item became an issue." if (m.get("pipeline") or [{}])[0].get("note") else "The panel ruled this worth fixing.",
    "panel": lambda m: "A plan was written before any code." if "Plan written" in str(m["pipeline"][1].get("note")) else "No plan was needed; it was a mechanical change.",
    "build": lambda m: "The shipwright built it in its own worktree and opened a pull request.",
    "verify": lambda m: "The inspector checked it against the issue and recorded " + str((m.get("evidence") or {}).get("verdict") or "a verdict") + ".",
    "review": lambda m: "A person read the pull request and merged it." if m["pipeline"][4]["state"] == "done" else "Waiting for a person to read and merge it.",
}


def showcase_candidates(fixes):
    """Finished fixes the inspector proved, merged ones first, newest first."""
    ok = [f for f in fixes.values() if str(f.get("verdict") or "").startswith("PROVEN") and f.get("status") in ("pr", "merged")]
    return sorted(ok, key=lambda f: (f.get("status") == "merged", f.get("finished") or f.get("started") or ""), reverse=True)


def showcase_case(m, roles, names=()):
    """Pure. The case study for one fix mission `m` (compose_mission output), or None
    when it is not a verified, finished fix. `roles` = {duty: role sentence}."""
    ev = m.get("evidence") or {}
    if m.get("kind") != "fix" or not m.get("pipeline") or not str(ev.get("verdict") or "").startswith("PROVEN"):
        return None
    clean = lambda t: sanitize_public(t, names)
    item = (m.get("items") or [{}])[0] or {}
    merged = m["pipeline"][4]["state"] == "done"
    seen, byline = set(), []
    for r in reversed(m.get("history") or []):
        if r.get("duty") and r["duty"] not in seen:
            seen.add(r["duty"])
            byline.append({"duty": r["duty"], "role": clean(roles.get(r["duty"], "")), "verdict": clean(r.get("verdict") or "")})
    diff = sanitize_public(ev.get("diff") or "", names, code=True)
    return {
        "id": m["id"], "project": clean(m.get("project") or ""),
        "headline": clean(f"{m['title']}, {'merged and ' if merged else ''}verified."),
        "summary": clean(" ".join(x for x in (item.get("claim"), ("The panel ruled: " + item["action"]) if item.get("action") else "") if x)
                         or "The panel ruled this worth fixing."),
        "found": clean(item.get("claim") or ""), "ruled": clean(item.get("action") or ""),
        "diff": diff or None,
        "disagreements": [{"by": clean(x["by"]), "against": clean(x.get("against") or ""), "item": clean(x.get("item") or ""), "note": clean(x.get("note") or "")}
                          for x in m.get("disputes") or []],
        "byline": byline,
        "verified": "Verified by the inspector: " + clean(ev["verdict"]) + ". The record does not say which commit it covered.",
        "stages": [{"id": n["id"], "label": n["label"], "state": n["state"], "caption": clean(STAGE_CAPTION[n["id"]](m))} for n in m["pipeline"]],
        "pr_number": (re.search(r"/pull/(\d+)", ev.get("pr") or "") or [None, None])[1],
    }


def owner_names():
    """What identifies this machine's owner, to be removed from anything shown."""
    import getpass
    import socket
    out = {Path.home().name}
    for f in (getpass.getuser, lambda: socket.gethostname().split(".")[0]):
        try:
            out.add(f())
        except Exception:
            pass
    return sorted(x for x in out if x)


def case_view(mid, get_panel, fixes, runs, inbox, queue, roles, names):
    cands = showcase_candidates(fixes)
    key = lambda f: f"fix:{f['panel']}#{f['item']}"
    pick = next((f for f in cands if key(f) == mid), cands[0] if cands else None)
    case = None
    if pick:
        m = compose_mission(key(pick), get_panel, fixes, runs, inbox, queue)
        case = showcase_case(m, roles, names) if m else None
    return {"private": True,
            "candidates": [{"id": key(f), "title": sanitize_public(f.get("title"), names), "status": f.get("status")} for f in cands[:12]],
            "case": case}


# ---- missions -----------------------------------------------------------------
# The first slice of the mission model from the strategy review: a draft only.
# No executor exists yet, so there is nothing here that starts an agent or
# writes to GitHub — create, edit and link-as-evidence are the whole surface.
# Persisted the same way schedules are: a plain JSON list, read-modify-written
# whole. That is an existing, accepted risk in this codebase (runs.json has the
# same shape), not a new one introduced here.

def load_missions():
    m = read_json(MISSIONS_FILE, [])
    return m if isinstance(m, list) else []


def save_missions(items):
    write_json(MISSIONS_FILE, items)


def record_event(kind, detail, source):
    return {"at": iso(now_utc()), "kind": kind, "detail": detail, "source": source}


# What a plan step would actually do, ground-truthed against each duty's real
# behavior (the same table README.md's crew section describes), never guessed.
# A registered duty missing from here shows as unclassified rather than a
# invented description — the review's own warning against pretending every
# sentence is executable applies just as much to pretending every duty is understood.
DUTY_PLAN = {
    "surveyor": {"about": "Inspects a pull request and reports defects. Never approves, never merges.", "perm": "read-only"},
    "joiner": {"about": "Reviews the interface and writes a findings document.", "perm": "local-write"},
    "panel": {"about": "Seats a discipline of crew on the question and rules on it.", "perm": "local-write"},
    "foreman": {"about": "Turns a findings document into deduplicated GitHub issues.", "perm": "github-write"},
    "shipwright": {"about": "Takes one issue to a branch and a pull request.", "perm": "github-write"},
    "inspector": {"about": "Verifies a pull request against its issue and comments on it.", "perm": "github-write"},
    "harbourmaster": {"about": "Reconciles the project board against GitHub reality.", "perm": "github-write"},
    "purser": {"about": "Turns a backlog issue into something a stranger could start from.", "perm": "local-write"},
    "trials": {"about": "Runs the project's own verify command.", "perm": "read-only"},
    "scribe": {"about": "Drafts the README and architecture overview a project is missing; writes only a new branch, and only on your yes.", "perm": "local-write"},
}
PERM_LABEL = {"read-only": "Read-only analysis", "local-write": "Local file changes",
              "github-write": "GitHub writes", "unclassified": "Not yet mapped — read its duty file before approving"}


def duty_cost_estimate(project, duty, rows):
    """A real historical average, scoped to this exact project and duty. None
    when there is no history yet — a guess dressed as a number is worse than
    an honest unknown, and the review said so directly."""
    costs = [r.get("cost") or 0 for r in rows if r.get("project") == project and r.get("duty") == duty]
    return {"avg": sum(costs) / len(costs), "n": len(costs)} if costs else None


def propose_plan(mission):
    """One step per duty the project owner already enabled, in the order they
    registered them — a real ordering decision that exists, not one invented
    here. No step here means work; it only means it would, if this mission had
    an executor, which it does not yet."""
    projects = read_json(PROJECTS_FILE, {})
    duties = (projects.get(mission["project"]) or {}).get("duties") or []
    rows = spend_rows()
    steps = []
    for duty in duties:
        d = DUTY_PLAN.get(duty, {"about": "Behavior not yet mapped for planning.", "perm": "unclassified"})
        steps.append({"duty": duty, "about": d["about"], "permission": d["perm"],
                      "permission_label": PERM_LABEL[d["perm"]],
                      "cost_estimate": duty_cost_estimate(mission["project"], duty, rows)})
    return steps


def mission_act(action, body, source):
    """The only writes a mission draft can receive. Each is validated against
    the project registry and the panel store, never trusted from the request."""
    items = load_missions()

    if action == "create":
        projects = read_json(PROJECTS_FILE, {})
        project = body.get("project")
        if not isinstance(project, str) or project not in projects:
            raise ValueError("unknown project")
        objective = (body.get("objective") or "").strip()
        if not objective or len(objective) > 2000:
            raise ValueError("objective must be 1-2000 characters")
        rec = {
            "id": "m-" + secrets.token_hex(6), "project": project, "objective": objective,
            "constraints": (body.get("constraints") or "").strip()[:2000],
            "success_criteria": (body.get("success_criteria") or "").strip()[:2000],
            "status": "draft", "created_at": iso(now_utc()), "updated_at": iso(now_utc()),
            "links": {"panels": [], "runs": [], "fixes": [], "issues": [], "prs": [], "documents": []},
            "plan": None, "plan_revision": 0, "plan_approved_revision": None, "plan_approved_at": None,
            "events": [record_event("created", "draft created", source)],
        }
        items.append(rec)
        save_missions(items)
        return rec

    m = next((x for x in items if x.get("id") == body.get("id")), None)
    if not m:
        raise ValueError("unknown mission")

    if action == "update":
        if m["status"] != "draft":
            raise ValueError("only a draft can be edited")
        if "objective" in body and not (body.get("objective") or "").strip():
            raise ValueError("objective must be 1-2000 characters")
        for field in ("objective", "constraints", "success_criteria"):
            if field in body:
                m[field] = (body.get(field) or "").strip()[:2000]
        if m.get("plan_approved_revision") is not None:
            m["plan_approved_revision"] = None
            m["events"].append(record_event("approval-invalidated", "an edit invalidated the approved plan", source))
        m["updated_at"] = iso(now_utc())
        m["events"].append(record_event("edited", "draft edited", source))
    elif action == "link":
        panel = body.get("panel")
        if not valid_id(panel) or not (PANELS / f"{panel}.json").is_file():
            raise ValueError("unknown panel")
        if panel not in m["links"]["panels"]:
            m["links"]["panels"].append(panel)
            m["updated_at"] = iso(now_utc())
            m["events"].append(record_event("linked", f"linked panel {panel} as evidence", source))
    elif action == "propose_plan":
        if m["status"] != "draft":
            raise ValueError("only a draft can get a plan")
        m["plan"] = propose_plan(m)
        m["plan_revision"] = m.get("plan_revision", 0) + 1
        m["plan_approved_revision"] = None
        m["updated_at"] = iso(now_utc())
        m["events"].append(record_event("planned", f"plan proposed (revision {m['plan_revision']})", source))
    elif action == "approve_plan":
        if not m.get("plan"):
            raise ValueError("propose a plan before approving one")
        if body.get("revision") != m["plan_revision"]:
            raise ValueError("that plan revision is no longer current")
        m["plan_approved_revision"] = m["plan_revision"]
        m["plan_approved_at"] = iso(now_utc())
        m["updated_at"] = iso(now_utc())
        m["events"].append(record_event("approved", f"plan revision {m['plan_revision']} approved", source))
    elif action == "start_panel":
        # The one thing an approved mission can actually start: a spec panel,
        # seeded with the objective, since that is the one duty that takes an
        # outcome stated in plain language rather than a pre-existing target
        # (a PR, an issue, a path) that a brand-new mission does not have yet.
        # Deliberately not the rest of the plan — chaining steps automatically
        # is the "not automatic orchestration" line the review drew on purpose.
        if m["status"] != "draft":
            raise ValueError("only a draft can be started")
        if m.get("plan_approved_revision") != m.get("plan_revision") or not m.get("plan"):
            raise ValueError("approve a plan before starting it")
        projects = read_json(PROJECTS_FILE, {})
        if "panel" not in (projects.get(m["project"]) or {}).get("duties", []):
            raise ValueError("this project has no panel duty to start from")
        idea = m["objective"]
        if m.get("constraints"):
            idea += f"\n\nConstraints: {m['constraints']}"
        if m.get("success_criteria"):
            idea += f"\n\nSuccess criteria: {m['success_criteria']}"
        what = spawn_run(m["project"], "panel", ["--panel", "spec", "--idea", idea],
                         apply_=True, source="mission", mission=m["id"])
        m["status"] = "started"
        m["updated_at"] = iso(now_utc())
        m["events"].append(record_event("started", f"started a spec panel: {what}", source))
    else:
        raise ValueError("not something this can do")

    save_missions(items)
    return m


# ---- schedules ---------------------------------------------------------------
# A schedule is the same `qtdeck run` a human would type, plus when. Kept in
# config/ because it is a decision about the fleet, not a byproduct of running
# it — but written by this process, so it stays small and boring on purpose.

def load_schedules():
    # In state/, not config/: a schedule only fires while this machine is
    # running the dashboard, and last_run churns on every tick. Machine-specific
    # by nature, so it does not belong in the repo.
    s = read_json(SCHEDULES_FILE, [])
    return s if isinstance(s, list) else []


def next_due(s, now=None):
    """When this schedule should next fire, or None if it never will.

    A returned time in the past means due now — the same way an overdue
    interval reads. `now` is injectable so the daily case can be tested at a
    fixed hour rather than only at whatever o'clock the suite happens to run.
    """
    now = now or datetime.now().astimezone()
    if s.get("paused"):
        return None
    # Never run yet? Count from when the schedule was created, so adding one
    # never fires a run the moment you press the button.
    last = s.get("last_run") or s.get("created")
    base = None
    if last:
        try:
            base = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except Exception:
            base = None
    if s.get("at"):
        m = AT.match(s["at"])
        if not m:
            return None
        local_now = now.astimezone()
        today = local_now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                  second=0, microsecond=0)
        # The occurrence that should already have happened. Returning the NEXT
        # one instead is the bug this replaces: a time in the future is never
        # due, so a daily schedule fired exactly never.
        pending = today if today <= local_now else today - timedelta(days=1)
        if base is None or base.astimezone() < pending:
            return pending.astimezone(timezone.utc)
        return (pending + timedelta(days=1)).astimezone(timezone.utc)

    m = EVERY.match(s.get("every", ""))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)
    return (base or now) + delta


def schedules_view():
    out = []
    for s in load_schedules():
        due = next_due(s)
        out.append({**s, "next_due": iso(due) if due else None,
                    "seconds_until": int((due - now_utc()).total_seconds()) if due else None})
    out.sort(key=lambda x: (x["seconds_until"] is None, x["seconds_until"] or 0))
    return out


# ---- starting a run ----------------------------------------------------------

def validate_run(project, duty, args):
    """Return argv for a run, or raise ValueError. Nothing reaches a shell."""
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or not SAFE_NAME.match(project) or project not in projects:
        raise ValueError("unknown project")
    if not isinstance(duty, str) or not SAFE_NAME.match(duty) or not (DUTIES / f"{duty}.sh").is_file():
        raise ValueError("unknown duty")
    if duty not in (projects[project].get("duties") or []):
        raise ValueError(f"'{duty}' is not enabled for '{project}'")
    if not isinstance(args, list) or len(args) > 12:
        raise ValueError("bad arguments")
    clean = []
    for a in args:
        if not isinstance(a, str):
            raise ValueError("bad argument")
        a = a.strip()
        if not a:
            continue
        if a.startswith("--"):
            if not SAFE_FLAG.match(a):
                raise ValueError(f"bad flag: {a}")
        else:
            if not SAFE_VALUE.match(a) or ".." in a or a.startswith("/"):
                raise ValueError(f"bad value: {a}")
        clean.append(a)
    return [str(ROOT / "bin" / "qtdeck"), "run", project, duty, *clean]


def spawn_run(project, duty, args, apply_=False, source="dashboard", mission=None):
    no_demo("start a run")
    argv = validate_run(project, duty, args)
    if source in ("dashboard", "mission"):           # started by hand: a line of time, project and a short label in Quarterdeck's own state/ (for My rhythm), nothing else
        try:
            import attention.tasks as _tk
            label = ("mission: " + str(next((m.get("objective") for m in load_missions() if m.get("id") == mission), ""))) if mission else _tk.run_label(duty, args)
            _append_private(HAND_RUNS, json.dumps({"at": iso(now_utc()), "project": project, "label": _tk.clean(label)}) + "\n")
        except Exception:
            pass
    if apply_:
        argv.append("--apply")
    # No pre-check here: several of these duties now lock per target (an
    # issue, a PR), not per project, so "is duty-project busy" can no longer be
    # answered without parsing args the same way the duty script itself will.
    # A genuinely busy target still refuses cleanly — acquire_lock inside the
    # duty logs it and exits 0 rather than doing the work twice — the same as
    # every other way a run gets started (a schedule, a fix pipeline).
    LOGS.mkdir(exist_ok=True)
    out = open(LOGS / f"{duty}-{project}.log", "a")
    out.write(f"\n[{iso(now_utc())}] started by {source}: {' '.join(argv[2:])}\n")
    out.flush()
    # Same seam bin/fix already uses for QUARTERDECK_FIX_RUN: an env var the duty
    # never has to know about, picked up by record_run itself so every row it
    # writes is tagged, not just the one this call happens to make.
    env = {**os.environ, "QUARTERDECK_MISSION_RUN": mission} if mission else None
    subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, env=env,
                     stdin=subprocess.DEVNULL, cwd=str(ROOT), start_new_session=True)
    return " ".join(argv[2:])


def scheduler_loop():
    """One thread, one job: fire what is due. Nothing here is privileged — it
    spawns exactly the command a human would type, and skips anything already
    holding its lock rather than queueing a second copy behind it."""
    run_loop("scheduler", 15, scheduler_tick)


def scheduler_tick():
    """Three independent jobs: one failing must not starve the others, so each
    runs, and the first error is re-raised after for the loop to log and back off."""
    if demo_on():
        return                      # demo mode never fires, queues or syncs anything real
    first = None
    for job in (fire_due, drain_fix_queues, sync_fix_status_soon):
        try:
            job()
        except Exception as e:
            first = first or e
            log_error(f"scheduler {job.__name__}", e)
    if first:
        raise first


def fire_due():
    scheds = load_schedules()
    changed = False
    for s in (scheds if not over_budget() else []):
        due = next_due(s)
        if not due or due > now_utc():
            continue
        lock = STATE / f"{s['duty']}-{s['project']}.lock"
        if lock.is_dir():
            try:
                if pid_alive((lock / "pid").read_text().strip()):
                    continue
            except FileNotFoundError:
                pass
        try:
            spawn_run(s["project"], s["duty"], s.get("args") or [],
                      bool(s.get("apply")), source=f"schedule {s.get('id')}")
        except Exception as e:
            s["last_error"] = str(e)
        s["last_run"] = iso(now_utc())
        changed = True
    if changed:
        write_json(SCHEDULES_FILE, scheds)


# What a document IS decides whether filing it makes sense. Findings and specs
# become issues; a decision record, a backlog ruling and board notes are read,
# not filed; a fix item is the pipeline's own working file and it files it
# itself. Counting all of them as "not filed" is how a to-do count inflates.
KIND_LABEL = {
    "design": ("design findings", True), "findings": ("findings", True),
    "spec": ("specification", True), "dev": ("implementation plan", False),
    "decision": ("decision record", False), "backlog": ("backlog ruling", False),
    "board-notes": ("board notes", False), "fix-item": ("fix working file", False),
    "requirements": ("requirements", False),
    "other": ("document", False),
}


def classify(name, doc_kind):
    kind = doc_kind.get(name) or (
        "fix-item" if "-fix-" in name else
        "board-notes" if "-board-" in name else
        "requirements" if "-requirements-" in name else
        "findings" if "-joiner-" in name or "-findings-" in name else
        "dev" if "-plan-" in name else "other")
    label, fileable = KIND_LABEL.get(kind, KIND_LABEL["other"])
    return {"kind": kind, "kind_label": label, "fileable": fileable}


# What Quarterdeck writes into every pull request it opens, so one can be recognised even after its ledger row has aged out:
# bin/markers.py (PR_SIGNS), which also knows how bodies were signed before.


def verdict_outdated(sha, head):
    """A verdict names the revision it was read against (F09). A push since
    makes it outdated, not wrong — it is still the truth about the commit it
    describes, just not proof about the PR's current head. Either side
    missing (an older row with no recorded sha, or a head gh did not return)
    is not treated as a mismatch — an unknown stays unknown, never a guessed
    "outdated"."""
    return bool(sha and head and sha != head)


def issue_progress(repo):
    """How far a repository's issue list has got: what is closed, what is open,
    and which open issues already have a pull request. Cached like open_prs."""
    no_demo("ask GitHub")
    hit = PROGRESS_CACHE.get(repo)
    if not hit or time.time() - hit["at"] > BOARD_TTL:
        def gh(kind, fields):
            r = subprocess.run(["gh", kind, "list", "-R", repo, "--state", "all", "--limit", "200",
                                "--json", fields], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or "gh failed").strip()[:300])
            return json.loads(r.stdout or "[]")
        hit = {"at": time.time(), "issues": gh("issue", "number,title,state"),
               "prs": gh("pr", "number,state,closingIssuesReferences")}
        PROGRESS_CACHE[repo] = hit
    return summarize_progress(hit["issues"], hit["prs"])


def summarize_progress(issues, prs):
    in_review = {i["number"] for p in prs if p.get("state") == "OPEN"
                 for i in p.get("closingIssuesReferences") or []}
    closed = sum(i["state"] == "CLOSED" for i in issues)
    return {"total": len(issues), "closed": closed, "open": len(issues) - closed,
            "in_review": len(in_review & {i["number"] for i in issues if i["state"] == "OPEN"}),
            "titles": {i["number"]: i["title"] for i in issues}}


def open_prs(project, repo, runs, fixes):
    """Open pull requests on one repository, each saying whether Quarterdeck opened
    it and what the crew said about it. Authorship cannot tell: Quarterdeck pushes as
    whoever gh is logged in as, so every PR looks like the author's own."""
    no_demo("ask GitHub")
    hit = PR_CACHE.get(repo)
    if not hit or time.time() - hit["at"] > BOARD_TTL:
        r = subprocess.run(
            ["gh", "pr", "list", "-R", repo, "--state", "open", "--limit", "50", "--json",
             "number,title,url,headRefName,headRefOid,baseRefName,createdAt,isDraft,body,"
             "closingIssuesReferences,reviewDecision,statusCheckRollup,additions,deletions,"
             "changedFiles,mergeable,mergeStateStatus"],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "gh failed").strip()[:300])
        hit = {"at": time.time(), "prs": json.loads(r.stdout or "[]")}
        PR_CACHE[repo] = hit

    opened = {x.get("url"): x for x in runs
              if x.get("duty") in ("shipwright", "trials") and x.get("url")}
    from_item = {f.get("pr"): f for f in fixes.values() if f.get("pr")}

    def said(duty, n, head):
        """The crew's last word on #n — surveyor and inspector both name the PR.

        A verdict names the revision it was read against (F09: record_run
        stamps it at write time). A push since then does not erase the
        verdict — it is still the truth about that earlier commit — but it is
        marked outdated so it is never read as covering code it never saw."""
        tag = f"#{n}"
        rows = [x for x in runs if x.get("project") == project and x.get("duty") == duty
                and re.search(rf"(^|\s){re.escape(tag)}(\b|$)", x.get("detail") or "")]
        if not rows:
            return None
        row = rows[-1]
        sha = row.get("sha")
        return {"verdict": row.get("verdict"), "detail": row.get("detail"), "at": row.get("at"),
                "sha": sha, "outdated": verdict_outdated(sha, head)}

    out = []
    for pr in hit["prs"]:
        body = pr.get("body") or ""
        checks = pr.get("statusCheckRollup") or []
        state = lambda c: (c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        f = from_item.get(pr["url"])
        out.append({
            "project": project, "number": pr["number"], "title": pr["title"], "url": pr["url"],
            "branch": pr["headRefName"], "base": pr.get("baseRefName"),
            "created": pr["createdAt"], "draft": pr.get("isDraft"),
            "head_sha": pr.get("headRefOid"), "mergeable": pr.get("mergeable"),
            "merge_state": pr.get("mergeStateStatus"),
            "closes": [i["number"] for i in pr.get("closingIssuesReferences") or []],
            "review_decision": pr.get("reviewDecision") or "",
            "size": {"add": pr.get("additions"), "del": pr.get("deletions"),
                     "files": pr.get("changedFiles")},
            "checks": {"pass": sum(state(c) in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in checks),
                       "fail": sum(state(c) in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT") for c in checks),
                       "pending": sum(state(c) in ("PENDING", "IN_PROGRESS", "QUEUED", "") for c in checks),
                       "failing": [c.get("name") or c.get("context") for c in checks
                                   if state(c) in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT")]},
            "by_quarterdeck": (pr["url"] in opened) or _markers.signed(body),
            "from_item": ({"panel": f.get("panel"), "item": f.get("item"), "title": f.get("title")}
                          if f else None),
            "review": said("surveyor", pr["number"], pr.get("headRefOid")),
            "verify": said("inspector", pr["number"], pr.get("headRefOid")),
        })
    return out, hit["at"]


def merge_pr(project, number, head_sha):
    """Merge a real, open pull request — the one write in this system a human
    makes directly rather than a duty proposing it for review. Every guardrail
    tells the crew never to merge; this is the harness acting on the human's
    own decision, the same category as any action the owner presses, never the model's.

    Pinned to the commit the dashboard showed when the button was drawn:
    --match-head-commit refuses rather than merging a push nobody here has
    seen, the same principle F09 verdicts pin to a revision for.
    """
    no_demo("merge")
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or project not in projects:
        raise ValueError("unknown project")
    repo = projects[project].get("repo")
    if not repo:
        raise ValueError(f"'{project}' has no repo configured")
    if type(number) is not int or not 0 < number < 10 ** 7:
        raise ValueError("bad pull request number")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[0-9a-f]{7,40}", head_sha or ""):
        raise ValueError("bad commit sha")
    r = subprocess.run(
        ["gh", "pr", "merge", str(number), "-R", repo, "--merge", "--delete-branch",
         "--match-head-commit", head_sha],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout or "gh pr merge failed").strip()[:300])
    PR_CACHE.pop(repo, None)   # what's open just changed; don't serve the stale list
    record_run_row(project, "dashboard", "MERGED", f"#{number}",
                    f"https://github.com/{repo}/pull/{number}")
    return {"merged": True, "number": number}


# ---- reading one board card ---------------------------------------------------
# READ ONLY. One gh call for the issue or pull request with its comments, fetched when a card is opened and kept for the
# board's 60 seconds in memory. The repository comes from the registry, the number is checked, both go to gh as argv items.
CARD_BODY_MAX = 200_000
CARD_COMMENT_MAX = 20_000
CARD_COMMENTS = 100
CARD_KEEP = 40
CARD_FIELDS = "number,title,state,body,labels,assignees,milestone,createdAt,updatedAt,author,comments,url"
GITHUB_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+")


def _login(x):
    return _clip((x or {}).get("login") if isinstance(x, dict) else "", 60)


def _card_state(snap, kind, number):
    """The state the board snapshot already holds for an issue or pull request, or ""."""
    for r in ((snap or {}).get("items") or []):
        if r.get("number") == number:
            return _clip(r.get("state"), 20)
    return ""


def shape_card(raw, kind, snap=None):
    """What the reading panel needs from gh's JSON, trimmed and typed. Nothing but data to display."""
    def text(v, n):
        return v[:n] if isinstance(v, str) else ""
    body = text(_markers.normalise(raw.get("body")), CARD_BODY_MAX)       # an older requirements block reads as the current one on the page
    comments = [c for c in (raw.get("comments") or []) if isinstance(c, dict)]
    linked = []
    for ref in (raw.get("closedByPullRequestsReferences") if kind == "issue" else raw.get("closingIssuesReferences")) or []:
        if isinstance(ref, dict) and isinstance(ref.get("number"), int):
            linked.append({"kind": "pr" if kind == "issue" else "issue", "number": ref["number"],
                           "state": _card_state(snap, kind, ref["number"]),
                           "url": ref["url"] if isinstance(ref.get("url"), str) and GITHUB_URL.fullmatch(ref["url"]) else ""})
    url = raw.get("url")
    ms = raw.get("milestone")
    return {"kind": kind, "number": raw.get("number"), "title": _clip(raw.get("title"), 300), "state": _clip(raw.get("state"), 20),
            "url": url if isinstance(url, str) and GITHUB_URL.fullmatch(url) else "",
            "draft": bool(raw.get("isDraft")), "author": _login(raw.get("author")),
            "labels": [_clip(l.get("name"), 60) for l in (raw.get("labels") or []) if isinstance(l, dict)][:30],
            "assignees": [_login(a) for a in (raw.get("assignees") or [])][:20],
            "milestone": _clip(ms.get("title"), 80) if isinstance(ms, dict) else "",
            "created": _clip(raw.get("createdAt"), 30), "updated": _clip(raw.get("updatedAt"), 30),
            "body": body, "body_cut": isinstance(raw.get("body"), str) and len(raw["body"]) > CARD_BODY_MAX,
            "comments": [{"author": _login(c.get("author")), "at": _clip(c.get("createdAt"), 30), "body": text(c.get("body"), CARD_COMMENT_MAX)}
                         for c in comments[:CARD_COMMENTS]],
            "comments_more": max(0, len(comments) - CARD_COMMENTS), "linked": linked[:20]}


def card_view(project, number, kind="issue", fresh=False):
    no_demo("ask GitHub")
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or project not in projects:
        raise ValueError("unknown project")
    repo = projects[project].get("repo")
    if not isinstance(repo, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError(f"'{project}' has no repo configured")
    if kind not in ("issue", "pr"):
        raise ValueError("kind must be issue or pr")
    if not isinstance(number, str) or not re.fullmatch(r"[1-9]\d{0,6}", number):
        raise ValueError("bad number")
    key = (repo, kind, number)
    hit = CARD_CACHE.get(key)
    if hit and not fresh and time.time() - hit["at"] <= BOARD_TTL:
        return hit["card"], hit["at"]
    fields = CARD_FIELDS + (",isDraft,closingIssuesReferences" if kind == "pr" else ",closedByPullRequestsReferences")

    def call(f):
        return subprocess.run(["gh", kind, "view", number, "-R", repo, "--json", f], capture_output=True, text=True, timeout=60)
    r = call(fields)
    if r.returncode != 0 and "Unknown JSON field" in (r.stderr or ""):
        r = call(CARD_FIELDS + (",isDraft" if kind == "pr" else ""))      # an older gh without the link fields: show the card without them
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gh failed").strip()[:300])
    card = shape_card(json.loads(r.stdout or "{}"), kind, ((BOARD_CACHE.get(project) or {}).get("snap")))
    CARD_CACHE[key] = {"at": time.time(), "card": card}
    while len(CARD_CACHE) > CARD_KEEP:
        CARD_CACHE.pop(min(CARD_CACHE, key=lambda k: CARD_CACHE[k]["at"]))
    return card, CARD_CACHE[key]["at"]


def board_snapshot(owner, number, repo, named=None):
    """The board joined to repository reality — the same view the harbourmaster
    reconciles, so the dashboard and the duty can never disagree about it."""
    spec = importlib.util.spec_from_file_location("board", ROOT / "bin" / "board.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.snapshot(owner, number, repo, named)


def _split_verdict(r):
    v = (r.get("verdict") or "").strip()
    if " " not in v:
        return r
    token, rest = v.split(" ", 1)
    detail = r.get("detail") or ""
    return {**r, "verdict": token, "detail": f"{rest} — {detail}" if detail else rest}


# ---- the fleet timeline ---------------------------------------------------------
# Every run in the ledger and every merge (a run too), inside a window, plus whatever an add-on contributes (EXT["events"]).
# Read from the files and from what is already in memory: no network, no process.
TIMELINE_WINDOWS = {"6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400}
TIMELINE_CAP = 3000
ISO_AT = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d")      # a row without a real time cannot sit on a timeline (and would sort after every real one)


def timeline_view(window):
    secs = TIMELINE_WINDOWS.get(window)
    if secs is None:
        raise ValueError("window must be 6h, 24h or 7d")
    now = now_utc()
    cutoff = iso(now - timedelta(seconds=secs))
    ledger = read_json(STATE / "runs.json", [])
    events = []
    for r in (ledger if isinstance(ledger, list) else []):
        if not isinstance(r, dict) or not isinstance(r.get("at"), str) or not ISO_AT.match(r["at"]) or r["at"] < cutoff:
            continue
        r = _split_verdict(r)
        url = r.get("url")
        events.append({"at": r["at"][:40], "project": _clip(r.get("project"), 60), "duty": _clip(r.get("duty"), 40),
                       "verdict": _clip(r.get("verdict"), 40), "detail": _clip(r.get("detail"), 140),
                       "kind": "merge" if r.get("verdict") == "MERGED" else "run",
                       "url": url if isinstance(url, str) and url.startswith("https://") else None})
    for source in EXT["events"]:
        events += source(cutoff)
    events.sort(key=lambda e: e["at"], reverse=True)
    return {"window": window, "now": iso(now), "total": len(events), "capped": len(events) > TIMELINE_CAP, "events": events[:TIMELINE_CAP]}


# ---- brain dump ---------------------------------------------------------------
# One line of text, typed or spoken, kept locally in state/capture.jsonl. Nothing
# reads it as an instruction: it is a note that waits for you. A finished note is
# a second line saying so, so the file is only ever appended to.
CAPTURE = STATE / "capture.jsonl"


def _append_private(path, line):
    no_demo(f"write {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)      # owner only
    with os.fdopen(fd, "a") as f:
        f.write(line)


NOTE_ID = re.compile(r"[0-9a-f]{8}")
NOTE_CHARS = 1000


def _note_text(text):
    return " ".join(str(text or "").split())[:NOTE_CHARS]


def _note_project(project):
    """"" clears the tag; anything else must be a registered project."""
    if project in (None, ""):
        return ""
    if not isinstance(project, str) or project not in read_json(PROJECTS_FILE, {}):
        raise ValueError("unknown project")
    return project


def capture_add(text, project=""):
    text = _note_text(text)
    if not text:
        raise ValueError("nothing to capture")
    rec = {"id": secrets.token_hex(4), "at": iso(now_utc()), "text": text}
    if project:
        rec["project"] = _note_project(project)
    _append_private(CAPTURE, json.dumps(rec) + "\n")
    return rec


def _note(cid):
    if not isinstance(cid, str) or not NOTE_ID.fullmatch(cid):
        raise ValueError("bad id")
    n = next((x for x in capture_notes() if x["id"] == cid), None)
    if n is None:
        raise ValueError("no such note")
    return n


def capture_done(cid):
    _note(cid)
    _append_private(CAPTURE, json.dumps({"id": cid, "done": True, "at": iso(now_utc())}) + "\n")


def capture_reopen(cid):
    if not _note(cid)["done"]:
        raise ValueError("that note is not done")
    _append_private(CAPTURE, json.dumps({"id": cid, "done": False, "at": iso(now_utc())}) + "\n")


def capture_edit(cid, text=None, project=None):
    """Appends a line with the same id; the latest line wins when the file is read."""
    _note(cid)
    rec = {"id": cid, "at": iso(now_utc())}
    if text is not None:
        rec["text"] = _note_text(text)
        if not rec["text"]:
            raise ValueError("a note cannot be empty")
    if project is not None:
        rec["project"] = _note_project(project)
    if len(rec) == 2:
        raise ValueError("nothing to change")
    _append_private(CAPTURE, json.dumps(rec) + "\n")
    return _note(cid)


def idea_text(text):
    """A note as one safe argument for a panel: plain characters, no leading dash (it must not read as a flag), 200 at most."""
    t = re.sub(r"[^\w .,#:@+=-]", " ", str(text or ""))
    t = re.sub(r"\.{2,}", " ", t)
    return re.sub(r"^[\s/-]+", "", t).strip()[:200]


def capture_promote(cid, to, project, confirm=False):
    """A note becomes a mission draft (free) or a spec panel run (spends tokens, so it needs confirm).
    Both go through the same guarded paths as the buttons: the registry and the duty must allow it."""
    n = _note(cid)
    project = _note_project(project)
    if not project:
        raise ValueError("pick a project first")
    if to == "mission":
        rec = mission_act("create", {"project": project, "objective": n["text"]}, "notes")
        promoted = {"kind": "mission", "ref": rec["id"], "project": project}
    elif to == "plan":
        if confirm is not True:
            raise ValueError("confirm is required: a plan runs a panel and spends model tokens")
        idea = idea_text(n["text"])
        if not idea:
            raise ValueError("that note has no words a panel can use")
        spawn_run(project, "panel", ["--panel", "spec", "--idea", idea], False, source="notes")
        promoted = {"kind": "plan", "ref": "spec panel", "project": project}
    else:
        raise ValueError("promote to a mission or a plan")
    _append_private(CAPTURE, json.dumps({"id": cid, "at": iso(now_utc()), "promoted": promoted}) + "\n")
    return promoted


def capture_rows():
    try:
        lines = CAPTURE.read_text(errors="replace").splitlines()[-5000:]
    except OSError:
        return []
    rows = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            rows.append(r)
    return rows


def capture_notes():
    """The append-only file folded into one record per note, in the order they were first written. A line with
    text is the note or an edit of it (latest wins); done true or false closes or reopens it; project tags it;
    promoted records where it went. Lines for a note never created, and lines of the wrong shape, are ignored."""
    notes = {}
    for r in capture_rows():
        if not NOTE_ID.fullmatch(r["id"]):      # ids are written by this program; anything else is not ours and never reaches a page
            continue
        n = notes.get(r["id"])
        text = _note_text(r["text"]) if isinstance(r.get("text"), str) else ""
        if n is None:
            if not text:
                continue
            n = notes[r["id"]] = {"id": r["id"], "at": str(r.get("at") or "")[:40], "text": text, "project": "", "done": False,
                                  "updated": str(r.get("at") or "")[:40], "promoted": None}
        elif text:
            n["text"], n["updated"] = text, str(r.get("at") or "")[:40]
        if isinstance(r.get("project"), str):
            n["project"] = r["project"][:60]
        if r.get("done") is True or r.get("done") is False:
            n["done"], n["updated"] = r["done"], str(r.get("at") or "")[:40]
        pr = r.get("promoted")
        if isinstance(pr, dict) and pr.get("kind") in ("mission", "plan"):
            n["promoted"] = {"kind": pr["kind"], "ref": str(pr.get("ref") or "")[:40], "project": str(pr.get("project") or "")[:60]}
    return list(notes.values())


def captures_view(limit=200):
    """Open notes and recently done ones, newest first, and where the file is. The first two keys are the old shape."""
    notes = capture_notes()[::-1]
    open_ = [n for n in notes if not n["done"]]
    done = [n for n in notes if n["done"]]
    try:
        where = str(CAPTURE.relative_to(HOME))
    except ValueError:
        where = CAPTURE.name
    return {"items": open_[:limit], "open": len(open_), "done": done[:limit], "total": len(notes), "path": where}


# ---- Helm's helpers: a small local language model and a neural voice -----------
# Both run on this Mac and only while Helm is in use: each starts on first request
# and is stopped after ten idle minutes, so they cost no memory when you are not
# talking. Nothing here reaches a network.
HELM_HOME = Path.home() / ".cache" / "quarterdeck"
LLM_MODEL = HELM_HOME / "models" / "qwen2.5-3b-instruct-q4_k_m.gguf"
LLM_PORT = 0            # chosen afresh each time the helper starts (an unused port, not a well-known one)
LLM_KEY = ""
LLM_CHECKED = {"at": 0.0}
TTS_PYTHON = HELM_HOME / "venv" / "bin" / "python"
TTS_MODEL = HELM_HOME / "models" / "kokoro-v1.0.onnx"
TTS_SCRIPT = ROOT / "tools" / "helm" / "tts.py"
HELM_IDLE = 600


class Sidecar:
    """A helper process started on first use, stopped when idle or at exit."""

    def __init__(self, start, idle=HELM_IDLE):
        self.start, self.idle, self.proc, self.last = start, idle, None, 0.0
        self.lock = threading.RLock()

    def up(self):
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self.proc = self.start()
            self.last = time.time()
            return self.proc

    def running(self):
        with self.lock:
            return self.proc is not None and self.proc.poll() is None

    def reap(self, now=None):
        with self.lock:
            if self.proc and (self.proc.poll() is not None or (now or time.time()) - self.last > self.idle):
                self.stop()

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            self.proc = None


def _free_port():
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def listener_pids(port):
    """The process ids listening on this TCP port on this computer, by asking the system (lsof, else ss). None when neither could answer."""
    for argv, parse in ((["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"], lambda out: {int(x[1:]) for x in out.split() if x[:1] == "p" and x[1:].isdigit()}),
                        (["ss", "-ltnpH", f"sport = :{port}"], lambda out: {int(x) for x in re.findall(r"pid=(\d+)", out)})):
        if not shutil.which(argv[0]):
            continue
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode in (0, 1):                     # lsof exits 1 when nothing listens
            return parse(r.stdout)
    return None


def llm_ours(p, port):
    """True only if the one process listening on `port` is the helper we started. Anything else (or not knowing) means the key stays unsent."""
    pids = listener_pids(port)
    return pids is not None and pids == {p.pid}


def llm_base():
    """The helper's address, once it is up and is certainly ours. The key and the facts digest are never sent to anything else."""
    p = LLM.up()
    if time.time() - LLM_CHECKED["at"] > 30:
        if not llm_ours(p, LLM_PORT):
            LLM.stop()
            raise RuntimeError("something other than the language model is listening on its port, so nothing was sent")
        LLM_CHECKED["at"] = time.time()
    return f"http://127.0.0.1:{LLM_PORT}"


def _start_llm():
    exe = shutil.which("llama-server") or "/opt/homebrew/bin/llama-server"
    model = Path(env_flag("QUARTERDECK_HELM_MODEL", "") or LLM_MODEL).expanduser()
    if not (Path(exe).is_file() and model.is_file()):
        raise RuntimeError("the local language model is not set up: brew install llama.cpp and put a GGUF model at " + str(model))
    global LLM_KEY, LLM_PORT
    LLM_KEY = secrets.token_hex(16)                 # nothing else on this machine can use the model
    LLM_PORT = _free_port()
    LLM_CHECKED["at"] = 0.0
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_")}
    env["LLAMA_API_KEY"] = LLM_KEY                  # in the environment, not the arguments, so ps does not show it
    p = subprocess.Popen([exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(LLM_PORT), "-c", "4096", "-ngl", "99", "-np", "1", "--no-slots"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    for _ in range(90):
        if p.poll() is not None:
            raise RuntimeError("the language model failed to start")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{LLM_PORT}/health", timeout=1).read()    # a plain health check: no key, no data
            if not llm_ours(p, LLM_PORT):               # the answer must come from the child, not from whatever grabbed the port first
                p.terminate()
                raise RuntimeError("something other than the language model answered on its port, so nothing was sent")
            LLM_CHECKED["at"] = time.time()
            return p
        except RuntimeError:
            raise
        except Exception:
            time.sleep(1)
    p.terminate()
    raise RuntimeError("the language model took too long to start")


def _start_tts():
    if not (TTS_PYTHON.is_file() and TTS_MODEL.is_file()):
        raise RuntimeError("the natural voice is not set up: see the README")
    p = subprocess.Popen([str(TTS_PYTHON), str(TTS_SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, bufsize=0)
    try:
        if len(_read_exact(p, 4, 90)) < 4:
            raise RuntimeError("the voice worker failed to start")
    except Exception:
        p.kill()
        p.wait()                                    # no zombie from a failed start
        raise
    return p


def _read_exact(p, n, timeout):
    import select
    buf, end = b"", time.time() + timeout
    while len(buf) < n:
        left = end - time.time()
        if left <= 0 or not select.select([p.stdout], [], [], left)[0]:
            p.terminate()
            raise RuntimeError("the voice worker timed out")
        chunk = os.read(p.stdout.fileno(), n - len(buf))
        if not chunk:
            raise RuntimeError("the voice worker stopped")
        buf += chunk
    return buf


LLM, TTS = Sidecar(_start_llm), Sidecar(_start_tts)
TTS_LOCK = threading.Lock()


def helm_reaper():
    run_loop("helm_reaper", 30, lambda: (LLM.reap(), TTS.reap(), CLAUDE_SESSION.reap()))


atexit.register(lambda: (LLM.stop(), TTS.stop(), CLAUDE_SESSION.kill()))


def speak(text, voice=None, speed=None):
    """WAV bytes of text, spoken by Kokoro on this Mac."""
    text = " ".join(str(text or "").split())[:600]
    if not text:
        raise ValueError("nothing to say")
    voice = voice or env_flag("QUARTERDECK_HELM_VOICE", "") or "am_liam"
    if not re.fullmatch(r"[a-z]{2}_[a-z]{2,12}", voice):
        voice = "am_liam"
    try:
        speed = min(1.4, max(0.7, float(speed or env_flag("QUARTERDECK_HELM_SPEED", "") or 1.05)))
    except ValueError:
        speed = 1.05
    with TTS_LOCK:
        try:
            p = TTS.up()
            p.stdin.write((json.dumps({"text": text, "voice": voice, "speed": speed}) + "\n").encode())
            n = struct.unpack(">I", _read_exact(p, 4, 60))[0]
            return _read_exact(p, n, 60)
        except (OSError, RuntimeError):
            TTS.stop()
            raise


# What the language model may say. Every field is checked against what the page
# and the registry actually contain before anything is returned (vet_intent), so
# a wrong guess becomes a question, never an action: and anything that changes
# something still waits for a click on the page.
HELM_SCHEMA = {"anyOf": [
    {"type": "object", "properties": {"intent": {"const": "go"}, "view": {"type": "string"}, "project": {"type": "string"}},
     "required": ["intent", "view"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "project"}, "project": {"type": "string"}},
     "required": ["intent", "project"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "find"}, "query": {"type": "string"}},
     "required": ["intent", "query"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "capture"}, "text": {"type": "string"}},
     "required": ["intent", "text"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "work"}, "action": {"enum": ["start", "analyse"]},
                                      "issue": {"type": "integer"}, "project": {"type": "string"}},
     "required": ["intent", "action", "issue"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "run"}, "duty": {"type": "string"}, "project": {"type": "string"},
                                      "apply": {"type": "boolean"}, "pr": {"type": "integer"}},
     "required": ["intent", "duty"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "halt"}, "duty": {"type": "string"}, "project": {"type": "string"}},
     "required": ["intent", "duty"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "ack"}, "query": {"type": "string"}},
     "required": ["intent", "query"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "plan"}, "objective": {"type": "string"}, "project": {"type": "string"},
                                      "panel": {"type": "boolean"}},
     "required": ["intent", "objective"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "panelsay"}, "query": {"type": "string"}, "project": {"type": "string"}},
     "required": ["intent", "query"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "promote"}, "n": {"type": "integer"}, "kind": {"enum": ["plan", "mission"]}, "project": {"type": "string"}},
     "required": ["intent", "n", "kind"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "notedone"}, "n": {"type": "integer"}, "query": {"type": "string"}},
     "required": ["intent"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"const": "clarify"}, "say": {"type": "string"}},
     "required": ["intent", "say"], "additionalProperties": False},
    {"type": "object", "properties": {"intent": {"enum": ["running", "next", "brief", "agenda", "reminders", "missions", "notes", "help", "none"]}},
     "required": ["intent"], "additionalProperties": False}]}

HELM_SHOTS = [
    ("how are the agents doing", {"intent": "running"}),
    ("show me the pull requests for wayfarer mobile", {"intent": "go", "view": "prs", "project": "wayfarer-mobile"}),
    ("remind me that the dentist is on monday", {"intent": "capture", "text": "the dentist is on monday"}),
    ("what did I miss overnight", {"intent": "brief"}),
    ("what did the agents do last night", {"intent": "brief"}),
    ("what is the status of harvest-pipeline", {"intent": "project", "project": "harvest-pipeline"}),
    ("start issue 7 on wayfarer web", {"intent": "work", "action": "start", "issue": 7, "project": "wayfarer-web"}),
    ("how is saltpan-blog doing", {"intent": "project", "project": "saltpan-blog"}),
    ("what is the weather", {"intent": "none"}),
    ("where did I put the brand notes", {"intent": "find", "query": "brand notes"}),
    ("how is the crew getting on", {"intent": "running"}),
    ("what happened while I was asleep", {"intent": "brief"}),
    ("what is this costing me", {"intent": "go", "view": "spend"}),
    ("let's look at wayfarer api", {"intent": "project", "project": "wayfarer-api"}),
    ("tell me something funny", {"intent": "none"}),
    ("run the surveyor on wayfarer mobile", {"intent": "run", "duty": "surveyor", "project": "wayfarer-mobile"}),
    ("review pull request 12 on wayfarer web and apply it", {"intent": "run", "duty": "surveyor", "project": "wayfarer-web", "apply": True, "pr": 12}),
    ("stop the shipwright on wayfarer mobile", {"intent": "halt", "duty": "shipwright", "project": "wayfarer-mobile"}),
    ("acknowledge the surveyor signal", {"intent": "ack", "query": "surveyor"}),
    ("plan offline mode for wayfarer mobile", {"intent": "plan", "objective": "offline mode", "project": "wayfarer-mobile"}),
    ("plan a dark theme for wayfarer web and get the panel to look at it", {"intent": "plan", "objective": "a dark theme", "project": "wayfarer-web", "panel": True}),
    ("what did the panel say about onboarding", {"intent": "panelsay", "query": "onboarding"}),
    ("what are my open missions", {"intent": "missions"}),
    ("read me my notes", {"intent": "notes"}),
    ("turn the second note into a plan for wayfarer mobile", {"intent": "promote", "n": 2, "kind": "plan", "project": "wayfarer-mobile"}),
    ("mark the dentist note done", {"intent": "notedone", "query": "dentist"})]

def helm_shots(demo):
    """The examples shown to the model. They use invented project names (the same ones Demo mode shows), so there is nothing to swap."""
    return HELM_SHOTS + EXT["shots"] if EXT["shots"] else HELM_SHOTS


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n):
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "") if n < 100 else str(n)


def said_number(text, n):
    low, words = text.lower(), number_words(n).replace(" ", "[ -]")
    return bool(re.search(rf"(?<!\d){n}(?!\d)", low) or re.search(rf"\b{words}\b", low))


CAPTURE_CUES = r"\b(remind|remember|note|jot|capture|write down|don'?t forget|add to my list)\b"


VOICE_DUTIES = ("surveyor", "joiner", "harbourmaster", "inspector")   # mirrors RUN_DUTIES in assistant.js


def vet_intent(cmd, text, view_ids, projects, duties_of=None):
    clip = lambda v, n: " ".join(str(v or "").split())[:n]
    ask = lambda q: {"intent": "clarify", "say": q}
    if not isinstance(cmd, dict):
        return {"intent": "none"}
    i = cmd.get("intent")
    proj = cmd.get("project") if cmd.get("project") in projects else None
    if i == "go":
        if cmd.get("view") not in view_ids:
            return ask("Which page do you mean?")
        return {"intent": "go", "view": cmd["view"], **({"project": proj} if proj else {})}
    if i == "project":
        return {"intent": "project", "project": proj} if proj else ask("Which project do you mean?")
    if i == "find":
        q = clip(cmd.get("query"), 100)
        return {"intent": "find", "query": q} if q else ask("What should I look for?")
    if i == "capture":
        if not re.search(CAPTURE_CUES, text.lower()):
            return {"intent": "none"}
        words = lambda x: " ".join(re.sub(r"[^a-z0-9]+", " ", str(x).lower()).split())
        t = clip(cmd.get("text"), 500)
        if not t or words(t) not in words(text):          # only words that were actually said are saved
            m = re.search(CAPTURE_CUES + r"(?:\s+me)?(?:\s+(?:that|to))?\s+(.+)", text, re.I)
            t = clip(m.group(m.lastindex), 500) if m else ""
        return {"intent": "capture", "text": t} if t else {"intent": "none"}
    if i == "work":
        n = cmd.get("issue")
        ok = type(n) is int and 0 < n < 10**7 and said_number(text, n) and cmd.get("action") in ("start", "analyse")
        return {"intent": "work", "action": cmd["action"], "issue": n, **({"project": proj} if proj else {})} if ok else ask("I need an issue number to start work. Which one?")
    if i in ("run", "halt"):
        duty = cmd.get("duty")
        if duties_of is None:
            duties_of = {n: (v or {}).get("duties") or [] for n, v in read_json(PROJECTS_FILE, {}).items()}
        known = i == "halt" and isinstance(duty, str) and SAFE_NAME.match(duty) and duty != "_template" and (DUTIES / f"{duty}.sh").is_file()
        if not (known or (i == "run" and duty in VOICE_DUTIES)):
            return ask("Which duty do you mean?")
        if proj and duty not in duties_of.get(proj, []):
            return ask(f"The {duty} is not enabled for {proj}.")
        out = {"intent": i, "duty": duty, **({"project": proj} if proj else {})}
        if i == "run":
            n = cmd.get("pr")
            if type(n) is int and 0 < n < 10**7 and said_number(text, n):
                out["pr"] = n
            if cmd.get("apply") is True and re.search(r"\bapply\b", text.lower()):
                out["apply"] = True                       # only ever on the owner's own word
        return out
    if i in EXT["vet"]:
        return EXT["vet"][i](cmd, clip, ask)
    if i == "ack":
        return {"intent": "ack", "query": clip(cmd.get("query"), 60)}
    if i == "plan":
        words = lambda x: " ".join(re.sub(r"[^a-z0-9]+", " ", str(x).lower()).split())
        t = clip(cmd.get("objective"), 300)
        if not t or words(t) not in words(text):          # only words that were actually said become the objective
            return ask("What should the plan be for?")
        return {"intent": "plan", "objective": t, **({"project": proj} if proj else {}),
                "panel": bool(cmd.get("panel")) and bool(re.search(r"\bpanel\b", text.lower()))}
    if i == "promote":
        n = cmd.get("n")
        if not (type(n) is int and 0 < n < 100) or cmd.get("kind") not in ("plan", "mission"):
            return ask("Which note, and a plan or a mission?")
        return {"intent": "promote", "n": n, "kind": cmd["kind"], **({"project": proj} if proj else {})}
    if i == "notedone":
        n, q = cmd.get("n"), clip(cmd.get("query"), 60)
        if type(n) is int and 0 < n < 100:
            return {"intent": "notedone", "n": n}
        return {"intent": "notedone", "query": q} if q else ask("Which note?")
    if i == "panelsay":
        return {"intent": "panelsay", "query": clip(cmd.get("query"), 60), **({"project": proj} if proj else {})}
    if i == "clarify":
        return ask(clip(cmd.get("say"), 160) or "Could you say that another way?")
    if i in ("running", "next", "brief", "agenda", "reminders", "missions", "notes", "help"):
        return {"intent": i}
    return {"intent": "none"}


def understand(text, views, projects=None, duties_of=None):
    """One spoken request in, one checked command out, from the local model."""
    text = " ".join(str(text or "").split())[:300]
    if not text:
        return {"intent": "none"}
    projects = sorted(projects if projects is not None else read_json(PROJECTS_FILE, {}))
    ids = {v["id"]: str(v.get("label", ""))[:40] for v in views if isinstance(v, dict) and re.fullmatch(r"[a-z-]{2,24}", str(v.get("id", "")))}
    system = (
        "You turn ONE spoken request into ONE JSON command for the Quarterdeck dashboard. The request comes from speech to text, so "
        + misheard_note() +
        'Commands: {"intent":"go","view":ID,"project":NAME optional} open a page; {"intent":"project","project":NAME} switch project; '
        '{"intent":"find","query":WORDS} look something up in the second brain; {"intent":"capture","text":WORDS} save a note exactly as said; '
        '{"intent":"work","action":"start"|"analyse","issue":NUMBER,"project":NAME optional}; {"intent":"clarify","say":SHORT QUESTION} when unsure; '
        '{"intent":"run","duty":"surveyor"|"joiner"|"harbourmaster"|"inspector","project":NAME,"apply":true only if they said apply,"pr":NUMBER if said}; '
        + "".join(EXT["commands"]) +
        '{"intent":"halt","duty":NAME,"project":NAME} stop a running agent; {"intent":"ack","query":WORDS} dismiss a signal; '
        '{"intent":"plan","objective":WORDS AS SAID,"project":NAME,"panel":true only if they asked for the panel}; '
        '{"intent":"panelsay","query":TOPIC} what the panel said; '
        '{"intent":"promote","n":NUMBER,"kind":"plan"|"mission","project":NAME} turn the n-th open note into a plan or a mission; '
        '{"intent":"notedone","n":NUMBER or "query":WORDS} mark a note done; '
        '{"intent":"running"|"next"|"brief"|"agenda"|"reminders"|"missions"|"notes"|"help"|"none"}. '
        "notes = list my notes; missions = my open missions; running = what the agents are doing now; next = what to do next; brief = what changed while away; agenda = calendar today; "
        "reminders = my reminders; " + "".join(EXT["describe"]) + "none = not about the dashboard at all (jokes, weather, chat).\n"
        "Page ids: " + "; ".join(f"{k}={v}" for k, v in ids.items()) + "\nProjects: " + ", ".join(projects) +
        "\nOnly use page ids and project names from the lists. " + "".join(EXT["rules"]) + "Reply with the JSON only.")
    msgs = [{"role": "system", "content": system}]
    for u, a in helm_shots(demo_on()):
        msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": json.dumps(a, separators=(",", ":"))}]
    msgs.append({"role": "user", "content": text})
    body = json.dumps({"messages": msgs, "temperature": 0, "max_tokens": 140,
                       "response_format": {"type": "json_schema", "json_schema": {"name": "cmd", "schema": {"anyOf": HELM_SCHEMA["anyOf"] + EXT["schema"]}}}}).encode()
    req = urllib.request.Request(llm_base() + "/v1/chat/completions", body,
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY})
    with urllib.request.urlopen(req, timeout=40) as r:
        out = json.loads(r.read())["choices"][0]["message"]["content"]
    try:
        cmd = json.loads(out)
    except ValueError:
        cmd = None
    return vet_intent(cmd, text, set(ids), set(projects), duties_of)


# ---- Helm's conversation: POST /api/chat ----------------------------------------------
# The local brain (the same llama-server that classifies commands) answers open questions from a facts block built by
# chatctx.chat_digest, streaming so the page can speak the first sentence while the rest is still being written.
# What the model says is only ever text: an ACTION: line is handed to the page, which runs it through the normal
# command pipeline (parse, vet, confirm click). Nothing the model writes reaches an endpoint.
import chatctx
import claudeproc
import fleetview
import projagents
from integrations import accounts as integrations_accounts
from integrations import manifest as integrations_manifest
import billing as _billing                               # who pays for a duty's model calls, and the API key's presence (bin/billing.py)

# Local fleets (bin/fleetview.py): the agent folders the owner registered in config/fleet.local.json, shown on one screen and
# started or stopped from it. Not in /api/state, so nothing here reaches Helm or any model. Cached for a few seconds because
# a status command runs a few processes.
FLEET = {"at": 0.0, "data": None}
FLEET_LOCK = threading.Lock()


def fleet_view(force=False):
    """The cached view. A stale one is served at once and refreshed in the background, so the page never waits on dozens of git calls."""
    def refresh():
        data = fleetview.snapshot()
        with FLEET_LOCK:
            FLEET["data"], FLEET["at"], FLEET["busy"] = data, time.time(), False
    with FLEET_LOCK:
        have, age, busy = FLEET["data"], time.time() - FLEET["at"], FLEET.get("busy")
        start = (force or have is None or age > 20) and not busy
        if start:
            FLEET["busy"] = True
    if start and (have is None or force):
        refresh()
        return FLEET["data"]
    if start:
        threading.Thread(target=refresh, daemon=True).start()
    return have if have is not None else {"sources": [], "errors": ["still reading the fleets"], "at": 0}


def fleet_action(b):
    """pause, resume or test one job of a registered fleet. A click the owner confirmed, nothing else."""
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this starts or stops a real agent"}
    cfg = fleetview.load_config()
    ok, msg = fleetview.run_action(cfg, str(b.get("source", "")), str(b.get("job", "")), str(b.get("action", "")), STATE)
    try:
        with open(LOGS / "fleet-actions.log", "a") as f:                       # who did what, never what the agents read
            f.write(f"{iso(now_utc())} {log_field(b.get('source'))} {log_field(b.get('job'))} {log_field(b.get('action'))} {'ok' if ok else 'failed'}\n")
    except OSError:
        pass
    with FLEET_LOCK:
        FLEET["data"] = None
    return (200 if ok else 400), {"ok": ok, "message": msg}

def settings_view():
    """What this installation is and how it is set, read-only: where the data lives, the run defaults, the privacy limits, the version. No secrets."""
    return {
        "data_folder": str(HOME), "data_why": _home.why(), "program_folder": str(ROOT),
        "env_files": [str(ROOT / "config" / "quarterdeck.env"), str(HOME / "config" / "quarterdeck.env")],
        "dry_run": env_flag("QUARTERDECK_DRY_RUN", "1") == "1", "model": env_flag("QUARTERDECK_MODEL") or "account default",
        "sandbox": env_flag("QUARTERDECK_SANDBOX", "on") == "on",
        "voice": env_flag("QUARTERDECK_HELM_VOICE", "am_liam"), "voice_speed": env_flag("QUARTERDECK_HELM_SPEED", "1.05"),
        "attention": attention_on(), "commit": git_commit(), "uptime_seconds": int(time.time() - STARTED),
        "projects": len(read_json(PROJECTS_FILE, {}) or {}),
        "packs": [{k: x[k] for k in ("id", "label", "status")} for x in _packs_mod.load()],
        "billing": _billing.summary(),                   # modes, caps and whether the API key is stored; never the key
    }


def settings_api(b):
    """The writable part of Settings: who pays for each duty (plan or API key), the API spend caps, and the API key itself, which goes in and
    never comes back: every answer about it is a presence flag. Needs the owner's confirm. The log names the action, never a value."""
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this changes which account pays for model calls"}
    action = b.get("action")
    try:
        if action == "api_key":
            result = {"present": _billing.set_key(b.get("value") if isinstance(b.get("value"), str) else "")}
        elif action in ("billing", "seat"):
            name, mode = str(b.get("duty" if action == "billing" else "seat") or ""), b.get("mode")
            if mode not in _billing.MODES or not _billing.SAFE_NAME.match(name) or (action == "billing" and name not in _billing.duty_names()):
                return 400, {"error": "name a duty (or seat) that exists, and plan or api"}
            cfg = _billing.load()
            cfg["duties" if action == "billing" else "seats"][name] = mode
            _billing.save(cfg)
            result = {"billing": _billing.mode(name) if action == "billing" else mode}
        elif action == "cap":
            usd = b.get("usd")
            if usd is not None and _billing._usd(usd) is None:
                return 400, {"error": "a cap is a number of dollars, or null for none"}
            cfg = _billing.load()
            if b.get("scope") == "daily":
                cfg["caps"]["daily_usd"] = _billing._usd(usd) if usd is not None else None
            elif b.get("scope") == "duty" and (b.get("duty") == "*" or str(b.get("duty") or "") in _billing.duty_names()):
                if usd is None:
                    cfg["caps"]["duty_usd"].pop(b["duty"], None)
                else:
                    cfg["caps"]["duty_usd"][b["duty"]] = float(usd)
            else:
                return 400, {"error": "scope is daily, or duty with a duty that exists (or *)"}
            _billing.save(cfg)
            result = {"caps": _billing.load()["caps"]}
        else:
            return 400, {"error": "action must be api_key, billing, seat or cap"}
    except ValueError as e:
        return 400, {"error": str(e)}
    except OSError as e:
        return 500, {"error": "could not write: " + type(e).__name__}
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "settings.log", "a") as f:                     # what changed, never a value of the key
            f.write(f"{iso(now_utc())} {log_field(action)} {log_field(b.get('duty') or b.get('seat') or b.get('scope') or '')}\n")
    except OSError:
        pass
    return 200, result


MAX_BODY = 2_000_000


class BodyError(Exception):
    """A write's body that cannot be read as the small JSON object every route expects."""
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def csp(nonce=None):
    """The page's Content-Security-Policy. Scripts run only from this server's own files, plus the page's own inline scripts by their
    per-response nonce. Nothing is allowed to load from another site, to be framed, to submit a form anywhere, or to set a base URL.
    Relaxations, each deliberate: style-src 'unsafe-inline' (Shoelace sets styles on its parts and the page styles by attribute; styles
    cannot run code), img-src data: (the favicon and Shoelace's inline icons are data: images), connect-src data: (Shoelace reads those same inline icons back with fetch(); a data: URL holds its own bytes and reaches no host)."""
    return ("default-src 'self'; script-src 'self'" + (f" 'nonce-{nonce}'" if nonce else "") + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


def connection_test(sid, label, timeout=180):
    """Refresh one account once, in its own process (the loop's way, so a hang cannot block the dashboard). Returns {"ok", "message"}: a short
    sentence, never a value. Demo mode never calls a real service."""
    svc = next((x for x in integrations_manifest.load_services() if x["id"] == sid), None)
    if svc is None or svc["local"] or not svc["module"]:
        return {"ok": False, "message": "this service is read by a helper app, so there is nothing to test here"}
    if label != "default":
        src = (integrations_manifest.common.load_config()["sources"].get(sid) or {})
        if label not in integrations_accounts.labels_of(src):
            return {"ok": False, "message": "no such account: add it first"}
    run_py = ROOT / "bin" / "integrations" / "run.py"
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "QUARTERDECK_HOME", "QUARTERDECK_DIR", "QUARTERDECK_SECRETS_DIR")}
    try:
        r = subprocess.run([sys.executable, str(run_py), svc["module"], "--account", label], env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "the refresh did not finish in time"}
    except OSError:
        return {"ok": False, "message": "could not start the refresh"}
    line = (r.stdout.strip().splitlines() or [""])[-1]
    why = line.split("failed:", 1)[1].strip() if "failed:" in line else ""
    return {"ok": r.returncode == 0, "message": "Refreshed." if r.returncode == 0 else (why[:200] or "the refresh failed")}


def connections_api(b):
    """Put a credential in the private store (never read back), or switch a service's feed on or off. Both need the owner's confirm.
    An account of a service is named by `label` (default "default"). Actions stay credential, enable and store:
      enable with on:true (or add:true) on a label that does not exist yet adds the account; enable with on:false and remove:true removes it;
      enable with test:true refreshes it once and answers {ok, message}."""
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this changes how a service is connected"}
    sid, action = str(b.get("id") or ""), b.get("action")
    try:
        label = integrations_accounts.norm(b.get("label"))
        if action == "credential":
            if label != "default" and sid and str(b.get("value") or "").strip():
                integrations_manifest.add_account(sid, label)               # a credential for a new label makes the account, so it is never an orphan
            present = integrations_manifest.set_credential(str(b.get("key") or ""), b.get("value"), label=label)
            result = {"key": b.get("key"), "label": label, "present": present}
        elif action == "enable" and b.get("test") is True:
            if demo_on():
                return 400, {"error": "Demo mode: nothing is connected or tested."}
            result = connection_test(sid, label)
        elif action == "enable" and b.get("remove") is True and b.get("on") is not True:
            result = {"removed": integrations_manifest.remove_account(sid, label), "label": label}
        elif action == "enable":
            if label != "default" and (b.get("on") is True or b.get("add") is True):
                integrations_manifest.add_account(sid, label)          # "Add another account" sends add:true, switched off
            result = {"enabled": integrations_manifest.set_enabled(sid, b.get("on") is True, label=label), "label": label}
        elif action == "store":                                          # move every credential to the file or the keychain, verified, then switch
            result = {"moved": integrations_manifest.move_store(str(b.get("to") or "")), "store": integrations_manifest.store_info()["kind"]}
        else:
            return 400, {"error": "action must be credential, enable or store"}
    except ValueError as e:
        return 400, {"error": str(e)}
    except OSError as e:
        return 500, {"error": "could not write: " + type(e).__name__}
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        what = "test" if b.get("test") is True else "remove" if b.get("remove") is True else action
        with open(LOGS / "connections.log", "a") as f:                  # which key or service and account changed, never a value
            f.write(f"{iso(now_utc())} {log_field(what)} {log_field(sid or b.get('key') or b.get('to'))} {log_field(label)}\n")
    except OSError:
        pass
    return 200, result


def newproject_api(b):
    """Make a new folder with a git repository and a README. Needs the owner's confirm; registers nothing."""
    import newproject as _np
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this creates a folder on this computer"}
    try:
        parent = check_project_folder(str(b.get("folder") or "").strip() or Path.home() / "Projects", "a new project", whole=False)
        if str(b.get("name") or "").strip():
            check_project_folder(str(parent / str(b.get("name")).strip()), "a new project")
        dest = _np.create(str(b.get("name") or "").strip(), str(parent), b.get("about"))
    except ValueError as e:
        return 400, {"error": str(e)}
    except OSError as e:
        return 500, {"error": "could not create it: " + type(e).__name__}
    return 200, {"path": str(dest)}


def project_agents_api(name):
    """(status, body) for GET /api/project-agents?project=NAME: the agents that registered project defines for itself, plus the coverage table.
    Only a name in the registry is read, and only inside its own folder; nothing is written."""
    p = read_json(PROJECTS_FILE, {}).get(name) if isinstance(name, str) and name else None
    if not isinstance(p, dict) or not p.get("path"):
        return 400, {"error": "unknown project"}
    try:
        root = Path(str(p["path"])).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return 400, {"error": "unknown project"}
    return 200, {"project": name, **projagents.project_agents(str(root))}


def attach_api(b):
    """Look at a folder and propose how the crew should work on it; with apply and confirm, register it. Read-only until the owner confirms."""
    import attach as _attach, scan as _scan
    raw = str(b.get("path") or "").strip()
    if not raw:
        return 400, {"error": "say which folder"}
    try:
        path = check_project_folder(raw)
    except ValueError as e:
        return 400, {"error": str(e)}
    if not path.is_dir():
        return 400, {"error": f"{raw} is not a folder"}
    try:
        prof = _scan.scan(path)
        prop = proposed = _attach.propose(prof, str(b.get("name") or "").strip() or None)
        agents = None
        if b.get("edits") is not None:
            prop = _attach.edit(prop, b["edits"])
        if b.get("apply"):
            if b.get("confirm") is not True:
                return 400, {"error": "confirm is required: this adds the project to your registry"}
            _attach.apply(prop, prof, PROJECTS_FILE, proposed, "owner, reviewed in the dashboard" if b.get("edits") is not None else "owner, with --apply")
            if b.get("agents_md") is True:                  # opt-in, and only inside the confirmed apply
                try:
                    agents = _attach.write_agents_md(prop, path)
                except (OSError, ValueError):
                    agents = "failed"
            try:
                LOGS.mkdir(parents=True, exist_ok=True)
                with open(LOGS / "attach.log", "a") as f:
                    f.write(f"{iso(now_utc())} registered {log_field(prop['name'])}\n")
            except OSError:
                pass                                   # a note that could not be written never undoes the registration
    except ValueError as e:
        return 400, {"error": str(e)}
    except OSError as e:
        return 500, {"error": str(e)[:200]}
    return 200, {"profile": prof, "proposal": prop, "applied": bool(b.get("apply")), "agents_md": agents, "duty_options": [{"name": x["name"], "role": x["role"]} for x in duty_list() if x["name"] in _attach.known_duties()], "guardrail_options": _attach.GUARDRAILS, "pack_status": {x["id"]: x["status"] for x in _packs_mod.load()}}


# ---- tickets and the GitHub repo, on the page --------------------------------------------------------------------------------------------
# The page's "New ticket" box and the options for a project with no repo. The model is reached only through `qtdeck ticket new`, started detached
# with the owner's words on STANDARD INPUT (never in an argument list, so no process listing shows them); filing to GitHub is `qtdeck ticket file
# --apply`, so the planner's credential scan and the foreman's filing are the ones the command line uses. The dashboard itself holds no token and
# never reads one. Each write needs confirm:true, and logs the action and the project (never the request or any value) to logs/tickets.log.
TICKET_JOBS = {}                 # (project, "draft" | "file") -> {"popen", "at"}: the run this dashboard started last, so a page can ask why nothing came
TICKET_LOCK = threading.Lock()
DEMO_TICKET_MSG = "Demo mode: nothing is drafted, filed or created."
NOT_SIGNED_IN = "GitHub CLI is not signed in: run gh auth login in a terminal, then try again."


def _ticket_log(action, project):
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "tickets.log", "a") as f:
            f.write(f"{iso(now_utc())} {log_field(action)} {log_field(project)}\n")
    except OSError:
        pass                                        # a note that could not be written never undoes the action


def _ticket_entry(project):
    ent = read_json(PROJECTS_FILE, {}).get(project) if isinstance(project, str) else None
    if not isinstance(ent, dict):
        raise ValueError("unknown project")
    return ent


def _ticket_job_alive(project, kind):
    with TICKET_LOCK:
        job = TICKET_JOBS.get((project, kind))
    return bool(job and job["popen"].poll() is None)


def _ticket_running(project, kind="draft", locks=None):
    return f"planner-{project}-tickets" in (running_locks() if locks is None else locks) or _ticket_job_alive(project, kind) or _ticket_job_alive(project, "file" if kind == "draft" else "draft")


def _ticket_error(project, kind):
    """Why the last run this dashboard started for the project made nothing: one plain sentence, or "". Read from the ledger row the planner wrote,
    else from the end of the run's own log. Nothing here quotes the owner's request."""
    with TICKET_LOCK:
        job = TICKET_JOBS.get((project, kind))
    if not job or job["popen"].poll() is None:
        return ""
    rows = [r for r in read_json(STATE / "runs.json", []) if isinstance(r, dict) and r.get("project") == project and r.get("duty") == "planner"
            and isinstance(r.get("at"), str) and r["at"] >= job["at"]]
    row = rows[-1] if rows else None
    if row and row.get("verdict") in ("DRAFTED", "FILED"):
        return ""
    detail = " ".join(str(row.get("detail") or "").split()) if row else ""
    if row and row.get("verdict") == "NOTHING_TO_DRAFT":
        return "Everything in the draft is already on GitHub." if "tracker" in detail else "The planner found nothing to turn into a ticket from that request. Say more about what you want built."
    if row and row.get("verdict") == "REFUSED" and detail.startswith("ticket request"):
        return "Your request looks like it holds a password or a key, so nothing was sent. Take it out of the request and draft again."
    if row and row.get("verdict") == "REFUSED":
        return "A ticket looks like it holds a password or a key, so nothing was sent. Take it out of the request and draft again."
    if row:
        if detail.startswith("ticket draft refused"):
            return "The planner's answer did not pass Quarterdeck's checks, so nothing was kept. Try again; a new draft usually does."
        return plain_failure(re.sub(r"^ticket draft: ", "", detail))[:300]
    rc = job["popen"].returncode
    if rc not in (0, None):
        try:
            tail = [ln.strip() for ln in (LOGS / f"ticket-{project}.log").read_text(errors="replace").split("started by dashboard")[-1].splitlines() if ln.strip()]
        except OSError:
            tail = []
        return (tail[-1][:200] if tail else "The planner stopped before it finished.")
    return "The planner stopped without a result, perhaps at a usage limit. Try again later." if kind == "draft" else ""


def _ticket_review(t):
    """The command that shows a local ticket's branch, from its cycle record; "" when there is none."""
    cid = t.get("cycle")
    if t.get("status") not in ("review", "building") or not (isinstance(cid, str) and valid_id(cid)):
        return ""
    r = read_json(CYCLES / f"{cid}.json", None)
    return str(r.get("review") or "")[:500] if isinstance(r, dict) and r.get("kind") == "cycle" else ""


def _ticket_shown(x):
    """A ticket or a draft as the page may show it: every string passes the credential scan, so a model that copied a key into a ticket cannot put it
    on a screen (the draft stays on disk; the filing scan refuses it)."""
    try:
        import outscan as _os
    except Exception:
        return {"id": x.get("id"), "title": "(hidden: the credential scan could not run)", "body": "", "acceptance": [], "tickets": []}
    if isinstance(x, str):
        return _os.redact(x)
    if isinstance(x, list):
        return [_ticket_shown(v) for v in x]
    if isinstance(x, dict):
        return {k: _ticket_shown(v) for k, v in x.items()}
    return x


def tickets_view(project):
    """GET /api/tickets?project=: what the Tickets card and the repo options need. Read-only; no secret in it."""
    import tickets as _tk, repo as _repo
    no_demo("read tickets")
    ent = _ticket_entry(project)
    store = _tk.load(project)
    repo = ent.get("repo") or ""
    locks = running_locks()
    return {"project": project, "repo": repo, "has_repo": bool(repo), "sentence": "" if repo else _repo.sentence(project), "options": _repo.options(project),
            "stack": _tk.stack_context(project)["stack"], "cycle": ent.get("cycle") is True,
            "tickets": [{**_ticket_shown(t), "review": _ticket_review(t)} for t in store["tickets"]], "drafts": [_ticket_shown(d) for d in store["drafts"]],
            "running": _ticket_running(project, "draft", locks), "last_draft_error": _ticket_error(project, "draft"), "last_file_error": _ticket_error(project, "file"),
            "request_limit": _tk.REQUEST_MAX}


def _ticket_start(argv, log_name, request=None):
    """Run `argv` detached like a cycle; `request` (text) is written to its standard input, so it is in no argument list. Returns the Popen."""
    LOGS.mkdir(exist_ok=True)
    out = open(LOGS / log_name, "a")
    out.write(f"\n[{iso(now_utc())}] started by dashboard: {' '.join(a[:60] for a in argv[2:])}\n")
    out.flush()
    p = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.PIPE if request is not None else subprocess.DEVNULL,
                         cwd=str(ROOT), start_new_session=True)
    out.close()
    if request is not None:
        try:
            p.stdin.write(request.encode())          # at most a few thousand bytes: well inside a pipe's buffer, so this never waits
        finally:
            p.stdin.close()
    threading.Thread(target=p.wait, daemon=True).start()          # reaped when it ends
    return p


def ticket_draft_api(b):
    import tickets as _tk
    no_demo("draft tickets")
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: drafting asks the model, which costs a few cents"}
    project = b.get("project")
    try:
        ent = _ticket_entry(project)
        request = _tk.check_request(b.get("request"))
        if not (Path(os.path.expanduser(str(ent.get("path") or ""))) / ".git").exists():
            return 400, {"error": "that project's folder is not a git checkout"}
        if _ticket_running(project):
            return 409, {"error": f"the planner is already working on {project}: wait for it to finish"}
        bud = daily_budget()
        if bud is not None and spent_today() >= bud:
            return 409, {"error": f"today's budget is spent (${spent_today():.2f} of ${bud:.2f}); drafting would stop at once"}
        argv = _tk.argv_new(project)
    except ValueError as e:
        return 400, {"error": str(e)}
    at = iso(now_utc())
    try:
        p = _ticket_start(argv, f"ticket-{project}.log", request)
    except OSError as e:
        return 500, {"error": "could not start the planner: " + type(e).__name__}
    with TICKET_LOCK:
        TICKET_JOBS[(project, "draft")] = {"popen": p, "at": at}
    _ticket_log("draft", project)
    return 200, {"started": True}


def ticket_file_api(b):
    import tickets as _tk
    no_demo("file tickets")
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this saves tickets, or files issues on GitHub"}
    project, did, local = b.get("project"), b.get("draft"), b.get("local", False)
    if not isinstance(local, bool):
        return 400, {"error": "local is true or false"}
    try:
        ent = _ticket_entry(project)
        dr = _tk.draft_get(project, did)
        repo = ent.get("repo") or ""
        if repo and not local:
            if _ticket_running(project, "file"):
                return 409, {"error": f"the planner is already working on {project}: wait for it to finish"}
            argv = _tk.argv_file(project, did, apply=True)
        else:
            made = _tk.local_add(project, dr["tickets"])
            _tk.draft_remove(project, did)
            _ticket_log("file-local", project)
            return 200, {"tickets": made, "local": True}
    except ValueError as e:
        return 400, {"error": str(e)}
    at = iso(now_utc())
    try:
        p = _ticket_start(argv, f"ticket-{project}.log")
    except OSError as e:
        return 500, {"error": "could not start the filing: " + type(e).__name__}
    with TICKET_LOCK:
        TICKET_JOBS[(project, "file")] = {"popen": p, "at": at}
    _ticket_log("file-github", project)
    return 200, {"started": True, "count": len(dr["tickets"]), "repo": repo}


def ticket_discard_api(b):
    import tickets as _tk
    no_demo("discard a draft")
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: a discarded draft is gone"}
    try:
        _ticket_entry(b.get("project"))
        _tk.draft_remove(b.get("project"), b.get("draft"))
    except ValueError as e:
        return 400, {"error": str(e)}
    _ticket_log("discard", b.get("project"))
    return 200, {"discarded": True}


def repo_api(b):
    """Connect a repo the owner already has (set), or make a private one after two explicit yeses (create, push). The program that does it is bin/repo.py;
    this never creates a GitHub account, and reads and returns no token."""
    import attach as _attach
    no_demo("change the repo")
    if b.get("confirm") is not True:
        return 400, {"error": "confirm is required: this changes which GitHub repo the project uses"}
    project, action = b.get("project"), b.get("action")
    try:
        ent = _ticket_entry(project)
        if action == "set":
            repo = b.get("repo")
            if not isinstance(repo, str):
                return 400, {"error": "say the repo as owner/name, like octocat/hello-world"}
            _attach.set_repo(project, repo.strip())
            _ticket_log("repo-set", project)
            return 200, {"ok": True, "repo": repo.strip()}
        if action != "create":
            return 400, {"error": "action is set or create"}
        push = b.get("push", False)
        if not isinstance(push, bool):
            return 400, {"error": "push is true or false"}
        if ent.get("repo"):
            return 400, {"error": f"{project} already uses the GitHub repo {ent['repo']}"}
    except ValueError as e:
        return 400, {"error": str(e)}
    except OSError as e:
        return 500, {"error": "could not write: " + type(e).__name__}
    argv = [sys.executable, str(ROOT / "bin" / "repo.py"), "create", project, "--private", "--yes"] + (["--push"] if push else [])
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return 200, {"ok": False, "code": 1, "message": "GitHub did not answer in time. Nothing was recorded; check GitHub and try again."}
    except OSError as e:
        return 500, {"error": "could not run it: " + type(e).__name__}
    _ticket_log("repo-create" + ("-push" if push else ""), project)
    text = (r.stdout or "") + (r.stderr or "")
    try:
        import outscan as _os
        text = _os.redact(text)
    except Exception:
        text = ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if r.returncode == 3:
        return 200, {"ok": False, "code": 3, "message": NOT_SIGNED_IN}
    if r.returncode == 2:
        return 400, {"error": (lines[0] if lines else "That cannot be created.")[:300]}
    if r.returncode != 0:
        return 200, {"ok": False, "code": r.returncode, "message": "The repository was not created. " + " ".join(lines[-2:])[:300]}
    now = _ticket_entry(project).get("repo") or ""
    pushed = any(ln.startswith("pushed ") for ln in lines)
    return 200, {"ok": True, "code": 0, "repo": now, "private": True, "pushed": pushed,
                 "message": f"Created the private repository {now} and connected it." + (" The default branch was pushed once." if pushed else " Nothing was pushed.")}


# ---- design briefs, mock-ups and sprint plans: the owner's approval screens ------------------------------------------
# Every write here is one explicit click with confirm:true, and every write lands in the data folder (state/briefs, workspace/,
# state/plans) except two the owner names on purpose: a plan's card moves (through the board keeper's own move) and the opt-in
# "add the brief to the project as docs/BRIEF.md". Nothing merges, pushes or posts. The model runs are the brief and mockup duties.
STALE_AFTER = 20 * 60                       # a "working" record older than this belongs to a run that died


def _maker_home():
    return STATE.parent if STATE.name == "state" else HOME


def _plan_ok(pid):
    return isinstance(pid, str) and valid_id(pid) and bool(re.fullmatch(r"[A-Za-z0-9._-]{1,80}", pid))


def _age(ts):
    try:
        return (now_utc() - datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return 0


def plain_failure(raw):
    """A stored failure reason (the duties write short technical ones) as a sentence a person who is not a developer can act on."""
    t = " ".join(str(raw or "").split())
    if not t:
        return "Something went wrong and no reason was recorded. Try again."
    if t.startswith("needs a person:"):
        return "There is not enough to go on yet:" + t[len("needs a person:"):].rstrip(".") + ". Add a few more sentences and try again."
    if t.startswith("brief refused"):
        return "The draft did not pass Quarterdeck's checks, so nothing was kept. Try again; a new draft usually does."
    if t.startswith("mock-ups refused"):
        return "The drawn pages did not pass Quarterdeck's safety checks, so none were kept. Try again."
    if t in ("the model call failed", "empty reply", "hit the per-call cap") or t.startswith(("could not write", "could not save")):
        return "The run did not finish and nothing was kept. Try again; if it keeps happening, look at the log under Operations."
    return t


def brief_public(rec):
    """The record as the page needs it. A run that died (working for too long) is reported as stopped, not as still going."""
    m = dict(rec.get("mockups") or {"state": "none"})
    if m.get("state") == "working" and _age(m.get("started")) > STALE_AFTER:
        m["state"], m["error"] = "failed", "The run stopped before it finished. Try again."
    elif m.get("state") == "failed":
        m["error"] = plain_failure(m.get("error"))
    st, err = rec.get("status"), rec.get("error")
    if st == "drafting" and _age(rec.get("created")) > STALE_AFTER:
        st, err = "failed", "The run stopped before it finished. Try again."
    elif st == "failed":
        err = plain_failure(err)
    out = {k: rec.get(k) for k in ("id", "source", "project", "issue", "idea", "audience_hint", "brief", "notes", "doc", "revises",
                                   "superseded_by", "created", "updated", "added_to_project")}
    out.update(status=st, error=err, mockups=m)
    return out


def brief_load(bid):
    import brief as _b
    if not _b.id_ok(bid):
        raise ValueError("bad id")
    try:
        return _b.load(_maker_home(), bid)
    except _b.BriefError:
        raise KeyError(bid)


def briefs_summary(limit=12):
    import brief as _b
    out = []
    for r in _b.list_all(_maker_home()):
        if r.get("status") == "superseded":
            continue
        p = brief_public(r)
        out.append({"id": p["id"], "status": p["status"], "project": p["project"] or "", "mockups": p["mockups"].get("state", "none"),
                    "title": (p["brief"] or {}).get("title") or (p["idea"] or "")[:60] or "A new idea", "at": p["updated"] or p["created"]})
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)[:limit]


def plan_load(pid):
    if not _plan_ok(pid):
        raise ValueError("bad id")
    p = read_json(_maker_home() / "state" / "plans" / f"{pid}.json", None)
    if not isinstance(p, dict) or p.get("id") != pid:
        raise KeyError(pid)
    return p


def plans_summary(limit=8):
    out = []
    d = _maker_home() / "state" / "plans"
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        p = read_json(f, None)
        if isinstance(p, dict) and p.get("id") and p.get("status") != "superseded":
            out.append({"id": p["id"], "project": p.get("project", ""), "status": p.get("status", ""), "sprint": len(p.get("sprint") or []),
                        "items": len(p.get("plan") or []), "at": p.get("approved_at") or p.get("created") or ""})
    return sorted(out, key=lambda x: x["at"], reverse=True)[:limit]


def _spawn_detached(argv, log_name):
    LOGS.mkdir(exist_ok=True)
    out = open(LOGS / log_name, "a")
    out.write(f"\n[{iso(now_utc())}] started by dashboard: {' '.join(a[:60] for a in argv[2:])}\n")
    out.flush()
    subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(ROOT), start_new_session=True)


def brief_new(b):
    """Start the brief duty on an idea, or on an issue of a registered project that has the duty switched on. Returns the id at once;
    the page watches the record. Costs model usage on the owner's subscription, so it needs the owner's confirm."""
    import brief as _b
    no_demo("start a brief")
    if b.get("confirm") is not True:
        raise ValueError("confirm is required: this uses your model subscription")
    idea = " ".join(str(b.get("idea") or "").split())
    aud = " ".join(str(b.get("audience") or "").split())[:300]
    project = str(b.get("project") or "").strip()
    issue = b.get("issue")
    if project and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}", project):
        raise ValueError("that is not a project name")
    if issue is not None and (type(issue) is not int or not 0 < issue < 10**7):
        raise ValueError("bad issue")
    if issue is None and not 10 <= len(idea) <= _b.IDEA_MAX:
        raise ValueError(f"describe the idea in a few sentences (at least 10 and at most {_b.IDEA_MAX} characters)")
    if over_budget():
        raise ValueError("today's budget is spent")
    bid = _b.new_id()
    if issue is not None:
        argv = validate_run(project, "brief", ["--issue", str(issue), "--id", bid]) + ["--apply"]      # the project must have the duty switched on
    else:
        argv = [str(ROOT / "bin" / "qtdeck"), "brief", "--idea", idea, "--id", bid, "--apply"]
        if aud:
            argv += ["--for", aud]
        if project:
            argv += ["--project", project]
    _b.stub(_maker_home(), bid, "issue" if issue is not None else "idea", project, issue, idea, aud)
    _spawn_detached(argv, f"brief-{project or 'idea'}.log")
    return {"id": bid}


def brief_act(b):
    """The owner's answer to a brief or to its mock-ups, and the things they may start from there."""
    import brief as _b, mockup as _m
    no_demo("answer a brief")
    bid, act, note = b.get("id"), b.get("action"), str(b.get("note") or "")
    if not isinstance(bid, str) or not _b.id_ok(bid):
        raise ValueError("bad id")
    if act not in ("approve", "changes", "mockups", "mockups_approve", "mockups_changes", "revise", "add_to_project", "link"):
        raise ValueError("unknown action")
    if b.get("confirm") is not True:
        raise ValueError("confirm is required")
    home = _maker_home()
    rec = brief_load(bid)
    try:
        if act in ("approve", "changes"):
            return brief_public(_b.act(home, bid, act, note))
        if act in ("mockups_approve", "mockups_changes"):
            return brief_public(_m.act(home, bid, act.split("_")[1], note))
        if act == "mockups":
            _m.need(home, bid)                                        # refuses a brief that is not approved
            if brief_public(rec)["mockups"].get("state") == "working":
                raise LookupError("mock-ups for this brief are already being made")
            if over_budget():
                raise ValueError("today's budget is spent")
            _spawn_detached([str(ROOT / "bin" / "qtdeck"), "mockup", bid, "--apply"], f"mockup-{rec.get('project') or 'idea'}.log")
            return {"started": f"mockup {bid}"}
        if act == "revise":
            _b.revise_context(home, bid)                              # refuses a brief nobody asked changes on
            if over_budget():
                raise ValueError("today's budget is spent")
            nid = _b.new_id()
            _b.stub(home, nid, rec.get("source") or "idea", rec.get("project") or "", rec.get("issue"), rec.get("idea") or "", rec.get("audience_hint") or "", bid)
            _spawn_detached([str(ROOT / "bin" / "qtdeck"), "brief", "--revise", bid, "--id", nid, "--apply"], f"brief-{rec.get('project') or 'idea'}.log")
            return {"id": nid}
        if act == "link":
            name = str(b.get("project") or "")
            if name not in read_json(PROJECTS_FILE, {}):
                raise ValueError("that project is not registered")
            with _b.LOCK:
                rec = _b.load(home, bid)
                rec["project"], rec["updated"] = name, _b.now()
                _b._write(_b._path(home, bid), rec)
            return brief_public(rec)
        # add_to_project: the one write outside the data folder, and only because the owner asked for it by name
        if rec.get("status") != "approved":
            raise LookupError("only an approved brief can be added to a project")
        proj = read_json(PROJECTS_FILE, {}).get(rec.get("project") or "")
        root = Path(str((proj or {}).get("path") or "")).expanduser()
        if not proj or not root.is_dir():
            raise LookupError("this brief is not linked to a project that has a folder on this computer")
        docs = root / "docs"
        if docs.is_symlink() or (docs.exists() and not docs.is_dir()):
            raise LookupError("docs/ in the project is not a plain folder")
        docs.mkdir(exist_ok=True)
        target = docs / "BRIEF.md"
        if target.exists() or target.is_symlink():
            raise LookupError("docs/BRIEF.md already exists in the project; it was left alone")
        with open(target, "x") as f:
            f.write(_b.render(rec))
        with _b.LOCK:
            rec = _b.load(home, bid)
            rec["added_to_project"] = {"at": _b.now(), "path": "docs/BRIEF.md"}
            _b._write(_b._path(home, bid), rec)
        return brief_public(rec)
    except (_b.BriefError, _m.MockupError) as e:
        raise LookupError(str(e))


def plan_act(b):
    """Approve a sprint plan, preview its card moves, or make them (after approve). plan.py does the work; the cards move only
    through the board keeper's own move, one at a time, and a card that moved meanwhile is left alone."""
    import plan as _p
    no_demo("answer a plan")
    pid, project, act = b.get("id"), b.get("project"), b.get("action")
    if not _plan_ok(pid):
        raise ValueError("bad id")
    projects = read_json(PROJECTS_FILE, {})
    if not isinstance(project, str) or project not in projects:
        raise ValueError("unknown project")
    if act not in ("approve", "preview", "apply"):
        raise ValueError("unknown action")
    if act != "preview" and b.get("confirm") is not True:
        raise ValueError("confirm is required")
    home = _maker_home()
    try:
        if act == "approve":
            return {"plan": _p.approve(home, project, pid), "lines": []}
        bd = projects[project].get("board") or {}
        if not bd.get("number") or not bd.get("owner"):
            raise ValueError(f"'{project}' has no board in the registry")
        sm = bd.get("status")
        lines = _p.apply(home, project, pid, str(bd["owner"]), str(bd["number"]), projects[project].get("repo", ""),
                         json.dumps(sm) if isinstance(sm, dict) else "", act == "apply")
        BOARD_CACHE.pop(project, None)
        return {"plan": _p.load(home, project, pid), "lines": lines}
    except _p.PlanError as e:
        raise LookupError(str(e))


CLAUDE_SESSION = claudeproc.Session()      # the one long-lived deep-brain process (started on the first Claude turn, stopped when idle)

CHAT_TOKENS, CHAT_TOKENS_MORE, CHAT_TEMP = 160, 300, 0.3


def llm_stream(messages, max_tokens=CHAT_TOKENS, temperature=CHAT_TEMP):
    """Text deltas from the local model, as they are written."""
    base = llm_base()
    body = json.dumps({"messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", body,
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY})
    with urllib.request.urlopen(req, timeout=90) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                continue
            if delta:
                yield delta


def _rollup_counts(rollup):
    c = {"pass": 0, "fail": 0, "pending": 0}
    for x in rollup if isinstance(rollup, list) else []:
        v = str((x or {}).get("conclusion") or (x or {}).get("state") or (x or {}).get("status") or "").upper()
        c["pass" if v in ("SUCCESS", "NEUTRAL", "SKIPPED") else "fail" if v in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") else "pending"] += 1
    return c


def chat_facts():
    """(state, open pull requests) for the digest: the made-up world in demo mode, otherwise what the dashboard already knows."""
    if demo_on():
        w = DEMO["world"]
        return w.state(), [{"project": p["project"], "number": p["number"], "title": p["title"], "checks": p["checks"]} for p in w.open_prs(w.elapsed())][:8]
    prs = []
    try:
        for name, v in sorted(read_json(PROJECTS_FILE, {}).items()):
            hit = PR_CACHE.get((v or {}).get("repo"))
            for p in ((hit or {}).get("prs") or [])[:4]:
                prs.append({"project": name, "number": p.get("number"), "title": p.get("title"), "checks": _rollup_counts(p.get("statusCheckRollup"))})
    except Exception:
        pass
    return build_state(), prs[:8]


def helm_claude():
    """The deep brain's settings (off unless config/quarterdeck.env says on) and what it has cost today."""
    cfg = chatctx.claude_settings(env_flag)
    cfg["spent"] = round(chatctx.spent_today(spend_rows(), local_midnight_utc()), 4)
    return cfg


def helm_chat_view():
    c = helm_claude()
    return {"claude": "on" if c.pop("on") else "off", **c}


def _book_chat_spend(cost, out, stopped, model):
    """One row in the spend ledger under duty helm-chat for a deep-brain turn, whether it worked or not."""
    usage = out.get("usage") if isinstance(out.get("usage"), dict) else {}
    row = {"at": iso(now_utc()), "project": "", "duty": "helm-chat", "run": "", "fix": "", "effort": "",
           "model": next(iter(out.get("modelUsage") or {}), model), "cost": cost, "turns": out.get("num_turns") or 0,
           "read": sum(int(usage.get(k) or 0) for k in ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens")),
           "out": int(usage.get("output_tokens") or 0), "stopped": stopped}
    try:
        with open(SPEND, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def claude_chat(system, prompt, budget, model):
    """One deep-brain turn through a fresh claude process, as the duties call it: an argv list (no shell), every tool off, a hard
    per-turn dollar cap, a timeout, nothing saved. Slower than the long-lived process (claude_stream), so it is only the way
    out when that cannot start. Its cost goes into the spend ledger under duty helm-chat whether it worked or not."""
    no_demo("call Claude")
    exe = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        raise RuntimeError("the claude command was not found")
    argv = chatctx.claude_argv(exe, system, model, budget)
    book = lambda cost, out, stopped: _book_chat_spend(cost, out, stopped, model)

    try:
        with tempfile.TemporaryDirectory() as work:
            r = subprocess.run(argv, input=str(prompt), capture_output=True, text=True, timeout=chatctx.CLAUDE_TIMEOUT, cwd=work, env=claudeproc.clean_env())
    except subprocess.TimeoutExpired:
        book(float(budget), {}, "timeout")          # killed mid-turn: count the most it could have spent, so the daily cap still bites
        raise RuntimeError("it took too long")
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    out = out if isinstance(out, dict) else {}
    cost = float(out.get("total_cost_usd") or 0)
    stopped = "cap" if out.get("subtype") == "error_max_budget_usd" else "error" if (out.get("is_error") or r.returncode != 0) else None
    book(cost, out, stopped)
    if stopped == "cap":
        raise RuntimeError("it hit its limit for one turn")
    if stopped or not str(out.get("result") or "").strip():
        raise RuntimeError("it returned nothing" if not stopped else "the call failed")
    return str(out["result"]), cost


def claude_stream(system, message, *, allow, model, fresh, inc, budget, warm=False):
    """One deep-brain turn through the long-lived process: yields ("s", text) as it is written and finally ("done", cost). The
    process is started on the first turn and again after any error, an idle spell, a model change, a conversation that started
    over, or sharing that was withdrawn (see claudeproc). If it cannot be started at all, the one-shot call answers instead."""
    no_demo("call Claude")
    exe = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        raise RuntimeError("the claude command was not found")
    argv = chatctx.claude_stream_argv(exe, system, model, budget)
    sig = (model, hashlib.sha1(system.encode()).hexdigest()[:12])
    book = lambda cost, out, stopped: _book_chat_spend(cost, out, stopped, model)
    try:
        yield from CLAUDE_SESSION.turn(message, argv=argv, sig=sig, budget=budget, allow=allow, fresh=fresh, inc=inc, book=book, warm=warm)
    except claudeproc.StartFailed:
        if warm:
            raise
        reply, cost = claude_chat(system, message, allow, model)
        yield ("s", reply)
        yield ("done", cost)


def _emit_sentences(buf, final, want_action=True):
    """(events, rest) from a growing reply: sentences as {"s"}, an ACTION line as {"action"} (dropped unless the owner's own
    words asked for something to be done), and the model's own instruction wording kept out of what is spoken."""
    events = []
    sentences, rest = chatctx.split_sentences(buf, final=final)
    for sent in sentences:
        kind, val = chatctx.parse_action(sent)
        if kind == "action":
            if val and want_action:
                events.append({"action": val})
        else:
            clean = chatctx.scrub_prompt_wording(val) if val else ""
            if clean:
                events.append({"s": chatctx.strip_for_speech(clean)})
    return events, rest


def _claude_turn_inputs(b, cfg, state, prs, inc):
    """What a deep-brain turn is given: the message (newest facts without the private parts unless shared, the chat-tagged
    conversation, the question), and the facts that decide whether the long-lived process may carry on."""
    digest = chatctx.chat_digest(state, {"agenda": inc.get("agenda") is True, "notes": inc.get("notes") is True, "prs": prs})
    message = chatctx.claude_message(digest, b.get("history"), b.get("text"))
    shared = frozenset(k for k in ("agenda", "notes") if inc.get(k) is True)
    fresh = not chatctx.clean_history(b.get("history"), chat_only=True)       # nothing said yet in this conversation: a start (or a start over)
    return message, shared, fresh


def chat_events(b, facts=None, stream=None, claude=None, cfg=None):
    """The events of one reply, in order: {"s": sentence} while it is written, {"action": phrase} for an ACTION line,
    then {"done": true, "brain": "local"|"claude", "cost": dollars, "fallback": reason}. `facts`, `stream`, `claude`
    and `cfg` are injectable so the whole path is testable without a model. A request with "warm": true only gets the deep
    brain's process ready (one tiny turn, booked like any other) and answers {"done": true, "warm": true}."""
    warm = b.get("warm") is True
    text = chatctx.clean_text(b.get("text")) if not warm else "warm"
    if not text:
        yield {"error": "nothing to answer"}
        return
    state, prs = (facts or chat_facts)()
    inc = b.get("include") if isinstance(b.get("include"), dict) else {}
    want_action = chatctx.action_wanted(text)
    note, reason = "", ""
    if b.get("brain") == "claude" or warm:
        if demo_on():
            note, reason = "Thinking with Claude is off in demo mode, so I am answering locally.", "demo"
        else:
            cfg = cfg or helm_claude()
            allow = chatctx.turn_allowance(cfg.get("spent", 0), cfg["daily"], cfg["turn"]) if cfg["on"] else 0
            if not cfg["on"]:
                note, reason = "Thinking with Claude is switched off, so I am answering locally.", "off"
            elif not allow:
                note, reason = f"Today's limit of ${cfg['daily']:.2f} for thinking with Claude is reached, so I am answering locally.", "cap"
            else:
                budget = chatctx.process_budget(cfg["daily"] - cfg.get("spent", 0), cfg["turn"])
                message, shared, fresh = _claude_turn_inputs(dict(b, text=text), cfg, state, prs, inc)
                if warm:
                    message = "Reply with the single word ready."
                buf, said, cost, failed = "", False, 0.0, ""
                try:
                    for kind, val in (claude or claude_stream)(chatctx.claude_system(), message, allow=allow, model=cfg["model"], fresh=fresh,
                                                              inc=shared, budget=budget, warm=warm):
                        if warm:
                            if kind == "done":
                                cost = val
                            continue
                        if kind == "s":
                            buf += val
                            events, buf = _emit_sentences(buf, False, want_action)
                            for ev in events:
                                said = said or "s" in ev
                                yield ev
                        elif kind == "done":
                            cost = val
                except Exception as e:
                    failed = str(e)[:80] or "it stopped"
                if warm:
                    yield {"done": True, "brain": "claude", "warm": True, "cost": round(cost, 4), **({"error": failed} if failed else {})}
                    return
                if failed and not said and not buf.strip():
                    note, reason = f"Claude did not answer ({failed}), so I am answering locally.", "error"
                else:
                    events, _ = _emit_sentences(buf, True, want_action)
                    for ev in events:
                        said = said or "s" in ev
                        yield ev
                    if failed:
                        yield {"s": f"Claude stopped partway ({failed})."}
                    elif not said:
                        yield {"s": "I do not have an answer to that."}
                    yield {"done": True, "brain": "claude", "cost": round(cost, 4)}
                    return
        if warm:
            yield {"done": True, "brain": "local", "warm": True, "fallback": reason}
            return
    if note:
        yield {"s": note}
    digest = chatctx.chat_digest(state, {"agenda": True, "notes": True, "prs": prs})        # the local brain never leaves this Mac
    messages = chatctx.build_messages(digest, b.get("history"), text)
    limit = CHAT_TOKENS_MORE if chatctx.wants_more(text) else CHAT_TOKENS
    buf, said = "", bool(note)
    for delta in (stream or llm_stream)(messages, limit, CHAT_TEMP):
        buf += delta
        events, buf = _emit_sentences(buf, False, want_action)
        for ev in events:
            said = said or "s" in ev
            yield ev
    events, _ = _emit_sentences(buf, True, want_action)
    for ev in events:
        said = said or "s" in ev
        yield ev
    if not said:
        yield {"s": "I do not have an answer to that."}
    yield {"done": True, "brain": "local", **({"fallback": reason} if reason else {})}


# The brain view's outside-world nodes. Quarterdeck holds no credentials for any of
# these: each is a snapshot file some other tool wrote (state/connectors/<name>.json),
# read here as data and never as instructions. No file means "not connected".
CONNECTORS = STATE / "connectors"
KNOWN_CONNECTORS = (("gmail", "Gmail"), ("calendar", "Calendar"), ("reminders", "Reminders"),
                    ("slack", "Slack"), ("drive", "Drive"), ("ga4", "Site analytics"),
                    ("linkedin", "LinkedIn"), ("facebook", "Facebook"), ("instagram", "Instagram"),
                    ("macmail", "Mac Mail"), ("threads", "Threads"), ("x", "X"))


# Apple Calendar and Reminders, read on this Mac by a small app with its own identity
# (tools/agenda). It writes the same snapshot files as any other connector, so the
# dashboard holds no login and sends nothing anywhere. No app, no refresh.
AGENDA_APP = Path.home() / "Applications" / "QuarterdeckAgenda.app"


def agenda_loop():
    CONNECTORS.mkdir(parents=True, exist_ok=True)
    os.chmod(CONNECTORS, 0o700)
    run_loop("agenda", 900 + 150, agenda_tick)      # the slowest sleep plus the 150 s refresh


# ---- where the owner's attention goes ---------------------------------------------------
# bin/attention/ reads, locally and for free, only timestamps and counts: his own commits in the registered projects, pull requests,
# notes and the number of meetings. Nothing outside the registered projects and state/ is read. Never a prompt, a message, a diff or a title. It writes
# state/attention.json (owner only, in QUARTERDECK_PRIVATE_DENY so no agent can read it). QUARTERDECK_ATTENTION=off stops the
# collector and deletes nothing. Demo mode never runs it.
ATTENTION = STATE / "attention.json"
HAND_RUNS = STATE / "hand-runs.jsonl"
RHYTHM_TASKS = STATE / "rhythm-tasks.json"      # the owner's own task titles for My rhythm: local, 0600, never sent anywhere (bin/attention/tasks.py)


def rhythm_tasks_on():
    return env_flag("QUARTERDECK_RHYTHM_TASKS", "on").strip().lower() != "off"
ATTENTION_EVERY = 1800


def attention_on():
    return env_flag("QUARTERDECK_ATTENTION", "on").strip().lower() != "off"


def attention_inputs():
    projects = read_json(PROJECTS_FILE, {})
    ours = {x.get("url") for x in read_json(STATE / "runs.json", []) if isinstance(x, dict) and x.get("duty") in ("shipwright", "trials") and x.get("url")}
    prs = []
    for name, v in projects.items():
        for p in ((PR_CACHE.get((v or {}).get("repo")) or {}).get("prs") or []):
            if isinstance(p, dict) and p.get("url") not in ours:          # opened by Quarterdeck under his account: that is the agents' work
                prs.append({"project": name, "created": p.get("createdAt"), "title": p.get("title")})
    notes = [{"project": n.get("project"), "at": n.get("at"), "text": n.get("text")} for n in capture_notes()]
    runs = []
    try:
        for ln in HAND_RUNS.read_text().splitlines()[-5000:]:
            try:
                r = json.loads(ln)
            except (ValueError, RecursionError):
                continue
            if isinstance(r, dict):
                runs.append({"project": r.get("project"), "at": r.get("at"), "label": r.get("label")})
    except OSError:
        pass
    cal = read_json(CONNECTORS / "calendar.json", {})
    return {"projects": projects, "prs": prs, "notes": notes, "runs": runs, "rhythm_tasks": rhythm_tasks_on(), "calendar": cal.get("items") if isinstance(cal, dict) else []}


def rhythm_view():
    """My rhythm: the demo world's invented preview in Demo mode, otherwise the owner's own counts (hour buckets) through the adapter."""
    if demo_on():
        return DEMO["world"].rhythm()
    import attention.rhythm_feed as rf
    if not attention_on():
        return {"concept": False, "on": False, "badge": rf.BADGE, "today": _today(), "events": [], "meetings": [], "rules": rf.RULES, "tasks": {"on": False, "events": []}}
    out = rf.build(read_json(ATTENTION, {}), _today())
    out["tasks"] = rf.task_view(read_json(RHYTHM_TASKS, {}), _today(), rhythm_tasks_on())      # titles: only for this screen, never anywhere else
    return out


def attention_tick():
    if demo_on() or not attention_on():
        return ATTENTION_EVERY
    import attention.collect as ac
    ac.collect(attention_inputs(), STATE)
    return ATTENTION_EVERY


def attention_loop():
    run_loop("attention", ATTENTION_EVERY + 300, attention_tick)


def attention_view(days=120):
    """The aggregated buckets for the page (a window of days), or an explanation if there are none."""
    if demo_on():
        return DEMO["world"].attention(DEMO["world"].elapsed())
    st = read_json(ATTENTION, {})
    cutoff = (datetime.now() - timedelta(days=max(1, min(int(days), 400)))).strftime("%Y-%m-%d")
    per = st.get("days") if isinstance(st.get("days"), dict) else {}
    return {"on": attention_on(), "updated": st.get("updated"), "estimated": True,
            "days": {p: {d: v for d, v in dd.items() if d >= cutoff} for p, dd in per.items() if isinstance(dd, dict)}}


INTENT = STATE / "intent.jsonl"
PROJECT_STATUS = STATE / "project-status.json"


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def intent_view():
    """The focus the owner set (the newest record whose week covers today), the last few, and what he chose for quiet projects."""
    import attention.intent as ai
    if demo_on():
        return DEMO["world"].intent_view()
    rows = ai.read_intents(INTENT)
    t = _today()
    cur = [r for r in rows if r["from"] <= t <= r["to"]]
    return {"today": t, "current": cur[-1] if cur else None, "history": rows[-8:], "status": ai.read_status(PROJECT_STATUS)}


def intent_set(projects, which, confirm):
    """Writes need the owner's click, so the page sends confirm true only after he pressed the button."""
    import attention.intent as ai
    no_demo("set the focus")
    if confirm is not True:
        raise ValueError("the owner has to confirm this")
    rec = ai.make_intent(projects, set(read_json(PROJECTS_FILE, {})), _today(), iso(now_utc()), which)
    ai.append_private(INTENT, rec)
    return rec


def project_status_set(project, status, confirm):
    import attention.intent as ai
    no_demo("mark a project")
    if confirm is not True:
        raise ValueError("the owner has to confirm this")
    return ai.set_status(PROJECT_STATUS, project, status, set(read_json(PROJECTS_FILE, {})), _today())


def agenda_tick():
    if demo_on():
        return 60
    if AGENDA_APP.is_dir() and env_flag("QUARTERDECK_APPLE_AGENDA", "on") != "off":
        try:
            subprocess.run(["open", "-g", "-W", "-a", str(AGENDA_APP), "--args", str(CONNECTORS), "7"],
                           capture_output=True, timeout=150)
        except Exception:
            pass
    for f in (STATE / "agenda-status.json", *CONNECTORS.glob("*.json")):   # what it wrote is yours alone
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
    st = read_json(STATE / "agenda-status.json", None)
    return 300 if isinstance(st, dict) and st.get("events") else 900   # no access yet: do not keep asking


# ---- local speech to text ----------------------------------------------------
# whisper.cpp on this Mac. The page records, turns it into 16 kHz mono WAV and posts
# it here; nothing leaves the machine. The model and the binary come from the
# environment, never from the request.
WHISPER_MODEL = Path.home() / ".cache" / "quarterdeck" / "models" / "ggml-base.en.bin"
MAX_AUDIO = 12 * 1024 * 1024


def transcribe(wav, vocab=()):
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    exe = shutil.which("whisper-cli") or "/opt/homebrew/bin/whisper-cli"
    model = Path(env_flag("QUARTERDECK_WHISPER_MODEL", "") or WHISPER_MODEL).expanduser()
    if not (Path(exe).is_file() and model.is_file()):
        raise RuntimeError("local speech is not set up: brew install whisper-cpp, then put a ggml model at " + str(model))
    pcm = array.array("h"); pcm.frombytes(wav[44:len(wav) - (len(wav) - 44) % 2])
    if not pcm or (sum(x * x for x in pcm) / len(pcm)) ** 0.5 < 150:
        return ""                                   # whisper invents words ("you") for silence
    lang = env_flag("QUARTERDECK_WHISPER_LANG", "en")
    lang = lang if re.fullmatch(r"[a-z]{2,3}|auto", lang) else "en"
    prompt = ("Helm. Hey Helm. Quarterdeck commands. " + ", ".join(v for v in vocab if re.fullmatch(r"[\w.-]{1,40}", v)))[:300]
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "in.wav"
        f.write_bytes(wav)
        r = subprocess.run([exe, "-m", str(model), "-f", str(f), "-nt", "-np", "-l", lang, "--prompt", prompt],
                           capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("the speech engine failed")
    text = re.sub(r"[\[(][^\])]*[\])]", " ", r.stdout)       # [BLANK_AUDIO], (music) and the like
    return " ".join(text.split())[:500]


def _same_token(given, want):
    """Constant-time compare of a header with a token, as bytes (round 8, L12): compare_digest raises TypeError on a non-ASCII str, which dropped the
    connection instead of answering 401. Headers arrive decoded as latin-1, so that is how they go back to bytes."""
    try:
        return secrets.compare_digest(str(given).encode("latin-1"), str(want).encode("latin-1"))
    except (UnicodeEncodeError, TypeError):
        return False


def _clip(x, n):
    return x[:n] if isinstance(x, str) else ""


def _norm_title(t):
    return " ".join(str(t or "").lower().split())


def dedupe_events(items):
    """One event that sits on several calendars is one event: same normalised title, same start, same
    all-day-ness. Keeps the first (earliest start), counts the calendars in the sub line. Items that
    differ in any of the three are never merged. Order is kept."""
    out, seen = [], {}
    for it in items:
        key = (_norm_title(it["title"]), it["at"], "all day" in it["sub"].lower())
        if key[1] and key in seen:
            seen[key]["n"] += 1
            if it["at"] and it["at"] < seen[key]["it"]["at"]:
                seen[key]["it"]["at"] = it["at"]
            continue
        seen[key] = {"it": it, "n": 1}
        out.append(it)
    for rec in seen.values():
        if rec["n"] > 1 and "calendars" not in rec["it"]["sub"]:
            rec["it"]["sub"] = _clip((rec["it"]["sub"] + " · " if rec["it"]["sub"] else "") + f"on {rec['n']} calendars", 140)
    return out


def _conn_items(d, name):
    items = []
    for it in (d.get("items") if isinstance(d.get("items"), list) else [])[:200]:
        if not isinstance(it, dict):
            continue
        url = it.get("url")
        items.append({"title": _clip(it.get("title"), 140), "sub": _clip(it.get("sub"), 140),
                      "at": _clip(it.get("at"), 40), "new": it.get("new") is True,
                      "url": url if isinstance(url, str) and url.startswith("https://") else None})
    if name == "calendar":
        items = dedupe_events(items)          # dedupe first, then cap: the card shows more distinct events
    return items


def _conn_entry(name, label, d):
    if not isinstance(d, dict):
        return {"name": name, "label": label, "connected": False}
    unread = d.get("unread")
    return {"name": name, "label": label, "connected": True, "updated": _clip(d.get("updated"), 40),
            "unread": unread if type(unread) is int else None, "items": _conn_items(d, name)[:12]}


def _snapshot_services():
    """snapshot name -> the service id whose folder holds it (meta writes facebook and instagram)."""
    try:
        return {sn: m["id"] for m in integrations_manifest.load_services() for sn in m["snapshots"]}
    except Exception:
        return {}


def brain_connectors():
    """One entry per outside connection. A service with a single account is the entry it always was. A service with more than one account (the
    default and at least one more that has a snapshot or is switched on) gets one entry per account, each with `account` and a unique `key`
    (the default account's key is the plain name), so two accounts are never one list of items with the account hidden."""
    out = []
    known = {n for n, _ in KNOWN_CONNECTORS}
    try:        # a connection the user added is just a snapshot file with a plain name; the Brain shows it with no code edit
        extra = sorted(p.stem for p in CONNECTORS.glob("*.json") if p.stem not in known and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", p.stem))
    except OSError:
        extra = []
    svc_of = _snapshot_services()
    sources = (read_json(HOME / "config" / "integrations.json", {}) or {}).get("sources")
    sources = sources if isinstance(sources, dict) else {}
    for name, label in list(KNOWN_CONNECTORS) + [(n, n) for n in extra[:20]]:
        svc = svc_of.get(name, name)
        cfg_acc = integrations_accounts.labels_of(sources.get(svc) if isinstance(sources.get(svc), dict) else {})
        try:
            on_disk = [p.name for p in (CONNECTORS / svc).iterdir() if p.is_dir() and integrations_accounts.valid(p.name)] if (CONNECTORS / svc).is_dir() else []
        except OSError:
            on_disk = []
        more = [l for l in sorted(set(cfg_acc) | set(on_disk)) if l != "default"
                and ((CONNECTORS / svc / l / f"{name}.json").is_file() or (l in cfg_acc and sources[svc]["accounts"][l].get("enabled") is True))]
        if not more:
            out.append(_conn_entry(name, label, read_json(CONNECTORS / f"{name}.json", None)))
            continue
        for acct in ["default"] + more:
            d = read_json(CONNECTORS / svc / acct / f"{name}.json", None)
            if d is None and acct == "default":
                d = read_json(CONNECTORS / f"{name}.json", None)
            e = _conn_entry(name, f"{label} ({acct})", d)
            e["account"], e["key"] = acct, integrations_accounts.status_key(name, acct)
            out.append(e)
    return out


# Claude's own memory, for the brain's thinking region. Read straight from the
# memory folders of each Claude home on this Mac (names and one-line descriptions
# only, never the bodies), so it is always as fresh as the memory itself.
CLAUDE_HOMES = (".claude",)      # one account: the Claude folder in your home
MEMORY_BACKUP = Path.home() / "claude-memory-backup"
_FM = re.compile(r"^\s*(name|description|type):\s*(.*?)\s*$")
_mem_cache = [0.0, None]


def memory_front(text):
    """name/description/type from a memory file's frontmatter (type may sit under metadata:)."""
    out, lines = {}, text.split("\n")
    if not lines or lines[0].strip() != "---":
        return out
    for ln in lines[1:40]:
        if ln.strip() == "---":
            break
        m = _FM.match(ln)
        if m and m.group(1) not in out:
            v = m.group(2).strip("\"'")
            out[m.group(1)] = "" if v in (">", "|", ">-", "|-") else v
    return out


def memory_label(slug):
    s = re.sub(r"^-Users-[^-]+-?", "", slug)
    return re.sub(r"^Projects-", "", s) or "home"


def memory_stale(newest, last_commit, grace=3600):
    """The backup is behind if something changed more than `grace` seconds ago and nothing was committed since."""
    return bool(newest and newest < time.time() - grace and (last_commit or 0) < newest)


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        log_error(f"state section {getattr(fn, '__name__', 'section')}", e)
        return default


def memory_view():
    no_demo("read Claude's memory")
    if time.time() - _mem_cache[0] < 30 and _mem_cache[1] is not None:
        return _mem_cache[1]
    seen, projects, newest = set(), {}, 0.0
    for home in CLAUDE_HOMES:
        for f in sorted((Path.home() / home / "projects").glob("*/memory/*.md")):
            try:
                real = f.resolve()
                if f.name == "MEMORY.md" or real in seen:
                    continue
                seen.add(real)
                fm, mt = memory_front(real.read_text(errors="replace")[:2000]), real.stat().st_mtime
            except OSError:
                continue
            newest = max(newest, mt)
            slug = f.parent.parent.name
            pr = projects.setdefault(slug, {"slug": slug, "label": memory_label(slug), "count": 0, "types": {}, "items": []})
            pr["count"] += 1
            t = _clip(fm.get("type"), 20) or "note"
            pr["types"][t] = pr["types"].get(t, 0) + 1
            pr["newest"] = max(pr.get("newest", 0), mt)
            pr["fresh"] = pr.get("fresh", 0) + (mt > time.time() - 86400)
            pr["items"].append({"name": _clip(fm.get("name") or f.stem, 80), "desc": _clip(fm.get("description"), 140),
                                "type": t, "at": mt})
    for pr in projects.values():
        pr["newest"] = datetime.fromtimestamp(pr["newest"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        pr["items"] = sorted(pr["items"], key=lambda i: -i["at"])
        for i in pr["items"]:
            i["at"] = datetime.fromtimestamp(i["at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name, v in read_json(PROJECTS_FILE, {}).items():        # a memory folder is named after its project's path
        pr = projects.get(re.sub(r"[/.]", "-", str(Path(v.get("path", "")).expanduser())))
        if pr:
            pr["project"] = name
    skills = {d.parent.name for h in (*CLAUDE_HOMES, ".claude-shared", ".agents")
              for d in (Path.home() / h / "skills").glob("*/SKILL.md")}
    backup = None
    try:
        r = _safegit.run(MEMORY_BACKUP, "log", "-1", "--format=%ct", text=True, timeout=5)
        last = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0
        if not last and MEMORY_BACKUP.exists():
            last = 1
        if last:
            backup = {"last": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "stale": memory_stale(newest, last)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    view = {"projects": sorted(projects.values(), key=lambda p: -p["count"]),
            "total": sum(p["count"] for p in projects.values()), "skills": len(skills), "backup": backup}
    _mem_cache[0], _mem_cache[1] = time.time(), view
    return view


ASSETS = ROOT / "dashboard" / "assets"
ASSET_TYPES = {".png": "image/png", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
               ".woff2": "font/woff2", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
ASSET_NAME = re.compile(r"^([A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.(png|js|css|woff2|svg|ico)$")


def asset_file(url_path):
    """(bytes, content type) for a file under dashboard/assets, else None. The
    name is matched against a strict pattern, so nothing outside that folder
    (or below vendor/) can be named."""
    rel = url_path[len("/assets/"):] if url_path.startswith("/assets/") else ""
    if not ASSET_NAME.match(rel) or ".." in rel or not (rel.startswith("vendor/") or "/" not in rel):
        return None
    f = ASSETS / rel
    try:
        return f.read_bytes(), ASSET_TYPES[f.suffix]
    except OSError:
        return None


def _build_state():
    projects = read_json(PROJECTS_FILE, {})
    runs = [r for r in read_json(STATE / "runs.json", [])
            if all(isinstance(r.get(k), (str, type(None))) for k in ("project", "duty", "at", "verdict", "detail"))]
    locks = running_locks()
    duties = duty_list()
    built = {d["name"] for d in duties}
    role_of = {d["name"]: d["role"] for d in duties}

    last_by_pair = {}
    counts = {}
    cutoff = iso(now_utc() - timedelta(days=1))
    for r in runs:
        key = (r.get("project"), r.get("duty"))
        last_by_pair[key] = r
        if (r.get("at") or "") >= cutoff:
            counts[key] = counts.get(key, 0) + 1

    filed = _safe(lambda: filing_index(projects, runs), {})
    panels = _safe(lambda: panel_list(locks=locks, filed=filed), [])
    stale_docs = {p["doc"]: p["superseded_by"] for p in panels if p["doc"] and p["superseded_by"]}
    doc_kind = {p["doc"]: p["discipline"] for p in panels if p["doc"]}

    agents = []
    for pname, p in sorted(projects.items()):
        for duty in p.get("duties", []):
            # Several of these lock per target now (an issue, a PR), not per
            # project, so more than one can be alive for the same duty at
            # once — a row per live instance, not the single slot this used
            # to assume.
            live = duty_locks(duty, pname, locks, projects)
            last = last_by_pair.get((pname, duty))
            base = {
                "project": pname,
                "repo": p.get("repo", ""),
                "duty": duty,
                "role": role_of.get(duty, ""),
                "implemented": duty in built,
                "last_verdict": (last or {}).get("verdict"),
                "last_detail": (last or {}).get("detail"),
                "last_at": (last or {}).get("at"),
                "runs_24h": counts.get((pname, duty), 0),
            }
            if not live:
                agents.append({**base, "status": "idle" if duty in built else "unbuilt",
                                "since": None, "pid": None, "what": None, "lock": f"{duty}-{pname}"})
                continue
            for lock_name, info in sorted(live.items()):
                agents.append({**base, "status": "running", "since": info["since"],
                                "pid": info["pid"], "what": info["what"], "lock": lock_name,
                                "fixrun": info.get("fixrun")})

    return {
        "now": iso(now_utc()),
        "agents": agents,
        "crew": crew_list(),
        "missions": _safe(load_missions, []),
        "showcase": _safe(load_showcase, []),
        "inbox": _safe(lambda: inbox_items(last_by_pair), []),
        "panels": panels,
        "fixes": _safe(lambda: fix_index(locks), {}),
        "cycles": _safe(lambda: cycles_summary(locks), []),
        "briefs": _safe(briefs_summary, []),
        "plans": _safe(plans_summary, []),
        "fixqueue": _safe(queue_view, {}),
        "spend": _safe(spend_summary, {}),
        "schedules": _safe(schedules_view, []),
        "docs": _safe(lambda: [{**d, "superseded_by": stale_docs.get(d["name"]),
                                **classify(d["name"], doc_kind)}
                               for d in doc_list(list(projects), filed)], []),
        "projects": [
            {"name": k, "repo": v.get("repo", ""), "summary": v.get("summary", ""),
             "duties": v.get("duties", []), "guardrails": v.get("guardrails", []),
             "verify": v.get("verify", ""), "cycle": v.get("cycle") is True,
             "board": (f'https://github.com/users/{v["board"]["owner"]}'
                       f'/projects/{v["board"]["number"]}' if v.get("board") else None)}
            for k, v in sorted(projects.items())
        ],
        "duties": duties,
        # The write-site now guarantees a one-token verdict (lib.sh record_run).
        # Rows written before that still hold a whole sentence, so split them
        # here too rather than letting the chip stretch until they age out.
        "runs": [_split_verdict(r) for r in runs[-200:][::-1]],
        "system": {
            "dry_run": env_flag("QUARTERDECK_DRY_RUN", "1") == "1",
            "model": env_flag("QUARTERDECK_MODEL") or "account default",
            "max_items": env_flag("QUARTERDECK_MAX_ITEMS", "5"),
            "timeout": env_flag("QUARTERDECK_RUN_TIMEOUT", "900"),
            "rounds": env_flag("QUARTERDECK_PANEL_ROUNDS", "2"),
            "running": len(locks),
        },
        "helm_chat": _safe(helm_chat_view, {"claude": "off"}),
        "logs": sorted(f.stem for f in LOGS.glob("*.log")),
        "captures": _safe(captures_view),
        "agenda_status": read_json(STATE / "agenda-status.json", {}) or None,
        "connectors": _safe(brain_connectors, []),
        "integrations": read_json(STATE / "integrations-status.json", {}),
        "memory": _safe(memory_view),
        **{k: _safe(f) for k, f in EXT["state"].items()},
    }


def build_state():
    out = _build_state()
    LAST_BUILD["at"] = time.time()
    return out


class Handler(BaseHTTPRequestHandler):
    timeout = 15                    # seconds a socket may sit idle: a half-open connection cannot hold a thread and a file descriptor for ever

    DEADLINE = 20                   # seconds for the whole request line, headers and body: a client that drips one header line at a time never goes idle, so the idle timeout alone would let 96 of them hold every slot

    def log_message(self, *args):
        pass

    def handle_one_request(self):
        self._deadline = threading.Timer(self.DEADLINE, self._deadline_hit)
        self._deadline.daemon = True
        self._deadline.start()
        try:
            return super().handle_one_request()
        except OSError:
            self.close_connection = True                                       # the deadline cut the socket under a half-read request, or the client went away
        finally:
            self._deadline.cancel()

    def _deadline_hit(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def parse_request(self):
        ok = super().parse_request()
        if not ok or self.command != "POST" or (self.headers.get("Content-Length") or "0").strip() in ("", "0"):
            self._deadline.cancel()                                            # nothing more to read: the handler may take as long as it needs
        return ok

    # ---- plumbing ----
    def _send(self, code, body, ctype="application/json", nonce=None, cookie=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")                            # nothing may frame this page (clickjacking)
        self.send_header("Content-Security-Policy", csp(nonce))
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _demo_reply(self, got):
        code, body = got or (404, {"error": "not found"})
        return self._send(code, json.dumps(body))

    def _local_host(self):
        """A page on another site can re-point its own hostname at 127.0.0.1
        (DNS rebinding) and then read this server as if it were same-origin,
        token and all. It cannot make the browser send a loopback Host header,
        so that is checked on every request, reads included."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def _origin_ok(self):
        """A browser names the page a request came from. Only this server's own address counts (not another port on localhost,
        which is another program), and a request the browser says came from another site is refused."""
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return False
        origin = self.headers.get("Origin")
        return not origin or origin == "http://" + (self.headers.get("Host") or "")

    def _cli(self):
        """The owner's own command-line tools: the token in state/dashboard.token (0600), sent with no Origin header. A browser
        always sends an Origin on a write, so a web page cannot pass as this."""
        t = self.headers.get("X-Quarterdeck-Token", "")
        return bool(t) and not self.headers.get("Origin") and _same_token(t, TOKEN)

    def _sid(self):
        """The qd_session value of this request's cookie, read by hand (round 8, L11): SimpleCookie drops every cookie after one it finds malformed,
        and another program on 127.0.0.1 can set such a cookie (cookies are per host, not per port), which hid the session and kept a paired tab
        at 401. Of several qd_session values, the one that names a live session."""
        vals = []
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, eq, v = part.strip().partition("=")
            if eq and k == "qd_session" and v:
                vals.append(v.strip().strip('"'))
        return next((v for v in vals if session_get(v) is not None), vals[0] if vals else None)

    def _session(self):
        """The paired browser session this request's cookie names, or None."""
        sid = self._sid()
        return session_get(sid) if sid else None

    def _read_ok(self):
        """A read of anything but the page shell, the assets and /api/health needs a paired browser (cookie) or the owner's CLI token."""
        return self._cli() or (self._session() is not None and self._origin_ok())

    def _same_origin(self):
        """The browser says this request came from this server's own page: an Origin equal to it, or (no Origin) Sec-Fetch-Site
        same-origin. A request that says neither is not a browser on this page, so a session write is refused."""
        if not self._origin_ok():
            return False
        return bool(self.headers.get("Origin")) or self.headers.get("Sec-Fetch-Site") == "same-origin"

    def _tab(self):
        """The paired session, if this request carries its cookie AND the token only that tab holds (sessionStorage), else None."""
        s = self._session()
        return s if s is not None and _same_token(self.headers.get("X-Quarterdeck-Token", ""), s["token"]) else None

    def _authorised(self):
        """A write needs more than a cookie: the cookie's session token in a header (which another site cannot add without a
        preflight this server never answers, and which is never handed out for a cookie), and the browser saying it came from
        this server's own page. Or the owner's CLI token."""
        if self._cli() and urlparse(self.path).path in CLI_WRITES:
            return True
        return self._tab() is not None and self._same_origin()

    def _body(self):
        """The JSON object a write sent. A body that is too big, not JSON or not an object is refused, not read as empty."""
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            raise BodyError(400, "bad Content-Length")
        if n < 0:
            raise BodyError(400, "bad Content-Length")
        if n > MAX_BODY:
            self.close_connection = True
            raise BodyError(413, "that request is too large")                  # a request body is small; audio has its own limit
        raw = self.rfile.read(n) if n else b""
        self._deadline.cancel()
        if not raw.strip():
            return {}
        try:
            v = json.loads(raw)
        except ValueError:
            raise BodyError(400, "the request body is not JSON")
        if not isinstance(v, dict):
            raise BodyError(400, "the request body must be a JSON object")
        return v

    def do_HEAD(self):
        self.send_response(405)                                                # nothing here is served to a HEAD, and nothing is read from disk
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- reads ----
    def do_GET(self):
        if not self._local_host():
            return self._send(403, json.dumps({"error": "forbidden"}))
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            try:
                html = (ROOT / "dashboard" / "index.html").read_text()
            except Exception:
                return self._send(500, "dashboard/index.html is missing", "text/plain")
            html = html.replace("__QUARTERDECK_EXT__", "".join(f'<script src="{u}"></script>\n' for u in EXT["scripts"]))
            nonce = secrets.token_urlsafe(16)                                  # this response's scripts, and no one else's, may run
            return self._send(200, html.replace("__QUARTERDECK_NONCE__", nonce), "text/html; charset=utf-8", nonce=nonce)

        if u.path == "/api/health":                 # liveness only (no state, no real data), so it answers in Demo mode too
            return self._send(200, json.dumps(health()))

        if u.path == "/api/session":                # a reloaded tab checking that its own token (sessionStorage) still opens its session
            s = self._tab()                         # the cookie alone proves nothing: any server on 127.0.0.1 the browser visits receives it
            if s is None or not self._origin_ok():
                return self._send(401, json.dumps({"error": "unpaired"}))
            if s.get("exp", 0) - time.time() > SESSION_TTL / 2:
                return self._send(200, json.dumps({"ok": True}))
            sid = self._sid()
            session_renew(sid)                                            # in use and past half its day: another day
            return self._send(200, json.dumps({"ok": True}),
                              cookie=f"qd_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}")

        if u.path.startswith("/api/") and not self._read_ok():
            return self._send(401, json.dumps({"error": "unpaired: open Quarterdeck from the link that `qtdeck dashboard` prints"}))

        if u.path.startswith("/api/") and demo_on():
            # Answered entirely from the made-up world; a path it does not know is a 404,
            # never a fall-through to the real handler below.
            if u.path == "/api/showcase/case":
                w = DEMO["world"]; st = w.state()
                return self._demo_reply((200, case_view((q.get("id") or [""])[0], w.panel_transcript, st["fixes"], st["runs"], st["inbox"], st["fixqueue"],
                                                        {x["name"]: x["role"] for x in st["duties"]}, owner_names())))
            if u.path == "/api/mission":            # composed from the made-up world, by the same function the real one uses
                w = DEMO["world"]; st = w.state()
                m = compose_mission((q.get("id") or [""])[0], w.panel_transcript, st["fixes"], st["runs"], st["inbox"], st["fixqueue"],
                                    get_cycle=w.cycle_record, get_brief=w.maker.brief, get_plan=w.maker.plan)
                return self._demo_reply((200, m) if m else (404, {"error": "no such mission"}))
            if u.path == "/api/cycle/estimate":
                w = DEMO["world"]; pr = (q.get("project") or [""])[0]
                return self._demo_reply((200, {"project": pr, "opted_in": pr in w.cycle_projects(), **cycle_estimate_calc(
                    [r["cost"] for r in w.cycle_records().values() if r["project"] == pr and r["status"] == "awaiting-review"], 15.0, 25.0, w.spend(w.elapsed())["today"])}))
            if u.path == "/api/project-agents":     # the made-up projects have no folders: none, and nothing is read from disk
                return self._demo_reply((200, {"project": (q.get("project") or [""])[0], "agents": [], "coverage": projagents.coverage([])}))
            if u.path == "/api/mockup":             # a made-up page, still served the strict way
                return self._mockup_page((q.get("brief") or [""])[0], (q.get("name") or [""])[0])
            return self._demo_reply(DEMO["world"].get(u.path, q))

        if u.path.startswith("/assets/"):
            got = asset_file(u.path)
            if not got:
                return self._send(404, "asset not found", "text/plain")
            return self._send(200, got[0], got[1])

        if u.path == "/api/state":
            return self._send(200, json.dumps(build_state()))

        if u.path == "/api/showcase/public":
            # The one route on this server built to be read by a stranger, in
            # shape if not yet in reach — still loopback-only like everything
            # else here. What it returns is the entire public boundary.
            return self._send(200, json.dumps(public_showcase()))

        if u.path == "/api/cycle/estimate":
            pr = (q.get("project") or [""])[0]
            return self._send(200, json.dumps({"project": pr, "opted_in": (read_json(PROJECTS_FILE, {}).get(pr) or {}).get("cycle") is True, **cycle_estimate(pr)}))
        if u.path == "/api/intent":
            return self._send(200, json.dumps(intent_view()))
        if u.path == "/api/rhythm":
            return self._send(200, json.dumps(rhythm_view()))
        if u.path == "/api/connections":
            return self._send(200, json.dumps({"services": integrations_manifest.status(), "store": integrations_manifest.store_info()}))
        if u.path == "/api/settings":
            return self._send(200, json.dumps(settings_view()))
        if u.path == "/api/fleet/projects":
            return self._send(200, json.dumps({"projects": fleetview.projects()}))
        if u.path == "/api/fleet":
            return self._send(200, json.dumps(fleet_view(force=(q.get("fresh") or [""])[0] == "1")))
        if u.path == "/api/attention":
            try:
                return self._send(200, json.dumps(attention_view(int((q.get("days") or ["120"])[0] or 120))))
            except ValueError:
                return self._send(400, json.dumps({"error": "days must be a number"}))

        if u.path == "/api/timeline":
            try:
                return self._send(200, json.dumps(timeline_view((q.get("window") or ["24h"])[0])))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))

        if u.path == "/api/log":
            name = (q.get("name") or ["quarterdeck"])[0]
            if not SAFE_NAME.match(name):
                return self._send(400, json.dumps({"error": "bad name"}))
            f = LOGS / f"{name}.log"
            if not f.is_file():
                return self._send(200, json.dumps({"lines": []}))
            n = min(int((q.get("n") or ["200"])[0] or 200), 2000)
            return self._send(200, json.dumps({"lines": f.read_text(errors="replace").splitlines()[-n:]}))

        if u.path == "/api/project-agents":
            code, body = project_agents_api((q.get("project") or [""])[0])
            return self._send(code, json.dumps(body))

        if u.path == "/api/tickets":
            try:
                return self._send(200, json.dumps(tickets_view((q.get("project") or [""])[0])))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))

        if u.path == "/api/board":
            name = (q.get("project") or [""])[0]
            projects = read_json(PROJECTS_FILE, {})
            p = projects.get(name)
            if not p:
                return self._send(400, json.dumps({"error": "unknown project"}))
            if not p.get("board"):
                return self._send(200, json.dumps({"board": None}))
            hit = BOARD_CACHE.get(name)
            if not hit or time.time() - hit["at"] > BOARD_TTL or (q.get("fresh") or [""])[0]:
                try:
                    snap = board_snapshot(p["board"]["owner"], str(p["board"]["number"]),
                                          p["repo"], p["board"].get("status"))
                except Exception as e:
                    return self._send(502, json.dumps({"error": str(e)[:300]}))
                hit = {"at": time.time(), "snap": snap}
                BOARD_CACHE[name] = hit
            return self._send(200, json.dumps({
                "board": hit["snap"],
                "fetched": iso(datetime.fromtimestamp(hit["at"], timezone.utc)),
                "url": (f'https://github.com/users/{p["board"]["owner"]}'
                        f'/projects/{p["board"]["number"]}'),
            }))

        if u.path == "/api/card":
            try:
                card, at = card_view((q.get("project") or [""])[0], (q.get("number") or [""])[0],
                                     (q.get("kind") or ["issue"])[0], bool((q.get("fresh") or [""])[0]))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(502, json.dumps({"error": str(e)[:300]}))
            return self._send(200, json.dumps({"card": card, "fetched": iso(datetime.fromtimestamp(at, timezone.utc))}))

        if u.path == "/api/progress":
            name = (q.get("project") or [""])[0]
            repo = (read_json(PROJECTS_FILE, {}).get(name) or {}).get("repo")
            if not repo:
                return self._send(400, json.dumps({"error": "unknown project"}))
            try:
                return self._send(200, json.dumps(issue_progress(repo)))
            except Exception as e:
                return self._send(200, json.dumps({"error": str(e)[:200]}))
        if u.path == "/api/prs":
            name = (q.get("project") or [""])[0]
            projects = read_json(PROJECTS_FILE, {})
            names = [name] if name else sorted(projects)
            if name and name not in projects:
                return self._send(400, json.dumps({"error": "unknown project"}))
            if (q.get("fresh") or [""])[0]:
                for n in names:
                    PR_CACHE.pop(projects[n].get("repo"), None)
            runs = read_json(STATE / "runs.json", [])
            fixes = fix_index(running_locks())
            prs, errors, oldest = [], {}, time.time()
            for n in names:
                repo = projects[n].get("repo")
                if not repo:
                    continue
                try:
                    got, at = open_prs(n, repo, runs, fixes)
                    prs += got; oldest = min(oldest, at)
                except Exception as e:
                    errors[n] = str(e)[:200]
            prs.sort(key=lambda x: x["created"], reverse=True)
            return self._send(200, json.dumps({
                "prs": prs, "errors": errors,
                "fetched": iso(datetime.fromtimestamp(oldest, timezone.utc))}))

        if u.path == "/api/showcase/case":
            rows = [r for r in read_json(STATE / "runs.json", []) if isinstance(r, dict)]
            last = {(r.get("project"), r.get("duty")): r for r in rows}
            return self._send(200, json.dumps(case_view(
                (q.get("id") or [""])[0], lambda pid: read_json(PANELS / f"{pid}.json", None), fix_index(running_locks()),
                [_split_verdict(r) for r in rows[-400:][::-1]], inbox_items(last), queue_view(),
                {x["name"]: x["role"] for x in duty_list()}, owner_names())))

        if u.path == "/api/mission":
            m = _safe(lambda: mission_view((q.get("id") or [""])[0]))
            return self._send(200, json.dumps(m)) if m else self._send(404, json.dumps({"error": "no such mission"}))

        if u.path == "/api/panel":
            pid = (q.get("id") or [""])[0]
            if not valid_id(pid):
                return self._send(400, json.dumps({"error": "bad id"}))
            t = read_json(PANELS / f"{pid}.json", None)
            if t is None:
                return self._send(404, json.dumps({"error": "no such panel"}))
            return self._send(200, json.dumps(t))

        if u.path == "/api/doc":
            name = (q.get("name") or [""])[0]
            if not re.match(r"^[\w.-]{1,120}\.md$", name):
                return self._send(400, json.dumps({"error": "bad name"}))
            f = WORKSPACE / name
            if not f.is_file():
                return self._send(404, json.dumps({"error": "no such document"}))
            return self._send(200, json.dumps({"name": name, "text": f.read_text(errors="replace")}))

        if u.path == "/api/brief":
            try:
                return self._send(200, json.dumps(brief_public(brief_load((q.get("id") or [""])[0]))))
            except ValueError:
                return self._send(400, json.dumps({"error": "bad id"}))
            except KeyError:
                return self._send(404, json.dumps({"error": "no such brief"}))

        if u.path == "/api/mockup":
            return self._mockup_page((q.get("brief") or [""])[0], (q.get("name") or [""])[0])

        if u.path == "/api/plan":
            try:
                return self._send(200, json.dumps(plan_load((q.get("id") or [""])[0])))
            except ValueError:
                return self._send(400, json.dumps({"error": "bad id"}))
            except KeyError:
                return self._send(404, json.dumps({"error": "no such plan"}))

        return self._send(404, json.dumps({"error": "not found"}))

    def _mockup_page(self, bid, name):
        """A saved mock-up, served the one strict way: no script can run in it, nothing can load into it, and it cannot send anything
        out (Content-Security-Policy), it is shown only in a frame with no permissions, and it is checked again on the way out. The
        page keeps its own origin out of reach of the dashboard's token: a sandbox without allow-same-origin gives it an opaque origin."""
        import brief as _b, mockup as _m
        if not _b.id_ok(bid) or not isinstance(name, str) or not _m.NAME_RE.match(name):
            return self._send(400, json.dumps({"error": "bad id or name"}))
        try:
            html = DEMO["world"].mockup_page(bid, name) if demo_on() else _m.page(_maker_home(), bid, name)
            if demo_on() and html is not None and _m.check_page(html)["errors"]:
                html = None
        except _m.MockupError as e:
            return self._send(404, json.dumps({"error": str(e)[:200]}))
        if html is None:
            return self._send(404, json.dumps({"error": "no such mock-up"}))
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")                       # this page may be framed by the dashboard and by nobody else
        self.send_header("Content-Security-Policy", _m.STRICT_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    # ---- writes ----
    def do_POST(self):
        try:
            return self._post()
        except BodyError as e:
            return self._send(e.code, json.dumps({"error": str(e)}))

    def _pair(self):
        """Trade a one-time nonce for a session: an HttpOnly, SameSite=Strict cookie, and the API token for the page's memory."""
        if not self._origin_ok():
            return self._send(403, json.dumps({"error": "forbidden"}))
        nonce = self._body().get("nonce")
        if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
            return self._send(400, json.dumps({"error": "that is not a pairing link"}))
        ok = pair_redeem(nonce)
        if ok is None:
            return self._send(429, json.dumps({"error": "too many wrong links: wait a minute"}))
        if not ok:
            return self._send(401, json.dumps({"error": "that link has been used or has expired: run `qtdeck dashboard` for a new one"}))
        sid, token = session_new()
        cookie = f"qd_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"
        return self._send(200, json.dumps({"token": token}), cookie=cookie)

    def _post(self):
        if not self._local_host():
            return self._send(403, json.dumps({"error": "forbidden"}))
        u = urlparse(self.path)
        if u.path == "/api/pair":
            return self._pair()
        if not self._authorised():
            unpaired = not self._cli() and self._session() is None
            return self._send(401 if unpaired else 403, json.dumps({"error": "unpaired" if unpaired else "forbidden"}))

        if u.path == "/api/logout":                 # the page's way of ending its own session
            sid = self._sid()
            if sid:
                session_end(sid)
            return self._send(200, json.dumps({"ok": True}), cookie="qd_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")

        if u.path == "/api/demo":
            b = self._body()
            demo_set(bool(b.get("on")), bool(b.get("restart")))
            return self._send(200, json.dumps({"on": demo_on()}))

        # Voice is the one thing demo mode leaves on (the talk is about directing agents by voice).
        # It reads no project data there: what it is told about projects comes from the made-up world.
        voice = u.path in ("/api/transcribe", "/api/understand", "/api/speak", "/api/chat")
        if demo_on() and voice and os.environ.get("QUARTERDECK_DEMO_VOICE", "on") == "off":
            return self._send(503, json.dumps({"error": "voice is switched off in demo mode"}))
        names = sorted(demo.PROJECTS) if demo_on() else None

        if u.path == "/api/transcribe":
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = 0
            if not 44 < n <= MAX_AUDIO:
                return self._send(400, json.dumps({"error": "no audio, or too much of it"}))
            wav = self.rfile.read(n)
            self._deadline.cancel()
            try:
                vocab = speech_vocab(names if names is not None else sorted(read_json(PROJECTS_FILE, {})))
                return self._send(200, json.dumps({"text": transcribe(wav, vocab)}))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))

        b = self._body()

        if demo_on() and not voice:
            return self._demo_reply(DEMO["world"].post(u.path, b))

        if u.path == "/api/connections":
            code, body = connections_api(b)
            return self._send(code, json.dumps(body))

        if u.path == "/api/settings":
            code, body = settings_api(b)
            return self._send(code, json.dumps(body))

        if u.path == "/api/newproject":
            code, body = newproject_api(b)
            return self._send(code, json.dumps(body))

        if u.path == "/api/attach":
            code, body = attach_api(b)
            return self._send(code, json.dumps(body))

        for path_, fn_ in (("/api/ticket/draft", ticket_draft_api), ("/api/ticket/file", ticket_file_api), ("/api/ticket/discard", ticket_discard_api), ("/api/repo", repo_api)):
            if u.path == path_:
                code, body = fn_(b)
                return self._send(code, json.dumps(body))

        if u.path == "/api/fleet/action":
            code, body = fleet_action(b)
            return self._send(code, json.dumps(body))

        if u.path == "/api/understand":
            try:
                return self._send(200, json.dumps(understand(b.get("text"), b.get("views") if isinstance(b.get("views"), list) else [], names,
                                                          {n: v["duties"] for n, v in demo.PROJECTS.items()} if demo_on() else None)))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))

        if u.path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                for ev in chat_events(b):
                    self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return                      # the page stopped listening (the owner interrupted): stop writing
            except Exception as e:
                try:
                    self.wfile.write(("data: " + json.dumps({"error": str(e)[:200]}) + "\n\n").encode())
                except OSError:
                    pass
            return

        if u.path == "/api/speak":
            try:
                return self._send(200, speak(b.get("text"), b.get("voice")), "audio/wav")
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))

        if u.path in EXT["post"]:
            try:
                EXT["post"][u.path](b)
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps({"ok": True}))

        if u.path in ("/api/brief/new", "/api/brief/action", "/api/plan/action"):
            fn = {"/api/brief/new": brief_new, "/api/brief/action": brief_act, "/api/plan/action": plan_act}[u.path]
            try:
                return self._send(200, json.dumps(fn(b)))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except KeyError:
                return self._send(404, json.dumps({"error": "not found"}))
            except LookupError as e:
                return self._send(409, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)[:200]}))

        if u.path == "/api/run":
            try:
                what = spawn_run(b.get("project"), b.get("duty"), b.get("args") or [],
                                 bool(b.get("apply")))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps({"started": what}))

        if u.path == "/api/fix":
            # One item or many. Anything the project cannot start right now is
            # queued behind what is running, rather than refused.
            pid = b.get("panel", "")
            if not valid_id(pid):
                return self._send(400, json.dumps({"error": "bad panel"}))
            raw = b.get("items") if isinstance(b.get("items"), list) else [b.get("item")]
            try:
                items = [int(x) for x in raw][:100]
            except (TypeError, ValueError):
                return self._send(400, json.dumps({"error": "bad item"}))
            try:
                project, queued, skipped = enqueue(pid, items)
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            if not queued:
                return self._send(409, json.dumps({
                    "error": "nothing to queue — " + "; ".join(
                        f"#{x['item']}: {x['why']}" for x in skipped[:4])}))
            return self._send(200, json.dumps({"project": project, "queued": queued,
                                               "skipped": skipped}))

        if u.path == "/api/work":
            try:
                what = start_work(b.get("project"), b.get("issue"), b.get("action"))
            except ValueError as e:
                return self._send(409 if "already running" in str(e) else 400,
                                  json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            BOARD_CACHE.pop(b.get("project"), None)   # the card is about to move
            return self._send(200, json.dumps({"started": what}))

        if u.path == "/api/cycle/start":
            try:
                got = start_cycle(b.get("project"), b.get("issue"), b.get("confirm"), b.get("ticket"))
            except ValueError as e:
                return self._send(409 if "already running" in str(e) or "budget" in str(e) else 400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(got))

        if u.path == "/api/merge":
            try:
                rec = merge_pr(b.get("project"), b.get("number"), b.get("head_sha"))
            except ValueError as e:
                return self._send(409, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(rec))

        if u.path == "/api/missions":
            try:
                rec = mission_act(b.get("action"), b, "dashboard")
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:
                return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(rec))

        if u.path == "/api/capture":
            try:
                act = b.get("action")
                if act == "done":
                    capture_done(b.get("id"))
                    return self._send(200, json.dumps({"ok": True}))
                if act == "reopen":
                    capture_reopen(b.get("id"))
                    return self._send(200, json.dumps({"ok": True}))
                if act == "edit":
                    return self._send(200, json.dumps(capture_edit(b.get("id"), b.get("text"), b.get("project"))))
                if act == "promote":
                    return self._send(200, json.dumps(capture_promote(b.get("id"), b.get("to"), b.get("project"), b.get("confirm"))))
                return self._send(200, json.dumps(capture_add(b.get("text"), b.get("project") or "")))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except OSError as e:
                return self._send(500, json.dumps({"error": "could not write the note: " + str(e)[:120]}))

        if u.path == "/api/intent":
            try:
                return self._send(200, json.dumps(intent_set(b.get("projects"), b.get("week") or "this", b.get("confirm"))))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except OSError as e:
                return self._send(500, json.dumps({"error": "could not save the focus: " + str(e)[:120]}))

        if u.path == "/api/project-status":
            try:
                return self._send(200, json.dumps(project_status_set(b.get("project"), b.get("status"), b.get("confirm"))))
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            except OSError as e:
                return self._send(500, json.dumps({"error": "could not save: " + str(e)[:120]}))

        if u.path == "/api/inbox":
            try:
                rec = inbox_act(b.get("action"), b, "dashboard")
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(rec))

        if u.path == "/api/showcase":
            try:
                rec = showcase_act(b.get("action"), b, "dashboard")
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps(rec))

        if u.path == "/api/fixqueue":
            project = b.get("project", "")
            if project not in read_json(PROJECTS_FILE, {}):
                return self._send(400, json.dumps({"error": "unknown project"}))
            action = b.get("action")
            with QLOCK:
                q = load_q(project)
                if action == "pause":
                    q["paused"] = True
                elif action == "resume":
                    q["paused"] = False
                elif action == "clear":
                    # a fix already running is left to finish; only waiting ones go
                    q["items"] = [x for x in q["items"] if x.get("state") == "active"]
                elif action == "remove":
                    q["items"] = [x for x in q["items"] if not (
                        x.get("panel") == b.get("panel") and x.get("item") == b.get("item")
                        and x.get("state") == "pending")]
                else:
                    return self._send(400, json.dumps({"error": "bad action"}))
                save_q(project, q)
            drain_fix_queues()
            return self._send(200, json.dumps({"ok": action}))

        if u.path == "/api/stop":
            lock = b.get("lock", "")
            if not SAFE_LOCK.match(lock or ""):
                return self._send(400, json.dumps({"error": "bad lock"}))
            d = STATE / f"{lock}.lock"
            try:
                pid = int((d / "pid").read_text().strip())
            except Exception:
                return self._send(404, json.dumps({"error": "not running"}))
            # A lock can outlive its run, and a pid gets reused. Signal it only
            # if it is still one of Quarterdeck's own scripts.
            try:
                cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                     capture_output=True, text=True, timeout=5).stdout
            except Exception:
                cmd = ""
            if str(ROOT) not in cmd:
                return self._send(404, json.dumps({"error": "not running"}))
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception as e:
                    return self._send(500, json.dumps({"error": str(e)}))
            return self._send(200, json.dumps({"stopped": lock}))

        if u.path == "/api/schedule":
            scheds = load_schedules()
            sid = b.get("id")
            if b.get("delete"):
                scheds = [s for s in scheds if s.get("id") != sid]
                write_json(SCHEDULES_FILE, scheds)
                return self._send(200, json.dumps({"deleted": sid}))
            if b.get("toggle"):
                for s in scheds:
                    if s.get("id") == sid:
                        s["paused"] = not s.get("paused")
                write_json(SCHEDULES_FILE, scheds)
                return self._send(200, json.dumps({"toggled": sid}))
            try:
                validate_run(b.get("project"), b.get("duty"), b.get("args") or [])
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}))
            every, at = (b.get("every") or "").strip(), (b.get("at") or "").strip()
            if at and not AT.match(at):
                return self._send(400, json.dumps({"error": "time must be HH:MM"}))
            if not at and not EVERY.match(every):
                return self._send(400, json.dumps({"error": "interval must look like 30m, 4h or 1d"}))
            s = {
                "id": secrets.token_hex(4),
                "project": b["project"], "duty": b["duty"],
                "args": [a for a in (b.get("args") or []) if a],
                "apply": bool(b.get("apply")),
                "every": "" if at else every, "at": at,
                "paused": False,
                "created": iso(now_utc()),
                "last_run": None,
            }
            scheds.append(s)
            write_json(SCHEDULES_FILE, scheds)
            return self._send(200, json.dumps(s))

        return self._send(404, json.dumps({"error": "not found"}))


MAX_CONNECTIONS = 96                # served at once; launchd gives the dashboard 256 file descriptors, and the rest are its own


def make_server(port):
    slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    class Server(ThreadingHTTPServer):
        request_queue_size = 128        # the default of 5 resets connections when a burst arrives on macOS (found by smoke.py)

        def process_request(self, request, client_address):
            if not slots.acquire(blocking=False):
                return self.shutdown_request(request)                  # full: closed at once, never queued behind idle sockets
            try:
                super().process_request(request, client_address)
            except Exception:
                slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                slots.release()
    sessions_revoke()               # a process that held this port while the dashboard was down may have the old cookie and token: they stop working. The owner pairs again with `qtdeck dashboard link`
    # and the pending pairing links (audit 7, L2): an impostor holding the port served the page a link opened and read its #pair= code; once the
    # real server bound, that code was still good for five minutes. bin/qtdeck mints the link it prints only after this server answers.
    for f in (STATE / "pair").glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    return Server(("127.0.0.1", port), Handler)


def main():
    os.umask(0o077)                                          # everything this server writes (state, logs, notes, pairing) is owner-only
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # atexit stops the helpers; non-zero so launchd restarts us
    if os.environ.get("QUARTERDECK_DEMO") == "1":
        demo_set(True)
    STATE.mkdir(exist_ok=True)
    PANELS.mkdir(parents=True, exist_ok=True)
    (STATE / "dashboard.pid").write_text(str(os.getpid()))
    tok = STATE / "dashboard.token"
    fd = os.open(tok, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)            # owner-only from the first byte, not after
    with os.fdopen(fd, "w") as f:
        f.write(TOKEN)
    os.chmod(tok, 0o600)
    threading.Thread(target=scheduler_loop, daemon=True).start()
    threading.Thread(target=agenda_loop, daemon=True).start()
    threading.Thread(target=attention_loop, daemon=True).start()
    try:
        import integrations.loop as _il
        _il.SKIP = demo_on                                  # demo mode never calls a real service
        from integrations.loop import integration_loop      # direct feeds, bin/integrations/
        threading.Thread(target=integration_loop, daemon=True).start()
    except Exception:
        pass
    threading.Thread(target=helm_reaper, daemon=True).start()
    for start in EXT["start"]:
        start()
    # Threaded so a slow GitHub call (board/PR reads) can't freeze every other
    # tab's poll behind it. State files are already written atomically
    # (write_json: temp file + rename), and locks are re-read from disk on
    # every check, never cached — so the real cost of two requests landing at
    # once is a duplicate GitHub fetch or a lost cache update, not corruption.
    # ponytail: no per-key locking on the in-memory BOARD_CACHE/PR_CACHE dicts;
    # add it if a real race ever shows up as more than a stale read.
    srv = make_server(PORT)
    print(f"qtdeck dashboard on http://127.0.0.1:{PORT}", flush=True)
    if not demo_on() and fleetview.projects():       # read the registered fleets once now, so the first look at Fleet is not a wait
        threading.Thread(target=fleet_view, kwargs={"force": True}, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


EXTENSIONS = load_extensions()


if __name__ == "__main__":
    if sys.argv[1:3] == ["sessions", "revoke"]:      # `qtdeck dashboard sessions revoke`: every paired browser is signed out, in a running dashboard too
        sessions_revoke()
        print("every paired browser is signed out; `qtdeck dashboard link` pairs one again")
        sys.exit(0)
    if sys.argv[1:2] == ["link"]:           # `qtdeck dashboard link`: a fresh one-time link, made by writing into state/, never over HTTP
        STATE.mkdir(parents=True, exist_ok=True)
        print(pair_link())
        sys.exit(0)
    main()
