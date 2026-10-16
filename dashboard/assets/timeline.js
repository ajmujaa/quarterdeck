// Pure logic for the fleet timeline (Home strip and the Timeline view). No DOM, no network: the page hands in
// events {at, project, duty, verdict, detail, kind} (kind is "run", "merge", or any other word an add-on gives its own events) and gets back plain data.
// Lanes are binned, so 500 runs or 5000 cost the page the same: at most `buckets` markers per lane.

export const WINDOWS = {"6h": 6 * 3600e3, "24h": 24 * 3600e3, "7d": 7 * 86400e3};
export const WINDOW_LABELS = {"6h": "6 hours", "24h": "24 hours", "7d": "7 days"};

// What a marker looks like. One entry per colour in the legend; the order is worst first, which is also how a
// bin that holds several events picks its colour.
export const CLASSES = [
  {id: "bad", label: "Failed"}, {id: "warn", label: "Needs a person"}, {id: "ext", label: "Failed elsewhere"},
  {id: "merge", label: "Merged"}, {id: "good", label: "Succeeded"}, {id: "quiet", label: "Routine"},
];
const BAD = new Set(["ERROR", "FAILED", "BLOCKED", "BROKEN"]);
const GOOD = new Set(["CLEAN", "OK", "PROVEN", "SYNCED", "FILED", "REPRODUCED", "PR", "RULED", "READY"]);
const QUIET = new Set(["DRY-RUN", "SKIPPED", "NOT-RED", "NONE", "TAKEN", "NOTHING-TO-BUILD"]);
export function classOf(ev) {
  if (!ev) return "quiet";
  if (ev.kind && ev.kind !== "run" && ev.kind !== "merge") return "ext";       // an add-on's own events (an add-on may rename the "ext" label above)
  if (ev.kind === "merge" || ev.verdict === "MERGED") return "merge";
  if (BAD.has(ev.verdict)) return "bad";
  if (GOOD.has(ev.verdict)) return "good";
  if (QUIET.has(ev.verdict)) return "quiet";
  return "warn";
}
const RANK = Object.fromEntries(CLASSES.map((c, i) => [c.id, i]));

const when = at => { const t = Date.parse(at); return isNaN(t) ? null : t; };

// Events inside the window ending at `now`, newest first, kept only if they pass the filters.
export function select(events = [], {windowKey = "24h", now = Date.now(), project = "", duty = "", verdict = ""} = {}) {
  const span = WINDOWS[windowKey] || WINDOWS["24h"], from = now - span;
  return events.filter(e => e && when(e.at) !== null && when(e.at) >= from && when(e.at) <= now + 60000
      && (!project || e.project === project) && (!duty || e.duty === duty) && (!verdict || classOf(e) === verdict))
    .sort((a, b) => when(b.at) - when(a.at));
}

// One lane per project that has an event or is known, each with at most `buckets` bins.
// A bin: {i, from, to, n, cls, events (newest first, at most 5 kept), first} where `first` is the worst-then-newest event.
export function buildLanes(events = [], {windowKey = "24h", now = Date.now(), project = "", duty = "", verdict = "", projects = [], buckets = 96} = {}) {
  const span = WINDOWS[windowKey] || WINDOWS["24h"], from = now - span, size = span / buckets;
  const sel = select(events, {windowKey, now, project, duty, verdict});
  const names = [...new Set([...(project ? [project] : projects), ...sel.map(e => e.project || "fleet")])].filter(p => !project || p === project).sort();
  const lanes = names.map(name => ({name, bins: new Map(), total: 0}));
  const byName = new Map(lanes.map(l => [l.name, l]));
  for (const e of sel) {
    const lane = byName.get(e.project || "fleet"), t = when(e.at);
    const i = Math.min(buckets - 1, Math.max(0, Math.floor((t - from) / size)));
    let b = lane.bins.get(i);
    if (!b) lane.bins.set(i, b = {i, from: from + i * size, to: from + (i + 1) * size, n: 0, cls: "quiet", events: [], first: null});
    b.n++; lane.total++;
    const c = classOf(e);
    if (b.n === 1 || RANK[c] < RANK[b.cls]) { b.cls = c; b.first = e; }
    if (b.events.length < 5) b.events.push(e);
  }
  return {from, to: now, windowKey, total: sel.length, buckets,
    lanes: lanes.map(l => ({name: l.name, total: l.total, bins: [...l.bins.values()].sort((a, b) => a.i - b.i)}))};
}

// Where a bin sits on the track, 0 to 100 percent.
export const pct = (bin, from, to) => Math.max(0, Math.min(100, ((bin.from + bin.to) / 2 - from) / (to - from) * 100));

// A few labelled ticks along the axis: the window's start, quarters, and "now".
export function axisTicks(windowKey, now, fmt) {
  const span = WINDOWS[windowKey] || WINDOWS["24h"];
  return [0, 0.25, 0.5, 0.75, 1].map(f => ({at: f * 100, label: f === 1 ? "now" : fmt(now - span * (1 - f))}));
}

// The compact strip on Home: the newest `n` events of any kind, runs and an add-on's own events together.
export function recentStrip(runs = [], extra = [], n = 12) {
  return [...runs.map(r => ({...r, kind: r.verdict === "MERGED" ? "merge" : "run"})), ...extra]
    .filter(e => e && when(e.at) !== null).sort((a, b) => when(b.at) - when(a.at)).slice(0, n);
}

// "6 events in this hour: 5 PR, 1 ERROR" for hover and focus.
export function binText(bin, fmt) {
  const first = bin.first || {};
  const kinds = {}; for (const e of bin.events) kinds[e.verdict || e.kind] = (kinds[e.verdict || e.kind] || 0) + 1;
  const head = bin.n === 1 ? `${first.project || "fleet"} · ${first.duty || first.kind} · ${first.verdict || ""}`.trim()
    : `${bin.n} events, ${Object.entries(kinds).map(([k, v]) => `${v} ${k}`).join(", ")}${bin.n > bin.events.length ? " and more" : ""}`;
  return `${fmt(bin.from)}: ${head}${bin.n === 1 && first.detail ? " · " + String(first.detail).slice(0, 120) : ""}`;
}
