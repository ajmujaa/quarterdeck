#!/usr/bin/env python3
"""Level 2 of "show your own agents": an agent source you add in a form on the Connections page.

A source is a small JSON API somewhere else (an https address, or an http://127.0.0.1:<port> tunnel the owner runs; Quarterdeck never starts
ssh or a tunnel). Quarterdeck asks it for one list of agents or tasks, keeps four mapped fields of each, and shows them in Fleet and, when one
is running, in the Running now strip on Home. Read only: it only ever sends a GET.

Rules this module keeps:
  * config/agent-sources.json (mode 0600) holds the name, address and field map. The token is not in it. The token goes to the same
    credential store as the other connections (the private file or the macOS Keychain) under AGENT_SOURCE_TOKEN@<id>, through
    bin/integrations/manifest.py, and is read back only to build the Authorization header of the request. It is never written to a
    snapshot, a log line or an error message.
  * address: https://... or http://127.0.0.1:<port>/... and nothing else; no user name or password in it, no secret in its query.
  * no redirects at all (a redirect would carry the token to another host), 10 seconds in total, a reply of at most 256 KB.
  * a source is asked at most once every 60 seconds, from a background thread, so a slow source never stalls the dashboard.
  * only the mapped fields are kept (name, status, last run, detail), each cut to a length cap and shown as text, never as markup.
    Snapshots go to state/agent-sources/<id>/snapshot.json; the reply body is not stored.
"""
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import home as _home
from integrations import accounts, common, manifest

TIMEOUT = 10
MAX_BYTES = 256 * 1024
MIN_INTERVAL = 60
MAX_SOURCES = 12
MAX_AGENTS = 60
NAME_MAX, DETAIL_MAX, LAST_MAX, NAME_SRC_MAX = 80, 200, 40, 60
PATH_PART = re.compile(r"[A-Za-z0-9_-]{1,40}")
LOCAL_URL = re.compile(r"http://127\.0\.0\.1:([0-9]{1,5})(/[^\s]*)?")
STATUSES = ("running", "waiting", "done", "failed", "unknown")
WORDS = {"running": ("running", "active", "in_progress", "in-progress", "in progress", "started", "busy", "working", "executing", "processing", "live", "on"),
         "waiting": ("waiting", "pending", "queued", "paused", "idle", "blocked", "needs_input", "waiting_for_input", "scheduled"),
         "done": ("done", "success", "succeeded", "completed", "complete", "ok", "finished", "passed"),
         "failed": ("failed", "failure", "error", "errored", "crashed", "cancelled", "canceled", "aborted", "timeout", "timed_out")}
FIELDS = ("name", "status", "last_run", "detail")
PRESETS = [
    {"id": "https-list", "label": "A JSON list over HTTPS", "name": "Relay tasks", "url": "https://agents.example.com/api/tasks",
     "map": {"list": "tasks", "name": "title", "status": "state", "last_run": "finished_at", "detail": "message"},
     "note": "The address answers with JSON such as {\"tasks\": [{\"title\": \"Nightly report\", \"state\": \"running\", \"finished_at\": \"2026-01-05T08:00:00Z\", \"message\": \"3 of 10 done\"}]}. "
             "The token, if it needs one, is sent as a bearer token."},
    {"id": "ssh-tunnel", "label": "A dashboard reached through my own SSH tunnel", "name": "Relay dashboard", "url": "http://127.0.0.1:8081/api/agents",
     "map": {"list": "data.agents", "name": "name", "status": "status", "last_run": "updated_at", "detail": "summary"},
     "note": "You start the tunnel yourself, for example ssh -L 8081:localhost:8081 you@host.example.com, and leave it running. Quarterdeck never starts ssh or a tunnel. "
             "Then the address is http://127.0.0.1:8081/ plus the path."},
]

_LOCK = threading.RLock()
_BUSY = set()
_LAST = {}                       # source id -> when it was last asked (this run)


class SourceError(Exception):
    """A plain-words reason a source could not be read. Never holds the token, the address or any part of the reply."""


# ---- config -------------------------------------------------------------------------------------------------------------------------------

def _paths(home=None):
    h = Path(home) if home else _home.resolve()
    return h / "config" / "agent-sources.json", h / "state" / "agent-sources"


def load(home=None):
    """The sources in config/agent-sources.json, validated again on every read. A bad entry is skipped, a bad file reads as no sources."""
    cfg, _ = _paths(home)
    try:
        raw = json.loads(cfg.read_text())
    except (OSError, ValueError):
        return []
    out = []
    for r in (raw.get("sources") if isinstance(raw, dict) else None) or []:
        s, err = clean_source(r)
        if s and not err and all(o["id"] != s["id"] for o in out):
            out.append(s)
    return out[:MAX_SOURCES]


def _save(sources, home=None):
    cfg, _ = _paths(home)
    common.write_private(cfg, json.dumps({"sources": sources}, indent=2) + "\n")


def check_url(url):
    """The address with nothing changed, or SourceError saying why not."""
    if not isinstance(url, str) or not url.strip() or len(url) > 300 or re.search(r"[\s\x00-\x1f\x7f]", url):
        raise SourceError("The address must be one line of at most 300 characters, with no spaces.")
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https":
        if not p.hostname:
            raise SourceError("The address has no host name.")
    elif p.scheme == "http":
        m = LOCAL_URL.fullmatch(url.split("?", 1)[0].split("#", 1)[0])
        if not m or not 1 <= int(m.group(1)) <= 65535:
            raise SourceError("Plain http is only allowed for a tunnel on this computer: http://127.0.0.1:<port>. Any other address must start with https://.")
    else:
        raise SourceError("The address must start with https://, or be http://127.0.0.1:<port> for a tunnel you run yourself.")
    try:
        p.port
    except ValueError:
        raise SourceError("The port in the address is not a number between 1 and 65535.")
    if p.username is not None or p.password is not None or "@" in p.netloc:
        raise SourceError("The address must not hold a user name or password. Put the token in the token field.")
    if p.fragment:
        raise SourceError("The address must not end with a # part.")
    if any(common.SECRET_PARAM.search(k) for k, _v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)):
        raise SourceError("The address must not carry a secret in its query. Put the token in the token field.")
    return url


def check_path(path, what, required):
    if path is None:
        path = ""
    if not isinstance(path, str):
        raise SourceError(f"The {what} must be a path such as data.items")
    path = path.strip()
    if path in ("", "$"):
        if required:
            raise SourceError(f"The {what} needs a path such as title or state.")
        return ""
    parts = path.split(".")
    if len(parts) > 6 or not all(PATH_PART.fullmatch(x) for x in parts):
        raise SourceError(f"The {what} path is names separated by dots, such as data.items (up to 6 names, letters, digits, - and _).")
    return path


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:24].strip("-")
    return s if accounts.valid(s) and s != accounts.DEFAULT else ("source-" + s if s and s != accounts.DEFAULT else "source")


def clean_source(raw):
    """(source, None) or (None, reason). Never raises."""
    try:
        if not isinstance(raw, dict):
            raise SourceError("A source is an object.")
        name = raw.get("name")
        if isinstance(name, str) and re.search(r"[\x00-\x1f\x7f]", name):
            raise SourceError("The name may not hold control characters.")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_SRC_MAX:
            raise SourceError(f"The name is a short label of up to {NAME_SRC_MAX} characters.")
        sid = raw.get("id")
        if not isinstance(sid, str) or not accounts.valid(sid) or sid == accounts.DEFAULT:
            raise SourceError("The id is lower case letters, digits and dashes, at most 24.")
        m = raw.get("map")
        if not isinstance(m, dict):
            raise SourceError("The field map is missing.")
        fm = {"list": check_path(m.get("list"), "list", False)}
        for f in FIELDS:
            fm[f] = check_path(m.get(f), f, f in ("name", "status"))
        words = {}
        for k, v in (raw.get("status_words") or {}).items() if isinstance(raw.get("status_words"), dict) else []:
            if k in WORDS and isinstance(v, list):
                words[k] = [str(x).strip().lower()[:30] for x in v if isinstance(x, (str, int)) and str(x).strip()][:10]
        out = {"id": sid, "name": name.strip(), "url": check_url(raw.get("url")), "map": fm}
        if words:
            out["status_words"] = words
        return out, None
    except SourceError as e:
        return None, str(e)


def token_key():
    return common.AGENT_SOURCE_KEY


def _token(sid):
    """The token of one source from the credential store, or "". Used only to build the request header."""
    try:
        stored = manifest.stored_name(common.AGENT_SOURCE_KEY, sid)
        if common.store_kind() == "keychain":
            from integrations import keychain
            return keychain.get(stored) or ""
        return common.read_env_file().get(stored, "") if common.env_path().is_file() else ""
    except Exception:
        return ""


def has_token(sid):
    return bool(_token(sid))


def add(b, home=None):
    """Add a source from the form. b: name, url, token (optional), map {list, name, status, last_run, detail}. Returns the stored source.
    Raises ValueError with a plain reason."""
    with _LOCK:
        have = load(home)
        if len(have) >= MAX_SOURCES:
            raise ValueError(f"At most {MAX_SOURCES} sources. Remove one first.")
        name = b.get("name")
        sid = b.get("id") or slug(name if isinstance(name, str) else "")
        base, n = sid, 2
        while not b.get("id") and any(s["id"] == sid for s in have):
            sid = f"{base[:21]}-{n}"
            n += 1
        if any(s["id"] == sid for s in have):
            raise ValueError("A source with that id exists already.")
        src, err = clean_source({"id": sid, "name": name, "url": b.get("url"), "map": b.get("map"), "status_words": b.get("status_words")})
        if err:
            raise ValueError(err)
        token = b.get("token")
        if token is not None and not isinstance(token, str):
            raise ValueError("The token is text.")
        _save([{k: v for k, v in s.items()} for s in have] + [src], home)
        try:
            if token and token.strip():
                manifest.set_credential(common.AGENT_SOURCE_KEY, token, label=sid)
        except Exception:
            _save(have, home)                       # the token did not reach the store: leave nothing half added
            raise
        return src


def remove(sid, home=None):
    """Forget a source: its entry, its token and its snapshots. Returns whether it existed."""
    with _LOCK:
        have = load(home)
        if not accounts.valid(sid) or all(s["id"] != sid for s in have):
            return False
        _save([s for s in have if s["id"] != sid], home)
        try:
            manifest.set_credential(common.AGENT_SOURCE_KEY, "", label=sid)
        except Exception:
            pass
        _, snaps = _paths(home)
        d = snaps / sid
        if d.is_dir() and not d.is_symlink():
            for f in d.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                d.rmdir()
            except OSError:
                pass
        _LAST.pop(sid, None)
        return True


# ---- reading one source -------------------------------------------------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                  # never follow: the token would go to the other host


def _opener(url):
    handlers = [_NoRedirect()]
    if url.startswith("http://"):
        handlers.insert(0, urllib.request.ProxyHandler({}))      # a tunnel on this computer never goes through a proxy
    return urllib.request.build_opener(*handlers)


def fetch_body(url, token=""):
    """The reply as parsed JSON. Raises SourceError with a plain sentence."""
    check_url(url)
    hdrs = {"Accept": "application/json", "User-Agent": "Quarterdeck"}
    if token:
        hdrs["Authorization"] = "Bearer " + token
    deadline = time.monotonic() + TIMEOUT
    try:
        with _opener(url).open(urllib.request.Request(url, method="GET", headers=hdrs), timeout=TIMEOUT) as r:
            try:
                if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
                    raise SourceError("Its reply is larger than 256 KB, so it was not read.")
            except ValueError:
                pass
            buf = bytearray()
            while True:
                chunk = r.read(8192)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise SourceError("Its reply is larger than 256 KB, so it was not read.")
                if time.monotonic() > deadline:
                    raise SourceError("It did not finish answering within 10 seconds.")
    except SourceError:
        raise
    except urllib.error.HTTPError as e:
        c = e.code
        if 300 <= c < 400:
            raise SourceError("It tried to send Quarterdeck to another address. Redirects are never followed, so nothing was read.")
        if c in (401, 403):
            raise SourceError(f"It refused the token (HTTP {c}). Check the token.")
        if c == 404:
            raise SourceError("Nothing is at that address (HTTP 404). Check the address.")
        if c == 429:
            raise SourceError("It is asking Quarterdeck to slow down (HTTP 429). It will try again later.")
        if c >= 500:
            raise SourceError(f"The source is having trouble (HTTP {c}).")
        raise SourceError(f"It refused the request (HTTP {c}).")
    except (socket.timeout, TimeoutError):
        raise SourceError("It did not answer within 10 seconds.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise SourceError("It did not answer within 10 seconds.")
        raise SourceError("Could not reach it. Check the address and your connection, and that the tunnel is running if you use one.")
    except Exception:
        raise SourceError("Could not reach it. Check the address and your connection, and that the tunnel is running if you use one.")
    try:
        return json.loads(bytes(buf).decode("utf-8"))
    except ValueError:
        raise SourceError("It answered with something that is not JSON.")


def _walk(doc, path):
    for part in path.split(".") if path else []:
        if isinstance(doc, dict) and part in doc:
            doc = doc[part]
        elif isinstance(doc, list) and part.isdigit() and int(part) < len(doc):
            doc = doc[int(part)]
        else:
            return None
    return doc


def _text(v, n):
    """A value as short plain text, or "". Lists and objects are not text. Control characters become spaces; markup stays as the characters it is."""
    if isinstance(v, bool):
        v = "yes" if v else "no"
    if not isinstance(v, (str, int, float)):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f  ]", " ", str(v))).strip()[:n]


def _when(v):
    """(ISO time in UTC, "") for a time Quarterdeck can read, else ("", short text)."""
    t = None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        t = v / 1000 if v > 1e11 else v
    elif isinstance(v, str) and v.strip():
        s = v.strip()
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            t = (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            try:
                t = float(s) / (1000 if float(s) > 1e11 else 1)
            except ValueError:
                return "", _text(s, LAST_MAX)
    if t is None:
        return "", ""
    try:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), ""
    except (OverflowError, OSError, ValueError):
        return "", ""


def map_status(v, words=None):
    s = _text(v, 40).lower()
    for st in ("running", "waiting", "done", "failed"):
        if s in WORDS[st] or s in (words or {}).get(st, ()):
            return st
    return "unknown"


def extract(doc, src):
    """The agents of one reply: [{name, status, last_run, last_run_text, detail}], only the mapped fields. Raises SourceError."""
    m = src["map"]
    rows = _walk(doc, m["list"])
    if isinstance(rows, dict):          # an object keyed by name is a list too
        rows = [dict(v, **{"_key": k}) if isinstance(v, dict) else v for k, v in rows.items()]
    if not isinstance(rows, list):
        raise SourceError("The reply has no list at \"%s\". Check the list path in the field map." % (m["list"] or "the top"))
    out = []
    for r in rows[:MAX_AGENTS]:
        if not isinstance(r, dict):
            continue
        name = _text(_walk(r, m["name"]), NAME_MAX)
        if not name:
            continue
        when, when_text = _when(_walk(r, m["last_run"])) if m["last_run"] else ("", "")
        out.append({"name": name, "status": map_status(_walk(r, m["status"]), src.get("status_words")), "last_run": when, "last_run_text": when_text,
                    "detail": _text(_walk(r, m["detail"]), DETAIL_MAX) if m["detail"] else ""})
    return out


# ---- snapshots and the background refresh ------------------------------------------------------------------------------------------------

def read_snapshot(sid, home=None):
    _, snaps = _paths(home)
    try:
        d = json.loads((snaps / sid / "snapshot.json").read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write_snapshot(sid, doc, home=None):
    _, snaps = _paths(home)
    d = snaps / sid
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    common.write_private(d / "snapshot.json", json.dumps(doc, indent=2) + "\n")


def refresh(src, home=None, now=None):
    """Ask one source once and write its snapshot. Runs on a background thread; does not check the interval (due() does). Returns the snapshot."""
    now = now or time.time()
    old = read_snapshot(src["id"], home) or {}
    try:
        agents = extract(fetch_body(src["url"], _token(src["id"])), src)
        snap = {"id": src["id"], "attempted_at": now, "ok": True, "ok_at": now, "error": "", "agents": agents}
    except SourceError as e:
        snap = {"id": src["id"], "attempted_at": now, "ok": False, "ok_at": old.get("ok_at"), "error": str(e), "agents": old.get("agents") or []}
    except Exception:
        snap = {"id": src["id"], "attempted_at": now, "ok": False, "ok_at": old.get("ok_at"), "error": "Something went wrong reading it.", "agents": old.get("agents") or []}
    try:
        _write_snapshot(src["id"], snap, home)
    except OSError:
        pass
    return snap


def due(src, now=None, home=None):
    now = now or time.time()
    last = _LAST.get(src["id"])
    if last is None:
        last = (read_snapshot(src["id"], home) or {}).get("attempted_at") or 0
    return now - last >= MIN_INTERVAL


def kick(home=None, now=None, spawn=True):
    """Start a background refresh for every source that is due and not already being read. Returns at once; never waits on a source."""
    now = now or time.time()
    started = []
    for src in load(home):
        with _LOCK:
            if src["id"] in _BUSY or not due(src, now, home):
                continue
            _BUSY.add(src["id"])
            _LAST[src["id"]] = now
        started.append(src["id"])

        def run(s=src):
            try:
                refresh(s, home, now)
            finally:
                with _LOCK:
                    _BUSY.discard(s["id"])
        if spawn:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
    return started


# ---- what the pages read ---------------------------------------------------------------------------------------------------------------

def fleet_sources(home=None):
    """Fleet-shaped rows, one per source, from the snapshots only (no network)."""
    out = []
    for src in load(home):
        sn = read_snapshot(src["id"], home)
        out.append({"id": "source:" + src["id"], "kind": "agent-source", "project": "", "title": src["name"], "about": "", "implicit": False,
                    "agents": (sn or {}).get("agents") or [], "error": ((sn or {}).get("error") or "") if sn else "",
                    "waiting": sn is None, "ok_at": (sn or {}).get("ok_at"), "attempted_at": (sn or {}).get("attempted_at")})
    return out


def settings_view(home=None):
    """What the Connections page shows: each source with where it stands, never the token (only whether one is saved), and the presets."""
    rows = []
    for src in load(home):
        sn = read_snapshot(src["id"], home)
        parsed = urllib.parse.urlsplit(src["url"])
        rows.append({"id": src["id"], "name": src["name"], "host": parsed.netloc, "token": has_token(src["id"]), "map": src["map"],
                     "state": "waiting" if sn is None else "ok" if sn.get("ok") else "unreachable", "error": (sn or {}).get("error") or "",
                     "agents": len((sn or {}).get("agents") or []), "ok_at": (sn or {}).get("ok_at"), "attempted_at": (sn or {}).get("attempted_at")})
    return {"sources": rows, "presets": PRESETS, "interval": MIN_INTERVAL, "max": MAX_SOURCES}
