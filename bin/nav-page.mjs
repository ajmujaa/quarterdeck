// nav-page.mjs: the browser half of bin/selftest-nav.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_T its
// throwaway Quarterdeck, QD_MODE "real" for the seeded data folder or "demo" for Demo mode, QD_SHOTS where the pictures go) in headless Chromium and prints one
// line per check: "ok ...", "FAIL ..." or "skip ...". Nothing here goes to the internet, and nothing real is touched.
//   node bin/nav-page.mjs probe     exit 0 when a browser can start here, 3 when none can
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
const BASE = new URL(LINK).origin + "/", NONCE = LINK.split("#pair=")[1] || "";
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + TAG + label); else { bad++; console.log("FAIL " + TAG + label + (extra !== undefined ? " | " + String(extra).slice(0, 400) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const cdp = {s: null};
const problems = {console: [], page: [], requests: []};
const watch = p => {
  p.on("console", m => { if (m.type() === "error" && !/Failed to load resource.*status of 404/.test(m.text())) problems.console.push(m.text()); });   // a 404 is judged from the response itself, below
  p.on("pageerror", e => problems.page.push(String(e.message)));
  p.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });   // a request cut off by leaving the page is not a failure
  p.on("response", r => { if (r.status() >= 400 && !r.url().includes("/api/mission?id=cycle%3Anope")) problems.requests.push(r.url() + " " + r.status()); });   // the one 404 is the test's own: a mission id that names nothing
};
let page = await ctx.newPage(); watch(page);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.screenshot({path: path.join(SHOTS, MODE + "-" + name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const snap = () => page.evaluate(() => ({hash: location.hash, len: history.length, qd: history.state && history.state.qd, view, sel, atPlace, missionId, scopeAddon: typeof scopeAddon === "undefined" ? "" : scopeAddon, title: document.querySelector("#ptitle").textContent.trim(),
  chip: (document.querySelector("#pscope .scope-chip") || {}).innerText || "", pick: document.querySelector("#proj-switch").value}));
const ready = () => page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && document.querySelector("#view") && document.querySelector("#view").children.length > 0 && !!document.querySelector("#ptitle").textContent.trim(), null, {timeout: 30000});
const entries = async () => { const c = await ctx.newCDPSession(page); const h = await c.send("Page.getNavigationHistory"); await c.detach().catch(() => {}); return h.entries.map(e => e.url); };
const rail = label => page.locator(`#dock-links button.rail-btn[aria-label^="${label}"]`).click();
const tab = id => page.locator(`#ptabs sl-tab[panel="${id}"]`).click();
const choose = async value => { await page.locator("#proj-switch").click(); await page.locator(`#proj-switch sl-option[value="${value}"]`).click(); await sleep(450); };
const back = async () => { await page.goBack().catch(() => null); await sleep(400); };
const forward = async () => { await page.goForward().catch(() => null); await sleep(400); };

const done = async () => { await browser.close(); process.exit(bad ? 1 : 0); };
try {
  // ---- pairing: the one-time link opens the app, and the nonce is gone from the address, the history and the page's storage at once ----
  await page.goto("about:blank");
  await page.goto(LINK);
  await ready(); await sleep(500);
  if (MODE === "demo") { await page.evaluate(async () => { await post("/api/demo", {on: true}); await tick(); }); await sleep(900); }
  let s = await snap();
  const st0 = await page.evaluate(() => JSON.stringify(history.state));
  const store = await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
  ok("after pairing the address is the first route (Home), with no #pair in it", s.hash === "#/home/overview" && !page.url().includes("pair"), page.url());
  ok("  the nonce is not in history.state, in the browser's own history entries, or in local or session storage", !st0.includes(NONCE.slice(0, 12)) && !(await entries()).some(u => u.includes("pair=")) && !store.includes(NONCE.slice(0, 12)) && /^\{"qd":\d+\}$/.test(st0), st0 + " " + (await entries()).join(" "));
  ok("  the first route replaced the entry the tab opened with: the tab has one page of its own in history", s.len === 2, s.len);
  await shot("01-home");

  // ---- a click-through of five pages: one history entry each, the address says where we are ----
  const base = s.len;
  await rail("Projects"); await sleep(400);
  const w = await snap();
  ok("the Projects rail button opens a Projects page and the address follows it", /^#\/projects\/(projects|inbox|missions|prs|board|ledger|timeline|operations|spend|log)$/.test(w.hash) && w.len === base + 1, w.hash + " " + w.len);
  await tab("missions"); await sleep(400);
  s = await snap(); const hMissions = s.hash;
  ok("the Missions tab: #/projects/missions, one more entry", s.hash === "#/projects/missions" && s.len === base + 2 && s.title === "Missions", JSON.stringify(s));
  await tab("prs"); await sleep(400);
  s = await snap();
  ok("the Pull requests tab: #/projects/prs", s.hash === "#/projects/prs" && s.len === base + 3 && s.title === "Pull requests", JSON.stringify(s));
  await rail("Agents"); await sleep(400);
  s = await snap();
  ok("the Agents rail button: #/agents/crew", s.hash === "#/agents/crew" && s.len === base + 4 && s.title === "Crew", JSON.stringify(s));
  await rail("Library"); await sleep(400);
  s = await snap();
  ok("the Library rail button: #/library/documents (the fifth page)", s.hash === "#/library/documents" && s.len === base + 5 && s.title === "Documents", JSON.stringify(s));
  await shot("02-library");
  const live = async () => (await page.locator("#sr-live").innerText().catch(() => "")).trim();
  // Back four times: each time the page before, never a new entry, and the page is announced
  const seq = [["#/agents/crew", "Crew"], ["#/projects/prs", "Pull requests"], ["#/projects/missions", "Missions"], [w.hash, null]];
  let backOk = true, why = "";
  for (const [h, t] of seq) {
    await back(); s = await snap();
    if (s.hash !== h || (t && s.title !== t) || s.len !== base + 5) { backOk = false; why += ` [want ${h} ${t}, got ${s.hash} ${s.title} len ${s.len}]`; }
  }
  ok("Back four times returns to Crew, Pull requests, Missions and the Projects page, each shown, and Back adds no entry", backOk, why);
  ok("  the page name is announced on Back, as it is on a click", (await live()) === "Projects" || (await live()).length > 2, await live());
  await forward(); s = await snap();
  ok("Forward once shows Missions again", s.hash === "#/projects/missions" && s.title === "Missions" && s.len === base + 5, JSON.stringify(s));
  await page.reload(); await ready(); await sleep(500); s = await snap();
  ok("a reload opens the same page: #/projects/missions, still one tab, no new entry", s.hash === "#/projects/missions" && s.title === "Missions" && s.len === base + 5, JSON.stringify(s));

  // ---- the project scope is in the address, in the page's chip and in the select ----
  const proj = await page.evaluate(() => S.projects.map(p => p.name)[0]);
  const qd0 = await page.evaluate(() => history.state.qd);
  await choose(proj); s = await snap();
  ok("choosing a project in the select puts it in the address (?project=<name>), as one new entry after this one (the forward entries are dropped, as in any browser)", s.hash === "#/projects/missions?project=" + encodeURIComponent(proj) && s.len === qd0 + 3 && s.sel === proj && s.pick === proj, JSON.stringify([qd0, s]));
  ok("  the page header shows the scope as a chip with the project's name", s.chip.trim() === proj, s.chip);
  await page.reload(); await ready(); await sleep(500); s = await snap();
  ok("a reload keeps the project scope, the chip and the select", s.hash === "#/projects/missions?project=" + encodeURIComponent(proj) && s.sel === proj && s.pick === proj && s.chip.trim() === proj, JSON.stringify(s));
  await back(); s = await snap();
  ok("Back from the project choice shows All projects again, in the address, the chip and the select", s.hash === "#/projects/missions" && s.sel === "" && s.pick === "_" && s.chip.trim() === "All projects", JSON.stringify(s));
  await forward(); s = await snap();
  ok("Forward brings the project back", s.sel === proj && s.chip.trim() === proj, JSON.stringify(s));
  await choose("_");

  // ---- every page says what it is showing: the scope chip is on every page header and is a button that opens the project select ----
  const chips = [], bare = [];
  for (const [kind, id] of [["go", "projects"], ["go", "inbox"], ["go", "missions"], ["go", "ledger"], ["go", "crew"], ["go", "documents"]]) {
    await page.evaluate(v => dockGo(v), id); await sleep(250);
    chips.push(id + ":" + (await text("#pscope .scope-chip")));
  }
  for (const id of ["overview", "spend", "connections", "settings"]) {
    await page.evaluate(v => dockGo(v), id); await sleep(250);
    bare.push(id + ":" + (await page.evaluate(() => (document.querySelector("#pscope .scope-chip") || {innerText: ""}).innerText)) + ":" + (await page.evaluate(() => document.querySelector("#proj-switch").hidden)));       // no waiting: the chip is meant to be absent
  }
  ok("the scope chip reads All projects on every page where a project scope applies (Projects, Needs you, Missions, Ledger, Crew, Documents)", chips.every(c => c.endsWith(":All projects")), chips.join(" "));
  ok("  and the pages of the person (Home, Spend, Connections, Settings) show no chip and no project select: nothing there pretends to be a scope", bare.every(c => /^\w+::true$/.test(c)), bare.join(" "));
  await page.evaluate(() => dockGo("missions")); await sleep(250);
  await page.locator("#pscope .scope-chip").click(); await sleep(400);
  ok("the chip is a button that opens the project select, which stays the one place the scope is chosen", await page.evaluate(() => document.querySelector("#proj-switch").open === true) && await page.locator("sl-select").count() >= 1
    && await page.evaluate(() => document.querySelectorAll("#view sl-select#proj-switch, #pscope sl-select").length === 0), "");
  await page.keyboard.press("Escape"); await sleep(300);
  ok("  the project select is still the first control of the top bar", await page.evaluate(() => { const c = document.querySelector("header.topbar").querySelector("sl-select, sl-input, button, sl-button"); return c && c.id === "proj-switch"; }));

  // ---- a mission opens from the page, and survives going away and Back ----
  const mid = await page.evaluate(m => m === "demo" ? "panel:20261004-1815-dev-wayfarer-api" : recentMissions(40).find(x => x.state === "done" && x.id.startsWith("panel:")).id, MODE);
  await page.evaluate(() => dockGo("projects")); await sleep(300);
  const h0 = (await snap()).qd;
  await page.locator(`.traj [data-m="${mid}"], .traj .traj-list [data-m="${mid}"]`).first().click({timeout: 3000}).catch(async () => { await page.locator(".traj-fin > button").first().click(); await sleep(200); await page.locator(`.traj [data-m="${mid}"]`).first().click(); });
  await here("#view .mission-main"); await sleep(500); s = await snap();
  ok("opening a mission puts its id in the address (#/projects/mission/<id>, encoded once) and is one entry", s.hash === "#/projects/mission/" + encodeURIComponent(mid) && s.qd === h0 + 1 && s.missionId === mid, JSON.stringify(s));
  const mtitle = s.title;
  await tab("prs"); await sleep(400);
  s = await snap();
  ok("then Pull requests", s.hash === "#/projects/prs" && s.title === "Pull requests", s.hash);
  await back(); s = await snap();
  ok("Back from Pull requests shows the mission again (the open mission is in the address, not forgotten)", s.hash === "#/projects/mission/" + encodeURIComponent(mid) && s.title === mtitle && await here("#view .mission-main", 5000), JSON.stringify(s));
  await page.reload(); await ready(); await here("#view .mission-main"); await sleep(400); s = await snap();
  ok("a reload keeps the mission open", s.hash === "#/projects/mission/" + encodeURIComponent(mid) && s.title === mtitle, JSON.stringify(s));
  await shot("03-mission");

  // ---- mission steps by kind, through the page ----
  const pipe = await page.evaluate(() => [...document.querySelectorAll(".pipe .node")].map(n => ({cls: n.className, label: n.querySelector("b").textContent.replace(/^[^A-Za-z]+/, "").trim(), state: n.querySelector(".ns").textContent.trim(), note: (n.querySelector("small") || {textContent: ""}).textContent})));
  const sub = await text("#psub");
  ok("a Done panel shows only the steps it needs: Brief and Panel done, Build, Verify and Review Skipped with the reason, and no Not started anywhere", pipe.length === 5 && pipe.slice(2).every(n => n.state === "Skipped" && /^Not needed for a .* panel mission$/.test(n.note)) && !pipe.some(n => n.state === "Not started") && !(await text("#view")).includes("Not started"), JSON.stringify(pipe));
  ok("  one plain sentence under the Done badge says what Done means and what comes next", /^The panel ruled on \d+ items?; fixing them is optional, start it from the Work tab\./.test(sub) && (await text("#pacts")).includes("Done"), sub);
  const pj = await text("#pproj");
  ok("  the project is named in the heading area, as a line of its own and not a small crumb", /^project\s+\S+/i.test(pj) && (MODE === "demo" ? pj.includes("wayfarer-api") : pj.includes("alpha-app")) && await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector("#pproj b")).fontSize) >= 16), pj);
  await shot("04-mission-done");
  if (MODE === "demo") {
    await page.evaluate(() => openMissionPage("fix:20261005-0412-design-wayfarer-mobile#1")); await here("#view .pipe"); await sleep(500);
    const run = await page.evaluate(() => [...document.querySelectorAll(".pipe .node")].map(n => n.querySelector(".ns").textContent.trim()));
    ok("a mission still running keeps its pending steps as Not started", run.join(",") === "Done,Done,Active,Not started,Not started", run.join(","));
    await page.evaluate(() => openMissionPage("fix:20261004-2130-spec-wayfarer-web#1")); await here("#view .pipe"); await sleep(500);
    ok("a merged fix is Done at every step, and says the pull request was merged", (await page.evaluate(() => [...document.querySelectorAll(".pipe .node .ns")].map(n => n.textContent.trim()).join(","))) === "Done,Done,Done,Done,Done" && (await text("#psub")).startsWith("The pull request was merged"));
  } else {
    await page.evaluate(id => openMissionPage(id), await page.evaluate(() => recentMissions(40).find(x => x.id.startsWith("cycle:") && x.state === "done").id)); await here("#view .pipe"); await sleep(500);
    const cyc = await page.evaluate(() => [...document.querySelectorAll(".pipe .node .ns")].map(n => n.textContent.trim()));
    ok("a Done cycle that had nothing to build shows no Not started step, and its line says nothing is waiting", !cyc.includes("Not started") && cyc.includes("Skipped") && (await text("#psub")).includes("nothing is waiting"), cyc.join(",") + " | " + (await text("#psub")));
    await page.evaluate(id => openMissionPage(id), await page.evaluate(() => recentMissions(40).find(x => x.id.startsWith("cycle:") && x.state === "awaiting").id)); await here("#view .pipe"); await sleep(500);
    const aw = await page.evaluate(() => [...document.querySelectorAll(".pipe .node .ns")].map(n => n.textContent.trim()));
    ok("a cycle waiting for review keeps the group it has not reached as Not started (it is still to come)", aw.includes("Not started") && aw.includes("Awaiting you"), aw.join(","));
  }

  // ---- the Projects overview's mission trajectory (it moved from Home): open missions first and large, finished ones in one small collapsed line ----
  await page.evaluate(() => dockGo("projects")); await sleep(500);
  const tr = await page.evaluate(() => ({rows: [...document.querySelectorAll(".traj .rowcard")].map(r => ({state: [...r.classList].find(c => ["running", "blocked", "awaiting", "done"].includes(c)), text: r.innerText.replace(/\s+/g, " ").trim(), h: r.getBoundingClientRect().height})),
    fin: (document.querySelector(".traj-fin > button") || {}).innerText, exp: (document.querySelector(".traj-fin > button") || {getAttribute: () => null}).getAttribute("aria-expanded"), list: document.querySelectorAll(".traj-list li").length}));
  ok("the trajectory lists open missions only as large rows, each naming its project and what is next", tr.rows.length > 0 && tr.rows.every(r => r.state !== "done" && /\b(in .+|no project)\b/.test(r.text) && r.text.includes("Next:") && r.h > 60), JSON.stringify(tr.rows).slice(0, 300));
  ok("  finished missions are one small collapsed line, Finished recently (N), closed by default", /^Finished recently \(\d+\)$/.test(tr.fin || "") && tr.exp === "false" && tr.list === 0, JSON.stringify([tr.fin, tr.exp, tr.list]));
  await shot("05-home-trajectory");
  await page.locator(".traj-fin > button").click(); await sleep(300);
  const tr2 = await page.evaluate(() => ({list: document.querySelectorAll(".traj-list li").length, exp: document.querySelector(".traj-fin > button").getAttribute("aria-expanded"), n: Number(/\((\d+)\)/.exec(document.querySelector(".traj-fin > button").innerText)[1]), focus: document.activeElement && document.activeElement.closest(".traj-fin") !== null, len: history.length}));
  ok("  it expands to a compact list with one line per finished mission, and keeps its place through a poll", tr2.exp === "true" && tr2.list === tr2.n && tr2.n > 0, JSON.stringify(tr2));
  await sleep(3500);
  ok("  (a redraw by the poll does not collapse it)", (await page.evaluate(() => document.querySelectorAll(".traj-list li").length)) === tr2.n);
  await page.locator(".traj-fin > button").click(); await sleep(200);
  await shot("06-home-after");

  // ---- the add-on: labelled in Needs you, listed in the scope box, a scope of its own ----
  const addon = MODE === "demo" ? {id: "relay", label: "Relay", place: false} : {id: "tide", label: "Tide", place: true};
  await page.evaluate(() => dockGo("inbox")); await sleep(500);
  const nu = await text("#view");
  ok(`an add-on's alert in Needs you is labelled "Add-on: ${addon.label}", and a sentence says why it shows under every project`, nu.includes("Add-on: " + addon.label) && nu.includes("not from one of your projects"), nu.slice(0, 400));
  await shot("07-needs-you-addon");
  const opts = await page.evaluate(() => [...document.querySelectorAll("#proj-switch sl-option")].map(o => o.value + "=" + o.textContent.trim()));
  ok(`the scope box has an Add-ons group with ${addon.label}, after the projects and before Add a project`, opts.indexOf("__addon:" + addon.id + "=" + addon.label) > opts.findIndex(o => o.startsWith("_=")) && opts.indexOf("__addon:" + addon.id + "=" + addon.label) < opts.indexOf("__add=Add a project…") && await page.evaluate(() => /Add-ons/.test(document.querySelector("#proj-switch small.sw-grp").textContent)), opts.join("|"));
  await page.evaluate(() => { selectProject(""); go("projects"); }); await sleep(300);
  const homeNeeds = await text(".needs");
  ok("the add-on's alert is labelled on the Projects overview's Needs you card too", homeNeeds.includes("Add-on: " + addon.label), homeNeeds.slice(0, 300));
  await page.evaluate(() => go("overview")); await sleep(300);
  ok("  and Home has no Needs you card and no add-on alert block (it has a count line that links to Projects)", (await page.locator("#view .needs").count()) === 0 && (await page.locator("#view .home-count .mlink").count()) === 1, await text("#view"));
  await page.evaluate(() => go("projects")); await sleep(300);
  const before = (await snap()).qd;
  await choose("__addon:" + addon.id); s = await snap();
  if (addon.place) {
    ok("choosing an add-on that has a place opens that place: #/addon/" + addon.id + ", chip \"Add-on: " + addon.label + "\", the select shows it", s.hash === "#/addon/" + addon.id && s.chip.trim() === "Add-on: " + addon.label && s.pick === "__addon:" + addon.id && s.atPlace === addon.id && s.qd === before + 1, JSON.stringify(s));
    await page.reload(); await ready(); await sleep(500); s = await snap();
    ok("  a reload keeps the add-on's place and scope", s.hash === "#/addon/" + addon.id && s.atPlace === addon.id && s.chip.trim() === "Add-on: " + addon.label && s.pick === "__addon:" + addon.id, JSON.stringify(s));
    await shot("08-addon-place");
    await back(); s = await snap();
    ok("  Back leaves the place and the scope returns to All projects", s.atPlace === "" && s.pick === "_" && s.chip.trim() === "All projects", JSON.stringify(s));
  } else {
    ok("choosing an add-on without a place opens Needs you filtered to it: #/projects/inbox?addon=" + addon.id + ", chip \"Add-on: " + addon.label + "\"", s.hash === "#/projects/inbox?addon=" + addon.id && s.chip.trim() === "Add-on: " + addon.label && s.pick === "__addon:" + addon.id && s.scopeAddon === addon.id && s.qd === before + 1, JSON.stringify(s));
    const only = await page.evaluate(() => [...document.querySelectorAll("#view .attn")].map(a => a.innerText.replace(/\s+/g, " ")));
    ok("  Needs you shows only that add-on's items, and says so", only.length === 1 && only[0].includes("Add-on: " + addon.label) && (await text("#view")).includes("Showing only items from the add-on " + addon.label), JSON.stringify(only));
    await shot("08-addon-scope");
    await page.reload(); await ready(); await sleep(500); s = await snap();
    ok("  a reload keeps the add-on scope in the address, the chip and the select", s.hash === "#/projects/inbox?addon=" + addon.id && s.scopeAddon === addon.id && s.chip.trim() === "Add-on: " + addon.label && s.pick === "__addon:" + addon.id, JSON.stringify(s));
    await tab("missions"); await sleep(400); s = await snap();
    ok("  going to another page ends the add-on scope: the page says All projects, not a scope it is not applying", s.scopeAddon === "" && s.chip.trim() === "All projects" && s.pick === "_" && !s.hash.includes("addon="), JSON.stringify(s));
    await back(); s = await snap();
    ok("  Back returns to the add-on's Needs you", s.scopeAddon === addon.id && s.hash === "#/projects/inbox?addon=" + addon.id, JSON.stringify(s));
    await choose("_"); s = await snap();
    ok("  All projects in the select ends it: every item is back", s.scopeAddon === "" && s.chip.trim() === "All projects" && !s.hash.includes("addon="), JSON.stringify(s));
  }

  // ---- a pasted or typed address: a deep link opens the mission directly, a hostile one opens Home ----
  const deep = BASE + "#/work/mission/" + encodeURIComponent(mid) + (MODE === "real" ? "?project=" + encodeURIComponent(proj) : "");
  await page.goto("about:blank");
  await page.goto(deep); await ready(); await here("#view .mission-main"); await sleep(500); s = await snap();
  ok("a deep link typed into a fresh page opens the mission directly, with its project scope; the old #/work/ spelling of the address opens the same page and is rewritten to #/projects/", s.view === "mission" && s.missionId === mid && s.title === mtitle && (MODE === "demo" || s.sel === proj) && s.hash.startsWith("#/projects/mission/"), JSON.stringify(s));
  await page.goto(BASE + "#/library/panels"); await sleep(500); s = await snap();
  ok("an address typed into this page (only the #fragment changes) goes there without reloading", s.hash === "#/library/panels" && s.title === "Panels", JSON.stringify(s));
  const before2 = problems.page.length;
  const hostile = ["#/projects/mission/<script>window.__pwn=1</script>", "#/projects/projects?project=%3Cimg%20src%3Dx%20onerror%3Dwindow.__pwn%3D1%3E", "#/work/mission/<script>window.__pwn=1</script>", "#/work/mission/%3Cimg%20src%3Dx%20onerror%3Dwindow.__pwn%3D1%3E", "#/zzz/overview", "#/work/inbox?project=%3Cimg%20src%3Dx%20onerror%3Dwindow.__pwn%3D1%3E",
    "#/work/mission/cycle%3A%00", "#/work/mission/..%2F..%2Fetc%2Fpasswd", "#/addon/__proto__", "#" + "/work/inbox".repeat(40), "#/work/inbox?addon=nope", "#/work/mission/%E0%A4%A", "#nonsense", "#/work/inbox#pair=" + "A".repeat(30)];
  let hostileOk = true, hwhy = "";
  for (const h of hostile) {
    await page.goto("about:blank"); await page.goto(BASE + h); await ready(); await sleep(450);
    const r = await page.evaluate(() => ({hash: location.hash, title: document.querySelector("#ptitle").textContent.trim(), pwn: window.__pwn, html: document.querySelector("#view").innerHTML.includes("<script"), view}));
    if (r.hash !== "#/home/overview" || r.pwn !== undefined || r.html || r.view !== "overview") { hostileOk = false; hwhy += ` [${h.slice(0, 50)} -> ${JSON.stringify(r)}]`; }
  }
  ok("a bad or hostile address opens Home without error, runs nothing, and is rewritten as Home in the address bar", hostileOk && problems.page.length === before2, hwhy);
  await page.evaluate(() => { location.hash = "#/work/mission/%3Cb%3Ex%3C%2Fb%3E"; }); await sleep(500); s = await snap();
  ok("a hostile address typed into a page that is already open is refused the same way", s.hash === "#/home/overview" && s.view === "overview", JSON.stringify(s));
  const unknown = "#/work/mission/" + encodeURIComponent("cycle:nope-nothing-here");
  await page.goto(BASE + unknown); await sleep(600); await ready(); await here("#view .empty-state, #view .back", 8000); s = await snap();
  ok("a well-formed mission address that names nothing says the mission is no longer on record and offers the list", s.view === "mission" && (await text("#view")).includes("no longer on record"), JSON.stringify(s));

  // ---- Esc in the Brain returns with one step, and the Brain's own switches are entries ----
  await page.goto("about:blank"); await page.goto(BASE + "#/home/overview"); await ready(); await sleep(500);
  const hb = (await snap()).qd;
  await rail("Brain"); await sleep(1200); s = await snap();
  ok("the Brain is #/brain/map, one entry", s.hash === "#/brain/map" && s.qd === hb + 1 && s.view === "brain", JSON.stringify(s));
  await page.keyboard.press("Escape"); await sleep(700); s = await snap();
  ok("Esc in the Brain returns to where the owner came from in one step: Home, and no new entry", s.hash === "#/home/overview" && s.view === "overview" && s.qd === hb && (await page.evaluate(() => history.length)) === s.len, JSON.stringify(s));
  await forward(); s = await snap();
  ok("  Forward goes back into the Brain", s.hash === "#/brain/map" && s.view === "brain", JSON.stringify(s));
  await page.keyboard.press("Escape"); await sleep(600);
  await page.evaluate(() => { dockGo("missions"); }); await sleep(300);
  await rail("Brain"); await sleep(1000);
  if (MODE === "demo") {
    const lb = (await snap()).qd;
    await page.locator('.brain-bar [data-k="m-rh"]').first().click().catch(() => null); await sleep(600); s = await snap();
    ok("My rhythm (Demo): the Map | Rhythm switch is one entry and the address says #/brain/rhythm", s.hash === "#/brain/rhythm" && s.qd === lb + 1, JSON.stringify(s));
    await page.keyboard.press("Escape"); await sleep(700); s = await snap();
    ok("  Esc from My rhythm still returns to the page before the Brain, in one step", s.view === "missions" && s.hash === "#/projects/missions" && s.qd === lb - 1, JSON.stringify(s));
  } else {
    await page.keyboard.press("Escape"); await sleep(700); s = await snap();
    ok("Esc from the Brain returns to Missions, the page before it", s.view === "missions" && s.hash === "#/projects/missions", JSON.stringify(s));
  }
  await page.goto("about:blank"); await page.goto(BASE + "#/brain/map"); await ready(); await sleep(1000); await page.keyboard.press("Escape"); await sleep(600); s = await snap();
  ok("a Brain opened by a pasted address has no page to return to: Esc goes Home (one new entry)", s.hash === "#/home/overview" && s.view === "overview", JSON.stringify(s));

  // ---- polls and re-renders never touch the address ----
  await rail("Projects"); await sleep(300); await tab("missions"); await sleep(400);
  const p0 = await page.evaluate(() => ({len: history.length, hash: location.hash, state: JSON.stringify(history.state)}));
  await page.evaluate(() => { window.__ticks = 0; const f = window.fetch; window.fetch = function(u, ...a){ if(String(u).includes("/api/state")) window.__ticks++; return f.call(this, u, ...a); }; });
  await sleep(10500);
  const p1 = await page.evaluate(() => ({len: history.length, hash: location.hash, state: JSON.stringify(history.state), ticks: window.__ticks}));
  ok("polling for 10 seconds adds no history entry and does not touch the address (at least three polls ran)", p1.len === p0.len && p1.hash === p0.hash && p1.state === p0.state && p1.ticks >= 3, JSON.stringify([p0, p1]));
  await page.evaluate(() => toggleCalm(!document.documentElement.classList.contains("calm"))); await sleep(500);
  await page.evaluate(() => { document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("resize")); render(); render(); }); await sleep(300);
  s = await snap();
  ok("a re-render (Calm, resize, render() called twice) adds no history entry", s.len === p0.len && s.hash === p0.hash, JSON.stringify(s));
  await page.evaluate(() => toggleCalm(!document.documentElement.classList.contains("calm"))); await sleep(300);

  // ---- one user action, one entry: a click that sets three things is still one ----
  const q0 = (await snap()).qd;
  await page.evaluate(() => { selectProject(S.projects[0].name); dockGo("ledger"); go("ledger"); }); await sleep(300);
  s = await snap();
  ok("selectProject then dockGo then go in the same click is one entry, not three", s.qd === q0 + 1 && s.hash.startsWith("#/projects/ledger?project="), JSON.stringify(s));
  await page.evaluate(() => { dockGo("ledger"); }); await sleep(200);
  ok("going where we already are adds no entry", (await snap()).qd === q0 + 1);

  // ---- the browser's own history only ever held this app ----
  const ents = await entries();
  ok("the browser's history holds only this app's addresses (and the blank page): Back never leaves for anything else, and no entry is a pairing link", ents.every(u => u === "about:blank" || u.startsWith(BASE)) && !ents.some(u => u.includes("pair=")), ents.join(" "));
  ok("no console error, no page error, no failed request", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));
} catch (e) {
  bad++; console.log("FAIL " + TAG + "the page test crashed | " + String(e && e.stack || e).split("\n").slice(0, 4).join(" / "));
}
await done();
