"""Shared plumbing for the direct feeds: snapshots, status, one HTTP helper, credentials.

No AI is involved anywhere in here. Nothing in this file logs a header, a token or a response
body, and every error a caller sees is a short sentence the owner can act on.
"""
import fcntl
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import home as _home

ROOT = Path(__file__).resolve().parents[2]              # the program
HOME = _home.resolve()                                   # your data (bin/home.py)
STATE = HOME / "state"
CONFIG_DIR = Path.home() / ".config" / "quarterdeck"
ENV_NAME = "integrations.env"
TIMEOUT = 15
MAX_ITEMS = 12
SLEEP = time.sleep
SECRET_PARAM = re.compile(r"token|secret|key|password|auth", re.I)

DEFAULT_CONFIG = {
    "sources": {
        "ga4": {"enabled": False, "minutes": 60},
        "gmail": {"enabled": False, "minutes": 10},
        "slack": {"enabled": False, "minutes": 5},
        "linkedin": {"enabled": False, "minutes": 60},
        "meta": {"enabled": False, "minutes": 60},
        "macmail": {"enabled": False, "minutes": 10},
        "threads": {"enabled": False, "minutes": 60},
        "x": {"enabled": False, "minutes": 60},
    },
    "ga4": {"property_id": "", "site_url": ""},
}


class IntegrationError(Exception):
    """A failure whose text is safe to show: short, no secrets, says what to do."""

    def __init__(self, short, status=None):
        super().__init__(short)
        self.short = short
        self.status = status


def clip(x, n):
    return " ".join(x.split())[:n] if isinstance(x, str) else ""


def https_url(u):
    return u if isinstance(u, str) and u.startswith("https://") and len(u) <= 600 else None


def make_item(title, sub="", at="", new=False, url=None):
    return {"title": clip(title, 140) or "(untitled)", "sub": clip(sub, 140), "at": clip(at, 40),
            "new": bool(new), "url": https_url(url)}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_private(path, text):
    """Atomic write, owner-only: temp file in the same folder, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def write_snapshot(name, items, unread=None):
    """state/connectors/<name>.json in the shape brain_connectors() reads."""
    clean = [make_item(i.get("title"), i.get("sub"), i.get("at"), i.get("new"), i.get("url"))
             for i in items[:MAX_ITEMS]]
    d = {"updated": now_iso(), "items": clean}
    if isinstance(unread, int):
        d["unread"] = unread
    d_dir = STATE / "connectors"
    d_dir.mkdir(parents=True, exist_ok=True)
    write_private(d_dir / f"{name}.json", json.dumps(d, indent=2))


def status_path():
    return STATE / "integrations-status.json"


def read_status():
    try:
        d = json.loads(status_path().read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def record_status(name, ok, error_short="", seconds=0.0):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "integrations-status.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)           # sources run in separate processes
        d = read_status()
        d[name] = {"ok": bool(ok), "at": now_iso(), "error_short": clip(error_short, 120),
                   "seconds": round(float(seconds), 1)}
        write_private(status_path(), json.dumps(d, indent=2))


# ---- credentials and config ---------------------------------------------------

def env_path():
    return CONFIG_DIR / ENV_NAME


def store_kind():
    """Where credentials live: "file" (the default) or "keychain" (opt-in, config/integrations.json credential_store)."""
    try:
        d = json.loads((HOME / "config" / "integrations.json").read_text())
    except Exception:
        return "file"
    return "keychain" if isinstance(d, dict) and d.get("credential_store") == "keychain" else "file"


def load_env():
    if store_kind() != "keychain":
        return read_env_file()
    from integrations import keychain, manifest          # lazy: manifest imports this module
    try:
        out = {k: v for k in sorted(manifest.known_keys()) for v in [keychain.get(k)] if v}
    except keychain.KeychainError as e:
        raise IntegrationError(f"the credential store is the macOS Keychain: {e}")
    if not out:
        raise IntegrationError("needs credentials: none are saved in the macOS Keychain (Connections page)")
    return out


def read_env_file():
    p = env_path()
    if not p.is_file():
        raise IntegrationError(f"needs credentials: create ~/.config/quarterdeck/{ENV_NAME} (see the README)")
    if p.stat().st_mode & 0o077:
        raise IntegrationError(f"~/.config/quarterdeck/{ENV_NAME} is readable by others: run chmod 600 on it")
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("\"'")
    return out


def need(env, key):
    v = env.get(key, "")
    if not v:
        raise IntegrationError(f"needs credentials: add {key} to ~/.config/quarterdeck/{ENV_NAME}")
    return v


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        d = json.loads((HOME / "config" / "integrations.json").read_text())
    except Exception:
        return cfg
    if isinstance(d, dict):
        for name, v in (d.get("sources") or {}).items():
            if isinstance(v, dict):
                cfg["sources"].setdefault(name, {}).update(v)
        if isinstance(d.get("ga4"), dict):
            cfg["ga4"].update(d["ga4"])
    return cfg


# ---- HTTP -----------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                  # a redirect would forward the Authorization header to another host


_NO_REDIRECT = urllib.request.build_opener(_NoRedirect)
SNAPSHOT_NAMES = {"meta": ("facebook", "instagram")}   # a source that writes more than one snapshot


def snapshots_of(name):
    return SNAPSHOT_NAMES.get(name, (name,))


def _urllib_transport(method, url, headers, data, timeout):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _NO_REDIRECT.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""                      # the body is never read, so it can never be logged
    except Exception:
        raise IntegrationError("network error: could not reach the service")


TRANSPORT = _urllib_transport                   # tests swap in a fake with the same signature


def _status_text(code):
    if code == 401:
        return "token expired or rejected (HTTP 401): sign in again"
    if code == 403:
        return "permission denied (HTTP 403): check the scopes or access"
    if code == 404:
        return "not found (HTTP 404): check the id in the env file or config"
    if code == 429:
        return "rate limited (HTTP 429): will retry on the next refresh"
    if code >= 500:
        return f"the service is having trouble (HTTP {code})"
    return f"request rejected (HTTP {code})"


def request(method, url, *, headers=None, params=None, json_body=None, form=None):
    """JSON in, JSON out. Retries 429 and 5xx with backoff. Secrets go in headers or a form body,
    never in the URL."""
    if not url.startswith("https://"):
        raise IntegrationError("refusing a non-https address")
    if params:
        if any(SECRET_PARAM.search(str(k)) for k in params):
            raise IntegrationError("refusing to put a secret in a URL")
        url += ("&" if "?" in url else "?") + urlencode(params, doseq=True)
    hdrs = {"Accept": "application/json", **(headers or {})}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    delay = 1
    for attempt in range(4):
        status, raw = TRANSPORT(method, url, hdrs, data, TIMEOUT)
        if status in (429, 500, 502, 503, 504) and attempt < 3:
            SLEEP(delay)
            delay *= 2
            continue
        break
    if status >= 400:
        raise IntegrationError(_status_text(status), status)
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        raise IntegrationError("the service sent something that is not JSON")


def fmt_int(n):
    return f"{int(n):,}"


def pct_change(now, prior):
    if not prior:
        return "new" if now else "no change"
    return f"{(now - prior) / prior * 100:+.0f}%"
