// projects-page.mjs: the browser half of bin/selftest-projects.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_T its
// throwaway Quarterdeck, QD_MODE "real" for the seeded data folder or "demo" for Demo mode, QD_SHOTS where the pictures go) in headless Chromium and prints one
// line per check: "ok ...", "FAIL ..." or "skip ...". Nothing here goes to the internet, and nothing real is touched.
//   node bin/projects-page.mjs probe     exit 0 when a browser can start here, 3 when none can
import {createRequire} from "node:module";
import path from "node:path";

function load() {
  const req = createRequire(import.meta.url), tries = [];
  if (process.env.QD_PLAYWRIGHT_PATH) tries.push(createRequire(path.join(process.env.QD_PLAYWRIGHT_PATH, "x.js")));
  tries.push(req);
  for (const r of tries) for (const n of ["playwright", "playwright-core"]) { try { return r(n); } catch (e) { /* next */ } }
  return null;
}
const pw = load();
if (!pw) { console.log("skip no playwright here"); process.exit(3); }
let browser;
try { browser = await pw.chromium.launch({headless: true, ...(process.env.QD_CHROME ? {executablePath: process.env.QD_CHROME} : {})}); }
catch (e) { console.log("skip no browser: " + String(e.message).split("\n")[0]); process.exit(3); }
if (process.argv[2] === "probe") { await browser.close(); process.exit(0); }

const SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK, MODE = process.env.QD_MODE === "demo" ? "demo" : "real", TAG = MODE === "demo" ? "demo: " : "real data: ";
const BASE = new URL(LINK).origin + "/";
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + TAG + label); else { bad++; console.log("FAIL " + TAG + label + (extra !== undefined ? " | " + String(extra).slice(0, 500) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const problems = {console: [], page: [], requests: []};
const page = await ctx.newPage();
page.on("console", m => { if (m.type() === "error" && !/Failed to load resource.*status of 404/.test(m.text())) problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });
page.on("response", r => { if (r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({path: path.join(SHOTS, MODE + "-" + name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const snap = () => page.evaluate(() => ({hash: location.hash, len: history.length, qd: history.state && history.state.qd, view, sel, keptSel, atPlace, scopeAddon, title: document.querySelector("#ptitle").textContent.trim(),
  chip: (document.querySelector("#pscope .scope-chip") || {}).innerText || "", pick: document.querySelector("#proj-switch").value, pickHidden: document.querySelector("#proj-switch").hidden}));
const ready = () => page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && S.overview && document.querySelector("#view") && document.querySelector("#view").children.length > 0 && !!document.querySelector("#ptitle").textContent.trim(), null, {timeout: 30000});
const rail = label => page.locator(`#dock-links button.rail-btn[aria-label^="${label}"]`).click();
const tab = id => page.locator(`#ptabs sl-tab[panel="${id}"]`).click();
const back = async () => { await page.goBack().catch(() => null); await sleep(450); };
const forward = async () => { await page.goForward().catch(() => null); await sleep(450); };
const visible = sel => page.locator(sel).first().isVisible().catch(() => false);
const done = async () => { await browser.close(); process.exit(bad ? 1 : 0); };
const wide = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await ready(); await sleep(500);
  if (MODE === "demo") { await page.evaluate(async () => { await post("/api/demo", {on: true}); await tick(); }); await sleep(900); }
  const names = await page.evaluate(() => S.projects.map(p => p.name));
  const A = MODE === "demo" ? "wayfarer-mobile" : "alpha-app", B = MODE === "demo" ? "wayfarer-api" : "beta-api";
  const addon = MODE === "demo" ? {id: "relay", label: "Relay", place: false} : {id: "tide", label: "Tide", place: true};

  // ================= Home: the person =================
  await page.evaluate(() => dockGo("overview")); await sleep(500);
  await here(".timeline-card .tl-lane", 20000);
  const home = await page.evaluate(() => ({
    labels: [...document.querySelectorAll("#view section.card")].map(c => c.getAttribute("aria-label")),
    kickers: [...document.querySelectorAll("#view .kicker")].map(k => k.textContent.trim()),
    old: ["#view .traj", "#view .needs", "#view .fleet-wrap", "#view .fleet-strip", "#view .berths", "#view .home-grid", "#view .chip", "#view .tl-strip", "#view .attn", "#view .rd-card"].filter(q => document.querySelector(q)),
    counts: document.querySelectorAll("#view .home-count").length, text: document.querySelector("#view").innerText.replace(/\s+/g, " "),
  }));
  const ALLOWED = ["Next action", "Running now", "Your day", "Brain dump", "Fleet timeline", "Recently finished", "Budget"];
  ok("Home shows exactly six things (Running now, Your day, Brain dump, the fleet timeline, Recently finished, Budget today), plus the one next action when there is one", ["Running now", "Your day", "Brain dump", "Fleet timeline", "Recently finished", "Budget"].every(l => home.labels.includes(l)) && home.labels.every(l => ALLOWED.includes(l)), home.labels.join("|"));
  ok("  none of the old cards or ids is on Home: no Mission trajectory, no Needs you card, no project chips or harbor map, no stats rows, no Operations, Spend or Fleet side card, no Ready card", home.old.length === 0 && !home.kickers.some(k => /^(Mission trajectory|Needs you|Operations|Spend|Fleet|Attention feed)$/.test(k)) && !home.text.includes("Mission trajectory"), JSON.stringify([home.old, home.kickers]));
  ok("  and exactly one count line", home.counts === 1, home.counts);
  const want = await page.evaluate(() => { const n = (S.inbox || []).filter(x => !x.acknowledged).length; return n; });
  const cl = await text("#view .home-count");
  ok("  the count line says how many things need you, in how many projects and add-ons, and counts the add-on's alert", want > 0 && new RegExp("^" + want + " things? needs? you").test(cl) && /from 1 add-on/.test(cl) && /in \d+ projects?/.test(cl), cl + " | " + want);
  const nx = await page.evaluate(() => { const n = document.querySelector("#view .next-card"); return n ? {kicker: n.querySelector(".kicker").textContent.trim(), text: n.innerText.replace(/\s+/g, " "), btns: n.querySelectorAll("sl-button").length} : null; });
  ok("  the one next action, when shown, has one primary button and says whose it is (a project, an add-on or Your day)", nx === null || (nx.btns === 1 && (/^Next · (Your day|Add-on: .+)$/.test(nx.kicker) || names.some(n => nx.kicker === "Next · " + n))), JSON.stringify(nx));
  ok("  an add-on's alert is not at the top of Home (the next action and the page header do not carry it)", !(nx && nx.text.includes("Add-on: " + addon.label)) && !(await text("#ptitle")).includes(addon.label) && !(await text("#psub")).includes(addon.label)
    && (MODE === "real" || !home.text.includes("Relay")), JSON.stringify(nx));
  ok("  the fleet timeline is a lane view of every project together, with a link that opens the full timeline", (await page.locator(".timeline-card .tl-lane").count()) >= 1 && (await page.locator(".timeline-card .tl-name").allInnerTexts()).some(t => names.some(n => t.includes(n))) && (await text(".timeline-card .card-h")).includes("Open the full timeline"), await text(".timeline-card"));
  const budget = await text('section[aria-label="Budget"]');
  ok("  Budget today names the daily cap", /today/.test(budget) && budget.includes("daily cap is $25.00"), budget);
  const fin0 = await page.evaluate(() => ({list: !!document.querySelector("#fin-list"), exp: document.querySelector('section[aria-label="Recently finished"] [aria-expanded]')?.getAttribute("aria-expanded")}));
  ok("  Recently finished is small and collapsed", fin0.list === false && fin0.exp === "false", JSON.stringify(fin0));
  await page.locator('section[aria-label="Recently finished"] [aria-expanded]').click(); await sleep(300);
  const fin = await page.evaluate(() => [...document.querySelectorAll("#fin-list .li")].map(r => r.innerText.replace(/\s+/g, " ")));
  ok("  opened, it lists finished missions and runs across projects, each row naming its project", fin.length > 0 && fin.every(r => names.some(n => r.includes(n)) || /fleet|no project/.test(r)) && new Set(names.filter(n => fin.some(r => r.includes(n)))).size >= (MODE === "demo" ? 2 : 1), fin.join(" || "));
  await shot("01-home");
  ok("  the rail's Projects button carries the needs-you count as its badge", await page.evaluate(() => { const b = document.querySelector('#dock-links button.rail-btn[aria-label^="Projects"]'); return !!b && /, \d+ need you$/.test(b.getAttribute("aria-label")) && b.querySelector(".dotn").textContent.trim() === String((S.inbox || []).filter(x => !x.acknowledged).length); }));
  const h1 = (await snap()).qd;
  await page.locator("#view .home-count .mlink").click(); await sleep(500);
  let s = await snap();
  ok("the count line is a plain button that opens the Projects overview, with every project shown (one new history entry)", s.hash === "#/projects/projects" && s.title === "Projects" && s.qd === h1 + 1 && s.sel === "" && s.chip.trim() === "All projects", JSON.stringify(s));

  // ================= Projects: the overview =================
  await here(".pj-card");
  const ov = await page.evaluate(() => [...document.querySelectorAll("#view .pj-card")].map(c => ({name: c.dataset.project, state: c.dataset.state, pill: c.querySelector(".pill").textContent.trim(), dts: [...c.querySelectorAll("dt")].map(d => d.textContent.trim()),
    dds: [...c.querySelectorAll("dd")].map(d => d.innerText.replace(/\s+/g, " ").trim()), stack: (c.querySelector(".pj-stack") || {}).textContent || "", open: !!c.querySelector('sl-button[aria-label^="Open "]'), ready: !!c.querySelector('button[aria-label$=" ready?"]'), h2: c.querySelector("h2").textContent.trim()})));
  ok("the overview shows one card per project, each with its name, a state word, and Needs you, Last run, Spend and Missions", ov.length === names.length && ov.map(o => o.name).join() === [...names].sort().join()
    && ov.every(o => o.h2 === o.name && ["Blocked", "Needs you", "Running", "Idle"].includes(o.pill) && o.dts.join() === "Needs you,Last run,Spend,Missions"), JSON.stringify(ov).slice(0, 400));
  ok("  and each has an Open button and a Ready? link", ov.length === names.length && ov.every(o => o.open && o.ready), JSON.stringify(ov.map(o => [o.name, o.open, o.ready])));
  if (MODE === "real") {
    const a = ov.find(o => o.name === A), b = ov.find(o => o.name === B);
    ok("  alpha-app: Blocked, 1 thing needs you (the failed run), its last run, $1.25 today and $3.25 in 7 days, 1 open and 2 finished missions, and the stack sentence", a.pill === "Blocked" && /^1 thing: the checks would not start/.test(a.dds[0]) && /^shipwright, ERROR /.test(a.dds[1])
      && a.dds[2] === "$1.25 today, $3.25 in 7 days" && a.dds[3] === "1 open, 2 finished" && a.stack === "Python with FastAPI, tests by pytest", JSON.stringify(a));
    ok("  beta-api: Idle, nothing needs you, $0.50 today and in 7 days, 0 open and 1 finished, and no stack sentence (it was never surveyed)", b.pill === "Idle" && b.dds[0] === "Nothing needs you." && b.dds[2] === "$0.50 today, $0.50 in 7 days" && b.dds[3] === "0 open, 1 finished" && b.stack === "", JSON.stringify(b));
  } else {
    ok("  every Demo card has a last run, spend over seven days and the invented stack sentence", ov.length === names.length && ov.every(o => /, [A-Z_-]+ \d+/.test(o.dds[1]) || /No run recorded/.test(o.dds[1])) && ov.every(o => /^\$[\d.]+ today, \$[\d.]+ in 7 days$/.test(o.dds[2]) && o.stack.length > 5), JSON.stringify(ov.map(o => o.dds)));
  }
  const strip = await page.evaluate(() => { const c = document.querySelector("#view .addons"); return c ? {text: c.innerText.replace(/\s+/g, " "), btns: [...c.querySelectorAll("sl-button")].map(b => b.innerText.trim())} : null; });
  ok("the Add-ons strip below the cards lists the add-on with its alert, labelled \"Add-on: " + addon.label + "\", and links to its page or to Needs you", !!strip && strip.text.includes("Add-on: " + addon.label) && (MODE === "demo" ? strip.text.includes("evening digest did not go out") && strip.btns.includes("See in Needs you") : strip.text.includes("The nightly sync has not run") && strip.btns.includes("Open Tide") && strip.btns.includes("See in Needs you")), JSON.stringify(strip));
  const nu = await text("#view .needs");
  const onOverview = (await snap()).hash === "#/projects/projects";
  ok("  the Needs you list on the overview spans projects, each row naming its project or its add-on", onOverview && nu.includes("Add-on: " + addon.label) && names.some(n => nu.includes(n)), nu.slice(0, 300));
  ok("  the Mission trajectory is here too (it moved from Home), and Home has none", onOverview && (await page.locator("#view .traj").count()) === 1 && (await page.evaluate(() => document.querySelector("#view .traj").textContent)).includes("Mission trajectory"));
  await shot("02-projects-overview");
  ok("  the project select is the first control of the top bar and offers All projects", onOverview && await page.evaluate(() => { const c = document.querySelector("header.topbar").querySelector("sl-select, sl-input, button, sl-button"); const el = document.querySelector("#proj-switch"); return c && c.id === "proj-switch" && !el.hidden && [...el.querySelectorAll("sl-option")].some(o => o.value === "_"); }) && await visible("#proj-switch"));
  if (addon.place) {
    await page.locator("#view .addons sl-button", {hasText: "Open Tide"}).click(); await sleep(500); s = await snap();
    ok("  Open " + addon.label + " opens its own place (#/addon/tide)", s.hash === "#/addon/tide" && s.atPlace === "tide", JSON.stringify(s));
    await back();
  }
  await page.locator("#view .addons sl-button", {hasText: "See in Needs you"}).click(); await sleep(500); s = await snap();
  ok("  See in Needs you opens Needs you filtered to that add-on (#/projects/inbox?addon=" + addon.id + ")", s.hash === "#/projects/inbox?addon=" + addon.id && s.scopeAddon === addon.id && (await text("#view")).includes("Showing only items from the add-on " + addon.label), JSON.stringify(s));
  await page.evaluate(() => openProjects()); await sleep(400);

  // ================= Open filters the page to one project =================
  const q0 = (await snap()).qd;
  await page.locator(`.pj-card[data-project="${A}"] sl-button`, {hasText: "Open"}).click(); await sleep(600);
  s = await snap();
  ok("Open puts the project in the address (?project=<name>) as one new entry, and the page, the chip and the select show it", s.hash === "#/projects/projects?project=" + encodeURIComponent(A) && s.qd === q0 + 1 && s.sel === A && s.chip.trim() === A && s.pick === A, JSON.stringify(s));
  const pp = await page.evaluate(() => ({h1: document.querySelector("#ptitle").textContent.trim(), fs: parseFloat(getComputedStyle(document.querySelector("#ptitle")).fontSize), cards: document.querySelectorAll("#view .pj-card").length, slot: !!document.querySelector("#guardrails-slot"),
    guard: (document.querySelector("#guardrails-slot") || {}).innerText || "", acts: document.querySelector("#pacts").innerText.replace(/\s+/g, " "), sub: document.querySelector("#psub").textContent.trim(), text: document.querySelector("#view").innerText.replace(/\s+/g, " ")}));
  ok("  the project page names the project large, shows its repo (or says there is none), the stack sentence, its facts, its Ready card and a slot for the guardrails card", pp.h1 === A && pp.fs >= 24 && pp.cards === 1 && pp.slot && (MODE === "demo" || (pp.acts.includes("x/alpha-app") && pp.sub === "Python with FastAPI, tests by pytest")) && /ready/i.test(pp.text), JSON.stringify(pp).slice(0, 500));
  await here("#guardrails-slot .gr-locked", 15000);
  const gv = await page.evaluate(() => ({text: (document.querySelector("#guardrails-slot") || {}).innerText || "", vals: [...document.querySelectorAll("#guardrails-slot .gr-in")].map(e => e.value)}));
  ok("  the guardrails editor is in the slot: the locked rules, and the project's own rules as fields", MODE === "demo" ? /guardrails/i.test(gv.text) : (gv.text.includes("Never merge a pull request.") && gv.vals.some(v => v.includes("Never touch the payments folder"))), JSON.stringify(gv));
  await page.evaluate(() => showGuardrails()); await sleep(400);
  ok("  (the older dialog still opens and lists the same rules)", (await text("#dtitle")).endsWith("guardrails") && (await page.locator("#dbody li").count()) >= 1);
  await page.keyboard.press("Escape"); await sleep(300);
  if (MODE === "real") {
    await here("#view .tk-card", 15000);
    ok("  the Tickets card is on the project page, with the project's own ticket", (await text("#view .tk-card")).includes("Add a reset button"), await text("#view .tk-card"));
  }
  await shot("03-project-page");
  // the tabs are filtered to the project
  await tab("inbox"); await sleep(500);
  const ib = await page.evaluate(() => [...document.querySelectorAll("#view .attn")].map(a => a.innerText.replace(/\s+/g, " ")));
  const mineN = await page.evaluate(n => (S.inbox || []).filter(x => !x.acknowledged && (x.project === n || x.addon || x.place)).length, A);
  ok("Needs you on the project shows only that project's items (and add-on items, which belong to no project)", ib.length === mineN && ib.every(r => r.includes(A) || r.includes("Add-on:")), ib.join(" || "));
  await tab("missions"); await sleep(500);
  const ms = await page.evaluate(() => ({open: [...document.querySelectorAll("#view .traj .rowcard")].map(r => r.innerText.replace(/\s+/g, " ")), fin: (document.querySelector("#view .traj-fin > button") || {}).innerText || ""}));
  const ovA = await page.evaluate(n => S.overview.find(o => o.name === n), A);
  const finN = Number((/\((\d+)\)/.exec(ms.fin) || [0, 0])[1]);
  ok("Missions on the project lists its open missions large and its finished ones in the small collapsed line, and the counts equal the card's", ms.open.every(r => r.includes("in " + A)) && ms.open.length === ovA.missions_open && finN === ovA.missions_done, JSON.stringify([ms, ovA.missions_open, ovA.missions_done]));
  await tab("prs"); await sleep(1200);
  const pr = await text("#view");
  ok("Pull requests on the project shows only its pull requests", MODE === "demo" ? (!pr.includes(" · " + B + " ") ) : (pr.includes("Add a Reset button") && !pr.includes("#12")), pr.slice(0, 300));
  await tab("ledger"); await sleep(500);
  const lg = await page.evaluate(() => [...document.querySelectorAll("#view table.ledger tbody tr")].map(r => r.innerText.replace(/\s+/g, " ")));
  const ledgerOther = await page.evaluate(n => S.runs.filter(r => r.project !== n && r.project).length, A);
  ok("Ledger on the project has only its runs (no Project column, none of the other project's)", lg.length > 0 && !(await page.evaluate(() => [...document.querySelectorAll("#view table.ledger th")].some(h => h.textContent.trim() === "Project"))) && (MODE === "demo" ? true : !lg.join(" ").includes("#12")) && ledgerOther > 0, lg.join(" || ").slice(0, 300));
  await shot("04-project-ledger");

  // ================= the scope lives in the address =================
  await tab("projects"); await sleep(400);
  s = await snap();
  const keepHash = s.hash;
  await page.reload(); await ready(); await sleep(600); s = await snap();
  ok("a reload keeps the project: the address, the page, the chip and the select", s.hash === keepHash && s.sel === A && s.chip.trim() === A && s.pick === A && s.title === A, JSON.stringify(s));
  await back(); s = await snap();
  ok("Back from the project page shows the Ledger of that project (the scope is in each entry)", s.view === "ledger" && s.sel === A && s.hash === "#/projects/ledger?project=" + encodeURIComponent(A), JSON.stringify(s));
  await forward(); s = await snap();
  ok("Forward shows the project page again", s.view === "projects" && s.sel === A && s.hash === keepHash, JSON.stringify(s));
  await page.evaluate(() => openProjects()); await sleep(400); s = await snap();
  ok("the Projects overview (All projects) is its own entry: no project in the address, the chip says All projects", s.hash === "#/projects/projects" && s.sel === "" && s.chip.trim() === "All projects" && s.pick === "_", JSON.stringify(s));
  await back(); s = await snap();
  ok("Back from the overview returns to the project", s.sel === A && s.hash === keepHash, JSON.stringify(s));
  // the old spelling of an address
  const open1 = BASE + "#/projects/missions?project=" + encodeURIComponent(A), old1 = BASE + "#/work/missions?project=" + encodeURIComponent(A);
  await page.goto("about:blank"); await page.goto(open1); await ready(); await sleep(500);
  const sNew = await snap(), tNew = await text("#view");
  await page.goto("about:blank"); await page.goto(old1); await ready(); await sleep(500);
  const sOld = await snap(), tOld = await text("#view");
  ok("an old #/work/missions?project=<name> address opens the same page as the new one, and the address is rewritten as #/projects/...", sOld.view === "missions" && sOld.sel === A && sOld.title === sNew.title && sOld.hash === sNew.hash && sOld.hash === "#/projects/missions?project=" + encodeURIComponent(A) && sOld.chip === sNew.chip && tOld.length > 20 && tOld.replace(/\d+[smhd] ago|just now/g, "") === tNew.replace(/\d+[smhd] ago|just now/g, ""), JSON.stringify([sOld, sNew]));
  await page.goto("about:blank"); await page.goto(BASE + "#/work/inbox"); await ready(); await sleep(500); s = await snap();
  ok("  and so does an old #/work/inbox (the place was called Work)", s.view === "inbox" && s.hash === "#/projects/inbox", JSON.stringify(s));

  // ================= the scope box exists only where it applies =================
  const where = {};
  for (const v of ["overview", "projects", "inbox", "missions", "ledger", "crew", "spend", "connections", "settings", "documents", "notes", "showcase"]) {
    await page.evaluate(id => { openProjects(); dockGo(id); }, v); await sleep(300);
    where[v] = {box: await visible("#proj-switch"), chip: await visible("#pscope .scope-chip"), allOpt: await page.evaluate(() => [...document.querySelectorAll("#proj-switch sl-option")].some(o => o.value === "_" && /All projects/.test(o.textContent)))};
  }
  const should = {projects: 1, inbox: 1, missions: 1, ledger: 1, crew: 1, documents: 1, notes: 1};
  ok("the project select and the scope chip are on Projects, Needs you, Missions, Ledger, Crew, Documents and Notes, and absent from Home, Spend, Connections, Settings and Showcase", Object.entries(where).every(([v, w]) => should[v] ? (w.box && w.chip) : (!w.box && !w.chip)), JSON.stringify(where));
  await page.evaluate(() => dockGo("overview")); await sleep(300);
  ok("  on Home there is no \"All projects\" box to look at (the option exists only where the select is shown)", !(await visible("#proj-switch")) && !(await visible('text="All projects"')));
  await rail("Brain"); await sleep(1200);
  ok("  nor on the Brain, whose own toolbar keeps its own choices", !(await visible("#proj-switch")) && !(await page.evaluate(() => document.querySelector("#pscope .scope-chip") && document.querySelector("#pscope .scope-chip").offsetParent !== null)));
  await page.keyboard.press("Escape"); await sleep(700);
  await rail("Settings"); await sleep(500);
  ok("  nor on Settings", !(await visible("#proj-switch")) && !(await visible("#pscope .scope-chip")));
  await rail("Projects"); await sleep(400);
  ok("  and the Projects rail button opens the place again with the select back", await visible("#proj-switch") && (await snap()).hash.startsWith("#/projects/"));

  // ================= Calm =================
  await page.evaluate(() => dockGo("overview")); await sleep(300);
  await page.evaluate(() => toggleCalm(true)); await sleep(700);
  const calmHome = await page.evaluate(() => ({vis: l => 0, cards: [...document.querySelectorAll('#view section.card')].filter(c => c.offsetParent !== null && c.closest("[data-calm=hide]") === null).map(c => c.getAttribute("aria-label")),
    hidden: [...document.querySelectorAll('#view [data-calm="hide"] section.card, #view section.card[data-calm="hide"]')].filter(c => c.offsetParent === null).map(c => c.getAttribute("aria-label")), count: !!document.querySelector("#view .home-count") && document.querySelector("#view .home-count").offsetParent !== null}));
  ok("Calm keeps the next action, Your day, Brain dump and the count line on Home, and hides the timeline, Recently finished and Budget", calmHome.count && calmHome.cards.includes("Your day") && calmHome.cards.includes("Brain dump") && ["Fleet timeline", "Recently finished", "Budget"].every(l => calmHome.hidden.includes(l)), JSON.stringify(calmHome));
  await shot("05-home-calm");
  await page.locator("#calm-all").click(); await sleep(300);
  ok("  Show everything brings the rest back", (await visible('section[aria-label="Budget"]')) && (await visible('section[aria-label="Fleet timeline"]')));
  await page.evaluate(() => { openProjects(); dockGo("projects"); }); await sleep(500);
  ok("Calm on the Projects overview keeps one card per project and the Needs you list", (await page.locator("#view .pj-card:visible").count()) === names.length && (await visible("#view .needs")), "");
  await shot("06-projects-calm");
  await page.evaluate(() => { toggleCalm(false); }); await sleep(400);

  // ---- notes: the New note and Brain dump boxes stop at 1000 characters, and Edit on a note focuses its box without an error ----
  if (MODE === "real") {
    await page.evaluate(async () => { await post("/api/capture", {text: "a note to edit"}); await tick(); go("notes"); }); await here("#note-new", 15000);
    ok("the New note and Brain dump boxes stop at 1000 characters, as the Edit box does", await page.evaluate(() => document.querySelector("#note-new").getAttribute("maxlength") === "1000" && /<sl-input id="cap-in"[^>]*maxlength="1000"/.test(homeNow())));
    const errs0 = problems.console.length + problems.page.length;
    await page.locator("sl-button, button", {hasText: /^\s*Edit\s*$/}).first().click(); await here("#note-edit", 5000); await sleep(600);
    ok("Edit on a note puts the focus in its edit box and logs no error", await page.evaluate(() => { const e = document.querySelector("#note-edit"); return !!e && (document.activeElement === e || e.matches(":focus-within")); }) && problems.console.length + problems.page.length === errs0, JSON.stringify(problems));
    await page.evaluate(() => noteEditStop());
  }

  // ================= a phone, and the dark theme =================
  await page.setViewportSize({width: 390, height: 844}); await sleep(500);
  const phone = {};
  await page.evaluate(() => dockGo("overview")); await sleep(500); phone.home = await wide(); await shot("07-home-390");
  await page.evaluate(() => { openProjects(); }); await sleep(500); phone.overview = await wide(); await shot("08-projects-390");
  await page.evaluate(n => openProject(n), A); await sleep(700); phone.project = await wide(); await shot("09-project-390");
  await page.evaluate(() => dockGo("inbox")); await sleep(400); phone.inbox = await wide();
  ok("at 390 pixels wide Home, the Projects overview, a project page and Needs you have no sideways scroll", Object.values(phone).every(Boolean), JSON.stringify(phone));
  ok("  the mobile bottom bar says Projects, not Work", (await page.locator("#mobile-bottom button").allInnerTexts()).map(t => t.trim()).join("|").includes("Projects") && !(await text("#mobile-bottom")).includes("Work"), await text("#mobile-bottom"));
  await page.setViewportSize({width: 1280, height: 1000});
  await page.evaluate(() => setTheme("dark")); await sleep(300);
  await page.evaluate(() => dockGo("overview")); await sleep(500); await shot("10-home-dark");
  await page.evaluate(() => { openProjects(); }); await sleep(500); await shot("11-projects-dark");
  await page.evaluate(n => openProject(n), A); await sleep(700); await shot("12-project-dark");
  await page.evaluate(() => setTheme("auto")); await sleep(200);
  ok("no console error, no page error, no failed request", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));

  // ---- last: a second tab in the same browser pairs with a newer link, so this tab's key no longer matches (reads still work, writes are refused) ----
  if (MODE === "real" && process.env.QD_LINK2) {
    const tabB = await ctx.newPage(); await tabB.goto("about:blank"); await tabB.goto(process.env.QD_LINK2);
    await tabB.waitForFunction(() => document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 20000}).catch(() => null);
    const st = await page.evaluate(async () => {
      const r = await post("/api/capture", {text: "written from a tab that was overtaken"});
      const al = [...document.querySelectorAll("sl-alert")].map(a => a.textContent).join(" ");
      return {r, shown: !document.getElementById("unpaired").hidden, why: document.getElementById("unpaired-why").textContent, toast: /forbidden/i.test(al), way: /qtdeck dashboard link/.test(document.getElementById("unpaired").textContent)};
    });
    ok("a write from a tab whose key was replaced by a newer link shows the disconnected screen, not a toast that says only forbidden", st.r === null && st.shown && /disconnected/.test(st.why) && !st.toast, JSON.stringify(st));
    ok("  that screen shows the way back: the command for a new link", st.shown && st.way);
  }
} catch (e) {
  bad++; console.log("FAIL " + TAG + "the page test crashed | " + String(e && e.stack || e).split("\n").slice(0, 4).join(" / "));
  try { await page.screenshot({path: path.join(SHOTS, MODE + "-zz-stopped.png")}); } catch (e2) { /* none */ }
}
await done();
