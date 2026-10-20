// Pure logic for the lists behind the Brain's counts: "9 need you", "1 not connected", an area's count.
// No DOM, no network. The page hands in the graph's nodes and gets back rows to show; it adds the buttons
// itself, because those act on the dashboard. A count and its list are built from the same nodes, so they
// cannot disagree.

export const STATE_TITLES = {attn: "Need you", live: "Working", new: "New", off: "Not connected"};
const ORDER = {attn: 0, live: 1, new: 2, idle: 3, off: 4};

// Where the README explains each connection that can be "not connected".
const DOCS = {
  ga4: "Connecting your accounts, Site analytics", gmail: "Connecting your accounts, Gmail", slack: "Connecting your accounts, Slack",
  linkedin: "Connecting your accounts, LinkedIn", facebook: "Connecting your accounts, Facebook and Instagram",
  instagram: "Connecting your accounts, Facebook and Instagram", calendar: "Your day", reminders: "Your day",
  macmail: "Connecting your accounts, Mac Mail", threads: "Connecting your accounts, Threads", x: "Connecting your accounts, X",
  drive: "Dashboard, Brain, Setting up the connections",
};
export const NODE_DOCS = {};      // add-ons say where their own nodes are explained: node id -> the line to show
export const docPointer = n => {
  const feed = n && n.ref && n.ref.feed;
  if (feed) return "README: " + (DOCS[String(feed).split("@")[0]] || "Dashboard, Brain, Setting up the connections");
  return (n && NODE_DOCS[n.id]) || "";
};

const rowOf = (n, byId, regions) => {
  const parent = n.parent && byId.get(n.parent);
  return {id: n.id, label: n.label, sub: n.sub || "", state: n.state, region: n.region, ref: n.ref || null,
    source: [(regions[n.region] || {}).name || n.region, parent ? parent.label : "", n.kind].filter(Boolean).join(" / "), doc: n.state === "off" ? docPointer(n) : ""};
};

// sel: {kind: "state", key: "attn"|"live"|"new"|"off"} | {kind: "region", key: "code"|...} | {kind: "hub", key: <hub id>}
export function listFor(sel, nodes = [], regions = {}) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  let pick, title;
  if (sel.kind === "state") { pick = n => n.state === sel.key; title = STATE_TITLES[sel.key] || sel.key; }
  else if (sel.kind === "region") { pick = n => n.region === sel.key; title = (regions[sel.key] || {}).name || sel.key; }
  else if (sel.kind === "hub") { pick = n => n.parent === sel.key && (!sel.only || n.state === sel.only); title = ((byId.get(sel.key) || {}).label || "Items") + (sel.only ? ", " + (STATE_TITLES[sel.only] || sel.only).toLowerCase() : ""); }
  else return {title: "", rows: []};
  const rows = nodes.filter(pick).map(n => rowOf(n, byId, regions))
    .map((r, i) => ({r, i})).sort((a, b) => (ORDER[a.r.state] ?? 3) - (ORDER[b.r.state] ?? 3) || a.i - b.i).map(x => x.r);
  return {title, rows};
}

// "Mark all seen": a node counts as seen when its key was marked. A hub's key includes how many of its
// children are new, so a hub (a mail connection) that gets another new item shows as new again.
export function seenKey(n, nodes) {
  if (!n.hub) return n.id;
  return n.id + "|" + nodes.filter(k => k.parent === n.id && k.state === "new").length;
}
export function applySeen(nodes, seen) {
  const set = seen instanceof Set ? seen : new Set(seen || []);
  return nodes.map(n => n.state === "new" && set.has(seenKey(n, nodes)) ? {...n, state: "idle"} : n);
}
// The keys to remember after pressing "Mark all seen" on the current "new" nodes, plus what was remembered
// before, kept only while it still matches something, and never more than `cap`.
export function markSeen(nodes, seen, cap = 400) {
  const now = nodes.filter(n => n.state === "new").map(n => seenKey(n, nodes));
  return [...new Set([...(seen instanceof Set ? [...seen] : seen || []), ...now])].slice(-cap);
}
