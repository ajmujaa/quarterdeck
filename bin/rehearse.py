#!/usr/bin/env python3
"""Replays docs/brain-talk/run-of-show.md against the demo world, second by second.

No browser, no models, stdlib only. For each timed step it builds the demo state at that second
(bin/demo.py) and asserts what the audience would see: agents running, open pull requests, the
Needs you item, the feed panel headlines, and the answer to each Helm phrase, using the page's own
fixed-phrase parser and answer builders through node (bin/rehearse-helm.mjs). Prints one
`  ok    ...` or `  FAIL  ...` line per step and exits non-zero if any failed."""
import datetime
import json
import re
import shutil
import subprocess
import nodeok
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import demo  # noqa: E402

T0 = datetime.datetime(2026, 10, 5, 10, 0).astimezone().timestamp()   # the same fixed morning the node tests use
OFFSET = 50                                                            # talk time = demo second + 50 (Restart pressed at 0:50)
SECONDS = (0, 20, 50, 55, 70, 90, 100, 118, 120, 130, 145, 150, 155, 165, 175, 180, 185, 200, 205, 215, 225, 235, 245, 380)
# (earlier poll, later poll) pairs whose suggestions are asserted; None is the first look
PAIRS = ((None, 0), (50, 50), (None, 50), (90, 100), (145, 155), (175, 185), (205, 215), (225, 235), (None, 70), (None, 380))
PROJECTS = list(demo.PROJECTS)
DUTIES = sorted({d for p in demo.PROJECTS.values() for d in p["duties"]})
# phrase -> what the fixed parser must return for it (each phrase must also appear in run-of-show.md)
PHRASES = {
    "Helm, what is running?": {"intent": "running"},
    "Helm, brief me.": {"intent": "brief"},
    "Helm, open needs you.": {"intent": "go", "view": "inbox"},
    "Helm, start work on issue 15 on wayfarer mobile.": {"intent": "work", "action": "start", "issue": 15, "project": "wayfarer-mobile", "confirm": True},
    "Helm, open the ledger": {"intent": "go", "view": "ledger"},
    "Helm, open wayfarer api": {"intent": "project", "project": "wayfarer-api"},
    "Helm, open pull requests": {"intent": "go", "view": "prs"},
    "Helm, my reminders": {"intent": "reminders"},
    "Helm, what's on today": {"intent": "agenda"},
    "Helm, start work on issue 131 on wayfarer api": {"intent": "work", "action": "start", "issue": 131, "project": "wayfarer-api", "confirm": True},
    "Helm, help": {"intent": "help"},
}
FAILS = []


def check(label, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + label + ("" if ok else f"  [{str(detail)[:160]}]"))
    if not ok:
        FAILS.append(label)


def state_at(sec):
    w = demo.World(clock=lambda: T0)
    w.clock = lambda: T0 + sec
    st = w.state()
    st["_prs"] = w.open_prs(sec)
    return st, w


def views():
    html = (ROOT / "dashboard" / "index.html").read_text()
    block = html[html.index("const VIEWS = ["):].split("\n]")[0]
    vs = [{"id": i, "label": l} for i, l in re.findall(r'\{id:\s*"([\w-]+)",\s*label:\s*"([^"]+)"', block)]
    return vs + [{"id": "overview", "label": "Home"}]


def att_input(w):
    """What the page would hold after /api/attention and /api/intent, from the demo world (invented numbers only)."""
    view, iv = w.attention(70), w.intent_view()
    return {"days": view["days"], "today": iv["today"], "intent": iv["current"], "status": iv["status"]}


def real_rhythm_input():
    """A made-up store of hour buckets through the real adapter: what the screen gets in real mode, without reading anything real."""
    import random
    sys.path.insert(0, str(ROOT / "bin"))
    import attention.rhythm_feed as rf
    rng, hours = random.Random(3), {}
    for back in range(0, 40):
        d = (datetime.date(2026, 10, 7) - datetime.timedelta(days=back))
        if d.weekday() >= 5:
            continue
        for h in (9, 10, 11, 14, 15):
            if rng.random() < 0.6:
                hours.setdefault("alpha" if h < 14 else "beta", {}).setdefault(d.isoformat(), {})["%02d" % h] = {"commits": rng.randint(1, 3)}
        if d.weekday() == 1:
            hours.setdefault("(calendar)", {}).setdefault(d.isoformat(), {})["13"] = {"meetings": 2}
    return rf.build({"hours": hours}, "2026-10-07")


def main():
    states = {s: state_at(s) for s in SECONDS}
    S = {s: states[s][0] for s in SECONDS}
    talk = lambda s: f"{(s + OFFSET) // 60}:{(s + OFFSET) % 60:02d}"
    running = lambda s: [(a["project"], a["duty"], a["what"]) for a in S[s]["agents"] if a["status"] == "running"]
    prs = lambda s: sorted(p["number"] for p in S[s]["_prs"])
    needs = lambda s: [i["text"] for i in S[s]["inbox"] if not i.get("place")]
    new = lambda s, name: [i["title"] for c in S[s]["connectors"] if c["name"] == name for i in c["items"] if i["new"]]

    node = None
    if nodeok.path():
        r = subprocess.run(["node", "--no-warnings", str(ROOT / "bin" / "rehearse-helm.mjs")], capture_output=True, text=True, timeout=60,
                           input=json.dumps({"views": views(), "projects": PROJECTS, "duties": DUTIES, "phrases": list(PHRASES),
                                             "states": {str(s): S[s] for s in SECONDS}, "pairs": [list(p) for p in PAIRS],
                                             "attention_second": 70, "attention": att_input(states[70][1]),
                                             "rhythm": states[70][1].rhythm(), "realRhythm": real_rhythm_input()}))
        node = json.loads(r.stdout) if r.returncode == 0 else None
        if node is None:
            check("the page's own parser and answer builders ran under node", False, r.stderr[-300:])
    else:
        print("  skip  Helm phrases and feed panels: node is not installed")
    N = lambda s: node["seconds"][str(s)] if node else None

    check("demo world: five made-up projects and twenty-one kinds of agent (slide 2)", len(PROJECTS) == 5 and len(DUTIES) == 21, (len(PROJECTS), DUTIES))
    s0 = running(0)
    check(f"{talk(0)} restart: one agent already building mobile issue 14, four pull requests open",
          len(s0) == 1 and s0[0][0] == "wayfarer-mobile" and "#14" in s0[0][2] and len(prs(0)) == 4, (s0, prs(0)))
    check(f"{talk(20)} a second agent starts on web issue 31", {a[0] for a in running(20)} == {"wayfarer-mobile", "wayfarer-web"} and not any("#31" in a[2] for a in running(0)), running(20))
    check(f"{talk(55)} a TestFlight mail arrives", not any("TestFlight" in t for t in new(0, "gmail")) and any("TestFlight" in t for t in new(55, "gmail")), new(55, "gmail"))
    check(f"{talk(70)} mobile pull request 42 opens and the mobile agent is done", 42 in prs(70) and 42 not in prs(55) and not any(a[0] == "wayfarer-mobile" and a[1] == "shipwright" for a in running(70)), prs(70))
    review = lambda s: next((p["review"] for p in S[s]["_prs"] if p["number"] == 42), None)
    check(f"{talk(100)} the surveyor is reviewing 42, and by {talk(120)} has found it clean",
          any(a[1] == "surveyor" and "#42" in a[2] for a in running(100)) and review(100) is None and (review(120) or {}).get("verdict") == "CLEAN", (running(100), review(120)))
    check(f"{talk(100)} web pull request 78 opens, six open in all", 78 in prs(100) and 78 not in prs(70) and len(prs(100)) == 6, prs(100))
    check(f"{talk(118)} an agent starts on API issue 131", any(a[0] == "wayfarer-api" and "#131" in a[2] for a in running(118)), running(118))
    check(f"{talk(150)} the API agent fails: nothing running, the red item is in Needs you",
          running(150) == [] and any("#131 tests failed: 2 failing in test_bookings.py" in t for t in needs(150)) and not any("#131" in t for t in needs(130)), needs(150))
    check(f"{talk(165)} the re-run starts", any(a[0] == "wayfarer-api" and "re-run" in a[2] for a in running(165)), running(165))
    check(f"{talk(225)} the re-run opens pull request 132 and the failure clears", 132 in prs(225) and 132 not in prs(200) and not any("#131" in t for t in needs(225)), (prs(225), needs(225)))
    check(f"{talk(200)} the inspector is verifying 78", any(a[1] == "inspector" and "#78" in a[2] for a in running(200)), running(200))
    check("the scenario settles: nothing running at 380 seconds and the Slack mention, LinkedIn post and Instagram post have all arrived",
          running(380) == [] and new(380, "slack") and new(380, "linkedin") and new(380, "instagram"), (new(380, "slack"), new(380, "linkedin")))
    if not node:
        return
    check("every Helm phrase in the run of show parses to the intent the script says",
          all(node["phrases"][p] == want for p, want in PHRASES.items()), {p: node["phrases"][p] for p, want in PHRASES.items() if node["phrases"][p] != want})
    ros_file = ROOT / "docs" / "brain-talk" / "run-of-show.md"
    if ros_file.is_file():          # the talk's own script is private and absent from the public tree: the rest of the replay stands on the demo world alone
        ros = ros_file.read_text()
        check("every phrase tested here is in docs/brain-talk/run-of-show.md (so the test and the script stay tied)",
              all(p.rstrip(".?") in ros for p in PHRASES), [p for p in PHRASES if p.rstrip(".?") not in ros])
    check(f"{talk(0)} Helm, what is running: names the mobile agent", len(N(0)["running"]) == 1 and N(0)["running"][0].startswith("wayfarer-mobile: shipwright on #14"), N(0)["running"])
    check(f"{talk(130)} Helm, what is running: the API agent, a few minutes in", len(N(130)["running"]) == 1 and N(130)["running"][0].startswith("wayfarer-api: shipwright on #131"), N(130)["running"])
    check(f"{talk(150)} Helm, what is running: nothing", N(150)["running"] == [])
    check(f"{talk(150)} Helm, brief me: the failure is in the failed count and pull requests are in the opened count", N(150)["digest"]["failed"] >= 1 and N(150)["digest"]["prs"] >= 3, N(150)["digest"])
    check(f"{talk(150)} Next up names the failed run", N(150)["next"] == "shipwright failed on wayfarer-api", N(150)["next"])
    check(f"{talk(130)} the Slack panel: 3 waiting, latest the releases mention", N(130)["feeds"]["slack"]["sub"] == "3 waiting on you, latest from #releases: mention.", N(130)["feeds"]["slack"])
    check(f"{talk(55)} the Gmail panel counts the TestFlight mail", N(55)["feeds"]["gmail"]["sub"].startswith("5 waiting on you, latest from App Store Connect"), N(55)["feeds"]["gmail"])
    check(f"{talk(180)} the analytics panel calls out the spike", N(180)["feeds"]["analytics"]["state"] == "new" and N(180)["feeds"]["analytics"]["sub"].startswith("Brown butter rice pudding is up 640% (4,210 views)"), N(180)["feeds"]["analytics"])
    check(f"{talk(0)} the analytics panel is quiet before the spike", N(0)["feeds"]["analytics"]["state"] == "idle", N(0)["feeds"]["analytics"])
    check(f"{talk(245)} the LinkedIn panel headlines the post that took off", N(245)["feeds"]["linkedin"]["sub"].startswith("What six months of offline-first taught us"), N(245)["feeds"]["linkedin"])
    A = node["attention"]
    check("attention (Demo): nothing real is read, the invented buckets are the same shape the real endpoint returns, and every project and day is a count",
          states[70][1].attention(70)["estimated"] is True and set(states[70][1].attention(70)) == {"on", "updated", "estimated", "days"}
          and all(isinstance(v, (int, float)) for dd in states[70][1].attention(70)["days"].values() for r in dd.values() for v in r.values()), None)
    check("attention (Demo): exactly one project is emerging, harvest-pipeline, and Helm says so as an estimate",
          A["emerging"] == ["harvest-pipeline"] and A["emergingText"].startswith("harvest-pipeline is up about ") and A["emergingText"].endswith("That is an estimate."), (A["emerging"], A["emergingText"]))
    check("attention (Demo): exactly one project has gone quiet, wayfarer-mobile, and parking it takes it out of the list",
          A["dormant"] == ["wayfarer-mobile"] and "wayfarer-mobile" in A["dormantText"] and "park wayfarer-mobile" in A["dormantText"] and A["parked"] == [], (A["dormant"], A["parked"]))
    f = {r["project"]: r["verdict"] for r in (A["focus"] or {"rows": []})["rows"]}
    check("attention (Demo): the focus has a gap, wayfarer-web is missing and saltpan-blog is under, and harvest-pipeline took the time instead",
          f == {"wayfarer-web": "missing", "saltpan-blog": "under"} and A["focus"]["elsewhere"]["project"] == "harvest-pipeline", A["focus"])
    check("attention (Demo): Brain nodes are sized by share, the largest is harvest-pipeline, and the quiet project has none",
          max(A["sizes"], key=A["sizes"].get) == "harvest-pipeline" and "wayfarer-mobile" not in A["sizes"], A["sizes"])
    check("attention (Demo): how was my week and the one Home line speak in words, never percentages",
          A["week"].startswith("Over the last seven days, as an estimate:") and "%" not in A["week"] and A["home"].startswith("harvest-pipeline is up ") and "%" not in A["home"], (A["week"], A["home"]))
    check("attention (Demo): the Helm phrases parse, and parking asks for a click",
          A["phrases"]["which projects are dormant"] == {"intent": "dormant"} and A["phrases"]["what is emerging"] == {"intent": "emerging"} and A["phrases"]["how was my week"] == {"intent": "week"}
          and A["phrases"]["what is my focus this week"] == {"intent": "focus"} and A["phrases"]["park wayfarer mobile"] == {"intent": "parkproject", "status": "park", "project": "wayfarer-mobile", "confirm": True}, A["phrases"])
    check(f"attention (Demo): once the mobile pull request is open ({talk(70)}), the Brain says the quiet project has an open pull request, calmly, and only opens it",
          [e["kind"] for e in A["suggest"]] == ["dormant-pr"] and A["suggest"][0]["action"] == "url" and A["suggest"][0]["live"] is False, A["suggest"])
    RY = node["rhythm"]
    r1, r2 = demo.World(clock=lambda: T0).rhythm(), demo.World(clock=lambda: T0).rhythm()
    check("My rhythm (Demo): the invented data is the same every run, holds only commits, pull requests, notes and runs started by hand plus calendar blocks, and has the concept badge",
          r1 == r2 and RY["kinds"] == ["commit", "note", "pr", "run"] and r1["concept"] is True and RY["badge"] == "Concept preview: invented data, nothing is collected"
          and set(r1) == {"concept", "badge", "today", "events", "meetings", "tasks"} and all(set(m) == {"day", "from", "to"} for m in r1["meetings"]) and all(set(e) == {"t", "kind", "project"} for e in r1["events"]), RY["kinds"])
    check("My rhythm (Demo): nine weeks to pick from, a five week by seventeen hour heatmap with something in it, and a day strip of focus blocks, meetings and gaps",
          RY["weeks"] == 9 and RY["newest"] == "Last 7 days" and RY["heatDays"] == 35 and RY["heatRows"] == 17 and RY["heatTotal"] > 100 and "focus" in RY["strip"] and "gap" in RY["strip"], RY)
    check("My rhythm (Demo): a long focus block, a streak of working days with 90 minute blocks, and a meeting load set against last week",
          RY["longest"] >= 90 and RY["streak"] >= 1 and RY["meetings"]["mins"] > 0 and RY["meetings"]["prev"] > 0 and "last week" in RY["meetings"]["word"], (RY["longest"], RY["streak"], RY["meetings"]))
    check("My rhythm (Demo): three quiet observations that only say what happened (mornings are the longest blocks, Tuesday had the most meetings), and a switches note against the usual",
          len(RY["obs"]) == 3 and "Mornings are your longest blocks." in RY["obs"] and "Tuesday had the most meetings." in RY["obs"] and len(RY["older"]) >= 1
          and re.fullmatch(r"\d+ switch(es)? today, your usual is \d+\.", RY["note"]), (RY["obs"], RY["note"]))
    bad = re.compile(r"\b(apps?|websites?|typing|typed|keystrokes?|idle|screens?|screenshots?|clipboard|location|browser|tabs?|where you were|mouse|should|try|consider|must|you could|make sure)\b|[\u2014\u2013]", re.I)
    check("My rhythm (Demo): nothing it says depicts or implies apps, websites, typing, idle or screen time, the clipboard or where you were, nothing instructs, and no em dash appears",
          not [t for t in RY["texts"] if bad.search(t)], [t for t in RY["texts"] if bad.search(t)])
    RR = node["realRhythm"]
    import inspect
    check("My rhythm (Demo keeps its own): the demo preview still carries the concept badge and invented wording, its code reads no file and imports nothing real, and real mode has its own badge and wording",
          RR["demoBadge"] == "Concept preview: invented data, nothing is collected" and "invented" in RR["demoHeat"] and "cannot see reading" not in RR["demoHeat"]
          and RR["badge"].startswith("Estimated from your commits, branches, notes and calendar") and RR["concept"] is False and "cannot see reading, thinking or other work" in RR["heat"] and "invented" not in RR["heat"]
          and not re.search(r"open\(|read_text|Path\(|attention|state/|import ", inspect.getsource(demo.World.rhythm)), (RR["demoBadge"], RR["badge"]))
    check("My rhythm (real data through the adapter): enough data draws, a thin store says not enough yet, blocks are found with the real rules, meetings are counted without lengths and marked at their start, and the observations hold a real pattern",
          RR["enough"] is True and RR["thin"] is False and RR["blocks"] > 0 and RR["meetings"]["mins"] is None and RR["meetings"]["count"] >= 2 and RR["strip"] and 1 <= len(RR["obs"]) <= 3 and not any("not enough" in o for o in RR["obs"]), RR["obs"])
    check("My rhythm (both wordings): nothing either one says depicts or implies apps, websites, typing, idle or screen time, the clipboard or where you were, nothing instructs, and no em dash appears",
          not [t for t in RR["texts"] if re.search(r"\b(apps?|websites?|typing|typed|keystrokes?|idle|screens?|screenshots?|clipboard|location|browser|tabs?|where you were|mouse|should|try|consider|must|you could|make sure)\b|[\u2014\u2013]", t, re.I)])
    TK = RY["tasks"]
    check("My rhythm tasks (Demo): the invented timeline has labelled blocks per project with evidence, a calendar title for meetings, a per project summary line, and never an Unlabelled or empty label",
          TK["on"] and TK["work"] >= 3 and TK["meetings"] and all(TK["meetings"]) and "Unlabelled" not in TK["labels"] and all(TK["labels"]) and TK["evidence"] and set(TK["projects"]) <= set(PROJECTS)
          and TK["summary"] and all(re.fullmatch(r"[a-z-]+ (\d+ h )?\d+ min across \d+ blocks?", x.replace(" h ", " h ")) or re.fullmatch(r"[a-z-]+ \d+ h across \d+ blocks?", x) for x in TK["summary"]) and "commit" in TK["sources"], TK)
    check("My rhythm tasks (Demo): Helm answers what was I working on this morning, what did I do yesterday afternoon and when did I last touch a project from the invented tasks, and says it is an estimate",
          TK["morning"].startswith("This morning: ") and TK["morning"].endswith("That is an estimate from commits, branches, notes and the calendar.") and TK["yesterday"].startswith(("Yesterday afternoon: ", "Nothing is recorded for yesterday afternoon."))
          and TK["last"].startswith("You last touched ") and "an estimate" in TK["last"], (TK["morning"], TK["last"]))
    wr = demo.World(clock=lambda: T0).rhythm()["tasks"]
    check("My rhythm tasks (Demo): the invented tasks are the same every run, carry no stored file, say they are invented, and the demo code reads nothing real to make them",
          wr == demo.World(clock=lambda: T0).rhythm()["tasks"] and wr["file"] == "" and "invented" in TK["explain"] and "rhythm-tasks.json" not in TK["explain"]
          and not re.search(r"open\(|read_text|Path\(|attention|state/|import |subprocess|git ", inspect.getsource(demo.World.rhythm_tasks)) and wr["events"] and all(set(e) <= {"t", "kind", "project", "label", "branch"} for e in wr["events"]))
    # the Board and card reading in Demo: invented cards, nothing real read
    cw = demo.World(clock=lambda: T0)
    _b = cw.get("/api/board", {"project": ["wayfarer-mobile"]})[1]["board"]
    _cols = {r["status"] for pn in demo.PROJECTS for r in cw.get("/api/board", {"project": [pn]})[1]["board"]["items"]}
    _cards = {r["number"]: cw.get("/api/card", {"project": ["wayfarer-mobile"], "number": [str(r["number"])]}) for r in _b["items"]}
    _full = [c[1]["card"] for c in _cards.values() if c[0] == 200]
    _all_bodies = "\n".join(c["body"] for c in _full)
    _backlog = [c for c in _full if next(r for r in _b["items"] if r["number"] == c["number"])["status"] == "Backlog"]
    check("Board (Demo): every column has invented cards and every card opens with a title, state and a body, and no card is real",
          {"Backlog", "Ready", "In progress", "In review", "Done"} <= _cols and len(_full) == len(_b["items"]) and all(c["title"] and c["state"] and c["body"] for c in _full)
          and all(c["url"].startswith("https://github.com/wayfarer-demo/") for c in _full) and cw.get("/api/card", {"project": ["wayfarer-mobile"], "number": ["9999"]})[0] == 404
          and cw.get("/api/card", {"project": ["nope"], "number": ["1"]})[0] == 400 and cw.get("/api/card", {"project": ["wayfarer-mobile"], "number": ["1;x"]})[0] == 400, _cols)
    check("Board (Demo): the invented cards include a checklist, a code block, a table, two comments in order and a Backlog card with the purser's requirements",
          "- [x]" in _all_bodies and "```" in _all_bodies and "| --- |" in _all_bodies and any(len(c["comments"]) == 2 and c["comments"][0]["at"] < c["comments"][1]["at"] for c in _full)
          and any("quarterdeck:requirements" in c["body"] and "Accept when" in c["body"] for c in _backlog), len(_full))
    check("Board (Demo): the demo code behind it reads no file and runs no process",
          not re.search(r"open\(|read_text|Path\(|subprocess|\bgh\b", inspect.getsource(demo.World.board) + inspect.getsource(demo.World.card)))
    # what the Brain suggests, between two polls, from plain rules
    sg = lambda a, b: node["suggest"][f"{a if a is not None else 'null'}>{b}"]
    kinds = lambda a, b: sorted(e["kind"] for e in sg(a, b))
    check(f"{talk(0)} on the first look the Brain suggests only what is true now: the mail that has waited over a day",
          kinds(None, 0) == ["waiting"] and "Gmail" in sg(None, 0)[0]["title"] and sg(None, 0)[0]["action"] == "brain", sg(None, 0))
    check(f"{talk(0)} to {talk(50)} nothing changes, so nothing new is suggested beyond that mail", kinds(None, 50) == ["waiting"] and kinds(50, 50) == ["waiting"], (kinds(None, 50), kinds(50, 50)))
    check(f"{talk(70)} a meeting is 15 minutes away and the Brain says so, most important first",
          kinds(None, 70) == ["meeting", "waiting"] and sg(None, 70)[0]["kind"] == "meeting" and sg(None, 70)[0]["title"] == "Sprint planning starts in 15 min", sg(None, 70))
    check(f"{talk(95)} pull request 42's checks pass: one suggestion to open it", "pr-green" in kinds(90, 100) and any(e["title"] == "Checks passed on #42 (wayfarer-mobile)" and e["action"] == "url" for e in sg(90, 100)), sg(90, 100))
    check(f"{talk(150)} the API run fails: the highest severity suggestion, pointing at its Ledger row", "run-failed" in kinds(145, 155) and next(e for e in sg(145, 155) if e["kind"] == "run-failed")["action"] == "ledger"
          and next(e for e in sg(145, 155) if e["kind"] == "run-failed")["title"] == "shipwright failed on wayfarer-api" and sg(145, 155)[0]["kind"] in ("run-failed", "meeting"), sg(145, 155))
    check(f"{talk(180)} the pudding recipe doubles in analytics", any(e["kind"] == "doubled" and e["title"] == "Brown butter rice pudding doubled" for e in sg(175, 185)) and not any(e["kind"] == "doubled" for e in sg(145, 155)), sg(175, 185))
    check(f"{talk(210)} a reminder goes overdue", any(e["kind"] == "overdue" and e["title"] == "Overdue: Send the October invoice" for e in sg(205, 215)) and not any(e["kind"] == "overdue" for e in sg(175, 185)), sg(205, 215))
    check(f"{talk(230)} the Facebook feed breaks", any(e["kind"] == "feed-broke" and e["title"] == "Facebook stopped refreshing" for e in sg(225, 235)) and not any(e["kind"] == "feed-broke" for e in sg(205, 215)), sg(225, 235))
    check(f"{talk(380)} once the scenario has settled no agent is running too long and nothing is failing", not any(e["kind"] in ("agent-long", "run-failed", "pr-green") for e in sg(None, 380)), sg(None, 380))
    # the confirm and refusal behaviour of "start work" in the demo world
    w = states[150][1]
    code, body = w.post("/api/work", {"project": "wayfarer-mobile", "issue": 15, "action": "start"})
    check(f"{talk(150)} confirming start work on issue 15 starts a run in the demo world", code == 200 and "started" in body, (code, body))
    w2 = states[130][1]
    code2, body2 = w2.post("/api/work", {"project": "wayfarer-api", "issue": 131, "action": "start"})
    check(f"{talk(130)} start work on issue 131 is refused while it is already being built", code2 >= 400, (code2, body2))


if __name__ == "__main__":
    main()
    print()
    print("  all steps held" if not FAILS else f"  {len(FAILS)} step(s) failed")
    sys.exit(1 if FAILS else 0)
