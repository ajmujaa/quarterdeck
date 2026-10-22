// onboarding-page.mjs: the browser half of bin/selftest-onboarding.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_MODE "first"
// for the first-run panel or "attach" for the guided attach panel, QD_T the throwaway data folder, QD_HOME_DIR the fake HOME, QD_OUTSIDE a folder outside it, QD_SHOTS where the
// pictures go) in headless Chromium and prints one line per check: "ok ...", "FAIL ..." or "skip ...". Nothing here goes to the internet, and nothing real is touched.
//   node bin/onboarding-page.mjs probe     exit 0 when a browser can start here, 3 when none can
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

const SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK, MODE = process.env.QD_MODE === "attach" ? "attach" : "first";
const HOME = process.env.QD_HOME_DIR, OUTSIDE = process.env.QD_OUTSIDE, DATA = process.env.QD_T;
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra !== undefined ? " | " + String(extra).slice(0, 600) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
// the page's clipboard is a recorder: what the Copy buttons write is read from here (the test reads it; the page never reads the clipboard)
await ctx.addInitScript(() => {
  window.__copied = []; window.__refuse = false;
  Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText: t => window.__refuse ? Promise.reject(new Error("refused")) : (window.__copied.push(String(t)), Promise.resolve())}});
});
const problems = {console: [], page: [], requests: []};
const page = await ctx.newPage();
page.on("console", m => { if (m.type() === "error" && !/Failed to load resource.*status of (400|404)/.test(m.text())) problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });
page.on("response", r => { if (r.status() >= 400 && !(/\/api\/attach$/.test(r.url()) && r.status() === 400)) problems.requests.push(r.url() + " " + r.status()); });
const attaches = [];                               // every POST /api/attach that applies: a double click on Attach this project must send one
page.on("request", r => { if (r.method() === "POST" && new URL(r.url()).pathname === "/api/attach" && (r.postData() || "").includes('"apply":true')) attaches.push(r.postData()); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({path: path.join(SHOTS, MODE + "-" + name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const here = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "visible", timeout: ms}); return true; } catch (e) { return false; } };
const gone = async (sel, ms = 15000) => { try { await page.waitForSelector(sel, {state: "detached", timeout: ms}); return true; } catch (e) { return false; } };
const text = async sel => (await page.locator(sel).first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
const ready = () => page.waitForFunction(() => typeof S !== "undefined" && S && S.projects && document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 30000});
const wide = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);
const noDash = s => !/[\u2013\u2014]/.test(s);
const done = async () => {
  ok("no console error, no page error and no failed request in this part", !problems.console.length && !problems.page.length && !problems.requests.length, JSON.stringify(problems));
  await browser.close(); process.exit(bad ? 1 : 0);
};

try {
  await page.goto("about:blank");
  await page.goto(LINK);
  await ready();

  if (MODE === "first") {
    // ================= the first-run panel =================
    ok("a fresh data folder opens Home with the first-run panel and nothing else on the page", await here(".fr-card #fr-title"));
    await page.waitForFunction(() => document.querySelectorAll(".fr-item").length >= 8, null, {timeout: 60000}).catch(() => null);
    await sleep(500);
    const f = await page.evaluate(() => ({
      cards: document.querySelectorAll("#view > section.card").length, title: document.querySelector("#fr-title").textContent.trim(),
      focus: document.activeElement && document.activeElement.id, items: [...document.querySelectorAll(".fr-item")].map(i => ({key: i.dataset.key, label: i.querySelector(".fr-label").textContent.trim(),
        pill: i.querySelector(".pill").textContent.trim(), cmd: (i.querySelector(".fr-cmd") || {}).textContent || "", copy: i.querySelectorAll(".fr-fix sl-button").length})),
      primary: [...document.querySelectorAll("#view sl-button[variant=primary]")].map(b => b.textContent.trim()), buttons: [...document.querySelectorAll(".fr-card .btns sl-button")].map(b => b.textContent.trim()),
      text: document.querySelector(".fr-card").innerText.replace(/\s+/g, " "), nextcard: !!document.querySelector(".next-card"), demo: !!(S.demo && S.demo.on)}));
    ok("  it is one card, a heading that takes focus, and Demo is not on", f.cards === 1 && f.title === "Welcome to Quarterdeck" && f.focus === "fr-title" && !f.demo && !f.nextcard, JSON.stringify([f.cards, f.title, f.focus, f.demo, f.nextcard]));
    ok("  the checklist is the doctor's: claude, gh, git, node, python3 and the three sign-ins, each with a state pill", f.items.map(i => i.label).join("|") === "claude|gh|git|node|python3|claude signed in|gh signed in|API key stored" && f.items.every(i => ["Have", "Missing", "Not checked"].includes(i.pill)), JSON.stringify(f.items));
    const by = Object.fromEntries(f.items.map(i => [i.key, i]));
    ok("  from the stand-ins on PATH: claude and its sign-in are 'Have', gh is installed but not signed in ('Missing', 'gh auth login'), the API key has no fix while claude is signed in", by.claude.pill === "Have" && by.claude_auth.pill === "Have" && by.gh.pill === "Have" && by.gh_auth.pill === "Missing" && by.gh_auth.cmd === "gh auth login" && by.api_key.pill === "Missing" && by.api_key.cmd === "", JSON.stringify(by));
    const fixes = f.items.filter(i => i.cmd);
    ok("  every fix command is in a small box with a Copy button of its own (and nothing else has one)", fixes.length >= 1 && fixes.every(i => i.copy === 1) && f.items.filter(i => !i.cmd).every(i => i.copy === 0), JSON.stringify(f.items));
    ok("  it says these are the same checks as qtdeck doctor", /These are the same checks as qtdeck doctor\./.test(f.text), f.text);
    ok("  one primary button, 'Look around in Demo', and a plain secondary 'Skip, I will set it up myself'", f.primary.length === 1 && f.primary[0] === "Look around in Demo" && f.buttons.join("|") === "Look around in Demo|Skip, I will set it up myself", JSON.stringify([f.primary, f.buttons]));
    ok("  calm wording: no em dash or en dash anywhere in the panel", noDash(f.text), f.text);
    await shot("first-run");
    // keyboard: Tab from the heading reaches the primary button
    let reached = false;
    for (let i = 0; i < 30 && !reached; i++) { await page.keyboard.press("Tab"); reached = await page.evaluate(() => /Look around in Demo/.test((document.activeElement && document.activeElement.textContent) || "")); }
    ok("  the panel is reachable by keyboard: Tab arrives at 'Look around in Demo'", reached);
    // Copy
    await page.locator(`.fr-item[data-key="gh_auth"] .fr-fix sl-button`).click(); await sleep(300);
    const c1 = await page.evaluate(() => ({copied: window.__copied.slice(), toast: [...document.querySelectorAll("sl-alert")].map(a => a.textContent).join(" ")}));
    ok("  Copy writes exactly that one command to the clipboard and says so", c1.copied.length === 1 && c1.copied[0] === "gh auth login" && /Copied/.test(c1.toast), JSON.stringify(c1));
    await page.evaluate(() => { window.__refuse = true; });
    await page.locator(`.fr-item[data-key="gh_auth"] .fr-fix sl-button`).click(); await sleep(400);
    const c2 = await page.evaluate(() => ({sel: String(getSelection()), toast: [...document.querySelectorAll("sl-alert")].map(a => a.textContent).join(" "), copied: window.__copied.length}));
    ok("  if the browser refuses, the command is selected in its box and the page says to press Cmd+C or Ctrl+C", c2.sel === "gh auth login" && /Cmd\+C or Ctrl\+C/.test(c2.toast) && c2.copied === 1, JSON.stringify(c2));
    await page.evaluate(() => { window.__refuse = false; });
    // Calm and a phone width, with the panel up
    await page.evaluate(() => { document.querySelector(".js-calm").click(); }); await sleep(500);
    ok("  Calm mode keeps the panel and its one primary button", await here(".fr-card") && (await page.locator("#view sl-button[variant=primary]").count()) === 1);
    await page.evaluate(() => { document.querySelector(".js-calm").click(); }); await sleep(300);
    await page.setViewportSize({width: 390, height: 844}); await sleep(500);
    ok("  at 390px wide the page has no sideways scroll", await wide(), await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]));
    await shot("first-run-phone");
    await page.setViewportSize({width: 1280, height: 1000}); await sleep(300);
    // Look around in Demo
    await page.locator(".fr-card sl-button[variant=primary]").click();
    ok("  'Look around in Demo' switches Demo on and the panel goes away", await gone(".fr-card") && await page.evaluate(() => S.demo && S.demo.on === true));
    await sleep(600);
    ok("  the Demo banner is showing", await page.evaluate(() => !document.querySelector("#demo-banner").hidden));
    await shot("demo-after-first-run");
    await page.reload(); await ready(); await sleep(1200);
    ok("  after a reload the panel stays away and Demo is still on", (await page.locator(".fr-card").count()) === 0 && await page.evaluate(() => S.demo && S.demo.on === true));
  } else {
    // ================= the guided attach panel =================
    await page.evaluate(async () => { await post("/api/demo", {on: false}); await tick(); }); await sleep(500);
    await page.reload(); await ready(); await sleep(1000);
    ok("Demo is off again and the first-run panel does not come back (it was seen)", (await page.locator(".fr-card").count()) === 0 && await page.evaluate(() => !(S.demo && S.demo.on) && S.first_run === false));
    await page.evaluate(() => openAttach());
    ok("the attach panel opens on step 1 of 5: one labelled field, an example, the privacy sentence and the home-folder hint", await here("#at-path"));
    const s1 = await page.evaluate(() => ({title: document.querySelector("#dtitle").textContent, body: document.querySelector("#dbody").innerText.replace(/\s+/g, " "),
      steps: [...document.querySelectorAll("#at-steps li")].map(li => li.textContent.replace(/^Done: /, "").trim()), cur: [...document.querySelectorAll("#at-steps li")].findIndex(li => li.getAttribute("aria-current") === "step"),
      label: document.querySelector("#at-path").label, help: document.querySelector("#at-path").getAttribute("help-text"), ph: document.querySelector("#at-path").placeholder}));
    ok("  steps are Folder, Scan, Missing docs, Crew, Ready, and Folder is the current one", s1.steps.join("|") === "Folder|Scan|Missing docs|Crew|Ready" && s1.cur === 0, JSON.stringify(s1.steps) + s1.cur);
    ok("  it says 'Nothing is read until you press Scan' and 'never scans your home folder', and that the folder is under the home folder and not hidden, with an example", /Nothing is read until you press Scan\. Quarterdeck never scans your home folder\./.test(s1.body) && /under your home folder and not a hidden folder/.test(s1.help) && /~\/Projects\/my-app/.test(s1.ph + s1.help) && s1.label === "Project folder", JSON.stringify(s1));
    ok("  and it has no em or en dash", noDash(s1.body + s1.help), s1.body);
    await shot("attach-step1");
    const tryPath = async p => {
      await page.evaluate(v => { const el = document.querySelector("#at-path"); el.value = v; }, p);
      await page.locator('#dbody sl-button[variant=primary]').first().click(); await sleep(900);
      return page.evaluate(() => ({help: document.querySelector("#at-path").helpText, out: document.querySelector("#at-out").innerText.trim(), h2: !!document.querySelector("#at-h2")}));
    };
    const bads = [
      ["an empty field", "   ", /Paste a folder path first/],
      ["a folder that does not exist", "~/projects/not-there/", /nothing at that path/],
      ["a file instead of a folder", `${HOME}/projects/sample-react/package.json`, /is a file, not a folder/],
      ["a hidden folder", `${HOME}/.hidden-proj`, /hidden folder/],
      ["a folder outside the allowed places", OUTSIDE, /outside the places/],
      ["the home folder itself, written ~", "~", /whole folder of projects/],
      ["the home folder itself, quoted with a slash", `"${HOME}/"`, /whole folder of projects/],
    ];
    for (const [label, p, re] of bads) {
      const r = await tryPath(p);
      ok(`  ${label}: one plain line under the field, and nothing is scanned`, re.test(r.help) && !/\n/.test(r.help) && r.help.length < 400 && r.out === "" && !r.h2 && noDash(r.help), JSON.stringify(r));
    }
    ok("  after those, no profile exists and nothing is registered", !fs.existsSync(path.join(DATA, "state", "profiles")) && !fs.existsSync(path.join(DATA, "config", "projects.json")) || (fs.readdirSync(path.join(DATA, "state", "profiles")).length === 0));
    // the pasted forms that are fine: spaces round it, quotes, a trailing slash, ~ and a folder with a space in its name
    const sample = `${HOME}/projects/sample-react`;
    const forms = [["quotes, spaces and a trailing slash", `  "${sample}/"  `], ["single quotes", `'${sample}'`], ["a ~ path", "~/projects/sample-react"], ["a folder with a space in its name", `${HOME}/projects/my app`], ["a space written the way a terminal does", `${HOME}/projects/my\\ app/`]];
    for (const [label, p] of forms) {
      const r = await tryPath(p);
      ok(`  ${label}: scanned as the folder it names`, r.h2 && r.help === "", JSON.stringify(r));
    }
    // a clean scan of the sample app, then each step in order
    await tryPath(`"${sample}/"`);
    ok("scanning the sample app shows steps 2, 3, 4 and 5 below, in order, each with its heading", await here("#at-stack") && (await page.locator("#at-out h3").allInnerTexts()).map(t => t.slice(0, 11)).join("|") === "Step 2 of 5|Step 3 of 5|Step 4 of 5|Step 5 of 5", await page.locator("#at-out h3").allInnerTexts());
    const sc = await page.evaluate(() => ({stack: document.querySelector("#at-stack").innerText, facts: [...document.querySelectorAll("#at-h2 ~ ul")][0].innerText.replace(/\s+/g, " "), docs: document.querySelector("#at-docs").innerText,
      docCmds: [...document.querySelectorAll("#at-out .fr-cmd")].map(c => c.textContent), docCopy: document.querySelectorAll("#at-out .fr-fix sl-button").length,
      duties: [...document.querySelectorAll("#at-out [data-ad]")].map(s => [s.getAttribute("data-ad"), s.checked]), cur: [...document.querySelectorAll("#at-steps li")].filter(li => li.classList.contains("now")).map(li => li.textContent.trim()),
      reasons: document.querySelector("#at-h4").parentElement.innerText.replace(/\s+/g, " "), checklist: document.querySelectorAll("#at-ready .rd-item").length, registered: S.projects.length}));
    ok("  step 2 gives the stack sentence and the verify, build and lint lines", /React/i.test(sc.stack) && /Verify/.test(sc.facts) && /Build/.test(sc.facts) && /Lint/.test(sc.facts), JSON.stringify([sc.stack, sc.facts]));
    ok("  step 3 says what is present and missing, and offers the scribe commands (with Copy) without writing anything", /present:/.test(sc.docs) && (!/missing/.test(sc.docs) || (sc.docCmds.some(c => /^qtdeck docs sample-react (readme|architecture)$/.test(c)) && sc.docCopy === sc.docCmds.length)), JSON.stringify([sc.docs, sc.docCmds]));
    ok("  step 4 lists the duties with a switch each (some on with a reason, the suggested ones off) and the reason for the set", sc.duties.length >= 3 && sc.duties.some(d => d[1]) && sc.duties.some(d => !d[1]) && /on, with the reason/i.test(sc.reasons), JSON.stringify(sc.duties));
    ok("  step 5 shows the checklist as it would be, and nothing is registered yet", sc.checklist >= 5 && sc.registered === 0 && !fs.existsSync(path.join(DATA, "config", "projects.json")), JSON.stringify([sc.checklist, sc.registered]));
    await shot("attach-scan");
    await page.setViewportSize({width: 390, height: 844}); await sleep(500);
    ok("  at 390px wide neither the page nor the panel scrolls sideways", await wide() && await page.evaluate(() => { const b = document.querySelector("#dbody"); return b.scrollWidth <= b.clientWidth + 1; }), await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth, document.querySelector("#dbody").scrollWidth, document.querySelector("#dbody").clientWidth]));
    await shot("attach-scan-phone");
    await page.setViewportSize({width: 1280, height: 1000}); await sleep(300);
    // switch one suggested duty on, then attach
    const sugg = sc.duties.find(d => !d[1]);
    await page.evaluate(n => { document.querySelector(`#at-out [data-ad="${n}"]`).checked = true; }, sugg[0]);
    await page.evaluate(() => { const b = document.querySelector("#at-ready sl-button[variant=primary]"); b.click(); b.click(); });      // a double click
    ok("Attach registers the project and the panel moves to step 5, Ready, with the real checklist", await here("#at-next") && (await text("#dtitle")) === "Attached sample-react", await text("#dtitle"));
    await sleep(800);
    ok("  a double click on it sent one attach, and no error toast sits beside the success", attaches.length === 1 && (await page.locator("sl-alert[variant=danger]").count()) === 0, attaches.length);
    const af = await page.evaluate(() => ({cur: [...document.querySelectorAll("#at-steps li")].filter(li => li.getAttribute("aria-current") === "step").map(li => li.textContent.trim()), rows: document.querySelectorAll("#dbody .rd-item").length,
      next: document.querySelector("#at-next").innerText, primary: [...document.querySelectorAll("#dbody sl-button[variant=primary]")].map(b => b.textContent.trim()), projects: S.projects.map(p => p.name), duties: (S.projects[0] || {}).duties}));
    ok("  step 5 is current, the checklist rows are there, and there is exactly one next action and one primary button", af.cur.join() === "Ready" && af.rows >= 5 && /^Next: \S/.test(af.next) && af.primary.length === 1 && noDash(af.next), JSON.stringify(af));
    ok("  the project is registered, and the duty the person switched on is on", af.projects.join() === "sample-react" && (af.duties || []).includes(sugg[0]), JSON.stringify([af.projects, af.duties, sugg]));
    ok("  its profile now exists in the data folder", fs.existsSync(path.join(DATA, "state", "profiles", "sample-react.json")));
    await shot("attach-ready");
    // Home and the Ready card show one next action only
    await page.evaluate(() => { closeDrawer(); dockGo("overview"); }); await sleep(1500);
    const hn = await page.evaluate(() => ({cards: document.querySelectorAll(".next-card").length, primary: document.querySelectorAll(".next-card sl-button[variant=primary]").length, firstrun: !!document.querySelector(".fr-card")}));
    ok("Home shows at most one next action, with one primary button, and no first-run panel", hn.cards <= 1 && hn.primary === hn.cards && !hn.firstrun, JSON.stringify(hn));
    // the file-your-first-ticket and sessions-hook steps, with the checklist said to be ready (the real verify run needs an install from the registry, which this suite never does)
    const quiet = await page.evaluate(async () => {
      HR.at = Date.now() + 3600e3; HR.data = {"sample-react": {project: "sample-react", ready: true, items: [], next: {kind: "ticket", text: "File your first ticket: qtdeck ticket new sample-react \"<what you want built>\"", command: ""}}};
      S.attention = []; S.inbox = []; S.runs = []; S.live = {...S.live, hook_installed: true};
      render(); await new Promise(r => setTimeout(r, 300));
      const n = document.querySelector(".next-card");
      return n ? {tag: n.querySelector(".kicker").textContent.trim(), title: n.querySelector("h2").textContent.trim(), btns: [...n.querySelectorAll("sl-button")].map(b => [b.textContent.trim(), b.getAttribute("variant")])} : null;
    });
    if (quiet) {
      ok("a ready project with no tickets: the one next action is 'File your first ticket', one primary button", quiet.title === "File your first ticket" && quiet.btns.length === 1 && quiet.btns[0][0] === "File your first ticket" && quiet.btns[0][1] === "primary", JSON.stringify(quiet));
      await page.locator(".next-card sl-button").click(); await sleep(2500);
      ok("  pressing it opens the project and puts the cursor in the ticket box", await page.evaluate(() => !!document.querySelector("#tk-request") && sel === "sample-react" && (document.activeElement.id === "tk-request" || !!document.activeElement.closest("#tk-request"))), await page.evaluate(() => [sel, document.activeElement && document.activeElement.id]));
      await page.evaluate(() => { dockGo("overview"); }); await sleep(500);
      const hook = await page.evaluate(async () => {
        HR.data = {"sample-react": {project: "sample-react", ready: true, items: [], next: {kind: "ticket", text: "File your next ticket: qtdeck ticket new sample-react \"<x>\"", command: ""}}};
        S.live = {...S.live, hook_installed: false, install_command: "bash /opt/qd/bin/fleet-hook.sh install"}; render(); await new Promise(r => setTimeout(r, 300));
        const n = document.querySelector(".next-card");
        return n ? {title: n.querySelector("h2").textContent.trim(), cmd: (n.querySelector(".fr-cmd") || {}).textContent, btns: [...n.querySelectorAll("sl-button")].map(b => [b.textContent.trim(), b.getAttribute("variant")]), text: n.innerText.replace(/\s+/g, " ")} : null;
      });
      ok("with tickets filed and live work not connected: the one next action is 'Start the dashboard sessions hook', the install command in a box, one primary button that copies it", hook && hook.title === "Start the dashboard sessions hook" && hook.cmd === "bash /opt/qd/bin/fleet-hook.sh install" && hook.btns.length === 1 && hook.btns[0][1] === "primary" && noDash(hook.text), JSON.stringify(hook));
      await page.locator(".next-card sl-button").click(); await sleep(300);
      ok("  and pressing it copies that command", await page.evaluate(() => window.__copied[window.__copied.length - 1] === "bash /opt/qd/bin/fleet-hook.sh install"));
      await shot("home-next-hook");
      // something more urgent wins: the hook is not offered then
      const urgent = await page.evaluate(async () => { S.runs = [{at: new Date().toISOString(), project: "sample-react", duty: "shipwright", verdict: "ERROR", detail: "the checks would not start"}]; render(); await new Promise(r => setTimeout(r, 300)); const n = document.querySelector(".next-card"); return n ? n.querySelector("h2").textContent.trim() : ""; });
      ok("  a failed run is more urgent: then the hook is not what Home offers", urgent !== "Start the dashboard sessions hook" && urgent !== "File your first ticket", urgent);
    } else {
      ok("the quiet next action could be drawn (Home had something more urgent, so the check could not run)", false, JSON.stringify(hn));
    }
    // the Ready card: one next step, whichever it is
    const rc = await page.evaluate(async () => {
      openProject("sample-react", true); await new Promise(r => setTimeout(r, 1500));
      const d = rdData("sample-react");
      const out = {};
      for (const [k, text, hook] of [["first", "File your first ticket: x", true], ["next", "File your next ticket: x", false]]) {
        RD.data = {...d, ready: true, next: {kind: "ticket", text, command: ""}}; RD.show = true; RD.at = Date.now() + 3600e3;
        S.live = {...S.live, hook_installed: hook, install_command: "bash /opt/qd/bin/fleet-hook.sh install"}; render(); await new Promise(r => setTimeout(r, 400));
        const c = document.querySelector(".rd-card");
        out[k] = c ? {primary: [...c.querySelectorAll("sl-button[variant=primary]")].map(b => b.textContent.trim()), line: (c.querySelector("#rd-next-line") || {}).textContent, box: (c.querySelector(".fr-cmd") || {}).textContent || ""} : null;
      }
      return out;
    });
    ok("the Ready card of a ready project with no tickets has one primary button, 'File your first ticket'", rc.first && rc.first.primary.join() === "File your first ticket" && rc.first.box === "", JSON.stringify(rc.first));
    ok("  with tickets filed and no sessions hook, it has one primary button, 'Copy the install command', and the command in a box", rc.next && rc.next.primary.join() === "Copy the install command" && /fleet-hook\.sh install/.test(rc.next.box) && /^Next: Start the dashboard sessions hook/.test(rc.next.line), JSON.stringify(rc.next));
    await shot("ready-card");
    await page.evaluate(() => { document.querySelector(".js-calm").click(); openAttach(); }); await sleep(700);
    ok("Calm mode keeps the attach panel working", await here("#at-path") && (await page.locator("#at-steps li").count()) === 5);
  }
} catch (e) {
  ok("the page test ran to the end", false, String(e && e.stack || e).slice(0, 600));
}
await done();
