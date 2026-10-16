"""Made-up design briefs, mock-ups and a sprint plan for Demo mode. No model call, no file, no network: everything lives in memory
and goes away with the demo world. The mock-up pages are served by the same route, with the same strict headers, as real ones, and
pass the same check (bin/mockup.py)."""
import re

ID_RE = re.compile(r"^b\d{8}-\d{6}-[0-9a-f]{4}\Z")
PLAN_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}\Z")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}\Z")
NOW = "2026-10-15T09:00:00Z"

SWAP = {
    "title": "Neighbourhood book swap", "one_line": "A small page where neighbours list a book and see which books are free to take.",
    "audience": "People who live on one street and like to swap books. Some are not used to websites.",
    "goals": ["List a book in under a minute", "See at a glance which books are available", "Say which book you would like"],
    "not_goals": ["Taking payments", "Accounts or passwords", "Reviews of books"],
    "key_screens": [
        {"name": "Available books", "purpose": "Show every book that can be taken, newest first.",
         "content": ["A list of books: title, author and the street number it is at", "A short line saying how many books are free"],
         "actions": ["Open a book", "Go to Add a book"]},
        {"name": "Add a book", "purpose": "Let a neighbour list a book they want to give away.",
         "content": ["Title", "Author", "Your street number"], "actions": ["Save the book", "Go back to the list"]}],
    "flows": [{"name": "List a book", "steps": ["Open the page", "Choose Add a book", "Fill in the title, author and street number", "Save", "See the book in the list"]}],
    "content_notes": "Friendly, short words. No pictures are needed to start with.",
    "accessibility": "Everything can be reached with the keyboard alone, in a sensible order, and the place you are is always clearly marked (the focus). Text is large and dark on a light background.",
    "assumptions": ["Neighbours know each other, so no sign-in is needed", "A street number is enough to find the book"],
    "open_questions": ["Should a book disappear when someone takes it, or stay with a note?", "Does anyone besides you need to remove a listing?"],
    "success_checks": ["A neighbour who has never seen the page can list a book in under a minute", "The list shows only books that are still free"]}
THEME = {
    "title": "Dark theme switch", "one_line": "Let people choose a dark look for the web companion, and remember the choice.",
    "audience": "Travellers who plan trips at night or on a phone in a dim room.",
    "goals": ["Offer a dark look that is easy to read", "Remember the choice on the next visit"], "not_goals": ["Custom colours"],
    "key_screens": [
        {"name": "Settings", "purpose": "Where the look is chosen.", "content": ["A choice of Light, Dark or Same as my device"], "actions": ["Choose a look"]},
        {"name": "Trip list", "purpose": "Show that the whole page follows the choice.", "content": ["The list of trips"], "actions": ["Open a trip"]}],
    "flows": [{"name": "Switch to dark", "steps": ["Open Settings", "Choose Dark", "Go to the trip list and see it dark"]}],
    "content_notes": "", "accessibility": "Everything can be reached with the keyboard alone and the focus stays clearly visible in both looks. Text keeps at least the same contrast in dark as in light.",
    "assumptions": ["Same as my device is the starting choice"], "open_questions": [], "success_checks": ["Dark text on light and light text on dark are both easy to read"]}


def _page(title, body, accent="#0a6c74"):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{title}</title><style>:root{{--ink:#1d2433;--bg:#ffffff;--accent:{accent};--line:#d5dae3}}"
            "body{color:var(--ink);background:var(--bg);font:16px/1.5 system-ui,sans-serif;margin:0;padding:1.25rem}main{max-width:36rem;margin:0 auto}"
            "h1{font-size:1.5rem;margin:0 0 .25rem}p{margin:.25rem 0 1rem}ul{list-style:none;padding:0;margin:0}li{border:1px solid var(--line);border-radius:8px;padding:.75rem;margin-bottom:.5rem}"
            "a,button{color:var(--accent);font:inherit}button{background:transparent;border:2px solid var(--accent);border-radius:8px;padding:.5rem 1rem;cursor:pointer}"
            "label{display:block;font-weight:600;margin-top:.75rem}input{display:block;width:100%;box-sizing:border-box;font:inherit;padding:.5rem;border:1px solid var(--ink);border-radius:6px}"
            "a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}</style></head>"
            f"<body><main>{body}</main></body></html>")


PAGES = {
    "available-books": ("Available books", _page("Available books", "<h1>Available books</h1><p>3 books are free to take.</p><ul>"
                        "<li><strong>The Wind in the Willows</strong><br>Kenneth Grahame, no. 14</li><li><strong>Persuasion</strong><br>Jane Austen, no. 22</li>"
                        "<li><strong>Cooking for One</strong><br>Anna Lind, no. 9</li></ul><p><a href=\"#add\">Add a book</a></p>")),
    "add-a-book": ("Add a book", _page("Add a book", "<h1>Add a book</h1><p>Tell your neighbours what you are giving away.</p>"
                   "<label for=\"t\">Title</label><input id=\"t\" type=\"text\"><label for=\"a\">Author</label><input id=\"a\" type=\"text\">"
                   "<label for=\"n\">Your street number</label><input id=\"n\" type=\"text\"><p><button type=\"button\">Save the book</button> <a href=\"#list\">Back to the list</a></p>")),
    "settings": ("Settings", _page("Settings", "<h1>Settings</h1><p>Choose how the page looks.</p><label for=\"l\">Look</label><input id=\"l\" type=\"text\" value=\"Same as my device\">"
                 "<p><button type=\"button\">Save</button></p>", "#1b5e8c")),
    "trip-list": ("Trip list", _page("Trip list", "<h1>Your trips</h1><ul><li><strong>Lisbon</strong><br>12 to 16 March</li><li><strong>Porto</strong><br>2 to 5 May</li></ul>"
                 "<p><a href=\"#open\">Open a trip</a></p>", "#1b5e8c")),
}

PLAN = {
    "id": "wayfarer-web-20261015-100000", "project": "wayfarer-web", "created": "2026-10-15T10:00:00Z", "status": "proposed", "capacity": 3, "budget": None,
    "reordered": False, "measured_runs": 4, "columns": {"todo": "Backlog", "ready": "Ready"},
    "plan": [
        {"issue": 32, "title": "Add alt text to destination photos", "size": "S", "reason": "One contained change in the photo component; the text already exists in the data.",
         "depends_on": [], "parallel_ok": True, "needs_decision": "", "why_now": "It is the quickest win and blocks nothing.", "from_status": "Backlog",
         "cost": {"low": 0.9, "high": 1.6, "n": 3, "basis": "size"}},
        {"issue": 31, "title": "Dark mode contrast on settings", "size": "M", "reason": "Touches the settings page and the shared colour tokens, so two places change together.",
         "depends_on": [], "parallel_ok": True, "needs_decision": "", "why_now": "Users have reported it; the fix is clear.", "from_status": "Backlog",
         "cost": {"low": 1.4, "high": 3.1, "n": 3, "basis": "size"}},
        {"issue": 30, "title": "Date picker ignores the user's locale", "size": "L", "reason": "Crosses the form library and every screen with a date, and nobody has settled which locales to support.",
         "depends_on": [31], "parallel_ok": False, "needs_decision": "Which locales must the date picker support in this release?", "why_now": "",
         "from_status": "Backlog", "cost": {"low": 3.4, "high": 7.4, "n": 4, "basis": "all"}}],
    "sprint": [32, 31], "later": [{"issue": 30, "reason": "needs a decision before it can start: Which locales must the date picker support in this release?"}],
    "left_out": [], "total_cost": {"low": 2.3, "high": 4.7}, "moves": [], "doc": "wayfarer-web-plan-2026-10-15.md"}


def _is_pub(rec):
    return rec


class Maker:
    def __init__(self):
        self.briefs = {
            "b20261015-090000-d3a1": self._rec("b20261015-090000-d3a1", "idea", "", None, SWAP, "proposed", "I want a small page for my neighbourhood book swap where people can list a book and see what is available."),
            "b20261014-150000-d3a2": self._rec("b20261014-150000-d3a2", "issue", "wayfarer-web", 35, THEME, "approved", ""),
        }
        m = self.briefs["b20261014-150000-d3a2"]
        m["mockups"] = {"state": "ready", "created": NOW, "pages": [{"name": "settings", "title": "Settings", "bytes": 1800, "contrast": 14.8, "contrast_note": ""},
                                                                   {"name": "trip-list", "title": "Trip list", "bytes": 1500, "contrast": 14.8, "contrast_note": ""}], "missing": [], "notes": []}
        self.plans = {PLAN["id"]: dict(PLAN, plan=[dict(x) for x in PLAN["plan"]], moves=[])}
        self.n = 0

    def _rec(self, bid, source, project, issue, brief, status, idea):
        return {"id": bid, "kind": "brief", "source": source, "project": project, "issue": issue, "idea": idea, "audience_hint": "", "brief": brief, "notes": [],
                "doc": "", "revises": "", "superseded_by": "", "created": NOW, "updated": NOW, "status": status, "error": None, "mockups": {"state": "none"}}

    # ---- reads ----
    def summary(self):
        return [{"id": r["id"], "status": r["status"], "project": r["project"], "mockups": r["mockups"].get("state", "none"),
                 "title": (r["brief"] or {}).get("title") or "A new idea", "at": r["updated"]} for r in self.briefs.values() if r["status"] != "superseded"]

    def plan_summary(self):
        return [{"id": p["id"], "project": p["project"], "status": p["status"], "sprint": len(p["sprint"]), "items": len(p["plan"]), "at": p["created"]}
                for p in self.plans.values()]

    def brief(self, bid):
        return self.briefs.get(bid) if ID_RE.match(bid or "") else None

    def plan(self, pid):
        return self.plans.get(pid) if PLAN_RE.match(pid or "") and ".." not in pid else None

    def mockup_page(self, bid, name):
        r = self.brief(bid)
        if not r or name not in {p["name"] for p in (r["mockups"].get("pages") or [])}:
            return None
        return PAGES[name][1]

    def get(self, path, q):
        one = lambda k: (q.get(k) or [""])[0]
        if path == "/api/brief":
            if not ID_RE.match(one("id")):
                return 400, {"error": "bad id"}
            r = self.brief(one("id"))
            return (200, r) if r else (404, {"error": "no such brief"})
        if path == "/api/plan":
            if not PLAN_RE.match(one("id")) or ".." in one("id"):
                return 400, {"error": "bad id"}
            p = self.plan(one("id"))
            return (200, p) if p else (404, {"error": "no such plan"})
        return None

    # ---- writes: in memory only ----
    def post(self, path, b):
        if path == "/api/brief/new":
            if b.get("confirm") is not True:
                return 400, {"error": "confirm is required: this uses your model subscription"}
            idea = " ".join(str(b.get("idea") or "").split())
            if b.get("issue") is None and not 10 <= len(idea) <= 2000:
                return 400, {"error": "describe the idea in a few sentences (at least 10 and at most 2000 characters)"}
            self.n += 1
            bid = f"b20261015-{100000 + self.n:06d}-d3{self.n % 256:02x}"
            self.briefs[bid] = self._rec(bid, "issue" if b.get("issue") is not None else "idea", str(b.get("project") or ""), b.get("issue"), SWAP, "proposed", idea)
            return 200, {"id": bid}
        if path == "/api/brief/action":
            return self._brief_action(b)
        if path == "/api/plan/action":
            return self._plan_action(b)
        return None

    def _brief_action(self, b):
        r, act, note = self.brief(b.get("id")), b.get("action"), " ".join(str(b.get("note") or "").split())[:1200]
        if not ID_RE.match(str(b.get("id") or "")):
            return 400, {"error": "bad id"}
        if act not in ("approve", "changes", "mockups", "mockups_approve", "mockups_changes", "revise", "add_to_project", "link"):
            return 400, {"error": "unknown action"}
        if b.get("confirm") is not True:
            return 400, {"error": "confirm is required"}
        if not r:
            return 404, {"error": "not found"}
        st, m = r["status"], r["mockups"]
        def to(status):
            r["status"] = status
            return 200, r
        if act == "approve":
            return to("approved") if st == "proposed" else (409, {"error": f"only a proposed brief can be approved"})
        if act == "changes":
            if st not in ("proposed", "approved"):
                return 409, {"error": "changes can be asked for on a proposed or approved brief"}
            if not note:
                return 409, {"error": "say what should change"}
            r["notes"].append({"at": NOW, "action": "changes_requested", "text": note})
            return to("changes_requested")
        if act == "mockups":
            if st != "approved":
                return 409, {"error": "mock-ups are made only from an approved brief"}
            names = [s["name"].lower().replace(" ", "-") for s in r["brief"]["key_screens"]]
            pick = ["available-books", "add-a-book"] if "available-books" in names else ["settings", "trip-list"]
            r["mockups"] = {"state": "ready", "created": NOW, "pages": [{"name": n, "title": PAGES[n][0], "bytes": len(PAGES[n][1]), "contrast": 14.8, "contrast_note": ""} for n in pick], "missing": [], "notes": []}
            return 200, {"started": f"mockup {r['id']} (made up: no model ran)"}
        if act in ("mockups_approve", "mockups_changes"):
            if m.get("state") not in ("ready", "approved", "changes_requested") or not m.get("pages"):
                return 409, {"error": "there are no finished mock-ups to answer"}
            if act == "mockups_approve":
                if m["state"] != "ready":
                    return 409, {"error": "only a new set can be approved"}
                m["state"] = "approved"
            else:
                if not note:
                    return 409, {"error": "say what should change"}
                m["state"] = "changes_requested"
                m.setdefault("notes", []).append({"at": NOW, "action": "changes_requested", "text": note})
            return 200, r
        if act == "revise":
            if st != "changes_requested":
                return 409, {"error": "only a brief you asked changes on can be revised"}
            self.n += 1
            bid = f"b20261015-{200000 + self.n:06d}-d4{self.n % 256:02x}"
            new = self._rec(bid, r["source"], r["project"], r["issue"], r["brief"], "proposed", r["idea"])
            new["revises"] = r["id"]
            r["status"], r["superseded_by"] = "superseded", bid
            self.briefs[bid] = new
            return 200, {"id": bid}
        if act == "link":
            r["project"] = str(b.get("project") or "")
            return 200, r
        return 400, {"error": "Demo mode: nothing is written into any project."}

    def _plan_action(self, b):
        pid, act, project = b.get("id"), b.get("action"), b.get("project")
        if not PLAN_RE.match(str(pid or "")) or ".." in str(pid):
            return 400, {"error": "bad id"}
        if act not in ("approve", "preview", "apply"):
            return 400, {"error": "unknown action"}
        if act != "preview" and b.get("confirm") is not True:
            return 400, {"error": "confirm is required"}
        p = self.plan(pid)
        if not p:
            return 404, {"error": "not found"}
        if project != p["project"]:
            return 409, {"error": f"{pid} belongs to {p['project']}, not {project}"}
        if act == "approve":
            if p["status"] == "proposed":
                p["status"] = "approved"
            return 200, {"plan": p, "lines": []}
        if act == "apply" and p["status"] != "approved":
            return 409, {"error": f"{pid} is {p['status']}, not approved"}
        by = {x["issue"]: x for x in p["plan"]}
        lines = []
        for n in p["sprint"]:
            if any(m["issue"] == n and m["result"] == "moved" for m in p["moves"]):
                lines.append(f"#{n}: already moved by this plan")
            elif act == "preview":
                lines.append(f"#{n}: would move Backlog → Ready   ({by[n]['title'][:60]})")
            else:
                p["moves"].append({"issue": n, "result": "moved", "from": "Backlog", "why": "", "at": NOW})
                lines.append(f"#{n}: moved Backlog → Ready")
        if act == "preview" and p["status"] != "approved":
            lines.insert(0, f"({pid} is {p['status']}: this is a preview, apply would refuse)")
        return 200, {"plan": p, "lines": lines}
