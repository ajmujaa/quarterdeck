#!/usr/bin/env python3
"""python3 bin/integrations/run.py <ga4|gmail|macmail|slack|linkedin|meta|threads|x|all>

Runs one source, writes its snapshot and its status record. Every exception is caught into the
status record as a short, secret-free sentence. `all` runs every enabled source, each on its own.
"""
import importlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations import common  # noqa: E402

from integrations import manifest  # noqa: E402
SOURCES = tuple(m["module"] for m in manifest.load_services() if m["module"])      # one manifest per service: adding a file adds a source


def run_source(name):
    """Returns (ok, short message). Never raises, never includes a secret."""
    t0, mod, written = time.time(), None, ()
    try:
        mod = importlib.import_module("integrations." + name)
        cfg = common.load_config()
        env = {} if name in ("linkedin", "macmail") else common.load_env()      # these two read no credential
        got = mod.fetch(env, cfg)
        for snap, payload in got.items():
            common.write_snapshot(snap, payload["items"], payload.get("unread"))
        ok, msg, written = True, "", tuple(got)
    except common.IntegrationError as e:
        ok, msg = False, e.short
    except Exception as e:                       # the type name only: a message could carry a value
        ok, msg = False, f"unexpected {type(e).__name__}: see the README"
    for snap in (written if ok else common.snapshots_of(name)):    # a feed that never ran is not "refreshed"
        common.record_status(snap, ok, msg, time.time() - t0)
    return ok, msg


def run_all():
    cfg = common.load_config()
    results = {}
    for name in SOURCES:
        if cfg["sources"].get(name, {}).get("enabled"):
            results[name] = run_source(name)
    return results


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "all":
        res = run_all()
        if not res:
            print("no sources are enabled in config/integrations.json")
    elif which in SOURCES:
        res = {which: run_source(which)}
    else:
        sys.exit("usage: run.py <" + "|".join(SOURCES) + "|all>")
    for n, (ok, msg) in res.items():
        print(f"{n}: {'ok' if ok else 'failed: ' + msg}")
    sys.exit(0 if all(ok for ok, _ in res.values()) else 1)
