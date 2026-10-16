"""What the owner worked on, and when: the labels for My rhythm's task timeline.

THE ONE PLACE WHERE TITLES ARE KEPT. Everything else under bin/attention/ stores counts only. This file stores the owner's own words, so it
lives in state/rhythm-tasks.json only (mode 0600, on QUARTERDECK_PRIVATE_DENY and the sandbox deny list, 400 days, deleted with
`rm -f state/rhythm-tasks.json`), is shown only on his screen, and is never sent to any model or off this Mac.

The ONLY fields kept, per event: the time (to the minute), a kind, the project, one short label, and for a branch its name:
  commit   the SUBJECT line (the first line, nothing after it) of his own commits; commits agents make under his name carry a
           Co-Authored-By: Claude trailer and git itself leaves them out (--invert-grep), so no body is ever read here;
  branch   the branch he checked out, from the project's own git reflog (checkout entries and their time), as a plain label;
  pr       the title of a pull request he opened;
  note     the text of a note he added in Quarterdeck;
  run      the objective of a mission, or the duty and number of a run, he started by hand from Quarterdeck;
  meeting  the title of a timed event in his calendar snapshot.
Never a commit body, a diff, a file name or file content, a message from any chat or mail, or anything outside the registered
projects, state/ and the calendar. No file times, no editor, terminal, browser or app activity.
"""
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from attention import sources

FILE = "rhythm-tasks.json"
VERSION = 1
KEEP_DAYS = 400
MAX_LABEL = 140
MAX_EVENTS = 20000
KINDS = ("commit", "branch", "pr", "note", "run", "meeting")
GIT_BACK_DAYS = 45
CTRL = re.compile(r"[\x00-\x1f\x7f]")
TYPE_WORDS = {"feat", "feature", "fix", "bugfix", "hotfix", "chore", "docs", "doc", "refactor", "test", "tests", "cloud", "integrate", "release", "wip"}
HEX = re.compile(r"[0-9a-f]{7,40}")


def clean(text, limit=MAX_LABEL):
    return " ".join(CTRL.sub(" ", str(text if text is not None else "")).split())[:limit]


def branch_label(name):
    """feat/focus-voice becomes "focus voice"; an issue number becomes "#47" (fix/47-login becomes "#47 login")."""
    name = clean(name, 80)
    if not name or HEX.fullmatch(name) or name in ("HEAD", "main", "master"):
        return name if name in ("main", "master") else ""
    parts = [p for p in re.split(r"/", name) if p]
    while len(parts) > 1 and parts[0].lower() in TYPE_WORDS:
        parts.pop(0)
    words = re.sub(r"[-_.]+", " ", " ".join(parts)).split()
    issue = None
    for i, w in enumerate(words):
        m = re.fullmatch(r"(?:issue|gh|bug|pr)?#?(\d{2,6})", w, re.I)
        if m:
            issue = m.group(1)
            words.pop(i)
            if i and words[i - 1].lower() in ("issue", "gh", "bug", "pr"):
                words.pop(i - 1)
            break
    text = " ".join(words)
    return clean((f"#{issue} " if issue else "") + text)


# ---- the readers (git runs inside the registered project only) ----
def commit_subjects(path, email, since_day, run=subprocess.run):
    """[(YYYY-MM-DDTHH:MM, subject)] of the owner's own commits. %s is the subject: the first line only. Agent commits are dropped by git."""
    p = Path(str(path)).expanduser()
    if not (p / ".git").exists() or not sources.EMAIL.fullmatch(email or "") or not sources.DAY.fullmatch(since_day or ""):
        return []
    try:
        r = run(["git", "-c", "log.showSignature=false", "-c", "core.fsmonitor=false", "-C", str(p), "log", "--no-merges", "--fixed-strings", "--regexp-ignore-case",
                 "--author=" + email, "--invert-grep", "--grep=" + sources.AGENT_TRAILER, "--since=" + since_day,
                 "--date=format-local:%Y-%m-%dT%H:%M", "--pretty=format:%ad%x09%s"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for ln in (r.stdout or "").splitlines() if r.returncode == 0 else []:
        t, _, subject = ln.partition("\t")
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", t) and clean(subject):
            out.append((t, clean(subject)))
    return out


def checkouts(path, since_day, run=subprocess.run):
    """[(YYYY-MM-DDTHH:MM, branch)] from the project's own reflog: the entries that say "checkout: moving from A to B"."""
    p = Path(str(path)).expanduser()
    if not (p / ".git").exists() or not sources.DAY.fullmatch(since_day or ""):
        return []
    try:
        r = run(["git", "-c", "core.fsmonitor=false", "-C", str(p), "reflog", "show", "HEAD", "--date=format-local:%Y-%m-%dT%H:%M", "--format=%gd%x09%gs"],
                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for ln in (r.stdout or "").splitlines() if r.returncode == 0 else []:
        sel, _, subj = ln.partition("\t")
        m = re.fullmatch(r"HEAD@\{(\d{4}-\d\d-\d\dT\d\d:\d\d)\}", sel)
        c = re.fullmatch(r"checkout: moving from .+ to (\S+)", subj)
        if m and c and m.group(1)[:10] >= since_day:
            out.append((m.group(1), c.group(1)))
    return out


def run_label(duty, args):
    """"surveyor, PR #12" or "panel: <the idea>" for a run he started by hand."""
    duty = clean(duty, 30)
    args = [str(a) for a in args or []]
    for flag in ("--idea",):
        if flag in args and args.index(flag) + 1 < len(args):
            return clean(f"{duty}: {args[args.index(flag) + 1]}")
    for flag, name in (("--pr", "PR #"), ("--issue", "issue #")):
        if flag in args and args.index(flag) + 1 < len(args) and re.fullmatch(r"\d{1,7}", args[args.index(flag) + 1]):
            return f"{duty}, {name}{args[args.index(flag) + 1]}"
    return duty


# ---- the store ----
def _t(value, tz=None):
    t = sources.parse_ts(value)
    return datetime.fromtimestamp(t, tz).strftime("%Y-%m-%dT%H:%M") if t is not None else None


def _event(t, kind, project, label, **extra):
    label = clean(label)
    return {"t": t, "kind": kind, "project": clean(project, 60), "label": label, **extra} if t and label and kind in KINDS else None


def _merge(events, kind, new, covered_day=None, covered_from=None, keep=False):
    """Replace the events of one kind. `covered_day` (a set of days) limits the replacement to the days that source read; `covered_from`
    keeps events before that time; `keep` unions instead (a pull request cache forgets, so what was seen stays)."""
    if not keep:
        events = [e for e in events if e["kind"] != kind or (covered_day is not None and e["t"][:10] not in covered_day)
                  or (covered_from is not None and e["t"] < covered_from)]
    seen = {(e["t"], e["kind"], e["project"], e["label"]) for e in events}
    for e in new:
        if e and (e["t"], e["kind"], e["project"], e["label"]) not in seen:
            events.append(e)
            seen.add((e["t"], e["kind"], e["project"], e["label"]))
    return events


def collect_tasks(inputs, store, now, tz=None, email_of=None, run=subprocess.run):
    """Update the stored events from the sources and return the new store dict. `inputs` has projects, prs [{project, created, title}],
    notes [{project, at, text}], runs [{project, at, label}], calendar [{at, sub, title}]."""
    events = [e for e in (store.get("events") if isinstance(store, dict) else []) or [] if isinstance(e, dict) and e.get("kind") in KINDS and isinstance(e.get("t"), str)]
    projects = inputs.get("projects") or {}
    since = (datetime.fromtimestamp(now) - timedelta(days=GIT_BACK_DAYS)).strftime("%Y-%m-%d")
    covered = {(datetime.fromtimestamp(now) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(GIT_BACK_DAYS + 1)}
    commits, branches = [], []
    for name, v in projects.items():
        if not isinstance(v, dict) or not v.get("path"):
            continue
        email = (email_of or sources.repo_email)(str(Path(str(v["path"])).expanduser()))
        commits += [_event(t, "commit", name, s) for t, s in commit_subjects(v["path"], email, since, run)]
        branches += [_event(t, "branch", name, branch_label(b), branch=clean(b, 80)) for t, b in checkouts(v["path"], since, run)]
    events = _merge(events, "commit", commits, covered)
    events = _merge(events, "branch", branches, covered)
    proj = lambda it: it.get("project") if it.get("project") in projects else ""
    events = _merge(events, "pr", [_event(_t(p.get("created"), tz), "pr", proj(p), p.get("title")) for p in inputs.get("prs") or [] if isinstance(p, dict)], keep=True)
    events = _merge(events, "note", [_event(_t(n.get("at"), tz), "note", proj(n), n.get("text")) for n in inputs.get("notes") or [] if isinstance(n, dict)])
    events = _merge(events, "run", [_event(_t(r.get("at"), tz), "run", proj(r), r.get("label")) for r in inputs.get("runs") or [] if isinstance(r, dict)])
    now_t = datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M")
    cal = [_event(_t(c.get("at"), tz), "meeting", "", c.get("title")) for c in inputs.get("calendar") or []
           if isinstance(c, dict) and "all day" not in str(c.get("sub") or "").lower()]
    events = _merge(events, "meeting", cal, covered_from=now_t)                  # past blocks stay as seen; coming ones follow the snapshot
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    events = sorted((e for e in events if e["t"][:10] >= cutoff), key=lambda e: (e["t"], e["kind"]))[-MAX_EVENTS:]
    keep = {"t", "kind", "project", "label", "branch"}
    events = [{k: v for k, v in e.items() if k in keep} for e in events]
    return {"version": VERSION, "updated": datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S"), "events": events}
