// missions-page.mjs: the browser half of bin/selftest-missions.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_T its
// throwaway Quarterdeck, QD_SHOTS where the pictures go) in headless Chromium and prints one line per check: "ok ...", "FAIL ..." or "skip ...".
// Nothing here goes to the internet, and nothing real is touched: gh is a stand-in and there is no model.
//   node bin/missions-page.mjs probe     exit 0 when a browser can start here, 3 when none can
import {createRequire} from "node:module";
import fs from "node:fs";
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

const T = process.env.QD_T, SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK;
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra !== undefined ? " | " + String(extra).slice(0, 400) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const page = await ctx.newPage();
const problems = {console: [], page: [], requests: []};
page.on("console", m => { if (m.type() === "error") problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });
page.on("response", r => { if (r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const sent = [];                                   // every POST the page sends: a double click must send one
page.on("request", r => { if (r.method() === "POST") sent.push({url: new URL(r.url()).pathname, body: r.postData() || ""}); });
const sentCount = (path, needle) => sent.filter(x => x.url === path && x.body.includes(needle)).length;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({path: path.join(SHOTS, name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const view = async () => (await page.locator("#view").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const calls = () => { try { return fs.readFileSync(path.join(T, "gh-calls"), "utf8").split("\n").filter(l => l.startsWith("gh issue close")); } catch (e) { return []; } };
const fixLog = () => { try { return fs.readFileSync(path.join(T, "logs", "fix-tp.log"), "utf8"); } catch (e) { return ""; } };
const button = label => page.locator("#view sl-button", {hasText: new RegExp("^\\s*" + label + "\\s*$")});
const openMission = async id => { await page.evaluate(i => openMissionPage(i), id); await here(".mission-grid", 20000); await sleep(300); };
const missions = async () => { await page.evaluate(() => go("missions")); await here(".traj", 20000); await sleep(300); };
const wide = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);
const confirmed = async yes => { const ok1 = await here("#confirm-yes", 8000); const msg = await page.locator("#confirm-msg").innerText().catch(() => ""); await page.locator(yes ? "#confirm-yes" : "#confirm-no").click(); await sleep(600); return ok1 ? msg : null; };
const done = async () => { await browser.close(); process.exit(bad ? 1 : 0); };

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && S.fixes && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});
  await sleep(500);

  // ================= the lists =================
  await missions();
  let v = await view();
  ok("the Missions page lists a recent stop as an open mission, with the Blocked word", /Stopped, to try again/.test(v) && /Blocked/.test(v), v.slice(0, 300));
  const grp = page.locator("#view .old-grp > button");
  ok("a stop from weeks ago is under one group, 'Older than 7 days (1)', collapsed by default, and not in the open list", (await grp.innerText()).trim() === "Older than 7 days (1)" && (await grp.getAttribute("aria-expanded")) === "false"
    && (await page.locator("#old-list").count()) === 0 && !/Stopped weeks ago/.test(await view()));
  await grp.click(); await sleep(300);
  ok("  opening it lists the old mission, and closing it hides it again", (await page.locator("#old-list").innerText()).includes("Stopped weeks ago") && (await grp.getAttribute("aria-expanded")) === "true");
  await grp.click(); await sleep(300);
  ok("  the count is real: it equals the stopped, blocked or waiting missions older than 7 days that are not dismissed", await page.evaluate(() => missionSets(60).old.length === 1 && recentMissions(60, true).filter(x => isOld(x) && !x.dismissed).length === 1));
  const facts = await page.evaluate(() => ({waiting: homeFacts().waiting.length, prs: Object.values(S.fixes).filter(r => r.status === "pr").length}));
  ok("the old group does not count toward what needs you: every waiting pull request here is recent, all are counted, and the old stop is not among them", facts.waiting === facts.prs && facts.prs > 0, JSON.stringify(facts));
  const sw = page.locator('sl-switch[aria-label="Hide handled missions"]').first();
  ok("Hide handled is on by default, and a Nothing to build mission is never in the open list", await sw.evaluate(e => e.checked) && !/Nothing to build/.test(await page.locator(".traj .list").innerText().catch(() => "")));
  ok("  a small count says how many are dismissed", /1 dismissed/.test(await page.locator(".handled-bar").first().innerText()));
  await page.locator(".traj-fin > button").first().click(); await sleep(300);
  const fin = await page.locator("#traj-fin-list").innerText();
  ok("  the finished line holds the finished missions and the Nothing to build ones (with their own word), and not the dismissed one", /Merged on GitHub/.test(fin) && /Already fixed on main/.test(fin) && /Nothing to build/.test(fin) && !/already matches/.test(fin), fin.slice(0, 300));
  const calm = await page.evaluate(() => { const mk = c => { const e = document.createElement("span"); e.className = "pill " + c; e.textContent = "x"; document.body.appendChild(e); const s = getComputedStyle(e); const r = [s.color, s.backgroundColor, s.borderColor]; e.remove(); return r; }; return {nothing: mk("nothing"), blocked: mk("blocked")}; });
  ok("  the Nothing to build pill is in a calm colour, not the red of Blocked", calm.nothing[0] !== calm.blocked[0] && calm.nothing[1] !== calm.blocked[1] && calm.nothing[2] !== calm.blocked[2], JSON.stringify(calm));
  await page.locator('button[aria-pressed]', {hasText: /dismissed/}).first().click(); await sleep(300);
  ok("'N dismissed' opens the dismissed ones, each marked Dismissed", /already matches/.test(await page.locator("#dismissed-list").innerText()) && /Dismissed/.test(await page.locator("#dismissed-list").innerText()));
  await shot("missions-list");

  // ================= a merged fix =================
  await openMission("fix:issue#7");
  v = await view();
  ok("the mission page of a merged fix says Merged, and never 'Awaiting you' or 'Pull request is open'", /Merged/.test(v) && !/Awaiting you|Pull request is open|Waiting for you/.test(v), v.slice(0, 300));
  ok("  the Review step is Done, and the pull request is linked (https, its own address)", await page.locator(".pipe .node.done", {hasText: "Review"}).count() === 1 && await page.locator('sl-button[href$="/pull/70"]').count() >= 1);
  ok("  its buttons: Open the pull request and Dismiss; not Try again, not Close the issue", await button("Open the pull request").count() === 1 && await button("Dismiss").count() === 1 && await button("Try again").count() === 0 && await button("Close the issue").count() === 0);
  await shot("mission-merged");

  await page.evaluate(() => closeMissionPage()); await here(".mission-list", 10000); await sleep(300);
  const lst1 = await page.locator("#view .mission-list").innerText();
  ok("Hide handled on the mission list: finished and Nothing to build missions are not in it, open ones are", !/Merged on GitHub|Already fixed on main/.test(lst1) && /Stopped, to try again/.test(lst1), lst1.slice(0, 200));
  await page.locator('#view sl-switch[aria-label="Hide handled missions"]').click(); await sleep(500);
  const lst2 = await page.locator("#view .mission-list").innerText();
  ok("  switched off, they are, each with its word (Done, Nothing to build); the dismissed one still is not", /Merged on GitHub/.test(lst2) && /Already fixed on main/.test(lst2) && /Nothing to build/.test(lst2) && !/already matches/.test(lst2), lst2.slice(0, 200));
  await page.locator('#view sl-switch[aria-label="Hide handled missions"]').click(); await sleep(300);

  // ================= nothing to build =================
  await openMission("fix:issue#16");
  v = await view();
  ok("a NO_CHANGE mission says 'Nothing to build' with the reason in plain words, and none of Blocked", /Nothing to build/.test(v) && /Already fixed on main in 9ab3c4d\./.test(v) && !/Blocked|Open it to see why/.test(v), v.slice(0, 300));
  ok("  it is in the calm style: a callout and a header pill of the 'nothing' kind, none of the blocked kind", await page.locator(".callout.nothing").count() >= 1 && await page.locator(".callout.blocked").count() === 0 && await page.locator("#view .pill.blocked, #ptitle ~ * .pill.blocked").count() === 0);
  ok("  its buttons: Close the issue and Dismiss, each with a line of what it does and never does", await button("Close the issue").count() === 1 && await button("Dismiss").count() === 1 && /only after you say yes/.test(v) && /Dismiss only hides it here/.test(v));
  await shot("mission-nothing");
  await button("Close the issue").click();
  const msg = await confirmed(false);
  ok("Close the issue asks first, naming the repo and the issue; declining calls gh not at all", msg && /x\/tp/.test(msg) && /#16/.test(msg) && calls().length === 0, msg);
  await button("Close the issue").click();
  await confirmed(true); await sleep(900);
  ok("  saying yes calls gh issue close exactly once, with a comment, and the page then says it was closed", calls().length === 1 && /^gh issue close 16 -R x\/tp --comment /.test(calls()[0]) && /was closed from here/.test(await view()) && await button("Close the issue").count() === 0, calls().join("|"));

  // ================= a stopped mission, Dismiss and Undo =================
  await openMission("fix:issue#20");
  v = await view();
  ok("a real stop says Blocked, with Try again and Dismiss, and the hint to add the brief duty (tp lacks it, the mission has no brief)", /Blocked/.test(v) && await button("Try again").count() === 1 && await button("Dismiss").count() === 1
    && /To make a brief for this issue, add "brief" to the duties of tp/.test(v), v.slice(0, 400));
  await shot("mission-blocked");
  await button("Try again").dblclick(); await sleep(700);
  ok("a double click on Try again leaves the confirmation open (the second click must not close it)", await page.locator("#confirm-dlg[open]").count() === 1);
  const msg2 = await confirmed(false);
  ok("Try again asks first; declining starts nothing", msg2 && /same work again/.test(msg2) && !/--issue 20/.test(fixLog()), msg2);
  const hint = await page.evaluate(() => {
    const m = JSON.parse(JSON.stringify(missionNow())), keep = [S.briefs, S.projects];
    const out = {};
    out.lacks = missionActions(m).includes("To make a brief for this issue");
    S.briefs = [{id: "b1", project: "tp", issue: 20}]; out.hasBrief = missionActions(m).includes("To make a brief for this issue"); out.link = missionActions(m).includes("Open the brief");
    S.briefs = keep[0]; S.projects = S.projects.map(p => p.name === "tp" ? {...p, duties: [...p.duties, "brief"]} : p);
    out.hasDuty = missionActions(m).includes("To make a brief for this issue"); out.button = missionActions(m).includes("Make a brief for this issue");
    S.projects = keep[1]; return out;
  });
  ok("the brief hint shows only when the duty is missing and the mission has no brief: with a brief, or with the duty, there is no hint", hint.lacks && !hint.hasBrief && hint.link && !hint.hasDuty && hint.button, JSON.stringify(hint));
  await openMission("fix:issue#21");
  v = await view();
  ok("  on a project that has the brief duty the mission offers 'Make a brief for this issue' and no hint", /Make a brief for this issue/.test(v) && !/To make a brief for this issue/.test(v), v.slice(0, 300));
  await openMission("fix:issue#20");
  const dis0 = sentCount("/api/mission/action", '"dismiss"');
  await button("Dismiss").dblclick(); await button("Undo dismiss").waitFor({state: "visible", timeout: 8000}).catch(() => null); await sleep(300);
  ok("Dismiss is undoable on the page: the button turns into Undo dismiss, and the mission is still on its address", await button("Undo dismiss").count() === 1 && await button("Dismiss").count() === 0 && await page.evaluate(() => missionId === "fix:issue#20" && missionNow().dismissed === true), (await view()).slice(0, 300));
  ok("  a double click on Dismiss sent one request, not two", sentCount("/api/mission/action", '"dismiss"') - dis0 === 1, sentCount("/api/mission/action", '"dismiss"') - dis0);
  await missions();
  ok("  dismissed, it leaves the list and the count says 2 dismissed", !/Stopped, to try again/.test(await page.locator(".traj .list").innerText().catch(() => "")) && /2 dismissed/.test(await page.locator(".handled-bar").first().innerText()));
  await openMission("fix:issue#20");
  await button("Undo dismiss").click(); await sleep(900);
  await missions();
  ok("  Undo brings it back into the list, and the count goes back to 1", /Stopped, to try again/.test(await page.locator(".traj .list").innerText()) && /1 dismissed/.test(await page.locator(".handled-bar").first().innerText()));

  // ================= Calm mode, a phone, the console =================
  await page.evaluate(() => toggleCalm()); await sleep(500);
  const isCalm = await page.evaluate(() => document.documentElement.classList.contains("calm"));
  await openMission("fix:issue#20");
  ok("Calm mode keeps the actions", isCalm && await button("Try again").count() === 1 && await button("Dismiss").count() === 1);
  await page.evaluate(() => toggleCalm()); await sleep(300);
  await page.setViewportSize({width: 390, height: 800}); await sleep(500);
  const w1 = await wide();
  await openMission("fix:issue#20");
  const hs = await page.evaluate(() => [...document.querySelectorAll("#view .mact sl-button")].map(b => Math.round(b.getBoundingClientRect().height)));
  ok("the action buttons are at least 40px high", hs.length >= 2 && hs.every(h => h >= 40), hs.join());
  await openMission("fix:issue#16"); const w2 = await wide();
  await missions(); const w3 = await wide();
  ok("at 390px wide the list and the mission pages have no sideways scroll", w1 && w2 && w3, [w1, w2, w3].join());
  await shot("mission-phone");
  // ================= a plan to approve: a double click approves once =================
  await page.setViewportSize({width: 1280, height: 1000});
  const mid = await page.evaluate(async () => {
    const c = await post("/api/missions", {action: "create", project: "tp", objective: "Double click test"});
    if (!c) return null;
    await post("/api/missions", {action: "propose_plan", id: c.id}); await tick(); return c.id;
  });
  await missions(); await page.evaluate(id => openMission(id), mid);
  await page.locator("#dbody sl-button", {hasText: /^\s*Approve this plan\s*$/}).waitFor({state: "visible", timeout: 10000}).catch(() => null);
  const ap0 = sentCount("/api/missions", "approve_plan");
  await page.locator("#dbody sl-button", {hasText: /^\s*Approve this plan\s*$/}).dblclick(); await sleep(1500);
  ok("a double click on Approve this plan sent one request, and the history holds one approval", !!mid && sentCount("/api/missions", "approve_plan") - ap0 === 1
    && await page.evaluate(id => S.missions.find(m => m.id === id).events.filter(e => e.kind === "approved").length === 1, mid), sentCount("/api/missions", "approve_plan") - ap0);
  ok("no console errors, no page errors, no failed requests", problems.console.length + problems.page.length + problems.requests.length === 0, JSON.stringify(problems));
} catch (e) {
  ok("the page test ran to the end", false, e && e.stack ? e.stack.split("\n").slice(0, 3).join(" ") : e);
}
await done();
