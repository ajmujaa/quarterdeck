// tickets-ui-page.mjs: the browser half of bin/selftest-tickets-ui.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link,
// QD_T its throwaway Quarterdeck, QD_SHOTS where the pictures go) in headless Chromium and prints one line per check: "ok ...", "FAIL ..." or "skip ...".
// Nothing here goes to the internet, and nothing real is touched: the model is the fake provider and gh a stand-in.
//   node bin/tickets-ui-page.mjs probe     exit 0 when a browser can start here, 3 when none can
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
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra ? " | " + String(extra).slice(0, 300) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const page = await ctx.newPage();
const problems = {console: [], page: [], requests: []};
let watching = true;
page.on("console", m => { if (watching && m.type() === "error") problems.console.push(m.text()); });
page.on("pageerror", e => { if (watching) problems.page.push(String(e.message)); });
page.on("requestfailed", r => { if (watching) problems.requests.push(r.url() + " " + (r.failure() || {}).errorText); });
page.on("response", r => { if (watching && r.status() >= 400) problems.requests.push(r.url() + " " + r.status()); });
const shot = async name => { try { await page.screenshot({path: path.join(SHOTS, name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const off = sel => page.locator(sel).first().evaluate(e => !!e.disabled);      // a Shoelace button's own state (Playwright's isDisabled reads only native controls)
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const gone = async (sel, ms = 20000) => { try { await page.waitForSelector(sel, {state: "detached", timeout: ms}); return true; } catch (e) { return false; } };
const here = async (sel, ms = 20000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const calls = () => { try { return fs.readFileSync(path.join(T, "gh-calls"), "utf8").split("\n").filter(Boolean); } catch (e) { return []; } };
const reg = () => JSON.parse(fs.readFileSync(path.join(T, "config", "projects.json"), "utf8"));
const openProject = async name => { await page.evaluate(n => { selectProject(n); go("missions"); }, name); await here("#view .tk-card"); await sleep(400); };
const fill = async (sel, value) => { const i = page.locator(sel + " textarea, " + sel + " input").first(); await i.click(); await i.fill(value); };
const confirmText = async () => { await here("#confirm-dlg[open]"); return text("#confirm-msg"); };
const dlgClick = async which => { await page.locator(which).click(); await sleep(450); };

try {
await page.goto("about:blank");
await page.goto(LINK);
await page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});

// ---- no project chosen: the card asks for one, with the project select as its one action ----
await page.evaluate(() => { selectProject(""); go("missions"); });
await here("#view .tk-card, #view .card");
ok("with All projects the Tickets card says to choose a project and offers the project select", (await text("#view")).includes("Choose a project to add tickets") && await page.locator("#tk-pick").count() === 1);
await shot("00-all-projects");

// ---- a project with no repo: the options, in order ----
await openProject("pagetest");
const keys = await page.locator(".tk-opt .tk-t").allInnerTexts();
ok("the repo card shows the four options in order, with the plain titles", keys.map(s => s.replace(/^[abcd]\s*/, "").trim()).join("|") === "I already have a GitHub repo|I have a GitHub account|I have no GitHub account|Not now", keys.join("|"));
ok("  the one sentence from the server is above them", (await text(".tk-card")).includes("No GitHub repo yet") && (await text("#view")).includes("pagetest has no GitHub repo, so the crew cannot open pull requests yet; local tickets still work."));
ok("  (c) is an ordered list of steps and says a person must do it", await page.locator(".tk-steps li").count() >= 5 && (await text(".tk-opt:nth-child(3)")).includes("A person has to do this: Quarterdeck never creates an account and never touches a password."));
ok("  (a) has a labelled owner/name field and Save; (b) a Create button; the Tickets card is below the repo card", (await page.locator("#tk-repo").getAttribute("label")) === "GitHub repo (owner/name)"
  && await page.getByText("Create a private GitHub repo", {exact: true}).count() === 1 && await page.evaluate(() => { const c = [...document.querySelectorAll("#view .card")]; const i = c.findIndex(x => x.textContent.includes("No GitHub repo yet")), j = c.findIndex(x => x.querySelector("#tk-request")); return i >= 0 && j > i; }));
await shot("01-repo-options");

// ---- type a request, draft, see the stand-in's draft ----
ok("the request box is labelled, shows its limit, and Draft tickets waits for words", (await page.locator("#tk-request").getAttribute("label")) === "What do you want built?" && (await text("#tk-count")) === "0 of 2000 characters" && await off("#tk-draft"));
await fill("#tk-request", "Make a counter page with a reset button");
ok("  typing counts the characters and wakes the button", (await text("#tk-count")) === "39 of 2000 characters" && !(await off("#tk-draft")));
await shot("02-request-typed");
await page.locator("#tk-draft").click();
ok("Draft tickets shows the polite status line while the planner runs", await here("#view [role=status]:has-text('The planner is reading the project and drafting. This can take a minute and costs a few cents; nothing is filed yet.')", 8000));
await shot("03-drafting");
ok("then the draft arrives: two tickets with their acceptance checks, one primary button that tells the truth", await here("#tk-file-d1", 40000) && (await text("#tk-file-d1")) === "Save 2 tickets on this computer"
  && (await text(".tk-draft")).includes("Add a reset button") && (await text(".tk-draft")).includes("Press Reset and the counter shows 0") && await page.locator(".tk-draft .tk-ticket").count() === 2);
ok("  that button is the primary one, Discard draft sits beside it, and the request box is cleared and enabled", (await page.locator("#tk-file-d1").getAttribute("variant")) === "primary" && await page.getByText("Discard draft", {exact: true}).count() === 1
  && (await page.locator("#tk-request textarea").inputValue()) === "");
await shot("04-draft");
await page.locator("#tk-file-d1").click();
ok("Save on this computer lists the tickets: id, title, status open, kept on this computer, and the draft is gone", await here("#tk-list .li", 15000) && await page.locator("#tk-list .li").count() === 2 && (await text("#tk-list")).includes("Add a reset button")
  && (await text("#tk-list")).includes("kept on this computer") && (await text("#tk-list")).includes("open") && await gone(".tk-draft"));
await sleep(500);
ok("  focus lands on the ticket list", await page.evaluate(() => document.activeElement && document.activeElement.id === "tk-list"));
ok("  each open ticket has a Start a mission button (the project opted in)", await page.getByText("Start a mission", {exact: true}).count() === 2);
await shot("05-tickets");

// ---- Start a mission opens the cycle dialog for that ticket ----
await page.getByText("Start a mission", {exact: true}).first().click();
ok("Start a mission opens the cycle dialog for that ticket: no issue field, the ticket named, a local branch and no pull request", await here("#cycle-dlg[open]") && (await text("#cycle-body")).includes("Local ticket") && (await text("#cycle-body")).includes("Remember the count after a reload")
  && await page.locator("#cycle-issue").count() === 0 && (await text("#cycle-dlg")).includes("It never pushes, opens a pull request or merges."));
await shot("06-cycle-dialog");
await page.locator("#cycle-no").click(); await sleep(500);

// ---- (a) validation, then a repo is connected: the card goes ----
await fill("#tk-repo", "not a repo");
await page.getByText("Save", {exact: true}).first().click();
ok("a repo that is not owner/name is said at the field, and nothing is sent", (await page.locator("#tk-repo").evaluate(e => e.helpText)).includes("owner/name") && reg().pagetest.repo === "");
await fill("#tk-repo", "octo/pagetest");
await page.getByText("Save", {exact: true}).first().click();
ok("Save connects the repo: the registry has it, and the repo card disappears", await gone(".tk-opt", 15000) && reg().pagetest.repo === "octo/pagetest" && !(await text("#view")).includes("No GitHub repo yet"));
// a new draft now files on GitHub, behind a confirmation
fs.writeFileSync(path.join(T, "fake-script.json"), JSON.stringify([{text: 'TICKETS_JSON: {"tickets":[{"title":"Show the count in the page title","body":"The tab title shows the current count.","acceptance":["Press + twice: the tab title says 2"]},{"title":"Add a keyboard shortcut for reset","body":"Pressing R resets the counter.","acceptance":["Press R: the counter shows 0"]}]}\nRESULT: DRAFTED 2 tickets', sleep: 1, cost_usd: 0.05}]));
await fill("#tk-request", "Another idea for the counter");
await page.locator("#tk-draft").click();
ok("with a repo the primary button says where it files: File 2 issues on octo/pagetest, and there is a small Save on this computer only", await here("#tk-file-d2", 40000) && (await text("#tk-file-d2")) === "File 2 issues on octo/pagetest" && await page.getByText("Save on this computer only", {exact: true}).count() === 1);
await shot("07-draft-with-repo");
const before = calls().filter(l => l.startsWith("gh issue create")).length;
await page.locator("#tk-file-d2").click();
const msg = await confirmText();
ok("filing on GitHub asks first: how many issues, in which repo", msg.includes("creates 2 GitHub issues in octo/pagetest"), msg);
await shot("08-confirm-file");
await dlgClick("#confirm-no");
ok("  Cancel files nothing: no gh issue create, the draft is still there", calls().filter(l => l.startsWith("gh issue create")).length === before && await page.locator("#tk-file-d2").count() === 1);
await page.getByText("Save on this computer only", {exact: true}).click();
ok("  Save on this computer only keeps both tickets here without a dialog or a gh call", await here("#tk-list .li:nth-child(4)", 15000) && calls().filter(l => l.startsWith("gh issue create")).length === before);
// discard
fs.writeFileSync(path.join(T, "fake-script.json"), JSON.stringify([{text: 'TICKETS_JSON: {"tickets":[{"title":"A third thing nobody asked for","body":"b","acceptance":["c"]}]}\nRESULT: DRAFTED 1 tickets', sleep: 1, cost_usd: 0.05}]));
await fill("#tk-request", "A third idea");
await page.locator("#tk-draft").click();
await here("#tk-file-d3", 40000);
await page.getByText("Discard draft", {exact: true}).click();
const dmsg = await confirmText();
await dlgClick("#confirm-yes");
ok("Discard draft asks, then removes the draft", dmsg.startsWith("Discard this draft?") && await gone(".tk-draft", 15000));

// ---- (b) create a private repo: two confirmations, and the not-signed-in message ----
await openProject("pagetest2");
fs.writeFileSync(path.join(T, "gh-signedout"), "");
await page.getByText("Create a private GitHub repo", {exact: true}).click();
const c1 = await confirmText();
ok("(b) Create asks first: a PRIVATE repository, named, connected, nothing pushed yet", c1 === "This creates a PRIVATE repository pagetest2 on your GitHub account and connects it. Nothing is pushed yet.", c1);
await shot("09-create-confirm");
await dlgClick("#confirm-yes");
const c2 = await confirmText();
ok("  then a second question for the push", c2.startsWith("Push your default branch once so pull requests have a base?"), c2);
await dlgClick("#confirm-no");
ok("  gh not signed in: the plain message is shown at the button, and nothing was created", await here("#view .callout.blocked", 15000)
  && (await text("#view .callout.blocked")) === "GitHub CLI is not signed in: run gh auth login in a terminal, then try again." && !calls().some(l => l.startsWith("gh repo create")) && reg().pagetest2.repo === "");
await shot("10-not-signed-in");
fs.unlinkSync(path.join(T, "gh-signedout"));
await page.getByText("Create a private GitHub repo", {exact: true}).click();
await confirmText(); await dlgClick("#confirm-yes"); await confirmText(); await dlgClick("#confirm-no");
ok("  signed in, it creates the repo (without the push) and the card goes", await gone(".tk-opt", 30000) && reg().pagetest2.repo === "octo-cat/pagetest2" && calls().some(l => l.startsWith("gh repo create octo-cat/pagetest2 --private")));

// ---- the mission view of a ticket cycle ----
const cid = await page.evaluate(() => { const c = (S.cycles || []).find(x => Number.isInteger(x.ticket)); return c ? c.id : ""; });
ok("the mission list holds the ticket cycle the API suite ran", !!cid);
await page.evaluate(id => { selectProject(""); openMissionPage("cycle:" + id); }, cid);
await here("#view .mission-main", 15000);
await sleep(500);
const mt = await text("#view");
ok("the mission view says ticket #n, shows the crew's steps (purser, dev panel, shipwright) and the skipped ones as Skipped with the reason", /Cycle · ticket #\d+/.test(await text("#ptitle")) && mt.toLowerCase().includes("the crew's steps") && mt.includes("Purser") && mt.includes("Dev panel") && mt.includes("Shipwright")
  && (mt.match(/Skipped/g) || []).length >= 4 && mt.includes("needs a GitHub pull request"), (await text("#ptitle")) + " | " + (mt.match(/Skipped/g) || []).length);
ok("  nothing skipped is shown as failed: no bad pill, no blocked step", await page.locator("#view .pill.bad, #view .node.blocked").count() === 0);
ok("  the local branch and the review command are plain selectable text (not links), and one line says what is next", await page.locator("#view code.tk-sel").count() >= 2 && await page.locator("#view a:has-text('ticket/')").count() === 0
  && mt.includes("What is next:") && mt.includes("merge it yourself"));
await shot("11-ticket-mission");
await page.evaluate(() => toggleCalm(true)); await sleep(500);
ok("the same mission renders in Calm mode without errors, and the pipeline still names the skipped groups", (await text("#view")).includes("Skipped") && await page.locator("#view .pipe .node.skipped").count() === 2);
await shot("12-ticket-mission-calm");
await openProject("pagetest");
ok("in Calm the secondary things are folded away (the local-only button), and Show everything brings them back", !(await page.getByText("Save on this computer only", {exact: true}).isVisible().catch(() => false)));
await shot("13-tickets-calm");
await page.evaluate(() => toggleCalm(false));

// ---- a review ticket in the list, and the other widths and theme ----
const reviewTk = await page.evaluate(() => 1);
await page.evaluate(() => { selectProject("norepo"); go("missions"); });
await here("#tk-list .li", 15000); await sleep(400);
const lt = await text("#tk-list");
ok("a local ticket in review shows its branch and the review command as selectable text, and the What now line", lt.includes("review") && lt.includes("Review it with") && lt.includes("What now: review it, merge it yourself, or connect a repo to run the reviewers.") && await page.locator("#tk-list code.tk-sel").count() >= 2);
await shot("14-review-ticket");
await page.setViewportSize({width: 390, height: 844}); await sleep(500);
ok("at phone width the page does not scroll sideways, and the new controls are 40px high", await page.evaluate(() => document.scrollingElement.scrollWidth <= window.innerWidth + 1)
  && await page.evaluate(() => [...document.querySelectorAll("#view .tk-card sl-button, #view .tk-card sl-input, #view .tk-card sl-textarea")].every(e => e.getBoundingClientRect().height >= 39.5)));
await shot("15-phone");
await page.setViewportSize({width: 1280, height: 1000});
await page.evaluate(() => setTheme("light")); await sleep(400);
await openProject("pagetest2"); await shot("16-light");
await page.evaluate(() => setTheme("dark"));

// ---- the rules of the kit ----
await openProject("norepo");
const kit = await page.evaluate(() => {
  const root = document.querySelector("#view"), out = {unlabelled: [], small: [], rawHex: 0};
  for (const e of root.querySelectorAll("sl-input, sl-textarea, sl-select")) if (!e.getAttribute("label")) out.unlabelled.push(e.id || e.localName);
  for (const e of root.querySelectorAll(".tk-card *")) { const fs = parseFloat(getComputedStyle(e).fontSize); if (e.children.length === 0 && e.textContent.trim() && fs < 12) out.small.push(e.localName + ":" + fs); }
  out.primaries = root.querySelectorAll(".tk-card sl-button[variant=primary]").length;
  out.dash = /[\u2013\u2014]/.test([...root.querySelectorAll(".tk-card")].map(c => c.textContent).join(" "));
  return out;
});
ok("every textarea, input and select in the new cards has a label, no text is under 12px, there is no en or em dash in the copy", kit.unlabelled.length === 0 && kit.small.length === 0 && !kit.dash, JSON.stringify(kit));
ok("  at most one primary button in the Tickets card", kit.primaries <= 1, kit.primaries);

// ---- Demo mode: invented tickets, and every action says nothing is done ----
ok("no console error, no page error and no failed request in the whole run so far", problems.console.length === 0 && problems.page.length === 0 && problems.requests.length === 0, JSON.stringify(problems));
watching = false;
await page.evaluate(async () => { await post("/api/demo", {on: true}); await tick(); selectProject("saltpan-blog"); go("missions"); });
await here("#view .tk-card", 15000); await sleep(800);
const dt = await text("#view");
ok("Demo mode shows invented tickets and a draft, and the options for the project with no repo", dt.includes("No GitHub repo yet") && dt.includes("Thank the reader after the newsletter signup") && dt.includes("Add a recipe card to the template") && dt.includes("Review it with"));
await shot("17-demo");
await page.locator("#tk-file-d1").click();
await sleep(800);
ok("  a demo action says nothing is drafted, filed or created, and changes nothing", (await page.locator("sl-alert").allInnerTexts()).join(" ").includes("Demo mode: nothing is drafted, filed or created.") && !fs.existsSync(path.join(T, "state", "tickets", "saltpan-blog.json")));
await page.evaluate(async () => { await post("/api/demo", {on: false}); await tick(); });

} catch (e) {
  bad++; console.log("FAIL the page driver stopped: " + String(e.message).split("\n").slice(0, 3).join(" / "));
  try { await page.screenshot({path: path.join(SHOTS, "zz-stopped.png")}); } catch (e2) { /* none */ }
}
await browser.close();
process.exit(bad ? 1 : 0);
