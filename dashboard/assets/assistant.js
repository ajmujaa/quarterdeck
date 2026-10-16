// Pure logic for the Home "Next up" card, the "while you were away" digest and the
// voice/typed command bar. No DOM, no network: the page passes plain data in and
// does the acting itself, so this can be tested with node (bin/selftest.py).

import {ordinal} from "./notes.js";

const BAD = new Set(["ERROR", "FAILED", "BLOCKED", "BROKEN"]);
const routine = r => r.verdict === "DRY-RUN" && /(^|\s)0 finding/.test(r.detail || "");
const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const clean = s => String(s || "").replace(/https?:\/\/\S+\/pull\/(\d+)/g, "PR #$1").replace(/\s+—\s+/g, " ");

// The one thing to do next. Order is the point: something broken, then something
// waiting for you, then "nothing needs you" so a quiet screen is read as quiet.
export function nextUp({attention = [], runs = [], agents = [], prs = [], projects = null, now = Date.now()}) {
  // A fresh install has nothing to look at: the one next step is to add a project (or try the demo).
  if (Array.isArray(projects) && !projects.length) return {title: "Add your first project.", why: "Name a folder and Quarterdeck reads what is in it, changes nothing, and asks before it adds it. Or press Demo to look around with made-up data.", label: "Add a project", act: "attach"};
  const bad = attention.find(x => x.kind === "bad");
  if (bad) return {title: short(`${bad.source}: ${clean(bad.text)}`, 150), why: "Marked as needing you.", label: "Open it", go: bad.view};
  const cutoff = now - 6 * 3600e3, seen = new Set();
  for (const r of runs) {                        // newest first: a later success ends the story
    const k = r.project + "|" + r.duty;
    if (new Date(r.at) < cutoff) break;
    if (seen.has(k)) continue;
    seen.add(k);
    if (BAD.has(r.verdict)) return {title: `${r.duty} failed on ${r.project}`, why: short(clean(r.detail || "No detail recorded."), 140), label: "See why", go: "ledger", project: r.project};
  }
  const pr = prs.find(p => p.by_quarterdeck && !p.draft && p.checks && !p.checks.fail && !p.checks.pending);
  if (pr) return {title: `Review PR #${pr.number} on ${pr.project}`, why: short(pr.title, 120) + ". Its checks pass.", label: "Open on GitHub", url: pr.url};
  const warn = attention.find(x => x.kind === "warn");
  if (warn) return {title: short(`${warn.source}: ${clean(warn.text)}`, 150), why: "Worth a look, not urgent.", label: "Open it", go: warn.view};
  const live = agents.filter(a => a.status === "running");
  if (live.length) return {title: "Nothing needs you. The crew is working.", why: live.map(a => `${a.project} ${a.duty}`).join(", ") + ".", label: "Watch", go: "operations"};
  return {title: "Nothing needs you. Pick one thing to start.", why: "The board lists what is open on each project.", label: "Open the board", go: "board"};
}

// What changed since you were last here, for someone who loses track of time.
export function awayDigest(runs, since, now = Date.now()) {
  const from = since ? new Date(since).getTime() : now - 12 * 3600e3;
  const rows = runs.filter(r => new Date(r.at).getTime() > from && !routine(r));
  const failed = rows.filter(r => BAD.has(r.verdict)).length;
  const prs = rows.filter(r => r.verdict === "PR").length;
  const capped = runs.length >= 80 && new Date(runs[runs.length - 1].at).getTime() > from;
  const lines = rows.slice(0, 4).map(r => `${r.project} ${r.duty} ${String(r.verdict || "").toLowerCase()}${r.detail ? " · " + short(clean(r.detail), 70) : ""}`);
  return {total: rows.length, failed, prs, lines, fresh: !since, capped};
}

export function runningLines(agents, now = Date.now()) {
  return agents.filter(a => a.status === "running").map(a => {
    const m = a.since ? Math.max(0, Math.round((now - new Date(a.since)) / 60000)) : null;
    const what = clean(a.what || "").replace(/^issue\s+/, "");
    return `${a.project}: ${a.duty}${what ? " on " + short(what, 80) : ""}${m === null ? "" : `, ${m} minute${m === 1 ? "" : "s"} in`}`;
  });
}

const norm = s => String(s).toLowerCase().replace(/[^a-z0-9#\s-]/g, " ").replace(/\s+/g, " ").trim();
const spaced = s => s.replace(/-/g, " ");

// Duties Helm may start by voice: each runs with no input beyond an optional pull request number
// (inspector needs one). The server keeps its own copy of this list (VOICE_DUTIES in dashboard.py).
export const RUN_DUTIES = ["surveyor", "joiner", "harbourmaster", "inspector"];
export const STOP_WORDS = new Set(["the", "a", "an", "my", "job", "jobs", "now", "signal", "signals", "that", "it", "this", "please"]);
// Add-ons (assets/ext-*) extend Helm through these, each a mutable list or set that is empty without one: rules tried at two
// points of parseCommand ((t, ctx) => an intent or null; ctx has the views, and for "late" the phrase `tn` and `words`), words an
// acknowledgement keeps in its query.
export const RULES = {early: [], late: []};
export const ACK_KEEP = new Set();
const stem = w => w.slice(0, Math.max(4, w.length - 2));

// Fuzzy "which one did you mean": every word said must appear in the name. One hit wins; an exact
// name beats a partial one; otherwise the page asks, naming what matched.
export function pickByName(query, items, nameOf) {
  const toks = norm(query).split(" ").filter(w => w && !STOP_WORDS.has(w));
  if (!toks.length) return {none: true, empty: true};
  const hits = items.filter(i => { const n = spaced(norm(nameOf(i))); return toks.every(w => n.includes(stem(w))); });
  if (hits.length === 1) return {match: hits[0]};
  const exact = hits.filter(i => spaced(norm(nameOf(i))) === toks.join(" "));
  if (exact.length === 1) return {match: exact[0]};
  return hits.length ? {ambiguous: hits} : {none: true};
}

// The text of a spoken plan, made safe to hand to a duty as one argument: no characters outside plain
// words, and never a leading dash, so it cannot be read as a flag (an idea of "--apply" is just "apply").
export const cleanIdea = s => String(s || "").replace(/[^\w .,#:@+=-]/g, " ").replace(/\.{2,}/g, " ").replace(/^[\s\/-]+/, "").trim().slice(0, 200);

// Words in, one plain intent out. Anything that changes something returns
// confirm:true and the page asks for a click; voice never skips that.
export function parseCommand(text, {views = [], projects = [], duties = RUN_DUTIES} = {}) {
  let t = norm(text).replace(/^(hey |ok |okay )?(helm|quarterdeck)[ ,]*/, "").replace(/^(please |can you |could you )+/, "").trim();
  if (!t) return {intent: "empty"};
  let m;
  if (/^(stop|cancel|never mind|be quiet|quiet)$/.test(t)) return {intent: "stop"};
  // Conversation switches. All of them only change how Helm talks; none changes anything on the dashboard.
  if (/^(?:think with me|let s think(?: about (.+?))?(?: with me)?|think about (.+?) with me)$/.test(t)) {
    const m2 = t.match(/^(?:let s think about (.+?)(?: with me)?|think about (.+?) with me)$/);
    return {intent: "deep", on: true, topic: m2 ? (m2[1] || m2[2]) : ""};
  }
  if (/^(?:back to normal|that s enough)$/.test(t)) return {intent: "deep", on: false};
  if (/^(?:start over|forget (?:that|all that|this)|new conversation|clear the conversation)$/.test(t)) return {intent: "reset"};
  if ((m = t.match(/^include my (agenda|calendar|notes)$/))) return {intent: "include", what: m[1] === "notes" ? "notes" : "agenda"};
  if (/^(?:that s all|that is all|thats all|that will be all)$/.test(t)) return {intent: "bye"};
  if ((m = t.match(/^let s (?:talk|chat) about (.+)$/))) return {intent: "talk", topic: m[1]};
  if (/^(help|what can you do|commands)$/.test(t)) return {intent: "help"};
  if ((m = t.match(/^(?:remember|note|capture|jot down|jot|add a note|add a thought|remind me)(?: that| to)? (.+)/)))
    return {intent: "capture", text: String(text).replace(/^\s*(hey |ok |okay )?(helm|quarterdeck)?[ ,]*(please )?(remember|note|capture|jot down|jot|add a note|add a thought|remind me)( that| to)?\s*/i, "").trim() || m[1]};
  if (/^(?:brief me|catch me up|what did i miss|what s new|what is new|summary)$|while i was away/.test(t)) return {intent: "brief"};
  if (/^(?:what s |what is |whats )?(?:on )?(?:my )?(?:agenda|schedule|calendar)(?: today)?$|^what s on(?: my day| today)?$|^what do i have (?:on )?today$/.test(t)) return {intent: "agenda"};
  if (/^(?:what s |what is |whats )?(?:on )?(?:my )?reminders?$|^what do i need to remember$|^what am i forgetting$/.test(t)) return {intent: "reminders"};
  if (/^(?:what s |what is |whats )?(?:running|happening|going on)(?: now| right now)?$|^who s working$|^status$/.test(t)) return {intent: "running"};
  if (/^(?:what s |what is |whats )?next(?: up)?$|^what should i do(?: next)?$|^what needs me$|^what do i need(?: to do)?$|^next (?:action|thing)$/.test(t)) return {intent: "next"};
  for (const rule of RULES.early) { const got = rule(t, {views}); if (got) return got; }
  const byLen = projects.slice().sort((a, b) => b.length - a.length);
  const proj = tt => byLen.find(p => tt.includes(spaced(p)) || tt.includes(p));
  // Attention: reading the focus is free; setting it asks for a click. A model may suggest reading it, never setting it.
  if (/^(?:what s |what is |whats )?(?:my )?focus(?: this week| for the week| for this week| now)?$|^what am i (?:focused on|focusing on)(?: this week)?$/.test(t)) return {intent: "focus"};
  if ((m = t.match(/^(?:(?:set|change|update|make) my focus (?:to|on|as)|focus on) (.+?)(?: (?:for )?(this|next) week)?$/))) {
    // Names are matched anywhere in the phrase (punctuation is already gone), longest first, in the order spoken.
    let rest = m[1];
    const hits = [];
    for (const p of byLen) {
      const i = Math.max(rest.indexOf(spaced(p)), rest.indexOf(p));
      const w = rest.indexOf(spaced(p)) >= 0 ? spaced(p) : p;
      if (i >= 0 && rest.indexOf(w) >= 0) { hits.push([rest.indexOf(w), p]); rest = rest.replace(w, "|"); }
    }
    const found = hits.sort((x, y) => x[0] - y[0]).map(h => h[1]).filter((n, i, a) => a.indexOf(n) === i);
    const unknown = rest.split("|").map(x => x.replace(/^(?:\s|and\b)+|(?:\s|and\b)+$/g, "").trim()).filter(Boolean);
    return {intent: "focusset", projects: found, unknown, week: m[2] || "this", confirm: true};
  }
  if (/^(?:which|what) projects (?:are|have gone) (?:dormant|quiet)$|^what(?: has| s) gone quiet$|^what is dormant$|^(?:the )?dormant projects$/.test(t)) return {intent: "dormant"};
  if (/^(?:what|which projects?) (?:is|are|s) (?:emerging|picking up)$|^what s emerging$|^(?:the )?emerging projects$/.test(t)) return {intent: "emerging"};
  if (/^(?:how was my week|how did my week go|how s my week going|where did my (?:time|week) go)$/.test(t)) return {intent: "week"};
  if ((m = t.match(/^(park|archive|unpark|continue(?: with)?|bring back) (?:the )?(.+)$/)) && proj(m[2]))
    return {intent: "parkproject", status: m[1] === "park" ? "park" : m[1] === "archive" ? "archive" : "continue", project: proj(m[2]), confirm: true};
  // My rhythm, read aloud from the owner's own task titles (local; a model may not suggest these, see ACTION_INTENTS).
  const WHEN = "this morning|this afternoon|this evening|today|yesterday(?: morning| afternoon| evening)?";
  if ((m = t.match(new RegExp(`^what (?:was|were) i (?:working on|doing)(?: (${WHEN}))?$|^what did i (?:do|work on)(?: (${WHEN}))?$|^what have i been (?:working on|doing)(?: (today))?$`)))) {
    const w = m[1] || m[2] || m[3] || "today", y = w.startsWith("yesterday"), part = (w.match(/morning|afternoon|evening/) || [null])[0];
    return {intent: "worked", day: y ? "yesterday" : "today", part};
  }
  if ((m = t.match(/^when did i (?:last )?(?:touch|work on|open|look at|commit to|commit on)(?: last)? (.+)$/)) || (m = t.match(/^when did i last (?:touch|work on) (.+)$/)))
    return {intent: "lasttouch", project: proj(m[1]) || null, query: m[1]};
  // Planning: a draft is free; "and get the panel to look at it" adds a second, separate confirm.
  if ((m = t.match(/^(?:plan|draft a plan for|make a plan for|draft a mission for)(?: for)? (.+)/))) {
    let rest = m[1];
    const panel = /\s+and (?:get|have|ask|let) the (?:dev |design |spec )?panel (?:to )?(?:look at|review|weigh in on|think about|take a look at)(?: it| that| this)?$/.test(rest);
    rest = rest.replace(/\s+and (?:get|have|ask|let) the (?:dev |design |spec )?panel .*$/, "");
    const project = proj(rest);
    if (project) rest = rest.replace(new RegExp(`\\s+(?:for|on|in|of)\\s+(?:the\\s+)?(?:${spaced(project)}|${project})$`), "");
    return {intent: "plan", objective: rest.trim(), project: project || null, panel, confirm: true};
  }
  if (/^what did the (?:dev |design |spec )?panel say(?: about .+)?$/.test(t)) return {intent: "panelsay", query: t.replace(/^what did the (?:dev |design |spec )?panel say(?: about)?\s*/, ""), project: proj(t) || null};
  if (/^(?:what s |what is |whats |what are )?(?:my )?open missions$|^(?:list )?(?:my )?missions$/.test(t)) return {intent: "missions"};
  // Notes (the brain dump): reading them out asks for no click; marking one done or promoting one does.
  const ORD = "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|one|two|three|four|five|six|seven|eight|nine|ten|\\d{1,2}(?:st|nd|rd|th)?";
  if (/^(?:list|read|show|what are|what s in)(?: me| out)?(?: all)?(?: my)? (?:open )?(?:notes|brain dump)$|^(?:my )?notes$|^what notes do i have$/.test(t)) return {intent: "notes"};
  if ((m = t.match(new RegExp(`^(?:turn|make|promote|convert) (?:the )?(?:(${ORD}) note|note (${ORD})) (?:in)?to (?:a |an )?(plan|mission)(?: (?:for|on|in) (?:the )?(.+))?$`)))) {
    const n = ordinal(m[1] || m[2]);
    return {intent: "promote", n, kind: m[3], project: m[4] ? proj(m[4]) || null : null, confirm: true};
  }
  if ((m = t.match(new RegExp(`^(?:mark|set|tick) (?:the )?(?:(${ORD}) note|note (${ORD})|(.+?) note) (?:as )?(?:done|finished|complete)$|^(?:finish|close|complete) (?:the )?(?:(${ORD}) note|note (${ORD})|(.+?) note)$`)))) {
    const ord = m[1] || m[2] || m[4] || m[5], query = m[3] || m[6] || "";
    return ord ? {intent: "notedone", n: ordinal(ord), query: "", confirm: true} : {intent: "notedone", n: null, query: norm(query).split(" ").filter(w => w && !STOP_WORDS.has(w)).join(" "), confirm: true};
  }
  // Duties: stop one that is running, start one that is safe to start from a sentence.
  const duty = w => duties.includes(w) ? w : null;
  if ((m = t.match(/^(?:stop|halt|kill|cancel) (?:the )?([a-z]+)(?: (?:on|for) (.+))?$/)) && duty(m[1]))
    return {intent: "halt", duty: m[1], project: proj(m[2] || "") || null, confirm: true};
  const apply = /\s+and apply(?: it| that| them)?$/.test(t), tn = t.replace(/\s+and apply(?: it| that| them)?$/, "");
  let ran = null;
  if ((m = tn.match(/^(?:run|start|kick off|launch) (?:the )?([a-z]+)(?: (.*))?$/)) && RUN_DUTIES.includes(m[1]) && duty(m[1])) ran = [m[1], m[2] || ""];
  else if ((m = tn.match(/^review (?:the )?((?:pull request|pr)\b.*)$/))) ran = ["surveyor", m[1]];
  if (ran) {
    const pr = ran[1].match(/\b(?:pull request|pr) #?(\d+)/);
    return {intent: "run", duty: ran[0], project: proj(ran[1]) || null, pr: pr ? Number(pr[1]) : null, apply, confirm: true};
  }
  const words = (q, keep) => norm(q).split(" ").filter(w => w && !(STOP_WORDS.has(w) && !(keep && ACK_KEEP.has(w)))).join(" ");
  for (const rule of RULES.late) { const got = rule(t, {tn, words}); if (got) return got; }
  if ((m = t.match(/^(?:dismiss|acknowledge|acknowledge|ack|clear)(?: the)? (.+)$/)))
    return {intent: "ack", query: words(m[1], true), confirm: true};
  if ((m = t.match(/^(start|begin|analyse|analyze)(?: work)?(?: on)?(?: issue)? #?(\d+)\b(.*)/))) {
    const project = proj(m[3]);
    return {intent: "work", action: m[1] === "start" || m[1] === "begin" ? "start" : "analyse", issue: Number(m[2]), project: project || null, confirm: true};
  }
  if ((m = t.match(/^(?:open|show me|show|go to|take me to|switch to|view)(?: the| my)? (.+)/))) {
    const what = m[1].replace(/ (page|view|tab)$/, "");
    const view = views.find(v => norm(v.label) === what || v.id === what || norm(v.label) + "s" === what);
    if (view) return {intent: "go", view: view.id};
    const p = proj(what);
    if (p) return {intent: "project", project: p};
    return {intent: "find", query: what.replace(/ in (the )?brain$/, "")};
  }
  if ((m = t.match(/^(?:find|where is|where s|locate|search for|search)(?: the| my)? (.+)/))) return {intent: "find", query: m[1].replace(/ in (the )?brain$/, "")};
  return {intent: "unknown", heard: t};
}

// An ACTION: phrase from a conversation brain may only become one of these. It goes through the same pipeline as a typed
// command (parse, vet, a click for anything that changes something), and it can never save a note by itself ("capture"
// writes at once), switch the deep brain on, change the conversation, or stop Helm speaking.
export const ACTION_INTENTS = new Set(["running", "next", "brief", "agenda", "reminders", "go", "project", "find", "missions", "notes", "panelsay", "focus", "dormant", "emerging", "week",
  "work", "run", "halt", "ack", "plan", "promote", "notedone"]);
export const WRITES_NEED_CLICK = new Set(["work", "run", "halt", "ack", "plan", "promote", "notedone"]);
export function actionAccepted(cmd) {
  return !!cmd && ACTION_INTENTS.has(cmd.intent) && (!WRITES_NEED_CLICK.has(cmd.intent) || cmd.confirm === true || cmd.confirm === undefined && !cmd.intent);
}
// Pull the phrase out of a model's reply line: only a line that starts ACTION: counts.
export function actionLine(text) {
  const m = /^\s*ACTION\s*:\s*(.{1,120}?)\s*$/i.exec(String(text || ""));
  return m ? m[1].replace(/[.\s]+$/, "") : "";
}

export const HELP = "Try: what is on today, my reminders, what is running, what is next, brief me, remember to call the dentist, open the ledger, open wayfarer mobile, find the memory about Brand, start work on issue 13 on wayfarer mobile, list my notes, mark the dentist note done, turn the second note into a plan for wayfarer mobile, run the surveyor on wayfarer mobile, stop the shipwright on wayfarer mobile, plan offline mode for wayfarer mobile, what are my open missions, how was my week, which projects are dormant, what is my focus this week.";

// Calendar and Reminders arrive as snapshots {title, sub, at}; these only read them.
const dayKey = d => d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate();
const clock = iso => new Date(iso).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", hour12: false});

// The same event on two calendars is one event: same normalised title, same start, same all-day-ness.
// (The server merges these too; this keeps Helm from reading one twice if an old snapshot slips through.)
export function dedupeEvents(items = []) {
  const seen = new Map(), out = [];
  for (const i of items) {
    if (!i || !i.at) { out.push(i); continue; }
    const key = [String(i.title || "").toLowerCase().split(/\s+/).filter(Boolean).join(" "), Date.parse(i.at) || i.at, /all day/i.test(i.sub || "")].join("|");
    if (seen.has(key)) { const k = seen.get(key); if (Date.parse(i.at) < Date.parse(k.at)) k.at = i.at; continue; }
    const copy = {...i}; seen.set(key, copy); out.push(copy);
  }
  return out;
}

export function agendaFor(items = [], now = Date.now(), offset = 0) {
  const day = new Date(now); day.setDate(day.getDate() + offset);
  return dedupeEvents(items).filter(i => i && i.at && dayKey(new Date(i.at)) === dayKey(day))
    .sort((a, b) => new Date(a.at) - new Date(b.at))          // all-day entries sit at midnight, so they lead
    .map(i => ({title: i.title, time: /all day/i.test(i.sub || "") ? "all day" : clock(i.at)}));
}

export function agendaText(items, now = Date.now()) {
  const part = (label, rows) => rows.length ? `${label}: ` + rows.map(r => `${r.time} ${r.title}`).join("; ") + "." : "";
  const today = agendaFor(items, now, 0), tomorrow = agendaFor(items, now, 1);
  if (!today.length && !tomorrow.length) return "Nothing on your calendar today or tomorrow.";
  return [today.length ? part("Today", today) : "Nothing else today.", part("Tomorrow", tomorrow)].filter(Boolean).join(" ");
}

export function remindersSummary(items = [], now = Date.now()) {
  const dated = items.filter(i => i.at), today = dayKey(new Date(now));
  const overdue = dated.filter(i => new Date(i.at).getTime() < now && dayKey(new Date(i.at)) !== today);
  const dueToday = dated.filter(i => dayKey(new Date(i.at)) === today);
  return {overdue, dueToday, undated: items.length - dated.length};
}

export function remindersText(items, now = Date.now()) {
  if (!items.length) return "No open reminders.";
  const r = remindersSummary(items, now);
  const bits = [r.overdue.length && `${r.overdue.length} overdue`, r.dueToday.length && `${r.dueToday.length} due today`, r.undated && `${r.undated} with no date`].filter(Boolean);
  const first = (r.overdue[0] || r.dueToday[0] || items[0]).title;
  return `${bits.join(", ") || items.length + " coming up"}. First: ${first}.`;
}

// Written text is not what you want to hear: ids, arrows and urls are read as words,
// and only the first few sentences are spoken (the full text stays on screen).
export function speakable(text, maxSentences = 3, maxChars = 340) {
  let t = String(text || "")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\bPR #(\d+)/gi, "pull request $1")
    .replace(/#(\d+)/g, "number $1")
    .replace(/\b([A-Za-z]+)-([A-Za-z]+)\b/g, "$1 $2")
    .replace(/\s*[·→]\s*/g, ", ")
    .replace(/…/g, "")
    .replace(/\s+/g, " ").trim();
  t = t.split(/(?<=[.!?])\s+/).slice(0, maxSentences).join(" ").trim();     // a full stop inside 3.50 or v2.1 is not a sentence end
  return t.length > maxChars ? t.slice(0, maxChars).replace(/\s+\S*$/, "") + "." : t;
}

// "Helm, what is running" -> {woke: true, rest: "what is running"}. Speech to text
// often hears the name as elm, hem, held or "tell 'em", so those count.
export function stripWake(text) {
  const m = String(text).match(/^\s*(?:hey |hi |ok |okay |to his |the )?(?:helm|elm|hem|held|hell|healm|tell ?'?em)\b[\s,.!?:;'-]*/i);
  return m ? {woke: true, rest: String(text).slice(m[0].length).trim()} : {woke: false, rest: String(text).trim()};
}
