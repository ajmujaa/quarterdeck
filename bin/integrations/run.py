#!/usr/bin/env python3
"""python3 bin/integrations/run.py <ga4|gmail|macmail|slack|linkedin|meta|threads|x|all> [--account <label>]

Runs one source (one account of it), writes its snapshot and its status record. Every exception is caught into the
status record as a short, secret-free sentence. `all` runs every enabled source, each on its own.
"""
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import accounts, common  # noqa: E402

from integrations import manifest  # noqa: E402
SOURCES = tuple(m["module"] for m in manifest.load_services() if m["module"])      # one manifest per service: adding a file adds a source


def service_id(name):
    """The service whose module is `name` (the snapshot folder is named after the service); the name itself when none says so."""
    return next((m["id"] for m in manifest.load_services() if m["module"] == name), name)


def run_source(name, label="default"):
    """Returns (ok, short message). Never raises, never includes a secret. `label` is the account; the default one also keeps the older flat snapshot."""
    t0, mod, written = time.time(), None, ()
    label = accounts.norm(label)
    try:
        mod = importlib.import_module("integrations." + name)
        cfg = {**common.load_config(), "account": label}        # a module that needs to know which account it is reads cfg.get("account", "default")
        env = {} if name in ("linkedin", "macmail") else common.load_env(label)      # these two read no credential
        got = mod.fetch(env, cfg)
        sid = service_id(name)
        for snap, payload in got.items():
            common.write_snapshot(snap, payload["items"], payload.get("unread"), service=sid, label=label)
        ok, msg, written = True, "", tuple(got)
    except common.IntegrationError as e:
        ok, msg = False, e.short
    except Exception as e:                       # the type name only: a message could carry a value
        ok, msg = False, f"unexpected {type(e).__name__}: see the README"
    for snap in (written if ok else common.snapshots_of(name)):    # a feed that never ran is not "refreshed"
        common.record_status(snap, ok, msg, time.time() - t0, label)
    return ok, msg


def run_all():
    """Every enabled account of every source: the default one by sources.<s>.enabled, another by its own flag. One failing never stops the rest."""
    cfg = common.load_config()
    results = {}
    for name in SOURCES:
        src = cfg["sources"].get(name, {})
        if src.get("enabled"):
            results[name] = run_source(name)
        for label in accounts.labels_of(src):
            if src["accounts"][label].get("enabled"):
                results[accounts.work_item(name, label)] = run_source(name, label)
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    label = "default"
    if "--account" in args:
        i = args.index("--account")
        try:
            label = accounts.norm(args[i + 1] if i + 1 < len(args) else None)
        except ValueError as e:
            sys.exit(str(e))
        if i + 1 >= len(args):
            sys.exit("--account needs a label")
        del args[i:i + 2]
    which = args[0] if args else ""
    if which == "all":
        res = run_all()
        if not res:
            print("no sources are enabled in config/integrations.json")
    elif which in SOURCES:
        res = {accounts.work_item(which, label): run_source(which, label)}
    else:
        sys.exit("usage: run.py <" + "|".join(SOURCES) + "|all> [--account <label>]")
    for n, (ok, msg) in res.items():
        print(f"{n}: {'ok' if ok else 'failed: ' + msg}")
    sys.exit(0 if all(ok for ok, _ in res.values()) else 1)
