// live-page.mjs: the browser half of bin/selftest-live.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_MODE "real" for the
// seeded throwaway Quarterdeck or "demo" for Demo mode, QD_SHOTS where the pictures go) in headless Chromium and prints one line per check: "ok ...", "FAIL ..." or
// "skip ...". Nothing here goes to the internet, and nothing real is touched.
//   node bin/live-page.mjs probe     exit 0 when a browser can start here, 3 when none can
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
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + TAG + label); else { bad++; console.log("FAIL " + TAG + label + (extra !== undefined ? " | " + String(extra).slice(0, 600) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const problems = {console: [], page: [], requests: []};
const page = await ctx.newPage();
page.on("console", m => { if (m.type() === "error" && !/Failed to load resource.*status of 404/.test(m.text())) problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });
page.on("response", r => { if (r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({path: path.join(SHOTS, MODE + "-" + name + ".png"), fullPage: true}); } catch (e) { /* a picture is a bonus */ } };
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const until = async (fn, arg, ms = 20000) => { try { await page.waitForFunction(fn, arg, {timeout: ms}); return true; } catch (e) { return false; } };
const wide = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);
const done = async () => { await browser.close(); process.exit(bad ? 1 : 0); };
const A = MODE === "demo" ? "wayfarer-api" : "alpha-app", B = MODE === "demo" ? "wayfarer-web" : "beta-api";

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && S.live && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});
  if (MODE === "demo") { await page.evaluate(async () => { await post("/api/demo", {on: true}); await tick(); }); await sleep(900); }
  else if (!await until(() => S.live.worktrees.length > 0, null, 40000)) ok("the worktrees of the registered projects were read", false, "no worktree in S.live after 40 seconds");
  await page.evaluate(() => { window.__noReload = true; });

  // ================= Home: the Running now strip =================
  await page.evaluate(() => dockGo("overview")); await sleep(500);
  const strip = 'section[aria-label="Running now"]';
  ok("Home shows a Running now strip", await here(strip, 20000));
  const home = await page.evaluate(() => {
    const el = document.querySelector('#view section[aria-label="Running now"]'), prev = el && el.previousElementSibling;
    return {text: el ? el.innerText.replace(/\s+/g, " ") : "", prev: prev ? prev.getAttribute("aria-label") || prev.className : "", first: !!el && [...document.querySelectorAll("#view > section, #view > div")].indexOf(el) <= 2,
            before: !!el && !!document.querySelector("#view .home-count") && !!(el.compareDocumentPosition(document.querySelector("#view .home-count")) & Node.DOCUMENT_POSITION_FOLLOWING),
            img: !!document.querySelector('#view img[src="x"]'), rows: el ? el.querySelectorAll(".live-row").length : 0};
  });
  ok("  it is the first block under the next action (before the count line, Your day and Brain dump)", home.first && home.before && (home.prev === "" || home.prev === "Next action" || /next-card/i.test(home.prev)), JSON.stringify({prev: home.prev, first: home.first, before: home.before}));
  ok("  the header line says when the live data was last updated", /Live data updated (less than a minute|\d+ minutes?) ago\./i.test(home.text), home.text.slice(0, 200));
  if (MODE === "real") {
    ok("  a working session: project, branch, agent, what it does and its draft pull request", /alpha-app session/i.test(home.text) && /feat\/export/i.test(home.text) && /Agent: reviewer/i.test(home.text) && /Running the reviewer agent/i.test(home.text) && /draft PR #12/i.test(home.text), home.text);
    ok("  a duty is named a duty, with its run's own words", /alpha-app duty/i.test(home.text) && /Duty: shipwright/i.test(home.text) && /issue #7, Add export/i.test(home.text), home.text);
    ok("  the other project's session is there, and where the hook gave no detail the line says so", /beta-api session/i.test(home.text) && /Agent: no detail reported/i.test(home.text), home.text);
    ok("  a session that matches no project says so, under Other", /Other session/i.test(home.text) && /Not in a registered project\./i.test(home.text), home.text);
    ok("  the owner's turn is marked: waiting for you", /waiting for you/i.test(home.text), home.text);
    ok("  the quiet ones are one folded line, 2 idle sessions, and the finished one is not shown", (await page.locator(strip + ' sl-details[summary="2 idle sessions"]').count()) === 1 && !/old\/branch/i.test(home.text), home.text);
    ok("  text from an event is shown as text, never as markup", !home.img && /<img src=x onerror=alert\(1\)>/i.test(home.text), home.text.slice(-300));
    ok("  the strip has a line for each session and duty that is working, waiting for the owner or idle (at least 5)", home.rows >= 5, home.rows);
    await page.evaluate(() => { const a = S.live; window.__live = a; S.live = {...a, hook_installed: false, updated_at: null, items: []}; render(); }); await sleep(300);
    const nohook = await text(strip);
    ok("  with no hook and nothing running: Nothing is running right now., the plain line and the exact command", /Nothing is running right now\./i.test(nohook) && /No live data: the sessions hook is not installed\. Install it with: bash .*fleet-hook\.sh install/i.test(nohook), nohook);
    await page.evaluate(() => { S.live = window.__live; render(); }); await sleep(300);
  } else {
    ok("  invented Relay sessions: a builder working in wayfarer-api, a draft pull request, a duty, a session under Other", /wayfarer-api session/i.test(home.text) && /Agent: builder/i.test(home.text) && /draft PR #91/i.test(home.text) && /duty/i.test(home.text) && /Other session/i.test(home.text), home.text);
  }
  await shot("01-home");
  await page.locator(strip + " .mlink.link").first().click(); await sleep(500);
  ok("  Open the full fleet view goes to the Fleet page", (await page.evaluate(() => view)) === "fleet");
  await page.evaluate(() => dockGo("overview")); await sleep(400);
  await page.evaluate(() => toggleCalm(true)); await sleep(400);
  ok("Calm keeps the Running now strip", await page.locator(strip).first().isVisible());
  await page.evaluate(() => toggleCalm(false)); await sleep(300);

  // ================= a project's Live work =================
  await page.evaluate(n => openProject(n), A); await sleep(800);
  ok("a project's page has a Live work card", await here("#live-work", 15000));
  const pj = await page.evaluate(() => { const kids = [...document.querySelector("#view .pj-page").children], i = kids.findIndex(k => k.id === "live-work"), n = kids.findIndex(k => k.classList.contains("needs"));
    return {i, n, text: document.querySelector("#live-work").innerText.replace(/\s+/g, " ")}; });
  ok("  it comes right after the project's facts and before Needs you", pj.i === 1 && (pj.n === -1 || pj.n > pj.i), JSON.stringify({i: pj.i, n: pj.n}));
  if (MODE === "real") {
    ok("  the worktree with the draft pull request: branch, state, the pull request with its draft marker, and the session working in it", /feat\/export/i.test(pj.text) && /Draft pull request #12 Add export \(open\)/i.test(pj.text) && /Session working/i.test(pj.text) && /draft pull request/i.test(pj.text), pj.text);
    ok("  a worktree nobody works in says so, and shows its changes", /spike\/probe/i.test(pj.text) && /Nobody working in it/i.test(pj.text) && /1 changed file/i.test(pj.text), pj.text);
    ok("  the running duty is listed in the project", /Duty: shipwright/i.test(pj.text), pj.text);
    ok("  the project's own page shows nothing of the other project", !/beta-api/i.test(pj.text), pj.text);
  } else {
    ok("  the invented worktrees and their sessions", /feat\/trip-export-timezone/i.test(pj.text) && /Session working/i.test(pj.text), pj.text);
  }
  await shot("02-project-live");
  await page.evaluate(() => { openProjects(); }); await sleep(600);
  const all = await page.evaluate(() => ({heads: [...document.querySelectorAll("#live-work h3[data-live-project]")].map(h => h.dataset.liveProject), text: document.querySelector("#live-work").innerText.replace(/\s+/g, " ")}));
  ok("with All projects chosen the same list is grouped under a heading per project, with Other last", all.heads.includes(A) && all.heads.includes(B) && all.heads.includes("") && all.heads[all.heads.length - 1] === "" && /Other \(not in a registered project\)/i.test(all.text), JSON.stringify(all.heads));
  await shot("03-projects-live");
  await page.evaluate(n => { location.hash = "#/agents/fleet?project=" + encodeURIComponent(n); }, A); await sleep(700);
  const fl = await page.evaluate(() => ({view, sel, hash: location.hash}));
  ok("the Fleet page takes the project from the address (?project=)", fl.view === "fleet" && fl.sel === A, JSON.stringify(fl));

  // ================= the Crew page =================
  await page.evaluate(n => { selectProject(n); dockGo("crew"); }, A); await sleep(900);
  ok("the Crew page for one project loads", await here(".crew-sum", 15000));
  const crew = await page.evaluate(() => { const v = document.querySelector("#view");
    return {rows: [...v.querySelectorAll(".crew-row .mono")].map(e => e.textContent.trim()), avail: v.querySelector("sl-details.crew-avail") ? v.querySelector("sl-details.crew-avail").getAttribute("summary") : "",
            open: !!(v.querySelector("sl-details.crew-avail") || {}).open, height: v.scrollHeight, text: v.innerText.replace(/\s+/g, " "), n: S.duties.length,
            first: [...v.querySelectorAll("[data-avail]")].slice(0, 2).map(e => e.dataset.avail), hasEnable: v.querySelectorAll("[data-enable]").length}; });
  if (MODE === "real") {
    ok("  enabled agents first and full size: panel, shipwright and marshal", ["panel", "shipwright", "marshal"].every(d => crew.rows.includes(d)) && crew.rows.length === 3, JSON.stringify(crew.rows));
    ok("  the rest are folded in one Available (N) list, closed", crew.avail === `Available (${crew.n - 3})` && !crew.open, JSON.stringify({a: crew.avail, n: crew.n, open: crew.open}));
    ok("  no wall of 'not enabled' lines and no 'How to enable it' link", !/Not enabled for this project/i.test(crew.text) && !/How to enable it/i.test(crew.text), crew.text.slice(0, 300));
    ok("  the header counts sessions and duties apart: 1 session and 1 duty", /Running now 1 session and 1 duty/i.test(crew.text), crew.text.slice(0, 200));
    ok("  the project keeps no agents of its own: one sentence, no list of covered jobs", /This project keeps no agents of its own\./i.test(crew.text) && !/Which jobs are covered/i.test(crew.text), crew.text.slice(-300));
  } else {
    ok("  enabled agents first, the rest folded in Available (N)", crew.rows.length > 0 && /^Available \(\d+\)$/i.test(crew.avail) && !crew.open, JSON.stringify(crew));
  }
  const closedH = crew.height;
  await shot("04-crew-closed");
  await page.evaluate(() => document.querySelector("sl-details.crew-avail").show()); await sleep(700);
  const openH = await page.evaluate(() => document.querySelector("#view").scrollHeight);
  ok("  folded, the page is much shorter than the same list open (the old page was a wall)", openH - closedH > 150, `${closedH} closed, ${openH} open`);
  const av = await page.evaluate(() => ({first: [...document.querySelectorAll("[data-avail]")].slice(0, 3).map(e => e.dataset.avail), text: document.querySelector("[data-avail]") ? document.querySelector("[data-avail]").innerText.replace(/\s+/g, " ") : "",
    btns: [...document.querySelectorAll("[data-enable]")].map(b => b.getAttribute("aria-label")), tall: [...document.querySelectorAll("[data-enable]")].every(b => b.getBoundingClientRect().height >= 30)}));
  ok("  Available: one line each with an Enable button that has a name", av.btns.length === crew.n - (MODE === "real" ? 3 : crew.rows.length) && av.btns.every(l => /^Enable the \w+ for /i.test(l)), JSON.stringify(av.btns).slice(0, 300));
  if (MODE === "real") {
    ok("  the scan's suggestions come first, with its reason", av.first[0] === "surveyor" && av.first[1] === "inspector" && /Suggested for this project: it reads pull requests/i.test(av.text), JSON.stringify(av));
    await shot("05-crew-available");
    // cancel leaves everything as it was
    await page.locator('[data-enable="surveyor"]').click();
    ok("  Enable asks first, and the question says what the duty does, why it is suggested and that it stays report-only", await here("#confirm-dlg[open]", 8000) && /Why it is suggested: it reads pull requests/i.test(await text("#confirm-msg")) && /report-only until you run it with Write for real/i.test(await text("#confirm-msg")), await text("#confirm-msg"));
    await page.locator("#confirm-no").click(); await sleep(500);
    ok("  Cancel changes nothing", (await page.evaluate(() => S.projects.find(p => p.name === "alpha-app").duties)).join() === "panel,shipwright,marshal");
    const before = await page.evaluate(() => ({rows: document.querySelectorAll(".crew-row").length, avail: document.querySelector("sl-details.crew-avail").getAttribute("summary")}));
    await page.locator('[data-enable="inspector"]').click();
    await here("#confirm-dlg[open]", 8000);
    await page.locator("#confirm-yes").click();
    const moved = await until(() => [...document.querySelectorAll(".crew-row .mono")].some(e => e.textContent.trim() === "inspector") && !document.querySelector('[data-avail="inspector"]'), null, 20000);
    const after = await page.evaluate(() => ({rows: document.querySelectorAll(".crew-row").length, avail: document.querySelector("sl-details.crew-avail").getAttribute("summary"), open: document.querySelector("sl-details.crew-avail").open, noReload: window.__noReload === true,
      duties: S.projects.find(p => p.name === "alpha-app").duties}));
    ok("  Enable works from the page: the guarded endpoint answers, and the row moves up to the enabled agents without a reload", moved && after.rows === before.rows + 1 && after.noReload && after.duties.includes("inspector"), JSON.stringify({before, after}));
    ok("  the Available count went down by one and the list stayed open", after.avail === `Available (${crew.n - 4})` && after.open, JSON.stringify(after));
    await shot("06-crew-after-enable");
    await page.evaluate(() => { document.querySelector("#view").scrollIntoView(); });
    await page.locator(".crew-sum [aria-label^='1 session']").click(); await sleep(600);
    ok("  the sessions number in the header goes to the project's live work", (await page.evaluate(() => view)) === "projects" && (await here("#live-work", 5000)));
    await page.evaluate(() => dockGo("crew")); await sleep(500);
    await page.evaluate(() => selectProject("beta-api")); await sleep(700);
    const beta = await text("#view");
    ok("  another project has its own list: nothing of alpha-app's enabled agents, and its own session count", !/marshal/i.test(await page.evaluate(() => [...document.querySelectorAll(".crew-row .mono")].map(e => e.textContent).join(" "))) && /Running now 1 session and 0 duties/i.test(beta), beta.slice(0, 300));
    await page.evaluate(() => selectProject("")); await sleep(700);
    const allc = await page.evaluate(() => ({text: document.querySelector("#view").innerText.replace(/\s+/g, " "), enable: document.querySelectorAll("[data-enable]").length, avail: !!document.querySelector("sl-details.crew-avail")}));
    ok("  with All projects chosen: one row per agent, the not-enabled ones folded too, and no Enable button (it needs a project)", allc.avail && allc.enable === 0 && /Running now \d+ sessions? and \d+ dut/i.test(allc.text), JSON.stringify(allc).slice(0, 300));
  } else {
    await page.evaluate(n => selectProject(n), "wayfarer-web"); await sleep(700);
    await page.evaluate(() => document.querySelector("sl-details.crew-avail") && document.querySelector("sl-details.crew-avail").show()); await sleep(500);
    const first = await page.evaluate(() => (document.querySelector("[data-avail]") || {dataset: {}}).dataset.avail);
    ok("  Demo: the invented scan suggests the joiner first", first === "joiner", first);
    await page.locator('[data-enable="joiner"]').click();
    await here("#confirm-dlg[open]", 8000);
    await page.locator("#confirm-yes").click(); await sleep(900);
    problems.requests = problems.requests.filter(r => !/\/api\/project\/duties 400$/.test(r)); problems.console = problems.console.filter(c => !/status of 400/.test(c));      // the refusal is the answer this check asks for
    ok("  Demo: Enable is refused, saying nothing is changed, and the row stays in Available", /nothing is run, drafted or changed/i.test(await text(".toast, #toasts, sl-alert") + await text("body")) && !!(await page.locator('[data-avail="joiner"]').count()), "");
  }

  // ================= a phone, and Calm on the Crew page =================
  await page.evaluate(n => selectProject(n), A); await sleep(500);
  await page.evaluate(() => { dockGo("crew"); toggleCalm(true); }); await sleep(600);
  ok("Calm keeps the Crew page: the enabled agents and the Available list", (await page.locator(".crew-row").count()) > 0 && !!(await page.locator("sl-details.crew-avail").count()));
  await page.evaluate(() => toggleCalm(false)); await sleep(300);
  await page.setViewportSize({width: 390, height: 844}); await sleep(500);
  const phone = {};
  await page.evaluate(() => dockGo("overview")); await sleep(500); phone.home = await wide(); await shot("07-home-390");
  await page.evaluate(n => openProject(n), A); await sleep(700); phone.project = await wide(); await shot("08-project-390");
  await page.evaluate(() => { openProjects(); }); await sleep(600); phone.projects = await wide();
  await page.evaluate(n => { selectProject(n); dockGo("crew"); }, A); await sleep(700); phone.crew = await wide(); await shot("09-crew-390");
  await page.evaluate(() => { const d = document.querySelector("sl-details.crew-avail"); if (d) d.show(); }); await sleep(500); phone.crewOpen = await wide();
  await page.evaluate(() => dockGo("fleet")); await sleep(700); phone.fleet = await wide();
  ok("at 390 pixels wide Home, a project, the Projects overview, the Crew page (folded and open) and Fleet have no sideways scroll", Object.values(phone).every(Boolean), JSON.stringify(phone));
  await page.setViewportSize({width: 1280, height: 1000});
  ok("no console error, no page error, no failed request", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));
} catch (e) {
  bad++; console.log("FAIL " + TAG + "the page test crashed | " + String(e && e.stack || e).split("\n").slice(0, 4).join(" / "));
  try { await page.screenshot({path: path.join(SHOTS, MODE + "-zz-stopped.png")}); } catch (e2) { /* none */ }
}
await done();
