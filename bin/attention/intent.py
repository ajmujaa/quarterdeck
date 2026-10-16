"""The owner's stated focus and his Continue / Park / Archive choices. Both are small, local and private (mode 0600, listed
in QUARTERDECK_PRIVATE_DENY). Neither is ever sent anywhere. Park and Archive only mark a project so Quarterdeck stops raising it as
dormant: they never delete, move or touch a repository."""
import json
import os
import re
from datetime import date, timedelta

MAX_PROJECTS = 4
STATUSES = ("continue", "park", "archive")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def week_range(today, which="this"):
    """Monday to Sunday of this week or next, as YYYY-MM-DD strings. `today` is a YYYY-MM-DD string in local time."""
    d = date.fromisoformat(today)
    mon = d - timedelta(days=d.weekday()) + timedelta(days=7 if which == "next" else 0)
    return mon.isoformat(), (mon + timedelta(days=6)).isoformat()


def make_intent(projects, known, today, at, which="this"):
    """One append-only record. Names must be registered projects, 1 to 4 of them; shares are optional and each 0 to 1,
    adding up to at most 1. Raises ValueError with a sentence the page can show."""
    if which not in ("this", "next"):
        raise ValueError("the week is this or next")
    if not isinstance(projects, list) or not 1 <= len(projects) <= MAX_PROJECTS:
        raise ValueError(f"pick 1 to {MAX_PROJECTS} projects")
    out, seen, total = [], set(), 0.0
    for x in projects:
        name = x.get("name") if isinstance(x, dict) else x
        if not isinstance(name, str) or name not in known:
            raise ValueError("unknown project")
        if name in seen:
            raise ValueError("a project is listed twice")
        seen.add(name)
        rec = {"name": name}
        sh = x.get("share") if isinstance(x, dict) else None
        if sh not in (None, ""):
            if isinstance(sh, bool) or not isinstance(sh, (int, float)) or not 0 < sh <= 1:
                raise ValueError("a share is between 0 and 1")
            rec["share"] = round(float(sh), 3)
            total += rec["share"]
        out.append(rec)
    if total > 1.001:
        raise ValueError("the shares add up to more than 1")
    start, end = week_range(today, which)
    return {"at": at, "from": start, "to": end, "projects": out}


def read_intents(path):
    """The records, oldest first. Lines of the wrong shape are skipped; nothing here can raise."""
    rows = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            r = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not (isinstance(r, dict) and DAY.fullmatch(str(r.get("from", ""))) and DAY.fullmatch(str(r.get("to", ""))) and isinstance(r.get("projects"), list)):
            continue
        ps = []
        for x in r["projects"][:MAX_PROJECTS]:
            if isinstance(x, dict) and isinstance(x.get("name"), str):
                ps.append({k: x[k] for k in ("name", "share") if k in x and (k == "name" or isinstance(x[k], (int, float)) and not isinstance(x[k], bool))})
        if ps:
            rows.append({"at": str(r.get("at") or "")[:40], "from": r["from"], "to": r["to"], "projects": ps})
    return rows


def append_private(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(rec) + "\n")


def read_status(path):
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    out = {}
    for p, v in (raw.items() if isinstance(raw, dict) else []):
        if isinstance(v, dict) and v.get("status") in STATUSES and DAY.fullmatch(str(v.get("at", ""))):
            out[str(p)[:60]] = {"status": v["status"], "at": v["at"]}
    return out


def set_status(path, project, status, known, today):
    if not isinstance(project, str) or project not in known:
        raise ValueError("unknown project")
    if status not in STATUSES:
        raise ValueError("status is continue, park or archive")
    cur = read_status(path)
    cur[project] = {"status": status, "at": today}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cur, f)
    os.replace(tmp, path)
    return cur[project]
