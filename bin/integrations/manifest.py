"""Service manifests: what a connection is, what it needs, and where it stands. Plain data, no network, no secret values.

A service is one JSON file in bin/integrations/services/ (or in your data folder under config/services/, for a service of your own):
  id, label, what, snapshots[], minutes, local?, module?  (module is the python file in bin/integrations that fetches it)
  credentials[]: {key, label, secret, help}   the names it needs; the values are never read back out of the store
  steps[]: plain sentences, shown on the Connections page
  help, all optional and all plain text: reads[] and not_reads[] (what it reads and what it never reads), scopes[] (what to grant, read-only where the
  service allows), revoke (how to take access back), tested (what was and was not checked; the default says it was not tested against the real service),
  links[] ({label, url}, https only, a provider's own pages), and per credential looks (what the value looks like)
  accounts?  (a boolean, default true for a service that has credentials and is not local) whether several accounts of it can be connected, each with its own
  label, credentials and snapshots (bin/integrations/accounts.py); calendar, linkedin and macmail stay single
Adding a service is adding a file. status() says where each one stands: off, needs set-up, ready, ok or failing, and when it last refreshed.
"""
import contextlib
import fcntl
import json
import re
import threading
from pathlib import Path

from integrations import accounts, common, google_oauth, keychain

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
            "accounts": (raw["accounts"] if isinstance(raw.get("accounts"), bool) else True) and bool(creds) and raw.get("local") is not True,
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


def stored_name(key, label=accounts.DEFAULT):
    return accounts.cred_key(key, label)


def env_keys(label=accounts.DEFAULT):
    """The credential NAMES (the base names) present in the active store for one account, never the values."""
    label = accounts.norm(label)
    if common.store_kind() == "keychain":
        try:
            return {k for k in known_keys() if keychain.has(stored_name(k, label))}
        except keychain.KeychainError:
            return set()
    p = common.env_path()
    keys = set()
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                base, lab = accounts.split_key(k.strip())
                if lab == label and common.unquote(v.strip()):
                    keys.add(base)
    except OSError:
        pass
    return keys


def _state_of(s, on, missing, recs, local_last=None):
    """The state word of one account: off, needs set-up, ready, ok or failing."""
    last = max(recs, key=lambda r: r.get("at", ""), default=None)
    bad = next((r for r in recs if not r.get("ok")), None)
    if local_last and (not last or local_last > last.get("at", "")):
        last = {"ok": True, "at": common.clip(local_last, 40)}
    if s["local"]:
        state = "failing" if bad else "ok" if last else "ready"
    elif not on:
        state = "off"
    elif missing:
        state = "needs set-up"
    elif bad:
        state = "failing"
    else:
        state = "ok" if last else "ready"
    return state, last, bad


def status(services=None, cfg=None, have=None, recorded=None):
    """One row per service: its state in plain words and when it last refreshed. Values of credentials are never part of it.
    The top-level fields describe the default account; `accounts` lists every account (the default first) with the same facts, and `multi` says
    whether more can be added."""
    services = load_services() if services is None else services
    cfg = common.load_config() if cfg is None else cfg
    recorded = common.read_status() if recorded is None else recorded
    kind = common.store_kind()
    rows = []
    for s in services:
        src = cfg["sources"].get(s["id"]) or {}
        labels = [accounts.DEFAULT] + (accounts.labels_of(src) if s["accounts"] else [])
        entries = []
        for label in labels:
            if label == accounts.DEFAULT:
                have_l = env_keys() if have is None else have
                on = bool(src.get("enabled"))
            else:
                have_l = env_keys(label)
                on = bool((src.get("accounts") or {}).get(label, {}).get("enabled"))
            missing = [c["key"] for c in s["credentials"] if c["key"] not in have_l and not c["optional"]]
            recs = [recorded[k] for n in s["snapshots"] for k in [accounts.status_key(n, label)] if isinstance(recorded.get(k), dict)]
            stamp = None
            if s["local"]:                                     # a helper app writes the snapshot itself; its own stamp is the last refresh
                for n in s["snapshots"]:
                    d = common.read_snapshot(n, s["id"], label)
                    t = d.get("updated") if d else None
                    if isinstance(t, str) and (not stamp or t > stamp):
                        stamp = t
            state, last, bad = _state_of(s, on or s["local"], missing, recs, stamp)
            entry = {"label": label, "enabled": on, "state": state, "missing": missing, "last_at": (last or {}).get("at"),
                     "error": (bad or {}).get("error_short") or "",
                     "credentials": [{**c, "present": c["key"] in have_l, "stored": kind if c["key"] in have_l else None} for c in s["credentials"]]}
            if s["id"] in google_oauth.SCOPES:                     # the page offers "Sign in with Google" for these, and says whether it was done
                entry["signin"] = {"kind": "google", "signed_in": google_oauth.token_file(s["id"], label).is_file()}
            elif s["id"] == "meta":                                # Connect with Facebook: done when the Page token is saved
                entry["signin"] = {"kind": "facebook", "signed_in": "META_PAGE_TOKEN" in have_l}
            entries.append(entry)
        d = entries[0]
        rows.append({**{k: s[k] for k in ("id", "label", "what", "minutes", "local", "settings", "reads", "not_reads", "scopes", "revoke", "tested", "links")},
                     "steps": [x.replace("{data_folder}", str(common.HOME)) for x in s["steps"]],          # the exact folder, not "your data folder"
                     "verified": s["tested"].startswith(VERIFIED),
                     "credentials": d["credentials"], "enabled": d["enabled"], "state": d["state"], "missing": d["missing"], **({"signin": d["signin"]} if "signin" in d else {}),
                     "last_at": d["last_at"], "error": d["error"], "multi": s["accounts"], "accounts": entries})
    return rows


# ---- changing things: a credential goes in and is never read back out; a feed is switched on or off ---------------------------

def known_keys(services=None):
    return {c["key"] for s in (load_services() if services is None else services) for c in s["credentials"]} | {common.AGENT_SOURCE_KEY}


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


def set_credential(key, value, services=None, label=accounts.DEFAULT):
    """Store one credential in the private file (owner only), replacing any earlier value for that key. An empty value removes it.
    Only keys a manifest names are accepted. The credential belongs to one account: KEY for the default, KEY@label for another.
    Returns whether the key is now present. Never returns or logs the value."""
    label = accounts.norm(label)
    if key not in known_keys(services):
        raise ValueError("that is not a credential any service asks for")
    value = str(value or "").strip()
    if "\n" in value or "\r" in value or len(value) > 4000:
        raise ValueError("a credential is one line of at most 4000 characters")
    stored = stored_name(key, label)
    if value and common.store_kind() == "keychain" and not keychain.fits(stored, value):
        raise ValueError(f"the keychain takes at most about {keychain.MAX_CHARS:,} characters per credential. Move credentials back to the file to keep a longer one")
    with _store_lock():
        _write(common.store_kind(), stored, value)
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
    base = known_keys(services)
    labels = {accounts.DEFAULT} | {l for src_ in common.load_config()["sources"].values() for l in accounts.labels_of(src_)} | set(common.agent_source_ids())
    keys = {stored_name(k, l) for k in base for l in labels} | set(common.EXTRA_KEYS)
    try:
        if frm == "keychain":
            src = {k: v for k in sorted(keys) for v in [keychain.get(k)] if v}
        else:           # every account's entries, whether or not its label is still in the config
            src = {k: v for k, v in (common.read_env_file() if common.env_path().is_file() else {}).items()
                   if (k in keys or (accounts.split_key(k)[0] in base and accounts.split_key(k)[1])) and v}
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


def _config_path():
    return common.HOME / "config" / "integrations.json"


def _edit_config(fn):
    """Read config/integrations.json, let fn change it, write it back owner-only; everything else in the file is kept."""
    p = _config_path()
    with _store_lock():
        try:
            cur = json.loads(p.read_text())
            cur = cur if isinstance(cur, dict) else {}
        except (OSError, ValueError):
            cur = {}
        out = fn(cur)
        p.parent.mkdir(parents=True, exist_ok=True)
        common.write_private(p, json.dumps(cur, indent=2) + "\n")
    return out


def _service(service_id, services=None):
    s = next((x for x in (load_services() if services is None else services) if x["id"] == service_id), None)
    if not s:
        raise ValueError("no such service")
    return s


def set_enabled(service_id, on, services=None, label=accounts.DEFAULT):
    """Switch one account's feed on or off in config/integrations.json, keeping everything else in that file. The default account is
    sources.<service>.enabled; another account must exist first (add_account)."""
    label = accounts.norm(label)
    _service(service_id, services)

    def go(cur):
        srcs = cur.setdefault("sources", {})
        src = srcs.setdefault(service_id, {"minutes": 60})
        if label == accounts.DEFAULT:
            src["enabled"] = bool(on)
        else:
            acc = src.get("accounts")
            if not isinstance(acc, dict) or not isinstance(acc.get(label), dict):
                raise ValueError("no such account: add it first")
            acc[label]["enabled"] = bool(on)
    _edit_config(go)
    return bool(on)


def add_account(service_id, label, services=None):
    """Make another account of a service: off until switched on, with no credentials. Safe to repeat. The default account always exists."""
    label = accounts.norm(label)
    s = _service(service_id, services)
    if label == accounts.DEFAULT:
        raise ValueError("the default account always exists; give the new account a label such as work")
    if not s["accounts"]:
        raise ValueError(f"{s['label']} takes one account")

    def go(cur):
        srcs = cur.setdefault("sources", {})
        src = srcs.setdefault(service_id, {"enabled": False, "minutes": s["minutes"]})       # the default account stays off, on its own interval
        acc = src.setdefault("accounts", {})
        if not isinstance(acc, dict):
            acc = src["accounts"] = {}
        if not isinstance(acc.get(label), dict):
            acc[label] = {"enabled": False}
    _edit_config(go)
    return label


def remove_account(service_id, label, services=None):
    """Forget one account: its credentials in the active store, its Google sign-in file, its config entry, its snapshots and its status records.
    The default account keeps its card: its credentials, sign-in and snapshots go and it is switched off."""
    import shutil
    label = accounts.norm(label)
    s = _service(service_id, services)
    with _store_lock():
        for c in s["credentials"]:
            _write(common.store_kind(), stored_name(c["key"], label), "")
        from integrations import google_oauth                # lazy: it is a command-line tool too
        for n in {s["id"], s["module"] or s["id"]}:
            try:
                google_oauth.token_file(n, label).unlink()
            except OSError:
                pass

        def go(cur):
            src = (cur.get("sources") or {}).get(service_id)
            if not isinstance(src, dict):
                return
            if label == accounts.DEFAULT:
                src["enabled"] = False
            elif isinstance(src.get("accounts"), dict):
                src["accounts"].pop(label, None)
        _edit_config(go)
    folder = accounts.snapshot_dir(common.STATE, s["id"], label)
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder, ignore_errors=True)
    for n in s["snapshots"]:
        if label == accounts.DEFAULT:
            try:
                accounts.legacy_file(common.STATE, n).unlink()
            except OSError:
                pass
    common.forget_status([accounts.status_key(n, label) for n in s["snapshots"]])
    return True
