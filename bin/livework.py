#!/usr/bin/env python3
"""Live work: what is running right now, across every project, composed from facts only.

Two kinds of thing run. A session is a live agent process the owner has open in a registered repository (the fleet hook writes
one line per event into state/fleet-events/<source>.jsonl, see bin/fleet-hook.sh). A duty is a Quarterdeck run (a live lock).
live_work() puts both in one list, with the worktrees git knows for each project and the pull request each one carries.

Rules this module keeps:
  * nothing is invented: a field the hook did not report says "no detail reported" (the hook never reads a prompt, a reply or a
    file name, so it can only say a turn started, a turn finished, an agent started or stopped, a session ended);
  * everything that comes from an event file is untrusted text: it is clipped here, escaped by the page and never run;
  * a session that cannot be tied to a registered project is grouped under "Other" (project is the empty string) and says so.

Item shape: {kind: "session"|"duty", project, source, branch, worktree, agent, doing, since, minutes, waiting_on_owner, state, pr}
  state: working | idle | finished.  waiting_on_owner: a session whose turn finished and that is still open (the next move is the owner's).
  pr: {number, draft, url} for an open pull request on the session's branch, else None.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

NO_DETAIL = "no detail reported"
HOOK_NAME = "fleet-hook.sh"
MAX_ITEMS, MAX_TREES = 60, 30
REPO = re.compile(r"^[\w.-]{1,60}/[\w.-]{1,100}$")


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "..."


def settings_path():
    return Path(os.environ.get("CLAUDE_SETTINGS_FILE") or Path(os.path.expanduser("~")) / ".claude" / "settings.json")


def hook_installed(settings=None):
    """True when the settings file lists the Quarterdeck hook script as a command. Reads one file; never throws."""
    try:
        doc = json.loads(Path(settings or settings_path()).read_text())
        for entries in (doc.get("hooks") or {}).values():
            for entry in entries if isinstance(entries, list) else []:
                for h in entry.get("hooks") or [] if isinstance(entry, dict) else []:
                    if isinstance(h, dict) and str(h.get("command") or "").endswith(HOOK_NAME):
                        return True
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return False


def collect(cfg, cached=None, events_dir=None, now=None):
    """The sources live_work reads: for each repo-agents source of the config, its sessions built from the event file right now (cheap, so
    sessions are up to the minute) and its worktrees from the cached fleet document when there is one (git and gh calls, a few seconds old)."""
    import fleetview as fv
    now = now or time.time()
    have = {s.get("id"): s for s in (cached or {}).get("sources", []) if isinstance(s, dict)}
    out = []
    for s in cfg.get("sources", []):
        if s.get("kind") != "repo-agents":
            continue
        ev = fv.read_events(s["id"], events_dir)
        out.append({"id": s["id"], "title": s.get("title") or s["id"], "project": s.get("project") or "",
                    "last_event": max((e["t"] for e in ev), default=None) if ev else None,
                    "sessions": fv.build_sessions(ev, now) if ev is not None else None,
                    "worktrees": (have.get(s["id"]) or {}).get("worktrees") or []})
    return out


def _pr(row, repo):
    """The pull request of a worktree as the page shows it, or None."""
    if not isinstance(row, dict) or not isinstance(row.get("number"), int):
        return None
    url = f"https://github.com/{repo}/pull/{row['number']}" if REPO.match(repo or "") else ""
    return {"number": row["number"], "draft": bool(row.get("draft")), "url": url, "state": str(row.get("state") or "open")[:12], "title": _clip(row.get("title"), 90)}


def _session_item(x, project, source, wt, repo, now):
    st = x["state"]
    state = "working" if st == "working" else "finished" if st == "ended" else "idle"
    agents = list(x.get("running_agents") or [])
    waiting = st == "idle" and x.get("turns", 0) > 0
    if agents:
        agent, doing = ", ".join(agents)[:80], "Running the " + " and ".join(agents)[:80] + (" agent" if len(agents) == 1 else " agents")
    elif st == "working":
        agent, doing = NO_DETAIL, "Answering a prompt"
    elif st == "idle" and x.get("turns", 0) > 0:
        agent, doing = NO_DETAIL, "Finished its turn"
    elif st == "quiet":
        agent, doing = NO_DETAIL, "Nothing reported for %d minutes" % (x["last_ago"] // 60)
    elif st == "ended":
        agent, doing = NO_DETAIL, "The session ended"
    else:
        agent, doing = NO_DETAIL, NO_DETAIL
    ago = x.get("state_ago", x["last_ago"]) if st != "quiet" else x["last_ago"]
    pr = _pr((wt or {}).get("pr"), repo)
    return {"kind": "session", "project": project, "source": source, "branch": (x.get("branch") or "")[:80], "worktree": (x.get("worktree") or "")[:60],
            "agent": agent, "doing": doing, "since": _iso(now - ago), "minutes": max(0, int(ago // 60)), "waiting_on_owner": waiting, "state": state,
            "pr": {k: pr[k] for k in ("number", "draft", "url")} if pr and pr["state"] == "open" else None}


def _duty_item(a, now):
    try:
        t = datetime.fromisoformat(str(a.get("since")).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        t = None
    what = _clip(a.get("what"), 140)
    return {"kind": "duty", "project": a.get("project") or "", "source": "", "branch": "", "worktree": "", "agent": _clip(a.get("duty"), 40) or NO_DETAIL,
            "doing": what or NO_DETAIL, "since": _iso(t) if t else None, "minutes": max(0, int((now - t) // 60)) if t else 0, "waiting_on_owner": False,
            "state": "working", "pr": None}


def live_work(sources, duties, projects, now=None, installed=None, install_command="", settings=None):
    """The whole picture. sources: collect() rows. duties: running agent rows ({project, duty, what, since}). projects: {name: {repo}}.
    Returns {items, worktrees, updated_at, hook_installed, install_command, sources}."""
    now = now or time.time()
    items, trees, seen = [], [], []
    for s in sources or []:
        project = s["project"] if s.get("project") in projects else s["id"] if s.get("id") in projects else ""
        repo = (projects.get(project) or {}).get("repo", "") if project else ""
        seen.append({"id": s["id"], "title": str(s.get("title") or s["id"])[:80], "project": project, "sessions": None if s.get("sessions") is None else len(s["sessions"])})
        by = {w.get("name"): w for w in s.get("worktrees") or []}
        live = {}
        for x in s.get("sessions") or []:
            if x["state"] in ("working", "idle", "quiet", "ended"):
                items.append(_session_item(x, project, s["id"], by.get(x.get("worktree")), repo, now))
                if x["state"] in ("working", "idle") and x.get("worktree") not in live:
                    live[x.get("worktree")] = {"id": x["id"], "state": x["state"]}
        for w in (s.get("worktrees") or [])[:MAX_TREES]:
            pr = _pr(w.get("pr"), repo)
            last = [v for v in (w.get("last_commit_ago"), w.get("touched_ago")) if isinstance(v, (int, float))]
            trees.append({"project": project, "name": str(w.get("name") or "")[:60], "branch": str(w.get("branch") or "")[:80], "main": bool(w.get("main")),
                          "stage": str(w.get("stage") or "")[:20], "activity": str(w.get("activity") or "")[:10], "changed": int(w.get("changed") or 0),
                          "last_activity_ago": int(min(last)) if last else None, "pr": pr, "session": live.get(w.get("name"))})
    for a in duties or []:
        if a.get("status") == "running":
            items.append(_duty_item(a, now))
    rank = {"working": 0, "idle": 1, "finished": 3}
    items.sort(key=lambda i: (rank[i["state"]] + (0 if i["waiting_on_owner"] or i["state"] != "idle" else 1), i["minutes"]))
    newest = max((s["last_event"] for s in sources or [] if s.get("last_event")), default=None)
    return {"items": items[:MAX_ITEMS], "worktrees": trees, "updated_at": _iso(newest) if newest else None,
            "hook_installed": hook_installed(settings) if installed is None else bool(installed),
            "install_command": install_command, "sources": seen}
