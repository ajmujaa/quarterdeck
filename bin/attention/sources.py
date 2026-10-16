"""The readers. Standing rule: nothing outside the registered projects and Quarterdeck's own state/ is ever read (no
session files of any tool, no apps, screens, keystrokes, clipboard or location).

The readers. Each returns {project: {day: {field: number}}} and nothing else.

What each one looks at, and what it never keeps:
  git                   `git log --pretty=format:%ad --shortstat` for the owner's own commits (git itself drops those carrying the agents'
                        Co-Authored-By: Claude trailer): dates and counts, no message,
                        no author, no file name, no diff;
  pull requests, notes, calendar   the dates the dashboard already holds (created, at), never a title or a body.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}")
AGENT_TRAILER = "Co-Authored-By: Claude"      # commits the agents make under his name carry this trailer; git drops them, so no message ever reaches this program
DAY = re.compile(r"\d{4}-\d\d-\d\d")


def day_of(ts, tz=None):
    """The calendar day of an epoch time in `tz` (the Mac's own zone when None)."""
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def parse_ts(value):
    """An ISO time as epoch seconds, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---- git ----------------------------------------------------------------------------
def repo_email(path, run=subprocess.run):
    try:
        r = run(["git", "-C", str(path), "config", "user.email"], capture_output=True, text=True, timeout=10)
        e = (r.stdout or "").strip()
        return e if r.returncode == 0 and EMAIL.fullmatch(e) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


DAYHOUR = re.compile(r"(\d{4}-\d\d-\d\d) (\d\d)")


def parse_git_log(text):
    """Commits and files per day, and commits per hour of the day, from `--pretty=format:%ad --shortstat` output where %ad is
    "YYYY-MM-DD HH". {day: {commits, files, hours: {HH: n}}}. Nothing else in the output is kept."""
    out, cur = {}, None
    for ln in str(text).splitlines():
        ln = ln.strip()
        m = DAYHOUR.fullmatch(ln)
        if m:
            cur = out.setdefault(m.group(1), {"commits": 0, "files": 0, "hours": {}})
            cur["commits"] += 1
            cur["hours"][m.group(2)] = cur["hours"].get(m.group(2), 0) + 1
        elif cur is not None:
            m = re.match(r"(\d+) files? changed", ln)
            if m:
                cur["files"] += int(m.group(1))
    return out


def git_days(path, email, since_day, run=subprocess.run):
    """{day: {commits, files, hours}} for the owner's commits since a day. Never a message, an author, a file name or a diff."""
    p = Path(str(path)).expanduser()
    if not (p / ".git").exists() or not EMAIL.fullmatch(email or "") or not DAY.fullmatch(since_day or ""):
        return {}
    try:
        r = run(["git", "-c", "log.showSignature=false", "-c", "core.fsmonitor=false", "-C", str(p), "log", "--no-merges", "--fixed-strings", "--regexp-ignore-case",
                 "--author=" + email, "--invert-grep", "--grep=" + AGENT_TRAILER, "--since=" + since_day,
                 "--date=format-local:%Y-%m-%d %H", "--pretty=format:%ad", "--shortstat"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_git_log(r.stdout) if r.returncode == 0 else {}


# ---- what the dashboard already holds -------------------------------------------------
def _day_of_iso(value, tz=None):
    t = parse_ts(value)
    return day_of(t, tz) if t is not None else None


def count_days(items, field, project_of, tz=None):
    """{project: {day: n}} from dates alone."""
    out = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            d = _day_of_iso(it.get(field), tz)
            if d:
                p = project_of(it)
                out.setdefault(p, {}).setdefault(d, 0)
                out[p][d] += 1
    return out


def hour_of(value, tz=None):
    """("YYYY-MM-DD", "HH") of an ISO time, or None."""
    t = parse_ts(value)
    return (day_of(t, tz), datetime.fromtimestamp(t, tz).strftime("%H")) if t is not None else None


def count_hours(items, field, project_of, tz=None):
    """{project: {day: {HH: n}}} from timestamps alone."""
    out = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            dh = hour_of(it.get(field), tz)
            if dh:
                h = out.setdefault(project_of(it), {}).setdefault(dh[0], {})
                h[dh[1]] = h.get(dh[1], 0) + 1
    return out
