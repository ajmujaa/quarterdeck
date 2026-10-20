"""Service manifests: what a connection is, what it needs, and where it stands. Plain data, no network, no secret values.

A service is one JSON file in bin/integrations/services/ (or in your data folder under config/services/, for a service of your own):
  id, label, what, snapshots[], minutes, local?, module?  (module is the python file in bin/integrations that fetches it)
  credentials[]: {key, label, secret, help}   the names it needs; the values are never read back out of the store
  steps[]: plain sentences, shown on the Connections page
  help, all optional and all plain text: reads[] and not_reads[] (what it reads and what it never reads), scopes[] (what to grant, read-only where the
  service allows), revoke (how to take access back), tested (what was and was not checked; the default says it was not tested against the real service),
  links[] ({label, url}, https only, a provider's own pages), and per credential looks (what the value looks like)
Adding a service is adding a file. status() says where each one stands: off, needs set-up, ready, ok or failing, and when it last refreshed.
"""
import contextlib
import fcntl
import json
import re
import threading
from pathlib import Path

from integrations import common, keychain

BUILTIN = Path(__file__).resolve().parent / "services"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
SAFE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{2,60}$")


def user_dir():
    return common.HOME / "config" / "services"


NOT_TESTED = "Not tested against the real service."
VERIFIED = "Tested against the real service"          # a manifest earns the Tested pill only by saying so in these words


def _lines(v, n, size):
    return [common.clip(x, size) for x in (v or []) if isinstance(x, str) and x.strip()][:n]


def _clean(raw):
    """One validated manifest, or None. Never raises."""
    if not isinstance(raw, dict) or not SAFE_ID.match(str(raw.get("id", ""))):
        return None
    creds = []
    for c in raw.get("credentials") or []:
        if not isinstance(c, dict) or not SAFE_KEY.match(str(c.get("key", ""))):
            return None
        creds.append({"key": c["key"], "label": common.clip(c.get("label") or c["key"], 60), "secret": c.get("secret") is not False, "help": common.clip(c.get("help"), 240),
                      "looks": common.clip(c.get("looks"), 120), "optional": c.get("optional") is True})
    snaps = [s for s in raw.get("snapshots") or [] if isinstance(s, str) and SAFE_ID.match(s)] or [raw["id"]]
    module = str(raw.get("module") or "")
    if module and not SAFE_ID.match(module.replace("_", "-")):
        return None
    return {"id": raw["id"], "label": common.clip(raw.get("label") or raw["id"], 40), "what": common.clip(raw.get("what"), 200), "snapshots": snaps,
            "minutes": int(raw["minutes"]) if isinstance(raw.get("minutes"), int) and 0 <= raw["minutes"] <= 1440 else 60, "local": raw.get("local") is True,
            "module": module, "credentials": creds, "settings": [s for s in raw.get("settings") or [] if isinstance(s, str) and SAFE_ID.match(s.replace("_", "-"))],
            "steps": [common.clip(s, 240) for s in raw.get("steps") or [] if isinstance(s, str)][:12],
            "reads": _lines(raw.get("reads"), 6, 160), "not_reads": _lines(raw.get("not_reads"), 6, 160), "scopes": _lines(raw.get("scopes"), 10, 120),
            "revoke": common.clip(raw.get("revoke"), 400), "tested": common.clip(raw.get("tested"), 240) or NOT_TESTED,
            "links": [{"label": common.clip(l.get("label"), 80) or "Provider page", "url": l["url"]} for l in (raw.get("links") or [])[:6]
                      if isinstance(l, dict) and common.https_url(l.get("url"))]}


def load_services(extra=None):
    """Built-in services, then yours; a file of yours with a built-in's id replaces it. A bad file is skipped, never fatal."""
    out = {}
    for d in (BUILTIN, Path(extra) if extra else user_dir()):
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                m = _clean(json.loads(f.read_text()))
            except (OSError, ValueError):
                m = None
            if m:
                out[m["id"]] = m
    return list(out.values())


def env_keys():
    """The credential NAMES present in the active store, never the values."""
    if common.store_kind() == "keychain":
        try:
            return {k for k in known_keys() if keychain.has(k)}
        except keychain.KeychainError:
            return set()
    p = common.env_path()
    keys = set()
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if common.unquote(v.strip()):
                    keys.add(k.strip())
    except OSError:
        pass
    return keys


def status(services=None, cfg=None, have=None, recorded=None):
    """One row per service: its state in plain words and when it last refreshed. Values of credentials are never part of it."""
    services = load_services() if services is None else services
    cfg = common.load_config() if cfg is None else cfg
    have = env_keys() if have is None else have
    recorded = common.read_status() if recorded is None else recorded
    kind = common.store_kind()
    rows = []
    for s in services:
        on = bool((cfg["sources"].get(s["id"]) or {}).get("enabled")) or s["local"]
        missing = [c["key"] for c in s["credentials"] if c["key"] not in have and not c["optional"]]
        recs = [recorded[n] for n in s["snapshots"] if isinstance(recorded.get(n), dict)]
        last = max(recs, key=lambda r: r.get("at", ""), default=None)
        bad = next((r for r in recs if not r.get("ok")), None)
        if s["local"]:
            for n in s["snapshots"]:                           # a helper app writes the snapshot itself; its own stamp is the last refresh
                try:
                    stamp = json.loads((common.STATE / "connectors" / f"{n}.json").read_text()).get("updated")
                except (OSError, ValueError, AttributeError):
                    stamp = None
                if isinstance(stamp, str) and (not last or stamp > last.get("at", "")):
                    last = {"ok": True, "at": common.clip(stamp, 40)}
            state = "failing" if bad else "ok" if last else "ready"
        elif not on:
            state = "off"
        elif missing:
            state = "needs set-up"
        elif bad:
            state = "failing"
        else:
            state = "ok" if last else "ready"
        rows.append({**{k: s[k] for k in ("id", "label", "what", "minutes", "local", "settings", "reads", "not_reads", "scopes", "revoke", "tested", "links")},
                     "steps": [x.replace("{data_folder}", str(common.HOME)) for x in s["steps"]],          # the exact folder, not "your data folder"
                     "verified": s["tested"].startswith(VERIFIED),
                     "credentials": [{**c, "present": c["key"] in have, "stored": kind if c["key"] in have else None} for c in s["credentials"]],
                     "enabled": bool((cfg["sources"].get(s["id"]) or {}).get("enabled")), "state": state, "missing": missing,
                     "last_at": (last or {}).get("at"), "error": (bad or {}).get("error_short") or ""})
    return rows


# ---- changing things: a credential goes in and is never read back out; a feed is switched on or off ---------------------------

def known_keys(services=None):
    return {c["key"] for s in (load_services() if services is None else services) for c in s["credentials"]}


_LOCK = threading.RLock()
_HELD = threading.local()


@contextlib.contextmanager
def _store_lock():
    """One writer at a time (round 8, L9: the dashboard is threaded, and four saves arriving together lost one): a thread lock for this process and
    an flock on a file in the config folder for every process, taken once per thread (move_store writes through _write while it holds it)."""
    with _LOCK:
        if getattr(_HELD, "n", 0):
            _HELD.n += 1
            try:
                yield
            finally:
                _HELD.n -= 1
            return
        common.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(common.CONFIG_DIR / ".credentials.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            _HELD.n = 1
            try:
                yield
            finally:
                _HELD.n = 0


def set_credential(key, value, services=None):
    """Store one credential in the private file (owner only), replacing any earlier value for that key. An empty value removes it.
    Only keys a manifest names are accepted. Returns whether the key is now present. Never returns or logs the value."""
    if key not in known_keys(services):
        raise ValueError("that is not a credential any service asks for")
    value = str(value or "").strip()
    if "\n" in value or "\r" in value or len(value) > 4000:
        raise ValueError("a credential is one line of at most 4000 characters")
    if value and common.store_kind() == "keychain" and not keychain.fits(key, value):
        raise ValueError(f"the keychain takes at most about {keychain.MAX_CHARS:,} characters per credential. Move credentials back to the file to keep a longer one")
    with _store_lock():
        _write(common.store_kind(), key, value)
    return bool(value)


def store_info():
    """Where credentials are kept and whether the keychain could be chosen. Facts only."""
    return {"kind": common.store_kind(), "keychain_available": keychain.available()}


def _write(kind, key, value):
    """One credential into one named store; an empty value removes it."""
    if kind == "keychain":
        keychain.put(key, value) if value else keychain.delete(key)
        return
    p = common.env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.parent.chmod(0o700)
    lines = p.read_text().splitlines() if p.is_file() else []
    keep = [l for l in lines if l.split("=", 1)[0].strip() != key]
    if value:
        keep.append(f"{key}={common.quote(value)}")      # round 8 (M6): read back exactly, a quote at either end included
    common.write_private(p, "\n".join(keep) + ("\n" if keep else ""))


def move_store(to, services=None):
    with _store_lock():
        return _move_store(to, services)


def _move_store(to, services=None):
    """Move every credential a service asks for to the other store, then make it the active one. The caller has the owner's confirm.
    Copies first (the keychain reads each back); the old copies go only after the new store holds them all; a failure leaves the old store as it was."""
    if to not in ("file", "keychain"):
        raise ValueError("the store is the file or the keychain")
    frm = common.store_kind()
    if to == frm:
        raise ValueError("credentials are already kept there")
    if to == "keychain" and not keychain.available():
        raise ValueError("the macOS Keychain is not available on this computer")
    keys = known_keys(services) | set(common.EXTRA_KEYS)
    try:
        if frm == "keychain":
            src = {k: v for k in sorted(keys) for v in [keychain.get(k)] if v}
        else:
            src = {k: v for k, v in (common.read_env_file() if common.env_path().is_file() else {}).items() if k in keys and v}
    except common.IntegrationError as e:
        raise ValueError(e.short)
    if to == "keychain" and not all(keychain.fits(k, v) for k, v in src.items()):
        raise ValueError(f"a credential is longer than the keychain takes (about {keychain.MAX_CHARS:,} characters), so nothing was moved")
    done = []
    try:
        for k, v in src.items():
            done.append(k)                      # before the write: a write that fails half way must be undone too
            _write(to, k, v)
        if to == "file":                        # round 8 (M6): read every value back before the keychain copies go, as keychain.put does
            back = common.read_env_file()
            if any(back.get(k) != v for k, v in src.items()):
                raise ValueError("a credential did not read back from the file exactly, so nothing was moved")
    except Exception:
        for k in done:
            try:
                _write(to, k, "")
            except Exception:
                pass
        raise
    p = common.HOME / "config" / "integrations.json"
    try:
        cur = json.loads(p.read_text())
        cur = cur if isinstance(cur, dict) else {}
    except (OSError, ValueError):
        cur = {}
    cur["credential_store"] = to
    p.parent.mkdir(parents=True, exist_ok=True)
    common.write_private(p, json.dumps(cur, indent=2) + "\n")
    for k in src:
        _write(frm, k, "")
    return len(src)


def set_enabled(service_id, on, services=None):
    """Switch a service's feed on or off in config/integrations.json, keeping everything else in that file."""
    if service_id not in {s["id"] for s in (load_services() if services is None else services)}:
        raise ValueError("no such service")
    p = common.HOME / "config" / "integrations.json"
    try:
        cur = json.loads(p.read_text())
        cur = cur if isinstance(cur, dict) else {}
    except (OSError, ValueError):
        cur = {}
    srcs = cur.setdefault("sources", {})
    srcs.setdefault(service_id, {"minutes": 60})["enabled"] = bool(on)
    p.parent.mkdir(parents=True, exist_ok=True)
    common.write_private(p, json.dumps(cur, indent=2) + "\n")
    return bool(on)
