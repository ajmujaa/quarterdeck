// Helper for bin/rehearse.py: runs the page's own fixed-phrase parser and answer builders over demo states
// handed in on stdin as {views, projects, duties, phrases, states: {second: state}}. Prints one JSON object.
import {parseCommand, runningLines, awayDigest, nextUp} from "../dashboard/assets/assistant.js";
import {feedPanel} from "../dashboard/assets/feeds.js";
import {detect} from "../dashboard/assets/suggest.js";
import * as AT from "../dashboard/assets/attention.js";
import * as RH from "../dashboard/assets/rhythm.js";
import fs from "node:fs";
const inp = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {phrases: {}, seconds: {}};
for (const t of inp.phrases) out.phrases[t] = parseCommand(t, {views: inp.views, projects: inp.projects, duties: inp.duties});
for (const [sec, S] of Object.entries(inp.states)) {
  const now = Date.parse(S.now), feed = n => { const c = S.connectors.find(x => x.name === n); const f = feedPanel(c, now); return f && {state: f.state, sub: f.sub}; };
  const d = awayDigest(S.runs, null, now);
  out.seconds[sec] = {running: runningLines(S.agents, now), digest: {total: d.total, failed: d.failed, prs: d.prs},
    next: nextUp({attention: S.inbox.filter(x => !x.acknowledged && !x.place).map(x => ({source: (x.project || "Local") + " · " + x.duty, text: x.text, view: "inbox", kind: x.severity})),
                  runs: S.runs, agents: S.agents, prs: S._prs, now}).title,
    feeds: {slack: feed("slack"), analytics: feed("analytics"), gmail: feed("gmail"), linkedin: feed("linkedin"), instagram: feed("instagram")}};
}
// What the Brain would suggest between two polls: {prev, cur} are second numbers (cur alone: the first look).
out.suggest = {};
for (const [a, b] of inp.pairs || []) {
  const snap = sec => ({S: inp.states[sec], prs: inp.states[sec]._prs});
  out.suggest[a + ">" + b] = detect(a === null ? null : snap(a), snap(b), Date.parse(inp.states[b].now)).map(e => ({kind: e.kind, sev: e.sev, title: e.title, action: e.action && e.action.type}));
}
// Where my attention goes, from the demo world's invented buckets (the same shape the real endpoint returns).
if (inp.attention) {
  const a = inp.attention, names = inp.projects, st = a.status || {}, S70 = inp.states[inp.attention_second];
  out.attention = {
    phrases: Object.fromEntries(["which projects are dormant", "what is emerging", "how was my week", "what is my focus this week", "park wayfarer mobile"].map(t => [t, parseCommand(t, {views: inp.views, projects: names, duties: inp.duties})])),
    dormant: AT.dormant(a.days, a.today, names, st).map(x => x.project), dormantText: AT.dormantText(AT.dormant(a.days, a.today, names, st)),
    emerging: AT.emerging(a.days, a.today).map(x => x.project), emergingText: AT.emergingText(AT.emerging(a.days, a.today)),
    week: AT.weekText(a.days, a.today, a.intent), home: AT.homeLine(a.days, a.today),
    focus: AT.focusVsReality(a.intent, a.days, a.today), sizes: AT.sizeWeights(a.days, a.today),
    parked: AT.dormant(a.days, a.today, names, {...st, "wayfarer-mobile": {status: "park", at: a.today}}).map(x => x.project),
    suggest: detect(null, {S: S70, prs: S70._prs, attention: {days: a.days, today: a.today, projects: names, statuses: st, intents: [a.intent]}}, Date.parse(S70.now)).filter(e => ["dormant-pr", "focus-check", "emerging"].includes(e.kind)).map(e => ({kind: e.kind, title: e.title, action: e.action && e.action.type, live: e.live})),
  };
}
// My rhythm (a concept preview): what the audience would see from the demo world's invented data.
if (inp.rhythm) {
  const d = inp.rhythm, end = d.today, st = RH.weekStats(d, end, d.today), ws = RH.weeks(d, d.today), obs = RH.observations(d, end);
  const strip = RH.dayStrip(d, end), heat = RH.heatmap(d, end), sw = RH.switches(d, end), us = RH.usualSwitches(d, end);
  out.rhythm = {weeks: ws.length, newest: ws.at(-1).label, kinds: [...new Set(d.events.map(e => e.kind))].sort(), longest: st.longest && st.longest.mins, streak: st.streak,
    meetings: st.meetings, obs, strip: strip.segments.map(x => x.type), heatTotal: heat.total, heatDays: heat.days.length, heatRows: heat.hours.length,
    note: RH.switchNote(sw, us), badge: d.badge, texts: [...obs, ...Object.values(RH.EXPLAIN), RH.BADGE, RH.switchNote(sw, us), st.meetings.word],
    older: ws.length > 1 ? RH.observations(d, ws[0].end) : [],
    tasks: (() => { const bl = RH.taskBlocks(d, end), sm = RH.projectSummary(bl);
      return {blocks: bl.length, work: bl.filter(b => b.kind === "work").length, meetings: bl.filter(b => b.kind === "meeting").map(b => b.label), sources: [...new Set(bl.map(b => b.source))].sort(),
        summary: sm.map(RH.summaryLine), labels: bl.map(b => b.label), evidence: bl.filter(b => b.kind === "work").every(b => b.evidence.length >= 1), projects: [...new Set(bl.filter(b => b.kind === "work").map(b => b.project))],
        morning: RH.workedText(d, end, "morning", end), yesterday: RH.workedText(d, RH.addDays(end, -1), "afternoon", end), last: RH.lastTouched(d, bl.find(b => b.kind === "work").project, end), explain: RH.explainFor(d).tasks, on: RH.tasksOn(d)}; })()};
}
// My rhythm on real-shaped data (a synthetic hour-bucket store run through the adapter) and the demo's wording, to prove the two stay apart.
if (inp.realRhythm) {
  const d = inp.realRhythm, end = d.today, ob = RH.observations(d, end), st = RH.weekStats(d, end, d.today), ex = RH.explainFor(d), dx = RH.explainFor(inp.rhythm);
  out.realRhythm = {enough: RH.enough(d, d.today), thin: RH.enough({...d, events: d.events.slice(0, 5)}, d.today), blocks: RH.blocks(d, end).length + RH.weekDays(end).reduce((a, x) => a + RH.blocks(d, x).length, 0),
    obs: ob, meetings: st.meetings, badge: d.badge, concept: d.concept, strip: RH.dayStrip(d, RH.weekDays(end).find(x => RH.meetingsOf(d, x).length) || end).meetingStarts,
    heat: ex.heat, demoHeat: dx.heat, demoBadge: inp.rhythm.badge, texts: [...Object.values(ex), ...Object.values(dx), ...ob]};
}
console.log(JSON.stringify(out));
