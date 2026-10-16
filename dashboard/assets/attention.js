// Pure metrics over state/attention.json (what the OWNER did, estimated from timestamps and counts, never content).
// days = {project: {"YYYY-MM-DD": {commits, files, prs, notes, meetings}}}. No DOM, no network:
// the page passes the snapshot in, so this is tested with node (bin/selftest-assistant.mjs). The numbers are
// estimates; everything shown to the owner goes through band() and ratioWord() so nothing looks more exact than it is.

export const CALENDAR = "(calendar)", OTHER = "other";
export const DEFAULTS = {windowDays: 7, longDays: 30, minVolume: 24, smooth: 12, emergeRatio: 1.8, dormantDays: 14, meaningful: 6, gapShare: 0.1};

const n0 = v => (typeof v === "number" && isFinite(v) && v > 0 ? v : 0);
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const ms = d => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
export const addDays = (d, k) => { const t = new Date(ms(d) + k * 864e5); return t.toISOString().slice(0, 10); };
export const weekday = d => new Date(ms(d)).getUTCDay();                 // 0 Sunday .. 6 Saturday
export const isWeekend = d => { const w = weekday(d); return w === 0 || w === 6; };
export const mondayOf = d => addDays(d, -((weekday(d) + 6) % 7));
export const dayDiff = (a, b) => Math.round((ms(a) - ms(b)) / 864e5);

// One number per project and day, in "points": a fixed credit for each of the owner's own commits, pull requests and
// notes. Only what Quarterdeck may read counts (never what happens on the computer outside the projects).
export const weight = r => (r && typeof r === "object" ? 6 * n0(r.commits) + 4 * n0(r.prs) + 2 * n0(r.notes) : 0);

const named = days => Object.keys(days || {}).filter(p => p !== CALENDAR && p !== OTHER);
const inWindow = (days, project, from, to) => {
  let t = 0;
  for (const [d, r] of Object.entries((days || {})[project] || {})) if (DAY.test(d) && d >= from && d <= to) t += weight(r);
  return t;
};

// Points per project for the n days ending on `today`, shifted back by `back` days. Named projects only.
export function totals(days, today, n = DEFAULTS.windowDays, back = 0) {
  const to = addDays(today, -back), from = addDays(to, -(n - 1)), out = {};
  for (const p of named(days)) { const t = inWindow(days, p, from, to); if (t > 0) out[p] = t; }
  return out;
}

export function share(days, today, n = DEFAULTS.windowDays, back = 0) {
  const t = totals(days, today, n, back), sum = Object.values(t).reduce((a, b) => a + b, 0);
  return Object.entries(t).map(([project, points]) => ({project, points, share: sum ? points / sum : 0})).sort((a, b) => b.points - a.points);
}

const BANDS = [[0.85, "nearly all"], [0.62, "about two thirds"], [0.45, "about half"], [0.29, "about a third"], [0.2, "about a quarter"],
               [0.14, "about a sixth"], [0.07, "a small part"], [0.0001, "a sliver"]];
export function band(s) {
  const v = typeof s === "number" && isFinite(s) ? s : 0;
  for (const [min, word] of BANDS) if (v >= min) return word;
  return "none";
}

// Smoothed ratio of this window to the previous one: (cur + k) / (prev + k), so 10 points against 2 is not "5x".
export function ratio(cur, prev, k = DEFAULTS.smooth) { return (n0(cur) + k) / (n0(prev) + k); }
export function ratioWord(r) {
  if (!(r > 0)) return "";
  if (r >= 5) return "5x or more";
  if (r >= 2.5) return "about " + Math.round(r) + "x";
  if (r >= 1.8) return "about twice";
  if (r >= 1.3) return "up about half";
  if (r > 0.77) return "about the same";
  if (r > 0.55) return "down about a third";
  if (r > 0.4) return "down about half";
  return "much less";
}

export function velocity(days, today, opts = {}) {
  const o = {...DEFAULTS, ...opts}, cur = totals(days, today, o.windowDays), prev = totals(days, today, o.windowDays, o.windowDays), out = [];
  for (const p of new Set([...Object.keys(cur), ...Object.keys(prev)])) {
    const c = cur[p] || 0, q = prev[p] || 0;
    out.push({project: p, cur: c, prev: q, ratio: ratio(c, q, o.smooth), word: ratioWord(ratio(c, q, o.smooth)), enough: c + q >= o.minVolume});
  }
  return out.sort((a, b) => b.ratio - a.ratio);
}

// Emerging: clearly more than last window AND enough volume this window to mean something.
export function emerging(days, today, opts = {}) {
  const o = {...DEFAULTS, ...opts};
  return velocity(days, today, o).filter(v => v.cur >= o.minVolume && v.ratio >= o.emergeRatio);
}

// Weekdays (Monday to Friday) from the day after `from` up to and including `to`.
export function weekdaysBetween(from, to) {
  let n = 0;
  for (let d = addDays(from, 1); d <= to; d = addDays(d, 1)) if (!isWeekend(d)) n++;
  return n;
}

// First day anything was recorded at all (to tell "went quiet" from "never tracked").
export function firstDay(days) {
  let f = "";
  for (const p of named(days)) for (const [d, r] of Object.entries(days[p] || {})) if (DAY.test(d) && weight(r) > 0 && (!f || d < f)) f = d;
  return f;
}

// statuses = {project: {status: "continue"|"park"|"archive", at: "YYYY-MM-DD"}} from state/project-status.json.
// Dormant = no meaningful day for `dormantDays` weekdays (weekends do not count). Parked and archived are left out;
// "continue" restarts the clock from the day it was chosen. A project never seen is dormant only when the data is old enough.
export function dormant(days, today, projects, statuses = {}, opts = {}) {
  const o = {...DEFAULTS, ...opts}, start = firstDay(days), out = [];
  for (const p of projects || []) {
    if (p === CALENDAR || p === OTHER) continue;
    const st = (statuses || {})[p] || {};
    if (st.status === "park" || st.status === "archive") continue;
    let last = "";
    for (const [d, r] of Object.entries((days || {})[p] || {})) if (DAY.test(d) && weight(r) >= o.meaningful && d > last) last = d;
    const anchor = [last, st.status === "continue" && DAY.test(st.at || "") ? st.at : ""].sort().pop();
    const from = anchor || start;
    if (!from) continue;
    const quiet = weekdaysBetween(from, today);
    if (quiet >= o.dormantDays) out.push({project: p, last: last || null, quiet, never: !last});
  }
  return out.sort((a, b) => b.quiet - a.quiet);
}

// intent = {projects: [{name, share?}], from, to}; shares are 0..1 and optional (equal split when none are given).
export function intentTargets(intent) {
  const ps = (Array.isArray(intent && intent.projects) ? intent.projects : []).filter(x => x && typeof x.name === "string" && x.name).slice(0, 4);
  if (!ps.length) return [];
  const given = ps.reduce((a, x) => a + n0(x.share), 0), unset = ps.filter(x => !n0(x.share)).length;
  const each = unset ? Math.max(0, 1 - Math.min(given, 1)) / unset : 0;
  const raw = ps.map(x => ({project: x.name, target: n0(x.share) || each}));
  const sum = raw.reduce((a, x) => a + x.target, 0);
  return sum ? raw.map(x => ({...x, target: x.target / sum})) : raw.map(x => ({...x, target: 1 / raw.length}));
}

// The newest intent whose week range covers `today` (the range is Monday to Sunday of the week it was set for).
export function currentIntent(records, today) {
  const ok = (records || []).filter(r => r && DAY.test(r.from || "") && DAY.test(r.to || "") && r.from <= today && today <= r.to);
  return ok.length ? ok[ok.length - 1] : null;
}

// Focus versus reality for the days of the intent's week so far (at most seven, at least one).
export function focusVsReality(intent, days, today, opts = {}) {
  const o = {...DEFAULTS, ...opts}, targets = intentTargets(intent);
  if (!targets.length) return null;
  const from = intent.from > today ? today : intent.from, n = Math.min(7, Math.max(1, dayDiff(today, from) + 1));
  const sh = share(days, today, n), by = Object.fromEntries(sh.map(x => [x.project, x.share])), total = sh.reduce((a, x) => a + x.points, 0);
  const rows = targets.map(t => {
    const actual = by[t.project] || 0, gap = actual - t.target;
    return {project: t.project, target: t.target, actual, gap, verdict: !total ? "no data" : actual < 0.05 ? "missing" : gap <= -o.gapShare ? "under" : gap >= o.gapShare ? "over" : "on track"};
  });
  const elsewhere = sh.filter(x => !targets.some(t => t.project === x.project) && x.share >= 0.15)[0] || null;
  return {rows, elsewhere: elsewhere && {project: elsewhere.project, share: elsewhere.share}, days: n, total, enough: total >= o.minVolume};
}

// Node weights for the Brain (0..1, the share of the largest), only when there is data.
export function sizeWeights(days, today, n = DEFAULTS.windowDays) {
  const sh = share(days, today, n), top = sh.length ? sh[0].points : 0;
  return Object.fromEntries(sh.map(x => [x.project, top ? x.points / top : 0]));
}

// Quiet one-liner for Home: the strongest emerging project, or null. Never more than one.
export function homeLine(days, today, opts = {}) {
  const e = emerging(days, today, opts)[0];
  return e ? `${e.project} is up ${e.word === "about twice" ? "about twice" : e.word} this week.` : null;
}

// ---- spoken and written answers (Helm and the panel). Every one says it is an estimate. ----
const list = (xs, n = 3) => xs.length <= 1 ? xs.join("") : xs.length <= n ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs.slice(0, n).join(", ") + ` and ${xs.length - n} more`;
export function dormantText(d, o = DEFAULTS) {
  if (!d.length) return `Nothing has gone quiet: every project has had real work in the last ${o.dormantDays} working days. That is an estimate.`;
  const first = d.slice(0, 3).map(x => x.never ? `${x.project}, with no activity recorded` : `${x.project}, quiet for ${x.quiet} working days`);
  return `${d.length} project${d.length === 1 ? " has" : "s have"} gone quiet: ${list(first)}. Say, park ${d[0].project}, to stop raising it. That only hides it, and it is an estimate.`;
}
export function emergingText(e) {
  if (!e.length) return "Nothing is clearly picking up compared with last week. That is an estimate.";
  return list(e.slice(0, 3).map(x => `${x.project} is up ${x.word === "about twice" ? "about twice" : x.word}`)) + " compared with last week. That is an estimate.";
}
export function weekText(days, today, intent) {
  const sh = share(days, today, 7), total = sh.reduce((a, x) => a + x.points, 0);
  if (total < DEFAULTS.minVolume) return "Not enough is recorded in the last seven days to say, and these numbers are only estimates.";
  const active = new Set();
  let meetings = 0;
  for (let i = 0; i < 7; i++) {
    const d = addDays(today, -i);
    if (named(days).some(p => weight((days[p] || {})[d]) > 0)) active.add(d);
    meetings += n0(((days || {})[CALENDAR] || {})[d] && days[CALENDAR][d].meetings);
  }
  const parts = [`Over the last seven days, as an estimate: ${list(sh.slice(0, 3).map(x => `${band(x.share)} was ${x.project}`))}.`, `You were active on ${active.size} of 7 days.`];
  if (meetings) parts.push(`${meetings} timed meeting${meetings === 1 ? "" : "s"}.`);
  const up = emerging(days, today)[0];
  if (up) parts.push(`${up.project} is up ${up.word === "about twice" ? "about twice" : up.word} on the week before.`);
  const f = intent && focusVsReality(intent, days, today);
  if (f && f.enough) parts.push("Against your focus: " + list(f.rows.map(r => `${r.project} ${r.verdict}`)) + ".");
  return parts.join(" ");
}

// ---- replay: a day slider that re-sizes nodes from the daily buckets, no state snapshots needed ----
// The days offered run from the first recorded day (at most `max` back) to today, oldest first.
export function replayRange(days, today, max = 60) {
  const f = firstDay(days);
  if (!f) return [];
  const from = f > addDays(today, -(max - 1)) ? f : addDays(today, -(max - 1)), out = [];
  for (let d = from; d <= today; d = addDays(d, 1)) out.push(d);
  return out;
}
// The Brain's node weights as of `day`: the same seven-day share the toggle uses, ending that day.
export const dayWeights = (days, day, n = DEFAULTS.windowDays) => sizeWeights(days, day, n);
// What the Ledger holds for one day, oldest first. `dayOf` turns a timestamp into the owner's local day.
export function dayRuns(runs, day, dayOf = at => String(at).slice(0, 10)) {
  return (Array.isArray(runs) ? runs : []).filter(r => r && r.at && dayOf(r.at) === day)
    .sort((a, b) => String(a.at).localeCompare(String(b.at))).map(r => ({at: r.at, project: r.project, duty: r.duty, verdict: r.verdict, detail: String(r.detail || "").slice(0, 160)}));
}
