import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {nextUp, awayDigest, parseCommand, runningLines, agendaFor, agendaText, remindersText, speakable, stripWake, pickByName, cleanIdea, dedupeEvents, actionAccepted, actionLine, ACTION_INTENTS, WRITES_NEED_CLICK} from "../dashboard/assets/assistant.js";
import {feedPanel} from "../dashboard/assets/feeds.js";
import {T as TT, listenParams, decide, sentenceFinished, followMs, needsWake, createSegmenter} from "../dashboard/assets/turns.js";
import {emptyMemory, push as cvPush, expire as cvExpire, forRequest, looksLikeCommand, route, MAX_TURNS, IDLE_MS} from "../dashboard/assets/convo.js";
import {detect, emptyStore, ingest, dismiss, snooze, pick, shouldSpeak, spokenText, LONG_MINUTES, KEEP} from "../dashboard/assets/suggest.js";
import {WINDOWS, classOf, select, buildLanes, pct, axisTicks, recentStrip, binText, CLASSES} from "../dashboard/assets/timeline.js";
import {ordinal, filterNotes, nthOpen, notesText} from "../dashboard/assets/notes.js";
import {renderMarkdown, splitRequirements, safeUrl, esc as mdEsc, MAX_CHARS} from "../dashboard/assets/md.js";
import {listFor, seenKey, applySeen, markSeen, docPointer} from "../dashboard/assets/brainlists.js";
import * as AT from "../dashboard/assets/attention.js";
import * as RH from "../dashboard/assets/rhythm.js";
import * as DK from "../dashboard/assets/dock.js";
import {logMinute, runForLine, stampLength, crumbText} from "../dashboard/assets/ledgerlog.js";
const ctx = {views: [{id: "overview", label: "Command center"}, {id: "ledger", label: "Ledger"}, {id: "brain", label: "Brain"}],
             projects: ["harvest-pipeline", "wayfarer-mobile", "wayfarer-web"]};
const p = t => parseCommand(t, ctx);
const T = (name, fn) => { fn(); console.log("  ok    " + name); };
const now = Date.parse("2026-10-03T10:00:00Z"), ago = m => new Date(now - m * 60000).toISOString();

T("commands are understood, and writes ask for a click", () => {
  assert.deepEqual(p("Hey Helm, what's running?"), {intent: "running"});
  assert.deepEqual(p("what's on today"), {intent: "agenda"});
  assert.deepEqual(p("what's my agenda"), {intent: "agenda"});
  assert.deepEqual(p("my reminders"), {intent: "reminders"});
  assert.deepEqual(p("what is next"), {intent: "next"});
  assert.deepEqual(p("brief me"), {intent: "brief"});
  assert.deepEqual(p("open the ledger"), {intent: "go", view: "ledger"});
  assert.deepEqual(p("go to command center"), {intent: "go", view: "overview"});
  assert.deepEqual(p("open wayfarer mobile"), {intent: "project", project: "wayfarer-mobile"});
  assert.deepEqual(p("find the Brand memory"), {intent: "find", query: "brand memory"});
  assert.deepEqual(p("start work on issue 13 on wayfarer mobile"), {intent: "work", action: "start", issue: 13, project: "wayfarer-mobile", confirm: true});
  assert.equal(p("blah blah").intent, "unknown");
  assert.equal(p("open the next steps doc").intent, "find");
  assert.equal(p("find the status memory").intent, "find");
  assert.equal(p("show summary of harvest-pipeline").intent, "project");
  assert.equal(p("   ").intent, "empty");
});
const cd = {...ctx, duties: ["surveyor", "joiner", "harbourmaster", "inspector", "shipwright", "panel"]};
const pd = t => parseCommand(t, cd);
T("helm runs duties: report-only unless the owner says apply, and only duties Helm may start", () => {
  assert.deepEqual(pd("run the surveyor on wayfarer mobile"), {intent: "run", duty: "surveyor", project: "wayfarer-mobile", pr: null, apply: false, confirm: true});
  assert.deepEqual(pd("review the pull request on harvest-pipeline"), {intent: "run", duty: "surveyor", project: "harvest-pipeline", pr: null, apply: false, confirm: true});
  assert.deepEqual(pd("Review pull request 12 on wayfarer mobile and apply it"), {intent: "run", duty: "surveyor", project: "wayfarer-mobile", pr: 12, apply: true, confirm: true});
  assert.equal(pd("run the shipwright on harvest-pipeline").intent, "unknown");          // it takes an issue: the work command does that
  assert.equal(pd("run the surveyor").project, null);
  assert.equal(pd("run the surveyor on wayfarer mobile").apply, false);
});
T("helm stops a duty, and a stop word alone still means be quiet", () => {
  assert.deepEqual(pd("stop the shipwright on wayfarer mobile"), {intent: "halt", duty: "shipwright", project: "wayfarer-mobile", confirm: true});
  assert.deepEqual(pd("stop"), {intent: "stop"});
  assert.equal(pd("stop the music").intent, "unknown");
});
T("job names are matched loosely, an exact name wins, and two matches become a question", () => {
  const jobs = [{name: "daily-promo-digest"}, {name: "sentry-fix"}, {name: "sentry-fix-weekly"}, {name: "scout-feed-refresh"}];
  const by = q => pickByName(q, jobs, j => j.name);
  assert.equal(by("daily promo digest").match.name, "daily-promo-digest");
  assert.equal(by("the scouts feed").match.name, "scout-feed-refresh");
  assert.equal(by("sentry fix").match.name, "sentry-fix");                    // exact beats the weekly one
  assert.equal(by("sentry").ambiguous.length, 2);
  assert.equal(by("invented thing").none, true);
  assert.equal(by("it").empty, true);
});
T("helm dismisses a signal, plans a draft, and reads out panels and missions", () => {
  assert.deepEqual(pd("dismiss the surveyor log signal"), {intent: "ack", query: "surveyor log", confirm: true});
  assert.deepEqual(pd("acknowledge that"), {intent: "ack", query: "", confirm: true});
  assert.deepEqual(pd("plan offline mode for wayfarer mobile"), {intent: "plan", objective: "offline mode", project: "wayfarer-mobile", panel: false, confirm: true});
  assert.deepEqual(pd("plan offline mode for wayfarer mobile and get the panel to look at it"), {intent: "plan", objective: "offline mode", project: "wayfarer-mobile", panel: true, confirm: true});
  assert.equal(pd("plan a better onboarding").project, null);
  assert.deepEqual(pd("what did the panel say about onboarding"), {intent: "panelsay", query: "onboarding", project: null});
  assert.deepEqual(pd("what are my open missions"), {intent: "missions"});
  assert.equal(pd("start work on issue 3 on harvest-pipeline").intent, "work");          // the older commands still win their own phrases
});
T("a spoken note keeps your own words and casing", () => {
  assert.deepEqual(p("Remember to call Dr. Hansen about the 14th"), {intent: "capture", text: "call Dr. Hansen about the 14th"});
});
T("next up: broken first, then waiting, then quiet", () => {
  const base = {now, attention: [], runs: [], agents: [], prs: []};
  assert.equal(nextUp({...base, projects: []}).act, "attach", "no projects yet: the one next step is to add one");
  assert.notEqual(nextUp({...base, projects: ["wayfarer-api"]}).act, "attach", "with a project the step is something else");
  assert.notEqual(nextUp(base).act, "attach", "an old caller that passes no project list is not told to add one");
  assert.equal(nextUp({...base, attention: [{kind: "warn", source: "Outside", text: "late", view: "outside"}, {kind: "bad", source: "Outside", text: "down", view: "outside"}]}).title.includes("down"), true);
  assert.equal(nextUp({...base, runs: [{at: ago(30), project: "wayfarer-mobile", duty: "shipwright", verdict: "ERROR", detail: "#2 run failed"}]}).title, "shipwright failed on wayfarer-mobile");
  assert.equal(nextUp({...base, runs: [{at: ago(10), project: "a", duty: "x", verdict: "PR"}, {at: ago(30), project: "a", duty: "x", verdict: "ERROR"}]}).title.startsWith("Nothing needs you"), true);
  assert.equal(nextUp({...base, prs: [{number: 22, project: "x", title: "t", url: "u", by_quarterdeck: true, draft: false, checks: {fail: 0, pending: 1}}]}).title.startsWith("Nothing needs you"), true);
  assert.equal(nextUp({...base, prs: [{number: 22, project: "wayfarer-mobile", title: "t", url: "u", by_quarterdeck: true, draft: false, checks: {fail: 0}}]}).url, "u");
  assert.equal(nextUp({...base, prs: [{number: 9, project: "brand-site", title: "bump", url: "k", by_quarterdeck: false, draft: false, checks: {fail: 0}}]}).title.startsWith("Nothing needs you"), true);
  assert.match(nextUp({...base, agents: [{status: "running", project: "harvest-pipeline", duty: "surveyor"}]}).why, /harvest-pipeline surveyor/);
  assert.equal(nextUp(base).go, "board");
});
T("the away digest skips routine runs and counts what matters", () => {
  const runs = [{at: ago(5), project: "a", duty: "s", verdict: "PR", detail: "#3 → https://github.com/o/r/pull/22"},
                {at: ago(20), project: "a", duty: "s", verdict: "DRY-RUN", detail: "0 finding(s)"},
                {at: ago(40), project: "a", duty: "s", verdict: "ERROR", detail: "x"},
                {at: ago(600), project: "a", duty: "old", verdict: "PR"}];
  const d = awayDigest(runs, ago(120), now);
  assert.deepEqual([d.total, d.failed, d.prs], [2, 1, 1]);
  assert.match(d.lines[0], /PR #22/);
  assert.equal(awayDigest(runs, null, now).fresh, true);
});
T("running lines say how long each job has been going", () => {
  assert.equal(runningLines([{status: "running", project: "wayfarer-mobile", duty: "shipwright", what: "issue #13 — i18n", since: ago(14)}], now)[0],
               "wayfarer-mobile: shipwright on #13 i18n, 14 minutes in");
});

T("agenda and reminders read out in order, with all-day and overdue handled", () => {
  const at = (d, h, m) => new Date(2026, 9, 3 + d, h, m).toISOString();
  const n = new Date(2026, 9, 3, 8, 0).getTime();
  const ev = [{title: "Standup", sub: "x", at: at(0, 9, 30)}, {title: "Sam birthday", sub: "Sat 3 Oct, all day", at: at(0, 0, 0)}, {title: "Flight", sub: "x", at: at(1, 8, 30)}];
  assert.deepEqual(agendaFor(ev, n).map(e => e.time), ["all day", "09:30"]);
  assert.equal(agendaText(ev, n), "Today: all day Sam birthday; 09:30 Standup. Tomorrow: 08:30 Flight.");
  const shuffled = [{title: "Late", sub: "x", at: at(0, 16, 22)}, {title: "Early", sub: "x", at: at(0, 9, 5)}];
  assert.deepEqual(agendaFor(shuffled, n).map(e => e.title), ["Early", "Late"]);
  assert.equal(agendaText([], n), "Nothing on your calendar today or tomorrow.");
  const rem = [{title: "Pay rent", at: at(-2, 9, 0)}, {title: "Call dentist", at: at(0, 15, 0)}, {title: "Someday", at: ""}];
  assert.equal(remindersText(rem, n), "1 overdue, 1 due today, 1 with no date. First: Pay rent.");
  assert.equal(remindersText([], n), "No open reminders.");
});

T("text is made pleasant to hear, and the wake word is spotted", () => {
  assert.equal(speakable("1 running. wayfarer-mobile: shipwright on #13 i18n, 14 minutes in."), "1 running. wayfarer mobile: shipwright on number 13 i18n, 14 minutes in.");
  assert.equal(speakable("PR #65 → https://github.com/o/r/pull/65 done"), "pull request 65, done");
  assert.equal(speakable("One. Two. Three. Four. Five."), "One. Two. Three.");
  assert.equal(speakable("Spent $3.50 today on v2.1. Two PRs open. Three. Four."), "Spent $3.50 today on v2.1. Two PRs open. Three.");
  assert.deepEqual(stripWake("Hey Helm, what is running?"), {woke: true, rest: "what is running?"});
  assert.deepEqual(stripWake("Elm"), {woke: true, rest: ""});
  assert.deepEqual(stripWake("what is the time"), {woke: false, rest: "what is the time"});
  assert.equal(stripWake("helmet laws").woke, false);
  assert.deepEqual(stripWake("Tell 'em are you there."), {woke: true, rest: "are you there."});
  assert.deepEqual(stripWake("to his helm."), {woke: true, rest: ""});
});

// Demo world: Helm reads the same state object, so it must answer sensibly on made-up data.
// The state is built by bin/demo.py at fixed seconds of the scenario, on a fixed local morning.
const demoAt = secs => JSON.parse(execFileSync("python3", ["-c", `
import sys, json, datetime
sys.path.insert(0, "bin")
import demo
t0 = datetime.datetime(2026, 10, 5, 10, 0).astimezone().timestamp()
w = demo.World(clock=lambda: t0)
w.clock = lambda: t0 + ${secs}
st = w.state()
st["_prs"] = w.open_prs(${secs})
print(json.dumps(st))
`], {encoding: "utf8", cwd: new URL("..", import.meta.url).pathname}));
const DS = {0: demoAt(0), 130: demoAt(130), 200: demoAt(200), 300: demoAt(300)};
const at = secs => Date.parse(DS[secs].now);
const conn = (S, n) => S.connectors.find(c => c.name === n).items;
// What the page feeds nextUp: the unacknowledged inbox as attention (obsAttention), plus the open pull requests.
const attentionOf = S => S.inbox.filter(x => !x.acknowledged).map(x => ({
  source: x.label || (x.project || "Local") + " · " + x.duty, text: x.text, view: x.place || "ledger", kind: x.severity}));
const pickNext = S => nextUp({attention: attentionOf(S), runs: S.runs, agents: S.agents, prs: S._prs, now: Date.parse(S.now)});

T("demo: 'what is running' names the agents and how long they have been going", () => {
  assert.equal(runningLines(DS[0].agents, at(0)).length, 1);        // the opening scene already has an agent at work
  assert.match(runningLines(DS[0].agents, at(0))[0], /^wayfarer-mobile: shipwright on #14/);
  const l = runningLines(DS[130].agents, at(130));
  assert.equal(l.length, 1);
  assert.match(l[0], /^wayfarer-api: shipwright on #131/);
  assert.match(l[0], /\d+ minutes? in$/);
  assert.equal(runningLines(DS[200].agents, at(200)).length, 2);
});
T("demo: 'what is next' follows the story: the failed run, then a pull request to review", () => {
  assert.equal(pickNext(DS[200]).title, "shipwright failed on wayfarer-api");
  assert.match(pickNext(DS[200]).why, /2 failing/);
  assert.equal(pickNext(DS[300]).title, "Review PR #132 on wayfarer-api");
});
T("demo: 'brief me' counts what the crew finished", () => {
  const d0 = awayDigest(DS[0].runs, null, at(0)), d3 = awayDigest(DS[300].runs, null, at(300));
  assert.ok(d0.total > 5 && d0.prs >= 3 && d0.failed >= 1, JSON.stringify(d0));
  assert.ok(d3.total > d0.total && d3.prs >= d0.prs + 3 && d3.failed >= 2, JSON.stringify(d3));
  assert.ok(d3.lines.length > 0 && d3.lines.every(x => x.startsWith("wayfarer") || x.startsWith("harvest") || x.startsWith("saltpan")));
});
T("demo: 'what is on today' and reminders read from the made-up calendar", () => {
  const n = at(0), a = agendaText(conn(DS[0], "calendar"), n);
  assert.match(a, /^Today: .*Sprint planning/);
  assert.match(a, /Design review: onboarding flow/);
  assert.match(a, /Tomorrow: .*1:1 with Priya/);
  assert.equal(remindersText(conn(DS[0], "reminders"), n), "1 overdue, 2 due today, 1 with no date. First: Renew the domain.");
});
T("demo: commands that write still ask for a click, and a made-up project name is understood", () => {
  const dctx = {views: ctx.views, projects: DS[0].projects.map(p => p.name)};
  assert.deepEqual(parseCommand("open wayfarer mobile", dctx), {intent: "project", project: "wayfarer-mobile"});
  assert.deepEqual(parseCommand("start work on issue 14 on wayfarer mobile", dctx), {intent: "work", action: "start", issue: 14, project: "wayfarer-mobile", confirm: true});
});
const feed = (S, n) => feedPanel(S.connectors.find(c => c.name === n), Date.parse(S.now));
T("feeds: analytics says the trend, the top pages and the sources, and a spike is called out", () => {
  const a = feed(DS[0], "analytics");
  assert.equal(a.state, "idle");
  assert.match(a.sub, /^18,420 views this week, \+14% vs last week\. Nothing needs you\.$/);
  assert.ok(a.lines.includes("Top pages:") && a.lines.some(l => l.startsWith("1. Pumpkin soup with sage: 1,120 views")), a.lines.join("|"));
  assert.ok(a.lines.some(l => l.startsWith("Traffic: Organic Search 6,120")));
  const spike = feed(DS[200], "analytics");
  assert.equal(spike.state, "new");
  assert.match(spike.sub, /^Brown butter rice pudding is up 640% \(4,210 views\)/);
  assert.ok(spike.lines.some(l => l.startsWith("1. Brown butter rice pudding")));
});
T("feeds: mail and Slack list who is waiting, and go red when it has waited over a day", () => {
  const m = feed(DS[0], "gmail"), now = at(0);
  assert.equal(m.state, "attn");                                   // the oldest demo mail is a day and more old
  assert.match(m.sub, /^4 waiting on you, latest from accounts@printshop\.example\. Oldest is over a day old\.$/);
  assert.ok(m.lines[0] === "4 waiting on you:" && m.lines.some(l => l.startsWith("Sam: Weekly planning notes")) && m.lines.includes("Most from Sam (2)."), m.lines.join("|"));
  const sl = feed(DS[130], "slack");
  assert.equal(sl.state, "new");
  assert.match(sl.sub, /^3 waiting on you, latest from #releases: mention\.$/);
  assert.ok(sl.lines.some(l => l.startsWith("Priya (DM): can you look at the release notes?")));
  const fresh = {name: "gmail", connected: true, unread: 1, items: [{title: "Hello", sub: "Sam", at: new Date(now - 3600e3).toISOString(), new: true}]};
  assert.equal(feedPanel(fresh, now).state, "new");
  assert.deepEqual(feedPanel({name: "slack", connected: true, unread: 0, items: []}, now), {state: "idle", sub: "Nothing is waiting on you.", lines: []});
});
T("feeds: social shows the latest post, the top post and the trend, and a new post wins the headline", () => {
  const l = feed(DS[0], "linkedin");
  assert.equal(l.state, "idle");
  assert.ok(l.lines.some(l => l.startsWith("Top post: Shipping a trip planner with three agents")), l.lines.join("|"));
  assert.ok(l.lines.some(l => /^Trend: the last 3 posts got 85 reactions and comments, the 3 before got 40 \(\+113%\)/.test(l)), l.lines.join("|"));
  assert.match(feed(DS[0], "facebook").sub, /^Latest post got 51 reactions and comments, \d+h ago\. Nothing needs you\.$/);
  const n = feed(DS[300], "instagram");
  assert.equal(n.state, "new");
  assert.match(n.sub, /^The pancake reel: 940 likes/);
  assert.ok(n.lines[0] === "New since you looked:");
});
T("feeds: an unconnected feed, a feed without a panel and junk give nothing, never an error", () => {
  assert.equal(feedPanel({name: "gmail", connected: false}), null);
  assert.equal(feedPanel(DS[0].connectors.find(c => c.name === "calendar")), null);
  assert.equal(feedPanel(undefined), null);
  for (const n of ["ga4", "gmail", "slack", "linkedin", "facebook", "instagram"])
    assert.ok(feedPanel({name: n, connected: true, items: [{title: 5, sub: null}, {}]}, 0));
  assert.equal(feedPanel({name: "ga4", connected: true}, 0).sub, "0 items. Nothing needs you.");
});
T("review: saying yes, merge or delete never becomes an action; every write asks for a click; a plan cannot smuggle a flag", () => {
  const wr = new Set(["run", "halt", "ack", "plan", "work"]);
  for (const t of ["yes", "yes do it", "yeah go ahead", "confirm", "do it", "ok", "sure", "merge pull request 5", "merge it", "merge the pull request on wayfarer mobile",
                   "delete the sentry fix job", "delete the job", "remove the sentry job", "delete the ledger", "drop the database"]) {
    const c = pd(t);
    assert.ok(!wr.has(c.intent), t + " -> " + JSON.stringify(c));
    assert.ok(!/merge|delete|remove/.test(c.intent), t);
  }
  for (const t of ["run the surveyor on harvest-pipeline", "stop the shipwright on wayfarer mobile", "dismiss the surveyor signal", "plan offline mode for wayfarer mobile",
                   "start work on issue 13", "review pull request 3 and apply it"])
    assert.equal(pd(t).confirm, true, t);
  assert.equal(cleanIdea("--apply the thing"), "apply the thing");
  assert.equal(cleanIdea("  -- --idea; rm -rf /"), "idea  rm -rf");
  assert.equal(cleanIdea("offline mode"), "offline mode");
  assert.equal(cleanIdea("---"), "");
});
T("ledger and log: a log line links to the run of the same project, duty and minute, and nothing else", () => {
  const runs = [
    {at: new Date(2026, 9, 5, 14, 3, 40).toISOString(), project: "wayfarer-mobile", duty: "shipwright", verdict: "PR"},
    {at: new Date(2026, 9, 5, 14, 3, 5).toISOString(), project: "harvest-pipeline", duty: "shipwright", verdict: "PR"},
    {at: new Date(2026, 9, 5, 14, 4, 1).toISOString(), project: "wayfarer-mobile", duty: "shipwright", verdict: "ERROR"}];
  assert.equal(logMinute("[2026-10-05 14:03:11] building"), new Date(2026, 9, 5, 14, 3).getTime());
  assert.equal(logMinute("[2026-10-05T12:03:11Z] started by dashboard"), Date.UTC(2026, 9, 5, 12, 3));
  assert.equal(logMinute("no stamp here"), null);
  assert.equal(runForLine("[2026-10-05 14:03:11] building", runs, "shipwright", "wayfarer-mobile"), runs[0]);
  assert.equal(runForLine("[2026-10-05 14:03:11] building", runs, "shipwright", "harvest-pipeline"), runs[1]);
  assert.equal(runForLine("[2026-10-05 14:03:11] building", runs, "surveyor", "wayfarer-mobile"), null);
  assert.equal(runForLine("[2026-10-05 14:05:00] later", runs, "shipwright", "wayfarer-mobile"), null);
  assert.equal(runForLine("[2026-10-05 14:04:59] x", runs, "shipwright", "wayfarer-mobile"), runs[2]);
  assert.equal(runForLine("[2026-10-05 14:03:11] x", [null, {}, {at: "nope"}], "shipwright", "wayfarer-mobile"), null);
  assert.equal(runForLine("[2026-10-05 14:03:11] x", undefined, "a", "b"), null);
  assert.equal(stampLength("[2026-10-05 14:03:11] building"), 21);
  assert.equal(stampLength("plain"), 0);
  assert.equal(crumbText("shipwright", "wayfarer-mobile"), "Ledger / shipwright on wayfarer-mobile / log");
});
T("your day: an event on two calendars is read once; different times, all-day and untimed items are kept", () => {
  const n = new Date(2026, 9, 5, 8, 0).getTime(), at = (h, m) => new Date(2026, 9, 5, h, m).toISOString();
  const ev = [{title: "Standup", sub: "Mon 09:30 · A", at: at(9, 30)}, {title: " standup ", sub: "Mon 09:30 · B", at: at(9, 30)},
              {title: "Planning", sub: "x", at: at(11, 0)}, {title: "Planning", sub: "x", at: at(12, 0)},
              {title: "Offsite", sub: "Mon, all day · A", at: at(0, 0)}, {title: "Offsite", sub: "Mon 00:00 · B", at: at(0, 0)}, {title: "Offsite", sub: "Mon, all day · B", at: at(0, 0)}];
  assert.deepEqual(dedupeEvents(ev).map(e => e.title.trim().toLowerCase()), ["standup", "planning", "planning", "offsite", "offsite"]);
  assert.equal(agendaText(ev, n), "Today: all day Offsite; 00:00 Offsite; 09:30 Standup; 11:00 Planning; 12:00 Planning.");
  assert.equal(ev.length, 7);                                      // the input is not changed
  assert.deepEqual(dedupeEvents([{title: "A", sub: "", at: ""}, {title: "A", sub: "", at: ""}]).length, 2);
  assert.deepEqual(dedupeEvents(undefined), []);
});
T("brain lists: a count and its list come from the same nodes, worst first, with a pointer for what is not connected", () => {
  const R = {code: {name: "Code"}, world: {name: "The world"}};
  const nodes = [
    {id: "p:a", label: "alpha", region: "code", kind: "project", hub: true, state: "live"},
    {id: "pr:a#1", label: "#1 fix", region: "code", kind: "pull request", parent: "p:a", state: "attn", sub: "checks failing", ref: {pr: 1, project: "a"}},
    {id: "pr:a#2", label: "#2 add", region: "code", kind: "pull request", parent: "p:a", state: "idle"},
    {id: "c:gmail", label: "Gmail", region: "world", kind: "connection", hub: true, state: "off", sub: "needs credentials", ref: {feed: "gmail"}},
    {id: "c:ga4", label: "Site analytics", region: "world", kind: "connection", hub: true, state: "off", ref: {feed: "ga4"}},
    {id: "c:slack", label: "Slack", region: "world", kind: "connection", hub: true, state: "new"},
    {id: "c:slack:1", label: "Priya (DM)", region: "world", kind: "Slack", parent: "c:slack", state: "new"},
    {id: "c:slack:2", label: "Lee (DM)", region: "world", kind: "Slack", parent: "c:slack", state: "idle"}];
  const count = st => nodes.filter(n => n.state === st).length;
  for (const st of ["attn", "live", "new", "off"]) assert.equal(listFor({kind: "state", key: st}, nodes, R).rows.length, count(st), st);
  assert.deepEqual(listFor({kind: "state", key: "attn"}, nodes, R).rows.map(r => r.id), ["pr:a#1"]);
  assert.equal(listFor({kind: "state", key: "attn"}, nodes, R).title, "Need you");
  assert.equal(listFor({kind: "state", key: "attn"}, nodes, R).rows[0].source, "Code / alpha / pull request");
  const off = listFor({kind: "state", key: "off"}, nodes, R).rows;
  assert.equal(off.length, 2);
  assert.equal(off.find(r => r.id === "c:gmail").doc, "README: Connecting your accounts, Gmail");
  assert.equal(off.find(r => r.id === "c:ga4").doc, "README: Connecting your accounts, Site analytics");
  assert.equal(docPointer({ref: {feed: "gmail"}}).startsWith("README:"), true);
  const region = listFor({kind: "region", key: "world"}, nodes, R);
  assert.equal(region.rows.length, 5);
  assert.deepEqual(region.rows.slice(0, 2).map(r => r.state), ["new", "new"]);                  // worst first
  assert.deepEqual(listFor({kind: "hub", key: "c:slack"}, nodes, R).rows.map(r => r.id), ["c:slack:1", "c:slack:2"]);
  assert.deepEqual(listFor({kind: "hub", key: "p:a", only: "attn"}, nodes, R).rows.map(r => r.id), ["pr:a#1"]);
  assert.deepEqual(listFor({kind: "nope"}, nodes, R), {title: "", rows: []});
  assert.deepEqual(listFor({kind: "state", key: "live"}, undefined, undefined).rows, []);
});
T("brain lists: Mark all seen is remembered, only hides what was new, and a hub with another new item is new again", () => {
  const mk = (extra = []) => [
    {id: "c:slack", label: "Slack", hub: true, state: "new"}, {id: "c:slack:1", label: "a", parent: "c:slack", state: "new"},
    {id: "m:1", label: "memory", state: "new"}, {id: "x:1", label: "idle", state: "idle"}, {id: "bad", label: "broken", state: "attn"}, ...extra];
  const seen = markSeen(mk(), []);
  assert.deepEqual(seen.slice().sort(), ["c:slack|1", "c:slack:1", "m:1"].sort());
  const after = applySeen(mk(), seen);
  assert.deepEqual(after.filter(n => n.state === "new").map(n => n.id), []);
  assert.equal(after.find(n => n.id === "bad").state, "attn");                                       // needs-you is never hidden
  const more = applySeen(mk([{id: "c:slack:2", label: "b", parent: "c:slack", state: "new"}]), seen);
  assert.deepEqual(more.filter(n => n.state === "new").map(n => n.id).sort(), ["c:slack", "c:slack:2"]);   // a new message: hub and item are new
  assert.equal(seenKey({id: "m:1"}, []), "m:1");
  assert.equal(markSeen(mk(), new Set(["old"])).includes("old"), true);
  assert.equal(markSeen(mk(), Array.from({length: 500}, (_, i) => "k" + i), 400).length, 400);
  assert.deepEqual(applySeen(mk(), undefined).filter(n => n.state === "new").length, 3);
  assert.equal(mk()[2].state, "new");                                                                   // the input was not changed
});
T("notes: ordinals, search, filters and what Helm reads out", () => {
  const notes = [{id: "a", at: "3", text: "Call the dentist", project: "", done: false}, {id: "b", at: "2", text: "Plan offline mode", project: "harvest-pipeline", done: false},
                 {id: "c", at: "1", text: "Renew the domain", project: "harvest-pipeline", done: true}, null, {id: "x", text: 5}];
  assert.deepEqual(["second", "2nd", "2", "two", "Tenth", "12"].map(ordinal), [2, 2, 2, 2, 10, 12]);
  assert.deepEqual(["", "zero", "0", "banana", null].map(ordinal), [null, null, null, null, null]);
  assert.deepEqual(filterNotes(notes).map(n => n.id), ["a", "b"]);
  assert.deepEqual(filterNotes(notes, {state: "done"}).map(n => n.id), ["c"]);
  assert.deepEqual(filterNotes(notes, {state: "all"}).map(n => n.id), ["a", "b", "c"]);
  assert.deepEqual(filterNotes(notes, {state: "all", project: "harvest-pipeline"}).map(n => n.id), ["b", "c"]);
  assert.deepEqual(filterNotes(notes, {state: "all", project: "-"}).map(n => n.id), ["a"]);
  assert.deepEqual(filterNotes(notes, {state: "all", q: "HARVEST-PIPELINE offline"}).map(n => n.id), ["b"]);
  assert.deepEqual(filterNotes(undefined), []);
  assert.equal(nthOpen(notes, 2).id, "b");
  assert.equal(nthOpen(notes, 3), null);
  assert.equal(notesText(notes), "2 open notes: 1, Call the dentist; 2, Plan offline mode.");
  assert.equal(notesText([]), "No open notes.");
  assert.equal(notesText(Array.from({length: 7}, (_, i) => ({id: "" + i, text: "n" + i, done: false}))).endsWith("5, n4; and 2 more."), true);
});
T("notes: Helm lists, marks done and promotes; the last two ask for a click; nothing deletes or merges", () => {
  const c = {views: [], projects: ["wayfarer-mobile", "wayfarer-web"], duties: ["shipwright"]}, q = t => parseCommand(t, c);
  for (const t of ["list my notes", "what are my open notes", "my notes", "read me my notes", "show me my brain dump"]) assert.deepEqual(q(t), {intent: "notes"}, t);
  assert.deepEqual(q("turn the second note into a plan for wayfarer mobile"), {intent: "promote", n: 2, kind: "plan", project: "wayfarer-mobile", confirm: true});
  assert.deepEqual(q("Turn note 3 into a mission for wayfarer web"), {intent: "promote", n: 3, kind: "mission", project: "wayfarer-web", confirm: true});
  assert.deepEqual(q("promote the 2nd note to a plan"), {intent: "promote", n: 2, kind: "plan", project: null, confirm: true});
  assert.deepEqual(q("mark the dentist note done"), {intent: "notedone", n: null, query: "dentist", confirm: true});
  assert.deepEqual(q("mark note 2 done"), {intent: "notedone", n: 2, query: "", confirm: true});
  assert.deepEqual(q("finish the dentist note"), {intent: "notedone", n: null, query: "dentist", confirm: true});
  assert.deepEqual(q("remember to call the dentist"), {intent: "capture", text: "call the dentist"});
  for (const t of ["delete the second note", "merge the second note", "turn the second note into a merge", "delete my notes"]) assert.ok(!["promote", "notedone", "notes"].includes(q(t).intent), t);
});
T("timeline: windows, filters, lanes and bins with many events, colours worst first", () => {
  const now = Date.parse("2026-10-05T12:00:00Z"), ago = m => new Date(now - m * 60000).toISOString();
  const ev = [{at: ago(10), project: "a", duty: "shipwright", verdict: "PR"}, {at: ago(12), project: "a", duty: "surveyor", verdict: "ERROR", detail: "tests failed"},
    {at: ago(13), project: "a", duty: "surveyor", verdict: "DRY-RUN"}, {at: ago(400), project: "b", duty: "joiner", verdict: "CLEAN"},
    {at: ago(2000), project: "b", duty: "joiner", verdict: "NEEDS_HUMAN"}, {at: ago(30), project: "b", duty: "dashboard", verdict: "MERGED", detail: "#9"},
    {at: ago(20), project: "elsewhere", duty: "scout-feed", verdict: "FAILED", kind: "other"}, {at: ago(5), project: "a", duty: "x", verdict: "PR"},
    {at: "junk", project: "a"}, null, {at: new Date(now + 3 * 3600e3).toISOString(), project: "a", duty: "future", verdict: "PR"}];
  assert.deepEqual(["PR", "ERROR", "DRY-RUN", "NEEDS_HUMAN", "MERGED", "banana"].map(v => classOf({verdict: v})), ["good", "bad", "quiet", "warn", "merge", "warn"]);
  assert.equal(classOf({kind: "other", verdict: "FAILED"}), "ext");              // any kind word an add-on gives its own events
  assert.equal(select(ev, {windowKey: "6h", now}).length, 6);              // not the 400 minute one at 6h? 400 min is 6h40, so it is out
  assert.equal(select(ev, {windowKey: "24h", now}).length, 7);
  assert.equal(select(ev, {windowKey: "7d", now}).length, 8);
  assert.deepEqual(select(ev, {windowKey: "7d", now}).map(e => e.at).slice(0, 2), [ago(5), ago(10)]);   // newest first
  assert.deepEqual(select(ev, {windowKey: "7d", now, project: "b"}).map(e => e.verdict), ["MERGED", "CLEAN", "NEEDS_HUMAN"]);
  assert.deepEqual(select(ev, {windowKey: "7d", now, verdict: "bad"}).map(e => e.verdict), ["ERROR"]);
  assert.deepEqual(select(ev, {windowKey: "7d", now, duty: "joiner"}).length, 2);
  assert.equal(select(ev, {windowKey: "nope", now}).length, 7);            // an unknown window is 24 hours
  assert.deepEqual(select(undefined), []);
  const L = buildLanes(ev, {windowKey: "24h", now, projects: ["a", "b", "c"], buckets: 24});
  assert.deepEqual(L.lanes.map(l => l.name), ["a", "b", "c", "elsewhere"]);
  assert.equal(L.total, 7);
  const a = L.lanes.find(l => l.name === "a");
  assert.equal(a.total, 4);
  assert.equal(a.bins.length, 1);                                          // 5, 10, 12, 13 minutes ago share the newest hour
  assert.equal(a.bins[0].n, 4); assert.equal(a.bins[0].cls, "bad"); assert.equal(a.bins[0].first.verdict, "ERROR");
  assert.match(binText(a.bins[0], () => "12:00"), /^12:00: 4 events, 1 PR, 1 ERROR, 1 DRY-RUN|^12:00: 4 events/);
  assert.equal(L.lanes.find(l => l.name === "c").bins.length, 0);          // a known project with no events keeps its lane
  assert.ok(pct(a.bins[0], L.from, L.to) > 90 && pct(a.bins[0], L.from, L.to) <= 100);
  assert.equal(buildLanes(ev, {windowKey: "24h", now, project: "b"}).lanes.length, 1);
  assert.deepEqual(axisTicks("6h", now, () => "t").map(t => t.label), ["t", "t", "t", "t", "now"]);
  assert.ok(CLASSES.length === 6 && WINDOWS["7d"] === 7 * 86400e3);
});
T("timeline: 5000 events cost the same as 50: at most one marker per bin, built in a blink", () => {
  const now = Date.now(), ev = Array.from({length: 5000}, (_, i) => ({at: new Date(now - (i * 97 % (7 * 86400)) * 1000).toISOString(),
    project: "p" + (i % 8), duty: "d" + (i % 5), verdict: ["PR", "ERROR", "CLEAN", "DRY-RUN"][i % 4]}));
  const t0 = Date.now(), L = buildLanes(ev, {windowKey: "7d", now, buckets: 96}), ms = Date.now() - t0;
  assert.equal(L.total, 5000);
  assert.ok(L.lanes.length === 8 && L.lanes.every(l => l.bins.length <= 96 && l.bins.every(b => b.events.length <= 5)));
  assert.equal(L.lanes.reduce((n, l) => n + l.bins.reduce((m, b) => m + b.n, 0), 0), 5000);
  assert.ok(ms < 500, "took " + ms + " ms");
});
T("timeline: the Home strip is the newest 12 of runs, merges and an add-on's own events together", () => {
  const now = Date.parse("2026-10-05T12:00:00Z"), ago = m => new Date(now - m * 60000).toISOString();
  const runs = Array.from({length: 15}, (_, i) => ({at: ago(i * 10), project: "a", duty: "x", verdict: i === 3 ? "MERGED" : "PR"}));
  const hz = [{at: ago(25), project: "elsewhere", duty: "job", verdict: "FAILED", kind: "other"}];
  const strip = recentStrip(runs, hz, 12);
  assert.equal(strip.length, 12);
  assert.ok(strip.some(e => e.kind === "other") && strip.some(e => e.kind === "merge"));
  assert.deepEqual(strip.slice(0, 3).map(e => e.at), [ago(0), ago(10), ago(20)]);
  assert.deepEqual(recentStrip(undefined, undefined), []);
});
const SNOW = Date.parse("2026-10-05T12:00:00Z"), sago = m => new Date(SNOW - m * 60000).toISOString(), sin = m => new Date(SNOW + m * 60000).toISOString();
const snap = (S = {}, prs = null) => ({S: {runs: [], agents: [], connectors: [], integrations: {}, ...S}, prs});
const kinds = (a, b) => detect(a, b, SNOW).map(e => e.kind);
T("suggest: a pull request whose checks just passed, and a run that just failed, each with one way to look", () => {
  const pr = (pending, fail, pass) => ({project: "a", number: 7, title: "Fix it", url: "https://github.com/o/a/pull/7", checks: {pending, fail, pass}});
  assert.deepEqual(kinds(snap({}, [pr(2, 0, 2)]), snap({}, [pr(0, 0, 4)])), ["pr-green"]);
  assert.deepEqual(kinds(snap({}, [pr(0, 1, 3)]), snap({}, [pr(0, 0, 4)])), ["pr-green"]);                 // red, then fixed
  assert.deepEqual(kinds(snap({}, [pr(0, 0, 4)]), snap({}, [pr(0, 0, 4)])), []);                           // green before and after: nothing
  assert.deepEqual(kinds(null, snap({}, [pr(0, 0, 4)])), []);                                               // first look: no change to report
  assert.deepEqual(kinds(snap({}, [pr(2, 0, 2)]), snap({}, [pr(1, 0, 3)])), []);                           // still running
  const e = detect(snap({}, [pr(2, 0, 2)]), snap({}, [pr(0, 0, 4)]), SNOW)[0];
  assert.deepEqual(e.action, {label: "Open pull request", type: "url", url: "https://github.com/o/a/pull/7"});
  assert.equal(detect(snap({}, [pr(2, 0, 2)]), snap({}, [{...pr(0, 0, 4), url: "javascript:x"}]), SNOW)[0].action.type, "go");   // never a non-https link
  const bad = {at: sago(5), project: "a", duty: "shipwright", verdict: "ERROR", detail: "tests failed"};
  const ok = {at: sago(9), project: "a", duty: "surveyor", verdict: "CLEAN", detail: ""};
  const f = detect(snap({runs: [ok]}), snap({runs: [bad, ok]}), SNOW);
  assert.deepEqual(f.map(x => x.kind), ["run-failed"]);
  assert.equal(f[0].sev, 3); assert.equal(f[0].title, "shipwright failed on a"); assert.deepEqual(f[0].action, {label: "See why", type: "ledger", key: `${bad.at}|a|shipwright`, project: "a"});
  assert.deepEqual(kinds(snap({runs: [bad]}), snap({runs: [bad]})), []);                                   // already known
  assert.deepEqual(kinds(null, snap({runs: [bad]})), []);                                                  // first look
  assert.deepEqual(kinds(snap({runs: []}), snap({runs: [{...bad, at: sago(60 * 7)}]})), []);                 // too old to be news
});
T("suggest: a long agent, mail waiting over a day, a page that doubled, an overdue reminder, a meeting soon, a broken feed", () => {
  const S = {agents: [{status: "running", duty: "shipwright", project: "a", lock: "L1", since: sago(70), what: "issue #1"}, {status: "running", duty: "surveyor", project: "a", lock: "L2", since: sago(10)},
                      {status: "idle", duty: "joiner", project: "a", since: null}],
    connectors: [
      {name: "gmail", label: "Gmail", connected: true, unread: 2, items: [{title: "Invoice", sub: "Print shop", at: sago(60 * 30)}, {title: "Hi", sub: "Sam", at: sago(60)}]},
      {name: "slack", label: "Slack", connected: true, unread: 1, items: [{title: "Priya (DM)", sub: "lunch?", at: sago(60)}]},
      {name: "ga4", label: "Analytics", connected: true, items: [{title: "Last 7 days: 1,000 views", sub: "x"}, {title: "Brown butter", sub: "4,210 views, +640% vs last week", url: "https://blog.example/b"}, {title: "Small", sub: "40 views, +300% vs last week"}, {title: "Up", sub: "900 views, +20% vs last week"}]},
      {name: "reminders", label: "Reminders", connected: true, items: [{title: "Call the dentist", at: sago(20)}, {title: "Next week", at: sin(60 * 24 * 7)}, {title: "Ancient", at: sago(60 * 24 * 9)}, {title: "No date", at: ""}]},
      {name: "calendar", label: "Calendar", connected: true, items: [{title: "Standup", sub: "Mon 12:10", at: sin(10)}, {title: "Retro", sub: "Mon 13:00", at: sin(60)}, {title: "Offsite", sub: "Mon, all day", at: sin(5)}, {title: "Over", sub: "x", at: sago(5)}]}],
    integrations: {facebook: {ok: false, error_short: "token expired"}, gmail: {ok: true}}};
  const out = detect(null, snap(S), SNOW), byKind = Object.fromEntries(out.map(e => [e.kind, e]));
  assert.deepEqual(out.map(e => e.kind).sort(), ["agent-long", "doubled", "feed-broke", "meeting", "overdue", "waiting"]);
  assert.match(byKind["agent-long"].title, /^shipwright on a has run 70 min$/);                             // the 10 minute surveyor is not long
  assert.match(byKind.waiting.title, /^Gmail: something has waited 30 h$/);                                  // Slack is only an hour old
  assert.equal(byKind.doubled.title, "Brown butter doubled"); assert.equal(byKind.doubled.action.url, "https://blog.example/b");
  assert.equal(byKind.overdue.title, "Overdue: Call the dentist");
  assert.equal(byKind.meeting.title, "Standup starts in 10 min"); assert.equal(byKind.meeting.sev, 3);
  assert.deepEqual(byKind["feed-broke"].action, {label: "Open facebook", type: "brain", node: "c:facebook"});
  assert.deepEqual(out.map(e => e.sev), [...out.map(e => e.sev)].sort((a, b) => b - a));                    // most important first
  assert.ok(out.every(e => e.action && ["url", "go", "brain", "ledger"].includes(e.action.type) && e.title.length <= 90 && e.why.length <= 140));
  assert.ok(Object.keys(LONG_MINUTES).includes("shipwright"));
  assert.deepEqual(detect(null, snap({}), SNOW), []);
  assert.deepEqual(detect(null, undefined, SNOW), []);
  assert.deepEqual(detect(null, snap({agents: [{status: "running", duty: "x", since: "junk"}], connectors: [{name: "gmail", connected: true, unread: 1, items: [{title: 1}]}, null]}), SNOW), []);
});
T("suggest: calm by design: one at a time, worst first, snooze for an hour, dismiss for good, twenty remembered", () => {
  const mk = (id, sev, at, live = false) => ({id, kind: "k", sev, title: id, why: "", at: new Date(at).toISOString(), action: null, live});
  let st = ingest(emptyStore(), [mk("a", 1, SNOW - 5000), mk("b", 3, SNOW - 9000), mk("c", 3, SNOW - 1000)], SNOW);
  assert.equal(pick(st, [], SNOW).id, "c");                                                                  // same severity: the newest
  st = snooze(st, "c", SNOW); assert.equal(pick(st, [], SNOW).id, "b");
  assert.equal(pick(st, [], SNOW + 59 * 60000).id, "b");
  assert.equal(pick(ingest(st, [], SNOW + 61 * 60000), [], SNOW + 61 * 60000).id, "c");                    // the hour is up: back
  st = dismiss(st, "b", SNOW); st = dismiss(st, "c", SNOW);
  assert.equal(pick(st, [], SNOW).id, "a");
  assert.equal(pick(dismiss(st, "a", SNOW), [], SNOW), null);
  assert.equal(pick(ingest(dismiss(st, "a", SNOW), [mk("a", 1, SNOW)], SNOW + 1000), [], SNOW + 1000), null); // seen again after dismissal: still dismissed
  assert.equal(pick(ingest(dismiss(st, "a", SNOW), [], SNOW + 4 * 86400e3), [], SNOW + 4 * 86400e3), null);       // the log entry is old by then
  const live = ingest(emptyStore(), [mk("m", 3, SNOW, true)], SNOW);
  assert.equal(pick(live, ["m"], SNOW).id, "m"); assert.equal(pick(live, [], SNOW), null);                  // a state that stopped being true goes away
  assert.equal(pick(ingest(emptyStore(), [mk("old", 3, SNOW - 7 * 3600e3)], SNOW), [], SNOW), null);        // a change older than six hours goes away
  const many = ingest(emptyStore(), Array.from({length: 40}, (_, i) => mk("e" + i, 1, SNOW + i)), SNOW);
  assert.equal(many.log.length, KEEP);
  assert.equal(ingest(many, [mk("e0", 1, SNOW)], SNOW).log.length, KEEP);
  assert.equal(JSON.stringify(emptyStore()), '{"log":[],"dismissed":{},"snoozed":{}}');
});
T("suggest: speaking is off by default, once per suggestion, at most every five minutes, never while Helm is busy", () => {
  const base = {enabled: true, id: "x", spoken: [], lastAt: 0, now: SNOW, busy: false};
  assert.equal(shouldSpeak(base), true);
  assert.equal(shouldSpeak({...base, enabled: false}), false);
  assert.equal(shouldSpeak({...base, enabled: undefined}), false);
  assert.equal(shouldSpeak({...base, busy: true}), false);
  assert.equal(shouldSpeak({...base, spoken: ["x"]}), false);
  assert.equal(shouldSpeak({...base, lastAt: SNOW - 4 * 60000}), false);
  assert.equal(shouldSpeak({...base, lastAt: SNOW - 5 * 60000}), true);
  assert.equal(shouldSpeak({...base, id: ""}), false);
  assert.equal(spokenText({title: "Standup starts in 10 min", why: "Mon 12:10"}), "Standup starts in 10 min. Mon 12:10");
  assert.equal(spokenText(null), "");
});
T("conversation: the spoken switches are fixed phrases, and none of them changes anything on the dashboard", () => {
  const c = {views: [], projects: ["wayfarer-mobile"], duties: ["shipwright"]}, q = t => parseCommand(t, c);
  assert.deepEqual(q("think with me"), {intent: "deep", on: true, topic: ""});
  assert.deepEqual(q("Helm, let's think about the release plan"), {intent: "deep", on: true, topic: "the release plan"});
  assert.deepEqual(q("think about offline mode with me"), {intent: "deep", on: true, topic: "offline mode"});
  assert.deepEqual(q("let's think"), {intent: "deep", on: true, topic: ""});
  assert.deepEqual(q("back to normal"), {intent: "deep", on: false});
  assert.deepEqual(q("that's enough"), {intent: "deep", on: false});
  assert.deepEqual(q("start over"), {intent: "reset"});
  assert.deepEqual(q("forget that"), {intent: "reset"});
  assert.deepEqual(q("include my agenda"), {intent: "include", what: "agenda"});
  assert.deepEqual(q("include my calendar"), {intent: "include", what: "agenda"});
  assert.deepEqual(q("include my notes"), {intent: "include", what: "notes"});
  assert.deepEqual(q("Helm, that's all"), {intent: "bye"});
  assert.deepEqual(q("let's talk about the weekend"), {intent: "talk", topic: "the weekend"});
  assert.equal(q("what is running").intent, "running");                       // a command is still a command
  assert.equal(q("stop").intent, "stop");
  for (const t of ["think with me", "back to normal", "start over", "include my notes", "that's all", "let's talk about it"]) assert.ok(!q(t).confirm, t);
});
T("conversation: memory keeps 12 turns, forgets after 30 minutes, and is sent as roles, words and the source tag only", () => {
  let m = emptyMemory(), t0 = 1e12;
  for (let i = 0; i < 20; i++) m = cvPush(m, i % 2 ? "assistant" : "user", "turn " + i, t0 + i * 1000);
  assert.equal(m.turns.length, MAX_TURNS); assert.equal(m.turns[0].content, "turn 8"); assert.equal(m.turns.at(-1).content, "turn 19");
  assert.deepEqual(forRequest(m)[0], {role: "user", content: "turn 8", src: "cmd"});
  assert.deepEqual(Object.keys(forRequest(m)[0]).sort(), ["content", "role", "src"]);
  m.deep = true; m.include.notes = true;
  assert.equal(cvExpire(m, t0 + 19000 + IDLE_MS).turns.length, MAX_TURNS);                       // exactly 30 minutes: still here
  const gone = cvExpire(m, t0 + 19000 + IDLE_MS + 1);
  assert.deepEqual(gone, emptyMemory()); assert.equal(gone.deep, false); assert.equal(gone.include.notes, false);
  assert.equal(cvPush(m, "user", "hello", t0 + 19000 + IDLE_MS + 5000).turns.length, 1);          // a turn after the silence starts afresh
  assert.equal(cvPush(m, "system", "x", t0).turns.length, MAX_TURNS);                              // only user and assistant turns are kept
  assert.equal(cvPush(emptyMemory(), "user", "   ", t0).turns.length, 0);
  assert.equal(cvPush(emptyMemory(), "user", "x".repeat(5000), t0).turns[0].content.length, 600);
  assert.deepEqual(forRequest(undefined), []);
  const input = emptyMemory(); cvPush(input, "user", "a", t0); assert.equal(input.turns.length, 0);   // pure
});
T("conversation: a command beats conversation; none becomes conversation; a clarify about a command stays a command", () => {
  assert.equal(route({intent: "running"}, "what is running"), "command");
  assert.equal(route({intent: "work", action: "start"}, "start work on 3"), "command");
  assert.equal(route({intent: "none"}, "what do you think about offline mode"), "conversation");
  assert.equal(route({intent: "talk", topic: "x"}, "let's talk about x"), "conversation");
  assert.equal(route({intent: "clarify", say: "Which one?"}, "what about the other one"), "conversation");
  assert.equal(route({intent: "clarify", say: "I need an issue number"}, "start work on the thing"), "command");
  assert.equal(route({intent: "clarify", say: "Which note?"}, "mark the note done"), "command");
  assert.equal(route({intent: "unknown", heard: "x"}, "x"), "unknown");                           // the classifier was not available
  assert.equal(route(undefined, "x"), "command");
  assert.ok(looksLikeCommand("Helm, please stop the shipwright") && looksLikeCommand("note 2") && looksLikeCommand("issue 12 is stuck"));
  assert.ok(!looksLikeCommand("why did that fail") && !looksLikeCommand("and wayfarer mobile?") && !looksLikeCommand("what do you think"));
  assert.ok(!looksLikeCommand(undefined));
});
T("turns: the numbers are constants, and what the microphone listens for changes while Helm speaks", () => {
  assert.deepEqual([TT.END_MS_COMMAND, TT.END_MS_CONVERSATION, TT.FOLLOW_MS_COMMAND, TT.FOLLOW_MS_CONVERSATION, TT.DEAF_AFTER_PLAYBACK_MS, TT.SLOW_ACK_MS], [900, 1400, 8000, 20000, 300, 2000]);
  assert.ok(TT.THRESHOLD_SPEAKING > TT.THRESHOLD * 2 && TT.ONSET_MS_SPEAKING >= TT.ONSET_MS * 2);          // a higher bar and a longer onset while Helm talks
  assert.deepEqual(listenParams(), {deaf: false, speaking: false, threshold: 0.02, onsetMs: 120, endMs: 900, peekMs: 0});
  assert.deepEqual(listenParams({conversation: true}), {deaf: false, speaking: false, threshold: 0.02, onsetMs: 120, endMs: 1400, peekMs: 900});
  assert.deepEqual(listenParams({speaking: true}), {deaf: false, speaking: true, threshold: 0.06, onsetMs: 320, endMs: 900, peekMs: 0});
  assert.equal(listenParams({speaking: true, bargeIn: false}).deaf, true);                                   // interruption switched off: deaf while Helm talks
  assert.equal(listenParams({sinceSpeechEndMs: 100}).deaf, true);                                            // the room still rings
  assert.equal(listenParams({sinceSpeechEndMs: 299}).deaf, true);
  assert.equal(listenParams({sinceSpeechEndMs: 300}).deaf, false);
  assert.equal(listenParams({sinceSpeechEndMs: null}).deaf, false);
  assert.equal(followMs(false), 8000); assert.equal(followMs(true), 20000);
  assert.equal(needsWake({handsFree: true, now: 100, followUntil: 200}), false);
  assert.equal(needsWake({handsFree: true, now: 200, followUntil: 200}), true);
  assert.equal(needsWake({handsFree: false, now: 999, followUntil: 0}), false);
});
T("turns: decisions: listen, stop speaking, end the turn, peek", () => {
  const quiet = listenParams(), talking = listenParams({speaking: true}), conv = listenParams({conversation: true});
  assert.equal(decide({type: "voice", rms: 0.05, voicedMs: 150}, quiet), "listen");
  assert.equal(decide({type: "voice", rms: 0.05, voicedMs: 100}, quiet), "ignore");                         // not long enough yet
  assert.equal(decide({type: "voice", rms: 0.01, voicedMs: 500}, quiet), "ignore");                          // not loud enough
  assert.equal(decide({type: "voice", rms: 0.04, voicedMs: 900}, talking), "ignore");                        // echo of Helm's own voice
  assert.equal(decide({type: "voice", rms: 0.09, voicedMs: 200}, talking), "ignore");                        // loud but short: a cough
  assert.equal(decide({type: "voice", rms: 0.09, voicedMs: 320}, talking), "stop_speaking");
  assert.equal(decide({type: "voice", rms: 0.09, voicedMs: 900}, listenParams({speaking: true, bargeIn: false})), "ignore");
  assert.equal(decide({type: "voice", rms: 0.9, voicedMs: 900}, listenParams({sinceSpeechEndMs: 50})), "ignore");
  assert.equal(decide({type: "quiet", quietMs: 899, segMs: 3000}, quiet), "ignore");
  assert.equal(decide({type: "quiet", quietMs: 900, segMs: 3000}, quiet), "end_turn");
  assert.equal(decide({type: "quiet", quietMs: 900, segMs: 3000}, conv), "peek");                           // in a conversation a pause only asks first
  assert.equal(decide({type: "quiet", quietMs: 900, segMs: 3000, peeked: true}, conv), "ignore");
  assert.equal(decide({type: "quiet", quietMs: 1399, segMs: 3000, peeked: true}, conv), "ignore");
  assert.equal(decide({type: "quiet", quietMs: 1400, segMs: 3000, peeked: true}, conv), "end_turn");
  assert.equal(decide({type: "quiet", quietMs: 0, segMs: 20000}, quiet), "end_turn");                       // never longer than 20 seconds
  assert.equal(decide({type: "nope"}, quiet), "ignore");
});
T("turns: a sentence is clearly finished only with its stop and enough words", () => {
  for (const t of ["How is the web project doing?", "What is running right now.", "Tell me about the failing pull request!", "Yes.", "Thank you.", "Stop."]) assert.equal(sentenceFinished(t), true, t);
  for (const t of ["How is the web project", "what about the other one and", "so,", "Okay so what do you think about the.", "", "hmm.", "go.", "And then, because."]) assert.equal(sentenceFinished(t), false, t);
  assert.equal(sentenceFinished(undefined), false);
});
const pushAll = (sg, rmsList, ms = 50) => { for (const r of rmsList) sg.push(new Float32Array(1), r, ms); };
const rep = (r, n) => Array(n).fill(r);
T("turns: the recorder starts on a voice, ends a command after 0.9 s and a conversation turn after 1.4 s", () => {
  const got = []; let p = listenParams();
  const sg = createSegmenter({timing: () => p, onOnset: o => got.push(["onset", o.stopSpeaking]), onSegment: (c, h) => got.push(["segment", c.length, h])});
  pushAll(sg, [...rep(0.001, 10), ...rep(0.1, 10), ...rep(0.001, 17)]);                                         // 850 ms of quiet: still recording
  assert.deepEqual(got, [["onset", false]]);
  pushAll(sg, [0.001]);                                                                                          // 900 ms: the command is over
  assert.equal(got.at(-1)[0], "segment");
  assert.ok(got.at(-1)[1] >= 10 + 18);
  got.length = 0; p = listenParams({conversation: true});
  pushAll(sg, [...rep(0.1, 10), ...rep(0.001, 27)]);                                                             // 1350 ms of quiet: a conversation waits
  assert.deepEqual(got, [["onset", false]]);
  pushAll(sg, [0.001]); pushAll(sg, [0.001]);
  assert.equal(got.at(-1)[0], "segment");
  got.length = 0; p = listenParams();
  pushAll(sg, [...rep(0.1, 4), ...rep(0.001, 30)]);                                                              // 200 ms of voice, then silence: a blip, not a turn
  assert.deepEqual(got, [["onset", false]]);                                                                  // it started (120 ms) but is too short to hand on
});
T("turns: talking over Helm stops it at once, its own echo does not, and the room is ignored for 0.3 s after it stops", () => {
  const got = []; let p = listenParams({speaking: true});
  const sg = createSegmenter({timing: () => p, onOnset: o => got.push(["onset", o.stopSpeaking]), onSegment: () => got.push(["segment"])});
  pushAll(sg, rep(0.045, 60));                                                                                   // 3 seconds of echo at a level that would trigger a normal listen
  assert.deepEqual(got, []);
  pushAll(sg, rep(0.09, 6));                                                                                     // 300 ms of a real voice: not yet
  assert.deepEqual(got, []);
  pushAll(sg, rep(0.09, 1));                                                                                     // 350 ms: Helm stops
  assert.deepEqual(got, [["onset", true]]);
  p = listenParams({sinceSpeechEndMs: 10});                                                                   // Helm has stopped; the recording goes on despite the deaf window
  pushAll(sg, [...rep(0.09, 4), ...rep(0.001, 18)]);
  assert.equal(got.at(-1)[0], "segment");
  got.length = 0; p = listenParams({sinceSpeechEndMs: 100});
  pushAll(sg, rep(0.2, 10));                                                                                     // loud, but 100 ms after playback ended: ignored
  assert.deepEqual(got, []);
  p = listenParams({sinceSpeechEndMs: 400}); pushAll(sg, rep(0.2, 4));
  assert.deepEqual(got, [["onset", false]]);
});
T("turns: in a conversation a pause is checked once, and a clearly finished sentence ends the turn early with its words", async () => {
  const got = []; let peeks = 0, finished = true; const p = listenParams({conversation: true});
  const sg = createSegmenter({timing: () => p, onOnset: () => got.push("onset"), onPeek: async () => { peeks++; return {text: "How is it going?", finished}; }, onSegment: (c, h) => got.push(["segment", h])});
  pushAll(sg, [...rep(0.1, 10), ...rep(0.001, 18)]);                                                             // 900 ms of quiet: peek
  assert.equal(peeks, 1);
  await new Promise(r => setTimeout(r, 5));
  assert.deepEqual(got, ["onset", ["segment", "How is it going?"]]);                                          // ended early, with the peek's text
  got.length = 0; peeks = 0; finished = false;
  pushAll(sg, [...rep(0.1, 10), ...rep(0.001, 18)]);
  await new Promise(r => setTimeout(r, 5));
  assert.equal(peeks, 1); assert.deepEqual(got, ["onset"]);                                                   // not finished: it keeps listening
  pushAll(sg, rep(0.001, 8));                                                                                    // up to 1.3 s
  assert.deepEqual(got, ["onset"]); assert.equal(peeks, 1);                                                   // and does not ask twice
  pushAll(sg, rep(0.001, 2));                                                                                    // 1.4 s: over, with no hint
  assert.deepEqual(got.at(-1), ["segment", undefined]);
  got.length = 0; peeks = 0; finished = true;
  pushAll(sg, [...rep(0.1, 10), ...rep(0.001, 18), ...rep(0.1, 2)]);                                            // the owner spoke again before the peek answered
  await new Promise(r => setTimeout(r, 5));
  assert.deepEqual(got, ["onset"]);                                                                           // the stale answer ends nothing
});
T("conversation safety: an ACTION line from a model only becomes a command Helm understands, writes still need the click, and nothing else is run", () => {
  const ctx = {views: [{id: "ledger", label: "Ledger"}, {id: "inbox", label: "Needs you"}], projects: ["wayfarer-mobile", "wayfarer-web"], duties: ["shipwright", "surveyor"]};
  const ok = t => actionAccepted(parseCommand(t, ctx));
  for (const t of ["what is running", "brief me", "open the ledger", "open needs you", "open wayfarer mobile", "list my notes", "what is next", "find the memory about offline", "what are my open missions"]) assert.equal(ok(t), true, t);
  for (const t of ["start work on issue 12 on wayfarer mobile", "run the surveyor on wayfarer mobile", "stop the shipwright on wayfarer mobile", "dismiss the surveyor signal",
                   "plan offline mode for wayfarer mobile", "mark the dentist note done", "turn the second note into a plan for wayfarer mobile"]) {
    const c = parseCommand(t, ctx);
    assert.equal(actionAccepted(c), true, t); assert.equal(c.confirm, true, t + " must ask for a click");
  }
  for (const t of ["remember to call the dentist", "think with me", "let's think about it", "back to normal", "start over", "include my notes", "that's all", "stop", "help",
                   "let's talk about the weekend", "delete everything", "merge pull request 12", "sudo rm -rf /", "send an email to everyone", "ACTION: open the ledger", ""]) assert.equal(ok(t), false, JSON.stringify(t));
  assert.equal(parseCommand("open https://evil.example", ctx).intent, "find");                                  // only ever a search of the Brain, never a link
  for (const i of WRITES_NEED_CLICK) assert.ok(ACTION_INTENTS.has(i), i);
  assert.ok(!ACTION_INTENTS.has("capture") && !ACTION_INTENTS.has("deep") && !ACTION_INTENTS.has("include") && !ACTION_INTENTS.has("reset") && !ACTION_INTENTS.has("stop"));
  assert.equal(actionAccepted(null), false); assert.equal(actionAccepted({intent: "work"}), false);          // a write without a confirm flag is refused
  assert.equal(actionAccepted({intent: "work", confirm: true}), true);
  assert.equal(actionLine("ACTION: open the ledger."), "open the ledger"); assert.equal(actionLine("  action:  what is running  "), "what is running");
  assert.equal(actionLine("I will ACTION: no"), ""); assert.equal(actionLine("ACTION:"), ""); assert.equal(actionLine(undefined), ""); assert.equal(actionLine("ACTION: " + "x".repeat(300)), "");
});

import * as _cv from "../dashboard/assets/convo.js";
T("conversation memory remembers where each turn came from, and says so on the way out", () => {
  let m = _cv.emptyMemory();
  m = _cv.push(m, "user", "what is on today", 1000, "cmd");
  m = _cv.push(m, "assistant", "Today: dentist at 9", 1001, "cmd");
  m = _cv.push(m, "user", "should I move it", 1002, "chat");
  m = _cv.push(m, "assistant", "Only if it clashes.", 1003);          // no source given: treated as a command turn, never sent to Claude
  assert.deepEqual(_cv.forRequest(m).map(t => t.src), ["cmd", "cmd", "chat", "cmd"]);
  assert.equal(_cv.push(m, "user", "x", 1004, "anything-else").turns.at(-1).src, "cmd");
});

// ---- attention metrics (invented numbers only) ----
const ATD = {
  quarterdeck: {"2026-10-05": {commits: 23}, "2026-10-04": {commits: 33}, "2026-09-26": {commits: 27}},
  "saltpan-blog": {"2026-10-05": {commits: 10}, "2026-09-30": {commits: 13}, "2026-09-29": {commits: 13}},
  tiny: {"2026-10-05": {commits: 2}},
  oldapp: {"2026-09-10": {commits: 15}},
  other: {"2026-10-05": {commits: 166}}, "(calendar)": {"2026-10-05": {meetings: 5}}};
const TODAY = "2026-10-06";   // a Tuesday
T("attention: share by project over a window, named projects only, and bands rather than false precision", () => {
  const sh = AT.share(ATD, TODAY, 7);
  assert.deepEqual(sh.map(x => x.project), ["quarterdeck", "saltpan-blog", "tiny"]);          // other and the calendar never count as projects; oldapp is outside the window
  assert.ok(Math.abs(sh.reduce((a, x) => a + x.share, 0) - 1) < 1e-9);
  assert.equal(AT.band(sh[0].share), "about two thirds");
  assert.equal(AT.band(0.34), "about a third"); assert.equal(AT.band(0.005), "a sliver"); assert.equal(AT.band(0), "none"); assert.equal(AT.band(NaN), "none"); assert.equal(AT.band(0.97), "nearly all");
  assert.deepEqual(AT.share({}, TODAY), []); assert.deepEqual(AT.share(undefined, TODAY), []);
});
T("attention: velocity is smoothed and needs volume, so tiny numbers never read as 340 percent", () => {
  const r = AT.ratio(4, 1); assert.ok(r < 1.5, String(r));                        // 5x raw, about 1.4 smoothed
  const e = AT.emerging(ATD, TODAY);
  assert.deepEqual(e.map(x => x.project), ["quarterdeck"]);                              // saltpan-blog is about level, tiny has too little volume
  assert.equal(e[0].word, "about twice"); assert.equal(AT.ratioWord(3.1), "about 3x"); assert.equal(AT.ratioWord(9), "5x or more"); assert.equal(AT.ratioWord(1), "about the same"); assert.equal(AT.ratioWord(0.5), "down about half");
  assert.equal(AT.homeLine(ATD, TODAY), "quarterdeck is up about twice this week."); assert.equal(AT.homeLine({}, TODAY), null);
  assert.equal(AT.velocity({tiny: {"2026-10-05": {commits: 1}}}, TODAY)[0].enough, false);
});
T("attention: dormant counts weekdays only, honours Park, Archive and Continue, and does not call an untracked project dormant too early", () => {
  const ps = ["quarterdeck", "saltpan-blog", "tiny", "oldapp", "never"];
  const d = AT.dormant(ATD, TODAY, ps);
  assert.deepEqual(d.map(x => x.project), ["oldapp", "never"]);                        // oldapp quiet 18 weekdays; never seen but the data is old enough
  assert.equal(d[0].quiet, AT.weekdaysBetween("2026-09-10", TODAY));
  assert.equal(AT.weekdaysBetween("2026-10-02", "2026-10-05"), 1);                   // Friday to Monday: only Monday counts
  assert.equal(AT.weekdaysBetween("2026-10-03", "2026-10-04"), 0);                   // Saturday to Sunday
  assert.deepEqual(AT.dormant(ATD, TODAY, ps, {oldapp: {status: "park", at: "2026-10-01"}}).map(x => x.project), ["never"]);
  assert.deepEqual(AT.dormant(ATD, TODAY, ps, {oldapp: {status: "archive", at: "2026-10-01"}, never: {status: "park"}}), []);
  assert.deepEqual(AT.dormant(ATD, TODAY, ps, {oldapp: {status: "continue", at: "2026-10-01"}}).map(x => x.project), ["never"]);   // the clock restarts
  assert.deepEqual(AT.dormant(ATD, TODAY, ps, {}, {dormantDays: 30}).map(x => x.project), []);                                   // configurable
  assert.deepEqual(AT.dormant({}, TODAY, ["a"]), []);                                // no data at all: nothing to say
  assert.deepEqual(AT.dormant({a: {"2026-10-05": {commits: 0}}, b: {"2026-09-01": {commits: 8}}}, TODAY, ["a"]).map(x => x.project), ["a"]);   // only a trivial day: never meaningful, and the data is old enough
});
T("attention: intent against observed, with optional shares and a clear verdict", () => {
  assert.deepEqual(AT.intentTargets({projects: [{name: "a"}, {name: "b"}]}).map(x => x.target), [0.5, 0.5]);
  assert.deepEqual(AT.intentTargets({projects: [{name: "a", share: 0.6}, {name: "b"}]}).map(x => Math.round(x.target * 100)), [60, 40]);
  assert.equal(AT.intentTargets({projects: "x"}).length, 0); assert.equal(AT.intentTargets({projects: [1, 2, 3, 4, 5].map(i => ({name: "p" + i}))}).length, 4);
  const intent = {projects: [{name: "quarterdeck", share: 0.5}, {name: "oldapp", share: 0.5}], from: "2026-10-05", to: "2026-10-11"};
  const f = AT.focusVsReality(intent, ATD, TODAY);
  assert.equal(f.days, 2);
  assert.equal(f.rows.find(r => r.project === "quarterdeck").verdict, "over"); assert.equal(f.rows.find(r => r.project === "oldapp").verdict, "missing");
  assert.equal(f.elsewhere.project, "saltpan-blog");
  assert.equal(AT.focusVsReality({projects: [{name: "a"}], from: "2026-10-05", to: "2026-10-11"}, {}, TODAY).rows[0].verdict, "no data");
  assert.equal(AT.focusVsReality({projects: []}, ATD, TODAY), null);
  assert.equal(AT.currentIntent([{from: "2026-09-28", to: "2026-10-04", n: 1}, {from: "2026-10-05", to: "2026-10-11", n: 2}], TODAY).n, 2);
  assert.equal(AT.currentIntent([{from: "2026-09-28", to: "2026-10-04"}], TODAY), null); assert.equal(AT.currentIntent(null, TODAY), null);
  assert.equal(AT.mondayOf("2026-10-11"), "2026-10-05"); assert.equal(AT.mondayOf("2026-10-05"), "2026-10-05");
});
T("attention: hostile or odd data does not break the metrics", () => {
  const bad = {x: {"not-a-day": {commits: 8}, "2026-10-05": {commits: "9", commits: -4, prs: NaN}}, y: null, z: {"2026-10-05": null}};
  assert.deepEqual(AT.share(bad, TODAY), []); assert.deepEqual(AT.emerging(bad, TODAY), []); assert.deepEqual(AT.dormant(bad, TODAY, ["x", "y", "z"]), []);
  assert.deepEqual(AT.sizeWeights(ATD, TODAY), {quarterdeck: 1, "saltpan-blog": AT.totals(ATD, TODAY)["saltpan-blog"] / AT.totals(ATD, TODAY).quarterdeck, tiny: AT.totals(ATD, TODAY).tiny / AT.totals(ATD, TODAY).quarterdeck});
});

T("attention: Helm reads the focus freely, setting it asks for a click, and a model can never set it", () => {
  const c2 = {...ctx, projects: ["quarterdeck", "saltpan-blog", "wayfarer-api", "harvest-pipeline"]}, q = t => parseCommand(t, c2);
  assert.deepEqual(q("what is my focus this week"), {intent: "focus"}); assert.deepEqual(q("Hey Helm, what am I focused on"), {intent: "focus"}); assert.deepEqual(q("my focus"), {intent: "focus"});
  assert.deepEqual(q("set my focus to Quarterdeck and Saltpan blog"), {intent: "focusset", projects: ["quarterdeck", "saltpan-blog"], unknown: [], week: "this", confirm: true});
  assert.deepEqual(q("set my focus to wayfarer api, quarterdeck and harvest-pipeline next week"), {intent: "focusset", projects: ["wayfarer-api", "quarterdeck", "harvest-pipeline"], unknown: [], week: "next", confirm: true});
  assert.deepEqual(q("focus on quarterdeck and the garden"), {intent: "focusset", projects: ["quarterdeck"], unknown: ["the garden"], week: "this", confirm: true});
  assert.equal(actionAccepted({intent: "focus"}), true); assert.equal(actionAccepted({intent: "focusset", confirm: true}), false);
  assert.equal(ACTION_INTENTS.has("focusset"), false);
});

T("attention suggestions: dormant with an open PR, a Monday focus check, and emerging; calm, once, open-only, and silent without data", () => {
  const prs = [{project: "oldapp", number: 12, title: "Add courts", url: "https://github.com/x/oldapp/pull/12", checks: {}}];
  const A = (today, extra = {}) => ({days: ATD, today, projects: ["quarterdeck", "saltpan-blog", "oldapp"], statuses: {}, intents: [], ...extra});
  const kinds = (today, extra, p = prs) => detect(null, {S: {}, prs: p, attention: A(today, extra)}, Date.parse(today + "T09:00:00Z")).map(e => e.kind);
  assert.deepEqual(detect(null, {S: {}, prs}, now), []); assert.deepEqual(detect(null, {S: {}, prs, attention: {days: {}}}, now), []);   // no data: nothing
  const d = detect(null, {S: {}, prs, attention: A("2026-10-06")}, now).find(e => e.kind === "dormant-pr");
  assert.equal(d.action.type, "url"); assert.ok(d.action.url.startsWith("https://")); assert.equal(d.live, false); assert.match(d.title, /oldapp has gone quiet/);
  assert.equal(kinds("2026-10-06", {}, []).includes("dormant-pr"), false);                                              // no open PR: no suggestion
  assert.equal(kinds("2026-10-06", {statuses: {oldapp: {status: "park", at: "2026-10-01"}}}).includes("dormant-pr"), false);   // parked: left alone
  const mon = detect(null, {S: {}, prs: [], attention: A("2026-10-05")}, now).filter(e => e.kind === "focus-check");
  assert.equal(mon.length, 1); assert.equal(mon[0].action.type, "focus"); assert.equal(mon[0].id, "focus-set:2026-10-05");
  assert.equal(kinds("2026-10-06", {}, []).includes("focus-check"), false);                                              // only on Mondays
  assert.equal(kinds("2026-10-05", {intents: [{from: "2026-10-05", to: "2026-10-11", projects: [{name: "quarterdeck"}]}]}, []).includes("focus-check"), false);   // focus already set
  const em = detect(null, {S: {}, prs: [], attention: A("2026-10-06")}, now).find(e => e.kind === "emerging");
  assert.equal(em.id, "emerging:quarterdeck:2026-10-05"); assert.equal(em.action.type, "attention"); assert.equal(em.live, false); assert.match(em.why, /estimate/i);
  assert.equal(kinds("2026-10-10", {}, []).includes("emerging"), false);                                                // never on a weekend
  const lastw = detect(null, {S: {}, prs: [], attention: A("2026-10-05", {intents: [{from: "2026-09-28", to: "2026-10-04", projects: [{name: "saltpan-blog", share: 0.8}, {name: "quarterdeck", share: 0.2}]}]})}, now).filter(e => e.id === "focus-last:2026-10-05");
  assert.equal(lastw.length, 1); assert.match(lastw[0].title, /saltpan-blog got less than you meant/); assert.equal(lastw[0].action.type, "attention");
  for (const e of detect(null, {S: {}, prs, attention: A("2026-10-06")}, now)) assert.ok(["url", "go", "attention", "focus"].includes((e.action || {type: "url"}).type));
});

T("attention: Helm answers which projects are dormant, what is emerging and how was my week, and parking asks for a click", () => {
  const c2 = {...ctx, projects: ["quarterdeck", "saltpan-blog", "wayfarer-api", "oldapp"]}, q = t => parseCommand(t, c2);
  for (const [t, i] of [["which projects are dormant", "dormant"], ["Hey Helm, what has gone quiet", "dormant"], ["what is emerging", "emerging"], ["what's picking up", "emerging"], ["how was my week", "week"], ["where did my time go", "week"]]) {
    assert.deepEqual(q(t), {intent: i}, t); assert.equal(actionAccepted(q(t)), true, t);
  }
  assert.deepEqual(q("park wayfarer api"), {intent: "parkproject", status: "park", project: "wayfarer-api", confirm: true});
  assert.deepEqual(q("archive the oldapp"), {intent: "parkproject", status: "archive", project: "oldapp", confirm: true});
  assert.deepEqual(q("continue with quarterdeck"), {intent: "parkproject", status: "continue", project: "quarterdeck", confirm: true});
  assert.notEqual(q("park the car").intent, "parkproject"); assert.equal(actionAccepted(q("park wayfarer api")), false);   // a model may read, never park
  const ps = ["quarterdeck", "saltpan-blog", "oldapp", "never"];
  assert.match(AT.dormantText(AT.dormant(ATD, TODAY, ps)), /^2 projects have gone quiet: oldapp, quiet for \d+ working days and never, with no activity recorded\. Say, park oldapp, .*estimate/);
  assert.match(AT.dormantText([]), /Nothing has gone quiet/); assert.match(AT.emergingText([]), /Nothing is clearly picking up/);
  assert.equal(AT.emergingText(AT.emerging(ATD, TODAY)), "quarterdeck is up about twice compared with last week. That is an estimate.");
  const w = AT.weekText(ATD, TODAY, null);
  assert.match(w, /as an estimate: about two thirds was quarterdeck/); assert.match(w, /active on \d of 7 days/); assert.match(w, /5 timed meetings/);
  assert.ok(!/\d+(\.\d+)?%/.test(w), "no percentages");
  assert.match(AT.weekText({}, TODAY, null), /Not enough is recorded/);
});

T("attention replay: the days on offer, the weights as of a day, and that day's Ledger events", () => {
  const r = AT.replayRange(ATD, TODAY, 60);
  assert.equal(r[0], "2026-09-10"); assert.equal(r.at(-1), TODAY); assert.equal(r.length, 27);                      // first recorded day to today, nothing invented
  assert.equal(AT.replayRange(ATD, TODAY, 5)[0], "2026-10-02"); assert.deepEqual(AT.replayRange({}, TODAY), []);
  const w = AT.dayWeights(ATD, "2026-09-10");
  assert.deepEqual(w, {oldapp: 1});                                                                                    // that day only oldapp had work
  assert.equal(AT.dayWeights(ATD, TODAY).quarterdeck, 1); assert.equal("oldapp" in AT.dayWeights(ATD, TODAY), false);
  const runs = [{at: "2026-10-05T14:00:00Z", project: "a", duty: "surveyor", verdict: "CLEAN", detail: "x".repeat(300)}, {at: "2026-10-05T08:00:00Z", project: "b", duty: "trials", verdict: "PROVEN"}, {at: "2026-10-04T08:00:00Z", project: "c", duty: "x", verdict: "PR"}, null];
  const d = AT.dayRuns(runs, "2026-10-05");
  assert.deepEqual(d.map(x => x.project), ["b", "a"]); assert.equal(d[1].detail.length, 160); assert.deepEqual(AT.dayRuns(runs, "2026-01-01"), []); assert.deepEqual(AT.dayRuns(null, TODAY), []);
});

// ---- My rhythm: a concept preview from invented data (rhythm.js is pure) ----
const rt = (day, hm, kind, project) => ({t: `${day}T${hm}`, kind, project});
const RD = {today: "2026-10-07", events: [
  ...["9:00", "9:15", "9:30", "9:45", "10:00", "10:15", "10:30"].map((h, i) => rt("2026-10-05", h.padStart(5, "0"), "commit", ["p1", "p1", "p1", "p2", "p2", "p1", "p1"][i])),
  rt("2026-10-05", "14:00", "note", "p2"), rt("2026-10-05", "14:10", "run", "p2"),
  ...["09:00", "09:10", "09:20"].map(h => rt("2026-10-06", h, "commit", "p1")),
  ...["09:00", "09:15", "09:30", "09:45", "10:00"].map(h => rt("2026-10-07", h, "pr", "p1"))],
  meetings: [{day: "2026-10-05", from: "11:00", to: "12:00"}, {day: "2026-10-06", from: "13:00", to: "14:00"}, {day: "2026-10-06", from: "14:30", to: "15:30"}]};
T("rhythm: focus blocks, the day strip and the heatmap are worked out from five kinds of invented signal", () => {
  assert.deepEqual(RH.blocks(RD, "2026-10-05"), [{from: 540, to: 635, mins: 95, n: 7, projects: 2}]);                 // the short afternoon burst is not a block
  assert.equal(RH.blocks(RD, "2026-10-06").length, 0);                                                                  // 25 minutes is under the 30 minute minimum
  const split = {events: [rt("2026-10-05", "10:00", "commit", "a"), rt("2026-10-05", "10:15", "commit", "a")], meetings: [{day: "2026-10-05", from: "10:05", to: "10:10"}]};
  assert.equal(RH.blocks(split, "2026-10-05").length, 0);                                                               // a meeting between two actions ends a block
  const st = RH.dayStrip(RD, "2026-10-05");
  assert.deepEqual(st.segments.map(x => [x.type, x.from, x.to]), [["focus", 540, 635], ["gap", 635, 660], ["meeting", 660, 720], ["gap", 720, 900]]);
  assert.equal(st.total, 360); assert.equal(RH.dayStrip(RD, "2026-01-01").segments.length, 0);
  const h = RH.heatmap(RD, "2026-10-07");
  assert.equal(h.days.length, 35); assert.equal(h.days.at(-1), "2026-10-07"); assert.equal(h.hours.length, 17);
  const c = h.days.indexOf("2026-10-05"), r9 = h.hours.indexOf(9), r10 = h.hours.indexOf(10);
  assert.equal(h.counts[r9][c], 4); assert.equal(h.levels[r9][c], 3); assert.equal(h.counts[r10][c], 3); assert.equal(h.levels[r10][c], 2);
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 9].map(RH.levelOf), [0, 1, 2, 2, 3, 3, 4, 4]);
  assert.equal(h.total, 17);
});
T("rhythm: switches against the usual, the longest block, the streak and the meeting load", () => {
  assert.equal(RH.switches(RD, "2026-10-05"), 3); assert.equal(RH.switches(RD, "2026-10-06"), 0);
  assert.equal(RH.usualSwitches(RD, "2026-10-06"), 3); assert.equal(RH.usualSwitches(RD, "2026-10-05"), null);
  assert.equal(RH.switchNote(0, 2), "0 switches today, your usual is 2."); assert.equal(RH.switchNote(1, 5), "1 switch today, your usual is 5."); assert.match(RH.switchNote(3, null), /no earlier day/);
  assert.deepEqual(RH.longestBlock(RD, "2026-10-07"), {mins: 95, day: "2026-10-05", from: 540, to: 635});
  assert.equal(RH.streak(RD, "2026-10-05", "2026-10-07"), 1); assert.equal(RH.streak(RD, "2026-10-07", "2026-10-07"), 0);
  assert.equal(RH.streak({events: [], meetings: []}, "2026-10-07", "2026-10-07"), 0);
  const long = (d) => ["09:00", "09:15", "09:30", "09:45", "10:00", "10:15", "10:30"].map(h => rt(d, h, "commit", "a"));
  const sk = {events: ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"].flatMap(long), meetings: []};
  assert.equal(RH.streak(sk, "2026-10-06", "2026-10-06"), 4); assert.equal(RH.streak(sk, "2026-10-04", "2026-10-06"), 2);   // the weekend neither counts nor breaks it
  const ml = RH.meetingLoad(RD, "2026-10-07");
  assert.equal(ml.mins, 180); assert.equal(ml.word, "3 h more than last week"); assert.equal(RH.meetingLoad({events: [], meetings: [{day: "2026-10-06", from: "9:00", to: "9:10"}]}, "2026-10-07").word, "about the same as last week");
  assert.equal(RH.hoursText(95), "1 h 35 min"); assert.equal(RH.hoursText(60), "1 h"); assert.equal(RH.hoursText(0), "0 min");
});
T("rhythm: three quiet observations that only say what happened, a week picker, and odd data ignored", () => {
  const o = RH.observations(RD, "2026-10-07");
  assert.deepEqual(o, ["Tuesday had the most meetings.", "Tuesday was the quietest working day.", "Your longest block ran 1 h 35 min on Monday."]);
  assert.match(RH.observations({events: [], meetings: []}, "2026-10-07")[0], /not enough/);
  const BAD = /\b(should|try|consider|must|need to|you could|make sure|avoid|please|tip)\b/i;
  const FORBIDDEN = /\b(apps?|websites?|typing|typed|keystrokes?|idle|screens?|screenshots?|clipboard|location|browser|tabs?|where you were|mouse)\b/i;
  const all = [...o, ...Object.values(RH.EXPLAIN), RH.BADGE, RH.switchNote(2, 5), RH.meetingLoad(RD, "2026-10-07").word];
  for (const t of all) { assert.ok(!BAD.test(t), t); assert.ok(!FORBIDDEN.test(t), t); assert.ok(!/[\u2014\u2013]/.test(t), t); }
  assert.equal(RH.BADGE, "Concept preview: invented data, nothing is collected");
  for (const k of ["heat", "block", "longest", "streak", "meetings", "switches", "strip", "observation"]) assert.ok(RH.EXPLAIN[k] && /invented/.test(RH.EXPLAIN[k]), k);
  const w = RH.weeks(RD, "2026-10-07");
  assert.deepEqual(w.map(x => [x.end, x.current, x.label]), [["2026-10-07", true, "Last 7 days"]]);
  const wide = {events: [rt("2026-08-10", "09:00", "commit", "a"), rt("2026-10-07", "09:00", "commit", "a")], meetings: []};
  const ws = RH.weeks(wide, "2026-10-07");
  assert.equal(ws.length, 9); assert.equal(ws.at(-1).label, "Last 7 days"); assert.match(ws[0].label, / to /);
  const odd = {events: [null, {t: 5}, {t: "x", kind: "commit"}, {t: "2026-10-07T09:00", kind: "screen"}, {t: "2026-10-07Tzz", kind: "commit"}, {t: "2026-10-07T09:00", kind: "commit", project: "a"}], meetings: [null, {day: "2026-10-07", from: "x", to: "y"}, {day: "2026-10-07", from: "10:00", to: "09:00"}]};
  assert.equal(RH.eventsOf(odd, "2026-10-07").length, 1); assert.equal(RH.meetingsOf(odd, "2026-10-07").length, 0); assert.equal(RH.heatmap(odd, "2026-10-07").total, 1);
  assert.equal(RH.heatmap(undefined, "2026-10-07").total, 0); assert.deepEqual(RH.weeks(undefined, "2026-10-07").length, 1);
});

// ---- My rhythm on real data: the real rules, counts of calendar blocks, a minimum volume and honest wording ----
const REAL = {concept: false, today: "2026-10-07", rules: {gap: 44, minBlock: 20, tail: 5, switchKinds: ["commit"], minEvents: 15, minDays: 3}, badge: "Estimated from your commits, branches, notes and calendar. It cannot see reading, thinking or other work.",
  events: [], meetings: []};
const rev = (day, hm, kind, project) => REAL.events.push({t: `${day}T${hm}`, kind, project});
T("rhythm (real): a focus block is a run with gaps under 45 minutes lasting at least 20, and a single event is not a block", () => {
  const D = {...REAL, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:40", "note", "a"), rt("2026-10-05", "10:20", "commit", "a"), rt("2026-10-05", "12:00", "commit", "a"), rt("2026-10-05", "15:30", "pr", "a"), rt("2026-10-05", "16:00", "commit", "b"), rt("2026-10-05", "16:30", "commit", "a")]};
  assert.deepEqual(RH.blocks(D, "2026-10-05"), [{from: 540, to: 625, mins: 85, n: 3, projects: 1}, {from: 930, to: 995, mins: 65, n: 3, projects: 2}]);     // gaps of 40 join, 100 does not; the lone event at 12:00 is no block
  assert.equal(RH.blocks({...D, events: [rt("2026-10-05", "09:00", "commit", "a")]}, "2026-10-05").length, 0);
  assert.equal(RH.blocks({...D, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:10", "commit", "a")]}, "2026-10-05").length, 0);   // 15 minutes is under the 20 minute minimum
  assert.equal(RH.blocks({...D, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:44", "commit", "a")]}, "2026-10-05").length, 1);       // 44 minutes still joins
  assert.equal(RH.blocks({...D, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:45", "commit", "a")]}, "2026-10-05").length, 0);       // 45 does not
  const split = {...D, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:30", "commit", "a")], meetings: [{day: "2026-10-05", from: "09:15", to: null}]};
  assert.equal(RH.blocks(split, "2026-10-05").length, 0);                                                          // a meeting that starts between two events ends the block
  assert.equal(RH.blocks({...split, meetings: []}, "2026-10-05").length, 1);
  assert.equal(RH.blocks(RD, "2026-10-05").length, 1); assert.equal(RH.rulesOf(RD).gap, 20);                          // the demo keeps its own rules
});
T("rhythm (real): project switches count commits only, meetings are blocks without lengths, and a thin week says not enough yet", () => {
  const D = {...REAL, events: [rt("2026-10-05", "09:00", "commit", "a"), rt("2026-10-05", "09:10", "note", "b"), rt("2026-10-05", "09:20", "commit", "b"), rt("2026-10-05", "09:30", "pr", "c"), rt("2026-10-05", "09:40", "commit", "a")]};
  assert.equal(RH.switches(D, "2026-10-05"), 2);                                                                      // a to b, b to a: the note and the pull request are not commits
  assert.equal(RH.switches({...D, rules: undefined}, "2026-10-05"), 3);                                              // the demo counts every action
  const M = {...REAL, meetings: [{day: "2026-10-06", from: "10:00", to: null}, {day: "2026-10-06", from: "14:00", to: null}, {day: "2026-09-30", from: "11:00", to: null}]};
  const ml = RH.meetingLoad(M, "2026-10-07");
  assert.deepEqual([ml.mins, ml.count, ml.prevCount, ml.word], [null, 2, 1, "1 more than last week"]);
  assert.equal(RH.meetingLoad({...M, meetings: []}, "2026-10-07").word, "about the same as last week");
  assert.deepEqual(RH.dayStrip({...M, events: [rt("2026-10-06", "09:00", "commit", "a"), rt("2026-10-06", "09:30", "commit", "a")]}, "2026-10-06").meetingStarts, [600, 840]);
  assert.match(RH.observations(D, "2026-10-07")[0], /not enough/);                                                    // five events on one day: no pattern is claimed
  assert.equal(RH.enough(D, "2026-10-07"), false); assert.equal(RH.enough(RD, "2026-10-07"), true);
  const many = {...REAL, events: ["2026-10-05", "2026-10-06", "2026-10-07"].flatMap(d => ["09:00", "09:15", "09:30", "09:45", "10:00", "10:20"].map(h => rt(d, h, "commit", "a")))};
  assert.equal(RH.enough(many, "2026-10-07"), true); assert.ok(!/not enough/.test(RH.observations(many, "2026-10-07")[0]));
});
T("rhythm (real): every explanation says the rules in plain words, says what it cannot see, and uses no forbidden or instructing words", () => {
  const E = RH.explainFor(REAL), keys = ["heat", "block", "longest", "streak", "meetings", "switches", "strip", "observation"];
  for (const k of keys) { assert.ok(E[k], k); assert.match(E[k], /cannot see reading, thinking or other work/, k); assert.ok(!/invented/.test(E[k]), k); }
  assert.match(E.heat, /commit of yours in a registered project, a note you added in Quarterdeck, a pull request you opened, or an agent run you started by hand/); assert.match(E.heat, /Commits that agents made under your name are left out/);
  assert.match(E.block, /less than 45 minutes/); assert.match(E.block, /at least 20 minutes/); assert.match(E.block, /single event is not a block/); assert.match(E.block, /Only the hour of each event is kept/);
  assert.match(E.switches, /two commits in a row/); assert.match(E.meetings, /count of blocks/); assert.match(E.meetings, /not how long it lasts/); assert.match(E.observation, /at least 15 events on 3 days/);
  assert.match(RH.explainFor(RD).heat, /invented/); assert.equal(RH.explainFor(null).block, RH.EXPLAIN.block);
  const BAD = /\b(should|try|consider|must|need to|you could|make sure|avoid|please)\b/i, FORBIDDEN = /\b(apps?|websites?|typing|typed|keystrokes?|idle|screens?|screenshots?|clipboard|location|browser|tabs?|where you were|mouse)\b/i;
  for (const t of [...Object.values(E), REAL.badge, ...RH.observations(RD, "2026-10-07")]) { assert.ok(!BAD.test(t), t); assert.ok(!FORBIDDEN.test(t), t); assert.ok(!/[\u2014\u2013]/.test(t), t); }
});

// ---- My rhythm: the task timeline (what was worked on, and when) ----
const te = (t, kind, project, label, branch) => ({t, kind, project, label, ...(branch ? {branch} : {})});
const TD = {today: "2026-10-06", tasks: {on: true, events: [
  te("2026-10-04T16:00", "branch", "saltpan-blog", "recipe index", "feat/recipe-index"),
  te("2026-10-05T08:55", "branch", "quarterdeck", "focus voice", "feat/focus-voice"),
  te("2026-10-05T09:10", "commit", "quarterdeck", "Add the focus rule"), te("2026-10-05T09:40", "commit", "quarterdeck", "Fix the gap rule"), te("2026-10-05T11:00", "commit", "quarterdeck", "Late fix"),
  te("2026-10-05T09:30", "note", "harvest-pipeline", "Call Priya about the freeze"), te("2026-10-05T10:00", "pr", "oldapp", "Add courts page"),
  te("2026-10-05T13:00", "run", "saltpan-blog", "surveyor, PR #12"), te("2026-10-05T14:00", "meeting", "", "Planning sync"), te("2026-10-05T15:00", "commit", "empty", "")]}};
T("rhythm tasks: neighbouring events of one project make a block named by its latest commit, else the branch, else a pull request, run or note; never invented", () => {
  const b = RH.taskBlocks(TD, "2026-10-05");
  const by = n => b.filter(x => x.project === n);
  assert.deepEqual(by("quarterdeck").map(x => [x.from, x.to, x.mins, x.label, x.source]), [[535, 585, 50, "Fix the gap rule", "commit"], [660, 665, 5, "Late fix", "commit"]]);         // the checkout at 8:55 starts the block; 100 minutes later is another block
  assert.deepEqual([by("quarterdeck")[0].evidence[0].kind, by("quarterdeck")[0].evidence[0].label, by("quarterdeck")[0].evidence[0].outside], ["branch", "focus voice", false]); assert.equal(by("saltpan-blog")[0].evidence[0].outside, true);   // the branch he was on is shown as evidence, even from the day before
  assert.deepEqual(by("harvest-pipeline").map(x => [x.label, x.source]), [["Call Priya about the freeze", "note"]]);
  assert.deepEqual(by("oldapp").map(x => [x.label, x.source]), [["Add courts page", "pr"]]);
  assert.deepEqual(by("saltpan-blog").map(x => [x.label, x.source]), [["recipe index", "branch"]]);                                                                       // a branch from the day before names a stretch with no commit
  assert.deepEqual(by("empty").map(x => [x.label, x.source]), [["Unlabelled", "none"]]);                                                                             // there is nothing to say, so nothing is made up
  assert.deepEqual(b.filter(x => x.kind === "meeting").map(x => [x.from, x.to, x.label]), [[840, null, "Planning sync"]]);
  assert.deepEqual(b.map(x => x.from), [...b.map(x => x.from)].sort((p, q) => p - q));
  assert.deepEqual(RH.blocks({...TD, events: []}, "2026-10-05"), []);                                                                                                 // the counts side is untouched
  assert.equal(RH.taskBlocks({today: "x"}, "2026-10-05").length, 0); assert.equal(RH.taskBlocks({tasks: {on: false, events: TD.tasks.events}}, "2026-10-05").length, 0);
  assert.equal(RH.taskBlocks({tasks: {on: true, events: [null, {t: "x"}, {t: "2026-10-05T09:00", kind: "keys", label: "a"}, {t: "2026-10-05T09:00", kind: "note"}]}}, "2026-10-05").length, 0);
});
T("rhythm tasks: the per project summary, the lines, and the three Helm questions answered from the same blocks", () => {
  const b = RH.taskBlocks(TD, "2026-10-05"), sm = RH.projectSummary(b);
  assert.equal(RH.summaryLine(sm[0]), "quarterdeck 55 min across 2 blocks"); assert.equal(RH.summaryLine({project: "p", mins: 190, blocks: 1}), "p 3 h 10 min across 1 block");
  assert.equal(RH.blockLine(b.find(x => x.label === "Fix the gap rule")), "8:55 to 9:45 quarterdeck, Fix the gap rule"); assert.equal(RH.blockLine(b.find(x => x.kind === "meeting")), "14:00 meeting, Planning sync");
  assert.equal(RH.workedText(TD, "2026-10-05", "morning", "2026-10-05"), "This morning: 8:55 to 9:45 quarterdeck, Fix the gap rule. 9:30 to 9:35 harvest-pipeline, Call Priya about the freeze. 10:00 to 10:05 oldapp, Add courts page. 11:00 to 11:05 quarterdeck, Late fix. That is an estimate from commits, branches, notes and the calendar.");
  assert.match(RH.workedText(TD, "2026-10-05", "afternoon", "2026-10-06"), /^Yesterday afternoon: 13:00 to 13:05 saltpan-blog, recipe index\. 14:00 meeting, Planning sync\. 15:00 to 15:05 empty, Unlabelled\./);
  assert.match(RH.workedText(TD, "2026-10-05", "evening", "2026-10-05"), /^Nothing is recorded for this evening\./);
  assert.match(RH.workedText({...TD, tasks: {on: false}}, "2026-10-05", null, "2026-10-05"), /switched off/);
  assert.equal(RH.lastTouched(TD, "saltpan-blog", "2026-10-06"), "You last touched saltpan-blog yesterday at 13:00: surveyor, PR #12. That is an estimate from commits, branches, notes and the calendar.");
  assert.match(RH.lastTouched(TD, "ghost", "2026-10-06"), /nothing recorded for ghost/); assert.match(RH.lastTouched({today: "x"}, "quarterdeck", "2026-10-06"), /switched off/);
  const E = RH.explainFor({concept: false, rules: {}, tasks: {on: true, events: []}}).tasks;
  assert.match(E, /less than 45 minutes apart/); assert.match(E, /first line of the message only/); assert.match(E, /never sent to any model/); assert.match(E, /rm -f state\/rhythm-tasks.json/); assert.match(RH.explainFor(null).tasks, /invented/);
});

T("rhythm tasks: Helm understands the three questions, and a model cannot suggest them", () => {
  const c2 = {...ctx, projects: ["quarterdeck", "saltpan-blog", "wayfarer-api"]}, q = t => parseCommand(t, c2);
  assert.deepEqual(q("what was I working on this morning"), {intent: "worked", day: "today", part: "morning"});
  assert.deepEqual(q("Hey Helm, what did I do yesterday afternoon"), {intent: "worked", day: "yesterday", part: "afternoon"});
  assert.deepEqual(q("what have I been working on"), {intent: "worked", day: "today", part: null});
  assert.deepEqual(q("what did I do yesterday"), {intent: "worked", day: "yesterday", part: null});
  assert.deepEqual(q("when did I last touch Saltpan blog"), {intent: "lasttouch", project: "saltpan-blog", query: "saltpan blog"});
  assert.deepEqual(q("when did I last work on wayfarer api"), {intent: "lasttouch", project: "wayfarer-api", query: "wayfarer api"});
  assert.equal(q("when did I last touch the garden").project, null);
  assert.equal(actionAccepted({intent: "worked"}), false); assert.equal(actionAccepted({intent: "lasttouch"}), false);
  assert.equal(ACTION_INTENTS.has("worked"), false); assert.equal(ACTION_INTENTS.has("lasttouch"), false);
});

// ---- The Helm dock: layout rules and the orb's states (pure) ----
T("dock: wide screens dock, narrower ones start as a rail, a phone gets a sheet, and the owner's choice is remembered", () => {
  assert.equal(DK.layoutMode(1440, null), "dock"); assert.equal(DK.layoutMode(1100, null), "dock"); assert.equal(DK.layoutMode(1099, null), "rail"); assert.equal(DK.layoutMode(901, null), "rail");
  assert.equal(DK.layoutMode(1440, "rail"), "rail"); assert.equal(DK.layoutMode(900, "dock"), "dock"); assert.equal(DK.layoutMode(1440, "junk"), "dock");
  assert.equal(DK.layoutMode(420, "dock"), "sheet"); assert.equal(DK.layoutMode(700, null), "sheet"); assert.equal(DK.layoutMode(701, null), "rail"); assert.equal(DK.layoutMode(0, null), "dock");
  assert.deepEqual(["dock", "rail", "sheet"].map(DK.reservedWidth), [380, 76, 0]);                                  // the page always leaves exactly this much free, so nothing is covered
  assert.equal(DK.toggledChoice("dock"), "rail"); assert.equal(DK.toggledChoice("rail"), "dock");
});
T("dock: the orb shows idle, listening, hearing you, thinking and speaking, from Helm's own state and level, and holds still for reduced motion", () => {
  const v = (o) => DK.orbVisual(o);
  assert.deepEqual([v({state: "idle"}).mode, v({state: "idle"}).word, v({state: "idle"}).hint], ["idle", "Idle", "Press to talk"]);
  assert.equal(v({state: "idle", handsFree: true}).word, "Listening for Helm");
  assert.deepEqual([v({state: "listening", level: 0}).mode, v({state: "listening", level: 0.005}).mode, v({state: "listening", level: 0.03}).mode], ["listening", "listening", "hearing"]);
  assert.equal(v({state: "listening", level: 0.03}).word, "Hearing you");
  assert.equal(v({state: "thinking", level: 0.5}).mode, "thinking"); assert.equal(v({state: "speaking"}).word, "Speaking"); assert.equal(v({state: "weird"}).mode, "idle");
  assert.ok(v({state: "speaking", level: 0.1}).scale > 0 && v({state: "speaking", level: 5}).scale === 1 && v({state: "speaking", level: -1}).scale === 0 && v({state: "speaking", level: NaN}).scale === 0);
  const still = v({state: "speaking", level: 0.5, reduced: true}); assert.deepEqual([still.animate, still.scale, still.mode], [false, 0, "speaking"]);       // the same state, a still picture
  assert.equal(v({state: "listening", level: 0.5}).animate, true);
});
T("dock: Cmd or Ctrl J talks, Cmd or Ctrl Backslash collapses, and nothing else is a dock key", () => {
  assert.equal(DK.dockKey({key: "j", metaKey: true}), "talk"); assert.equal(DK.dockKey({key: "J", ctrlKey: true}), "talk"); assert.equal(DK.dockKey({key: "\\", ctrlKey: true}), "collapse");
  assert.equal(DK.dockKey({key: "j"}), null); assert.equal(DK.dockKey({key: "j", ctrlKey: true, shiftKey: true}), null); assert.equal(DK.dockKey({key: "j", ctrlKey: true, altKey: true}), null);
  assert.equal(DK.dockKey({key: "k", metaKey: true}), null); assert.equal(DK.dockKey(null), null); assert.equal(DK.dockKey({}), null);
});

// ---- card reading: the safe markdown renderer ----
// Every `<` in the output must start one of the few tags the renderer makes itself, with only the attributes it sets.
const OKTAGS = {a: ["href", "target", "rel"], span: ["class", "aria-label"], li: ["class"], div: ["class"], p: ["class"], code: [], pre: [], strong: [], em: [], s: [], br: [], hr: [], h2: [], h3: [], h4: [], h5: [], h6: [],
  ul: [], ol: [], blockquote: [], table: [], thead: [], tbody: [], tr: [], th: [], td: []};
function audit(html) {
  const left = html.replace(/<(\/?)([a-z0-9]+)((?:\s+[a-z-]+="[^"<>]*")*)\s*>/g, (all, close, tag, attrs) => {
    assert.ok(OKTAGS[tag], "tag " + tag);
    for (const m of attrs.matchAll(/([a-z-]+)="([^"]*)"/g)) {
      assert.ok(OKTAGS[tag].includes(m[1]), tag + " attribute " + m[1]);
      if (m[1] === "href") assert.match(m[2], /^(https?:\/\/|mailto:)/i);
      if (tag === "a" && m[1] === "target") assert.equal(m[2], "_blank");
      if (tag === "a" && m[1] === "rel") assert.equal(m[2], "noopener noreferrer");
    }
    if (tag === "a" && !close) assert.ok(/rel="noopener noreferrer"/.test(attrs) && /target="_blank"/.test(attrs));
    return "";
  });
  assert.ok(!/[<>]/.test(left), "stray angle bracket: " + left.slice(0, 80));
  assert.ok(!/<(script|img|iframe|object|embed|svg|style|link|meta|form|input|video|audio|base)/i.test(html));
  return html;
}
T("card reading: headings, lists, done and not done boxes, code, links and tables read as plain structure", () => {
  const h = audit(renderMarkdown("# Title\n\nSome **bold** and *soft* and `code` text with [a link](https://example.com/x?a=1&b=2).\n\n- [x] done item\n- [ ] open item\n  - nested\n\n1. one\n2. two\n\n```js\nconst a = 1 < 2;\n```\n\n| Name | Value |\n| --- | --- |\n| a | 1 |\n| b | 2 |\n"));
  assert.match(h, /<h2>Title<\/h2>/); assert.match(h, /<strong>bold<\/strong>/); assert.match(h, /<em>soft<\/em>/); assert.match(h, /<code>code<\/code>/);
  assert.match(h, /href="https:\/\/example\.com\/x\?a=1&amp;b=2"/); assert.match(h, /aria-label="done"/); assert.match(h, /aria-label="not done"/);
  assert.match(h, /<li>nested/); assert.match(h, /<ol><li>one<\/li><li>two<\/li><\/ol>/); assert.match(h, /<pre><code>const a = 1 &lt; 2;<\/code><\/pre>/);
  assert.match(audit(renderMarkdown("_soft_ and snake_case_name and 5 * 3 * 2")), /<em>soft<\/em> and snake_case_name and 5 \* 3 \* 2|<em>soft<\/em> and snake_case_name and 5 <em> 3 <\/em> 2/);
  assert.match(h, /<table>/); assert.equal((h.match(/<tr>/g) || []).length, 3); assert.match(h, /<th>Name<\/th>/); assert.match(h, /<td>2<\/td>/);
});
T("card reading: hostile bodies never run and never load anything", () => {
  const bad = [
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<a href=\"javascript:alert(1)\" onclick=\"x()\">hi</a>", "<svg onload=alert(1)>", "<iframe src=\"https://evil.example\"></iframe>",
    "[click](javascript:alert(1))", "[click](JaVaScRiPt:alert(1))", "[click](  javascript:alert(1))", "[click](java\tscript:alert(1))", "[click](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
    "[click](vbscript:msgbox(1))", "[x](//evil.example/x)", "[x](/relative)", "![pixel](https://evil.example/track.png)", "![x](javascript:alert(1))", "![x](data:image/svg+xml;base64,AAAA)",
    "<https://ok.example/a\" onmouseover=\"alert(1)>", "[x](https://ok.example/\"onmouseover=\"alert(1))", "https://ok.example/a\"onfocus=\"alert(1)", "`<script>`", "```\n<script>alert(1)</script>\n```",
    "<<script>script>alert(1)<</script>/script>", "<div><div><div><b onmouseover=x>deep</b></div></div></div>", "<style>*{background:url(https://evil.example/x)}</style>", "<form action=https://evil.example><input name=p></form>",
    "<!-- <script>alert(1)</script> -->", "<!--", "<!-- <!-- <!--", "&lt;script&gt;alert(1)&lt;/script&gt;", "| a |\n| - |\n| <script>x</script> |", "> <img src=x onerror=1>", "- <script>x</script>", "# <script>x</script>",
    "<a href=\"https://ok.example\" target=\"_self\">x</a>", "<meta http-equiv=refresh content=\"0;url=https://evil.example\">", "<base href=https://evil.example/>",
  ];
  for (const b of bad) {
    const h = audit(renderMarkdown(b));
    assert.ok(!/href="(?!https?:\/\/|mailto:)/i.test(h), b);
  }
  assert.match(renderMarkdown("![pixel](https://evil.example/track.png)"), /<a href="https:\/\/evil\.example\/track\.png"[^>]*>image: pixel<\/a>/);   // a plain link, nothing loads
  assert.ok(!/<a /.test(renderMarkdown("[click](javascript:alert(1))")) && /click/.test(renderMarkdown("[click](javascript:alert(1))")));
  assert.ok((renderMarkdown(">".repeat(4000) + " deep").match(/<blockquote>/g) || []).length <= 10, "quotes nest to a fixed depth, however many > come");
  assert.match(renderMarkdown("<script>alert(1)</script>"),/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.equal(safeUrl("javascript:alert(1)"), ""); assert.equal(safeUrl("data:text/html,x"), ""); assert.equal(safeUrl("https://a.example/x"), "https://a.example/x"); assert.equal(safeUrl("mailto:a@b.example"), "mailto:a@b.example"); assert.equal(safeUrl("https://a b"), ""); assert.equal(mdEsc(`<"'&\``), "&lt;&quot;&#39;&amp;&#96;");
});
T("card reading: very long lines and a 200 KB body are cut, finish quickly and stay safe", () => {
  const t0 = Date.now();
  for (const b of ["a".repeat(300000), "**".repeat(100000), "[".repeat(100000), "[a](".repeat(50000), "![".repeat(60000), "<".repeat(100000), "<!--".repeat(50000), "`".repeat(100000), "* ".repeat(100000), "| a ".repeat(50000) + "\n" + "| - ".repeat(50000), "> ".repeat(50000), "https://x.example/".repeat(10000), "_".repeat(200000), "- [x] ".repeat(30000), "\n".repeat(200000), ("- a\n" + "  ".repeat(50) + "- b\n").repeat(5000)]) {
    const h = audit(renderMarkdown(b)); assert.ok(h.length < 3000000);
  }
  const big = ("Line with a [link](https://example.com) and <b>tags</b> and `code` and **bold**.\n").repeat(Math.ceil(300000 / 80));
  const h = audit(renderMarkdown(big));
  assert.match(h, /longer than 200 KB/); assert.ok(MAX_CHARS === 200000);
  assert.ok(Date.now() - t0 < 8000, "took " + (Date.now() - t0) + " ms");
});
T("card reading: the purser's requirements are split off between its marks, and an edited block is left alone", () => {
  const body = "Intro\n\n<!-- quarterdeck:requirements -->\n## Requirements\n\n1. Cache it\n   - **Accept when:** works offline\n<!-- /quarterdeck:requirements -->\n\nTail";
  const s = splitRequirements(body);
  assert.equal(s.main, "Intro\n\n\n\nTail"); assert.match(s.requirements, /^## Requirements/); assert.match(s.requirements, /Accept when/);
  const one = "Intro\n<!-- quarterdeck:requirements -->\nonly the opening mark";
  assert.deepEqual(splitRequirements(one), {main: one, requirements: ""});
  assert.deepEqual(splitRequirements(""), {main: "", requirements: ""}); assert.deepEqual(splitRequirements(null), {main: "", requirements: ""});
  assert.ok(!/quarterdeck:requirements/.test(renderMarkdown(body)));
});
