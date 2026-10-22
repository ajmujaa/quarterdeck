#!/usr/bin/env python3
"""Level 1 of "show your own agents": any script, job or agent reports itself to the Fleet view with one line.

    qtdeck fleet source add <id> <label>        the owner registers a reporting source (once)
    qtdeck fleet report --source <id> --kind <kind> --session <id> [--worktree <name>] [--branch <name>] [--agent <name>]

A report appends ONE line to state/fleet-events/<source>.jsonl, the file the sessions hook (bin/fleet-hook.sh) also writes:
    {"t": 1760000000.5, "event": "session_start", "session": "run-42", "worktree": "nightly", "branch": "main", "agent": ""}
Every field is checked against a short pattern (no control characters, length caps). A prompt, a reply, a file name or a transcript has no field
here and is refused as an unknown option. An id that was not registered with `fleet source add` is refused, so a stray script cannot invent a
source. The line is written with one append of under 4 KB (atomic), the file is mode 0600, and past two megabytes only the newest three thousand
events are kept, as the hook does. Nothing is read from the machine: the caller says what happened.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}")
KINDS = ("session_start", "session_end", "prompt", "stop", "agent_start", "agent_stop")
FIELDS = {"session": (re.compile(r"[A-Za-z0-9_-]{1,80}"), "letters, digits, - or _, up to 80"),
          "worktree": (re.compile(r"[A-Za-z0-9._-]{1,60}"), "letters, digits, . - or _, up to 60"),
          "branch": (re.compile(r"[A-Za-z0-9._/@+-]{1,80}"), "letters, digits and . _ / @ + -, up to 80"),
          "agent": (re.compile(r"[A-Za-z0-9._-]{1,40}"), "letters, digits, . - or _, up to 40")}
LABEL_MAX = 80


def _paths(home=None):
    h = Path(home) if home else _home.resolve()
    return h / "config" / "fleet.local.json", h / "state" / "fleet-events"


def _sources(config):
    try:
        raw = json.loads(Path(config).read_text())
    except OSError:
        return {"sources": []}
    except ValueError:
        raise ValueError("config/fleet.local.json is not valid JSON, not touching it")
    if not isinstance(raw, dict) or not isinstance(raw.get("sources", []), list):
        raise ValueError("config/fleet.local.json has an unexpected shape, not touching it")
    raw.setdefault("sources", [])
    return raw


def source_add(sid, label, home=None):
    """Register a reporting source. Returns the message; raises ValueError with the reason."""
    config, _ = _paths(home)
    if not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid):
        raise ValueError("a source id is lower case letters, digits, - or _, up to 31, starting with a letter or digit")
    if not isinstance(label, str) or not label.strip() or len(label) > LABEL_MAX or any(ord(c) < 32 or ord(c) == 127 for c in label):
        raise ValueError(f"a label is a short name of up to {LABEL_MAX} characters, with no control characters")
    doc = _sources(config)
    if any(isinstance(s, dict) and s.get("id") == sid for s in doc["sources"]):
        raise ValueError(f"{sid} is already a source")
    doc["sources"].append({"id": sid, "kind": "reported", "title": label.strip()})
    config.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(config.parent), prefix=".fleet.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, config)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return f"registered {sid}: report to it with `qtdeck fleet report --source {sid} --kind session_start --session <id>`"


def build_event(kind, session, worktree="", branch="", agent="", now=None):
    """The one event dict, or ValueError. Nothing but these six keys can ever be written."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    vals = {"session": session, "worktree": worktree or "", "branch": branch or "", "agent": agent or ""}
    for k, (pat, hint) in FIELDS.items():
        v = vals[k]
        if v == "" and k != "session":
            continue
        if not isinstance(v, str) or not pat.fullmatch(v):
            raise ValueError(f"{k} must be {hint}" + (" (it is required)" if k == "session" else ""))
    if kind.startswith("agent_") and not vals["agent"]:
        raise ValueError(f"{kind} needs --agent")
    if vals["agent"] and not kind.startswith("agent_"):
        raise ValueError("--agent goes with agent_start and agent_stop only")
    return {"t": round(now if now is not None else time.time(), 3), "event": kind, "session": vals["session"], "worktree": vals["worktree"],
            "branch": vals["branch"], "agent": vals["agent"]}


def report(source, kind, session, worktree="", branch="", agent="", home=None, now=None):
    """Append one event for a registered source. Raises ValueError with the reason."""
    config, events = _paths(home)
    if not isinstance(source, str) or not SOURCE_ID.fullmatch(source):
        raise ValueError("a source id is lower case letters, digits, - or _")
    ev = build_event(kind, session, worktree, branch, agent, now)
    if not any(isinstance(s, dict) and s.get("id") == source for s in _sources(config)["sources"]):
        raise ValueError(f"{source} is not a registered source: the owner adds it first with `qtdeck fleet source add {source} <label>`")
    events.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(events, 0o700)
    except OSError:
        pass
    path = events / f"{source}.jsonl"
    line = (json.dumps(ev, separators=(",", ":")) + "\n").encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, line)             # one write on an O_APPEND descriptor: lines from two reporters never interleave
        os.fchmod(fd, 0o600)
        size = os.fstat(fd).st_size
    finally:
        os.close(fd)
    if size > 2_000_000:
        try:
            keep = path.read_bytes().splitlines(True)[-3000:]
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(b"".join(keep))
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except OSError:
            pass
    return ev


def main(argv=None):
    ap = argparse.ArgumentParser(prog="qtdeck fleet", description="Show your own agents in the Fleet view.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="append one event line for a registered source")
    r.add_argument("--source", required=True)
    r.add_argument("--kind", required=True)
    r.add_argument("--session", required=True)
    r.add_argument("--worktree", default="")
    r.add_argument("--branch", default="")
    r.add_argument("--agent", default="")
    s = sub.add_parser("source", help="register a source")
    s.add_argument("action", choices=["add"])
    s.add_argument("id")
    s.add_argument("label")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "report":
            report(a.source, a.kind, a.session, a.worktree, a.branch, a.agent)
        else:
            print(source_add(a.id, a.label))
    except (ValueError, OSError) as e:
        from integrations import common as _common
        print("qtdeck fleet: " + (_common.why_not_saved(e) if isinstance(e, OSError) else str(e)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
