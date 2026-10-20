// a11y-check.mjs: an accessibility checker for the dashboard that needs nothing from the internet (axe-core is not vendored).
// It starts its own throwaway dashboard (a temp QUARTERDECK_HOME, a free port, pairing through the one-time link), opens it in
// Playwright's Chromium, and checks every view with the browser's own accessibility tree (CDP) plus the DOM.
//
//   node bin/a11y-check.mjs [--views overview,crew] [--themes dark,light] [--calm both|off|on] [--size 1280x900]
//                           [--focus] [--flows] [--json out.json] [--quick]
//   --focus  also tabs through every view and checks that each stop shows a focus indicator (pixel difference)
//   --flows  also checks the skip link, the dialog and drawer behaviour (trap, Esc, focus return) and the Brain's Esc
//   --quick  three views, dark only, no focus walk: what selftest runs
//
// Rules: name (every control has an accessible name), ids (unique), headings (one h1, no skipped level), landmarks, img-alt, aria (valid
// roles, attributes and references; nothing focusable inside aria-hidden), tabindex (none positive), contrast (text >= 4.5:1, large 3:1),
// select-popup (every sl-select list opens at its control, inside the viewport, clear of the nav rail), focus (a visible indicator on every tab stop; the ring colour is >= 3:1 on every surface), skip, dialogs, brain-esc.
// Exit 0 clean, 1 findings, 3 no Playwright or no browser (the JSON says so; selftest treats that as a skip, never a pass).
import {createRequire} from "node:module";
import {spawn, spawnSync} from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import net from "node:net";
import path from "node:path";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i < 0 ? d : (process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[i + 1] : true); };
const QUICK = process.argv.includes("--quick");
const ALL_VIEWS = ["overview", "projects", "brain", "inbox", "missions", "prs", "board", "timeline", "operations", "ledger", "spend", "log", "crew", "fleet", "connections", "documents", "panels", "notes", "showcase", "settings"];
// a view may name a project to be on: "missions@saltpan-blog" is the Missions page with that Demo project chosen (a project with no GitHub repo, so the repo options and the tickets list are drawn);
// "projects@wayfarer-web" is that project's own page (the Projects overview when no project is named)
const VIEWS = String(arg("views", QUICK ? "overview,projects,projects@wayfarer-web,crew,settings,missions@saltpan-blog" : ALL_VIEWS.join(",") + ",projects@wayfarer-web,projects@saltpan-blog,missions@saltpan-blog,missions@wayfarer-web")).split(",");
// the pages that have a project scope, and so show the project select and the scope chip; every other page shows neither (see Navigation, the scope table, in dashboard/UI.md)
const SCOPED = new Set(["projects", "inbox", "missions", "prs", "board", "ledger", "timeline", "operations", "log", "crew", "fleet", "panels", "documents", "notes"]);
const THEMES = String(arg("themes", QUICK ? "dark" : "dark,light")).split(",");
const CALMS = { both: [false, true], off: [false], on: [true] }[String(arg("calm", QUICK ? "off" : "both"))] || [false];
const SEED = arg("seed-agents", false);      // "one" | "all": no Demo; a made-up registry whose project has 3 agent files, so the Crew page's own-agents section is measured
const [W, H] = String(arg("size", "1500x900")).split("x").map(Number);
const FOCUS = !!arg("focus", false) && !QUICK, FLOWS = !!arg("flows", false) || QUICK;

function load() {
  const req = createRequire(import.meta.url), tries = [];
  if (process.env.QD_PLAYWRIGHT_PATH) tries.push(createRequire(path.join(process.env.QD_PLAYWRIGHT_PATH, "x.js")));
  tries.push(req);
  for (const r of tries) for (const n of ["playwright", "playwright-core"]) { try { return r(n); } catch (e) { /* next */ } }
  return null;
}
const pw = load();
if (!pw) { console.log(JSON.stringify({skipped: true, why: "playwright is not installed (npm i playwright; npx playwright install chromium)"})); process.exit(3); }
let browser;
try { browser = await pw.chromium.launch({headless: true, ...(process.env.QD_CHROME ? {executablePath: process.env.QD_CHROME} : {})}); }
catch (e) { console.log(JSON.stringify({skipped: true, why: "no browser: " + String(e.message).split("\n")[0]})); process.exit(3); }

// ---- a throwaway dashboard ----
const home = fs.mkdtempSync(path.join(os.tmpdir(), "qd-a11y-"));
const port = await new Promise(r => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => r(p)); }); });
if (SEED) {
  const pdir = path.join(home, "fakeproj"), ad = path.join(pdir, ".claude", "agents"); fs.mkdirSync(ad, {recursive: true}); fs.mkdirSync(path.join(home, "config"), {recursive: true});
  fs.writeFileSync(path.join(home, ".quarterdeck-home"), "");
  for (const [n, d, m] of [["code-critic", "Reviews a diff and audits it for mistakes.", "sonnet"], ["mason", "Implements features from an issue.", "opus"], ["pixel", "Design and mockup help for the UI.", ""]])
    fs.writeFileSync(path.join(ad, n + ".md"), `---\nname: ${n}\ndescription: ${d}\ntools: Read, Edit\nmodel: ${m}\n---\nPROMPT BODY\n`);
  fs.writeFileSync(path.join(home, "config", "projects.json"), JSON.stringify({"fake-app": {repo: "x/fake-app", path: pdir, summary: "A made-up project."}, "empty-app": {repo: "x/empty-app", path: path.join(home, "none"), summary: "No agents."}}));
}
const env = {...process.env, QUARTERDECK_HOME: home, QUARTERDECK_DASHBOARD_PORT: String(port)};
const srv = spawn("python3", [path.join(ROOT, "bin", "dashboard.py")], {env, stdio: "ignore"});
const done = async code => { try { await browser.close(); } catch (e) { /* closed */ } srv.kill(); try { fs.rmSync(home, {recursive: true, force: true}); } catch (e) { /* gone */ } process.exit(code); };
for (let i = 0; i < 60; i++) { try { const r = await fetch(`http://127.0.0.1:${port}/api/session`); if (r.status) break; } catch (e) { /* not yet */ } await new Promise(r => setTimeout(r, 250)); }
const link = spawnSync("python3", [path.join(ROOT, "bin", "dashboard.py"), "link"], {env, encoding: "utf8"}).stdout.trim();
if (!link.startsWith("http")) { console.log("could not get a pairing link"); await done(2); }

const ctx = await browser.newContext({viewport: {width: W, height: H}});
const page = await ctx.newPage();
await page.goto("about:blank");
await page.goto(link);
await page.waitForFunction(() => document.querySelector("#view") && document.querySelector("#view").children.length > 0, null, {timeout: 20000}).catch(() => {});
if (!SEED) await page.evaluate(async () => { await post("/api/demo", {on: true}); await tick(); });
else await page.evaluate(async all => { await tick(); sel = all === "all" ? "" : "fake-app"; localStorage.setItem("quarterdeck.project", sel); await tick(); }, SEED);
await page.waitForTimeout(600);
const cdp = await ctx.newCDPSession(page);
await cdp.send("Accessibility.enable"); await cdp.send("DOM.enable");

const issues = [];
const add = (rule, where, detail, ctxo) => issues.push({rule, view: ctxo.view, theme: ctxo.theme, calm: ctxo.calm, where, detail});

// ---- in-page DOM checks (ids, headings, img, aria, tabindex, landmarks, contrast) ----
function inPage(opts) {
  const out = [];
  const say = (rule, where, detail) => out.push({rule, where, detail});
  const desc = el => { let s = el.localName || "?"; if (el.id) s += "#" + el.id; if (el.classList && el.classList.length) s += "." + [...el.classList].slice(0, 2).join("."); const t = (el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("label"))) || (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 26); return s + (t ? ` "${t}"` : ""); };
  const parentOf = el => el.assignedSlot || el.parentElement || (el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null);
  const roots = [document], all = [];
  const walk = r => { for (const el of r.querySelectorAll("*")) { all.push(el); if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); } } };
  walk(document);
  const shown = el => { try { return el.checkVisibility({checkOpacity: false, checkVisibilityCSS: true}) && el.getBoundingClientRect().width > 0; } catch (e) { return false; } };
  const inClosedModal = el => { for (let p = el; p; p = parentOf(p)) if ((p.localName === "sl-drawer" || p.localName === "sl-dialog") && !p.open) return true; return false; };
  const openModal = [...document.querySelectorAll("sl-drawer,sl-dialog")].find(d => d.open);
  // ids
  for (const r of roots) { const seen = new Map(); for (const el of r.querySelectorAll("[id]")) { if (seen.has(el.id)) say("ids", desc(el), "duplicate id " + el.id); seen.set(el.id, el); } }
  // headings, only what is on screen
  const hs = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]")].filter(h => shown(h) && !inClosedModal(h) && !h.closest("[hidden]") && (!openModal || openModal.contains(h) === !!openModal));
  const lvl = h => +(h.getAttribute("aria-level") || (/^h\d$/.test(h.localName) ? h.localName[1] : 2));
  const page = hs.filter(h => !h.closest("sl-drawer,sl-dialog"));
  if (!openModal) {
    const h1 = page.filter(h => lvl(h) === 1);
    if (h1.length !== 1) say("headings", "page", h1.length + " h1 on the page (want exactly one): " + h1.map(desc).join(" | "));
  }
  for (const group of [page, hs.filter(h => h.closest("sl-drawer,sl-dialog"))]) {
    let prev = 0;
    for (const h of group) { const l = lvl(h); if (prev && l > prev + 1) say("headings", desc(h), `h${prev} followed by h${l}`); prev = l; }
  }
  // images
  for (const el of all) {
    if (el.localName === "img" && !el.hasAttribute("alt") && shown(el)) say("img-alt", desc(el), "img without alt");
    if (el.getAttribute && el.getAttribute("role") === "img" && !el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby") && shown(el)) say("img-alt", desc(el), "role=img without a name");
  }
  // aria
  const ROLES = new Set("alert alertdialog application article banner button cell checkbox columnheader combobox complementary contentinfo definition dialog directory document feed figure form grid gridcell group heading img link list listbox listitem log main marquee math menu menubar menuitem menuitemcheckbox menuitemradio navigation none note option presentation progressbar radio radiogroup region row rowgroup rowheader scrollbar search searchbox separator slider spinbutton status switch tab table tablist tabpanel term textbox timer toolbar tooltip tree treegrid treeitem".split(" "));
  const ATTRS = new Set("activedescendant atomic autocomplete busy checked colcount colindex colspan controls current describedby description details disabled dropeffect errormessage expanded flowto grabbed haspopup hidden invalid keyshortcuts label labelledby level live modal multiline multiselectable orientation owns placeholder posinset pressed readonly relevant required roledescription rowcount rowindex rowspan selected setsize sort valuemax valuemin valuenow valuetext".split(" "));
  const REFS = ["aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant", "aria-errormessage", "aria-details", "aria-flowto"];
  const focusable = el => el.matches && el.matches("a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex]:not([tabindex='-1']),sl-button,sl-icon-button,sl-input,sl-select,sl-switch,sl-checkbox,sl-textarea,sl-tab,sl-details") && !el.disabled;
  for (const el of all) {
    if (!el.attributes) continue;
    const root = el.getRootNode();
    const r = el.getAttribute("role");
    if (r && !r.split(/\s+/).some(x => ROLES.has(x))) say("aria", desc(el), "unknown role " + r);
    for (const a of el.attributes) {
      if (!a.name.startsWith("aria-")) continue;
      if (!ATTRS.has(a.name.slice(5))) say("aria", desc(el), "unknown attribute " + a.name);
      if (REFS.includes(a.name)) for (const id of a.value.split(/\s+/).filter(Boolean)) if (!(root.getElementById ? root.getElementById(id) : root.querySelector("#" + CSS.escape(id)))) say("aria", desc(el), `${a.name} points at #${id}, which is not there`);
    }
    if (el.getRootNode() === document && el.getAttribute("aria-hidden") === "true" && (focusable(el) || el.querySelector("a[href],button,input,select,textarea,[tabindex]:not([tabindex='-1']),sl-button,sl-input")) && shown(el)) say("aria", desc(el), "focusable content inside aria-hidden");
    const ti = el.getAttribute("tabindex");
    if (ti !== null && +ti > 0) say("tabindex", desc(el), "positive tabindex " + ti);
    if (/^(div|span)$/.test(el.localName) && (el.hasAttribute("data-on-click") || el.hasAttribute("onclick")) && !r && ti === null) say("keyboard", desc(el), "a click action on a div or span with no role and no tabindex");
  }
  // landmarks
  const lm = { banner: 0, main: 0, navigation: [], complementary: [] };
  for (const el of document.querySelectorAll("header,main,nav,aside,[role=banner],[role=main],[role=navigation],[role=complementary]")) {
    if (!shown(el)) continue;
    const role = el.getAttribute("role") || ({ header: el.closest("article,aside,main,nav,section") ? "" : "banner", main: "main", nav: "navigation", aside: "complementary" })[el.localName];
    if (role === "banner") lm.banner++; else if (role === "main") lm.main++;
    else if (role === "navigation" || role === "complementary") lm[role].push(el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || "");
  }
  if (lm.banner > 1) say("landmarks", "page", lm.banner + " banner landmarks (want at most 1; the Brain has none, its toolbar stands in)");
  if (lm.main !== 1) say("landmarks", "page", lm.main + " main landmarks (want 1)");
  for (const k of ["navigation", "complementary"]) { if (lm[k].length > 1 && lm[k].some(n => !n)) say("landmarks", k, "more than one, and one has no label"); if (new Set(lm[k]).size !== lm[k].length) say("landmarks", k, "two share a label"); }
  // contrast
  if (opts.contrast) {
    const parse = s => { const m = /rgba?\(([^)]+)\)/.exec(s); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
    const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    const bgOf = el => {   // the colour behind this element's text, or null when it sits on an image, a gradient or a canvas
      const layers = [];
      for (let p = el; p; p = parentOf(p)) {
        const cs = getComputedStyle(p);
        if (p.localName === "canvas") return null;
        if (cs.backgroundImage && cs.backgroundImage !== "none") return null;
        const c = parse(cs.backgroundColor);
        if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
      }
      let base = { r: 255, g: 255, b: 255, a: 1 };
      if (!layers.length || layers[layers.length - 1].a < 1) base = parse(getComputedStyle(document.documentElement).backgroundColor); if (!base || base.a === 0) base = parse(getComputedStyle(document.body).backgroundColor);
      let c = base || { r: 255, g: 255, b: 255, a: 1 };
      for (let i = layers.length - 1; i >= 0; i--) c = over(layers[i], c);
      return c;
    };
    const seen = new Set();
    const consider = (el, text) => {
      if (!text.trim() || !shown(el) || inClosedModal(el) || el.closest("canvas,.brain-overlay,.sr-only,[aria-hidden=true]") || (openModal && !openModal.contains(el) && !(el.getRootNode() instanceof ShadowRoot && openModal.contains(el.getRootNode().host)))) return;
      let off = false;
      for (let p = el; p; p = parentOf(p)) { if (p.hasAttribute && (p.hasAttribute("disabled") || p.getAttribute("aria-disabled") === "true")) { off = true; break; } }
      if (off) return;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight * 3) return;
      let fg = parse(cs.color), bg = bgOf(el);
      if (!fg || !bg) return;
      let op = 1; for (let p = el; p; p = parentOf(p)) { const o = +getComputedStyle(p).opacity; if (o < 1) op *= o; }
      fg = over({ ...fg, a: fg.a * op }, bg);
      const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700, large = size >= 24 || (size >= 18.66 && bold);
      window.__ctN = (window.__ctN || 0) + 1; const cr = ratio(fg, bg), need = large ? 3 : 4.5;
      if (cr < need) { const k = desc(el) + cr.toFixed(2); if (!seen.has(k)) { seen.add(k); say("contrast", desc(el), `${cr.toFixed(2)}:1 (needs ${need}) ${cs.color} on rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})`); } }
    };
    for (const el of all) {
      if (/^(script|style|svg|path|sl-icon)$/.test(el.localName)) continue;
      let own = ""; for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
      if (own.trim()) consider(el, own);
    }
  }
  // the one rule set (dashboard/UI.md): one font, no text under 12px, controls at least 40px where a finger reaches them
  if (opts.ui) {
    const fams = new Map();
    const touch = innerWidth <= 900 || matchMedia("(pointer:coarse)").matches;
    const ctl = /^(button|sl-button|sl-icon-button|sl-select|sl-input|sl-switch|sl-tab|sl-checkbox)$/;
    for (const el of all) {
      if (/^(script|style|svg|path|sl-icon|canvas)$/.test(el.localName) || !shown(el) || inClosedModal(el)) continue;
      const cs = getComputedStyle(el), own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
      if (own) {
        const f = cs.fontFamily.split(",")[0].replace(/["']/g, "").trim(); if (!fams.has(f)) fams.set(f, desc(el));
        if (parseFloat(cs.fontSize) < 12) say("ui-small", desc(el), cs.fontSize + " text (the floor is 12px)");
      }
      if (touch && el.getRootNode() === document && (ctl.test(el.localName) || el.matches(".mlink.link,.mlink.title"))) {
        const r = el.getBoundingClientRect();
        if ((r.height < 39.5 || r.width < 39.5) && !el.closest("[hidden],.sr-only")) say("ui-target", desc(el), `${Math.round(r.width)}x${Math.round(r.height)} (the floor is 40x40)`);
      }
    }
    if (fams.size > 1) say("ui-font", "page", "more than one font: " + [...fams].map(([f, d]) => `${f} (${d})`).join(", "));
  }
  return out;
}

// the accessibility tree: every control has a name
async function axNames(ctxo) {
  const {nodes} = await cdp.send("Accessibility.getFullAXTree");
  const NEED = new Set(["button", "link", "textbox", "searchbox", "combobox", "checkbox", "switch", "radio", "tab", "menuitem", "slider", "spinbutton", "listbox", "option"]);
  const hits = [];
  for (const n of nodes) {
    if (n.ignored || !n.role || !NEED.has(n.role.value)) continue;
    const props = Object.fromEntries((n.properties || []).map(p => [p.name, p.value && p.value.value]));
    if (props.hidden || props.disabled) continue;
    if ((n.name && n.name.value || "").trim()) continue;
    if (n.role.value === "option" || n.role.value === "listbox") continue;     // options of a closed select
    hits.push(n);
  }
  for (const n of hits.slice(0, 30)) {
    let d = "";
    try { const {node} = await cdp.send("DOM.describeNode", {backendNodeId: n.backendDOMNodeId}); const a = node.attributes || []; const g = k => { const i = a.indexOf(k); return i < 0 ? "" : a[i + 1]; }; d = node.localName + (g("id") ? "#" + g("id") : "") + (g("class") ? "." + g("class").split(" ")[0] : "") + (g("aria-label") ? ` aria-label="${g("aria-label")}"` : ""); } catch (e) { d = "?"; }
    add("name", d, `${n.role.value} with no accessible name`, ctxo);
  }
}

// focus: tab through the view, one pixel comparison per stop
async function focusWalk(ctxo, maxStops) {
  await page.evaluate(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); window.scrollTo(0, 0); });
  await page.evaluate(() => { document.body.setAttribute("tabindex", "-1"); document.body.focus(); document.body.removeAttribute("tabindex"); });
  const stops = []; let prev = "", same = 0;
  for (let i = 0; i < maxStops; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
      if (!a || a === document.body) return null;
      let host = a; while (host.getRootNode() instanceof ShadowRoot) host = host.getRootNode().host;
      const r = (host.localName.startsWith("sl-") ? host : a).getBoundingClientRect();
      const s = a.localName + (a.id ? "#" + a.id : "") + (a.className && typeof a.className === "string" ? "." + a.className.split(" ")[0] : "");
      let fixed = false; for (let p = host; p; p = p.parentElement || (p.getRootNode() instanceof ShadowRoot ? p.getRootNode().host : null)) if (getComputedStyle(p).position === "fixed") { fixed = true; break; }
      const label = host.getAttribute("aria-label") || host.getAttribute("label") || (host.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30);
      return {key: s + "|" + Math.round(r.left) + "," + Math.round(r.top), desc: host.localName + (host.id ? "#" + host.id : "") + ` "${label}"`, x: r.left, y: r.top, fixed, ay: r.top + scrollY, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight, tiny: r.width < 2 || r.height < 2};
    });
    if (!info) break;
    if (info.key === prev) { if (++same >= 2) { add("tab-order", info.desc, "focus stuck on one element (a keyboard trap?)", ctxo); break; } } else same = 0;
    prev = info.key;
    if (stops.length && stops[0].key === info.key) break;                           // wrapped round
    stops.push(info);
    if (info.tiny) { add("focus", info.desc, "a tab stop with no size", ctxo); continue; }
    const clip = {x: Math.max(0, info.x - 8), y: Math.max(0, info.y - 8), width: Math.min(info.vw, info.w + 16), height: Math.min(info.vh, info.h + 16)};
    if (clip.width < 1 || clip.height < 1 || info.y + info.h < 0 || info.y > info.vh) continue;
    await page.waitForTimeout(100);                                                   // the ring may fade in
    const el = await page.evaluateHandle(() => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; return a; });
    const shot = () => page.screenshot({clip}).catch(() => null);
    const focused = await shot();
    await el.evaluate(a => a.blur()); await page.waitForTimeout(60);
    const plain = await shot();
    if (focused && plain && focused.equals(plain)) {
      await el.evaluate(a => a.focus()); await page.waitForTimeout(150);          // once more, in case the poll redrew the page between the shots
      const again = await shot();
      if (again && again.equals(plain)) add("focus", info.desc, "no visible focus indicator", ctxo);
    }
    await el.evaluate(a => a.focus()); await el.dispose();                            // leave focus where it was, so the next Tab goes on from here
  }
  // reading order: a stop that jumps well above the one before it (a tab order that does not follow the page)
  for (let i = 1; i < stops.length; i++) if (!stops[i].fixed && !stops[i - 1].fixed && stops[i].ay < stops[i - 1].ay - 300 && stops[i].x <= stops[i - 1].x) add("tab-order", stops[i].desc, `jumps up ${Math.round(stops[i - 1].ay - stops[i].ay)}px from ${stops[i - 1].desc}`, ctxo);
  return stops.length;
}

async function setMode(theme, calm) {
  await page.evaluate(({theme, calm}) => { document.documentElement.dataset.theme = theme; toggleCalm(calm); }, {theme, calm});
  await page.waitForTimeout(250);
}
async function showView(v) {
  await page.evaluate(v => { window.scrollTo(0, 0); try { dockGo(v); } catch (e) { go(v); } }, v);        // from the top: a page the focus walk scrolled must not move the next one's selector
  await page.waitForTimeout(v === "brain" ? 1500 : 450);
}

const stats = {views: 0, stops: 0}, selBox = {};
const baseSel = await page.evaluate(() => sel);
for (const theme of THEMES) for (const calm of CALMS) {
  await setMode(theme, calm);
  for (const spec of VIEWS) {
    const [view, proj] = spec.split("@");
    const c = {view: spec, theme, calm: calm ? "calm" : "normal"};
    await page.evaluate(p => { if (sel !== p) selectProject(p); }, proj || baseSel);          // a view names its project, any other goes back to the one the run began on
    await showView(view);
    await page.evaluate(() => { window.__ctN = 0; });
    for (const x of await page.evaluate(inPage, {contrast: true, ui: true})) add(x.rule, x.where, x.detail, c);
    {                                                                                  // the project selector: one box on every page that has a scope, none on the others (Home, the Brain, Spend, Connections, Settings, Showcase)
      const box = await page.evaluate(() => { const e = document.querySelector("#proj-switch"); if (!e || !e.checkVisibility() || !e.getBoundingClientRect().width) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(","); });
      const key = theme + calm;
      const chip = await page.evaluate(() => { const e = document.querySelector("#pscope .scope-chip"); return !!e && e.checkVisibility() && e.getBoundingClientRect().width > 0; });
      if (!SCOPED.has(view)) { if (box) add("ui-selector", "#proj-switch", `${view} has no project scope, but the project selector is showing`, c); if (chip) add("ui-selector", "#pscope", `${view} has no project scope, but a scope chip is showing`, c); }
      else if (!box) add("ui-selector", "#proj-switch", "the project selector is not visible", c);
      else if (!chip) add("ui-selector", "#pscope", "the scope chip is not visible on a page that has a scope", c);
      else { selBox[key] = selBox[key] || box; if (selBox[key] !== box) add("ui-selector", "#proj-switch", `at ${box}, first seen at ${selBox[key]}`, c); }
    }
    if (process.env.QD_VERBOSE) console.log(view, theme, calm ? "calm" : "normal", "text checked for contrast:", await page.evaluate(() => window.__ctN));
    await axNames(c);
    await selectPopups(c);
    if (FOCUS) {                                                                       // the 3 second poll is paused for the walk, so the page does not redraw under the pixel comparison
      await page.evaluate(() => { window.__tick = window.tick; window.tick = async () => {}; });
      stats.stops += await focusWalk(c, view === "brain" ? 60 : 90);
      await page.evaluate(() => { window.tick = window.__tick; });
    }
    stats.views++;
  }
}

// select popups: open every visible sl-select; its list must start at the control's left edge (a few px), sit inside the viewport and clear of the nav rail
async function selectPopups(ctxo) {
  const n = await page.evaluate(() => [...document.querySelectorAll("sl-select")].filter(e => e.checkVisibility() && e.getBoundingClientRect().width && !e.closest("sl-dialog,sl-drawer")).length);
  for (let i = 0; i < n; i++) {
    const r = await page.evaluate(async i => {
      const e = [...document.querySelectorAll("sl-select")].filter(e => e.checkVisibility() && e.getBoundingClientRect().width && !e.closest("sl-dialog,sl-drawer"))[i];
      if (!e) return null;
      e.scrollIntoView({block: "center"}); await new Promise(r => setTimeout(r, 50));
      await e.show(); await new Promise(r => setTimeout(r, 250));
      const lb = e.shadowRoot.querySelector("[part~=listbox]"), c = e.getBoundingClientRect(), l = lb.getBoundingClientRect();
      const rail = document.querySelector(".rail"), rr = rail && getComputedStyle(rail).display !== "none" ? rail.getBoundingClientRect().right : 0;
      await e.hide();
      return {id: e.id || e.getAttribute("label") || "#" + i, cl: c.left, ll: l.left, lr: l.right, rail: rr, vw: innerWidth};
    }, i);
    if (!r) continue;
    const bad = r.ll < -0.5 ? "starts off screen" : r.lr > r.vw + 0.5 ? "runs off the right edge" : r.ll < r.rail - 0.5 ? `starts under the nav rail (list ${Math.round(r.ll)}, rail ends ${Math.round(r.rail)})` : Math.abs(r.ll - r.cl) > 4 && r.cl >= r.rail ? `list at x ${Math.round(r.ll)} but control at x ${Math.round(r.cl)}` : "";
    if (bad) add("select-popup", r.id, bad, ctxo);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
}

// focus ring contrast: the one token against every surface, both themes
for (const theme of ["dark", "light"]) {
  await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
  const r = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement), probe = document.createElement("div"); document.body.append(probe);
    const px = v => { probe.style.color = v; return getComputedStyle(probe).color; };
    const parse = s => { const m = /rgba?\(([^)]+)\)/.exec(s).slice(1)[0].split(/[ ,\/]+/).map(Number); return {r: m[0], g: m[1], b: m[2]}; };
    const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(c.r) + .7152 * f(c.g) + .0722 * f(c.b); };
    const out = {}, ring = parse(px(cs.getPropertyValue("--focus").trim() || "var(--accent)"));
    for (const k of ["--bg", "--card", "--card2", "--raised"]) { const s = parse(px(cs.getPropertyValue(k).trim())); const a = lum(ring), b = lum(s); out[k] = (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }
    probe.remove(); return out;
  });
  for (const [k, v] of Object.entries(r)) if (v < 3) add("focus", "--focus on " + k, `${v.toFixed(2)}:1 (needs 3)`, {view: "tokens", theme, calm: ""});
}

// flows: skip link, dialog and drawer behaviour, the Brain's Esc
async function flows() {
  const c = {view: "flows", theme: "dark", calm: "normal"};
  await setMode("dark", false); await showView("overview");
  const inside = (sel) => page.evaluate(s => { let a = document.activeElement; while (a) { if (a.matches && a.matches(s)) return true; a = a.parentElement || (a.getRootNode() instanceof ShadowRoot ? a.getRootNode().host : null); } return false; }, sel);
  // skip link
  await page.evaluate(() => { location.hash = ""; document.activeElement && document.activeElement.blur(); document.body.setAttribute("tabindex", "-1"); document.body.focus(); document.body.removeAttribute("tabindex"); });
  await page.keyboard.press("Tab");
  const first = await page.evaluate(() => document.activeElement && document.activeElement.className);
  if (first !== "skip") add("skip", "first Tab stop", "the first Tab stop is not the skip link (" + first + ")", c);
  else { await page.keyboard.press("Enter"); await page.waitForTimeout(150); if (!(await inside("main#view"))) add("skip", "skip link", "Enter did not move focus into the main region", c); }
  // dialogs and drawers: open from a real control, trap, Esc, focus returns
  const cases = [
    {name: "search everywhere", opener: "sl-button[data-on-click=openPalette]", modal: "#palette"},
    {name: "run dialog", pre: () => page.evaluate(() => dockGo("crew")), opener: "sl-button[data-on-click=openRun]", modal: "#run-dlg", wait: true},
    {name: "what PRIVATE means", opener: "button[data-on-click=showPrivacy]", modal: "#drawer"},
  ];
  for (const theme of ["dark", "light"]) for (const k of cases) {
    c.theme = theme; await setMode(theme, false); await showView("overview");
    if (k.pre) { await k.pre(); await page.waitForTimeout(500); }
    // reach the opener the way a keyboard user does: Tab from the top of the page until focus is on it
    await page.evaluate(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); document.body.setAttribute("tabindex", "-1"); document.body.focus(); document.body.removeAttribute("tabindex"); });
    let found = false;
    for (let i = 0; i < 120 && !found; i++) { await page.keyboard.press("Tab"); found = await page.evaluate(sel => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; let h = a; while (h && h.getRootNode() instanceof ShadowRoot) h = h.getRootNode().host; return !!(h && h.matches(sel)); }, k.opener); }
    if (!found) { add("dialogs", k.name, "Tab never reaches the opener " + k.opener, c); continue; }
    if (k.wait && theme === "dark") {                                                                      // two polls later the control must still have focus (the poll redraws regions that changed)
      await page.waitForTimeout(7000);
      const still = await page.evaluate(sel => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; let h = a; while (h && h.getRootNode() instanceof ShadowRoot) h = h.getRootNode().host; return !!(h && h.matches(sel)); }, k.opener);
      if (!still) add("poll", k.name, "keyboard focus was lost when the page refreshed itself", c);
    }
    await page.keyboard.press("Enter"); await page.waitForTimeout(700);
    const open = await page.evaluate(m => !!document.querySelector(m).open, k.modal);
    if (!open) { add("dialogs", k.name, "did not open from the keyboard", c); continue; }
    if (!(await inside(k.modal))) add("dialogs", k.name, "focus is not inside the dialog after it opens", c);
    const label = await page.evaluate(m => { const d = document.querySelector(m); return d.getAttribute("label") || (d.querySelector("[slot=label]") || {}).textContent || ""; }, k.modal);
    if (!String(label).trim()) add("dialogs", k.name, "the dialog has no label", c);
    for (const x of await page.evaluate(inPage, {contrast: true})) add(x.rule, k.name + ": " + x.where, x.detail, c);        // what is inside the open dialog, both themes
    let out = 0; for (let i = 0; i < 25; i++) { await page.keyboard.press("Tab"); if (!(await inside(k.modal))) { out++; break; } }
    if (out) add("dialogs", k.name, "Tab leaves the dialog (no focus trap)", c);
    await page.keyboard.press("Escape"); await page.waitForTimeout(600);
    if (await page.evaluate(m => !!document.querySelector(m).open, k.modal)) add("dialogs", k.name, "Esc does not close it", c);
    else if (!(await page.evaluate(sel => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement; const o = document.querySelector(sel); return !!(o && (a === o || o.contains(a) || (o.shadowRoot && o.shadowRoot.contains(a)))); }, k.opener.split(",")[0]))) add("dialogs", k.name, "focus does not return to the control that opened it", c);
  }
  // the Brain: Esc leaves
  await page.evaluate(() => dockGo("brain")); await page.waitForTimeout(1500);
  await page.locator("body").press("Escape"); await page.waitForTimeout(700);
  if ((await page.evaluate(() => view)) === "brain") add("brain-esc", "Brain", "Esc did not leave the Brain", c);
}
if (FLOWS) await flows();

const summary = {views: stats.views, tabStops: stats.stops, issues: issues.length};
const jf = arg("json", ""); if (jf && jf !== true) fs.writeFileSync(jf, JSON.stringify({summary, issues}, null, 1));
const by = {};
for (const i of issues) { const k = `${i.rule} | ${i.where} | ${i.detail}`; (by[k] ||= new Set()).add(`${i.view}/${i.theme}/${i.calm}`); }
for (const [k, v] of Object.entries(by)) console.log(`${k}   [${[...v].slice(0, 4).join(", ")}${v.size > 4 ? ", +" + (v.size - 4) : ""}]`);
console.log(JSON.stringify(summary));
await done(issues.length ? 1 : 0);
