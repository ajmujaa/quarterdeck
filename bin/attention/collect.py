"""Put the readers together and keep state/attention.json: incremental, tolerant, private."""
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from attention import sources, tasks

VERSION = 1
KEEP_DAYS = 400
OWNED = {"git": ("commits", "files"), "prs": ("prs",), "notes": ("notes",), "runs": ("runs",), "calendar": ("meetings",)}
HOUR_FIELD = {"git": "commits", "prs": "prs", "notes": "notes", "runs": "runs", "calendar": "meetings"}
GIT_BACK_DAYS = 45            # the git log is re-read this far back each pass; older days are kept as they were


def write_private(path, text):
    """Atomic, owner only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default):
    try:
        v = json.loads(Path(path).read_text())
        return v if isinstance(v, type(default)) else default
    except (OSError, ValueError, RecursionError):
        return default


def merge(days, source, result, covered=None, keep_max=False):
    """Replace the fields one source owns. A source that reads everything clears its fields first; one that reads a window
    (`covered`: a set of days) clears them only inside it. `keep_max` is for counts that can only grow but whose source can
    forget (an open pull request that was merged leaves the cache): the larger of the old and new number stays.
    Nothing owned by another source is touched."""
    fields = OWNED[source]
    old = {}
    for p, per_day in days.items():
        for d, v in per_day.items():
            if covered is None or d in covered:
                for f in fields:
                    if f in v:
                        old[(p, d, f)] = v.pop(f)
    for p, per_day in result.items():
        for d, vals in per_day.items():
            slot = days.setdefault(p, {}).setdefault(d, {})
            for f in fields:
                if f in vals:
                    slot[f] = vals[f]
    if keep_max:
        for (p, d, f), v in old.items():
            slot = days.setdefault(p, {}).setdefault(d, {})
            slot[f] = max(slot.get(f, 0), v)
    return days


def merge_hours(hours, field, result, covered=None, keep_max=False):
    """The same ownership rule as merge(), for the hour buckets: {project: {day: {HH: {field: n}}}}. A source replaces only its own
    field, inside the days it read (all days when `covered` is None)."""
    old = {}
    for p, per_day in hours.items():
        for d, per_hour in per_day.items():
            if covered is None or d in covered:
                for hh, v in per_hour.items():
                    if field in v:
                        old[(p, d, hh)] = v.pop(field)
    for p, per_day in result.items():
        for d, per_hour in per_day.items():
            for hh, n in per_hour.items():
                hours.setdefault(p, {}).setdefault(d, {}).setdefault(hh, {})[field] = n
    if keep_max:
        for (p, d, hh), v in old.items():
            slot = hours.setdefault(p, {}).setdefault(d, {}).setdefault(hh, {})
            slot[field] = max(slot.get(field, 0), v)
    return hours


def prune_hours(hours, now, keep=KEEP_DAYS):
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=keep)).strftime("%Y-%m-%d")
    for p in list(hours):
        for d in list(hours[p]):
            hours[p][d] = {hh: v for hh, v in hours[p][d].items() if v}
            if d < cutoff or not hours[p][d]:
                del hours[p][d]
        if not hours[p]:
            del hours[p]
    return hours


def prune(days, now, keep=KEEP_DAYS):
    cutoff = (datetime.fromtimestamp(now) - timedelta(days=keep)).strftime("%Y-%m-%d")
    for project in list(days):
        for day in list(days[project]):
            if day < cutoff or not days[project][day]:
                del days[project][day]
        if not days[project]:
            del days[project]
    return days


def collect(inputs, state_dir, now=None, tz=None):
    """One pass. inputs: {projects, prs: [{project, created}], notes: [{project, at}], runs: [{project, at}], calendar: [{at, sub}],
    email_of, run}. Returns a short summary. Reads nothing but timestamps and counts (see sources.py)."""
    now = now or time.time()
    state_dir = Path(state_dir)
    store = read_json(state_dir / "attention.json", {})
    days = store.get("days") if isinstance(store.get("days"), dict) else {}
    hours = store.get("hours") if isinstance(store.get("hours"), dict) else {}
    for old in ("attention-cache.json",):                        # left by an earlier version that read session files: gone
        try:
            (state_dir / old).unlink()
        except OSError:
            pass
    for per_day in days.values():                               # and so are the minutes and sessions it wrote
        for v in per_day.values():
            if isinstance(v, dict):
                v.pop("minutes", None)
                v.pop("sessions", None)
    projects = inputs.get("projects") or {}
    summary = {}

    since = (datetime.fromtimestamp(now) - timedelta(days=GIT_BACK_DAYS)).strftime("%Y-%m-%d")
    covered = {(datetime.fromtimestamp(now) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(GIT_BACK_DAYS + 1)}
    git, git_hours = {}, {}
    for name, v in projects.items():
        if not isinstance(v, dict) or not v.get("path"):
            continue
        email = (inputs.get("email_of") or sources.repo_email)(str(Path(str(v["path"])).expanduser()))
        res = sources.git_days(v["path"], email, since, inputs.get("run") or __import__("subprocess").run)
        if res:
            git[name] = {d: {k: x for k, x in r.items() if k != "hours"} for d, r in res.items()}
            git_hours[name] = {d: {hh: n for hh, n in r.get("hours", {}).items()} for d, r in res.items()}
    merge(days, "git", git, covered)
    merge_hours(hours, "commits", {p: {d: {hh: n for hh, n in v.items()} for d, v in per.items()} for p, per in git_hours.items()}, covered)
    summary["git_projects"] = len(git)

    proj_of = lambda it: it.get("project") if it.get("project") in projects else "other"
    prs = {p: {d: n for d, n in v.items()} for p, v in sources.count_days(inputs.get("prs"), "created", proj_of, tz).items()}
    merge(days, "prs", {p: {d: {"prs": n} for d, n in v.items()} for p, v in prs.items()}, None, keep_max=True)
    merge_hours(hours, "prs", sources.count_hours(inputs.get("prs"), "created", proj_of, tz), None, keep_max=True)
    notes = sources.count_days(inputs.get("notes"), "at", proj_of, tz)
    merge(days, "notes", {p: {d: {"notes": n} for d, n in v.items()} for p, v in notes.items()}, None)
    merge_hours(hours, "notes", sources.count_hours(inputs.get("notes"), "at", proj_of, tz), None)
    runs = sources.count_days(inputs.get("runs"), "at", proj_of, tz)             # agent runs the owner started by hand from Quarterdeck (its own state/)
    merge(days, "runs", {p: {d: {"runs": n} for d, n in v.items()} for p, v in runs.items()}, None)
    merge_hours(hours, "runs", sources.count_hours(inputs.get("runs"), "at", proj_of, tz), None)
    cal, cal_items = {}, []
    for it in inputs.get("calendar") or []:
        if isinstance(it, dict) and "all day" not in str(it.get("sub") or "").lower():
            d = sources._day_of_iso(it.get("at"), tz)
            if d:
                cal.setdefault("(calendar)", {}).setdefault(d, {"meetings": 0})["meetings"] += 1
                cal_items.append({"project": "(calendar)", "at": it.get("at")})      # the time only: the title is never copied
    cal_days = set(d for v in cal.values() for d in v)
    merge(days, "calendar", cal, cal_days)
    merge_hours(hours, "meetings", sources.count_hours(cal_items, "at", lambda it: "(calendar)", tz), cal_days)

    if inputs.get("rhythm_tasks"):                       # the owner's own words for the task timeline: the one file that holds titles (see tasks.py)
        old = read_json(state_dir / tasks.FILE, {})
        new = tasks.collect_tasks(inputs, old, now, tz, inputs.get("email_of"), inputs.get("run") or __import__("subprocess").run)
        write_private(state_dir / tasks.FILE, json.dumps(new, separators=(",", ":")))
        summary["task_events"] = len(new["events"])
    prune(days, now)
    prune_hours(hours, now)
    out = {"version": VERSION, "updated": datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S"), "estimated": True, "days": days, "hours": hours}
    write_private(state_dir / "attention.json", json.dumps(out, separators=(",", ":")))
    summary["projects"] = len(days)
    return summary
