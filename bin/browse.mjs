// browse.mjs: the harness's own headless browser driver, used by the Pilot and the Lookout.
// A model never runs this and never gets a browser. It writes a plan as data; the duty validates the plan here
// and this file carries it out against the one local address the duty started, from a build of the pull request
// under the duty's own state folder. It cannot open any other address, and it is not pointed at anything of the
// owner's: only the app being checked, in a throwaway context.
//
//   node bin/browse.mjs check <plan.json>             validate only, no browser
//   node bin/browse.mjs run   <plan.json> <outdir>    flows of steps, pass or fail per flow
//   node bin/browse.mjs shoot <spec.json> <outdir>    one image per route and width
//   node bin/browse.mjs screen <screen.json>          is this text an app, or only an error screen (no browser)
//
// Prints one JSON object on stdout. Exit 0 = it ran (read the JSON), 2 = bad input, 3 = no browser available.
import {createRequire} from "node:module";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

export const MAX_STEPS = 25, MAX_FLOWS = 12, MAX_WAIT_MS = 3000, STEP_TIMEOUT_MS = 5000;
const OPS = ["goto", "click", "fill", "press", "expect_text", "expect_visible", "expect_url", "wait", "shot", "set_offline"];
const PATH_OK = /^\/[A-Za-z0-9._~\/\-?=&%#:+,]{0,300}$/;
const KEY_OK = /^[A-Za-z0-9+]{1,30}$/;
const NAME_OK = /^[a-z0-9-]{1,40}$/;
const str = (v, n) => typeof v === "string" && v.length > 0 && v.length <= n;

// One step is one plain object. Anything not listed here is refused, never guessed at.
export function validateStep(s) {
  if (!s || typeof s !== "object" || Array.isArray(s)) return "a step is an object";
  if (!OPS.includes(s.op)) return `unknown op ${JSON.stringify(s.op)}`;
  switch (s.op) {
    case "goto": return PATH_OK.test(s.path ?? "") && !s.path.startsWith("//") ? "" : "goto takes a path on the app, starting with one slash";
    case "click": return str(s.selector, 200) ? "" : "click needs a selector";
    case "fill": return str(s.selector, 200) && typeof s.value === "string" && s.value.length <= 200 ? "" : "fill needs a selector and a value up to 200 characters";
    case "press": return KEY_OK.test(s.key ?? "") ? "" : "press takes a key name";
    case "expect_text": return str(s.text, 200) && (s.selector === undefined || str(s.selector, 200)) ? "" : "expect_text needs text";
    case "expect_visible": return str(s.selector, 200) ? "" : "expect_visible needs a selector";
    case "expect_url": return str(s.contains, 200) ? "" : "expect_url needs contains";
    case "wait": return Number.isInteger(s.ms) && s.ms >= 0 && s.ms <= MAX_WAIT_MS ? "" : `wait is a whole number of milliseconds up to ${MAX_WAIT_MS}`;
    case "shot": return NAME_OK.test(s.name ?? "") ? "" : "shot needs a short lowercase name";
    case "set_offline": return typeof s.on === "boolean" ? "" : "set_offline needs on: true or false";
  }
  return "";
}

// A plan is {flows:[{seat,title,steps}]}. Returns {flows (the valid ones), errors (why the others were dropped)}.
export function validatePlan(plan) {
  const errors = [], flows = [];
  if (!plan || !Array.isArray(plan.flows)) return {flows, errors: ["a plan has a flows array"]};
  plan.flows.slice(0, MAX_FLOWS).forEach((f, i) => {
    if (!f || typeof f !== "object" || !str(f.title, 120) || !Array.isArray(f.steps) || f.steps.length === 0) { errors.push(`flow ${i + 1}: needs a title and steps`); return; }
    if (f.steps.length > MAX_STEPS) { errors.push(`flow ${i + 1}: more than ${MAX_STEPS} steps`); return; }
    for (const [k, s] of f.steps.entries()) { const e = validateStep(s); if (e) { errors.push(`flow ${i + 1} step ${k + 1}: ${e}`); return; } }
    if (!f.steps.some(s => s.op.startsWith("expect_"))) { errors.push(`flow ${i + 1}: nothing is expected at the end of it, so it proves nothing`); return; }
    const touches = Array.isArray(f.touches) ? f.touches.filter(t => str(t, 200)).slice(0, 5) : [];   // the changed files that put this flow on the list
    flows.push({seat: typeof f.seat === "string" ? f.seat.slice(0, 40) : "", title: f.title, touches, steps: f.steps});
  });
  if (plan.flows.length > MAX_FLOWS) errors.push(`only the first ${MAX_FLOWS} flows are kept`);
  return {flows, errors};
}

// Is what the browser is showing an app at all? A page that is only an error or configuration screen (short, with no form, input or
// navigation) or a blank page means the app could not start properly, and nothing that follows may be counted for or against the change.
export const ERROR_RX = /(configuration|config) error|missing .*(env|environment|variable|key)|cannot connect|failed to (load|fetch)|something went wrong|application error/i;
export function classifyScreen({text = "", forms = 0, inputs = 0, navs = 0, media = 0} = {}) {
  const t = String(text).replace(/\s+/g, " ").trim();
  if (t.length < 300 && forms + inputs + navs === 0) {
    if (ERROR_RX.test(t)) return {usable: false, reason: `the app shows '${t.slice(0, 120)}' on its first screen`};
    if (t.length < 3 && media === 0) return {usable: false, reason: "the app shows a blank page on its first screen"};
  }
  return {usable: true, reason: ""};
}
async function readScreen(page) {
  return page.evaluate(() => ({
    text: document.body ? document.body.innerText : "",
    forms: document.querySelectorAll("form").length, inputs: document.querySelectorAll("input,textarea,select").length,
    navs: document.querySelectorAll("nav,[role=navigation]").length, media: document.querySelectorAll("img,svg,canvas,video,iframe,picture").length,
  }));
}
// Looked at twice, a second apart: an app that renders on the client has not drawn anything the instant the page loads.
export async function probe(page) {
  await page.waitForLoadState("networkidle", {timeout: 3000}).catch(() => {});
  let s = await readScreen(page).catch(() => ({text: "", forms: 0, inputs: 0, navs: 0, media: 0}));
  let c = classifyScreen(s);
  if (!c.usable) { await page.waitForTimeout(1000); s = await readScreen(page).catch(() => s); c = classifyScreen(s); }
  return {...c, text: String(s.text).replace(/\s+/g, " ").trim().slice(0, 160)};
}

const slug = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "root";

async function launch(base) {
  let pw;
  try { pw = createRequire(import.meta.url)("playwright"); } catch { return {error: "playwright is not installed (run it where `npx playwright install chromium` has been done)"}; }
  try {
    // the renderer keeps its own sandbox (Playwright turns it off by default): the page is a pull request's code
    const browser = await pw.chromium.launch({executablePath: process.env.QUARTERDECK_CHROMIUM || undefined, chromiumSandbox: true});
    return {browser};
  } catch (e) { return {error: "no browser could be started: " + String(e.message).split("\n")[0]}; }
}

// Only the app's own address is reachable. Everything else the page asks for is refused, so a build under
// check cannot call out while it is looked at.
async function context(browser, base, viewport) {
  const ctx = await browser.newContext({viewport, serviceWorkers: "block", acceptDownloads: false, permissions: []});
  const origin = new URL(base).origin;
  await ctx.route("**/*", r => (r.request().url().startsWith(origin + "/") || r.request().url() === origin || r.request().url().startsWith("data:") ? r.continue() : r.abort()));
  // route() never sees a WebSocket (round 5: one reached another port with the page's data). Any socket not to the app's own host:port is answered
  // here and closed, never connected. A Playwright too old to do that is refused rather than run without it.
  if (typeof ctx.routeWebSocket !== "function") throw new Error("this Playwright cannot block WebSockets (1.48 or later is needed)");
  const host = new URL(base).host;
  await ctx.routeWebSocket(u => new URL(String(u)).host !== host, ws => ws.close());
  return ctx;
}

async function runStep(page, ctx, base, s, outdir, fi) {
  const t = {timeout: STEP_TIMEOUT_MS};
  switch (s.op) {
    case "goto": await page.goto(base + s.path, {waitUntil: "load", timeout: 15000}); break;
    case "click": await page.click(s.selector, t); break;
    case "fill": await page.fill(s.selector, s.value, t); break;
    case "press": await page.keyboard.press(s.key); break;
    case "expect_text": {
      const loc = s.selector ? page.locator(s.selector).first() : page.locator("body");
      await loc.waitFor({state: "attached", ...t});
      await page.waitForFunction(([sel, text]) => ((sel ? document.querySelector(sel) : document.body)?.innerText || "").includes(text), [s.selector || null, s.text], t);
      break;
    }
    case "expect_visible": await page.locator(s.selector).first().waitFor({state: "visible", ...t}); break;
    case "expect_url": await page.waitForURL(u => u.toString().includes(s.contains), t); break;
    case "wait": await page.waitForTimeout(s.ms); break;
    case "shot": await page.screenshot({path: path.join(outdir, `flow${fi + 1}-${s.name}.png`)}); break;
    case "set_offline": await ctx.setOffline(s.on); break;
  }
}

export async function run(plan, outdir) {
  const {flows, errors} = validatePlan(plan);
  const base = plan.base;
  const out = {base, dropped: errors, flows: []};
  fs.mkdirSync(outdir, {recursive: true});
  const {browser, error} = await launch(base);
  if (error) return {...out, error, code: 3};
  try {
    for (const [fi, f] of flows.entries()) {
      const ctx = await context(browser, base, {width: 1280, height: 800});
      const page = await ctx.newPage();
      const rec = {seat: f.seat, title: f.title, touches: f.touches, ok: true, steps: f.steps.length, failed_step: null, message: "", screenshot: "", first_screen: false, step_sig: ""};
      let firstUrl = null, stop = false;
      for (const [si, s] of f.steps.entries()) {
        try {
          await runStep(page, ctx, base, s, outdir, fi);
          if (s.op === "goto" && firstUrl === null) {
            firstUrl = page.url();
            const pr = await probe(page);
            rec.first_text = pr.text;
            if (!pr.usable && out.blocked === undefined) {
              const shot = path.join(outdir, `flow${fi + 1}-first-screen.png`);
              try { await page.screenshot({path: shot}); } catch { /* the page may be gone */ }
              out.blocked = {reason: pr.reason, screenshot: shot}; stop = true; break;
            }
          }
        }
        catch (e) {
          rec.ok = false; rec.failed_step = si + 1; rec.message = String(e.message).split("\n")[0].slice(0, 300);
          rec.first_screen = firstUrl === null || page.url() === firstUrl;
          rec.step_sig = [s.op, s.selector || s.text || s.contains || s.path || s.key || ""].join("|");
          const shot = path.join(outdir, `flow${fi + 1}-failed-step${si + 1}.png`);
          try { await page.screenshot({path: shot}); rec.screenshot = shot; } catch { /* the page may be gone */ }
          break;
        }
      }
      out.flows.push(rec);
      await ctx.close();
      if (stop) break;
    }
    // The same step failing on the first screen in every flow says the app (or the plans' idea of it) is not there, not that every flow found a defect.
    if (out.blocked === undefined && out.flows.length >= 2 && out.flows.every(r => !r.ok && r.first_screen && r.step_sig === out.flows[0].step_sig)) {
      out.blocked = {reason: `the same step fails on the first screen in every flow (${out.flows[0].step_sig.replace("|", " ")}); the first screen shows '${(out.flows[0].first_text || "").slice(0, 120)}'`, screenshot: out.flows[0].screenshot};
    }
  } finally { await browser.close(); }
  return out;
}

export async function shoot(spec, outdir) {
  const base = spec.base, routes = (spec.routes || ["/"]).slice(0, 10), widths = (spec.widths || [390, 768, 1280]).slice(0, 4);
  const out = {base, shots: []};
  for (const r of routes) if (!PATH_OK.test(r) || r.startsWith("//")) return {...out, error: `bad route ${JSON.stringify(r)}`, code: 2};
  if (!widths.every(w => Number.isInteger(w) && w >= 280 && w <= 2000)) return {...out, error: "bad widths", code: 2};
  fs.mkdirSync(outdir, {recursive: true});
  const {browser, error} = await launch(base);
  if (error) return {...out, error, code: 3};
  try {
    for (const route of routes) for (const w of widths) {
      const ctx = await context(browser, base, {width: w, height: Math.round(w * 1.6) > 1000 ? 900 : 844});
      const page = await ctx.newPage();
      const file = path.join(outdir, `${slug(spec.prefix || "shot")}-${slug(route)}-${w}.png`);
      try {
        const resp = await page.goto(base + route, {waitUntil: "load", timeout: 15000});
        await page.waitForLoadState("networkidle", {timeout: 3000}).catch(() => {});
        const pr = await probe(page);
        await page.screenshot({path: file, fullPage: true});
        out.shots.push({route, width: w, file, status: resp ? resp.status() : 0, unusable: pr.usable ? "" : pr.reason, text: pr.text});
      } catch (e) { out.shots.push({route, width: w, file: "", status: 0, error: String(e.message).split("\n")[0].slice(0, 200)}); }
      await ctx.close();
    }
  } finally { await browser.close(); }
  // Every picture the same error screen, or blank: the app did not render, and a picture of that is not a screen to judge.
  const taken = out.shots.filter(x => x.file);
  if (taken.length > 0 && taken.every(x => x.unusable)) out.blocked = {reason: taken[0].unusable, screenshot: taken[0].file};
  return out;
}

async function main() {
  const [cmd, input, outdir] = process.argv.slice(2);
  let data;
  try { data = JSON.parse(fs.readFileSync(input, "utf8")); } catch { console.log(JSON.stringify({error: "cannot read the input file", code: 2})); process.exit(2); }
  let out;
  if (cmd === "check") { const v = validatePlan(data); out = {ok: v.flows.length > 0 && v.errors.length === 0, flows: v.flows.length, errors: v.errors, valid: v.flows}; }
  else if (cmd === "screen") out = classifyScreen(data)
  else if (cmd === "run" && outdir) out = await run(data, outdir);
  else if (cmd === "shoot" && outdir) out = await shoot(data, outdir);
  else { console.log(JSON.stringify({error: "usage: browse.mjs check|run|shoot <input.json> [outdir]", code: 2})); process.exit(2); }
  console.log(JSON.stringify(out));
  process.exit(out.code === 3 ? 3 : out.code === 2 ? 2 : 0);
}
// compare real paths: on macOS /var and /tmp are symlinks, so the path it was started with and its own url differ
if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))) main();
