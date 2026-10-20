#!/usr/bin/env python3
"""tickets: the local ticket list of a project, and the drafts the planner writes before anything is filed.

    state/tickets/<project>.json in your data folder (folder 0700, file 0600, written atomically under a lock):

        {"project": "my-app", "next_id": 3, "next_draft": 2, "tickets": [...], "drafts": [...]}

    ticket  {id, title, body, acceptance:[...], requirements, status: open|building|review|done, source: local|github,
             issue: null|<number>, url: null|<https url>, branch: null|<name>, cycle: null|<id>, created, updated}
    draft   {id: "d1"..., request, tickets: [{title, body, acceptance}], at}

A ticket is text. It never carries a path, a command or a flag for the harness to run: the harness reads only the fields above, and every one of them is
checked here (size, plain text, no control characters, no comment markers, no @mentions) before it is stored, shown or filed.
Drafts and tickets are never mixed: a draft is what the planner proposed; a ticket exists once someone filed it (--apply).

    bin/tickets.py list <project>                    tickets and drafts, one line each
    bin/tickets.py show [--json] <project> <id|dN>   one ticket (a number) or one draft (d1, d2 ...)
    bin/tickets.py drafts <project>                  the drafts, one line each
    bin/tickets.py file <project> <draft-id> [--apply]   save a draft as LOCAL tickets (nothing goes to GitHub from here); report only without --apply
    bin/tickets.py remove-draft <project> <draft-id>

The shell side (duties/planner.sh, the purser, the panel, the shipwright, bin/cycle) uses the helper commands at the bottom of main(). Standard library only.
"""
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home as _home

MAX_TICKETS = 500
MAX_DRAFTS = 50
MAX_DRAFT_TICKETS = 5
TITLE_MAX, BODY_MAX, CHECK_MAX, CHECKS_MAX, REQ_MAX, REQUEST_MAX = 120, 4000, 300, 8, 8000, 2000
STATUSES = ("open", "building", "review", "done")
SOURCES = ("local", "github")
PROJECT_OK = re.compile(r"[a-z0-9][a-z0-9_.-]{0,60}")          # the registry's name rule (bin/attach.py apply)
DRAFT_OK = re.compile(r"d[1-9][0-9]{0,8}")
CYCLE_OK = re.compile(r"[A-Za-z0-9._-]{1,120}")
BRANCH_OK = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]{0,199}")
URL_OK = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull)/[0-9]{1,9}")
_BAD_CHARS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")      # control characters (a tab and a line break are handled apart)
_HIDDEN = re.compile("[­؜᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]")     # zero-width and bidirectional controls
_MENTION = re.compile(r"(?<![A-Za-z0-9_.+/-])@(?=[A-Za-z0-9])")           # an @name or @org/team; an e-mail address (a@b.c) keeps its @
_FORGED_HEADING = re.compile(r"(?im)^\s{0,3}#{1,6}\s*(requirements|quarterdeck\b.*)\s*$")


_LIST = list      # the module defines list() below; the builtin is kept here for isinstance


class TicketError(ValueError):
    """A sentence the owner can act on."""


def home():
    return _home.resolve()


def folder():
    return home() / "state" / "tickets"


def _project(p):
    if not isinstance(p, str) or not PROJECT_OK.fullmatch(p):
        raise TicketError("the project name may hold lowercase letters, digits, dot, dash and underscore")
    return p


def _path(project):
    return folder() / f"{_project(project)}.json"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---- text: plain, bounded, and nothing that forges one of our marks -----------------------------------------------------------
def clean(s, field, limit, multiline=False, mentions=True, marks=True):
    """The text as it will be stored. Raises TicketError for what is not plain text. @mentions lose their @ so a ticket never pings anyone."""
    if not isinstance(s, str):
        raise TicketError(f"{field} must be text")
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        raise TicketError(f"{field} is empty")
    if _HIDDEN.search(s):
        raise TicketError(f"{field} holds an invisible or direction-changing character")
    probe = s.replace("\n", "").replace("\t", "") if multiline else s
    if _BAD_CHARS.search(probe) or (not multiline and ("\n" in s or "\t" in s)):
        raise TicketError(f"{field} holds a control character" if multiline else f"{field} must be one line of plain text")
    if len(s) > limit:
        raise TicketError(f"{field} is {len(s)} characters; the limit is {limit}")
    if marks:        # the purser's own requirements (marks=False) are Quarterdeck's text and carry a Requirements heading; its comment marks are cut off before they get here
        if "<!--" in s or "-->" in s:
            raise TicketError(f"{field} holds an HTML comment, which could forge one of Quarterdeck's marks")
        if "quarterdeck:" in s.lower():
            raise TicketError(f"{field} holds a Quarterdeck mark")
        if _FORGED_HEADING.search(s):
            raise TicketError(f"{field} has a heading that would pass for one Quarterdeck writes")
    if mentions:
        s = _MENTION.sub("", s)
    return s


def validate_ticket(t):
    if not isinstance(t, dict):
        raise TicketError("a ticket must be an object with a title, a body and acceptance checks")
    title = clean(t.get("title"), "the title", TITLE_MAX)
    body = clean(t.get("body"), "the body", BODY_MAX, multiline=True)
    acc = t.get("acceptance")
    if not isinstance(acc, _LIST) or not 1 <= len(acc) <= CHECKS_MAX:
        raise TicketError(f"acceptance must be a list of 1 to {CHECKS_MAX} checks")
    return {"title": title, "body": body, "acceptance": [clean(a, "an acceptance check", CHECK_MAX) for a in acc]}


def validate_draft(obj):
    """The checked draft: {"tickets": [{title, body, acceptance}]} (a bare list is accepted too) -> the list of cleaned tickets (1 to 5).
    Extra keys are dropped. Raises TicketError; nothing is stored here."""
    items = obj.get("tickets") if isinstance(obj, dict) else obj
    if not isinstance(items, _LIST) or not 1 <= len(items) <= MAX_DRAFT_TICKETS:
        raise TicketError(f"a draft holds 1 to {MAX_DRAFT_TICKETS} tickets")
    out, seen = [], set()
    for i, t in enumerate(items, 1):
        try:
            c = validate_ticket(t)
        except TicketError as e:
            raise TicketError(f"ticket {i}: {e}")
        k = norm_title(c["title"])
        if k in seen:
            raise TicketError(f"ticket {i}: the title repeats an earlier ticket of the draft")
        seen.add(k)
        out.append(c)
    return out


def norm_title(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s).lower()).split())


def check_request(s):
    """The owner's own words, as data: plain text, at most 2000 characters, line breaks allowed."""
    return clean(s, "the request", REQUEST_MAX, multiline=True, mentions=False)


# ---- the store -----------------------------------------------------------------------------------------------------------------
def _empty(project):
    return {"project": project, "next_id": 1, "next_draft": 1, "tickets": [], "drafts": []}


@contextmanager
def _locked(project):
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    lk = d / f".{_project(project)}.lock"
    fd = os.open(lk, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def load(project):
    """The store of a project: always a well-formed dict (an empty one when there is no file, or the file does not parse)."""
    p = _path(project)
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return _empty(project)
    if not isinstance(d, dict):
        return _empty(project)
    base = _empty(project)
    for k in ("tickets", "drafts"):
        d[k] = [x for x in d.get(k, []) if isinstance(x, dict)] if isinstance(d.get(k), _LIST) else []
    for k in ("next_id", "next_draft"):
        if not isinstance(d.get(k), int) or d[k] < 1:
            d[k] = base[k]
    d["next_id"] = max(d["next_id"], 1 + max([t.get("id", 0) for t in d["tickets"] if isinstance(t.get("id"), int)] or [0]))
    d["project"] = project
    return d


def save(project, data):
    """Atomic: a new file next to the old one (random name, O_EXCL), owner-only, then rename."""
    p = _path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="." + p.name + ".")
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(json.dumps(data, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _modify(project, fn):
    with _locked(project):
        d = load(project)
        r = fn(d)
        save(project, d)
        return r


def _new_ticket(d, c, source="local", issue=None, url=None):
    n = d["next_id"]
    d["next_id"] = n + 1
    now = _now()
    t = {"id": n, "title": c["title"], "body": c["body"], "acceptance": c["acceptance"], "requirements": "", "status": "open",
         "source": source, "issue": issue, "url": url, "branch": None, "cycle": None, "created": now, "updated": now}
    d["tickets"].append(t)
    return t


# ---- drafts ----------------------------------------------------------------------------------------------------------------------
def draft_save(project, request, tickets):
    """Keep a draft (already checked or not: it is checked again here). Returns the draft {id, request, tickets, at}. The oldest draft goes when there
    are 50."""
    tk = validate_draft(tickets)
    req = check_request(request) if request else ""

    def go(d):
        n = d["next_draft"]
        d["next_draft"] = n + 1
        dr = {"id": f"d{n}", "request": req, "tickets": tk, "at": _now()}
        d["drafts"].append(dr)
        d["drafts"] = d["drafts"][-MAX_DRAFTS:]
        return dr
    return _modify(project, go)


def drafts(project):
    return load(project)["drafts"]


def draft_get(project, did):
    if not isinstance(did, str) or not DRAFT_OK.fullmatch(did):
        raise TicketError("a draft id looks like d1")
    for dr in load(project)["drafts"]:
        if dr.get("id") == did:
            return dr
    raise TicketError(f"no draft {did} for {project} (see: qtdeck ticket list {project})")


def draft_remove(project, did):
    draft_get(project, did)

    def go(d):
        d["drafts"] = [x for x in d["drafts"] if x.get("id") != did]
    _modify(project, go)


def draft_drop_ticket(project, did, index):
    """Take one ticket out of a draft (it was filed, or it duplicated something); the draft goes when it is empty."""
    def go(d):
        for dr in d["drafts"]:
            if dr.get("id") == did:
                if 0 <= index < len(dr["tickets"]):
                    del dr["tickets"][index]
                break
        d["drafts"] = [x for x in d["drafts"] if x.get("tickets")]
    _modify(project, go)


# ---- tickets -----------------------------------------------------------------------------------------------------------------------
def local_add(project, tickets, source="local", issues=None):
    """Store tickets as LOCAL tickets. `tickets` is a list of {title, body, acceptance}; each is checked. Returns the stored tickets.
    A title equal to one already stored is not added twice (it comes back as the existing ticket). `issues` (source "github" only) is a list of
    (number, url) pairs, one per ticket: how a ticket that was filed is remembered."""
    if source not in SOURCES:
        raise TicketError("source is local or github")
    cl = [validate_ticket(t) for t in tickets]
    if not cl:
        raise TicketError("no ticket to add")

    def go(d):
        out = []
        for i, c in enumerate(cl):
            same = next((t for t in d["tickets"] if norm_title(t["title"]) == norm_title(c["title"]) and t["source"] == source
                         and (source == "local" or (issues and t.get("issue") == issues[i][0]))), None)
            if same:
                out.append(same)
                continue
            if len(d["tickets"]) >= MAX_TICKETS:
                raise TicketError(f"{project} already has {MAX_TICKETS} tickets; remove some first")
            if source == "github":
                num, url = issues[i]
                out.append(_new_ticket(d, c, "github", _int(num), _url(url)))
            else:
                out.append(_new_ticket(d, c))
        return out
    return _modify(project, go)


def _int(v):
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 999999999:
        raise TicketError("an issue number is a whole number")
    return v


def _url(v):
    if v is None:
        return None
    if not isinstance(v, str) or not URL_OK.fullmatch(v):
        raise TicketError("a ticket url is a github.com issue or pull request address")
    return v


def get(project, n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise TicketError("a ticket id is a number")
    for t in load(project)["tickets"]:
        if t.get("id") == n:
            return t
    raise TicketError(f"no ticket {n} for {project} (see: qtdeck ticket list {project})")


def list(project):  # noqa: A001 - the name the callers use
    return load(project)["tickets"]


_FIELDS = ("title", "body", "acceptance", "requirements", "status", "source", "issue", "url", "branch", "cycle")


def update(project, n, **fields):
    """Change fields of one ticket. Only the fields above, each checked; anything else is refused. Returns the ticket."""
    bad = [k for k in fields if k not in _FIELDS]
    if bad:
        raise TicketError("a ticket has no field " + ", ".join(sorted(bad)))
    get(project, n)
    n = int(n)

    def go(d):
        t = next(x for x in d["tickets"] if x.get("id") == n)
        for k, v in fields.items():
            if k in ("title", "body", "acceptance"):
                t[k] = validate_ticket({"title": t["title"], "body": t["body"], "acceptance": t["acceptance"], k: v})[k]
            elif k == "requirements":
                t[k] = "" if v in ("", None) else clean(str(v).replace("<!--", "").replace("-->", ""), "the requirements", REQ_MAX, multiline=True, mentions=False, marks=False)
            elif k == "status":
                if v not in STATUSES:
                    raise TicketError("status is " + ", ".join(STATUSES))
                t[k] = v
            elif k == "source":
                if v not in SOURCES:
                    raise TicketError("source is local or github")
                t[k] = v
            elif k == "issue":
                t[k] = None if v is None else _int(v)
            elif k == "url":
                t[k] = _url(v)
            elif k == "branch":
                if v is not None and not (isinstance(v, str) and BRANCH_OK.fullmatch(v) and ".." not in v and "//" not in v and not v.endswith(("/", ".", ".lock"))):
                    raise TicketError("a branch is a plain branch name")
                t[k] = v
            elif k == "cycle":
                if v is not None and not (isinstance(v, str) and CYCLE_OK.fullmatch(v)):
                    raise TicketError("a cycle is an id of letters, digits, dot, dash and underscore")
                t[k] = v
        if t["source"] == "github" and t["issue"] is None:
            raise TicketError("a ticket filed on GitHub has an issue number")
        t["updated"] = _now()
        return t
    return _modify(project, go)


def remove(project, n):
    get(project, n)

    def go(d):
        d["tickets"] = [t for t in d["tickets"] if t.get("id") != int(n)]
    _modify(project, go)


# ---- text for people and for the model --------------------------------------------------------------------------------------------
def issue_body(t):
    """The GitHub issue body of a ticket (a draft entry or a stored ticket): its body, then the acceptance checks as a checklist."""
    return t["body"] + "\n\n## Acceptance checks\n\n" + "\n".join(f"- [ ] {a}" for a in t["acceptance"]) + "\n"


def issues_json(project, did):
    """What would be filed from a draft, as the array bin/lib.sh file_issues takes: [{title, body, labels: []}]."""
    return [{"title": t["title"], "body": issue_body(t), "labels": []} for t in draft_get(project, did)["tickets"]]


def ticket_text(t):
    """The ticket as the model reads it (always inside an untrusted block): title, body, acceptance checks, and the purser's requirements if any."""
    s = f"Ticket #{t['id']}: {t['title']}\n\n{t['body']}\n\nAcceptance checks:\n" + "\n".join(f"- {a}" for a in t["acceptance"]) + "\n"
    if t.get("requirements"):
        s += "\nRequirements:\n" + t["requirements"] + "\n"
    return s


def line(t):
    where = f"GitHub issue #{t['issue']}" if t.get("issue") else "local"
    extra = f"  branch {t['branch']}" if t.get("branch") else ""
    return f"  {t['id']:>3}  {t['status']:<8} {where:<18} {t['title']}{extra}"


def stack_context(project):
    """What the drafting model is told about the project, from the attach profile (state/profiles) and the registry: the stack sentence and
    the commands. Facts only; empty strings when the project was never scanned."""
    h = home()
    out = {"stack": "", "commands": []}
    try:
        prof = json.loads((h / "state" / "profiles" / f"{_project(project)}.json").read_text())
        st = prof.get("stack") or {}
        out["stack"] = str(st.get("summary") or "")[:300]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        ent = json.loads((h / "config" / "projects.json").read_text()).get(project) or {}
        for k in ("verify", "test", "build", "lint", "typecheck"):
            v = ent.get(k)
            if isinstance(v, str) and v:
                out["commands"].append(f"{k}: {v[:200]}")
    except (OSError, ValueError, AttributeError):
        pass
    return out


def context_text(project):
    c = stack_context(project)
    d = load(project)
    s = "Stack: " + (c["stack"] or "(not scanned)") + "\n"
    s += "Commands the harness runs to prove a change: " + ("; ".join(c["commands"]) or "(none set)") + "\n"
    s += "Local tickets already on this computer (do not repeat them):\n"
    s += "\n".join(f"- {t['title']}" for t in d["tickets"]) or "(none)"
    s += "\nDrafts waiting to be filed (do not repeat them):\n"
    s += "\n".join(f"- {t['title']}" for dr in d["drafts"] for t in dr["tickets"]) or "(none)"
    return s


def dedupe(project, did, tracker):
    """Take out of a draft every ticket whose title is already on the tracker (`tracker`: "#n [STATE] title" lines, as bin/lib.sh existing_issues prints
    them). Returns one line per ticket taken out: "#n title"."""
    seen = {}
    for ln in tracker.splitlines():
        m = re.match(r"#(\d+) \[[A-Za-z_]+\] (.*)$", ln)
        if m:
            seen.setdefault(norm_title(m.group(2)), int(m.group(1)))
    gone = []
    for i, t in reversed(_LIST(enumerate(draft_get(project, did)["tickets"]))):
        n = seen.get(norm_title(t["title"]))
        if n:
            gone.append(f"#{n} {t['title']}")
            draft_drop_ticket(project, did, i)
    return gone[::-1]


# ---- the command line --------------------------------------------------------------------------------------------------------------
def _fail(msg, code=2):
    print(f"  {msg}", file=sys.stderr)
    return code


def _show_draft(dr, project):
    print(f"  draft {dr['id']}  ({len(dr['tickets'])} ticket{'s' if len(dr['tickets']) != 1 else ''})  asked: {dr['request'][:100]!r}")
    for i, t in enumerate(dr["tickets"], 1):
        print(f"\n  {i}. {t['title']}")
        for ln in t["body"].splitlines():
            print(f"       {ln}")
        print("       Acceptance checks:")
        for a in t["acceptance"]:
            print(f"         - {a}")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, a = argv[0], argv[1:]
    try:
        if cmd == "list" and len(a) == 1:
            d = load(a[0])
            if not d["tickets"] and not d["drafts"]:
                print(f"  no tickets or drafts yet for {a[0]}")
                print(f"  next: qtdeck ticket new {a[0]} \"what you want built\"")
                return 0
            for t in d["tickets"]:
                print(line(t))
            for dr in d["drafts"]:
                print(f"  {dr['id']:>4}  draft    {len(dr['tickets'])} ticket(s), nothing filed   {'; '.join(t['title'] for t in dr['tickets'])[:90]}")
            return 0
        if cmd == "drafts" and len(a) == 1:
            for dr in drafts(a[0]):
                print(f"{dr['id']}\t{len(dr['tickets'])}\t{dr['at']}\t{dr['request'][:80]}")
            return 0
        if cmd == "show":
            js, bare = "--json" in a, "--bare" in a
            a = [x for x in a if x not in ("--json", "--bare")]
            if len(a) != 2:
                return _fail("usage: tickets.py show [--json] <project> <id|dN>")
            if DRAFT_OK.fullmatch(a[1]):
                dr = draft_get(a[0], a[1])
                if js:
                    print(json.dumps(dr))
                else:
                    _show_draft(dr, a[0])
                    if not bare:
                        print(f"\n  nothing is filed. To file it: qtdeck ticket file {a[0]} {dr['id']} --apply")
                return 0
            t = get(a[0], a[1])
            if js:
                print(json.dumps(t))
                return 0
            print(line(t))
            print(f"\n  {t['body']}\n\n  Acceptance checks:")
            for c in t["acceptance"]:
                print(f"    - {c}")
            if t.get("requirements"):
                print("\n  Requirements (written by the purser):\n" + "\n".join("    " + x for x in t["requirements"].splitlines()))
            if t.get("url"):
                print(f"\n  {t['url']}")
            if t["source"] == "local" and t["status"] == "open":
                print(f"\n  next: qtdeck cycle {a[0]} --ticket {t['id']}")
            elif t.get("branch"):
                print(f"\n  review it: git diff <base>...{t['branch']}   (qtdeck cycle --status shows the exact command)")
            return 0
        if cmd == "file" and len(a) >= 2:
            project, did = a[0], a[1]
            dr = draft_get(project, did)
            if "--apply" not in a[2:]:
                print(f"  would save {len(dr['tickets'])} local ticket(s) from draft {did}:")
                for t in dr["tickets"]:
                    print(f"    - {t['title']}")
                print(f"  nothing was changed. To do it: python3 bin/tickets.py file {project} {did} --apply")
                return 0
            made = local_add(project, dr["tickets"])
            draft_remove(project, did)
            for t in made:
                print(f"  ticket {t['id']}: {t['title']}")
            return 0
        if cmd == "remove-draft" and len(a) == 2:
            draft_remove(a[0], a[1])
            print(f"  draft {a[1]} removed")
            return 0
        # ---- helpers for the shell (not for people) ----
        if cmd == "check-request" and len(a) == 0:               # the request on stdin -> the cleaned request, or an error
            sys.stdout.write(check_request(sys.stdin.read(REQUEST_MAX * 4 + 1)))
            return 0
        if cmd == "validate" and len(a) == 0:                    # the model's TICKETS_JSON on stdin -> the cleaned {"tickets": [...]}
            try:
                obj = json.loads(sys.stdin.read(200000))
            except ValueError:
                return _fail("the reply's TICKETS_JSON is not JSON")
            print(json.dumps({"tickets": validate_draft(obj)}))
            return 0
        if cmd == "draft-save" and len(a) == 2:                  # <project> <request-file>; the cleaned tickets JSON on stdin -> the draft id
            req = Path(a[1]).read_text() if a[1] != "-" else ""
            print(draft_save(a[0], req, json.loads(sys.stdin.read(200000)))["id"])
            return 0
        if cmd == "context" and len(a) == 1:
            print(context_text(a[0]))
            return 0
        if cmd == "text" and len(a) == 2:
            sys.stdout.write(ticket_text(get(a[0], a[1])))
            return 0
        if cmd == "issues-json" and len(a) == 2:
            print(json.dumps(issues_json(a[0], a[1])))
            return 0
        if cmd == "draft-titles" and len(a) == 2:
            for t in draft_get(a[0], a[1])["tickets"]:
                print(t["title"])
            return 0
        if cmd == "drop-draft-ticket" and len(a) == 3:
            draft_drop_ticket(a[0], a[1], int(a[2]))
            return 0
        if cmd == "record-filed" and len(a) == 5:                # <project> <draft> <issue> <url> <title>: a ticket that went to GitHub is remembered, then leaves the draft
            project, did, title = a[0], a[1], a[4]
            dr = draft_get(project, did)
            idx = next((i for i, t in enumerate(dr["tickets"]) if t["title"] == title), None)
            if idx is None:
                return _fail(f"draft {did} has no ticket titled that")
            local_add(project, [dr["tickets"][idx]], source="github", issues=[(int(a[2]), a[3])])
            draft_drop_ticket(project, did, idx)
            return 0
        if cmd == "dedupe" and len(a) == 2:                      # <project> <draft>; "#n [STATE] title" lines of the tracker on stdin
            print("\n".join(dedupe(a[0], a[1], sys.stdin.read(400000))))
            return 0
        if cmd == "set" and len(a) >= 3:                         # <project> <n> field=value ... (the shell's way to update; requirements come on stdin: field "requirements=-")
            fields = {}
            for kv in a[2:]:
                k, _, v = kv.partition("=")
                if k == "requirements" and v == "-":
                    v = sys.stdin.read(REQ_MAX * 4 + 1)
                fields[k] = None if v == "" and k in ("branch", "cycle", "url", "issue") else (int(v) if k == "issue" else v)
            update(a[0], a[1], **fields)
            return 0
    except TicketError as e:
        return _fail(str(e))
    except (OSError, ValueError, IndexError) as e:
        return _fail(f"{type(e).__name__}: {e}")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
