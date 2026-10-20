// The Brain that watches and suggests, from plain rules (no model). `detect` takes the dashboard's previous and
// current snapshot and returns change events, each with at most one suggested action. Every action only opens
// something (a pull request, a Ledger row, a page): nothing here changes anything, so no action needs a confirm.
// The rest is a small store (what was seen, dismissed, snoozed) that the page keeps in this browser.
// No DOM, no network, no clock but the one passed in, so it is all tested under node.
//
// A snapshot is {S, prs, attention}: S is /api/state, prs the open pull requests (or null before they are known), attention
// {days, today, projects, statuses, intents} from /api/attention and /api/intent (absent when the collector is off or empty).

import {dormant, emerging, focusVsReality, currentIntent, mondayOf, addDays, weekday, ratioWord, band} from "./attention.js";
const BAD = new Set(["ERROR", "FAILED", "BLOCKED", "BROKEN"]);
// "Far longer than usual" for an agent, in minutes, by duty. A duty not listed gets DEFAULT_LONG.
export const LONG_MINUTES = {harbourmaster: 10, foreman: 15, surveyor: 20, inspector: 20, joiner: 20, trials: 20, purser: 20, panel: 30, shipwright: 60};
export const DEFAULT_LONG = 45;
export const MEETING_MINUTES = 15, WAITING_HOURS = 24, OVERDUE_HOURS = 24, RUN_FAILED_HOURS = 6, SNOOZE_MINUTES = 60, KEEP = 20, TTL_HOURS = 6, SPEAK_GAP_MINUTES = 5;

const t = s => { const n = Date.parse(s); return isNaN(n) ? null : n; };
const clip = (s, n) => { s = String(s == null ? "" : s).replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const mins = ms => Math.round(ms / 60000);
const span = ms => { const m = mins(ms); return m < 120 ? m + " min" : m < 2880 ? Math.round(m / 60) + " h" : Math.round(m / 1440) + " days"; };
const ledgerKey = r => [r.at, r.project, r.duty].join("|");
const conn = (S, name) => ((S && S.connectors) || []).find(c => c && c.name === name && c.connected);
// Every connected account of a service (one entry each when a service has several accounts: each has `account` and a unique `key`).
const conns = (S, name) => ((S && S.connectors) || []).filter(c => c && c.name === name && c.connected);
const connKey = c => c.key || c.name;
const https = u => (typeof u === "string" && u.startsWith("https://") ? u : null);

const ev = (id, kind, sev, title, why, now, action, live) => ({id, kind, sev, title: clip(title, 90), why: clip(why, 140), at: new Date(now).toISOString(), action: action || null, live: !!live});

export function detect(prev, cur, now = Date.now()) {
  const S = (cur && cur.S) || {}, out = [], P = prev && prev.S;

  // 1. A pull request whose checks have just finished and passed (they were running or failing a poll ago).
  const before = new Map(((prev && prev.prs) || []).map(p => [p.project + "#" + p.number, p]));
  for (const p of (cur && cur.prs) || []) {
    const was = before.get(p.project + "#" + p.number), c = p.checks || {}, w = was && was.checks || {};
    if (was && (w.pending > 0 || w.fail > 0) && !c.pending && !c.fail && c.pass > 0)
      out.push(ev(`pr-green:${p.project}#${p.number}`, "pr-green", 2, `Checks passed on #${p.number} (${p.project})`, p.title, now,
        https(p.url) ? {label: "Open pull request", type: "url", url: p.url} : {label: "Pull requests", type: "go", view: "prs", project: p.project}, false));
  }

  // 2. A run that failed since the last look (not on the first look: the Needs you list already says so).
  if (P) {
    const had = new Set((P.runs || []).map(ledgerKey));
    for (const r of S.runs || []) {
      if (!BAD.has(r.verdict) || had.has(ledgerKey(r)) || now - (t(r.at) || 0) > RUN_FAILED_HOURS * 3600e3) continue;
      out.push(ev(`run-failed:${ledgerKey(r)}`, "run-failed", 3, `${r.duty} failed on ${r.project}`, r.detail || "No detail recorded.", now,
        {label: "See why", type: "ledger", key: ledgerKey(r), project: r.project}, false));
    }
  }

  // 3. An agent that has run far longer than usual for its duty.
  for (const a of S.agents || []) {
    if (a.status !== "running" || !t(a.since)) continue;
    const limit = (LONG_MINUTES[a.duty] || DEFAULT_LONG) * 60000, ran = now - t(a.since);
    if (ran > limit)
      out.push(ev(`agent-long:${a.lock || a.project + a.duty}:${a.since}`, "agent-long", 2, `${a.duty} on ${a.project} has run ${span(ran)}`,
        `That is far longer than a ${a.duty} usually takes. ${a.what || ""}`, now, {label: "Open operations", type: "go", view: "operations", project: a.project}, true));
  }

  // 4. Mail or a Slack message that has waited over a day.
  for (const name of ["gmail", "slack"]) for (const c of conns(S, name)) {
    if (!(c.unread > 0) || !(c.items || []).length) continue;
    const old = (c.items || []).filter(i => t(i.at)).sort((a, b) => t(a.at) - t(b.at))[0];
    if (old && now - t(old.at) > WAITING_HOURS * 3600e3)
      out.push(ev(`waiting:${c.account ? connKey(c) : name}:${old.at}`, "waiting", 2, `${c.label || name}: something has waited ${span(now - t(old.at))}`,
        `${c.unread} waiting. The oldest: ${old.title}${old.sub ? " (" + old.sub + ")" : ""}`, now, {label: "Open " + (c.label || name), type: "brain", node: "c:" + connKey(c)}, true));
  }

  // 5. An analytics page that doubled in views against last week.
  for (const name of ["ga4", "analytics"]) for (const c of conns(S, name)) {
    for (const i of c.items || []) {
      const m = /([\d,]+) views, \+(\d+)% vs last week/.exec(i.sub || ""), views = m && Number(m[1].replace(/,/g, "")), pct = m && Number(m[2]);
      if (m && pct >= 100 && views >= 100)
        out.push(ev(`doubled:${i.title}:${new Date(now).toISOString().slice(0, 10)}`, "doubled", 1, `${clip(i.title, 60)} doubled`, `${views.toLocaleString("en-US")} views, up ${pct}% on last week`, now,
          https(i.url) ? {label: "Open the page", type: "url", url: i.url} : {label: "Open analytics", type: "brain", node: "c:" + connKey(c)}, true));
    }
  }

  // 6. A reminder that has just gone overdue.
  const rem = conn(S, "reminders");
  for (const i of (rem && rem.items) || []) {
    const due = t(i.at);
    if (due && due <= now && now - due < OVERDUE_HOURS * 3600e3)
      out.push(ev(`overdue:${i.title}:${i.at}`, "overdue", 1, `Overdue: ${clip(i.title, 70)}`, `It was due ${span(now - due)} ago.`, now, {label: "Open Reminders", type: "brain", node: "c:reminders"}, true));
  }

  // 7. A meeting that starts within 15 minutes (all-day entries do not count).
  const cal = conn(S, "calendar");
  for (const i of (cal && cal.items) || []) {
    const at = t(i.at);
    if (at && at > now && at - now <= MEETING_MINUTES * 60000 && !/all day/i.test(i.sub || ""))
      out.push(ev(`meeting:${i.title}:${i.at}`, "meeting", 3, `${clip(i.title, 60)} starts in ${mins(at - now)} min`, i.sub || "", now, {label: "Open Calendar", type: "brain", node: "c:calendar"}, true));
  }

  // 8. A feed that has stopped refreshing.
  for (const [name, st] of Object.entries(S.integrations || {})) {
    if (st && st.ok === false) {
      const label = (((S.connectors || []).find(c => c && connKey(c) === name) || {}).label) || name.replace(/@(.+)$/, " ($1)");
      out.push(ev(`feed:${name}:${st.error_short}`, "feed-broke", 2, `${label} stopped refreshing`, st.error_short || "It reported an error.", now, {label: "Open " + label, type: "brain", node: "c:" + name}, true));
    }
  }
  out.push(...attentionEvents(cur, now));
  return out.sort((a, b) => b.sev - a.sev || a.id.localeCompare(b.id));
}

// 9 to 11. What my own attention suggests: calm by construction. Each is a single change that shows once (an id per
// pull request or per week), never "live", never on a weekend or with too little data, and each action only opens
// something: the pull request, the Brain's attention panel, or the focus card. Nothing here says what to do.
function attentionEvents(cur, now) {
  const A = cur && cur.attention, out = [];
  if (!A || !A.days || !A.today || !Array.isArray(A.projects)) return out;
  const mon = mondayOf(A.today), dow = weekday(A.today);
  // 9. A project that went quiet while a pull request of it is still open.
  const prs = (cur && cur.prs) || [];
  for (const d of dormant(A.days, A.today, A.projects, A.statuses || {})) {
    const pr = prs.find(p => p.project === d.project);
    if (!pr || d.never) continue;
    out.push(ev(`dormant-pr:${d.project}#${pr.number}`, "dormant-pr", 1, `${d.project} has gone quiet with a pull request open`,
      `No real work for ${d.quiet} working days. #${pr.number} is still open.`, now,
      https(pr.url) ? {label: "Open pull request", type: "url", url: pr.url} : {label: "Pull requests", type: "go", view: "prs", project: d.project}, false));
  }
  // 10. Monday only: no focus yet for this week, or last week's focus against what happened.
  if (dow === 1) {
    const intents = A.intents || [], here = currentIntent(intents, A.today);
    if (!here) out.push(ev(`focus-set:${mon}`, "focus-check", 1, "No focus set for this week", "Pick up to four projects. It is only compared with your own activity, as an estimate.", now, {label: "Open the focus card", type: "focus"}, false));
    const last = currentIntent(intents, addDays(mon, -2));
    const f = last && focusVsReality(last, A.days, addDays(mon, -1));
    const miss = f && f.enough ? f.rows.find(r => r.verdict === "missing" || r.verdict === "under") : null;
    if (miss) out.push(ev(`focus-last:${mon}`, "focus-check", 1, `Last week ${miss.project} got less than you meant`,
      `It took ${band(miss.actual)} of your time, you meant ${band(miss.target)}. An estimate.`, now, {label: "Where my attention goes", type: "attention"}, false));
  }
  // 11. A project that is clearly picking up.
  if (dow >= 2 && dow <= 5) {
    const e = emerging(A.days, A.today)[0];
    if (e) out.push(ev(`emerging:${e.project}:${mon}`, "emerging", 1, `${e.project} is picking up`, `${ratioWord(e.ratio)[0].toUpperCase() + ratioWord(e.ratio).slice(1)} compared with last week. An estimate.`, now,
      {label: "Where my attention goes", type: "attention"}, false));
  }
  return out;
}

// ---- what the page remembers in this browser ----------------------------------
export const emptyStore = () => ({log: [], dismissed: {}, snoozed: {}});

// Remember new events (last 20, newest first), and forget old dismissals and expired snoozes. Pure: returns a new store.
export function ingest(store, events, now = Date.now()) {
  const s = {log: (store && store.log || []).slice(), dismissed: {...(store && store.dismissed)}, snoozed: {...(store && store.snoozed)}};
  const known = new Set(s.log.map(e => e.id));
  for (const e of events) if (!known.has(e.id)) { s.log.unshift(e); known.add(e.id); }
  s.log = s.log.slice(0, KEEP);
  for (const [id, at] of Object.entries(s.dismissed)) if (now - at > 3 * 86400e3) delete s.dismissed[id];
  for (const [id, until] of Object.entries(s.snoozed)) if (until <= now) delete s.snoozed[id];
  return s;
}
export const dismiss = (store, id, now = Date.now()) => ({...store, dismissed: {...store.dismissed, [id]: now}});
export const snooze = (store, id, now = Date.now()) => ({...store, snoozed: {...store.snoozed, [id]: now + SNOOZE_MINUTES * 60000}});

// The one suggestion to show: remembered events that are not dismissed or snoozed, still true if they are state-based
// (live), or younger than six hours if they were a single change. Most important first, then newest.
export function pick(store, currentIds, now = Date.now()) {
  const live = new Set(currentIds);
  return (store.log || []).filter(e => !store.dismissed[e.id] && !(store.snoozed[e.id] > now)
      && (e.live ? live.has(e.id) : now - (t(e.at) || 0) < TTL_HOURS * 3600e3))
    .sort((a, b) => b.sev - a.sev || (t(b.at) || 0) - (t(a.at) || 0))[0] || null;
}

// May Helm read this suggestion aloud now? Off by default, once per suggestion, at most once per five minutes,
// and never while Helm is talking, listening or working.
export function shouldSpeak({enabled, id, spoken = [], lastAt = 0, now = Date.now(), busy = false}) {
  return !!enabled && !!id && !busy && !spoken.includes(id) && now - lastAt >= SPEAK_GAP_MINUTES * 60000;
}
export const spokenText = e => e ? `${e.title}. ${e.why}` : "";
