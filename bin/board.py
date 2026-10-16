#!/usr/bin/env python3
"""GitHub Projects plumbing, kept out of the duty that uses it.

The join this does — board items against the issues and pull requests they
claim to represent — is awkward in jq and clear in thirty lines of Python, so it
lives here and `duties/harbourmaster.sh` stays about the model call, the
contract, and the writes it authorises.

This is harness code, not model code. It performs the board edits a parsed
contract asked for; it never decides what to edit.

  board.py snapshot <owner> <number> <repo>          -> JSON on stdout
  board.py text     <owner> <number> <repo>          -> the same, for a prompt
  board.py move     <owner> <number> <item-id> <field> <option>
  board.py to       <owner> <number> <issue> <want> [status-map-json] [only-from]
                    moves an issue's card to a column, by meaning (ready, doing,
                    review, todo, done) or by name; prints the column it left
  board.py add      <owner> <number> <issue-url>     -> adds, returns the item id
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


def gh(*args, check=True):
    """Run gh, falling back to the login that actually has `project` scope.

    A GITHUB_TOKEN in the environment overrides `gh auth login`, and a classic
    token without `project` cannot see a board at all — it reports "unknown
    owner type", not a scope error, so there is no reliable message to match on.
    Rather than telling someone to unset a variable the rest of their shell
    depends on, retry any failure once with the keyring login instead.
    """
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0 and "GITHUB_TOKEN" in os.environ:
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        r = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        # Raised, not sys.exit: the dashboard imports this module, and SystemExit
        # would pass its `except Exception` and stop the whole server.
        raise BoardError(f"board: gh {' '.join(args[:3])} failed: {(r.stderr or '').strip()[:400]}")
    return r.stdout


class BoardError(Exception):
    pass


# What each Status column means on THIS board. The registry may name it
# (board.status in projects.json); otherwise the board's own option names are
# matched. A column that cannot be identified comes back empty, and whatever
# needs it does nothing rather than guess.
MEANING = {"todo": r"^backlog|^todo|^triage", "ready": r"^ready", "doing": r"progress|doing",
           "review": r"review", "done": r"^done|complete|shipped"}


def column(options, want, named=None):
    """The option `want` refers to: a meaning ("ready") or a column's own name."""
    if want in (named or {}):
        return named[want]
    if want in MEANING:
        return next((o for o in options if re.search(MEANING[want], o, re.I)), "")
    return next((o for o in options if o.lower() == want.lower()), "")


def jgh(*args):
    out = gh(*args)
    return json.loads(out) if out.strip() else {}


def days_since(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - d).total_seconds() // 86400)
    except Exception:
        return None


def snapshot(owner, number, repo, named=None):
    """The board, joined to what the repository actually says."""
    items = jgh("project", "item-list", number, "--owner", owner,
                "--limit", "500", "--format", "json").get("items", [])
    fields = jgh("project", "field-list", number, "--owner", owner,
                 "--format", "json").get("fields", [])
    issues = jgh("issue", "list", "-R", repo, "--state", "all", "--limit", "400",
                 "--json", "number,state,title,updatedAt,labels")
    prs = jgh("pr", "list", "-R", repo, "--state", "all", "--limit", "150", "--json",
              "number,state,title,updatedAt,isDraft,closingIssuesReferences")

    issue_by_num = {i["number"]: i for i in issues}
    pr_by_num = {p["number"]: p for p in prs}
    # Which pull requests claim to close which issue — the link that decides
    # whether an issue is genuinely in review.
    prs_for_issue = {}
    for p in prs:
        for ref in p.get("closingIssuesReferences") or []:
            prs_for_issue.setdefault(ref["number"], []).append(p)

    rows = []
    on_board = set()
    for it in items:
        c = it.get("content") or {}
        num = c.get("number")
        row = {
            "item_id": it.get("id"),
            "status": it.get("status"),
            "priority": it.get("priority"),
            "size": it.get("size"),
            "number": num,
            "type": c.get("type"),
            "title": it.get("title") or c.get("title"),
            "url": c.get("url"),
        }
        if num:
            on_board.add((c.get("type"), num))
            src = issue_by_num.get(num) if c.get("type") == "Issue" else pr_by_num.get(num)
            if src:
                row["state"] = src.get("state")
                row["idle_days"] = days_since(src.get("updatedAt"))
                row["labels"] = [l["name"] for l in src.get("labels", [])] if src.get("labels") else []
            else:
                row["state"] = "NOT FOUND IN REPO"
            row["open_prs"] = [
                {"number": p["number"], "state": p["state"], "draft": p.get("isDraft")}
                for p in prs_for_issue.get(num, []) if p["state"] == "OPEN"
            ]
        rows.append(row)

    missing = [
        {"number": i["number"], "type": "Issue", "title": i["title"],
         "url": f"https://github.com/{repo}/issues/{i['number']}",
         "idle_days": days_since(i.get("updatedAt"))}
        for i in issues
        if i["state"] == "OPEN" and ("Issue", i["number"]) not in on_board
    ]
    status = [o["name"] for f in fields if f["name"] == "Status" for o in f.get("options", [])]
    return {
        "owner": owner, "number": number, "repo": repo,
        "columns": {m: column(status, m, named) for m in MEANING},
        "fields": [
            {"name": f["name"], "id": f["id"],
             "options": [{"name": o["name"], "id": o["id"]} for o in f.get("options", [])]}
            for f in fields if f.get("options")
        ],
        "items": rows,
        "missing_from_board": missing,
    }


def move(owner, number, item_id, field, option):
    fields = jgh("project", "field-list", number, "--owner", owner,
                 "--format", "json").get("fields", [])
    f = next((x for x in fields if x["name"].lower() == field.lower()), None)
    if not f:
        raise BoardError(f"board: no field called {field}")
    o = next((x for x in f.get("options", []) if x["name"].lower() == option.lower()), None)
    if not o:
        raise BoardError(f"board: {field} has no option {option}")
    pid = jgh("project", "view", number, "--owner", owner, "--format", "json")["id"]
    gh("project", "item-edit", "--id", item_id, "--project-id", pid,
       "--field-id", f["id"], "--single-select-option-id", o["id"])


def as_text(s):
    """The snapshot as a prompt reads it: one line per item, facts only."""
    out = [f'BOARD: {s["repo"]} project #{s["number"]} — {len(s["items"])} item(s)']
    for f in s["fields"]:
        out.append(f'  field {f["name"]}: ' + " | ".join(o["name"] for o in f["options"]))
    out.append("")
    by_status = {}
    for r in s["items"]:
        by_status.setdefault(r.get("status") or "(no status)", []).append(r)
    for status, rows in sorted(by_status.items()):
        out.append(f"[{status}] — {len(rows)} item(s)")
        for r in rows:
            if not r.get("number"):
                out.append(f'  (draft) {r["title"]}')
                continue
            bits = [f'{r.get("state", "?")}']
            if r.get("priority"):
                bits.append(r["priority"])
            if r.get("size"):
                bits.append(r["size"])
            if r.get("open_prs"):
                bits.append("open PR " + ", ".join(
                    f'#{p["number"]}' + (" draft" if p["draft"] else "") for p in r["open_prs"]))
            if r.get("idle_days") is not None:
                bits.append(f'idle {r["idle_days"]}d')
            out.append(f'  {r["type"]} #{r["number"]} [{r["item_id"]}] {r["title"][:90]} — ' + ", ".join(bits))
        out.append("")
    if s["missing_from_board"]:
        out.append(f'NOT ON THE BOARD — {len(s["missing_from_board"])} open issue(s)')
        for m in s["missing_from_board"]:
            out.append(f'  Issue #{m["number"]} {m["title"][:90]} — idle {m["idle_days"]}d')
    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd in ("snapshot", "text"):
        owner, number, repo = sys.argv[2], sys.argv[3], sys.argv[4]
        s = snapshot(owner, number, repo)
        print(json.dumps(s, indent=2) if cmd == "snapshot" else as_text(s))
    elif cmd == "move":
        owner, number, item_id, field, option = sys.argv[2:7]
        move(owner, number, item_id, field, option)
        print(f'{item_id} {field}={option}')
    elif cmd == "to":
        owner, number, issue, want = sys.argv[2:6]
        arg = sys.argv[6] if len(sys.argv) > 6 else ""
        named = json.loads(arg) if arg.startswith("{") else {}
        only = sys.argv[7] if len(sys.argv) > 7 else ""
        # Nothing here is fatal to the caller: a card that cannot be moved is
        # said so on stderr and prints nothing, so the work it was moved for
        # still happens.
        items = jgh("project", "item-list", number, "--owner", owner,
                    "--limit", "500", "--format", "json").get("items", [])
        it = next((i for i in items if (i.get("content") or {}).get("type") == "Issue"
                   and (i.get("content") or {}).get("number") == int(issue)), None)
        if not it:
            return print(f"board: #{issue} is not on the board", file=sys.stderr)
        fields = jgh("project", "field-list", number, "--owner", owner,
                     "--format", "json").get("fields", [])
        opts = [o["name"] for f in fields if f["name"] == "Status" for o in f.get("options", [])]
        here, to = it.get("status") or "", column(opts, want, named)
        if not to:
            return print(f"board: no column for '{want}' on this board, card left alone", file=sys.stderr)
        if only and here != column(opts, only, named):
            return print(f"board: #{issue} is in '{here}', not '{column(opts, only, named)}', card left alone",
                         file=sys.stderr)
        if here != to:
            move(owner, number, it["id"], "Status", to)
        print(here)
    elif cmd == "add":
        owner, number, url = sys.argv[2], sys.argv[3], sys.argv[4]
        out = jgh("project", "item-add", number, "--owner", owner, "--url", url, "--format", "json")
        print(out.get("id", ""))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main()
    except BoardError as e:
        sys.exit(str(e))
