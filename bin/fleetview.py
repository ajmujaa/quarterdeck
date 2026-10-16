#!/usr/bin/env python3
"""Local fleets: a view, a start and a stop over agent folders that live outside Quarterdeck's own duties.

Two kinds of source, both described in config/fleet.local.json (gitignored, so nothing machine or employer specific is in
this repository):

  command-fleet   a folder with its own command line (`<cli> status`, `<cli> pause <job>`, `<cli> resume <job>`,
                  `<cli> test <job>`). Quarterdeck calls that command; it does not reimplement the scheduler.
  repo-agents     a repository that holds its own agents as markdown (agents/*.md), its own workflow commands
                  (commands/*.md) and, while agents work, worktrees. Read only.

Rules this module keeps, because it can start and stop things:
  * every path comes from the local config and must resolve inside that source's own folder;
  * a command is an argv list, never a shell string, and only ever one of: status, pause, resume, test;
  * the job and the action are looked up in the config, never taken as typed;
  * what it reads is names, descriptions, states and a few log lines, shown on this screen and nowhere else. It is not part
    of /api/state, so it is not in anything Helm tells a model.
Standing owner rule: it reads only the folders the owner registered, and never keystrokes, screens, apps, the clipboard or
location.
"""
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import home as _home
CONFIG = _home.resolve() / "config" / "fleet.local.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
SYNC_ACTIONS = ("pause", "resume")
ASYNC_ACTIONS = ("test",)
KINDS = ("command-fleet", "repo-agents")
LOG_LINES, LOG_WIDTH, MAX_AGENTS, MAX_TREES, MAX_HEAD_LOOKUPS = 3, 200, 60, 80, 25


def inside(root, rel):
    """rel (a relative path) resolved under root, or None if it is absolute, climbs out, or leaves root through a link."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    base = os.path.realpath(root)
    p = os.path.realpath(os.path.join(base, rel))
    return Path(p) if p == base or p.startswith(base + os.sep) else None


def _source(raw):
    """One validated source, or an error string. Never raises."""
    if not isinstance(raw, dict) or not SAFE_ID.match(str(raw.get("id", ""))):
        return None, "a source needs an id of lower case letters, digits, - or _"
    sid, kind = raw["id"], raw.get("kind")
    if kind not in KINDS:
        return None, f"{sid}: kind must be one of {', '.join(KINDS)}"
    root = Path(str(raw.get("path", ""))).expanduser()
    if not root.is_dir():
        return None, f"{sid}: its folder does not exist"
    project = str(raw.get("project") or "")
    if project and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,40}", project):
        return None, f"{sid}: project must be a registered project's name"
    out = {"id": sid, "kind": kind, "title": str(raw.get("title") or sid)[:80], "about": str(raw.get("about") or "")[:300], "root": root, "project": project,
           "implicit": bool(raw.get("implicit")), "crew": [str(c) for c in raw.get("crew") or []][:20]}
    if kind == "command-fleet":
        cli = inside(root, raw.get("cli", "bin/fleet"))
        if not cli or not cli.is_file():
            return None, f"{sid}: its command line is not a file inside its folder"
        jobs = []
        for j in raw.get("jobs") or []:
            if not isinstance(j, dict) or not SAFE_ID.match(str(j.get("id", ""))):
                return None, f"{sid}: every job needs an id of lower case letters, digits, - or _"
            arg = str(j.get("arg") or j["id"])
            if not SAFE_ID.match(arg):
                return None, f"{sid}: job {j['id']} has an arg that is not a plain word"
            log = inside(root, j["log"]) if j.get("log") else None
            if j.get("log") and not log:
                return None, f"{sid}: job {j['id']} has a log outside its folder"
            jobs.append({"id": j["id"], "name": str(j.get("name") or j["id"])[:40], "what": str(j.get("what") or "")[:200],
                         "status_key": str(j.get("status_key") or j["id"]), "arg": arg, "log": log})
        out.update(cli=cli, jobs=jobs)
    else:
        for k, d in (("agents", ".claude/agents"), ("commands", ".claude/commands"), ("worktrees", ".claude/worktrees")):
            out[k] = inside(root, raw.get(k, d))
            if out[k] is None:
                return None, f"{sid}: {k} must be a relative path inside its folder"
        repo, base = str(raw.get("repo") or ""), str(raw.get("base") or "")
        if repo and not re.fullmatch(r"[\w.-]{1,60}/[\w.-]{1,100}", repo):
            return None, f"{sid}: repo must look like owner/name"
        if base and not re.fullmatch(r"[\w./-]{1,60}", base):
            return None, f"{sid}: base must be a branch name such as origin/develop"
        out.update(repo=repo, base=base)
    return out, None


REGISTRY = _home.resolve() / "config" / "projects.json"


def implicit_sources(registry=None, taken=()):
    """A repo-agents source for every registered project that has a git checkout and no source of its own, so a project shows its agents and work
    with nothing to configure. `taken` holds the project names and ids already covered by a listed source."""
    try:
        reg = json.loads(Path(registry or REGISTRY).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for name, v in sorted(reg.items()) if isinstance(reg, dict) else []:
        if not isinstance(v, dict) or name in taken or not SAFE_ID.match(name):
            continue
        path = Path(str(v.get("path") or "")).expanduser()
        if not (path / ".git").exists():
            continue
        out.append({"id": name, "kind": "repo-agents", "title": name, "path": str(path), "project": name, "repo": v.get("repo") or "",
                    "about": str(v.get("summary") or ""), "implicit": True, "crew": v.get("duties") or []})
    return out


def load_config(path=None):
    """{"sources": [...], "errors": [...]}. A missing file is no sources; one bad source does not hide the others.
    With no path given, every registered project that has no listed source gets one of its own."""
    try:
        raw = json.loads(Path(path or CONFIG).read_text())
    except (OSError, ValueError):
        raw = {}
    if path is None:
        listed = raw.get("sources", []) if isinstance(raw, dict) else []
        taken = {str(r.get("id")) for r in listed if isinstance(r, dict)} | {str(r.get("project")) for r in listed if isinstance(r, dict) and r.get("project")}
        raw = {"sources": [r for r in listed if isinstance(r, dict)] + implicit_sources(taken=taken)} if isinstance(raw, dict) else {"sources": implicit_sources()}
    elif not raw:
        return {"sources": [], "errors": []}
    sources, errors, seen = [], [], set()
    for r in raw.get("sources", []) if isinstance(raw, dict) else []:
        s, err = _source(r)
        if err:
            errors.append(err)
        elif s["id"] in seen:
            errors.append(f"{s['id']}: listed twice")
        else:
            seen.add(s["id"]); sources.append(s)
    return {"sources": sources, "errors": errors}


# ---- repo-agents: names, descriptions, the workflow chains, what is in flight ----------------------------------------------------

def parse_frontmatter(text):
    """The few single-value keys at the top of an agent or command file. The body is never returned."""
    if not isinstance(text, str) or not text.startswith("---"):
        return {}
    block = text[3:].split("\n---", 1)[0]
    meta, key = {}, None
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            meta[key] = m.group(2).strip().strip("\"'")
            if meta[key] in (">", "|", ">-", "|-"):
                meta[key] = ""
        elif key and line.startswith((" ", "\t")) and not meta.get(key, "x") == "x":
            meta[key] = (meta[key] + " " + line.strip()).strip()
    return {k: v for k, v in meta.items() if k in ("name", "description", "model", "tools", "argument-hint")}


def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def chain_from_body(body, names):
    """The agents a command hands work to, in the order it first names them. A name counts only when it is written as a name
    (in backticks or quotes, after @, bold, or followed by the word agent), so ordinary words are not mistaken for agents."""
    found = []
    for n in names:
        m = re.search(rf"(?:[`\"'@]{re.escape(n)}\b)|(?:\*\*{re.escape(n)}\*\*)|(?:\b{re.escape(n)} (?:agent|subagent)\b)", body)
        if m:
            found.append((m.start(), n))
    return [n for _, n in sorted(found)]


def read_agents(directory):
    out = []
    try:
        files = sorted(Path(directory).glob("*.md"))[:MAX_AGENTS]
    except OSError:
        return out
    for f in files:
        try:
            meta = parse_frontmatter(f.read_text(errors="replace")[:6000])
        except OSError:
            continue
        out.append({"name": meta.get("name") or f.stem, "what": _short(meta.get("description"), 260), "model": meta.get("model", "")})
    return out


def read_commands(directory, agent_names):
    out = []
    try:
        files = sorted(Path(directory).glob("*.md"))[:MAX_AGENTS]
    except OSError:
        return out
    for f in files:
        try:
            text = f.read_text(errors="replace")[:30000]
        except OSError:
            continue
        meta = parse_frontmatter(text)
        body = text.split("\n---", 1)[1] if text.startswith("---") and "\n---" in text else text
        out.append({"name": f.stem, "what": _short(meta.get("description"), 200), "hint": _short(meta.get("argument-hint"), 80),
                    "chain": chain_from_body(body, agent_names)})
    return out


def _git(args, cwd, runner=subprocess.run):
    try:
        r = runner(["git", "-c", "core.fsmonitor=false", "-c", "gc.auto=0", "-C", str(cwd)] + args, capture_output=True, text=True, timeout=6)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def read_worktrees(directory, now=None, runner=subprocess.run):
    """What agents have in flight: each folder under the worktrees directory, its branch, its changes and when it last moved."""
    now = now or time.time()
    out = []
    try:
        dirs = sorted((d for d in Path(directory).iterdir() if d.is_dir()), key=lambda d: -d.stat().st_mtime)[:MAX_TREES]
    except OSError:
        return out
    for d in dirs:
        last = _git(["log", "-1", "--format=%ct"], d, runner)
        out.append({"name": d.name[:60], "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], d, runner)[:80],
                    "changed": len([l for l in _git(["status", "--porcelain"], d, runner).splitlines() if l.strip()]),
                    "last_commit_ago": int(now - int(last)) if last.isdigit() else None,
                    "touched_ago": int(now - d.stat().st_mtime)})
    return out


def read_all_worktrees(root, base="", now=None, runner=subprocess.run):
    """Every worktree git knows for this repository (the main checkout and every extra one, wherever it lives): its branch, the
    changes it holds, when it last moved and how far it is from its base. This is what "all the work in one place" means."""
    now = now or time.time()
    listing = _git(["worktree", "list", "--porcelain"], root, runner)
    trees, cur = [], {}
    for line in listing.splitlines() + [""]:
        if not line.strip():
            if cur.get("path"):
                trees.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "", 1)
        elif line == "detached":
            cur["detached"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = True
    real_root = os.path.realpath(root)

    def one(t):
        path = t["path"]
        last = _git(["log", "-1", "--format=%ct"], path, runner)
        ahead = behind = None
        if base:
            lr = _git(["rev-list", "--left-right", "--count", f"{base}...HEAD"], path, runner).split()
            if len(lr) == 2 and all(x.isdigit() for x in lr):
                behind, ahead = int(lr[0]), int(lr[1])
        try:
            touched = int(now - os.stat(path).st_mtime)
        except OSError:
            touched = None
        return {"name": os.path.basename(path)[:60], "main": os.path.realpath(path) == real_root,
                "branch": (t.get("branch") or ("detached" if t.get("detached") else ""))[:80],
                "changed": len([l for l in _git(["status", "--porcelain"], path, runner).splitlines() if l.strip()]),
                "last_commit_ago": int(now - int(last)) if last.isdigit() else None, "touched_ago": touched,
                "ahead": ahead, "behind": behind, "pr": None}

    live = [t for t in trees[:MAX_TREES] if not t.get("prunable") and os.path.isdir(t["path"])]
    with ThreadPoolExecutor(max_workers=8) as pool:         # a few git commands per worktree, and dozens of worktrees: side by side
        out = list(pool.map(one, live))
    return sorted(out, key=lambda w: (w["main"], w["last_commit_ago"] if w["last_commit_ago"] is not None else 10 ** 9))


def activity_of(t):
    """active: it holds changes or moved in the last two days; idle: moved in the last two weeks; old: nothing for longer."""
    last = t.get("last_commit_ago")
    if t.get("changed") or (last is not None and last < 2 * 86400):
        return "active"
    return "idle" if last is not None and last < 14 * 86400 else "old"


def stage_of(t):
    """Where a worktree's work stands, from facts only: its pull request, its changes, and whether it holds commits its base lacks."""
    pr = t.get("pr")
    if pr:
        if pr["state"] in ("merged", "closed"):
            if t.get("changed"):
                return "working"                    # new changes on a branch whose pull request is already finished
            return "clean" if t.get("main") else pr["state"]
        return "draft" if pr.get("draft") else "in review"
    if t.get("changed"):
        return "working"
    return "committed" if (t.get("ahead") or 0) > 0 else "clean"


PR_CACHE = {}


def _checks(rollup):
    """(passing, failing, pending) from a pull request's check rollup."""
    ok = bad = wait = 0
    for c in rollup or []:
        v = str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
        if v in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            ok += 1
        elif v in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            bad += 1
        else:
            wait += 1
    return ok, bad, wait


def _pr_row(pr):
    ok, bad, wait = _checks(pr.get("statusCheckRollup"))
    return {"number": pr.get("number"), "title": _short(pr.get("title"), 90), "state": str(pr.get("state") or "").lower(),
            "draft": bool(pr.get("isDraft")), "review": str(pr.get("reviewDecision") or "").lower(),
            "checks_ok": ok, "checks_bad": bad, "checks_wait": wait}


PR_FIELDS = "number,title,state,isDraft,headRefName,reviewDecision,statusCheckRollup,updatedAt,mergedAt"
HEAD_CACHE = {}
SKIP_BRANCHES = ("", "detached", "main", "master", "develop", "development")


def pull_request_for(repo, branch, runner=subprocess.run, ttl=600):
    """The newest pull request whose head is this branch (anyone's, any age), or None. One read only call, cached, so a branch with no
    pull request is not asked about again for ten minutes."""
    if not re.fullmatch(r"[\w./-]{1,120}", branch or ""):
        return None
    k = (repo, branch)
    hit = HEAD_CACHE.get(k)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    pr = None
    try:
        e = _env(); e["GH_PROMPT_DISABLED"] = "1"
        r = runner(["gh", "pr", "list", "-R", repo, "--head", branch, "--state", "all", "--limit", "1", "--json", PR_FIELDS],
                   capture_output=True, text=True, timeout=25, env=e)
        rows = json.loads(r.stdout) if r.returncode == 0 else []
        pr = _pr_row(rows[0]) if rows else None
    except (OSError, subprocess.SubprocessError, ValueError):
        pr = None
    HEAD_CACHE[k] = (time.time(), pr)
    return pr


def pull_requests(repo, runner=subprocess.run, ttl=90, branches=()):
    """{branch: pull request}: the owner's recent pull requests in one cached call, then one direct look for each listed branch they miss
    (a colleague's pull request, or an older one). Read only."""
    hit = PR_CACHE.get(repo)
    if hit and time.time() - hit[0] < ttl:
        return _with_heads(repo, hit[1], branches, runner)
    out = {}
    try:
        e = _env(); e["GH_PROMPT_DISABLED"] = "1"
        r = runner(["gh", "pr", "list", "-R", repo, "--author", "@me", "--state", "all", "--limit", "100", "--json", PR_FIELDS],
                   capture_output=True, text=True, timeout=25, env=e)
        for pr in (json.loads(r.stdout) if r.returncode == 0 else []):
            if pr.get("headRefName") and pr["headRefName"] not in out:        # newest first: the first one for a branch wins
                out[pr["headRefName"]] = _pr_row(pr)
    except (OSError, subprocess.SubprocessError, ValueError):
        out = {}
    PR_CACHE[repo] = (time.time(), out)
    return _with_heads(repo, out, branches, runner)


def _with_heads(repo, mine, branches, runner):
    missing = [b for b in dict.fromkeys(branches) if b not in mine and b not in SKIP_BRANCHES][:MAX_HEAD_LOOKUPS]
    if not missing:
        return mine
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = dict(zip(missing, pool.map(lambda b: pull_request_for(repo, b, runner), missing)))
    return {**mine, **{b: p for b, p in found.items() if p}}


# ---- command-fleet: states from its own `status`, a few log lines, and the three actions ----------------------------------------

LINE = re.compile(r"^ {2}(\S+)\s+(.+?)(?:\s+\(next (.+?)\))?\s*$")


def state_of(text):
    t = (text or "").lower()
    if any(w in t for w in ("not loaded", "paused", "stopped", "inactive", "disabled", "missing", "not running")):
        return "paused"
    if any(w in t for w in ("loaded", "running", "active", "scheduled", "waiting", "idle", "working")):
        return "on"
    return "unknown"


def parse_status(text):
    """{status_key: (raw text, state, next run)} from `status` output lines of the form two spaces, name, state, (next ...)."""
    out = {}
    for line in (text or "").splitlines():
        m = LINE.match(line)
        if m and ":" not in m.group(1) and not re.match(r"\S+:(\s|$)", m.group(2)) and m.group(1) not in out:      # the job lines come first; a later count line must not replace one
            out[m.group(1)] = (m.group(2).strip()[:80], state_of(m.group(2)), (m.group(3) or "").strip()[:40])
    return out


def tail(path, n=LOG_LINES, width=LOG_WIDTH):
    """(last lines, seconds since the file last changed) of a log inside the source's folder."""
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            f.seek(max(0, st.st_size - 4096))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return [l[:width] for l in lines if l.strip()][-n:], max(0, int(time.time() - st.st_mtime))
    except OSError:
        return [], None


def _env():
    e = dict(os.environ)
    e["NO_COLOR"] = "1"
    return e


def command_status(src, runner=subprocess.run):
    try:
        r = runner([str(src["cli"]), "status"], cwd=str(src["root"]), capture_output=True, text=True, timeout=20, env=_env())
        text, err = r.stdout, ("" if r.returncode == 0 else f"its status command exited {r.returncode}")
    except (OSError, subprocess.SubprocessError) as e:
        text, err = "", f"could not run its status command ({type(e).__name__})"
    states = parse_status(text)
    jobs = []
    for j in src["jobs"]:
        raw, st, nxt = states.get(j["status_key"], ("not in its status output", "unknown", ""))
        lines, ago = tail(j["log"]) if j["log"] else ([], None)
        jobs.append({"id": j["id"], "name": j["name"], "what": j["what"], "state": st, "raw": raw, "next": nxt,
                     "last_activity_ago": ago, "log": lines, "actions": ["pause" if st == "on" else "resume", "test"]})
    return {"id": src["id"], "kind": src["kind"], "project": src["project"], "title": src["title"], "about": src["about"], "jobs": jobs, "error": err}


def repo_status(src, runner=subprocess.run):
    agents = read_agents(src["agents"])
    trees = read_all_worktrees(src["root"], src.get("base", ""), runner=runner)
    prs = pull_requests(src["repo"], runner, branches=[t["branch"] for t in trees]) if src.get("repo") else {}
    for t in trees:
        t["pr"] = prs.get(t["branch"])
        t["activity"] = activity_of(t)
        t["stage"] = stage_of(t)
    runs = "own" if agents else "crew" if src.get("crew") else "none"      # the project's own agents, the built-in crew, or nothing set up yet
    return {"id": src["id"], "kind": src["kind"], "project": src["project"], "title": src["title"], "about": src["about"], "implicit": src.get("implicit", False),
            "runs": runs, "crew": src.get("crew", []), "agents": agents,
            "commands": read_commands(src["commands"], [a["name"] for a in agents]), "worktrees": trees,
            "sessions": build_sessions(ev) if (ev := read_events(src["id"])) is not None else None}


# ---- live sessions: events a Claude Code hook writes into Quarterdeck's own state/ (bin/fleet-hook.sh) ----------------------------------

EVENTS_DIR = _home.resolve() / "state" / "fleet-events"
EVENT_KINDS = ("session_start", "session_end", "prompt", "stop", "agent_start", "agent_stop")
SESSION_KEEP, SESSION_QUIET = 86400, 1800


def read_events(source_id, directory=None, limit=6000):
    """The newest events for a source, oldest first. Only the known fields are kept: when, what, which session and worktree, which agent."""
    path = Path(directory or EVENTS_DIR) / f"{source_id}.jsonl"
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.fstat(f.fileno()).st_size - 1_500_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[-limit:]
    except OSError:
        return None
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("event") in EVENT_KINDS and isinstance(e.get("t"), (int, float)) and re.fullmatch(r"[\w-]{1,80}", str(e.get("session", ""))):
            out.append({"t": float(e["t"]), "event": e["event"], "session": e["session"], "worktree": str(e.get("worktree", ""))[:60],
                        "branch": str(e.get("branch", ""))[:80], "agent": str(e.get("agent", ""))[:40]})
    return out


def build_sessions(events, now=None):
    """Sessions seen in the last day, newest activity first within each state. working: a prompt or an agent started after the last stop;
    idle: the turn finished; quiet: nothing for half an hour without an end; ended: it closed. Only what the events say, nothing guessed."""
    now = now or time.time()
    by = {}
    for e in events or []:
        if now - e["t"] > SESSION_KEEP:
            continue
        s = by.setdefault(e["session"], {"id": e["session"][:8], "first": e["t"], "last": e["t"], "worktree": "", "branch": "", "state": "idle",
                                           "open": {}, "used": {}, "turns": 0})
        s["last"] = max(s["last"], e["t"])
        if e["worktree"]:
            s["worktree"], s["branch"] = e["worktree"], e["branch"] or s["branch"]
        k = e["event"]
        if k == "prompt":
            s["state"], s["turns"] = "working", s["turns"] + 1
        elif k == "stop":
            s["state"], s["open"] = "idle", {}
        elif k == "session_end":
            s["state"], s["open"] = "ended", {}
        elif k == "session_start" and s["state"] != "working":
            s["state"] = "idle"
        elif k == "agent_start" and e["agent"]:
            s["state"] = "working" if s["state"] != "ended" else "ended"
            s["open"][e["agent"]] = s["open"].get(e["agent"], 0) + 1
            s["used"][e["agent"]] = s["used"].get(e["agent"], 0) + 1
        elif k == "agent_stop" and e["agent"] and s["open"].get(e["agent"]):
            s["open"][e["agent"]] -= 1
            if not s["open"][e["agent"]]:
                del s["open"][e["agent"]]
    out = []
    for s in by.values():
        age = now - s["last"]
        if s["state"] in ("working", "idle") and age > SESSION_QUIET:
            s["state"] = "quiet"
        out.append({"id": s["id"], "state": s["state"], "worktree": s["worktree"], "branch": s["branch"], "turns": s["turns"],
                    "running_agents": sorted(s["open"]), "agents_used": dict(sorted(s["used"].items(), key=lambda kv: -kv[1])),
                    "started_ago": int(now - s["first"]), "last_ago": int(age)})
    rank = {"working": 0, "idle": 1, "quiet": 2, "ended": 3}
    return sorted(out, key=lambda x: (rank[x["state"]], x["last_ago"]))


def projects(cfg=None):
    """The Quarterdeck project names that have a fleet source, so the page can send you there. Names only, nothing read."""
    cfg = cfg or load_config()
    def has_own(s):     # a project found on its own is sent to the Fleet page only when it really has agents of its own
        return not s.get("implicit") or (s["agents"].is_dir() and any(s["agents"].glob("*.md")))
    return sorted({s["project"] for s in cfg["sources"] if s["project"] and has_own(s)})


def snapshot(cfg=None, runner=subprocess.run):
    cfg = cfg or load_config()
    def one(s):
        return command_status(s, runner) if s["kind"] == "command-fleet" else repo_status(s, runner)
    with ThreadPoolExecutor(max_workers=6) as pool:                 # each project is its own git and gh calls: read them side by side, keep the order
        out = list(pool.map(one, cfg["sources"]))
    return {"sources": out, "errors": cfg["errors"], "at": int(time.time())}


def action_argv(cfg, source_id, job_id, action):
    """(argv, cwd, detached) for an action the config allows, or an error string. Nothing typed ever reaches the command."""
    src = next((s for s in cfg["sources"] if s["id"] == source_id and s["kind"] == "command-fleet"), None)
    job = src and next((j for j in src["jobs"] if j["id"] == job_id), None)
    if not job:
        return "unknown source or job"
    if action not in SYNC_ACTIONS + ASYNC_ACTIONS:
        return "an action is pause, resume or test"
    return [str(src["cli"]), action, job["arg"]], str(src["root"]), action in ASYNC_ACTIONS


def run_action(cfg, source_id, job_id, action, log_dir, runner=subprocess.run, popen=subprocess.Popen):
    """Do it. pause and resume wait for the command; test (one poll, can take minutes) starts it and returns."""
    a = action_argv(cfg, source_id, job_id, action)
    if isinstance(a, str):
        return False, a
    argv, cwd, detached = a
    try:
        if detached:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            fd = os.open(str(Path(log_dir) / f"fleet-{source_id}-{job_id}-test.log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            popen(argv, cwd=cwd, stdout=fd, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, env=_env())
            os.close(fd)
            return True, "started one run; it keeps going on its own"
        r = runner(argv, cwd=cwd, capture_output=True, text=True, timeout=30, env=_env())
        msg = _short(r.stdout or r.stderr, 160)
        return r.returncode == 0, msg or ("done" if r.returncode == 0 else f"exited {r.returncode}")
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"could not run it ({type(e).__name__})"
