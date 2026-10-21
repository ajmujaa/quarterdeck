// The live-work and Crew pages under node, with no browser: the real helpers and page functions are cut out of dashboard/index.html and rendered with fixture
// data (a session working, one waiting for the owner, one idle, one finished, a duty, a worktree with a draft pull request, text from the hook that is hostile).
// What it proves: the lines say what the data says and "no detail reported" where the hook gave none; text from the hook is escaped, never markup; the empty and
// "hook not installed" wording is there; the Crew page puts enabled agents first, folds the rest into "Available (N)" with an Enable button, and counts
// sessions and duties by their own names. The browser half (bin/live-page.mjs) drives the same pages in a real browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import {fileURLToPath} from "node:url";

const html = fs.readFileSync(fileURLToPath(new URL("../dashboard/index.html", import.meta.url)), "utf8");
const between = (a, b) => { const i = html.indexOf(a), j = html.indexOf(b, i); assert.ok(i > 0 && j > i, a); return html.slice(i, j); };
const crew = await import(new URL("../dashboard/assets/crew.js", import.meta.url).href);
const src = [
  between("const esc = s =>", "let ACT_EV = null"), between("let ACT_EV = null", "// click, keydown, submit"),
  between("const plural =", "let S = null"),
  html.split("\n").find(l => l.startsWith("const agoS = ")),
  between("const NO_DETAIL =", "function viewCommandCenterNew"),
  between("const crewRank =", "function crewFilterSet"),
].join("\n");
const page = new Function("CREW", `let S = null, sel = "", crewFilter = "all", filter = "";
const fleetOpen = new Set(), elapsedSpan = s => "<span>" + s + "</span>", verdictClass = v => v === "ERROR" ? "bad" : "", ago = () => "1m ago", ownAgents = () => "";
const crewMod = CREW, go = () => {}, openProjects = () => {};
${src}
return {set(s, c) { S = s; sel = c.sel || ""; crewFilter = c.filter || "all"; }, runningStrip, liveWorkCard, viewCrew, liveHeader, fleetOpen};`)(crew);

const EVIL = "<img src=x onerror=alert(1)>";
const item = (o) => ({kind: "session", project: "alpha", source: "alpha", branch: "feat/export", worktree: "alpha-feat", agent: "no detail reported", doing: "no detail reported", since: "", minutes: 3,
  waiting_on_owner: false, state: "working", pr: null, ...o});
const live = (o = {}) => ({hook_installed: true, install_command: "bash /x/bin/fleet-hook.sh install", sources: [], updated_at: new Date(Date.now() - 120000).toISOString(), worktrees: [], items: [], ...o});
const items = [
  item({agent: "reviewer", doing: "Running the reviewer agent", pr: {number: 12, draft: true, url: "https://github.com/x/alpha/pull/12"}}),
  item({kind: "duty", worktree: "", branch: "", agent: "shipwright", doing: "issue #7, Add export", source: ""}),
  item({project: "beta", branch: "main", worktree: "beta", doing: "Answering a prompt", minutes: 1}),
  item({state: "idle", waiting_on_owner: true, branch: "main", worktree: "alpha", doing: "Finished its turn", minutes: 19}),
  item({state: "idle", branch: EVIL, worktree: "w2", minutes: 40}),
  item({state: "idle", project: "", worktree: "scratch", branch: "", minutes: 90}),
  item({state: "finished", branch: "old/branch", worktree: "gone", doing: "The session ended", minutes: 120}),
];
const trees = [
  {project: "alpha", name: "alpha-feat", branch: "feat/export", main: false, stage: "draft", activity: "active", changed: 0, last_activity_ago: 240, session: {id: "s1", state: "working"},
   pr: {number: 12, draft: true, url: "https://github.com/x/alpha/pull/12", state: "open", title: "Add export"}},
  {project: "alpha", name: "alpha-spike", branch: "spike/x", main: false, stage: "working", activity: "active", changed: 2, last_activity_ago: 900, session: null, pr: null},
  {project: "alpha", name: "alpha", branch: "main", main: true, stage: "clean", activity: "active", changed: 0, last_activity_ago: 7200, session: null, pr: null},
  {project: "beta", name: "beta", branch: "main", main: true, stage: "clean", activity: "old", changed: 0, last_activity_ago: 900000, session: {id: "s3", state: "working"}, pr: null},
];
const names = Object.keys(crew.INFO);
const enabled = names.filter(n => n !== "inspector").slice(0, 4);
const S = {projects: [{name: "alpha", suggested: [{duty: "inspector", why: `fits ${EVIL}`}], duties: enabled}, {name: "beta", suggested: [], duties: []}],
  duties: names.map(n => ({name: n, role: n + " does a job."})),
  agents: enabled.map(n => ({project: "alpha", duty: n, role: "", status: n === enabled[0] ? "running" : "idle", since: "2026-01-01T00:00:00Z", what: "x", lock: n + "-alpha", last_at: null, last_verdict: null})),
  live: live({items, worktrees: trees})};
const flat = h => h.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ");

// ---- the Running now strip ----
page.set(S, {});
let h = page.runningStrip(), t = flat(h);
assert.ok(h.includes('aria-label="Running now"') && t.includes("Live data updated 2 minutes ago"), "the strip is a labelled card with the header line");
assert.ok(t.includes("alpha session") && t.includes("Agent: reviewer") && t.includes("Running the reviewer agent") && t.includes("draft PR #12"), "a working session: project, kind, agent, what it is doing, draft pull request");
assert.ok(t.includes("alpha duty") && t.includes("Duty: shipwright") && t.includes("issue #7, Add export"), "a duty is named a duty and shows the run's own words");
assert.ok(t.includes("Agent: no detail reported") && t.includes("Answering a prompt"), "where the hook gave nothing, the line says no detail reported and never invents");
assert.ok(t.includes("waiting for you") && t.includes("Finished its turn"), "a session whose turn finished is waiting for the owner");
assert.ok(h.includes('summary="2 idle sessions"'), "the quiet ones are folded into one line: 2 idle sessions");
assert.ok(!t.includes("The session ended") && !t.includes("old/branch"), "finished sessions are not shown");
assert.ok(t.includes("Not in a registered project."), "a session that matches no project says so");
assert.ok(t.indexOf("Running the reviewer agent") < t.indexOf("Finished its turn"), "working comes before waiting");
assert.ok(!h.includes("<img") && h.includes("&lt;img"), "text from the hook is escaped, never markup");
assert.ok(t.includes("Open the full fleet view"), "the full fleet view is one click away");
page.set({...S, live: live({items: []})}, {});
t = flat(page.runningStrip());
assert.ok(t.includes("Nothing is running right now.") && !t.includes("not installed"), "empty says so");
page.set({...S, live: live({items: [], hook_installed: false, updated_at: null})}, {});
t = flat(page.runningStrip());
assert.ok(t.includes("Nothing is running right now.") && t.includes("No live data: the sessions hook is not installed. Install it with: bash /x/bin/fleet-hook.sh install"), "no hook: the plain line and the exact command");
page.set({...S, live: live({items: [], hook_installed: false})}, {});
assert.ok(flat(page.liveHeader()).includes("not installed") && flat(page.liveHeader()).includes("last update was 2 minutes ago"), "no hook but old data: both facts");

// ---- the Live work card ----
page.set(S, {sel: "alpha"});
h = page.liveWorkCard("alpha"); t = flat(h);
assert.ok(h.includes('id="live-work"') && h.includes('aria-label="Live work"'), "the card has its anchor");
assert.ok(t.includes("feat/export") && t.includes("Draft pull request #12 Add export (open)") && t.includes("Session working") && t.includes("draft pull request"), "a worktree shows its branch, state, draft pull request and the session in it");
assert.ok(t.includes("spike/x") && t.includes("Nobody working in it") && t.includes("2 changed files"), "a worktree nobody works in says so");
assert.ok(t.includes("Duty: shipwright") && h.includes('summary="1 quiet worktree"'), "running duties are listed and the clean checkout is folded");
assert.ok(!t.includes("beta"), "only the chosen project");
page.set(S, {});
h = page.liveWorkCard(""); t = flat(h);
assert.ok(h.includes('data-live-project="alpha"') && h.includes('data-live-project="beta"') && h.includes('data-live-project=""'), "all projects: one heading per project, and Other");
assert.ok(t.includes("Other (not in a registered project)"), "Other says what it is");
page.set({...S, live: live({})}, {});
assert.ok(flat(page.liveWorkCard("alpha")).includes("Nothing is in flight in this project."), "an empty project says so");

// ---- the Crew page ----
page.set(S, {sel: "alpha"});
h = page.viewCrew(); t = flat(h);
const rows = (h.match(/class="crew-row /g) || []).length;
assert.equal(rows, enabled.length, "only the enabled agents are full rows");
const avail = names.length - enabled.length;
assert.ok(h.includes(`summary="Available (${avail})"`) && h.indexOf("crew-row") < h.indexOf("summary=\"Available ("), "the rest are folded under Available (N), after the enabled agents");
assert.ok(!t.includes("How to enable it") && !t.includes("Not enabled for this project"), "no wall of 'not enabled' lines");
assert.equal((h.match(/data-enable="/g) || []).length, avail, "every available agent has an Enable button");
assert.ok(h.includes('aria-label="Enable the inspector for alpha"') && h.indexOf('data-avail="inspector"') < h.indexOf('data-avail="' + names.filter(n => !enabled.includes(n) && n !== "inspector")[0] + '"'), "the scan's suggestion comes first");
assert.ok(t.includes("Suggested for this project: fits") && !h.includes("<img") && h.includes("&lt;img"), "the reason is shown, escaped");
assert.ok(t.includes("1 session") && t.includes("1 duty"), "Running now counts sessions and duties by their own names");
assert.ok(h.includes('data-on-click="liveJump"'), "the sessions number goes to the project's live work");
page.set({...S, live: live({items: []})}, {sel: "alpha"});
t = flat(page.viewCrew());
assert.ok(t.includes("0 sessions") && t.includes("1 duty"), "no session working: 0 sessions");
page.set(S, {});
h = page.viewCrew();
assert.ok(h.includes("summary=\"Available (") && !h.includes("data-enable="), "all projects: the not-enabled ones are folded too, with no Enable button (it needs a project)");
console.log("  ok    live work and Crew under node: lines, 'no detail reported', escaping, empty and no-hook wording, Available (N) folded with Enable buttons, sessions and duties counted apart");
