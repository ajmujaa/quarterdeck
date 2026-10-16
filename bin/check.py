#!/usr/bin/env python3
"""quarterdeck check: one command that says whether everything is fine.

Runs the selftest, the node assistant test, the smoke test and the rehearsal, then asks the live
dashboard (127.0.0.1, QUARTERDECK_DASHBOARD_PORT or 7878) for /api/health. Prints a green or red summary
and, if red, the first failing line. A dashboard that is not running is reported, not treated as a
failure of the code. Stdlib only. Exit 0 only if every step passed and the dashboard, if running, is ok."""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

import nodeok
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAD = re.compile(r"^\s*(FAIL\b|AssertionError|Traceback|Error\b|.*\bfailed\b)")


def paint(code, s):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def step(label, argv, timeout=600):
    """(ok, summary, first failing line) for one command."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "did not run", f"{label}: {type(e).__name__}"
    lines = (r.stdout + "\n" + r.stderr).splitlines()
    oks = sum(1 for ln in lines if ln.lstrip().startswith("ok"))
    first = next((ln.strip() for ln in lines if BAD.match(ln) and not ln.lstrip().startswith("ok")), "")      # a passing line that says "failed" is not the failure
    if r.returncode != 0 and not first:
        first = next((ln.strip() for ln in reversed(lines) if ln.strip()), f"exit code {r.returncode}")
    return r.returncode == 0, f"{oks} ok", first


def health():
    port = os.environ.get("QUARTERDECK_DASHBOARD_PORT", "7878")
    if not port.isdigit():
        return None, "QUARTERDECK_DASHBOARD_PORT is not a number", ""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4) as r:
            h = json.loads(r.read().decode())
    except Exception:
        return None, f"not running on 127.0.0.1:{port} (start it with: quarterdeck dashboard)", ""
    if not isinstance(h, dict):
        return False, "answered, but not with a health object", "/api/health"
    if h.get("ok") is True:
        return True, f"ok, up {h.get('uptime_seconds', '?')}s, commit {h.get('commit', '?')}", ""
    quiet = [k for k, v in (h.get("loops") or {}).items() if isinstance(v, dict) and v.get("alive") is False]
    return False, "reports not ok", ("quiet loops: " + ", ".join(quiet)) if quiet else "state or logs not writable, see /api/health"


def main():
    steps = [("selftest", [sys.executable, "bin/selftest.py"]), ("privacy limit", [sys.executable, "bin/forbidden_signals.py"]), ("secrets", [sys.executable, "bin/guard.py"]), ("smoke test", [sys.executable, "bin/smoke.py"]),
             ("rehearsal", [sys.executable, "bin/rehearse.py"])]
    if nodeok.path():
        steps.insert(1, ("assistant test", ["node", "--no-warnings", "bin/selftest-assistant.mjs"]))
    print("── Quarterdeck check ──\n")
    failed = []
    for label, argv in steps:
        ok, summary, first = step(label, argv)
        print(f"  {paint('32', '✓') if ok else paint('31', '✗')} {label:<16} {summary}")
        if not ok:
            failed.append((label, first))
    if not nodeok.path():
        print(f"  {paint('33', '–')} {'assistant test':<16} skipped, node 20 or newer is not installed")
    ok, text, first = health()
    mark = paint("33", "–") if ok is None else paint("32", "✓") if ok else paint("31", "✗")
    print(f"  {mark} {'dashboard':<16} {text}")
    if ok is False:
        failed.append(("dashboard", first))
    print()
    if failed:
        print(paint("31", "  RED: something is wrong"))
        print(f"  first failure, {failed[0][0]}: {failed[0][1]}")
        return 1
    print(paint("32", "  GREEN: everything checked is fine") + ("" if ok else "  (the dashboard is not running, so its health was not checked)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
