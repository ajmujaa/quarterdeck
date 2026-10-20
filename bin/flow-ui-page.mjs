// flow-ui-page.mjs: the browser half of part 4 of bin/selftest-flow.sh. It opens the real dashboard that suite started (QD_LINK is its one-time pairing
// link, QD_T its throwaway Quarterdeck, QD_PROJECT the project, QD_CYCLE the id of the ticket cycle the API part ran, QD_SHOTS where the pictures go) in
// headless Chromium, looks at the project's Missions page and at the mission, and prints one line per check: "ok ...", "FAIL ..." or "skip ...".
// Nothing here goes to the internet, and nothing real is touched: the model is the fake provider and gh a stand-in.
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

const SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK, PROJECT = process.env.QD_PROJECT, CYCLE = process.env.QD_CYCLE, T = process.env.QD_T;
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra ? " | " + String(extra).slice(0, 300) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const page = await ctx.newPage();
const problems = {console: [], page: [], requests: []};
page.on("console", m => { if (m.type() === "error") problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => problems.requests.push(r.url() + " " + (r.failure() || {}).errorText));
page.on("response", r => { if (r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const shot = async name => { try { await page.screenshot({path: path.join(SHOTS, name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const here = async (sel, ms = 20000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const calls = () => { try { return fs.readFileSync(path.join(T, "gh-calls"), "utf8").split("\n").filter(Boolean); } catch (e) { return []; } };

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});

  await page.evaluate(n => { selectProject(n); go("projects"); }, PROJECT);
  const listed = await here("#tk-list .li", 20000);
  await sleep(500);
  const lt = await text("#view");
  ok("the project's Missions page lists both tickets, and says the project has no GitHub repo yet", listed && lt.includes("Clear the completed todos") && lt.includes("Show a summary line") && lt.includes("No GitHub repo yet"), lt.slice(0, 200));
  const tl = await text("#tk-list");
  ok("  the ticket that was built shows as review, with its local branch and the review command as selectable text, not as links",
     tl.includes("review") && tl.includes("ticket/2-show-a-summary-line") && tl.includes("Review it with") && await page.locator("#tk-list code.tk-sel").count() >= 2 && await page.locator("#tk-list a:has-text('ticket/')").count() === 0, tl.slice(0, 300));
  ok("  the other ticket is still open, and the page names what to do next", tl.includes("open") && tl.includes("What now:"), tl.slice(0, 300));
  await shot("flow-01-tickets");

  await page.evaluate(id => { selectProject(""); openMissionPage("cycle:" + id); }, CYCLE);
  const opened = await here("#view .mission-main", 20000);
  await sleep(500);
  const mt = await text("#view");
  ok("the mission opens and says ticket #2, with the crew's steps: the purser, the dev panel and the shipwright", opened && /Cycle · ticket #2/.test(await text("#ptitle")) && mt.toLowerCase().includes("the crew's steps") && mt.includes("Purser") && mt.includes("Dev panel") && mt.includes("Shipwright"), (await text("#ptitle")) + " | " + mt.slice(0, 200));
  ok("  the steps that need a pull request show as Skipped with the reason, and nothing is shown as failed or blocked", (mt.match(/Skipped/g) || []).length >= 4 && mt.includes("needs a GitHub pull request") && await page.locator("#view .pill.bad, #view .node.blocked").count() === 0);
  ok("  the branch and the review command are on the page, and one line says what is next", mt.includes("ticket/2-show-a-summary-line") && mt.includes("What is next:") && mt.includes("merge it yourself"));
  await shot("flow-02-mission");

  ok("no console error, no page error and no failed request while the two views were open", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));
  ok("  and the page made no gh call", calls().length === 0, calls().join(" | "));
} catch (e) {
  bad++; console.log("FAIL the page driver stopped: " + String(e.message).split("\n").slice(0, 3).join(" / "));
  try { await page.screenshot({path: path.join(SHOTS, "flow-zz-stopped.png")}); } catch (e2) { /* none */ }
}
await browser.close();
process.exit(bad ? 1 : 0);
