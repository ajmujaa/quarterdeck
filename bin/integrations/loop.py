"""One background loop: run each enabled source on its own interval, each in its own process."""
import os
import subprocess
import sys
import time
from pathlib import Path

from integrations import common

RUN = Path(__file__).resolve().parent / "run.py"
MIN_MINUTES = 5


def minimal_env():
    return {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(Path.home()), "LANG": "en_US.UTF-8"}


def due_sources(cfg, last_run, now):
    out = []
    for name, s in cfg["sources"].items():
        if not s.get("enabled"):
            continue
        try:
            every = max(MIN_MINUTES, float(s.get("minutes", 60))) * 60
        except (TypeError, ValueError):
            every = 3600
        if now - last_run.get(name, 0) >= every:
            out.append(name)
    return out


def run_subprocess(name):
    try:
        subprocess.run([sys.executable, str(RUN), name], env=minimal_env(), capture_output=True, timeout=180)
    except Exception:
        for snap in common.snapshots_of(name):
            common.record_status(snap, False, "the refresh did not finish", 0)


def run_due(cfg, last_run, now, runner=run_subprocess):
    for name in due_sources(cfg, last_run, now):
        last_run[name] = now
        runner(name)


SKIP = lambda: False            # dashboard.py points this at demo_on: demo mode never calls a real service


def tick(last, cfg=None, runner=run_subprocess, now=None):
    """One pass: nothing at all while demo mode is on, otherwise run what is due."""
    if SKIP():
        return
    run_due(cfg or common.load_config(), last, now or time.time(), runner=runner)


def integration_loop():
    last = {}
    while True:
        try:
            tick(last)
        except Exception:
            pass
        time.sleep(30)
