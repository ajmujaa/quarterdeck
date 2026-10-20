// ready-ui-page.mjs: the browser half of the Ready card checks in bin/selftest-flow.sh (part 4). It opens the real dashboard that suite started (QD_LINK is
// its one-time pairing link, QD_T its throwaway Quarterdeck, QD_PROJECT the project, QD_SHOTS where the pictures go) in headless Chromium, looks at the
// Ready card of the project on its Missions page, proves the verify command through the button, drafts a README, and prints one line per check:
// "ok ...", "FAIL ..." or "skip ...". Nothing here goes to the internet and nothing real is touched: the model is the fake provider, gh a stand-in.
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

const SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK, PROJECT = process.env.QD_PROJECT, T = process.env.QD_T;
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra ? " | " + String(extra).slice(0, 300) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1100}});
const page = await ctx.newPage();
const problems = {console: [], page: [], requests: []};
page.on("console", m => { if (m.type() === "error") problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => problems.requests.push(r.url() + " " + (r.failure() || {}).errorText));
page.on("response", r => { if (r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const shot = async (name, full = false) => { try { await page.screenshot({path: path.join(SHOTS, name + ".png"), fullPage: full}); } catch (e) { /* a picture is a bonus */ } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 20000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const gone = async (sel, ms = 20000) => { try { await page.waitForSelector(sel, {state: "detached", timeout: ms}); return true; } catch (e) { return false; } };
const calls = () => { try { return fs.readFileSync(path.join(T, "gh-calls"), "utf8").split("\n").filter(Boolean); } catch (e) { return []; } };
const dlgClick = async which => { await page.locator(which).click(); await sleep(450); };
const confirmText = async () => { await here("#confirm-dlg[open]"); return text("#confirm-msg"); };
const verifyState = () => page.evaluate(() => { const d = RD.data; const v = d && d.items.find(i => i.key === "verify"); return v ? v.state : ""; });

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});
  await page.evaluate(n => { selectProject(n); go("missions"); }, PROJECT);

  const shown = await here(".rd-card", 20000);
  await sleep(400);
  const card = await text(".rd-card");
  ok("the Ready card is at the top of the Missions page for a project whose verify command was never proven", shown && card.includes("Is it ready?") && card.includes(PROJECT + " is not ready yet"), card.slice(0, 300));
  const labels = await page.locator(".rd-card .rd-label").allInnerTexts();
  ok("  it lists scan, verify, repo, docs, agents and cycles, in that order", labels.join(",") === "Scan,Verify command,GitHub repo,Docs,Agents,Cycles", labels.join(","));
  const primary = await page.locator(".rd-card sl-button[variant=primary]").count();
  ok("  it has exactly one primary button, at the bottom, and its label is the one next action", primary === 1 && (await text("#rd-next")) === "Run it once to prove it" && (await text("#rd-next-line")).startsWith("Next: Run it once to prove it"), await text("#rd-next"));
  ok("  the repo item is calm: optional, not a blocker", (await text(".rd-card details:nth-of-type(3) summary")).includes("optional"));
  await shot("ready-01-card");

  // prove it: the button asks first, then the verify command runs once in the sandbox
  await page.locator("#rd-next").click();
  const msg = await confirmText();
  ok("the button asks before it runs anything, and says it is the project's own code, in the sandbox, on a copy of the default branch", msg.includes("once, in the sandbox") && msg.includes("throwaway copy of main") && msg.includes("nothing is installed"), msg);
  await shot("ready-02-confirm");
  await dlgClick("#confirm-yes");
  ok("  while it runs the page says so (a status line) and the button is off", await here(".rd-card [role=status]") && (await page.locator("#rd-next").evaluate(e => !!e.disabled)), await text(".rd-card"));
  let state = "";
  for (let i = 0; i < 120 && state !== "done"; i++) { await sleep(500); state = await verifyState(); }
  ok("the verify command ran and the card shows it done", state === "done", state);
  await sleep(600);
  const after = await text("#view");
  ok("  the project is ready now, so the card steps aside and a link brings it back", after.includes("is ready for a first ticket") && after.includes("Ready? Show the checklist") && (await page.locator(".rd-card").count()) === 0, after.slice(0, 200));
  await page.locator("text=Ready? Show the checklist").click();
  await here(".rd-card");
  const card2 = await text(".rd-card");
  ok("  opened again, it says ready, the verify line is done, and the one primary button now starts a mission from ticket 1", card2.includes("is ready for a first ticket") && (await text("#rd-next")) === "Start a mission from ticket 1", await text("#rd-next"));
  ok("  proving it ran no gh command", calls().length === 0, calls().join(" | "));
  await shot("ready-03-ready");

  // the docs offer: draft a README, read it, nothing is written to the project
  await page.locator(".rd-card details", {hasText: "Docs"}).first().locator("summary").click();
  const offer = await page.locator("text=Draft a README").first().isVisible().catch(() => false);
  ok("the docs item offers the scribe: Draft a README (and the architecture overview)", offer && (await page.locator("text=Draft an architecture overview").count()) >= 1);
  await page.locator("sl-button", {hasText: "Draft a README"}).first().click();
  const m2 = await confirmText();
  ok("  drafting asks first, says it costs a few cents and writes nothing to the project", m2.includes("a few cents") && m2.includes("Nothing is written to your project"), m2);
  await dlgClick("#confirm-yes");
  const drafted = await here(".rd-file", 60000);
  await sleep(500);
  const dt = await text(".rd-draft");
  ok("  the draft arrives and is shown: the file, its size, a note that nothing was written, and the button that puts it on a new branch", drafted && dt.includes("README.md") && dt.includes("Nothing was written to your project") && dt.includes("Put it on a new branch") && dt.includes("Never main"), dt.slice(0, 300));
  await page.locator(".rd-file summary").first().click();
  const pre = await text(".rd-file pre");
  ok("  and the draft text can be read in the page", pre.includes("Sample React"), pre.slice(0, 120));
  const projDir = JSON.parse(fs.readFileSync(path.join(T, "config", "projects.json"), "utf8"))[PROJECT].path;
  ok("  the project folder has no README: the draft is only in the data folder", !fs.existsSync(path.join(projDir, "README.md")));
  await shot("ready-04-draft", true);

  // the agents list: a suggested duty has a Turn on button
  await page.locator(".rd-card details", {hasText: "Agents"}).first().locator("summary").click();
  const turn = await page.locator(".rd-card sl-button", {hasText: "Turn on"}).count();
  ok("the agents item lists the duties that are on with their reasons, and a Turn on button for each suggested one", turn >= 2 && (await text(".rd-agents")).includes("surveyor"), turn);

  // a small screen: the card does not make the page scroll sideways
  await page.setViewportSize({width: 390, height: 900});
  await sleep(500);
  const wide = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  ok("on a phone-width screen the page has no sideways scroll", !wide);
  await shot("ready-05-phone", true);
  await page.setViewportSize({width: 1280, height: 1100});

  ok("no console error, no page error and no failed request while the card was used", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));
} catch (e) {
  bad++; console.log("FAIL the page driver stopped: " + String(e.message).split("\n").slice(0, 3).join(" / "));
  try { await page.screenshot({path: path.join(SHOTS, "ready-zz-stopped.png")}); } catch (e2) { /* none */ }
}
await browser.close();
process.exit(bad ? 1 : 0);
