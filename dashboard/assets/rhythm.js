// "My rhythm": the pure logic behind a CONCEPT PREVIEW shown only in Demo mode, from invented data made by bin/demo.py.
// It works only from five invented kinds of signal: commits, pull requests, notes, calendar blocks and agent runs started
// by hand. Standing rule: Quarterdeck collects nothing beyond the registered projects and its own state/ (README, "Hard privacy limit"), and nothing
// here names or implies anything more. No DOM, no network, no clock: all of it is tested under node.
//
// data = {today: "YYYY-MM-DD", events: [{t: "YYYY-MM-DDTHH:MM", kind: "commit"|"pr"|"note"|"run", project}],
//         meetings: [{day: "YYYY-MM-DD", from: "HH:MM", to: "HH:MM"}]}

export const KINDS = ["commit", "pr", "note", "run"];
export const GAP = 20, TAIL = 5, FOCUS_MIN = 30, LONG = 90, HOURS = [6, 22], WEEKS_SHOWN = 5, WEEKS_BACK = 9;
// The rules of the demo's invented preview. Real data arrives with its own `rules` (see bin/attention/rhythm_feed.py): longer gaps, a shorter
// minimum block (`gap` is the longest pause, in minutes, that still belongs to the same block), switches counted between commits only, and a minimum volume before any pattern is claimed.
export const DEMO_RULES = {gap: GAP, minBlock: FOCUS_MIN, tail: TAIL, switchKinds: null, minEvents: 0, minDays: 0};
export const rulesOf = data => ({...DEMO_RULES, ...((data && data.rules) || {})});
export const isReal = data => !!data && data.concept === false;
export const DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const ms = d => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
export const addDays = (d, k) => new Date(ms(d) + k * 864e5).toISOString().slice(0, 10);
export const weekday = d => new Date(ms(d)).getUTCDay();
export const mondayOf = d => addDays(d, -((weekday(d) + 6) % 7));
export const isWeekday = d => { const w = weekday(d); return w >= 1 && w <= 5; };
export const dayName = d => DAY_NAMES[weekday(d)];
export const shortDate = d => `${+d.slice(8, 10)} ${MONTHS[+d.slice(5, 7) - 1]}`;
export const dayLabel = d => `${dayName(d).slice(0, 3)} ${shortDate(d)}`;
export const weekLabel = (w, e) => (w.slice(5, 7) === e.slice(5, 7) ? `${+w.slice(8, 10)} to ${shortDate(e)}` : `${shortDate(w)} to ${shortDate(e)}`);
const mins = hhmm => { const m = /^(\d{1,2}):(\d{2})/.exec(String(hhmm)); return m ? +m[1] * 60 + +m[2] : null; };
const hhmm = m => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;

export function hoursText(m) {
  m = Math.max(0, Math.round(+m || 0));
  const h = Math.floor(m / 60), r = m % 60;
  return h ? (r ? `${h} h ${r} min` : `${h} h`) : `${r} min`;
}

// ---- reading the data (anything odd is ignored) ----
export function eventsOf(data, day) {
  return ((data && data.events) || []).filter(e => e && KINDS.includes(e.kind) && typeof e.t === "string" && e.t.slice(0, 10) === day && mins(e.t.slice(11)) !== null)
    .map(e => ({m: mins(e.t.slice(11)), kind: e.kind, project: String(e.project || "")})).sort((a, b) => a.m - b.m);
}
// A calendar block with a start and an end, or (real data) only a start: the snapshot of the calendar has no lengths, so `to` is null.
export function meetingsOf(data, day) {
  return ((data && data.meetings) || []).filter(x => x && x.day === day).map(x => ({from: mins(x.from), to: x.to == null ? null : mins(x.to)}))
    .filter(x => x.from !== null && (x.to === null || (x.to !== undefined && x.to > x.from))).sort((a, b) => a.from - b.from);
}
export function firstDay(data) {
  let f = "";
  for (const e of (data && data.events) || []) { const d = e && typeof e.t === "string" ? e.t.slice(0, 10) : ""; if (DAY.test(d) && (!f || d < f)) f = d; }
  return f;
}

// ---- focus blocks: a run of actions with gaps under GAP minutes and no meeting in between ----
export function blocks(data, day) {
  const ev = eventsOf(data, day), ms_ = meetingsOf(data, day), out = [], R = rulesOf(data);
  let cur = null;
  for (const e of ev) {
    if (cur && e.m - cur.last <= R.gap && !ms_.some(x => x.from < e.m && (x.to ?? x.from) > cur.last)) { cur.last = e.m; cur.n++; cur.projects.add(e.project); }
    else { if (cur) out.push(cur); cur = {first: e.m, last: e.m, n: 1, projects: new Set([e.project])}; }
  }
  if (cur) out.push(cur);
  return out.map(b => ({from: b.first, to: b.last + R.tail, mins: b.last - b.first + R.tail, n: b.n, projects: b.projects.size}))
    .filter(b => b.mins >= R.minBlock);
}

// The day laid out left to right: focus blocks, meetings and everything else (gaps), from the first hour with anything to the last.
export function dayStrip(data, day) {
  const all0 = meetingsOf(data, day), bl = blocks(data, day).map(b => ({type: "focus", from: b.from, to: b.to})), mt = all0.filter(x => x.to !== null).map(x => ({type: "meeting", from: x.from, to: x.to}));
  const meetingStarts = all0.filter(x => x.to === null).map(x => x.from);
  const ev = eventsOf(data, day);
  const all = [...bl, ...mt].sort((a, b) => a.from - b.from);
  const starts = [...all.map(x => x.from), ...ev.map(x => x.m)], ends = [...all.map(x => x.to), ...ev.map(x => x.m + rulesOf(data).tail)];
  if (!starts.length) return {day, from: 0, to: 0, total: 0, segments: [], meetingStarts};
  const from = Math.floor(Math.min(...starts) / 60) * 60, to = Math.ceil(Math.max(...ends) / 60) * 60, segs = [];
  let at = from;
  for (const x of all) {
    const a = Math.max(x.from, at);
    if (a > at) segs.push({type: "gap", from: at, to: a});
    if (x.to > a) { segs.push({type: x.type, from: a, to: x.to}); at = x.to; }
  }
  if (to > at) segs.push({type: "gap", from: at, to});
  return {day, from, to, total: to - from, meetingStarts, segments: segs.map(s => ({...s, mins: s.to - s.from, label: `${hhmm(s.from)} to ${hhmm(s.to)}`}))};
}

// ---- the heatmap: days across, hours down, a handful of solid steps ----
export const LEVELS = 5;
export const levelOf = n => (n <= 0 ? 0 : n === 1 ? 1 : n <= 3 ? 2 : n <= 5 ? 3 : 4);
export function heatmap(data, end, weeks = WEEKS_SHOWN) {
  const first = addDays(end, -7 * weeks + 1), days = [];
  for (let i = 0; i < weeks * 7; i++) days.push(addDays(first, i));
  const rows = [];
  for (let h = HOURS[0]; h <= HOURS[1]; h++) rows.push(h);
  const cells = rows.map(() => days.map(() => 0));
  days.forEach((d, c) => { for (const e of eventsOf(data, d)) { const r = Math.floor(e.m / 60) - HOURS[0]; if (r >= 0 && r < rows.length) cells[r][c]++; } });
  return {days, hours: rows, counts: cells, levels: cells.map(r => r.map(levelOf)), total: cells.flat().reduce((a, b) => a + b, 0)};
}

// ---- switches between projects ----
export function switches(data, day) {
  let n = 0, prev = null;
  const only = rulesOf(data).switchKinds;
  for (const e of eventsOf(data, day).filter(x => !only || only.includes(x.kind))) { if (prev !== null && e.project && prev && e.project !== prev) n++; if (e.project) prev = e.project; }
  return n;
}
// The owner's usual: the average over the 20 most recent earlier working days that had any activity.
export function usualSwitches(data, day) {
  const vals = [];
  for (let i = 1; i <= 40 && vals.length < 20; i++) { const d = addDays(day, -i); if (isWeekday(d) && eventsOf(data, d).length) vals.push(switches(data, d)); }
  return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
}
export function switchNote(n, usual, when = "today") {
  const s = `${n} switch${n === 1 ? "" : "es"} ${when}`;
  return usual === null ? `${s}. There is no earlier day to compare with yet.` : `${s}, your usual is ${usual}.`;
}

// ---- the week: seven days ending on `end` (so the newest week is always a full seven days, whatever day it is today) ----
export function weekDays(end) { return [6, 5, 4, 3, 2, 1, 0].map(i => addDays(end, -i)); }
export function longestBlock(data, end) {
  let best = null;
  for (const d of weekDays(end)) for (const b of blocks(data, d)) if (!best || b.mins > best.mins) best = {mins: b.mins, day: d, from: b.from, to: b.to};
  return best;
}
const hasLong = (data, d) => blocks(data, d).some(b => b.mins >= LONG);
// Working days in a row, ending on `upTo`, that held a block of LONG minutes or more. Weekends neither count nor break it.
export function streak(data, upTo, today) {
  let d = upTo, n = 0;
  while (!isWeekday(d)) d = addDays(d, -1);
  if (d === today && !hasLong(data, d)) d = addDays(d, -1);
  for (let i = 0; i < 400; i++) {
    if (!isWeekday(d)) { d = addDays(d, -1); continue; }
    if (!hasLong(data, d)) break;
    n++; d = addDays(d, -1);
  }
  return n;
}
// Meeting load. Demo calendar blocks have an end, so the load is minutes. The real calendar snapshot holds only when a block starts, so it
// is a count of blocks, set against the week before in the same way.
export function meetingMinutes(data, end) {
  let t = 0;
  for (const d of weekDays(end)) for (const x of meetingsOf(data, d)) { if (x.to === null) return null; t += x.to - x.from; }
  return t;
}
export const meetingCount = (data, end) => weekDays(end).reduce((a, d) => a + meetingsOf(data, d).length, 0);
export function meetingLoad(data, end) {
  const m = meetingMinutes(data, end), prev = meetingMinutes(data, addDays(end, -7)), count = meetingCount(data, end), prevCount = meetingCount(data, addDays(end, -7));
  if (m === null || prev === null) {
    const diff = count - prevCount;
    return {mins: null, prev: null, count, prevCount, diff, word: diff === 0 ? "about the same as last week" : `${Math.abs(diff)} ${diff > 0 ? "more" : "fewer"} than last week`};
  }
  const d2 = m - prev;
  return {mins: m, prev, count, prevCount, diff: d2, word: Math.abs(d2) < 15 ? "about the same as last week" : `${hoursText(Math.abs(d2))} ${d2 > 0 ? "more" : "less"} than last week`};
}
export function weekStats(data, end, today) {
  return {longest: longestBlock(data, end), streak: streak(data, end, today), meetings: meetingLoad(data, end),
          active: weekDays(end).filter(d => eventsOf(data, d).length).length};
}

// ---- which weeks can be picked (oldest first; the newest ends today) ----
export function weeks(data, today) {
  const f = firstDay(data), out = [];
  for (let i = 0; i < WEEKS_BACK; i++) {
    const end = addDays(today, -7 * i), start = addDays(end, -6);
    if ((!f || end < f) && i > 0) break;
    out.unshift({end, start, label: i === 0 ? "Last 7 days" : weekLabel(start, end), current: i === 0});
  }
  return out;
}
// The day shown in the strip: the last day of the week picked (today, for the newest week).
export const defaultDay = (data, end) => end;

// ---- three quiet observations: sentences about what happened, never about what to do ----
export function observations(data, end) {
  const ds = weekDays(end).filter(d => eventsOf(data, d).length || meetingsOf(data, d).length), out = [], R = rulesOf(data);
  const total = weekDays(end).reduce((a, d) => a + eventsOf(data, d).length, 0), activeDays = weekDays(end).filter(d => eventsOf(data, d).length).length;
  if (ds.length < 2 || total < R.minEvents || activeDays < R.minDays) return ["There is not enough in this week yet to say anything."];
  const bl = ds.flatMap(d => blocks(data, d).map(b => ({...b, day: d})));
  const am = bl.filter(b => b.from < 12 * 60), pm = bl.filter(b => b.from >= 12 * 60);
  const avg = a => (a.length ? a.reduce((t, b) => t + b.mins, 0) / a.length : 0);
  if (am.length && pm.length) out.push(avg(am) >= avg(pm) * 1.2 ? "Mornings are your longest blocks." : avg(pm) >= avg(am) * 1.2 ? "Afternoons are your longest blocks." : "Your blocks are about as long in the morning as in the afternoon.");
  const meet = weekDays(end).map(d => ({d, n: meetingsOf(data, d).length, m: meetingsOf(data, d).reduce((t, x) => t + (x.to === null ? 0 : x.to - x.from), 0)}))
    .map(x => ({...x, k: x.m || x.n})).sort((a, b) => b.k - a.k);                // minutes when the lengths are known, else the number of blocks
  if (meet[0].n >= 2 && meet[0].k > meet[1].k) out.push(`${dayName(meet[0].d)} had the most meetings.`);
  const act = ds.filter(isWeekday).map(d => ({d, n: eventsOf(data, d).length})).sort((a, b) => a.n - b.n);
  if (act.length >= 3 && act[0].n < act[1].n) out.push(`${dayName(act[0].d)} was the quietest working day.`);
  const withLong = ds.filter(d => hasLong(data, d)), without = ds.filter(d => isWeekday(d) && !hasLong(data, d));
  if (withLong.length && without.length) {
    const a = withLong.reduce((t, d) => t + switches(data, d), 0) / withLong.length, b = without.reduce((t, d) => t + switches(data, d), 0) / without.length;
    if (a < b) out.push("Days with a long block had fewer project switches.");
  }
  const lb = longestBlock(data, end);
  if (lb) out.push(`Your longest block ran ${hoursText(lb.mins)} on ${dayName(lb.day)}.`);
  return out.slice(0, 3);
}

// ---- the task timeline: WHAT was worked on, and when (the owner's own words; they come from data.tasks and stay on this screen) ----
// data.tasks = {on, events: [{t: "YYYY-MM-DDTHH:MM", kind: "commit"|"branch"|"pr"|"note"|"run"|"meeting", project, label, branch?}]}
export const TASK_GAP = 45, TASK_TAIL = 5, BRANCH_DAYS = 3;
const TASK_KINDS = ["commit", "branch", "pr", "note", "run", "meeting"];
export const taskEvents = data => {
  const t = data && data.tasks;
  return t && t.on !== false && Array.isArray(t.events)
    ? t.events.filter(e => e && TASK_KINDS.includes(e.kind) && typeof e.t === "string" && DAY.test(e.t.slice(0, 10)) && mins(e.t.slice(11)) !== null && typeof e.label === "string")
      .map(e => ({t: e.t, day: e.t.slice(0, 10), m: mins(e.t.slice(11)), kind: e.kind, project: String(e.project || ""), label: e.label, branch: e.branch || ""})).sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
    : [];
};
export const tasksOn = data => !!(data && data.tasks && data.tasks.on !== false);
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "\u2026" : s);

// Blocks for one day: events of the same project less than TASK_GAP minutes apart make one block, named by its most recent commit subject, else the branch he was
// on (from the checkout entries), else a pull request title, a run, a note; "Unlabelled" when there is nothing. A calendar block is its own row with its title.
export function taskBlocks(data, day) {
  const all = taskEvents(data), ev = all.filter(e => e.day === day), out = [];
  const byProject = new Map();
  for (const e of ev.filter(x => x.kind !== "meeting")) { if (!byProject.has(e.project)) byProject.set(e.project, []); byProject.get(e.project).push(e); }
  for (const [project, list] of byProject) {
    let cur = null;
    const flush = () => { if (cur) out.push(cur); };
    for (const e of list) {
      if (cur && e.m - cur.last < TASK_GAP) { cur.last = e.m; cur.events.push(e); }
      else { flush(); cur = {project, first: e.m, last: e.m, events: [e]}; }
    }
    flush();
  }
  const named = out.map(b => {
    const end = `${day}T${String(Math.floor((b.last + 1) / 60)).padStart(2, "0")}:${String((b.last + 1) % 60).padStart(2, "0")}`, lo = addDays(day, -BRANCH_DAYS);
    const branch = [...all].reverse().find(x => x.kind === "branch" && x.label && x.project === b.project && x.t <= end && x.day >= lo);
    const pick = k => [...b.events].reverse().find(x => x.kind === k && x.label);
    const commit = pick("commit"), pr = pick("pr"), run = pick("run"), note = pick("note"), inBranch = pick("branch");
    const via = commit || (inBranch || branch) || pr || run || note;
    const evidence = [...b.events];
    if (branch && !b.events.includes(branch)) evidence.unshift({...branch, outside: true});
    return {kind: "work", project: b.project, from: b.first, to: b.last + TASK_TAIL, mins: b.last - b.first + TASK_TAIL, count: b.events.length, label: via ? short(via.label, 90) : "Unlabelled",
            source: via ? via.kind : "none", evidence: evidence.map(x => ({t: x.t, m: x.m, kind: x.kind, label: x.label, outside: !!x.outside}))};
  });
  const meets = ev.filter(e => e.kind === "meeting").map(e => ({kind: "meeting", project: "", from: e.m, to: null, mins: 0, count: 1, label: short(e.label, 90), source: "meeting", evidence: [{t: e.t, m: e.m, kind: "meeting", label: e.label, outside: false}]}));
  return [...named, ...meets].sort((a, b) => a.from - b.from || (a.kind < b.kind ? -1 : 1));
}
export function projectSummary(blocks) {
  const by = new Map();
  for (const b of blocks.filter(x => x.kind === "work")) { const v = by.get(b.project) || {project: b.project, mins: 0, blocks: 0}; v.mins += b.mins; v.blocks++; by.set(b.project, v); }
  return [...by.values()].sort((a, b) => b.mins - a.mins || (a.project < b.project ? -1 : 1));
}
export const summaryLine = x => `${x.project || "No project"} ${hoursText(x.mins)} across ${x.blocks} block${x.blocks === 1 ? "" : "s"}`;
export const clock = m => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
export const blockLine = b => (b.kind === "meeting" ? `${clock(b.from)} meeting, ${b.label}` : `${clock(b.from)} to ${clock(b.to)} ${b.project ? b.project + ", " : ""}${b.label}`);

const PARTS = {morning: [0, 720, "this morning", "that morning"], afternoon: [720, 1080, "this afternoon", "that afternoon"], evening: [1080, 1440, "this evening", "that evening"]};
export const dayWord = (day, today) => (day === today ? "today" : day === addDays(today, -1) ? "yesterday" : dayLabel(day));
// "What was I working on this morning": the blocks of that part of the day, in words. Says so when nothing is recorded.
export function workedText(data, day, part, today) {
  if (!tasksOn(data)) return "Task titles are switched off, so I cannot say.";
  const [lo, hi] = PARTS[part] || [0, 1440], when = part ? `${day === today ? "this" : day === addDays(today, -1) ? "yesterday" : dayWord(day, today)} ${part}`.replace("this morning", "this morning") : dayWord(day, today);
  const bl = taskBlocks(data, day).filter(b => b.from >= lo && b.from < hi);
  if (!bl.length) return `Nothing is recorded for ${when}. I can only see commits, branches, pull requests, notes, hand-started runs and calendar blocks.`;
  const shown = bl.slice(0, 4).map(b => blockLine(b)).join(". ");
  return `${when[0].toUpperCase() + when.slice(1)}: ${shown}.${bl.length > 4 ? ` And ${bl.length - 4} more.` : ""} That is an estimate from commits, branches, notes and the calendar.`;
}
// "When did I last touch Saltpan blog": the latest commit, branch, pull request, note or run of that project.
export function lastTouched(data, project, today) {
  if (!tasksOn(data)) return "Task titles are switched off, so I cannot say.";
  const e = [...taskEvents(data)].reverse().find(x => x.project === project && x.kind !== "meeting");
  if (!e) return `I find nothing recorded for ${project}.`;
  return `You last touched ${project} ${dayWord(e.day, today)} at ${clock(e.m)}: ${e.label}. That is an estimate from commits, branches, notes and the calendar.`;
}

// ---- how each number is worked out, in plain words (the demo says it is invented; real data says what it is built from and what it cannot see) ----
const SIGNALS = "Only five kinds of signal are used: commits, pull requests, notes, calendar blocks and agent runs you started by hand.";
const INVENTED = "In this preview all of it is invented, and nothing is collected.";
const REAL_SIGNALS = "An hour counts as active when it holds a commit of yours in a registered project, a note you added in Quarterdeck, a pull request you opened, or an agent run you started by hand from Quarterdeck. Commits that agents made under your name are left out. Only counts and the hour are kept: no message, file name, title or text is read.";
const CANNOT = "It is an estimate and it cannot see reading, thinking or other work.";
export function explainFor(data) {
  const R = rulesOf(data), real = isReal(data), end = real ? " " + CANNOT : " " + INVENTED, g = R.gap + 1;
  const block = real
    ? `A focus block is a run of those events with less than ${g} minutes between them, lasting at least ${R.minBlock} minutes. A single event is not a block. Only the hour of each event is kept, so the minutes inside an hour are estimated by spreading its events evenly across it. A meeting start between two events ends a block.`
    : `A focus block is a run of those actions with less than ${GAP} minutes between them and no calendar block in between. It runs from the first to the last, plus ${TAIL} minutes, and counts once it lasts ${FOCUS_MIN} minutes or more.`;
  return {
    heat: real ? `Each square is one hour of one day, lit by how many events fall in that hour: none, one, two or three, four or five, six or more. ${REAL_SIGNALS}${end}`
      : `Each square is one hour of one day. Its colour is how many commits, pull requests, notes and hand-started agent runs fall in that hour: none, one, two or three, four or five, six or more. ${SIGNALS}${end}`,
    block: `${block}${end}`,
    longest: `The longest focus block of the week shown (seven days): of all the blocks found on those days, the one that ran longest. ${block}${end}`,
    streak: `The number of working days in a row, counting back from the last day of the week shown, that held a focus block of ${LONG} minutes or more. Weekends do not count and do not break it.${end}`,
    meetings: real
      ? `The number of timed calendar blocks on the seven days, set against the week before. The calendar snapshot Quarterdeck reads holds when a block starts, not how long it lasts, and never a title, so this is a count of blocks, and only for blocks it saw before they passed.${end}`
      : `The total length of the calendar blocks on the seven days, set against the week before. A difference under 15 minutes is called about the same. Only the start and end of each block are used, never a title.${end}`,
    switches: real
      ? `A switch is two commits in a row, in the order they were made that day, that belong to different projects. Your usual is the average of the last 20 working days that had any commits, rounded to a whole number. Because only the hour of a commit is kept, the order inside an hour is an estimate.${end}`
      : `A switch is two actions in a row that belong to different projects, in the order they happened that day. Your usual is the average of the last 20 working days that had any activity, rounded to a whole number.${end}`,
    strip: real
      ? `The day from its first hour to its last: focus blocks in blue and everything else, the gaps, in grey; calendar blocks are marked at the hour they start, because their length is not known.${end}`
      : `The day from its first hour to its last: focus blocks in blue, calendar blocks in amber, and everything else, the gaps, in grey.${end}`,
    tasks: real
      ? `Events of the same project less than 45 minutes apart make one block: commits (the first line of the message only), branch checkouts from the project's own git log, pull requests you opened, notes you added in Quarterdeck, runs and missions you started by hand, and the calendar titles for meetings. A block is named by its most recent commit subject, else the branch you were on, else a pull request, run or note, and says Unlabelled when there is nothing. Nothing is invented: no body, diff or file is read. These words stay on this Mac in state/rhythm-tasks.json, are never sent to any model, and the file is deleted with rm -f state/rhythm-tasks.json.${end}`
      : `Events of the same project less than 45 minutes apart make one block, named by its most recent commit subject, else the branch, else a pull request, run or note. The blocks, labels and titles here are invented.${end}`,
    observation: `Each sentence is chosen by a rule over the week: comparing the length of morning and afternoon blocks, which day had the most calendar time, which working day had the fewest events, whether days with a long block had fewer project switches. It only says what happened.${real ? ` It says nothing until the week holds at least ${R.minEvents} events on ${R.minDays} days.` : ""}${end}`,
  };
}
export const EXPLAIN = explainFor(null);

// Is there enough to draw anything honest? (real data only: the demo always has plenty)
export function enough(data, today) {
  const R = rulesOf(data);
  if (!R.minEvents) return true;
  const from = addDays(today, -34);
  return ((data && data.events) || []).filter(e => e && typeof e.t === "string" && e.t.slice(0, 10) >= from).length >= R.minEvents;
}
export const BADGE = "Concept preview: invented data, nothing is collected";
