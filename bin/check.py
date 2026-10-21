#!/usr/bin/env python3
"""qtdeck check: one command that says whether everything is fine.

Runs every selftest (bin/selftest.py and every bin/selftest*.sh, the list `qtdeck doctor` used to run), the privacy, secrets and vendor
checks, the node assistant test, the smoke test and the rehearsal, then asks the live
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


# what each suite checks, for the summary line; a suite missing here is shown by its file name
LABELS = {
    "selftest.py": "logic", "selftest.sh": "commit gate", "selftest-fix.sh": "fix pipeline", "selftest-panel.sh": "panel prompts",
    "selftest-harbourmaster.sh": "board notes stay local", "selftest-portable.sh": "scripts run on macOS bash 3.2 and BSD tools",
    "selftest-purser.sh": "requirements reach the issue body only", "selftest-planner.sh": "the planner: validated plans, no card moves before approval",
    "selftest-packs.sh": "stack notes from listed packs only", "selftest-untrusted.sh": "third-party text reaches prompts only as data",
    "selftest-guardrails.sh": "guardrails are editable, three stay locked, and the crew receives exactly the list shown",
    "selftest-pilot.sh": "the pilot: the harness drives the browser", "selftest-lookout.sh": "the lookout: only pictures the harness took",
    "selftest-marshal.sh": "the marshal: forbidden paths block before any model", "selftest-caulker.sh": "the caulker: only what was found, three cycles",
    "selftest-assayer.sh": "the assayer: tests that fail first", "selftest-logkeeper.sh": "the logkeeper: records",
    "selftest-quartermaster.sh": "the quartermaster: facts by the harness", "selftest-bosun.sh": "the bosun: nothing is written to a repo",
    "selftest-infra.sh": "the infra duty: files only, no cloud tool", "selftest-brief.sh": "the brief: plain words, no code",
    "selftest-mockup.sh": "the mock-ups: only an approved brief, allowlisted pages", "selftest-checks.sh": "project commands: sandbox, protected paths",
    "selftest-terraform.sh": "Terraform: fmt and validate only", "selftest-injection.sh": "prompt injection: hostile text stays data",
    "selftest-providers.sh": "providers: the claude adapter, unknown ones refused", "selftest-security.sh": "security: one check per fix",
    "selftest-cycle.sh": "the cycle: stage order, caps, resume", "selftest-diet.sh": "fewer tokens: turn caps, reuse, rounds",
    "selftest-round8.sh": "round 8 review: expected failures until fixed", "selftest-billing.sh": "billing: the API key only where it is chosen",
    "selftest-firstrun.sh": "first use: data folder, help, doctor, attach, setup",
    "selftest-connections.sh": "connections: instructions, several accounts per service",
    "selftest-stack.sh": "the stack scan: framework and tools named, build and lint proposed, a reason per duty",
    "selftest-tickets.sh": "tickets: drafted from a request, filed only with --apply, local tickets and branches when there is no repo, repo create after a yes",
    "selftest-missions.sh": "missions that tell the truth: a merged pull request is Merged, NO_CHANGE is Nothing to build, the buttons on a finished or stopped mission do only what they say, old stops are grouped",
    "selftest-tickets-ui.sh": "tickets on the dashboard: draft first, file on a click, the repo options, a mission from a ticket, Demo mode does nothing",
    "selftest-nav.sh": "navigation: the address holds the page, project and mission (Back, Forward, reload, deep links, hostile addresses), the scope chip where a scope applies, mission steps by kind, the trajectory on Projects, add-ons in the scope box",
    "selftest-live.sh": "live work: Running now on Home, a project's Live work, sessions told from duties, no detail reported never invented, Enable on the Crew page with Available (N) folded, Demo shows invented Relay data",
    "selftest-projects.sh": "Home and Projects: Home is the person (five things and one count line), Projects shows a card per project and Open filters the tabs, the scope is in the address, the scope box exists only where it applies, Calm, a phone width",
    "selftest-onboarding.sh": "a smoother first run: the Homebrew formula and npm shim (offline), the first-run checklist and its API, the narrow Copy allowance in the privacy scan, the first-run panel and the guided attach panel in a browser",
    "selftest-prove-live.sh": "Prove shows its output while it runs (a polled small JSON, text only, redacted), keeps the last 60 lines and the line that failed, says what to do next, and Stop keeps nothing",
    "selftest-flow.sh": "the whole flow without a model: attach a sample React app (survey, missing docs by the scribe, the ready checklist), tickets, a cycle to a local branch on the CLI and the dashboard",
}


def suites(root=ROOT):
    """Every selftest `qtdeck check` runs: bin/selftest.py, then every bin/selftest*.sh but the shared library, found by name so a new one is never left out."""
    return ["selftest.py"] + sorted(p.name for p in (Path(root) / "bin").glob("selftest*.sh") if p.name != "selftest-lib.sh")


def step(label, argv, timeout=600):
    """(ok, summary, failing lines) for one command. The tests build their own throwaway folders: they must not inherit this installation's data
    folder, which would take precedence."""
    env = {k: v for k, v in os.environ.items() if k not in ("QUARTERDECK_HOME", "QUARTERDECK_HOME_WHY")}
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT), env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "did not run", [f"{label}: {type(e).__name__}"]
    lines = (r.stdout + "\n" + r.stderr).splitlines()
    oks = sum(1 for ln in lines if ln.lstrip().startswith("ok"))
    skips = sum(1 for ln in lines if ln.lstrip().startswith("skip"))
    xf = sum(1 for ln in lines if ln.startswith("  xfail"))
    bad = [ln.strip() for ln in lines if BAD.match(ln) and not ln.lstrip().startswith("ok")]      # a passing line that says "failed" is not the failure
    if r.returncode != 0 and not bad:
        bad = [next((ln.strip() for ln in reversed(lines) if ln.strip()), f"exit code {r.returncode}")]
    return r.returncode == 0, f"{oks} ok" + (f", {skips} skipped" if skips else "") + (f", {xf} expected failure(s) still open" if xf else ""), bad


def health():
    port = os.environ.get("QUARTERDECK_DASHBOARD_PORT", "7878")
    if not port.isdigit():
        return None, "QUARTERDECK_DASHBOARD_PORT is not a number", ""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4) as r:
            h = json.loads(r.read().decode())
    except Exception:
        return None, f"not running on 127.0.0.1:{port} (start it with: qtdeck dashboard)", ""
    if not isinstance(h, dict):
        return False, "answered, but not with a health object", "/api/health"
    if h.get("ok") is True:
        return True, f"ok, up {h.get('uptime_seconds', '?')}s, commit {h.get('commit', '?')}", ""
    quiet = [k for k, v in (h.get("loops") or {}).items() if isinstance(v, dict) and v.get("alive") is False]
    return False, "reports not ok", ("quiet loops: " + ", ".join(quiet)) if quiet else "state or logs not writable, see /api/health"


def main():
    steps = [(LABELS.get(f, f), [sys.executable if f.endswith(".py") else "bash", "bin/" + f]) for f in suites()]
    steps += [("privacy limit", [sys.executable, "bin/forbidden_signals.py"]), ("secrets", [sys.executable, "bin/guard.py"]), ("vendor files", [sys.executable, "bin/vendor-verify.py"]), ("smoke test", [sys.executable, "bin/smoke.py"]),
             ("rehearsal", [sys.executable, "bin/rehearse.py"])]
    if nodeok.path():
        steps.insert(1, ("assistant test", ["node", "--no-warnings", "bin/selftest-assistant.mjs"]))
    print("── Quarterdeck check ──\n")
    failed = []
    for label, argv in steps:
        ok, summary, bad = step(label, argv)
        print(f"  {paint('32', '✓') if ok else paint('31', '✗')} {label:<16} {summary}", flush=True)
        if not ok:
            print("".join(f"      {ln}\n" for ln in bad[:40]), end="", flush=True)
            failed.append((label, bad[0]))
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
