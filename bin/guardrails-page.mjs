// guardrails-page.mjs: the browser half of bin/selftest-guardrails.sh. It drives the real dashboard that suite started (QD_LINK is its one-time pairing link, QD_T its
// throwaway Quarterdeck, QD_PROJECT the project to open, QD_SHOTS where the pictures go) in headless Chromium and prints one line per check: "ok ...", "FAIL ..." or
// "skip ...". Nothing here goes to the internet, and nothing real is touched.
//   node bin/guardrails-page.mjs probe     exit 0 when a browser can start here, 3 when none can
import {createRequire} from "node:module";
import path from "node:path";
import fs from "node:fs";

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


const SHOTS = process.env.QD_SHOTS, LINK = process.env.QD_LINK, P = process.env.QD_PROJECT || "tp", T = process.env.QD_T;
const BASE = new URL(LINK).origin + "/", ADDR = BASE + "#/projects/projects?project=" + encodeURIComponent(P);
let bad = 0;
const ok = (label, cond, extra) => { if (cond) console.log("ok " + label); else { bad++; console.log("FAIL " + label + (extra !== undefined ? " | " + String(extra).slice(0, 500) : "")); } };
const ctx = await browser.newContext({viewport: {width: 1280, height: 1000}});
const problems = {console: [], page: [], requests: []};
const page = await ctx.newPage();
page.on("console", m => { if (m.type() === "error" && !/Failed to load resource.*status of 404/.test(m.text())) problems.console.push(m.text()); });
page.on("pageerror", e => problems.page.push(String(e.message)));
page.on("requestfailed", r => { const why = (r.failure() || {}).errorText || ""; if (!/ERR_ABORTED/.test(why)) problems.requests.push(r.url() + " " + why); });
page.on("response", r => { if (r.status() >= 400 && !/\/api\/project\/guardrails$/.test(r.url())) problems.requests.push(r.url() + " " + r.status()); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const shot = async name => { try { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({path: path.join(SHOTS, name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const reg = () => JSON.parse(fs.readFileSync(path.join(T, "config", "projects.json"), "utf8"))[P].guardrails;
const saveOff = () => page.evaluate(() => document.querySelector("#gr-save").disabled);
const fields = () => page.evaluate(() => [...document.querySelectorAll("#guardrails-slot .gr-in")].map(e => e.value));
const ready = async () => { await page.waitForSelector("#guardrails-slot .gr-locked", {state: "visible", timeout: 20000}); await sleep(300); };
const fill = async (sel, v) => { const i = page.locator(sel + " input"); await i.fill(v); };
const effective = async () => { await page.evaluate(() => { document.querySelector("#gr-eff").show(); }); await sleep(300); return (await page.locator("#gr-eff .gr-eff").evaluate(e => e.textContent)).trim(); };
const cardShot = async name => { try { await page.locator("#guardrails-slot").screenshot({path: path.join(SHOTS, name + ".png")}); } catch (e) { /* a picture is a bonus */ } };
const wide = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1 && document.body.scrollWidth <= window.innerWidth + 1);
const LOCK = ["Never merge a pull request.", "Never push to the default branch; every change goes on its own branch.", "Never touch .env files or anything that holds a secret."];
const done = async () => { await browser.close(); process.exit(bad ? 1 : 0); };

try {
  await page.goto("about:blank");
  await page.goto(LINK); await sleep(800);
  await page.goto(ADDR); await page.reload(); await ready();
  const lk = await page.evaluate(() => [...document.querySelectorAll("#guardrails-slot .gr-locked")].map(li => ({text: li.querySelector(".gr-t").firstChild.textContent.trim(), why: li.querySelector(".gr-why").textContent.trim(), icon: !!li.querySelector("sl-icon[name=lock]"),
    controls: li.querySelectorAll("input, button, sl-input, sl-button, sl-icon-button, textarea").length})));
  ok("the three locked rules are shown with a lock icon, their reason, and no field, remove or move control", lk.length === 3 && lk.every((x, i) => x.text === LOCK[i] && x.why.length > 20 && x.icon && x.controls === 0), JSON.stringify(lk));
  const f0 = await fields();
  ok("the project's own rules are labelled fields and the Save button starts disabled", f0.length === 1 && f0[0].startsWith("Follow the repository") && await saveOff()
    && (await page.locator("#gr-0").getAttribute("label")) === "Guardrail 1 for " + P, JSON.stringify(f0));
  const sizes = await page.evaluate(() => [...document.querySelectorAll("#gr-0 ~ .gr-tools sl-icon-button, .gr-tools sl-icon-button, #gr-add")].map(e => { const b = (e.shadowRoot && e.shadowRoot.querySelector("[part=base]") || e).getBoundingClientRect(); return [e.getAttribute("label") || e.id, Math.round(b.width), Math.round(b.height)]; }));
  ok("the small buttons have accessible names and 40px targets", sizes.length >= 3 && sizes.every(s => s[0] && s[2] >= 40 || s[0] === "gr-add") && ["Move guardrail 1 down", "Remove guardrail 1"].every(n => sizes.some(s => s[0] === n)), JSON.stringify(sizes));
  await shot("guardrails-01-start");

  await fill("#gr-new", "Keep each change small"); await page.locator("#gr-add").click(); await sleep(300);
  ok("Add puts the rule in the list and enables Save, and nothing is saved yet", (await fields()).join("|").endsWith("Keep each change small") && !(await saveOff()) && reg().length === 4);
  await page.locator("#gr-mv-1-up").click(); await sleep(300);
  let f = await fields();
  ok("move up puts it first", f[0] === "Keep each change small" && f.length === 2, JSON.stringify(f));
  await fill("#gr-0", "Keep each change small and say why"); await sleep(200);
  await page.locator("#gr-save").click(); await sleep(900);
  ok("Save lands in the registry file, in order, with the locked rules first", JSON.stringify(reg()) === JSON.stringify([...LOCK, "Keep each change small and say why", "Follow the repository's own AGENTS.md or CLAUDE.md where it has one."]), JSON.stringify(reg()));
  ok("  the Save button is disabled again and a toast says it was saved", await saveOff() && /Guardrails saved/.test(await page.evaluate(() => document.body.innerText + [...document.querySelectorAll("sl-alert")].map(a => a.textContent).join(" "))));
  const eff1 = await effective();
  ok("  What the crew receives shows the new list, exactly as the server sends it", eff1 === ["- " + LOCK.join("\n- "), "- Keep each change small and say why", "- Follow the repository's own AGENTS.md or CLAUDE.md where it has one."].join("\n"), eff1);
  await shot("guardrails-02-saved"); await cardShot("guardrails-card-saved");

  await page.reload(); await ready();
  ok("after a reload the page shows the same list", JSON.stringify(await fields()) === JSON.stringify(["Keep each change small and say why", "Follow the repository's own AGENTS.md or CLAUDE.md where it has one."]));

  await page.locator("#gr-rm-0").click(); await sleep(300);
  ok("remove takes it out of the list and Save is enabled", (await fields()).length === 1 && !(await saveOff()));
  await page.locator("#gr-save").click(); await sleep(900);
  const eff2 = await effective();
  ok("Save again: What the crew receives changes and the registry file has the change", !eff2.includes("Keep each change small") && eff2 !== eff1 && !reg().includes("Keep each change small and say why") && reg().slice(0, 3).join() === LOCK.join(), eff2);

  await fill("#gr-new", "token ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"); await page.locator("#gr-add").click(); await sleep(300);
  await page.locator("#gr-save").click(); await sleep(900);
  const err = await page.evaluate(() => (document.querySelector("#guardrails-slot [data-error]") || {}).helpText || "");
  ok("a refused rule shows the server's plain reason under a field, and the registry is unchanged", /password, key or token/.test(err) && reg().length === 4, err);
  await page.reload(); await ready();

  await page.evaluate(() => toggleCalm(true)); await sleep(600);
  const calm = await page.evaluate(() => ({locked: [...document.querySelectorAll("#guardrails-slot .gr-locked")].filter(e => e.offsetParent !== null).length, fields: document.querySelectorAll("#guardrails-slot .gr-in").length, save: !!document.querySelector("#gr-save"),
    why: [...document.querySelectorAll("#guardrails-slot .gr-why")].filter(e => e.offsetParent !== null).length, purpose: [...document.querySelectorAll("#guardrails-slot .hint")].filter(e => e.offsetParent !== null).length}));
  ok("Calm mode keeps the locked rules and the editor and hides the explanations", calm.locked === 3 && calm.fields === 1 && calm.save && calm.why === 0 && calm.purpose === 0, JSON.stringify(calm));
  await shot("guardrails-03-calm");
  await page.evaluate(() => toggleCalm(false)); await sleep(300);

  await page.setViewportSize({width: 390, height: 844}); await sleep(500);
  ok("at 390px wide there is no sideways scroll", await wide());
  await shot("guardrails-04-390"); await cardShot("guardrails-card-390");
  problems.console = problems.console.filter((m, i) => !(i === 0 && /status of 400/.test(m)));      // the one refused save above is a 400 on purpose
  ok("no console errors, no page errors, no failed requests", !problems.console.length && !problems.page.length && !problems.requests.length, JSON.stringify(problems));
} catch (e) {
  ok("the page test ran to the end", false, e && e.stack);
}
await done();
