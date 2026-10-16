#!/usr/bin/env python3
"""Sprint-plan plumbing, kept out of the duty that uses it (duties/planner.sh).

Harness code, not model code. The model proposes an order, sizes and a split; everything
here checks that proposal, prices it from the project's own measured runs, writes the
document, and (only after a person approved it) asks the board keeper's own `board.py to`
to move the cards. Nothing here creates or edits an issue.

  plan.py eligible <snapshot.json>                  open Backlog/Ready issue numbers
  plan.py context  <snapshot.json> <issues.jsonl> <home> <project>      -> context JSON
  plan.py check    <context.json> <capacity|-> <budget|->   (model's PLAN_JSON on stdin)
                                                    -> the checked plan JSON, or errors on stderr (exit 1)
  plan.py render   <plan.json>                      -> the document (markdown)
  plan.py save     <home> <plan.json>               -> writes workspace doc + state/plans/<id>.json
  plan.py approve  <home> <project> <plan-id>
  plan.py apply    <home> <project> <plan-id> <owner> <number> <repo> <status-map-json|-> [--apply]
  plan.py list     <home> <project>
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SIZES = ("S", "M", "L")
BODY_MAX = 2000
REQ_MARK = "<!-- quarterdeck:requirements -->"
REFERENCE = ("No run of this project is measured yet, so every cost below is unknown. The only measured "
             "reference is from a different project: the first full cycle on a fixture cost about 7.4 "
             "dollars for a one-button change. That is a reference from a different project, not an estimate for this one.")


class PlanError(Exception):
    pass


def _id_ok(s):
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", s or ""))


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) if not isinstance(obj, str) else obj)
    tmp.replace(path)


# ---- what can be planned ---------------------------------------------------------------------
def eligible(snap, cap=None):
    """Open issues in Backlog or Ready, in board order."""
    cols = snap.get("columns") or {}
    want = {c for c in (cols.get("todo"), cols.get("ready")) if c}
    out = [i for i in snap.get("items", [])
           if i.get("type") == "Issue" and i.get("number") and i.get("state") == "OPEN" and i.get("status") in want]
    return out[:cap] if cap else out


def known(snap):
    k = {i["number"]: {"state": i.get("state"), "status": i.get("status"), "title": i.get("title", "")}
         for i in snap.get("items", []) if i.get("number") and i.get("type") in (None, "Issue")}
    for m in snap.get("missing_from_board", []):
        k.setdefault(m["number"], {"state": "OPEN", "status": None, "title": m.get("title", "")})
    return k


# ---- cost: measured runs only ----------------------------------------------------------------
def _plans(home, project):
    out = []
    for f in sorted((Path(home) / "state" / "plans").glob("*.json")):
        try:
            p = json.loads(f.read_text())
        except Exception:
            continue
        if p.get("project") == project:
            out.append(p)
    return out


def costs(home, project):
    """Finished cycle records (state/cycles) and fix runs (spend ledger) of THIS project.
    A cycle on an issue that an approved plan sized is filed under that size."""
    sized = {}
    for p in _plans(home, project):
        if p.get("approved_at"):
            for it in p.get("plan", []):
                sized[it["issue"]] = it["size"]
    runs = []
    for f in sorted((Path(home) / "state" / "cycles").glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        if r.get("kind") == "cycle" and r.get("project") == project and r.get("finished") and (r.get("cost") or 0) > 0:
            runs.append({"what": f"cycle on #{r.get('issue')}", "cost": float(r["cost"]), "size": sized.get(r.get("issue"))})
    fixes = {}
    try:
        for line in (Path(home) / "state" / "spend.jsonl").read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            k = row.get("fix") or ""
            if row.get("project") == project and k and not k.startswith("cycle:"):
                fixes[k] = fixes.get(k, 0) + float(row.get("cost") or 0)
    except OSError:
        pass
    runs += [{"what": f"fix {k}", "cost": c, "size": None} for k, c in fixes.items() if c > 0]
    return runs


def expected(size, runs):
    """{low, high, n, basis} for one item of this size, or None when nothing is measured."""
    by = [r["cost"] for r in runs if r["size"] == size]
    pool, basis = (by, "size") if by else ([r["cost"] for r in runs], "all")
    if not pool:
        return None
    return {"low": min(pool), "high": max(pool), "n": len(pool), "basis": basis}


def money(c):
    if c is None:
        return "unknown (no measurement yet)"
    lo, hi = c["low"], c["high"]
    n = f"{c['n']} measured run{'s' if c['n'] != 1 else ''} of this project"
    pooled = "" if c.get("basis", "size") == "size" else ", not specific to this size"
    return (f"about ${lo:.2f} ({n}{pooled})" if abs(hi - lo) < 0.005 else f"${lo:.2f} to ${hi:.2f} ({n}{pooled})")


# ---- the model's input -----------------------------------------------------------------------
def context(snap, issues, home, project, cap=30):
    items = []
    k = known(snap)
    for i in eligible(snap, cap):
        n = i["number"]
        iss = issues.get(n) or {}
        body = (iss.get("body") or "")
        mentions = sorted({int(m) for m in re.findall(r"#(\d+)", (iss.get("title") or "") + " " + body)} - {n})
        items.append({"n": n, "title": iss.get("title") or i.get("title") or "", "status": i["status"],
                      "labels": [l["name"] if isinstance(l, dict) else l for l in (iss.get("labels") or i.get("labels") or [])],
                      "has_requirements": REQ_MARK in body, "mentions": [m for m in mentions if m in k],
                      "body": body[:BODY_MAX]})
    runs = costs(home, project)
    per = {s: expected(s, runs) for s in SIZES}
    lines = []
    for it in items:
        lines.append(f"#{it['n']} [{it['status']}] {it['title']}\n  labels: {', '.join(it['labels']) or 'none'}; "
                     f"requirements block from the purser: {'yes' if it['has_requirements'] else 'no'}; "
                     f"other issues mentioned: {', '.join('#%d' % m for m in it['mentions']) or 'none'}\n"
                     + "\n".join("  | " + l for l in it["body"].splitlines()))
    kn = "\n".join(f"#{n} {v['state']} ({v['status'] or 'not on the board'}) {v['title'][:80]}"
                   for n, v in sorted(k.items()) if n not in {i['n'] for i in items})
    if runs:
        cost_text = ("Measured cost of finished runs of THIS project (the harness prices the plan from these; "
                     "you never write a dollar figure):\n" +
                     "\n".join(f"  {r['what']}: ${r['cost']:.2f}" + (f" (planned size {r['size']})" if r["size"] else "") for r in runs[-12:]) +
                     "\nExpected cost per item, by size: " + "; ".join(f"{s} {money(c)}" for s, c in per.items()))
    else:
        cost_text = "No run of this project is measured yet. Do not write any dollar figure; cost is unknown."
    return {"project": project, "items": items, "known": {str(n): v for n, v in k.items()},
            "columns": snap.get("columns") or {}, "runs": runs, "has_cost": bool(runs),
            "board_text": "\n\n".join(lines) + ("\n\nOTHER ISSUES ON THE BOARD OR OPEN (not plannable, for dependencies):\n" + kn if kn else ""),
            "cost_text": cost_text}


# ---- the check ---------------------------------------------------------------------------------
def check(ctx, raw, capacity=None, budget=None):
    """Validate the model's PLAN_JSON and turn it into the plan. Raises PlanError listing every fault."""
    errs = []
    if not isinstance(raw, dict) or not isinstance(raw.get("plan"), list) or not isinstance(raw.get("sprint"), list):
        raise PlanError("the reply is not an object with a 'plan' list and a 'sprint' list")
    elig = {it["n"]: it for it in ctx["items"]}
    kn = {int(n): v for n, v in ctx["known"].items()}
    kn.update({n: {"state": "OPEN", "status": it["status"], "title": it["title"]} for n, it in elig.items()})
    cols = ctx["columns"]
    if budget is not None and not ctx["has_cost"]:
        raise PlanError("a budget needs measured cost and this project has none; use a capacity instead")

    def num(v, what):
        if isinstance(v, bool) or not isinstance(v, int):
            errs.append(f"{what}: '{v}' is not an issue number")
            return None
        return v

    plan, seen = [], set()
    for e in raw["plan"]:
        if not isinstance(e, dict):
            errs.append("a plan entry is not an object")
            continue
        n = num(e.get("issue"), "plan")
        if n is None:
            continue
        if n in seen:
            errs.append(f"#{n} appears twice in the plan")
        seen.add(n)
        if n not in kn:
            errs.append(f"#{n} is not on the board or in the open issues (unknown issue)")
        elif kn[n]["state"] != "OPEN":
            errs.append(f"#{n} is closed and cannot be planned")
        elif n not in elig:
            errs.append(f"#{n} is not in Backlog or Ready")
        if e.get("size") not in SIZES:
            errs.append(f"#{n}: size '{e.get('size')}' is not S, M or L")
        if not isinstance(e.get("reason"), str) or not e["reason"].strip():
            errs.append(f"#{n}: a size needs a one-sentence reason")
        if not isinstance(e.get("parallel_ok"), bool):
            errs.append(f"#{n}: parallel_ok must be true or false")
        deps = e.get("depends_on", [])
        if not isinstance(deps, list):
            errs.append(f"#{n}: depends_on must be a list")
            deps = []
        for d in deps:
            if num(d, f"#{n} depends_on") is None:
                continue
            if d not in kn:
                errs.append(f"#{n} depends on #{d}, which is not a known issue")
            elif d == n:
                errs.append(f"#{n} depends on itself")
        plan.append({"issue": n, "size": e.get("size"), "reason": str(e.get("reason", "")).strip()[:400],
                     "depends_on": [d for d in deps if isinstance(d, int) and not isinstance(d, bool)],
                     "parallel_ok": e.get("parallel_ok") is True,
                     "needs_decision": str(e.get("needs_decision") or "").strip()[:400],
                     "why_now": str(e.get("why_now") or "").strip()[:400]})
    order = [p["issue"] for p in plan]
    # dependency cycles, and an order that puts every dependency first (stable: the model's order wins otherwise)
    pos = {n: i for i, n in enumerate(order)}
    done, topo = set(), []
    while len(topo) < len(order):
        nxt = next((n for n in order if n not in done and all(d in done or d not in pos or d == n for d in plan[pos[n]]["depends_on"])), None)
        if nxt is None:
            errs.append("dependency cycle among " + ", ".join("#%d" % n for n in order if n not in done))
            break
        done.add(nxt)
        topo.append(nxt)
    sprint_raw = [num(s, "sprint") for s in raw["sprint"]]
    for s in sprint_raw:
        if s is not None and s not in pos:
            errs.append(f"sprint item #{s} is not in the plan")
    left = raw.get("left_out") or []
    if not isinstance(left, list):
        errs.append("left_out must be a list")
        left = []
    for l in left:
        n = num(l.get("issue"), "left_out") if isinstance(l, dict) else None
        if n is not None and n not in kn:
            errs.append(f"left_out #{n} is not a known issue")
        elif n in pos:
            errs.append(f"#{n} is both in the plan and left out")
    if errs:
        raise PlanError("\n".join(errs))

    reordered = topo != order
    by = {p["issue"]: p for p in plan}
    plan = [by[n] for n in topo]
    for p in plan:
        p["title"] = elig[p["issue"]]["title"]
        p["from_status"] = elig[p["issue"]]["status"]
        p["cost"] = expected(p["size"], ctx["runs"])
    # the sprint: the model's pick, then what the harness will not stand behind
    S = [p["issue"] for p in plan if p["issue"] in set(sprint_raw)]
    later = {}
    for p in plan:
        if p["issue"] in S and p["needs_decision"]:
            S.remove(p["issue"])
            later[p["issue"]] = "needs a decision before it can start: " + p["needs_decision"]
    changed = True
    while changed:
        changed = False
        for p in plan:
            n = p["issue"]
            if n not in S:
                continue
            for d in p["depends_on"]:
                v = kn[d]
                if v["state"] == "OPEN" and d not in S and (d in elig):
                    S.remove(n)
                    later[n] = f"waits on #{d}, which is not in this sprint"
                    changed = True
                    break
    if capacity is not None and len(S) > capacity:
        for n in S[capacity:]:
            later[n] = f"over the capacity of {capacity} item(s)"
        S = S[:capacity]
    if budget is not None:
        total, keep = 0.0, []
        for n in S:
            hi = by[n]["cost"]["high"]
            if total + hi > budget + 1e-9:
                break
            total += hi
            keep.append(n)
        for n in S[len(keep):]:
            later[n] = f"over the budget of ${budget:.2f} (counting the high end of each measured range)"
        S = keep
    for p in plan:
        if p["issue"] not in S:
            later.setdefault(p["issue"], "needs a decision before it can start: " + p["needs_decision"] if p["needs_decision"]
                             else "planned for a later sprint")
    placed = set(pos)
    lo = {int(l["issue"]): str(l.get("reason") or "").strip()[:400] for l in left}
    left_out = [{"issue": n, "title": elig[n]["title"],
                 "reason": lo.get(n) or "the planner did not place it and gave no reason"} for n in elig if n not in placed]
    costs_known = [by[n]["cost"] for n in S]
    total = ({"low": sum(c["low"] for c in costs_known), "high": sum(c["high"] for c in costs_known)}
             if S and all(costs_known) else None)
    now = datetime.now(timezone.utc)
    return {"id": f"{ctx['project']}-{now:%Y%m%d-%H%M%S}", "project": ctx["project"], "created": now.strftime("%FT%TZ"),
            "status": "proposed", "capacity": capacity, "budget": budget, "reordered": reordered,
            "measured_runs": len(ctx["runs"]), "columns": cols, "plan": plan, "sprint": S,
            "later": [{"issue": n, "reason": later[n]} for n in [p["issue"] for p in plan] if n in later],
            "left_out": left_out, "total_cost": total, "moves": []}


# ---- the document ------------------------------------------------------------------------------
def render(p):
    by = {x["issue"]: x for x in p["plan"]}
    o = [f"# {p['project']} — sprint plan {p['created'][:10]}", "",
         f"Plan `{p['id']}` · status **{p['status']}** · {len(p['sprint'])} item(s) in the sprint of {len(p['plan'])} planned. "
         "Written by the planner (the model's judgement); costs are priced by the harness. Nothing on the board or in GitHub has changed.", ""]
    if p["capacity"] is not None or p["budget"] is not None:
        o += ["Asked for: " + ", ".join(x for x in (f"capacity {p['capacity']} item(s)" if p["capacity"] is not None else "",
                                                     f"budget ${p['budget']:.2f} of expected model cost" if p["budget"] is not None else "") if x) + ".", ""]
    o += ["## Cost, and where it comes from", ""]
    if p["measured_runs"]:
        o += [f"Priced from {p['measured_runs']} finished run(s) of this project (cycle records and fix runs). Sizes are "
              "matched to runs only where an approved plan sized that issue; otherwise the range pools all runs and says so."]
    else:
        o += [REFERENCE]
    t = p["total_cost"]
    o += ["", "Expected cost of the sprint: **" + ((f"about ${t['low']:.2f}" if abs(t["high"] - t["low"]) < 0.005 else f"${t['low']:.2f} to ${t['high']:.2f}") if t else "unknown (no measurement yet)") + "**", ""]
    o += ["## The sprint, in order", ""]
    for i, n in enumerate(p["sprint"], 1):
        x = by[n]
        o += [f"### {i}. #{n} {x['title']} — {x['size']}", "", f"- **Why this size:** {x['reason']}",
              f"- **Expected cost:** {money(x['cost'])}", f"- **Why now:** {x['why_now'] or '(not given)'}",
              f"- **Depends on:** {', '.join('#%d' % d for d in x['depends_on']) or 'nothing'}",
              f"- **Card:** {x['from_status']} → Ready" + (" (already there, no move)" if x["from_status"] == (p['columns'] or {}).get("ready") else ""), ""]
    if not p["sprint"]:
        o += ["Nothing fits the sprint.", ""]
    par = [n for n in p["sprint"] if by[n]["parallel_ok"]]
    o += ["## What could run in parallel", "", (", ".join("#%d" % n for n in par) + " may be worked at the same time as the others, "
          "where no dependency above orders them.") if par else "Nothing is marked as safe to run alongside the rest.", ""]
    dec = [x for x in p["plan"] if x["needs_decision"]]
    o += ["## Decisions needed from you", ""]
    o += [f"- **#{x['issue']} {x['title']}:** {x['needs_decision']}" for x in dec] or ["None."]
    o += ["", "## Planned, but not in this sprint", ""]
    o += [f"- **#{l['issue']} {by[l['issue']]['title']}** ({by[l['issue']]['size']}, {money(by[l['issue']]['cost'])}): {l['reason']}"
          for l in p["later"] if l["issue"] not in p["sprint"]] or ["None."]
    o += ["", "## Left out", ""]
    o += [f"- **#{l['issue']} {l['title']}:** {l['reason']}" for l in p["left_out"]] or ["None."]
    if p["reordered"]:
        o += ["", "_The planner's order put an item before something it depends on; the harness moved the dependency first._"]
    o += ["", "## To go ahead", "", f"1. `quarterdeck plan approve {p['project']} {p['id']}`",
          f"2. `quarterdeck plan apply {p['project']} {p['id']}` lists the card moves; add `--apply` to make them.", "",
          "Only the sprint's cards move (Backlog to Ready), one at a time, and a card that has moved since this plan was made is left alone. "
          "No issue is created or edited."]
    return "\n".join(o) + "\n"


# ---- state -------------------------------------------------------------------------------------
def _path(home, pid):
    if not _id_ok(pid):
        raise PlanError("that is not a plan id")
    return Path(home) / "state" / "plans" / f"{pid}.json"


def load(home, project, pid):
    f = _path(home, pid)
    if not f.exists():
        raise PlanError(f"no plan called {pid}")
    p = json.loads(f.read_text())
    if p.get("project") != project:
        raise PlanError(f"{pid} belongs to {p.get('project')}, not {project}")
    return p


def save(home, p):
    for old in _plans(home, p["project"]):
        if old["status"] in ("proposed", "approved") and not old.get("moves"):
            old["status"] = "superseded"
            _write(_path(home, old["id"]), old)
    doc = Path(home) / "workspace" / f"{p['project']}-plan-{p['created'][:10]}.md"
    if doc.exists():
        doc = doc.with_name(doc.stem + f"-{p['created'][11:19].replace(':', '')}.md")
    p["doc"] = str(doc)
    _write(doc, render(p))
    _write(_path(home, p["id"]), p)
    return doc


def approve(home, project, pid):
    """The owner's yes. Callable from the dashboard later; returns the plan."""
    p = load(home, project, pid)
    if p["status"] == "superseded":
        raise PlanError(f"{pid} was superseded by a newer plan; approve that one")
    if p["status"] == "proposed":
        p["status"], p["approved_at"] = "approved", datetime.now(timezone.utc).strftime("%FT%TZ")
        p["approved_by"] = os.environ.get("USER", "")
        _write(_path(home, pid), p)
    return p


def _board(*args):
    return subprocess.run([sys.executable, str(Path(__file__).with_name("board.py")), *args],
                          capture_output=True, text=True, timeout=120)


def apply(home, project, pid, owner, number, repo, status_map="", do_apply=False):
    """Move the approved plan's sprint cards to Ready, one at a time. Returns report lines."""
    p = load(home, project, pid)
    if p["status"] == "superseded":
        raise PlanError(f"{pid} was superseded by a newer plan")
    if do_apply and p["status"] != "approved":
        raise PlanError(f"{pid} is {p['status']}, not approved: run  quarterdeck plan approve {project} {pid}  first")
    r = _board("snapshot", owner, str(number), repo)
    if r.returncode != 0:
        raise PlanError("could not read the board: " + (r.stderr or "").strip()[:200])
    snap = json.loads(r.stdout)
    cur = {i["number"]: i for i in snap.get("items", []) if i.get("type") == "Issue" and i.get("number")}
    ready = (snap.get("columns") or {}).get("ready", "")
    by = {x["issue"]: x for x in p["plan"]}
    out = [] if p["status"] == "approved" else [f"({pid} is {p['status']}: this is a preview, --apply would refuse)"]
    for n in p["sprint"]:
        x = by[n]
        if any(m["issue"] == n and m["result"] == "moved" for m in p["moves"]):
            out.append(f"#{n}: already moved by this plan")
            continue
        it = cur.get(n)
        if not it:
            why = "no longer on the board"
        elif it.get("state") != "OPEN":
            why = "closed since the plan was made"
        elif it.get("status") != x["from_status"]:
            why = f"moved meanwhile: the plan expected '{x['from_status']}', the card is in '{it.get('status')}'"
        elif x["from_status"] == ready:
            out.append(f"#{n}: already in {ready}, nothing to do")
            continue
        else:
            why = ""
        if why:
            res = {"issue": n, "result": "skipped", "why": why, "at": time.strftime("%FT%TZ", time.gmtime())}
        elif not do_apply:
            out.append(f"#{n}: would move {x['from_status']} → Ready   ({x['title'][:60]})")
            continue
        else:
            m = _board("to", owner, str(number), str(n), "ready", status_map if status_map.startswith("{") else "", "todo")
            moved = m.returncode == 0 and m.stdout.strip() != ""
            res = {"issue": n, "result": "moved" if moved else "skipped", "from": m.stdout.strip(),
                   "why": "" if moved else (m.stderr.strip()[:200] or "the board left the card alone"),
                   "at": time.strftime("%FT%TZ", time.gmtime())}
        if why or do_apply:
            if do_apply:
                p["moves"].append(res)
                _write(_path(home, pid), p)
            out.append(f"#{n}: " + (f"moved {res['from']} → Ready" if res["result"] == "moved" else f"left alone ({res['why']})"))
    return out


# ---- command line ------------------------------------------------------------------------------
def main(a):
    c = a[0] if a else ""
    if c == "eligible":
        for i in eligible(json.load(open(a[1])), int(os.environ.get("QUARTERDECK_PLAN_MAX", "30"))):
            print(i["number"])
    elif c == "context":
        issues = {}
        for line in open(a[2]):
            if line.strip():
                d = json.loads(line)
                issues[d["number"]] = d
        print(json.dumps(context(json.load(open(a[1])), issues, a[3], a[4], int(os.environ.get("QUARTERDECK_PLAN_MAX", "30")))))
    elif c == "check":
        try:
            print(json.dumps(check(json.load(open(a[1])), json.loads(sys.stdin.read()),
                                   None if a[2] == "-" else int(a[2]), None if a[3] == "-" else float(a[3]))))
        except json.JSONDecodeError as e:
            sys.exit(f"the reply is not JSON: {e}")
        except PlanError as e:
            sys.exit(str(e))
    elif c == "render":
        print(render(json.load(open(a[1]))), end="")
    elif c == "save":
        print(save(a[1], json.load(open(a[2]))))
    elif c == "approve":
        p = approve(a[1], a[2], a[3])
        print(f"{p['id']} is approved. Next: quarterdeck plan apply {p['project']} {p['id']}   (add --apply to move the cards)")
    elif c == "apply":
        print("\n".join(apply(a[1], a[2], a[3], a[4], a[5], a[6], "" if a[7] == "-" else a[7], "--apply" in a[8:]))
              + ("" if "--apply" in a[8:] else "\n(report only: add --apply to make these moves)"))
    elif c == "list":
        for p in _plans(a[1], a[2]):
            print(f"{p['id']}  {p['status']:10}  {len(p['sprint'])} in sprint of {len(p['plan'])}  {p.get('doc', '')}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except PlanError as e:
        sys.exit(f"plan: {e}")
