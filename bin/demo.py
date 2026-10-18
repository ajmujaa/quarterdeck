#!/usr/bin/env python3
"""Demo mode: a made-up Quarterdeck world that answers every endpoint the page uses.

Nothing here reads a file, runs a process or opens a socket: it imports no
module that could (no subprocess, no urllib, no os, no pathlib), so "demo mode
touches nothing real" is a property of this file's imports, not of its care.
The dashboard hands each request to World.get() / World.post() before any of its
own code runs, and the answers have exactly the shapes the real endpoints return,
so the page needs nothing demo-specific beyond a banner.

The world is a pure function of (seed, seconds since the demo started, what the
presenter has pressed): the same rehearsal replays identically. A scripted
timeline (SCENARIO below) makes the Brain move for about six minutes, then
settles and stays still. Every timestamp is generated relative to the moment the
demo started, so "5m ago" reads as live.
"""
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone

ORG = "example-org"
FEED_BREAKS = 230                # second at which the Facebook feed reports an expired token (the Brain notices and suggests)
SETTLE = 380                     # seconds after which the scripted timeline has finished and nothing more happens
SEED = 7

# ---- the fictional world ------------------------------------------------------

PROJECTS = {
    "wayfarer-mobile": {"summary": "Trip planner for iOS and Android, offline first", "kind": "mobile app",
                        "duties": ["surveyor", "foreman", "joiner", "shipwright", "panel", "inspector", "harbourmaster", "purser", "trials", "planner", "logkeeper", "bosun"],
                        "verify": "npm test"},
    "wayfarer-web": {"summary": "Web companion to the trip planner", "kind": "web app",
                     "duties": ["surveyor", "foreman", "shipwright", "panel", "inspector", "trials", "lookout", "pilot", "assayer", "caulker", "brief", "mockup"], "verify": "npm run check"},
    "wayfarer-api": {"summary": "REST API behind both apps", "kind": "API",
                     "duties": ["surveyor", "shipwright", "inspector", "purser", "trials", "marshal", "quartermaster", "infra", "bosun"], "verify": "pytest -q"},
    "harvest-pipeline": {"summary": "Nightly data pipeline that turns raw bookings into reports", "kind": "data pipeline",
                         "duties": ["surveyor", "purser", "trials", "infra"], "verify": "make test"},
    "saltpan-blog": {"summary": "A food blog: recipes, travel notes, a weekly newsletter", "kind": "blog",
                     "duties": ["surveyor", "joiner"], "verify": ""},
}
# ---- the board and its cards (invented; the Board view and the card reading panel in Demo mode) ----
BOARD_COLUMNS = ["Backlog", "Ready", "In progress", "In review", "Done"]
REQ_OPEN, REQ_CLOSE = "<!-- quarterdeck:requirements -->", "<!-- /quarterdeck:requirements -->"
CARD_BODIES = {
    ("wayfarer-mobile", 14): """## Problem

The trip list is empty when the phone is offline. People open the app on a plane and see nothing, even though they opened it yesterday.

## What we know

- The list is fetched on every launch and **replaced** by the response.
- A failed fetch writes an empty array into the store.
- Reported by three beta testers this week.

## Sketch

```ts
async function loadTrips() {
  try {
    const fresh = await api.trips();
    cache.write("trips", fresh);
  } catch {
    // keep what we have; do not write []
  }
  return cache.read("trips") ?? [];
}
```

| Case | Today | Wanted |
| --- | --- | --- |
| Online, first run | list | list |
| Offline, cached | empty | cached list and a small banner |
| Offline, never opened | empty | empty state that says so |

## Checklist

- [x] Reproduce on a device
- [ ] Keep the cached list on a failed fetch
- [ ] Offline banner above the list
- [ ] Test: airplane mode after one good load
""",
    ("wayfarer-mobile", 15): """Let someone send a trip to a friend as a link.

The link opens the trip read only in the web companion. See the design notes in the web app channel, and https://example.com/wayfarer/share-design for the mockups.

- [ ] Decide what the link contains
- [ ] Revoke a link
""" + "\n" + REQ_OPEN + """
## Requirements

_Written by Quarterdeck's purser from the issue and the code. Edit freely; running the analysis again replaces this section._

The share link must be unguessable, read only, and revocable.

1. A trip can be shared as a link with at least 128 bits of randomness
   - **Accept when:** two links for the same trip differ and neither can be guessed from the trip id
2. The shared page shows the trip read only
   - **Accept when:** no edit control is rendered and a write request with the link token is refused
3. The owner can revoke a link
   - **Accept when:** a revoked link answers with a not found page within a minute

**Out of scope**
- Comments on a shared trip
- Editing by a link holder
""" + REQ_CLOSE + "\n",
    ("wayfarer-mobile", 16): "A light haptic when a packing item is ticked.\n\n- [x] iOS\n- [ ] Android (needs a permission check)\n\nSee `Haptics.impact('light')`.\n",
    ("wayfarer-mobile", 17): "The onboarding flow ends before the notification prompt is shown.\n\n1. Open a fresh install\n2. Walk through the three steps\n3. The prompt never appears\n\nExpected: ask on the last step, with one sentence on why.\n",
    ("wayfarer-mobile", 18): "Crash when the airport code field is empty and the user taps *Add flight*.\n\n```\nTypeError: Cannot read properties of undefined (reading 'toUpperCase')\n    at normalise (src/flights/code.ts:12)\n```\n\n- [ ] Guard the empty value\n- [ ] Add a test\n",
    ("wayfarer-mobile", 41): "Closes #13.\n\nAdds pull to refresh to the trip list.\n\n- [x] Refresh on pull\n- [x] Spinner follows the system colour\n- [ ] Haptic on release (follow up)\n\n| File | Change |\n| --- | --- |\n| `TripList.tsx` | pull handler |\n| `useTrips.ts` | refetch |\n",
}
CARD_COMMENTS = {
    ("wayfarer-mobile", 14): [("mina-demo", -30, "I can reproduce this on an iPhone SE with airplane mode on. The list flashes and then goes blank."),
                              ("jonas-demo", -5, "Agreed. Keep the cache on error. I would also **not** show a spinner when we already have a list.\n\nSee https://example.com/wayfarer/offline-notes")],
    ("wayfarer-mobile", 15): [("mina-demo", -20, "Do we want links to expire by default?")],
    ("wayfarer-mobile", 41): [("jonas-demo", -2, "Looks good. One question about the release haptic, can it wait?"),
                              ("mina-demo", -1, "Yes, tracked as a follow up.")],
}
BOARD_PRIORITY = {14: "P1", 15: "P2", 18: "P0", 129: "P0", 131: "P1"}

GUARDRAILS = ["Never merge a pull request and never push to the default branch.",
              "Never touch payment or account-deletion code without saying so in the contract and stopping."]

DUTIES = [("foreman", "Turns a findings document into deduplicated GitHub issues."),
          ("harbourmaster", "Reconciles the project board against GitHub reality."),
          ("inspector", "Verifies a pull request against its issue and comments on it."),
          ("joiner", "Reviews the interface and writes a findings document."),
          ("panel", "Seats a discipline of crew on the question and rules on it."),
          ("purser", "Turns a backlog issue into something a stranger could start from."),
          ("shipwright", "Takes one issue to a branch and a pull request."),
          ("surveyor", "Inspects a pull request and reports defects. Never approves, never merges."),
          ("trials", "Runs the project's own verify command."),
          ("assayer", "Writes tests from the issue alone and keeps the ones that prove something."),
          ("bosun", "Walks the project and reports drift: stale branches and old to-dos."),
          ("brief", "Turns an idea into a one-page design brief."),
          ("caulker", "Fixes what the reviewers found on a pull request, and nothing else."),
          ("infra", "Reads a change to infrastructure files and reports how risky it is."),
          ("logkeeper", "Turns a panel's ruling into a numbered record in the docs."),
          ("lookout", "Takes pictures of the running screens and judges them."),
          ("marshal", "Reads a pull request for security problems."),
          ("mockup", "Makes one static page per key screen from an approved brief."),
          ("pilot", "Starts the app from a pull request and tries the main flows."),
          ("planner", "Puts the backlog in order and sizes each issue."),
          ("quartermaster", "Judges a dependency update: merge, hold or block.")]
DRIVEN = {"surveyor", "foreman", "joiner", "shipwright", "panel", "inspector", "harbourmaster", "purser", "trials"}   # the duties the scripted history runs; the rest are enabled but have never run

CREW = [("dockmaster", "design,dev,spec", "chair", "weighs the argument and rules"),
        ("shipwright", "dev", "builder", "prefers the smallest change that works"),
        ("surveyor", "design,dev", "reviewer", "assumes there is a defect until shown otherwise"),
        ("signaller", "design", "user voice", "speaks for the person using it"),
        ("steward", "spec,dev", "operations", "cares what happens at 3 a.m.")]

ISSUES = {  # number: (title, state)
    "wayfarer-mobile": {11: ("Trip list flickers on first load", "CLOSED"), 12: ("Map pins overlap on small phones", "CLOSED"),
                        13: ("Add pull to refresh to the trip list", "CLOSED"), 14: ("Offline cache for the trip list", "OPEN"),
                        15: ("Share a trip as a link", "OPEN"), 16: ("Haptics on the packing checklist", "OPEN"),
                        17: ("Onboarding skips the notification prompt", "OPEN"), 18: ("Crash when the airport code is empty", "OPEN")},
    "wayfarer-web": {28: ("Keyboard focus lost after closing the trip dialog", "CLOSED"), 29: ("Print view cuts off the itinerary", "CLOSED"),
                     30: ("Date picker ignores the user's locale", "OPEN"), 31: ("Dark mode contrast on settings", "OPEN"),
                     32: ("Add alt text to destination photos", "OPEN")},
    "wayfarer-api": {120: ("N+1 query on the trips endpoint", "CLOSED"), 121: ("Rate limit headers missing", "CLOSED"),
                     122: ("Paginate the activity feed", "CLOSED"), 129: ("Orders endpoint returns 500 on empty cart", "OPEN"),
                     130: ("Lint failure in the webhook handler", "OPEN"), 131: ("Idempotency keys for booking requests", "OPEN")},
    "harvest-pipeline": {7: ("Late-arriving rows double count", "CLOSED"), 8: ("Retry the warehouse load on timeout", "OPEN"),
                         9: ("Which timezone is canonical for daily totals?", "OPEN"), 10: ("Add a row-count check to the nightly job", "OPEN")},
    "saltpan-blog": {3: ("Recipe cards break on narrow screens", "CLOSED"), 4: ("Structured data for recipes", "OPEN"),
                     5: ("Newsletter signup form needs a thank-you state", "OPEN")},
}

# Open pull requests at the start of the demo: (project, number, title, branch, issue, add, del, files, failing check, review verdict/detail)
BASE_PRS = [
    ("wayfarer-mobile", 41, "Pull to refresh on the trip list", "fix/13-pull-to-refresh", 13, 88, 12, 4, None, ("CLEAN", "0 finding(s)")),
    ("wayfarer-web", 77, "Print stylesheet for the itinerary", "fix/29-print-view", 29, 61, 9, 3, None, ("CLEAN", "0 finding(s)")),
    ("wayfarer-api", 130, "Fix lint in the webhook handler", "fix/130-lint", 130, 14, 14, 1, "lint", None),
    ("harvest-pipeline", 19, "Retry warehouse load with backoff", "fix/8-retry-load", 8, 120, 31, 5, None, ("DRY-RUN", "2 finding(s)")),
]

PANELS = [  # id, project, discipline, subject, headline, hours ago, ruling
    ("20261005-0412-design-wayfarer-mobile", "wayfarer-mobile", "design", "the trip list and onboarding screens",
     "Offline and onboarding are the two things users will hit first", 9, [
         ("Trip list is empty offline", "major", "intricate", "change", "offline", "A failed fetch replaces the cached list with an empty state.", "src/trips/TripList.tsx", "Keep the cached list and show a small offline banner above it."),
         ("Notification prompt is skipped", "major", "routine", "change", "onboarding", "Onboarding ends before the permission prompt is shown.", "src/onboarding/Steps.tsx", "Ask on the last step, with one sentence on why."),
         ("Packing checklist gives no feedback", "minor", "mechanical", "change", "polish", "Ticking an item changes nothing the thumb can feel.", "src/packing/Checklist.tsx", "Add a light haptic on tick."),
         ("Pick a single empty-state voice", "minor", "routine", "decision", "copy", "Three screens greet an empty list in three different tones.", "src/copy/", "Decide the tone once and write it down.")]),
    ("20261004-2130-spec-wayfarer-web", "wayfarer-web", "spec", "dark mode for the web companion",
     "Dark mode ships as tokens, not overrides", 15, [
         ("Move colours into design tokens", "major", "intricate", "change", "theme", "Colours are hard-coded in 41 places.", "src/styles/", "Introduce a token file and replace the literals."),
         ("Dark mode contrast on settings", "major", "routine", "change", "theme", "Muted text on the settings page is 3.1:1 against its background.", "src/settings/", "Raise the muted text colour to meet 4.5:1."),
         ("Respect the system setting by default", "minor", "mechanical", "change", "theme", "No code reads prefers-color-scheme.", "src/main.ts", "Read it once at start and on change.")]),
    ("20261004-1815-dev-wayfarer-api", "wayfarer-api", "dev", "booking requests and retries",
     "Booking is safe to retry once keys are enforced", 20, [
         ("Idempotency keys for booking requests", "critical", "hard", "change", "bookings", "A retried POST can create two bookings.", "api/bookings.py", "Require a key header and store the first result per key."),
         ("Orders endpoint returns 500 on an empty cart", "major", "routine", "change", "orders", "An empty cart is not validated.", "api/orders.py", "Return 422 with a clear message."),
         ("Document the retry policy", "minor", "mechanical", "change", "docs", "Clients guess how often to retry.", "docs/retries.md", "Write one page and link it from the README.")]),
]

# The one stored diff in the made-up world: a finished fix's before and after, as unified-diff lines.
DEMO_DIFF = "\n".join([
    "--- a/src/styles/tokens.css", "+++ b/src/styles/tokens.css", "@@ -1,4 +1,8 @@",
    "-.btn { background: #2f6fed; }", "-.card { background: #ffffff; }",
    "+:root { --accent: #2f6fed; --surface: #ffffff; }",
    "+.btn { background: var(--accent); }", "+.card { background: var(--surface); }",
    "@@ -20,3 +24,4 @@", " .nav { display: flex; }", "+.nav a { color: var(--accent); }"])

# Scenario jobs. start/end are seconds after the demo starts. A job with a
# `fix` is an issue taken through the pipeline (ends in a pull request, or in a
# failure); one with a `pr` opens that pull request when it ends; `verdict` is
# the ledger row written when it ends.
SCENARIO_JOBS = [
    dict(start=-20, end=70, project="wayfarer-mobile", duty="shipwright", issue=14, panel=0, item=1,
         what="issue #14, Offline cache for the trip list", verdict="PR", pr=42, cost=1.84, step="building"),
    dict(start=20, end=100, project="wayfarer-web", duty="shipwright", issue=31, panel=1, item=2,
         what="issue #31, Dark mode contrast on settings", verdict="PR", pr=78, cost=1.12, step="building"),
    dict(start=85, end=115, project="wayfarer-mobile", duty="surveyor", target=42,
         what="pull request #42", verdict="CLEAN", detail="#42 0 finding(s)", cost=0.41),
    dict(start=118, end=150, project="wayfarer-api", duty="shipwright", issue=131, panel=2, item=1,
         what="issue #131, Idempotency keys for booking requests", verdict="ERROR", fail="tests failed: 2 failing in test_bookings.py",
         cost=0.95, step="verifying"),
    dict(start=165, end=225, project="wayfarer-api", duty="shipwright", issue=131, panel=2, item=1,
         what="issue #131, Idempotency keys for booking requests (re-run)", verdict="PR", pr=132, cost=1.63, step="building"),
    dict(start=200, end=232, project="wayfarer-web", duty="inspector", target=78,
         what="pull request #78", verdict="PROVEN", detail="#78 matches issue #31", cost=0.37),
    dict(start=240, end=265, project="wayfarer-mobile", duty="trials",
         what="the verify command", verdict="DRY-RUN", detail="verify passed on main", cost=0.12),
    dict(start=255, end=300, project="wayfarer-api", duty="surveyor", target=132,
         what="pull request #132", verdict="CLEAN", detail="#132 0 finding(s)", cost=0.44),
]

# Things that arrive from outside: (second, connector, item)
SCENARIO_DROPS = [
    (55, "gmail", dict(title="Your TestFlight build 1.4.0 (482) is ready", sub="App Store Connect", new=True)),
    (130, "slack", dict(title="#releases: mention", sub="the staging deploy for wayfarer-api is waiting on your approval", new=True)),
    (180, "analytics", dict(title="Brown butter rice pudding", sub="4,210 views, +640% vs last week", new=True)),
    (245, "linkedin", dict(title="What six months of offline-first taught us", sub="2,310 impressions, 61 reactions, 14 comments", new=True)),
    (290, "instagram", dict(title="The pancake reel", sub="940 likes, 38 comments, 10,420 reached", new=True)),
]


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hex8(n):
    return f"{0xd0000000 + n:08x}"


class World:
    MAKER = None    # set by the dashboard: made-up briefs, mock-ups and a sprint plan (bin/demo_maker.py), kept in memory
    EXT = []        # add-ons (bin/ext_*.py) that bring their own made-up data; each has reset(w), state(w, t, runs), inbox(w, t, runs), events(w, t, cutoff), logs(), post(w, path, b, t)

    def __init__(self, clock=time.time, seed=SEED):
        self.clock, self.seed = clock, seed
        self.reset()

    def reset(self):
        """Back to second zero, with nothing pressed."""
        self.t0 = self.clock()
        self.user_jobs, self.acks, self.merged, self.stopped = [], set(), set(), set()
        self.cycles_started = {}      # cycle id -> the invented running record made by the Start button (nothing real runs)
        self.counter, self.mission_extra, self.showcase, self.sched = 0, [], [], None
        self.stopped_user = set()
        self.ext = {}                               # what each add-on in EXT keeps about this world
        for x in self.EXT:
            x.reset(self)
        self.maker = self.MAKER() if self.MAKER else None
        self.notes = self._base_notes()
        self.queue = {}
        self.intents, self.pstatus = [self._start_focus()], {}
        self.base = self._base_ledger()
        self.spend_rows = self._base_spend()

    # ---- time ----
    def elapsed(self):
        return max(0.0, self.clock() - self.t0)

    def at(self, secs):
        return iso(datetime.fromtimestamp(self.t0 + secs, timezone.utc))

    def ago(self, **kw):
        return iso(datetime.fromtimestamp(self.t0, timezone.utc) - timedelta(**kw))

    def next_id(self):
        self.counter += 1
        return self.counter

    # ---- the ledger: 24 hours of runs before the demo starts ----
    def _base_ledger(self):
        rng = random.Random(self.seed)
        base = [  # minutes ago, project, duty, verdict, detail, url
            (1380, "wayfarer-mobile", "joiner", "CLEAN", "design findings: 0 finding(s) above the bar", ""),
            (1300, "wayfarer-api", "purser", "READY", "#131 has what a stranger needs to start", ""),
            (1210, "wayfarer-web", "foreman", "FILED", "wayfarer-web-joiner-2026-10-04.md: 4 issue(s) filed", ""),
            (400, "wayfarer-mobile", "shipwright", "PR", f"#13 → https://github.com/{ORG}/wayfarer-mobile/pull/41", f"https://github.com/{ORG}/wayfarer-mobile/pull/41"),
            (390, "wayfarer-mobile", "surveyor", "CLEAN", "#41 0 finding(s)", ""),
            (1020, "wayfarer-web", "shipwright", "PR", f"#29 → https://github.com/{ORG}/wayfarer-web/pull/77", f"https://github.com/{ORG}/wayfarer-web/pull/77"),
            (1005, "wayfarer-web", "surveyor", "CLEAN", "#77 0 finding(s)", ""),
            (590, "harvest-pipeline", "shipwright", "PR", f"#8 → https://github.com/{ORG}/harvest-pipeline/pull/19", f"https://github.com/{ORG}/harvest-pipeline/pull/19"),
            (580, "harvest-pipeline", "surveyor", "DRY-RUN", "#19 2 finding(s)", ""),
            (640, "harvest-pipeline", "shipwright", "ERROR", "#8 verify failed: warehouse client timeout in test_load", ""),
            (840, "wayfarer-api", "panel", "RULED", "20261004-1815-dev-wayfarer-api: 3 item(s) kept", ""),
            (700, "wayfarer-api", "shipwright", "PR", f"#130 → https://github.com/{ORG}/wayfarer-api/pull/130", f"https://github.com/{ORG}/wayfarer-api/pull/130"),
            (690, "wayfarer-api", "surveyor", "CLEAN", "#130 0 finding(s)", ""),
            (545, "wayfarer-mobile", "panel", "RULED", "20261005-0412-design-wayfarer-mobile: 4 item(s) kept", ""),
            (410, "wayfarer-web", "inspector", "PROVEN", "#77 matches issue #29", ""),
            (300, "harvest-pipeline", "purser", "NEEDS_HUMAN", "#9 needs a decision: which timezone is canonical for daily totals?", ""),
            (260, "wayfarer-mobile", "harbourmaster", "SYNCED", "2 card(s) moved, 0 problems", ""),
            (95, "wayfarer-api", "trials", "DRY-RUN", "verify passed on main", ""),
            (40, "wayfarer-web", "trials", "DRY-RUN", "verify passed on main", ""),
        ]
        for h in range(22):                        # the hourly watch the schedules keep
            for project, duty in (("wayfarer-mobile", "surveyor"), ("wayfarer-api", "surveyor")):
                if rng.random() < 0.55:
                    base.append((h * 60 + rng.randrange(5, 55), project, duty, "DRY-RUN", "0 finding(s)", ""))
        for day in range(1, 7):                     # the week before: a few runs a day on every project, so the 7 day timeline has lanes
            for project, p in PROJECTS.items():
                for _ in range(rng.randrange(2, 7)):
                    duty = rng.choice([d for d in p["duties"] if d != "panel" and d in DRIVEN])
                    verdict, detail = rng.choice([("PR", "#7 opened"), ("CLEAN", "0 finding(s)"), ("DRY-RUN", "0 finding(s)"), ("DRY-RUN", "0 finding(s)"),
                                                  ("PROVEN", "matches the issue"), ("ERROR", "verify failed"), ("SYNCED", "1 card(s) moved")])
                    base.append((day * 1440 + rng.randrange(0, 1380) - 700, project, duty, verdict, detail, ""))
        base = [r for r in base if r[0] > 0]
        base.sort(key=lambda r: -r[0])
        return [{"at": self.ago(minutes=m), "project": p, "duty": d, "verdict": v, "detail": det, "url": u}
                for m, p, d, v, det, u in base]

    def _base_spend(self):
        rng = random.Random(self.seed + 1)
        rows = []
        for day in range(7):
            for _ in range(rng.randrange(7, 12)):
                duty = rng.choice(["shipwright", "shipwright", "surveyor", "panel", "inspector", "purser", "joiner"])
                rows.append({"at": self.ago(days=day, minutes=rng.randrange(30, 900)), "duty": duty,
                             "model": rng.choice(["sonnet", "sonnet", "haiku", "opus"]), "turns": rng.randrange(3, 40),
                             "cost": round(rng.uniform(0.15, 2.1), 2)})
        rows += [{"at": self.ago(hours=h), "duty": "shipwright", "model": "sonnet", "turns": 22, "cost": 1.4, "fix": k}
                 for h, k in ((18, PANELS[1][0] + "#1"), (20, PANELS[1][0] + "#3"))]
        return rows

    # ---- what the scenario and the presenter's clicks have done by now ----
    def jobs(self):
        out = []
        for i, j in enumerate(SCENARIO_JOBS):
            out.append({**j, "id": f"s{i}", "user": False})
        out += self.user_jobs
        return out

    def _slug_pr(self, project, n):
        return f"https://github.com/{ORG}/{project}/pull/{n}"

    def timeline(self, t):
        """Everything derived from the clock: running jobs, finished jobs, new ledger rows."""
        running, finished, rows = [], [], []
        for j in self.jobs():
            if j["id"] in self.stopped:
                continue
            if t < j["start"]:
                continue
            if t < j["end"]:
                running.append(j)
                continue
            finished.append(j)
            url = self._slug_pr(j["project"], j["pr"]) if j.get("pr") else ""
            if j.get("fail"):
                detail = f"#{j['issue']} {j['fail']}"
            elif j.get("pr"):
                detail = f"#{j['issue']} → {url}"
            else:
                detail = j.get("detail") or "0 finding(s)"
            rows.append({"at": self.at(j["end"]), "project": j["project"], "duty": j["duty"],
                         "verdict": j["verdict"], "detail": detail, "url": url})
        return running, finished, rows

    def runs(self, t):
        _, _, rows = self.timeline(t)
        merged = [{"at": self.at(m[1]), "project": m[0], "duty": "dashboard", "verdict": "MERGED", "detail": f"#{m[2]}",
                   "url": self._slug_pr(m[0], m[2])} for m in self.merged_rows()]
        return sorted(self.base + rows + merged, key=lambda r: r["at"])

    def merged_rows(self):
        return sorted(self.merged, key=lambda m: m[1])

    # ---- the pieces of /api/state ----
    def agents(self, t, runs, duties):
        last, counts = {}, {}
        cutoff = iso(datetime.fromtimestamp(self.t0 + t, timezone.utc) - timedelta(days=1))
        for r in runs:
            key = (r["project"], r["duty"])
            last[key] = r
            if r["at"] >= cutoff:
                counts[key] = counts.get(key, 0) + 1
        running, _, _ = self.timeline(t)
        role = dict(duties)
        out = []
        for pname, p in sorted(PROJECTS.items()):
            for duty in p["duties"]:
                lv = last.get((pname, duty)) or {}
                base = {"project": pname, "repo": f"{ORG}/{pname}", "duty": duty, "role": role.get(duty, ""),
                        "implemented": True, "last_verdict": lv.get("verdict"), "last_detail": lv.get("detail"),
                        "last_at": lv.get("at"), "runs_24h": counts.get((pname, duty), 0)}
                live = [j for j in running if j["project"] == pname and j["duty"] == duty]
                if not live:
                    out.append({**base, "status": "idle", "since": None, "pid": None, "what": None, "lock": f"{duty}-{pname}"})
                for j in live:
                    out.append({**base, "status": "running", "since": self.at(j["start"]), "pid": 41000 + int(re.sub(r"\D", "", j["id"]) or 0),
                                "what": j["what"] if j["duty"] != "shipwright" else f"{j['what']} · {j.get('step', 'building')}",
                                "lock": f"{duty}-{pname}-{j['id']}", "fixrun": f"fix-{j['id']}" if j.get("panel") is not None else None})
        return out

    def fixes(self, t):
        out = {}
        base = [(1, 1, "merged", f"https://github.com/{ORG}/wayfarer-web/pull/70", 1110),
                (1, 3, "pr", f"https://github.com/{ORG}/wayfarer-web/pull/77", 1020)]
        for pi, item, status, pr, mins in base:
            if True:
                p = PANELS[pi]
                title = p[6][item - 1][0]
                out[f"{p[0]}#{item}"] = {"project": p[1], "panel": p[0], "item": item, "title": title, "kind": "change", "tier": "routine",
                                          "batch": None, "status": status, "step": None, "lock": f"fix-{p[1]}-{item}", "fixrun": f"fix-b{pi}{item}",
                                          "started": self.ago(minutes=mins + 12), "finished": self.ago(minutes=mins), "issue": 29, "pr": pr,
                                          "verdict": "PROVEN", "detail": "opened by Quarterdeck",
                                          "plan": "wayfarer-web-plan-29.md" if item == 1 else "the ruling item itself, mechanical, no developer panel",
                                          **({"diff": DEMO_DIFF} if item == 1 else {})}
        running, finished, _ = self.timeline(t)
        for j in running + finished:
            if j.get("panel") is None:
                continue
            p = PANELS[j["panel"]]
            status = "running" if j in running else ("failed" if j.get("fail") else "pr")
            key = f"{p[0]}#{j['item']}"
            out[key] = {"project": j["project"], "panel": p[0], "item": j["item"], "title": p[6][j["item"] - 1][0], "kind": "change",
                        "tier": p[6][j["item"] - 1][2], "batch": None, "status": status,
                        "step": j.get("step") if status == "running" else None, "lock": f"shipwright-{j['project']}-{j['id']}",
                        "fixrun": f"fix-{j['id']}", "started": self.at(j["start"]), "finished": self.at(j["end"]) if status != "running" else None,
                        "issue": j.get("issue"), "pr": self._slug_pr(j["project"], j["pr"]) if status == "pr" else None,
                        "verdict": j["verdict"] if status != "running" else None,
                        "detail": j.get("fail") or ("opened by Quarterdeck" if status == "pr" else "")}
        return out

    # ---- cycles: two invented `qtdeck cycle` run records (state/cycles/<id>.json), read only like the real ones ----
    def cycle_records(self):
        def st(sid, title, duty, state, verdict, detail, cost, mins, url=""):
            return {"id": sid, "title": title, "duty": duty, "state": state, "verdict": verdict, "detail": detail, "url": url, "cost": cost,
                    "runs": [f"{ORG}_{duty}-{sid.replace(':', '-')}"] if cost else [], "started": self.ago(minutes=mins + 3),
                    "finished": self.ago(minutes=mins), **({"note": "skipped"} if state == "skipped" else {})}
        a = [st("purser", "Purser", "purser", "done", "READY", "#29: 4 requirement(s)", 0.31, 88),
             st("panel", "Dev panel", "panel", "done", "RULED", "dev: 3 of 3 on issue #29", 1.42, 84),
             st("shipwright", "Shipwright", "shipwright", "done", "PR", "#29 → pull/78", 0.88, 76, f"https://github.com/{ORG}/wayfarer-web/pull/78"),
             st("assayer", "Assayer", "assayer", "done", "VERIFIED", "#29: 2 test file(s) fail on main and pass on the pull request", 0.21, 72),
             st("r1:surveyor", "Surveyor (round 1)", "surveyor", "done", "FINDINGS", "2 on #78", 0.44, 64),
             st("r1:marshal", "Marshal (round 1)", "marshal", "done", "CLEAN", "#78: three seats, nothing found", 1.05, 64),
             st("r1:lookout", "Lookout (round 1)", "lookout", "skipped", "SKIPPED", "no qa.start in the registry: there is no screen to take pictures of", 0, 64),
             st("r1:pilot", "Pilot (round 1)", "pilot", "skipped", "SKIPPED", "no qa.start in the registry: there is no screen to drive", 0, 64),
             st("r1:inspector", "Inspector (round 1)", "inspector", "done", "UNPROVEN", "#78: no test exercises the empty-currency case", 0.52, 64),
             st("caulk1", "Caulker (cycle 1)", "caulker", "done", "SEALED", "#78: cycle 1 of 3: guard the empty list", 0.47, 52),
             st("r2:surveyor", "Surveyor (round 2)", "surveyor", "done", "CLEAN", "#78", 0.39, 44),
             st("r2:marshal", "Marshal (round 2)", "marshal", "done", "CLEAN", "#78: three seats, nothing found", 0.98, 44),
             st("r2:inspector", "Inspector (round 2)", "inspector", "done", "PROVEN", "#78: the new test fails without the guard", 0.5, 44),
             {"id": "human", "title": "Human review", "duty": "human", "state": "waiting", "verdict": "WAITING", "url": "", "cost": 0, "runs": [],
              "detail": "a person reads the pull request and merges it"}]
        b = [st("purser", "Purser", "purser", "done", "READY", "#31: 3 requirement(s)", 0.29, 1500),
             st("panel", "Dev panel", "panel", "done", "RULED", "dev: 2 of 3 on issue #31", 1.38, 1496)]
        return {**self.cycles_started,
            f"cyc-wayfarer-web-29-{int(self.t0) - 5400}": {
                "kind": "cycle", "id": f"cyc-wayfarer-web-29-{int(self.t0) - 5400}", "project": "wayfarer-web", "issue": 29, "title": "Remember the last-used currency",
                "apply": True, "status": "awaiting-review", "started": self.ago(minutes=92), "finished": self.ago(minutes=41), "seconds": 3060,
                "final": f"The pull request https://github.com/{ORG}/wayfarer-web/pull/78 is open with no open findings on its current head. A person reads it and merges it; nothing here merges, approves or pushes to the trunk.",
                "pr": f"https://github.com/{ORG}/wayfarer-web/pull/78", "prnum": 78, "stages": a, "cost": round(sum(x["cost"] for x in a), 4),
                "notes": ["the assayer proposed tests as their own pull request. Merge it only if you agree with them."]},
            f"cyc-harvest-pipeline-31-{int(self.t0) - 90000}": {
                "kind": "cycle", "id": f"cyc-harvest-pipeline-31-{int(self.t0) - 90000}", "project": "harvest-pipeline", "issue": 31, "title": "Skip empty partitions in the nightly load",
                "apply": True, "status": "stopped-cap", "started": self.ago(minutes=1505), "finished": self.ago(minutes=1494), "seconds": 660,
                "final": "stopped at the cap: $119.82 of today's $120 is spent, so the next stage (shipwright) was not started. Nothing was lost. After the cap resets or is raised (QUARTERDECK_DAILY_BUDGET): qtdeck cycle --resume <id>",
                "pr": None, "prnum": None, "stages": b, "cost": round(sum(x["cost"] for x in b), 4), "notes": []}}

    def cycle_projects(self):
        return {"wayfarer-web"}

    def cycle_start(self, project, issue, confirm):
        """The Start a full cycle button, in Demo mode: an invented record appears in the list and nothing runs."""
        if project not in self.cycle_projects():
            return 400, {"error": f"'{project}' has not opted in to full cycles: add \"cycle\": true to its registry entry"}
        if type(issue) is not int or not 0 < issue < 10 ** 7:
            return 400, {"error": "bad issue"}
        if confirm is not True:
            return 400, {"error": "a cycle spends money and writes a branch and a pull request: confirm it"}
        if any(r["project"] == project and r["issue"] == issue and r["status"] == "running" for r in self.cycle_records().values()):
            return 409, {"error": f"a cycle for #{issue} on {project} is already running"}
        cid = f"cyc-{project}-{issue}-{int(self.t0 + self.elapsed())}"
        now = iso(datetime.fromtimestamp(self.t0 + self.elapsed(), timezone.utc))
        self.cycles_started[cid] = {"kind": "cycle", "id": cid, "project": project, "issue": issue, "title": ISSUES[project].get(issue, ("an issue",))[0], "apply": True,
                                    "status": "running", "started": now, "finished": None, "seconds": None, "final": "", "pr": None, "prnum": None,
                                    "stages": [{"id": "purser", "title": "Purser", "duty": "purser", "state": "running", "verdict": "", "detail": "", "url": "", "cost": 0,
                                                "runs": [], "started": now}], "cost": 0, "notes": []}
        return 200, {"started": f"cycle {project} --issue {issue}", "id": cid}

    def mockup_page(self, bid, name):
        return self.maker.mockup_page(bid, name) if self.maker else None

    def cycle_record(self, cid):
        return self.cycle_records().get(cid)

    def cycle_list(self):
        return [{"id": r["id"], "project": r["project"], "issue": r["issue"], "title": r["title"], "status": r["status"], "apply": r["apply"],
                 "started": r["started"], "finished": r["finished"], "cost": r["cost"], "pr": r["pr"]}
                for r in sorted(self.cycle_records().values(), key=lambda x: x["started"], reverse=True)]

    def open_prs(self, t, project=None):
        running, finished, _ = self.timeline(t)
        prs = []
        for pr_project, n, title, branch, issue, add, dele, files, failing, review in BASE_PRS:
            if (pr_project, n) in {(m[0], m[2]) for m in self.merged}:
                continue
            prs.append(self._pr(pr_project, n, title, branch, issue, add, dele, files, failing, review,
                                self.ago(hours=19 - n % 9), None, t))
        for j in finished:
            if not j.get("pr") or (j["project"], j["pr"]) in {(m[0], m[2]) for m in self.merged}:
                continue
            title = ISSUES[j["project"]].get(j.get("issue"), ("Change", ""))[0]
            rv = None
            for k in finished:                      # the crew's word on this PR, once it has been given
                if k.get("target") == j["pr"] and k["project"] == j["project"]:
                    rv = (k["verdict"], k["detail"].split(" ", 1)[1] if " " in k["detail"] else k["detail"], self.at(k["end"]), k["duty"])
            prs.append(self._pr(j["project"], j["pr"], title, f"fix/{j['issue']}-{re.sub('[^a-z0-9]+', '-', title.lower())[:24].strip('-')}", j["issue"],
                                96 + j["pr"] % 40, 14 + j["pr"] % 11, 3 + j["pr"] % 4, None, None, self.at(j["end"]), rv, t, opened_at=j["end"]))
        prs.sort(key=lambda p: p["created"], reverse=True)
        return [p for p in prs if not project or p["project"] == project]

    def _pr(self, project, n, title, branch, issue, add, dele, files, failing, review, created, rv, t, opened_at=None):
        sha = f"{(n * 2654435761) % 16 ** 12:012x}"
        age = (t - opened_at) if opened_at is not None else 99999
        pending = 2 if age < 25 else 0
        passing = 4 - pending - (1 if failing else 0)
        verdict = None
        if review:
            verdict = {"verdict": review[0], "detail": f"#{n} {review[1]}", "at": self.ago(hours=17), "sha": sha, "outdated": False}
        if rv and rv[3] == "surveyor":
            verdict = {"verdict": rv[0], "detail": rv[1] if rv[1].startswith("#") else f"#{n} {rv[1]}", "at": rv[2], "sha": sha, "outdated": False}
        verify = {"verdict": rv[0], "detail": f"#{n} {rv[1]}", "at": rv[2], "sha": sha, "outdated": False} if rv and rv[3] == "inspector" else None
        return {"project": project, "number": n, "title": title, "url": self._slug_pr(project, n), "branch": branch, "base": "main",
                "created": created, "draft": False, "head_sha": sha, "mergeable": "MERGEABLE", "merge_state": "CLEAN" if not failing else "UNSTABLE",
                "closes": [issue], "review_decision": "", "size": {"add": add, "del": dele, "files": files},
                "checks": {"pass": passing, "fail": 1 if failing else 0, "pending": pending, "failing": [failing] if failing else []},
                "by_quarterdeck": True, "from_item": None, "review": verdict, "verify": verify}

    def progress(self, project, t):
        issues = ISSUES[project]
        prs = self.open_prs(t, project)
        inrev = {i for p in prs for i in p["closes"]}
        closed = sum(1 for v in issues.values() if v[1] == "CLOSED")
        return {"total": len(issues), "closed": closed, "open": len(issues) - closed,
                "in_review": len(inrev & {n for n, v in issues.items() if v[1] == "OPEN"}),
                "titles": {str(n): v[0] for n, v in issues.items()}}

    # ---- the board and one card (invented) ----
    def board(self, project):
        issues = ISSUES[project]
        prs = {b[4]: b for b in BASE_PRS if b[0] == project}
        free = sorted((n for n, v in issues.items() if v[1] == "OPEN" and n not in prs), key=lambda n: (n == 15, n))      # 15 stays in the Backlog, with the purser's requirements
        status = {}
        for n, (title, st) in issues.items():
            status[n] = "Done" if st == "CLOSED" else "In review" if n in prs else None
        for k, n in enumerate(free):
            status[n] = ("In progress", "Ready")[k] if k < 2 else "Backlog"
        repo = f"wayfarer-demo/{project}"
        rows = []
        for n, (title, st) in sorted(issues.items(), reverse=True):
            row = {"item_id": f"PVTI_demo_{project}_{n}", "status": status[n], "priority": BOARD_PRIORITY.get(n), "size": "S" if n % 2 else "M",
                   "number": n, "type": "Issue", "title": title, "url": f"https://github.com/{repo}/issues/{n}", "state": st,
                   "idle_days": 2 + n % 40, "labels": ["bug"] if "rash" in title or "flicker" in title else ["enhancement"],
                   "open_prs": [{"number": prs[n][1], "state": "OPEN", "draft": False}] if n in prs else []}
            rows.append(row)
        return {"owner": "wayfarer-demo", "number": "1", "repo": repo,
                "columns": {"todo": "Backlog", "ready": "Ready", "doing": "In progress", "review": "In review", "done": "Done"},
                "fields": [{"name": "Status", "id": "PVTSSF_demo", "options": [{"name": c, "id": f"opt_{i}"} for i, c in enumerate(BOARD_COLUMNS)]}],
                "items": rows, "missing_from_board": []}

    def card(self, project, number, kind, t):
        pr = kind == "pr"
        if pr:
            hit = next((b for b in BASE_PRS if b[0] == project and b[1] == number), None)
            title, state = (hit[2], "OPEN") if hit else (None, None)
        else:
            title, state = ISSUES[project].get(number, (None, None))
        if title is None:
            return None
        repo = f"wayfarer-demo/{project}"
        body = CARD_BODIES.get((project, number)) or f"{title}.\n\nThis card is part of the invented demo world, so its text is short.\n\n- [x] Looked into it\n- [ ] Not started yet\n"
        base = datetime.fromtimestamp(self.t0, timezone.utc)
        comments = [{"author": a, "at": iso(base + timedelta(hours=h)), "body": b} for a, h, b in CARD_COMMENTS.get((project, number), [])]   # h: hours from now, negative = ago
        linked = []
        if pr:
            hit = next(b for b in BASE_PRS if b[0] == project and b[1] == number)
            linked = [{"kind": "issue", "number": hit[4], "state": ISSUES[project].get(hit[4], ("", "OPEN"))[1], "url": f"https://github.com/{repo}/issues/{hit[4]}"}]
        else:
            hit = next((b for b in BASE_PRS if b[0] == project and b[4] == number), None)
            if hit:
                linked = [{"kind": "pr", "number": hit[1], "state": "OPEN", "url": f"https://github.com/{repo}/pull/{hit[1]}"}]
        return {"kind": kind, "number": number, "title": title, "state": state, "url": f"https://github.com/{repo}/{'pull' if pr else 'issues'}/{number}",
                "draft": False, "author": "mina-demo", "labels": ["bug"] if "rash" in title or "lint" in title.lower() else ["enhancement"],
                "assignees": ["jonas-demo"] if number % 2 == 0 else [], "milestone": "Beta 2" if number % 3 == 0 else "",
                "created": iso(base - timedelta(days=9 + number % 5)), "updated": iso(base - timedelta(days=1)),
                "body": body, "body_cut": False, "comments": comments, "comments_more": 0, "linked": linked}

    # ---- panels and documents ----
    def panel_list(self):
        out = []
        for pid, project, disc, subject, headline, hours, ruling in PANELS:
            items = [{"id": i + 1, "seat": s} for i, s in enumerate(["shipwright", "surveyor", "signaller", "steward"][:len(ruling)])]
            out.append({"id": pid, "project": project, "discipline": disc, "mode": "panel", "subject": subject, "headline": headline,
                        "status": "done", "phase": "closed", "started": self.ago(hours=hours, minutes=14), "finished": self.ago(hours=hours),
                        "seats": ["dockmaster", "shipwright", "surveyor", "signaller"], "doc": self.doc_name(project, disc, hours),
                        "filed": {"state": "filed", "issues": [{"number": n} for n in ISSUES[project] if ISSUES[project][n][1] == "OPEN"][:len(ruling)], "at": self.ago(hours=hours - 1)},
                        "raised": len(ruling) + 2, "disputed": 2, "top_dispute": {"by": "surveyor", "against": "shipwright", "n": 2},
                        "kept": len(ruling), "superseded_by": None})
        return out

    def doc_name(self, project, disc, hours):
        d = (datetime.fromtimestamp(self.t0, timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")
        return f"{project}-{'joiner' if disc == 'design' else 'plan' if disc == 'dev' else 'requirements'}-{d}.md"

    def panel_transcript(self, pid):
        for p, row in zip(PANELS, self.panel_list()):
            if p[0] == pid:
                ruling = [{"title": t, "severity": sev, "tier": tier, "kind": kind, "area": area, "claim": claim, "where": where, "action": act}
                          for t, sev, tier, kind, area, claim, where, act in p[6]]
                items = [{"id": i + 1, "seat": s, "title": r["title"]} for i, (s, r) in enumerate(zip(["shipwright", "surveyor", "signaller", "steward"], ruling))]
                stances = [{"id": 1, "by": "surveyor", "stance": "dispute", "note": "The first item is too broad to land in one change; split it by screen."},
                           {"id": 2, "by": "shipwright", "stance": "dispute", "note": "The contrast figure was measured on one screen only."},
                           {"id": 1, "by": "signaller", "stance": "agree", "note": "It touches every screen, so one pass is the safe way."}]
                return {"id": pid, "project": p[1], "discipline": p[2], "mode": "panel", "subject": p[3], "headline": p[4],
                        "status": "done", "phase": "closed", "started": row["started"], "finished": row["finished"], "seats": row["seats"],
                        "items": items, "stances": stances, "ruling": ruling, "doc": "workspace/" + row["doc"], "verdict": "ruled"}
        return None

    def docs(self):
        out = []
        for row in self.panel_list():
            kind = {"design": "findings", "dev": "dev", "spec": "requirements"}.get(row["discipline"], "other")
            label = {"findings": "findings", "dev": "implementation plan", "requirements": "requirements"}[kind]
            out.append({"name": row["doc"], "project": row["project"], "at": row["finished"], "size": 4100 + 311 * len(row["doc"]),
                        "filed": row["filed"], "superseded_by": None, "kind": kind, "kind_label": label, "fileable": kind == "findings"})
        out.append({"name": "saltpan-blog-joiner-2026-10-02.md", "project": "saltpan-blog", "at": self.ago(days=3), "size": 3302,
                    "filed": None, "superseded_by": None, "kind": "findings", "kind_label": "findings", "fileable": True})
        return out

    def doc_text(self, name):
        for d in self.docs():
            if d["name"] == name:
                t = next((self.panel_transcript(p[0]) for p in PANELS if p[1] == d["project"] and self.doc_name(p[1], p[2], p[5]) == name), None)
                lines = [f"# {name[:-3].replace('-', ' ').capitalize()}", "", "Made-up document for the demo.", ""]
                for i, r in enumerate((t or {}).get("ruling", [])):
                    lines += [f"## {i + 1}. {r['title']}", "", r["claim"], "", f"Where: {r['where']}", "", f"Do: {r['action']}", ""]
                if not t:
                    lines += ["## 1. Recipe cards crowd the photo", "", "On a narrow screen the ingredients wrap under the photo.", ""]
                return "\n".join(lines)
        return None

    def log_lines(self, name, n):
        project = next((p for p in PROJECTS if name.endswith("-" + p)), "wayfarer-mobile")
        duty = name[:-(len(project) + 1)] if name.endswith("-" + project) else name
        rows = [r for r in self.base if r["project"] == project and r["duty"] == duty][-6:]
        lines = []
        for r in rows:
            lines += [f"[{r['at']}] started by schedule", f"{duty}: {project}: {r['detail']}", f"verdict {r['verdict']}"]
        return lines[-n:] or [f"[{self.ago(minutes=5)}] nothing logged yet"]

    def log_names(self):
        names = {f"{d}-{p}" for p, v in PROJECTS.items() for d in v["duties"] if d in ("surveyor", "shipwright", "panel")}
        return sorted(names | {"quarterdeck"}.union(*(x.logs() for x in self.EXT)))

    # ---- the outside world ----
    def connectors(self, t):
        lst = lambda m, **k: dict(at=self.ago(minutes=m), **k)
        now = datetime.fromtimestamp(self.t0 + t, timezone.utc).astimezone()
        today = lambda h, m: iso(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=h, minutes=m))
        soon = lambda mins: iso(datetime.fromtimestamp(self.t0, timezone.utc) + timedelta(minutes=mins))
        day = lambda d, h, m: iso(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=d, hours=h, minutes=m))
        fixed = {
            "gmail": [("Invoice 2026-114 from the print shop", "accounts@printshop.example", 190, False), ("Weekly planning notes", "Sam", 410, False),
                      ("Conference travel: confirmation", "Booking", 700, False), ("Re: weekly planning notes", "Sam", 1900, False)],
            "slack": [("Priya (DM)", "can you look at the release notes?", 120, False), ("Lee (DM)", "lunch at 12?", 260, False)],
            "drive": [("Q4 roadmap draft", "Edited by Sam", 340, False), ("Brand colours", "Shared with you", 1500, False)],
            "analytics": [("Last 7 days: 18,420 views", "6,310 users, 9,870 sessions, views +14% vs last week", 90, False),
                          ("Pumpkin soup with sage", "1,120 views, +3% vs last week", 90, False), ("Weeknight lentil dal", "980 views, +22% vs last week", 90, False),
                          ("Kitchen scale buying guide", "760 views, -8% vs last week", 90, False), ("Newsletter archive", "410 views, no change vs last week", 90, False),
                          ("Source: Organic Search", "6,120 sessions", 90, False), ("Source: Direct", "2,310 sessions", 90, False), ("Source: Email", "980 sessions", 90, False)],
            "linkedin": [("Shipping a trip planner with three agents", "1,480 impressions, 33 reactions, 5 comments", 1500, False),
                         ("Why the sync queue replays in order", "890 impressions, 18 reactions, 2 comments", 4300, False),
                         ("Release notes are a product surface", "1,020 impressions, 24 reactions, 3 comments", 7200, False),
                         ("Notes from a design review", "640 impressions, 11 reactions, 1 comments", 10100, False),
                         ("Small diffs, fast reviews", "720 impressions, 15 reactions, 4 comments", 13000, False),
                         ("Offline first is a feature, not a mode", "560 impressions, 9 reactions, 0 comments", 16000, False)],
            "facebook": [("Pumpkin soup is back on the menu", "42 reactions, 6 comments, 3 shares, 1,900 impressions", 300, False),
                         ("Saturday market haul", "28 reactions, 2 comments, 0 shares, 1,100 impressions", 3000, False),
                         ("Newsletter issue 41 is out", "19 reactions, 1 comments, 2 shares, 800 impressions", 5800, False)],
            "instagram": [("Pancake stack, golden hour", "612 likes, 21 comments, 7,300 reached", 500, False),
                          ("Lentil dal in the pot", "340 likes, 9 comments, 4,100 reached", 2900, False),
                          ("Market morning", "281 likes, 7 comments, 3,500 reached", 5700, False)],
        }
        labels = {"gmail": "Gmail", "calendar": "Calendar", "reminders": "Reminders", "slack": "Slack", "drive": "Drive",
                  "analytics": "Analytics", "linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}
        out = []
        for name in ("gmail", "calendar", "reminders", "slack", "drive", "analytics", "linkedin", "facebook", "instagram"):
            if name == "calendar":
                items = [dict(title="Sprint planning", sub="Room 2 · on 2 calendars", at=soon(16), new=False),
                         dict(title="Design review: onboarding flow", sub="Video call", at=soon(180), new=False),
                         dict(title="1:1 with Priya", sub="Room 4", at=day(1, 10, 0), new=False),
                         dict(title="Release freeze", sub="All day", at=day(1, 0, 0), new=False)]
                out.append({"name": name, "label": labels[name], "connected": True, "updated": self.ago(minutes=4), "unread": None,
                            "items": [{"title": i["title"], "sub": i["sub"], "at": i["at"], "new": False, "url": None} for i in items]})
                continue
            if name == "reminders":
                items = [("Renew the domain", day(-1, 9, 0)), ("Book the dentist", soon(240)), ("Send the October invoice", soon(3.5)), ("Look into standing desks", "")]
                out.append({"name": name, "label": labels[name], "connected": True, "updated": self.ago(minutes=4), "unread": None,
                            "items": [{"title": ti, "sub": "", "at": at, "new": False, "url": None} for ti, at in items]})
                continue
            items = [{"title": ti, "sub": sub, "at": self.ago(minutes=m), "new": nw, "url": None} for ti, sub, m, nw in fixed[name]]
            arrivals = [(s, it) for s, c, it in SCENARIO_DROPS if c == name and t >= s]
            newest = [{"title": it["title"], "sub": it["sub"], "at": self.at(s), "new": True, "url": None} for s, it in reversed(arrivals)]
            items = newest + items
            out.append({"name": name, "label": labels[name], "connected": True, "updated": self.at(arrivals[-1][0]) if arrivals else self.ago(minutes=7),
                        "unread": (len(arrivals) + len(fixed[name])) if name in ("gmail", "slack") else None, "items": items[:12]})
        return out

    # ---- memory ----
    def memory(self):
        data = {
            "wayfarer-mobile": ["feedback:Prefers the smallest change that works:Keep diffs small, no drive-by refactors", "project:Offline cache design:Write-through queue, replayed in order on reconnect",
                                "reference:Store review checklist:What App Review rejected last time", "project:Release train:Builds go out on Tuesdays", "feedback:Haptics are opt-in:Never vibrate for errors",
                                "project:Push notification digest idea:One digest instead of one per event", "reference:Design tokens:Where the colour and spacing tokens live"],
            "wayfarer-web": ["project:Dark mode plan:Tokens first, then components", "feedback:No new dependencies without a reason:Stdlib and what is already installed",
                             "reference:Browser support:Last two versions, no IE", "project:Print stylesheet:Itinerary prints on one page"],
            "wayfarer-api": ["project:Idempotency keys:Required header, first result stored per key", "reference:Rate limits:100 per minute per key",
                             "feedback:Errors are 4xx with a message:Never leak internals in a 500", "project:Pagination:Cursor based, never offset", "reference:Staging deploy:Needs an approval click"],
            "harvest-pipeline": ["project:Late rows:Reprocess the last two days every night", "reference:Warehouse limits:Loads time out after 90 seconds", "feedback:Counts must reconcile:Row counts in and out"],
            "saltpan-blog": ["project:Recipe schema:Structured data for every recipe", "feedback:Short sentences:Plain voice, no hype", "reference:Newsletter schedule:Thursdays at 7", "project:Photo style:Natural light, wooden board"],
            "home": ["user:Works in short focused blocks:Prefers a calm screen", "feedback:Ask before anything outward-facing:Drafts are fine, sending is not", "reference:Where notes live:Brain dump first, filed weekly"],
        }
        projects = []
        for k, (slug, rows) in enumerate(data.items()):
            items, types = [], {}
            for i, r in enumerate(rows):
                typ, name, desc = r.split(":", 2)
                types[typ] = types.get(typ, 0) + 1
                items.append({"name": name, "desc": desc, "type": typ, "at": self.ago(hours=2 + 5 * i + k * 3)})
            projects.append({"slug": slug, "label": slug, "count": len(items), "types": types, "items": items, "newest": items[0]["at"],
                             "fresh": sum(1 for i in items if i["at"] > self.ago(days=1)), **({"project": slug} if slug in PROJECTS else {})})
        return {"projects": sorted(projects, key=lambda p: -p["count"]), "total": sum(p["count"] for p in projects), "skills": 24,
                "backup": {"last": self.ago(minutes=22), "stale": False}}

    # ---- brain dump, inbox, spend ----
    def _base_notes(self):
        rows = [("a1b2c3d4", dict(hours=3), "Ask design for the empty-state illustration", "wayfarer-mobile", False),
                ("a1b2c3d5", dict(hours=26), "Try one push notification digest instead of one per event", "wayfarer-mobile", False),
                ("a1b2c3d6", dict(hours=50), "Book the dentist before the release freeze", "", False),
                ("a1b2c3d7", dict(hours=70), "Write down why the sync queue replays in order", "wayfarer-api", False),
                ("a1b2c3d8", dict(hours=100), "Renew the domain for the blog", "saltpan-blog", True)]
        return {i: {"id": i, "at": self.ago(**when), "text": text, "project": project, "done": done, "updated": self.ago(**when), "promoted": None}
                for i, when, text, project, done in rows}

    def captures_view(self):
        rows = sorted(self.notes.values(), key=lambda r: r["at"], reverse=True)
        open_, done = [r for r in rows if not r["done"]], [r for r in rows if r["done"]]
        return {"items": open_[:200], "open": len(open_), "done": done[:200], "total": len(rows), "path": "state/capture.jsonl"}

    def inbox(self, t, runs):
        items = [i for x in self.EXT for i in x.inbox(self, t, runs)]
        last = {}
        for r in runs:
            last[(r["project"], r["duty"])] = r
        for (project, duty), r in last.items():
            if r["verdict"] in ("NEEDS_HUMAN", "BLOCKED", "ERROR", "FAILED"):
                key = f"local:{project}:{duty}:{r['at']}"
                items.append({"id": key, "source": "local", "project": project, "duty": duty, "severity": r["verdict"], "text": r["detail"] or r["verdict"],
                              "at": r["at"], "stale": False, "acknowledged": key in self.acks})
        return items

    def spend(self, t):
        rows = list(self.spend_rows)
        for j in self.timeline(t)[1]:
            rows.append({"at": self.at(j["end"]), "duty": j["duty"], "model": "sonnet", "turns": 12, "cost": j.get("cost", 0.3),
                         **({"fix": f"{PANELS[j['panel']][0]}#{j['item']}"} if j.get("panel") is not None else {})})
        now = datetime.fromtimestamp(self.t0 + t, timezone.utc)
        midnight = iso(now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0))
        week = iso(now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6))
        wk = [r for r in rows if r["at"] >= week]
        def group(key):
            out = {}
            for r in wk:
                g = out.setdefault(r.get(key) or "unknown", {"cost": 0.0, "calls": 0, "turns": 0})
                g["cost"] += r["cost"]; g["calls"] += 1; g["turns"] += r.get("turns") or 0
            return dict(sorted(out.items(), key=lambda kv: -kv[1]["cost"]))
        by_day = {}
        for r in wk:
            d = datetime.fromisoformat(r["at"].replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
            by_day[d] = by_day.get(d, 0) + r["cost"]
        fixes = {}
        for r in rows:
            if r.get("fix"):
                f = fixes.setdefault(r["fix"], {"cost": 0.0, "calls": 0})
                f["cost"] += r["cost"]; f["calls"] += 1
        return {"today": sum(r["cost"] for r in rows if r["at"] >= midnight), "week": sum(r["cost"] for r in wk), "all": sum(r["cost"] for r in rows),
                "calls": len(rows), "since": min(r["at"] for r in rows), "daily_budget": 25.0, "over_budget": False, "call_budget": None,
                "planning": "tiered", "by_duty": group("duty"), "by_model": group("model"), "by_day": dict(sorted(by_day.items())), "fixes": fixes,
                "roles": {k: "account default" for k in ("foreman", "shipwright", "surveyor", "inspector", "joiner", "harbourmaster", "trials")},
                "tiers": {k: "account default" for k in ("mechanical", "routine", "intricate", "hard")}, "capped": 0}

    def schedules(self):
        if self.sched is None:
            self.sched = [{"id": "5e1a0c11", "project": "wayfarer-mobile", "duty": "surveyor", "args": [], "apply": False, "every": "1h", "at": "",
                           "paused": False, "created": self.ago(days=6), "last_run": self.ago(minutes=42)},
                          {"id": "5e1a0c12", "project": "harvest-pipeline", "duty": "trials", "args": [], "apply": False, "every": "", "at": "02:30",
                           "paused": False, "created": self.ago(days=6), "last_run": self.ago(hours=11)}]
        out = []
        for s in self.sched:
            secs = None if s.get("paused") else (1080 if s["every"] else 54000)
            out.append({**s, "next_due": iso(datetime.fromtimestamp(self.clock() + secs, timezone.utc)) if secs else None, "seconds_until": secs})
        return sorted(out, key=lambda x: (x["seconds_until"] is None, x["seconds_until"] or 0))

    def missions(self):
        base = [{"id": "m-demo00000001", "project": "wayfarer-mobile", "objective": "Make the trip list usable on a plane with no signal",
                 "constraints": "No new dependencies. Keep the first paint under one second.", "success_criteria": "Airplane mode shows yesterday's list.",
                 "status": "draft", "created_at": self.ago(days=1), "updated_at": self.ago(hours=5),
                 "links": {"panels": [PANELS[0][0]], "runs": [], "fixes": [], "issues": [14], "prs": [], "documents": []},
                 "plan": None, "plan_revision": 0, "plan_approved_revision": None, "plan_approved_at": None,
                 "events": [{"at": self.ago(days=1), "kind": "created", "detail": "draft created", "source": "dashboard"}]}]
        return base + self.mission_extra

    # ---- the assembled state ----
    def state(self):
        t = self.elapsed()
        runs = self.runs(t)
        running, _, _ = self.timeline(t)
        panels = self.panel_list()
        fixes = self.fixes(t)
        out = {
            "now": iso(datetime.fromtimestamp(self.t0 + t, timezone.utc)),
            "demo": {"on": True, "seconds": int(t), "settled": t >= SETTLE, "label": "DEMO DATA"},
            "agents": self.agents(t, runs, DUTIES),
            "crew": [{"name": n, "discipline": d, "panels": d.split(","), "seat": s, "bias": b} for n, d, s, b in CREW],
            "missions": self.missions(), "showcase": self.showcase,
            "inbox": self.inbox(t, runs), "panels": panels, "fixes": fixes, "cycles": self.cycle_list(), "fixqueue": self.queue,
            "briefs": self.maker.summary() if self.maker else [], "plans": self.maker.plan_summary() if self.maker else [],
            "spend": self.spend(t), "schedules": self.schedules(), "docs": self.docs(),
            "projects": [{"name": k, "repo": f"{ORG}/{k}", "summary": v["summary"], "duties": v["duties"], "guardrails": GUARDRAILS,
                          "verify": v["verify"], "board": None, "cycle": k == "wayfarer-web"} for k, v in sorted(PROJECTS.items())],
            "duties": [{"name": n, "summary": f"{n}: {s}", "role": s} for n, s in DUTIES],
            "runs": runs[-200:][::-1],
            "system": {"dry_run": True, "model": "demo", "max_items": "5", "timeout": "900", "rounds": "2", "running": len(running)},
            "helm_chat": {"claude": "off", "model": "claude-haiku-4-5", "turn": 0.05, "daily": 1.0, "spent": 0.0},      # the deep brain is never on in demo mode
            "logs": self.log_names(), "captures": self.captures_view(),
            "agenda_status": {"events": 4, "reminders": 4, "at": self.ago(minutes=4)},
            "integrations": {n: {"ok": not (n == "facebook" and t >= FEED_BREAKS), "at": self.ago(minutes=m), "seconds": 2,
                                 "error_short": "token expired" if n == "facebook" and t >= FEED_BREAKS else ""}
                             for n, m in (("ga4", 11), ("gmail", 6), ("slack", 3), ("linkedin", 55), ("facebook", 19), ("instagram", 19))},
            "connectors": self.connectors(t), "memory": self.memory(),
        }
        for x in self.EXT:
            out.update(x.state(self, t, runs))
        return out

    # ---- reads ----
    def get(self, path, query):
        """(status, json-able) for a GET path, or None for a path demo mode does not answer."""
        t = self.elapsed()
        q = lambda k, d="": (query.get(k) or [d])[0]
        got = self.maker.get(path, query) if self.maker else None
        if got:
            return got
        if path == "/api/state":
            return 200, self.state()
        if path == "/api/showcase/public":
            return 200, []
        if path == "/api/attention":
            return 200, self.attention(t)
        if path == "/api/intent":
            return 200, self.intent_view()
        if path == "/api/rhythm":
            return 200, self.rhythm()
        if path == "/api/connections":
            return 200, self.connections()
        if path == "/api/settings":
            return 200, {"data_folder": "~/.quarterdeck-demo", "data_why": "demo data is made up and kept in memory", "program_folder": "~/quarterdeck", "env_files": [],
                         "dry_run": True, "model": "account default", "sandbox": True, "voice": "am_liam", "voice_speed": "1.05", "attention": True,
                         "commit": "demo", "uptime_seconds": 3600, "projects": len(PROJECTS)}
        if path == "/api/fleet/projects":
            return 200, {"projects": ["wayfarer-api"]}
        if path == "/api/fleet":
            return 200, self.fleet()
        if path == "/api/timeline":
            window = q("window", "24h")
            if window not in ("6h", "24h", "7d"):
                return 400, {"error": "window must be 6h, 24h or 7d"}
            return 200, self.timeline_view(window, t)
        if path == "/api/log":
            return 200, {"lines": self.log_lines(q("name", "quarterdeck"), min(int(q("n", "200") or 200), 2000))}
        if path == "/api/board":
            if q("project") not in PROJECTS:
                return 400, {"error": "unknown project"}
            return 200, {"board": self.board(q("project")), "fetched": self.at(t), "url": "https://github.com/users/wayfarer-demo/projects/1"}
        if path == "/api/card":
            if q("project") not in PROJECTS:
                return 400, {"error": "unknown project"}
            kind, num = q("kind", "issue"), q("number")
            if kind not in ("issue", "pr") or not re.fullmatch(r"[1-9]\d{0,6}", num or ""):
                return 400, {"error": "bad number"}
            c = self.card(q("project"), int(num), kind, t)
            return (200, {"card": c, "fetched": self.at(t)}) if c else (404, {"error": "no such card"})
        if path == "/api/progress":
            if q("project") not in PROJECTS:
                return 400, {"error": "unknown project"}
            return 200, self.progress(q("project"), t)
        if path == "/api/prs":
            name = q("project")
            if name and name not in PROJECTS:
                return 400, {"error": "unknown project"}
            return 200, {"prs": self.open_prs(t, name or None), "errors": {}, "fetched": iso(datetime.fromtimestamp(self.t0 + t, timezone.utc))}
        if path == "/api/panel":
            tx = self.panel_transcript(q("id"))
            return (200, tx) if tx else (404, {"error": "no such panel"})
        if path == "/api/doc":
            text = self.doc_text(q("name"))
            return (200, {"name": q("name"), "text": text}) if text is not None else (404, {"error": "no such document"})
        return None

    # Invented attention (commits and meetings only): harvest-pipeline picks up this week, wayfarer-mobile went quiet weeks ago, and the focus the demo
    # starts with (wayfarer-web and saltpan-blog) is not where the time went. Nothing real is read, and it is the same
    # shape /api/attention returns for real data.
    def attention(self, t):
        today = datetime.strptime(self.today(), "%Y-%m-%d")
        days = {name: {} for name in PROJECTS}
        cal = {}
        for back in range(0, 46):
            d = today - timedelta(days=back)
            if d.weekday() >= 5:
                continue
            key = d.strftime("%Y-%m-%d")
            commits = {"harvest-pipeline": 4 if back < 7 else 1,              # clearly more than the week before
                       "saltpan-blog": 1, "wayfarer-api": 2,
                       "wayfarer-web": 1 if back % 7 == 3 else 0,
                       "wayfarer-mobile": 2 if back >= 27 else 0}              # last real work 27 or more days ago
            for name, n in commits.items():
                if n:
                    days[name][key] = {"commits": n, "files": 3 * n}
            cal[key] = {"meetings": 2}
        days["(calendar)"] = cal
        return {"on": True, "updated": self.at(t), "estimated": True, "days": {p: v for p, v in days.items() if v}}

    def _start_focus(self):
        d = datetime.fromtimestamp(self.t0, timezone.utc)
        mon = d - timedelta(days=d.weekday())
        return {"at": iso(d), "from": mon.strftime("%Y-%m-%d"), "to": (mon + timedelta(days=6)).strftime("%Y-%m-%d"),
                "projects": [{"name": "wayfarer-web", "share": 0.5}, {"name": "saltpan-blog", "share": 0.5}]}
    # ---- "My rhythm": a concept preview, invented and deterministic (the same every run). Demo mode only: the real server has no such route. ----
    RHYTHM_BADGE = "Concept preview: invented data, nothing is collected"

    def today(self):
        return datetime.fromtimestamp(self.t0 + self.elapsed(), timezone.utc).strftime("%Y-%m-%d")

    def intent_view(self):
        t = self.today()
        cur = [r for r in self.intents if r["from"] <= t <= r["to"]]
        return {"today": t, "current": cur[-1] if cur else None, "history": self.intents[-8:], "status": dict(self.pstatus)}

    def intent_post(self, path, b):
        """In memory only: demo mode never writes a file."""
        if b.get("confirm") is not True:
            return 400, {"error": "the owner has to confirm this"}
        t = self.today()
        if path == "/api/project-status":
            if b.get("project") not in PROJECTS or b.get("status") not in ("continue", "park", "archive"):
                return 400, {"error": "unknown project or status"}
            self.pstatus[b["project"]] = {"status": b["status"], "at": t}
            return 200, self.pstatus[b["project"]]
        ps = b.get("projects")
        if not isinstance(ps, list) or not 1 <= len(ps) <= 4:
            return 400, {"error": "pick 1 to 4 projects"}
        out = []
        for x in ps:
            name = x.get("name") if isinstance(x, dict) else x
            if name not in PROJECTS or any(o["name"] == name for o in out):
                return 400, {"error": "unknown project"}
            sh = x.get("share") if isinstance(x, dict) else None
            out.append({"name": name, **({"share": sh} if isinstance(sh, (int, float)) and not isinstance(sh, bool) and 0 < sh <= 1 else {})})
        d = datetime.strptime(t, "%Y-%m-%d") + timedelta(days=7 if b.get("week") == "next" else 0)
        mon = d - timedelta(days=d.weekday())
        rec = {"at": self.at(self.elapsed()), "from": mon.strftime("%Y-%m-%d"), "to": (mon + timedelta(days=6)).strftime("%Y-%m-%d"), "projects": out}
        self.intents.append(rec)
        return 200, rec
    # ---- Fleet: an invented fleet and an invented repository of agents, so the view can be shown with nothing real behind it ----
    FLEET_JOBS = [
        ("gull", "Gull", "Reviews open pull requests once per head commit.", "on", "in 3 min", 140,
         ["reviewed wayfarer-api#212 at 09:41: 2 findings", "reviewed wayfarer-web#88: clean"]),
        ("beacon", "Beacon", "Reads production alerts and opens a fix pull request when it can prove one.", "on", "in 1 min", 40,
         ["alert: timeout on /trips/export (3 in 10 min)", "fix opened: wayfarer-api#214"]),
        ("customs", "Customs", "Turns security findings into remediation runbooks. Read only.", "paused", "", 90000,
         ["14 findings on record, 2 high"]),
        ("ballast", "Ballast", "Verifies dependency bump pull requests and says whether each is safe.", "on", "in 22 min", 1500,
         ["bump left-pad 1.2.3 to 1.2.4: safe", "bump chart-lib 3.1 to 4.0: risky, a removed API is still used"]),
        ("ledger", "Ledger", "Reads meeting notes and keeps the backlog board honest.", "paused", "", 260000,
         ["3 items captured from the planning call"]),
    ]

    def fleet(self):
        st = getattr(self, "_fleet_state", None)
        if st is None:
            st = self._fleet_state = {j[0]: j[3] for j in self.FLEET_JOBS}
        jobs = [{"id": i, "name": n, "what": w, "state": st[i], "raw": "loaded" if st[i] == "on" else "NOT LOADED", "next": nxt if st[i] == "on" else "",
                 "last_activity_ago": ago, "log": lines, "actions": ["pause" if st[i] == "on" else "resume", "test"]}
                for i, n, w, _s, nxt, ago, lines in self.FLEET_JOBS]
        agents = [("planner", "Decides where a piece of work belongs: an existing service, a new one, or the frontend."),
                  ("builder", "Implements the change inside one service, with its tests."),
                  ("checker", "Writes the tests as the feature is built, from the acceptance checks."),
                  ("reviewer", "Reviews a change: correctness first, then boundaries and security."),
                  ("fixer", "Applies exactly the findings of a review and hands the branch back.")]
        return {"at": int(time.time()), "errors": [], "sources": [
            {"id": "fleet", "kind": "command-fleet", "project": "", "title": "Wayfarer agent fleet", "error": "",
             "about": "Invented for the demo. Nothing here is real, and pause, resume and run now change nothing.", "jobs": jobs},
            {"id": "repo", "kind": "repo-agents", "runs": "own", "crew": [], "implicit": False, "project": "wayfarer-api", "title": "Wayfarer API agents", "about": "Invented for the demo.",
             "agents": [{"name": n, "what": w, "model": "sonnet"} for n, w in agents],
             "commands": [{"name": "feature", "what": "Build a feature or fix through the full agent chain.", "hint": "what to build, in a sentence",
                           "chain": ["planner", "builder", "checker", "reviewer", "fixer"]},
                          {"name": "review", "what": "Review a branch, apply the findings, re-review, at most three times.", "hint": "branch or pull request",
                           "chain": ["reviewer", "fixer"]}],
             "worktrees": [
                 {"name": "wayfarer-api", "main": True, "branch": "develop", "changed": 0, "last_commit_ago": 3600, "touched_ago": 60, "ahead": 0, "behind": 0, "pr": None, "activity": "active", "stage": "clean"},
                 {"name": "agent-7f3a21", "main": False, "branch": "feat/trip-export-timezone", "changed": 4, "last_commit_ago": 1260, "touched_ago": 95, "ahead": 2, "behind": 3, "pr": None, "activity": "active", "stage": "working"},
                 {"name": "trip-cache", "main": False, "branch": "fix/offline-cache-keys", "changed": 0, "last_commit_ago": 7800, "touched_ago": 7500, "ahead": 3, "behind": 3,
                  "pr": {"number": 214, "title": "Fix offline cache keys for shared trips", "state": "open", "draft": False, "review": "review_required", "checks_ok": 5, "checks_bad": 1, "checks_wait": 0}, "activity": "active", "stage": "in review"},
                 {"name": "wayfarer-docs", "main": False, "branch": "docs/export-guide", "changed": 0, "last_commit_ago": 90000, "touched_ago": 90000, "ahead": 1, "behind": 9,
                  "pr": {"number": 208, "title": "Document the export format", "state": "merged", "draft": False, "review": "approved", "checks_ok": 6, "checks_bad": 0, "checks_wait": 0}, "activity": "idle", "stage": "merged"},
                 {"name": "wayfarer-spike", "main": False, "branch": "spike/map-clusters", "changed": 0, "last_commit_ago": 1900000, "touched_ago": 1900000, "ahead": 0, "behind": 80, "pr": None, "activity": "old", "stage": "clean"}],
             "sessions": [
                 {"id": "7c1e90aa", "state": "working", "worktree": "agent-7f3a21", "branch": "feat/trip-export-timezone", "turns": 6, "running_agents": ["builder"],
                  "agents_used": {"planner": 1, "builder": 2, "checker": 1}, "started_ago": 2700, "last_ago": 12},
                 {"id": "5b02d4cc", "state": "idle", "worktree": "trip-cache", "branch": "fix/offline-cache-keys", "turns": 3, "running_agents": [],
                  "agents_used": {"reviewer": 1, "fixer": 1}, "started_ago": 7000, "last_ago": 420},
                 {"id": "e0a9b811", "state": "ended", "worktree": "wayfarer-docs", "branch": "docs/export-guide", "turns": 2, "running_agents": [],
                  "agents_used": {"planner": 1}, "started_ago": 40000, "last_ago": 38000}]}]}

    def connections(self):
        """Invented services in each state, so the page can be seen full."""
        def row(i, label, what, state, ago, error="", cred=True, local=False):
            return {"id": i, "label": label, "what": what, "minutes": 10, "local": local, "steps": ["Made-up step one: open the service's settings.", "Made-up step two: create a read-only token.", "Made-up step three: paste it here and switch the service on."], "settings": [],
                    "reads": ["Made-up: a count and a few titles."], "not_reads": ["Made-up: nothing else is read."], "scopes": ["Made-up: read only."], "revoke": "Made-up: remove the token in the service's settings.",
                    "tested": "Demo text. Nothing here is tested because nothing here is real.", "verified": False, "links": [],
                    "credentials": [] if local else [{"key": i.upper() + "_TOKEN", "label": "Access token", "secret": True, "help": "Made-up help text.", "looks": "A made-up string of letters", "optional": False, "present": cred}], "enabled": state != "off" or local,
                    "state": state, "missing": [] if cred or local else [i.upper() + "_TOKEN"], "last_at": self.at(self.elapsed() - ago) if ago is not None else None, "error": error}
        return {"services": [row("calendar", "Calendar and reminders", "Today's events and what is due.", "ok", 120, local=True),
                             row("mail", "Mail", "How many messages are waiting.", "ok", 300),
                             row("analytics", "Site analytics", "Visitors and top pages.", "ok", 2400),
                             row("chat", "Team chat", "Unread mentions.", "failing", 5400, "The token was rejected. Paste a new one."),
                             row("social", "Social page", "Comments and messages.", "needs set-up", None, cred=False),
                             row("posts", "Post export", "Your posts and their numbers.", "off", None, cred=False)]}

    def fleet_action(self, b):
        job = next((j for j in self.FLEET_JOBS if j[0] == b.get("job")), None)
        if b.get("source") != "fleet" or not job or b.get("action") not in ("pause", "resume", "test"):
            return 400, {"error": "unknown job or action"}
        if b.get("confirm") is not True:
            return 400, {"error": "confirm is required: this starts or stops a real agent"}
        self.fleet()
        if b["action"] != "test":
            self._fleet_state[job[0]] = "paused" if b["action"] == "pause" else "on"
        return 200, {"ok": True, "message": "demo: nothing was started or stopped"}

    def rhythm(self):
        """Fourteen weeks of made-up actions (commits, pull requests, notes, agent runs started by hand) and calendar blocks. Mornings hold the
        long blocks, afternoons break up, Tuesday carries the meetings; nothing here is read from anywhere."""
        today = datetime.strptime(self.today(), "%Y-%m-%d")
        names = list(PROJECTS)
        events, meetings = [], []
        for back in range(0, 100):
            d = today - timedelta(days=back)
            key = d.strftime("%Y-%m-%d")
            rng = random.Random(f"rhythm{self.seed}{key}")
            wd = d.weekday()
            if wd >= 5:
                sessions = [(10 * 60 + rng.randint(0, 60), rng.randint(25, 50), 0.25)] if rng.random() < 0.3 else []
            else:
                short = rng.random() < 0.15                                    # now and then the morning is short
                sessions = [(8 * 60 + 30 + rng.randint(0, 45), rng.randint(60, 85) if short else rng.randint(115, 200), 0.15),
                            (13 * 60 + 30 + rng.randint(0, 40), rng.randint(40, 100), 0.3)]
                if rng.random() < 0.35:
                    sessions.append((20 * 60 + rng.randint(0, 30), rng.randint(25, 45), 0.2))
            day_meets = []
            if wd == 0:
                day_meets = [(14 * 60 + 30, 15 * 60)]
            elif wd == 1:
                day_meets = [(13 * 60, 14 * 60), (14 * 60 + 30, 15 * 60 + 30), (16 * 60, 16 * 60 + 40)]
            elif wd == 2:
                day_meets = [(15 * 60, 16 * 60)]
            elif wd == 3:
                day_meets = [(11 * 60 + 30, 12 * 60)] + ([(14 * 60, 15 * 60)] if d.isocalendar()[1] % 2 == 0 else [])
            elif wd == 4:
                day_meets = [(14 * 60, 14 * 60 + 45)]
            for a, b in day_meets:
                meetings.append({"day": key, "from": "%d:%02d" % (a // 60, a % 60), "to": "%d:%02d" % (b // 60, b % 60)})
            proj = names[rng.randrange(len(names))]
            for start, length, switch in sessions:
                m = start
                while m < start + length:
                    if not any(a <= m < b for a, b in day_meets):
                        if rng.random() < switch:
                            proj = names[rng.randrange(len(names))]
                        kind = rng.choices(["commit", "note", "run", "pr"], [0.6, 0.15, 0.18, 0.07])[0]
                        events.append({"t": "%sT%02d:%02d" % (key, m // 60, m % 60), "kind": kind, "project": proj})
                    m += rng.randint(6, 18) if start < 12 * 60 else rng.randint(9, 24)
        events.sort(key=lambda e: e["t"])
        return {"concept": True, "badge": self.RHYTHM_BADGE, "today": self.today(), "events": events, "meetings": sorted(meetings, key=lambda m: m["day"]),
                "tasks": self.rhythm_tasks(events, meetings)}

    # What the demo "worked on": invented subjects, branches, notes, pull request titles and meeting titles (nothing real, the same every run).
    TASK_SUBJECTS = {
        "wayfarer-mobile": ["Cache trips for offline use", "Fix crash when a trip has no dates", "Add pull to refresh on the trip list", "Update the onboarding copy", "Handle expired sessions on resume"],
        "wayfarer-web": ["Raise the contrast of the booking buttons", "Add a dark theme toggle", "Fix the footer links on small screens", "Tidy the trip card layout", "Load maps only when scrolled into view"],
        "wayfarer-api": ["Add a retry to the booking webhook", "Fix the timezone in trip exports", "Cover the cancel flow with tests", "Speed up the trips query", "Return clearer errors for bad dates"],
        "harvest-pipeline": ["Skip empty files in the nightly import", "Add a row count check to the report", "Rename the bookings table columns", "Fix the report date range", "Log the slowest step"],
        "saltpan-blog": ["Draft the brown butter rice pudding post", "Fix the broken image on the about page", "Schedule the Friday newsletter", "Add a recipe card to the template", "Update the travel notes index"]}
    TASK_BRANCHES = {"wayfarer-mobile": ["feat/offline-cache", "fix/14-trip-dates"], "wayfarer-web": ["feat/dark-theme", "fix/31-contrast"], "wayfarer-api": ["fix/131-booking-tests", "feat/trip-export"],
                     "harvest-pipeline": ["feat/row-count-check", "fix/nightly-import"], "saltpan-blog": ["feat/pudding-post", "chore/newsletter"]}
    TASK_NOTES = ["Ask Priya about the release freeze", "Look at the slow trips query", "Idea: show offline status in the header", "Check the newsletter links before Friday"]
    TASK_MEETINGS = [["Planning sync"], ["Design review", "Customer call", "Retro"], ["Backend catch up"], ["Release check"], ["Demo prep"]]

    @staticmethod
    def _branch_words(name):
        parts = [p for p in name.split("/") if p]
        words = re.sub(r"[-_.]+", " ", " ".join(parts[1:] if len(parts) > 1 else parts)).split()
        issue = next((w for w in words if re.fullmatch(r"\d{2,6}", w)), None)
        return (f"#{issue} " if issue else "") + " ".join(w for w in words if w != issue)

    def rhythm_tasks(self, events, meetings):
        out, last = [], {}
        for e in events:
            day, hm = e["t"][:10], e["t"][11:]
            d = datetime.strptime(day, "%Y-%m-%d")
            lr = random.Random(f"tasks{self.seed}{e['t']}{e['project']}")
            proj = e["project"]
            minute = int(hm[:2]) * 60 + int(hm[3:])
            if last.get(day) != proj:                                        # a checkout of that project's branch just before its first action after a switch
                names = self.TASK_BRANCHES[proj]
                branch = names[(d.isocalendar()[1] + sum(map(ord, proj))) % len(names)]
                mm = max(0, minute - 3)
                out.append({"t": "%sT%02d:%02d" % (day, mm // 60, mm % 60), "kind": "branch", "project": proj, "label": self._branch_words(branch), "branch": branch})
                last[day] = proj
            kind = e["kind"]
            if kind == "commit":
                label = lr.choice(self.TASK_SUBJECTS[proj])
            elif kind == "pr":
                label = lr.choice(self.TASK_SUBJECTS[proj])
            elif kind == "note":
                label = lr.choice(self.TASK_NOTES)
            else:
                label = lr.choice(["surveyor, PR #%d" % lr.randint(20, 140), "trials", "panel: offline mode"])
            out.append({"t": e["t"], "kind": kind, "project": proj, "label": label})
        for m in meetings:
            d = datetime.strptime(m["day"], "%Y-%m-%d")
            titles = self.TASK_MEETINGS[d.weekday()] if d.weekday() < 5 else ["Weekend call"]
            lr = random.Random(f"tasks{self.seed}{m['day']}{m['from']}")
            out.append({"t": "%sT%s" % (m["day"], m["from"].zfill(5)), "kind": "meeting", "project": "", "label": lr.choice(titles)})
        out.sort(key=lambda e: (e["t"], e["kind"]))
        return {"on": True, "events": out, "file": ""}

    def timeline_view(self, window, t):
        now = datetime.fromtimestamp(self.t0 + t, timezone.utc)
        cutoff = iso(now - timedelta(seconds={"6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400}[window]))
        events = [{"at": r["at"], "project": r["project"], "duty": r["duty"], "verdict": r["verdict"], "detail": r["detail"][:140],
                   "kind": "merge" if r["verdict"] == "MERGED" else "run", "url": r.get("url") or None}
                  for r in self.runs(t) if r["at"] >= cutoff and r["at"] <= iso(now)]
        for x in self.EXT:
            events += x.events(self, t, cutoff)
        events.sort(key=lambda e: e["at"], reverse=True)
        return {"window": window, "now": iso(now), "total": len(events), "capped": False, "events": events}

    # ---- writes: every one succeeds in memory and leaves a trace in the world ----
    def _start(self, project, duty, what, **kw):
        t = self.elapsed()
        n = self.next_id()
        job = {"id": f"u{n}", "user": True, "start": t, "end": t + kw.pop("seconds", 45), "project": project, "duty": duty, "what": what,
               "verdict": "DRY-RUN", "detail": "0 finding(s)", "cost": 0.3, **kw}
        self.user_jobs.append(job)
        return job

    def post(self, path, b):
        """(status, json-able) for a POST path, or None when it is not one demo mode answers."""
        t = self.elapsed()
        got = self.maker.post(path, b) if self.maker else None
        if got:
            return got
        for x in self.EXT:
            got = x.post(self, path, b, t)
            if got:
                return got
        if path == "/api/connections":
            return 400, {"error": "Demo mode: nothing is connected or changed."}
        if path == "/api/fleet/action":
            return self.fleet_action(b)
        if path == "/api/run":
            project, duty = b.get("project"), b.get("duty")
            if project not in PROJECTS:
                return 400, {"error": "unknown project"}
            if duty not in PROJECTS[project]["duties"]:
                return 400, {"error": f"'{duty}' is not enabled for '{project}'"}
            args = [str(a) for a in (b.get("args") or [])][:6]
            self._start(project, duty, " ".join(args) or "a run started from the dashboard")
            return 200, {"started": f"run {project} {duty} {' '.join(args)}".strip()}
        if path in ("/api/intent", "/api/project-status"):
            return self.intent_post(path, b)
        if path == "/api/cycle/start":
            return self.cycle_start(b.get("project"), b.get("issue"), b.get("confirm"))
        if path == "/api/work":
            project, issue, action = b.get("project"), b.get("issue"), b.get("action")
            if project not in PROJECTS:
                return 400, {"error": "unknown project"}
            if type(issue) is not int or not 0 < issue < 10 ** 7:
                return 400, {"error": "bad issue"}
            if action not in ("analyse", "start"):
                return 400, {"error": "bad action"}
            title = ISSUES[project].get(issue, ("an issue",))[0]
            if action == "analyse":
                self._start(project, "purser", f"issue #{issue}, {title}", verdict="READY", detail=f"#{issue} has what a stranger needs to start")
                return 200, {"started": f"run {project} purser --issue {issue}"}
            if "shipwright" not in PROJECTS[project]["duties"]:
                return 409, {"error": f"'shipwright' is not enabled for '{project}'"}
            if any(j["project"] == project and j.get("issue") == issue and j["start"] <= t < j["end"] and j["id"] not in self.stopped for j in self.jobs()):
                return 409, {"error": f"#{issue} is already being fixed"}
            n = 900 + self.next_id()
            self._start(project, "shipwright", f"issue #{issue}, {title}", issue=issue, verdict="PR", pr=n, step="building", seconds=60, cost=1.2)
            return 200, {"started": f"fix {project} --issue {issue}"}
        if path == "/api/fix":
            pid = b.get("panel", "")
            p = next((x for x in PANELS if x[0] == pid), None)
            if not p:
                return 400, {"error": "no such panel"}
            raw = b.get("items") if isinstance(b.get("items"), list) else [b.get("item")]
            try:
                items = [int(x) for x in raw][:100]
            except (TypeError, ValueError):
                return 400, {"error": "bad item"}
            queued, skipped = [], []
            running = {(j["panel"], j["item"]) for j in self.jobs() if j.get("panel") is not None and j["start"] <= t < j["end"]}
            for n in items:
                if not 1 <= n <= len(p[6]):
                    skipped.append({"item": n, "why": "no such item"})
                elif p[6][n - 1][3] != "change":
                    skipped.append({"item": n, "why": f"labelled a {p[6][n - 1][3]}, not a change"})
                elif (PANELS.index(p), n) in running:
                    skipped.append({"item": n, "why": "being fixed now"})
                else:
                    queued.append(n)
            if not queued:
                return 409, {"error": "nothing to queue: " + "; ".join(f"#{x['item']}: {x['why']}" for x in skipped[:4])}
            for n in queued:
                pr = 900 + self.next_id()
                self._start(p[1], "shipwright", f"item {n} of {pid}", panel=PANELS.index(p), item=n, issue=n, verdict="PR", pr=pr, step="building", seconds=60, cost=1.1)
            return 200, {"project": p[1], "queued": queued, "skipped": skipped}
        if path == "/api/merge":
            project, number = b.get("project"), b.get("number")
            if project not in PROJECTS:
                return 409, {"error": "unknown project"}
            if not any(p["project"] == project and p["number"] == number for p in self.open_prs(t)):
                return 409, {"error": "that pull request is not open"}
            self.merged.add((project, t, number))
            return 200, {"merged": True, "number": number}
        if path == "/api/stop":
            lock = b.get("lock", "")
            running, _, _ = self.timeline(t)
            for j in running:
                if lock.endswith(j["id"]):
                    self.stopped.add(j["id"])
                    return 200, {"stopped": lock}
            return 404, {"error": "not running"}
        if path == "/api/capture":
            act, cid = b.get("action"), b.get("id")
            if act in ("done", "reopen", "edit", "promote"):
                n = self.notes.get(cid) if isinstance(cid, str) else None
                if not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{8}", cid):
                    return 400, {"error": "bad id"}
                if n is None:
                    return 400, {"error": "no such note"}
                if act == "done":
                    n["done"], n["updated"] = True, self.at(t)
                elif act == "reopen":
                    if not n["done"]:
                        return 400, {"error": "that note is not done"}
                    n["done"], n["updated"] = False, self.at(t)
                elif act == "edit":
                    if b.get("text") is None and b.get("project") is None:
                        return 400, {"error": "nothing to change"}
                    if b.get("text") is not None:
                        text = " ".join(str(b["text"]).split())[:1000]
                        if not text:
                            return 400, {"error": "a note cannot be empty"}
                        n["text"] = text
                    if b.get("project") is not None:
                        if b["project"] != "" and b["project"] not in PROJECTS:
                            return 400, {"error": "unknown project"}
                        n["project"] = b["project"]
                    n["updated"] = self.at(t)
                    return 200, n
                else:
                    project = b.get("project")
                    if project not in PROJECTS:
                        return 400, {"error": "unknown project" if project else "pick a project first"}
                    if b.get("to") == "mission":
                        code, m = self._mission({"action": "create", "project": project, "objective": n["text"]}, t)
                        if code != 200:
                            return code, m
                        n["promoted"] = {"kind": "mission", "ref": m["id"], "project": project}
                    elif b.get("to") == "plan":
                        if b.get("confirm") is not True:
                            return 400, {"error": "confirm is required: a plan runs a panel and spends model tokens"}
                        if "panel" not in PROJECTS[project]["duties"]:
                            return 400, {"error": f"'panel' is not enabled for '{project}'"}
                        self._start(project, "panel", "a spec panel for a note")
                        n["promoted"] = {"kind": "plan", "ref": "spec panel", "project": project}
                    else:
                        return 400, {"error": "promote to a mission or a plan"}
                    return 200, n["promoted"]
                return 200, {"ok": True}
            text = " ".join(str(b.get("text") or "").split())[:1000]
            if not text:
                return 400, {"error": "nothing to capture"}
            project = b.get("project") or ""
            if project and project not in PROJECTS:
                return 400, {"error": "unknown project"}
            rec = {"id": _hex8(self.next_id()), "at": self.at(t), "text": text, "project": project, "done": False, "updated": self.at(t), "promoted": None}
            self.notes[rec["id"]] = rec
            return 200, rec
        if path == "/api/inbox":
            if b.get("action") != "acknowledge":
                return 400, {"error": "not something this can do"}
            key = b.get("id")
            if not isinstance(key, str) or not key or len(key) > 300:
                return 400, {"error": "bad id"}
            self.acks.add(key)
            return 200, {"id": key, "acknowledged": True}
        if path == "/api/missions":
            return self._mission(b, t)
        if path == "/api/showcase":
            return self._showcase(b, t)
        if path == "/api/fixqueue":
            if b.get("project") not in PROJECTS:
                return 400, {"error": "unknown project"}
            if b.get("action") not in ("pause", "resume", "clear", "remove"):
                return 400, {"error": "bad action"}
            return 200, {"ok": b["action"]}
        if path == "/api/schedule":
            self.schedules()
            sid = b.get("id")
            if b.get("delete"):
                self.sched = [s for s in self.sched if s["id"] != sid]
                return 200, {"deleted": sid}
            if b.get("toggle"):
                for s in self.sched:
                    if s["id"] == sid:
                        s["paused"] = not s["paused"]
                return 200, {"toggled": sid}
            project, duty = b.get("project"), b.get("duty")
            if project not in PROJECTS or duty not in PROJECTS[project]["duties"]:
                return 400, {"error": "unknown project or duty"}
            every, at = (b.get("every") or "").strip(), (b.get("at") or "").strip()
            if at and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", at):
                return 400, {"error": "time must be HH:MM"}
            if not at and not re.fullmatch(r"\d{1,3}[mhd]", every):
                return 400, {"error": "interval must look like 30m, 4h or 1d"}
            s = {"id": _hex8(self.next_id()), "project": project, "duty": duty, "args": [a for a in (b.get("args") or []) if a], "apply": bool(b.get("apply")),
                 "every": "" if at else every, "at": at, "paused": False, "created": self.at(t), "last_run": None}
            self.sched.append(s)
            return 200, s
        return None

    def _mission(self, b, t):
        action = b.get("action")
        if action == "create":
            if b.get("project") not in PROJECTS:
                return 400, {"error": "unknown project"}
            obj = (b.get("objective") or "").strip()
            if not obj or len(obj) > 2000:
                return 400, {"error": "objective must be 1-2000 characters"}
            m = {"id": "m-" + _hex8(self.next_id()), "project": b["project"], "objective": obj, "constraints": (b.get("constraints") or "").strip()[:2000],
                 "success_criteria": (b.get("success_criteria") or "").strip()[:2000], "status": "draft", "created_at": self.at(t), "updated_at": self.at(t),
                 "links": {"panels": [], "runs": [], "fixes": [], "issues": [], "prs": [], "documents": []}, "plan": None, "plan_revision": 0,
                 "plan_approved_revision": None, "plan_approved_at": None, "events": [{"at": self.at(t), "kind": "created", "detail": "draft created", "source": "dashboard"}]}
            self.mission_extra.append(m)
            return 200, m
        m = next((x for x in self.missions() if x["id"] == b.get("id")), None)
        if not m:
            return 400, {"error": "unknown mission"}
        ev = lambda kind, detail: m["events"].append({"at": self.at(t), "kind": kind, "detail": detail, "source": "dashboard"})
        if action == "update":
            for f in ("objective", "constraints", "success_criteria"):
                if f in b:
                    m[f] = (b.get(f) or "").strip()[:2000]
            ev("edited", "draft edited")
        elif action == "propose_plan":
            m["plan"] = [{"duty": "panel", "about": "Seats a discipline of crew on the question and rules on it.", "perm": "local-write", "label": "Local file changes"}]
            m["plan_revision"] += 1
            ev("planned", f"plan proposed (revision {m['plan_revision']})")
        elif action == "approve_plan":
            if not m.get("plan"):
                return 400, {"error": "propose a plan before approving one"}
            m["plan_approved_revision"] = m["plan_revision"]
            ev("approved", f"plan revision {m['plan_revision']} approved")
        elif action == "start_panel":
            if m.get("plan_approved_revision") != m.get("plan_revision") or not m.get("plan"):
                return 400, {"error": "approve a plan before starting it"}
            self._start(m["project"], "panel", "a spec panel for this mission")
            m["status"] = "started"
            ev("started", "started a spec panel")
        elif action == "link":
            ev("linked", "linked a panel as evidence")
        else:
            return 400, {"error": "not something this can do"}
        m["updated_at"] = self.at(t)
        if m["id"] != "m-demo00000001" and m not in self.mission_extra:
            self.mission_extra.append(m)
        return 200, m

    def _showcase(self, b, t):
        action = b.get("action")
        if action == "create":
            title = (b.get("title") or "").strip()
            if not title or len(title) > 200:
                return 400, {"error": "title must be 1-200 characters"}
            s = {"id": "s-" + _hex8(self.next_id()), "title": title, "summary": (b.get("summary") or "")[:1000], "before": (b.get("before") or "")[:600],
                 "after": (b.get("after") or "")[:600], "role": (b.get("role") or "")[:600], "synthetic": True, "mission_id": None, "status": "draft",
                 "published_at": None, "created_at": self.at(t), "updated_at": self.at(t), "events": []}
            self.showcase.append(s)
            return 200, s
        s = next((x for x in self.showcase if x["id"] == b.get("id")), None)
        if not s:
            return 400, {"error": "unknown showcase item"}
        if action == "publish":
            s["status"], s["published_at"] = "published", self.at(t)
        elif action == "unpublish":
            s["status"], s["published_at"] = "draft", None
        elif action == "update":
            for f in ("title", "summary", "before", "after", "role"):
                if f in b:
                    s[f] = (b.get(f) or "").strip()
        else:
            return 400, {"error": "not something this can do"}
        return 200, s
