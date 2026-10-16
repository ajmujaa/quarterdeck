// Pure logic for the Brain's side panel of each connected feed: one line saying what
// changed and what needs you, then the detail (top posts and trend for analytics and
// social, who is waiting for mail and Slack). No DOM, no network: the page passes a
// connector snapshot in, so this can be tested with node (bin/selftest-assistant.mjs).

const ANALYTICS = new Set(["ga4", "analytics"]), INBOX = new Set(["gmail", "slack"]), SOCIAL = new Set(["linkedin", "facebook", "instagram"]);
const num = s => Number(String(s).replace(/,/g, "")) || 0;
const fmt = n => Math.round(n).toLocaleString("en-US");
const short = (s, n) => (String(s || "").length > n ? String(s).slice(0, n - 1) + "…" : String(s || ""));
const when = at => { const t = Date.parse(at); return isNaN(t) ? 0 : t; };
export function age(at, now) {
  const m = Math.round((now - when(at)) / 60000);
  if (!when(at) || m < 0) return "";
  return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago";
}
const pctOf = s => { const m = String(s).match(/([+-]\d+)%/); return m ? Number(m[1]) : null; };
const viewsOf = s => { const m = String(s).match(/([\d,]+) views/); return m ? num(m[1]) : 0; };

function analytics(items) {
  const sum = items.find(i => /^Last 7 days:/.test(i.title));
  const pages = items.filter(i => i !== sum && !/^Source:/.test(i.title)).map(i => ({i, v: viewsOf(i.sub), p: pctOf(i.sub)}))
    .sort((a, b) => b.v - a.v);
  const sources = items.filter(i => /^Source:/.test(i.title));
  const spike = pages.filter(x => x.p !== null && x.p >= 100 && x.v >= 100).sort((a, b) => b.p - a.p)[0];
  const trend = sum ? (/views ([+-]\d+%|new|no change) vs last week/.exec(sum.sub) || [])[1] : null;
  const views = sum ? (/^Last 7 days: ([\d,]+) views/.exec(sum.title) || [])[1] : null;
  let sub, state = "idle";
  if (spike) { sub = `${short(spike.i.title, 60)} is up ${spike.p}% (${fmt(spike.v)} views). Nothing needs you.`; state = "new"; }
  else if (views) sub = `${views} views this week${trend ? ", " + trend + " vs last week" : ""}. Nothing needs you.`;
  else sub = `${items.length} items. Nothing needs you.`;
  const lines = [];
  if (sum) lines.push(sum.title, sum.sub);
  if (pages.length) lines.push("Top pages:", ...pages.slice(0, 5).map((x, n) => `${n + 1}. ${short(x.i.title, 60)}: ${x.i.sub}`));
  if (sources.length) lines.push("Traffic: " + sources.map(s => `${s.title.replace(/^Source: /, "")} ${s.sub.replace(/ sessions$/, "")}`).join(", "));
  return {state, sub, lines, url: sum && sum.url};
}

// Mail and Slack: the items are what is waiting on you. Who they are from is the
// sender (mail, in the sub line) or the title (Slack). Over a day old is red.
function inbox(c, items, now) {
  const slack = c.name === "slack", n = c.unread != null ? c.unread : items.length;
  const who = i => slack ? i.title : i.sub, what = i => slack ? i.sub : i.title;
  const oldest = items.map(i => when(i.at)).filter(Boolean).sort((a, b) => a - b)[0];
  const stale = oldest && now - oldest > 864e5;
  if (!n) return {state: "idle", sub: "Nothing is waiting on you.", lines: []};
  const by = {};
  items.forEach(i => { by[who(i) || "unknown"] = (by[who(i) || "unknown"] || 0) + 1; });
  const lines = [`${n} waiting on you${n > items.length ? `, showing ${items.length}` : ""}:`,
    ...items.slice(0, 6).map(i => `${short(who(i), 40)}: ${short(what(i), 70)}${age(i.at, now) ? " (" + age(i.at, now) + ")" : ""}`)];
  const top = Object.entries(by).sort((a, b) => b[1] - a[1])[0];
  if (top && top[1] > 1) lines.push(`Most from ${top[0]} (${top[1]}).`);
  const first = items[0];
  return {state: stale ? "attn" : "new", lines,
    sub: `${n} waiting on you${first ? `, latest from ${short(who(first), 40)}` : ""}${stale ? ". Oldest is over a day old." : "."}`};
}

// Posts: "12 reactions, 3 comments, 900 impressions" in the sub line. Engagement is
// reactions, likes, comments and shares; impressions and reach are reported apart.
function social(c, items, now) {
  const stats = i => { const o = {}; for (const m of String(i.sub).matchAll(/([\d,]+) (impressions|reactions|likes|comments|shares|reached)/g)) o[m[2]] = num(m[1]); return o; };
  const eng = i => { const s = stats(i); return (s.reactions || 0) + (s.likes || 0) + (s.comments || 0) + (s.shares || 0); };
  const posts = items.slice().sort((a, b) => when(b.at) - when(a.at));
  const fresh = items.filter(i => i.new);
  const top = items.slice().sort((a, b) => eng(b) - eng(a))[0];
  const lines = [];
  if (fresh.length) lines.push("New since you looked:", ...fresh.slice(0, 3).map(i => `${short(i.title, 60)}: ${i.sub}`));
  if (posts[0]) lines.push(`Latest (${age(posts[0].at, now) || "undated"}): ${short(posts[0].title, 60)}: ${posts[0].sub}`);
  if (top && eng(top) > 0) lines.push(`Top post: ${short(top.title, 60)}: ${top.sub}`);
  if (posts.length >= 6) {
    const a = posts.slice(0, 3).reduce((t, i) => t + eng(i), 0), b = posts.slice(3, 6).reduce((t, i) => t + eng(i), 0);
    lines.push(`Trend: the last 3 posts got ${fmt(a)} reactions and comments, the 3 before got ${fmt(b)}${b ? " (" + (a >= b ? "+" : "") + Math.round((a - b) / b * 100) + "%)" : ""}.`);
  }
  const sub = fresh.length ? `${short(fresh[0].title, 60)}: ${fresh[0].sub}. Nothing needs you.`
    : posts[0] ? `Latest post got ${fmt(eng(posts[0]))} reactions and comments${age(posts[0].at, now) ? ", " + age(posts[0].at, now) : ""}. Nothing needs you.` : "No posts yet.";
  return {state: fresh.length ? "new" : "idle", sub, lines};
}

// null for feeds without a panel of their own (calendar, reminders, Drive): the page keeps its item dots.
export function feedPanel(c, now = Date.now()) {
  if (!c || !c.connected) return null;
  const items = Array.isArray(c.items) ? c.items : [];
  if (ANALYTICS.has(c.name)) return analytics(items);
  if (INBOX.has(c.name)) return inbox(c, items, now);
  if (SOCIAL.has(c.name)) return social(c, items, now);
  return null;
}
