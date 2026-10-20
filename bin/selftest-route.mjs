// The router under node: dashboard/assets/route.js is a pure module (no DOM, no globals), so the address, the validation and the round trip
// are tested here with nothing but the module. The page's own wiring is tested in a browser by bin/selftest-nav.sh.
import assert from "node:assert/strict";
import fs from "node:fs";
import {fileURLToPath} from "node:url";
import {parseHash, buildHash, defaultRoute, validMissionId, validLogId, isPairHash, MAX_HASH} from "../dashboard/assets/route.js";

const GROUPS = [
  {id: "home", views: ["overview"]}, {id: "brain", views: ["brain"]},
  {id: "work", views: ["inbox", "missions", "prs", "board", "timeline", "operations", "ledger", "spend", "log"]},
  {id: "agents", views: ["crew", "fleet"]}, {id: "connections", views: ["connections"]},
  {id: "library", views: ["documents", "panels", "notes", "showcase"]}, {id: "settings", views: ["settings"]},
];
const known = {groups: GROUPS, projects: ["drydock", "wayfarer-mobile", "a b", "ünï/cødé", "x".repeat(40)], addons: ["hermes", "scout"], places: {hermes: ["hermes", "hermes-log"]}};
const HOME = {ok: false, group: "home", view: "overview", id: "", project: "", addon: "", brain: ""};
const fields = r => ({group: r.group, view: r.view, id: r.id, project: r.project, addon: r.addon, brain: r.brain});
let n = 0;
const ok = (label, fn) => { fn(); n++; };

// ---- the default route ----
ok("the default route is Home and is a fresh object each time", () => {
  assert.deepEqual(defaultRoute(), HOME);
  assert.notEqual(defaultRoute(), defaultRoute());
});

// ---- the route table: every group and view, every project, every add-on ----
const states = [];
for (const g of GROUPS) {
  if (g.id === "brain") { for (const brain of ["map", "rhythm"]) states.push({group: "brain", view: "brain", brain}); continue; }
  for (const view of g.views) states.push({group: g.id, view});
}
states.push({group: "work", view: "mission"}, {group: "work", view: "log"});
ok("every group and view round-trips, with and without a project scope", () => {
  for (const s of states) for (const project of ["", ...known.projects]) {
    const want = {group: s.group, view: s.view, id: "", project, addon: "", brain: s.brain || ""};
    const h = buildHash({...want});
    assert.ok(h.length <= MAX_HASH && h.startsWith("#/"), h);
    const r = parseHash(h, known);
    assert.equal(r.ok, true, h);
    assert.deepEqual(fields(r), want, h);
    assert.equal(buildHash(r), h, "the hash is stable: " + h);
  }
});
ok("the table of addresses is the one in the docs", () => {
  const t = {
    "#/home/overview": ["home", "overview"], "#/brain/map": ["brain", "brain"], "#/brain/rhythm": ["brain", "brain"], "#/work/inbox": ["work", "inbox"],
    "#/work/missions": ["work", "missions"], "#/work/prs": ["work", "prs"], "#/work/board": ["work", "board"], "#/work/timeline": ["work", "timeline"],
    "#/work/operations": ["work", "operations"], "#/work/ledger": ["work", "ledger"], "#/work/spend": ["work", "spend"], "#/work/log": ["work", "log"],
    "#/work/mission": ["work", "mission"], "#/agents/crew": ["agents", "crew"], "#/agents/fleet": ["agents", "fleet"],
    "#/connections/connections": ["connections", "connections"], "#/library/documents": ["library", "documents"], "#/library/panels": ["library", "panels"],
    "#/library/notes": ["library", "notes"], "#/library/showcase": ["library", "showcase"], "#/settings/settings": ["settings", "settings"],
  };
  for (const [h, [g, v]] of Object.entries(t)) { const r = parseHash(h, known); assert.ok(r.ok && r.group === g && r.view === v, h); }
  assert.equal(parseHash("#/brain/rhythm", known).brain, "rhythm");
  assert.equal(parseHash("#/work/mission/cycle%3Aabc?project=drydock", known).id, "cycle:abc");
  assert.equal(parseHash("#/work/mission/cycle%3Aabc?project=drydock", known).project, "drydock");
});
ok("an add-on's place and its pages, and the add-on scope on Needs you", () => {
  assert.deepEqual(fields(parseHash("#/addon/hermes", known)), {group: "addon", view: "hermes", id: "", project: "", addon: "hermes", brain: ""});
  assert.equal(parseHash("#/addon/hermes/hermes-log", known).view, "hermes-log");
  assert.equal(buildHash({place: "hermes", view: "hermes"}), "#/addon/hermes");
  assert.equal(buildHash({place: "hermes", view: "hermes-log"}), "#/addon/hermes/hermes-log");
  assert.equal(parseHash("#/addon/nope", known).ok, false, "an add-on place that is not installed");
  assert.equal(parseHash("#/addon/hermes/other", known).ok, false, "a page the place does not have");
  assert.equal(parseHash("#/addon/hermes?project=drydock", known).ok, false, "an add-on place has no project scope");
  const r = parseHash("#/work/inbox?addon=scout", known);
  assert.deepEqual(fields(r), {group: "work", view: "inbox", id: "", project: "", addon: "scout", brain: ""});
  assert.equal(buildHash(r), "#/work/inbox?addon=scout");
  assert.equal(parseHash("#/work/ledger?addon=scout", known).ok, false, "the add-on scope is only for Needs you");
  assert.equal(parseHash("#/work/inbox?addon=ghost", known).ok, false, "an add-on that is not installed");
  assert.equal(parseHash("#/work/inbox?project=drydock&addon=scout", known).ok, false, "one scope at a time");
});

// ---- ids: a mission id with colons, a panel id, a ledger run, hostile text ----
const goodIds = ["cycle:abc", "cycle:cyc-a-7-1", "panel:20261015-090000-dev", "fix:20261015-090000-dev#2", "run:2026-01-01T00:00:00Z|alpha|surveyor", "attn:remote:scout:job_failed",
  "brief:b20261015-090000-d3a1", "plan:p1", "fix:../x#1", "fix:ünï€#1", "run:a b|c d|e", "panel:" + "y".repeat(150), "attn:%00"];
ok("a mission id is encoded once and decoded once, whatever is in it", () => {
  for (const id of goodIds) {
    assert.equal(validMissionId(id), true, id);
    const h = buildHash({group: "work", view: "mission", id, project: "drydock"});
    assert.ok(/^[\x21-\x7e]+$/.test(h), "only printable ASCII in the address: " + h);
    assert.ok(!/[<>" `\\]/.test(h) && h.length <= MAX_HASH, h);
    const r = parseHash(h, known);
    assert.equal(r.ok, true, h);
    assert.equal(r.id, id, "decoded exactly once: " + h);
    assert.equal(r.project, "drydock");
  }
  assert.equal(parseHash("#/work/mission/fix%3Aa%253Ab%2523c", known).id, "fix:a%3Ab%23c", "a %25 in the address stays a literal %3A in the id: it is not decoded twice");
});
const hostile = ["", "x", ":", "cycle:", "../", "../../etc/passwd", "%00", "cycle:%00", "cycle:a\u0000b", "<script>alert(1)</script>", "cycle:<script>alert(1)</script>", 'cycle:"onmouseover="x',
  "cycle:`x`", "cycle:a\\b", "cycle:a\nb", "cycle:" + "z".repeat(250), "z".repeat(5000), "fix:a#pair=" + "A".repeat(32), "#pair=" + "A".repeat(32), "cycle:\ud800", "cycle:a?project=drydock",
  "cycle:a&addon=hermes", "cycle:a/b/c", "CYCLE:abc", "cycle:é‮", "__proto__", "constructor", "toString"];
ok("a hostile id is either kept exactly or left out; the address never holds it raw", () => {
  for (const id of hostile) {
    const h = buildHash({group: "work", view: "mission", id});
    assert.ok(h.length <= MAX_HASH, "bounded");
    assert.ok(/^#[\x21-\x7e]*$/.test(h) && !/[<>"`\\ ]/.test(h), "printable ASCII, nothing that closes markup: " + h);
    const r = parseHash(h, known);
    assert.equal(r.ok, true, h);
    assert.ok(r.id === "" || r.id === id, "kept exactly or dropped, never changed: " + JSON.stringify(id));
    if (r.id !== "") assert.equal(validMissionId(id), true);
    else assert.equal(validMissionId(id), false);
    assert.equal(r.view, h === "#/home/overview" ? "overview" : "mission", "an id that cannot be written at all (a lone surrogate) gives Home");
  }
  for (const id of ["<script>alert(1)</script>", "../", "%00", "cycle:%00x".replace("%00", "\u0000"), "x"]) assert.equal(validMissionId(id), false, id);
});
ok("a hostile id typed straight into the address is refused, never decoded into the page", () => {
  for (const h of ["#/work/mission/<script>alert(1)</script>", "#/work/mission/%3Cscript%3Ealert(1)%3C%2Fscript%3E", "#/work/mission/cycle%3A%3Cimg%20src%3Dx%3E", "#/work/mission/cycle%3A%00",
    "#/work/mission/%00", "#/work/mission/../../x", "#/work/mission/cycle:a#pair=" + "A".repeat(32), "#/work/mission/%E0%A4%A", "#/work/mission/cycle%3Aa/extra",
    "#/work/mission/cycle:" + "z".repeat(250), "#/work/mission/cycle%3A%5Cx"]) {
    const r = parseHash(h, known);
    assert.equal(r.ok, false, h);
    assert.deepEqual(fields(r), fields(HOME));
  }
});
ok("a log id is <project>~<duty>", () => {
  const r = parseHash("#/work/log/drydock~surveyor", known);
  assert.deepEqual([r.view, r.id], ["log", "drydock~surveyor"]);
  assert.equal(buildHash(r), "#/work/log/drydock~surveyor");
  assert.equal(validLogId("a~b~c"), false);
  assert.equal(parseHash("#/work/log/nonsense", known).ok, false);
  assert.equal(parseHash("#/work/inbox/drydock~surveyor", known).ok, false, "only Mission and Log take an id");
});

// ---- anything unknown, malformed, over-long or undecodable is Home, and nothing throws ----
const bad = [undefined, null, 5, {}, [], "", "#", "#/", "#//", "#/home", "#/home/", "#/home/overview/x", "#/home/nope", "#/nope/overview", "#/work/nope", "#/work", "work/inbox", "#work/inbox",
  "#/work/inbox?project=ghost", "#/work/inbox?project=", "#/work/inbox?project", "#/work/inbox?foo=bar", "#/work/inbox?project=drydock&project=drydock", "#/work/inbox?project=drydock&",
  "#/work/inbox?project=%E0%A4%A", "#/work/inbox?project=%00", "#/WORK/INBOX", "#/work/Inbox", "#/work/%69nbox%00", "#/work/inbox%2Fx", "#/brain/other", "#/brain/map/x", "#/brain",
  "#pair=" + "A".repeat(32), "#/work/inbox#pair=" + "A".repeat(32), "#/work/inbox?project=drydock#x", "#/__proto__/x", "#/work/__proto__", "#/addon/__proto__", "#/addon/constructor",
  "#/work/inbox?project=__proto__", "#/work/<script>", "#/work/inbox?project=<script>", "#/work/in box", "#/work/inbox\n", "#/work/ünï", "javascript:alert(1)", "#/work/inbox?project=drydock\u0000",
  "#/" + "a".repeat(400), "#/work/inbox?project=" + "x".repeat(300), "#/work/mission/" + "cycle%3A".repeat(60)];
ok("every bad address is Home and none throws", () => {
  for (const h of bad) {
    let r;
    assert.doesNotThrow(() => { r = parseHash(h, known); }, String(h));
    assert.deepEqual(fields(r), fields(HOME), String(h).slice(0, 80));
    assert.equal(r.ok, false, String(h).slice(0, 80));
  }
});
ok("a bad `known` is Home, not an exception", () => {
  for (const k of [undefined, null, 5, "x", {}, {groups: null}, {groups: [null]}, {groups: [{id: "work"}]}, {groups: GROUPS, places: null, projects: "x"}]) {
    assert.doesNotThrow(() => parseHash("#/work/inbox", k));
    assert.doesNotThrow(() => parseHash("#/work/inbox?project=drydock", k));
    assert.doesNotThrow(() => parseHash("#/addon/hermes", k));
  }
  assert.equal(parseHash("#/home/overview", {groups: GROUPS}).ok, true, "a known with only groups still opens a plain page");
});
ok("the hash is capped at 300 characters", () => {
  const fits = "#/work/mission/" + "cycle%3A" + "a".repeat(MAX_HASH - 15 - 8);
  assert.equal(fits.length, MAX_HASH);
  assert.equal(parseHash(fits, {...known}).ok, false, "an id past 200 characters is refused although the address fits");
  assert.equal(parseHash(fits + "a", known).ok, false, "one character over the cap");
  assert.equal(parseHash("#/work/inbox?project=" + "x".repeat(40), known).ok, true);
  assert.equal(parseHash("#/work/inbox" + "?".repeat(1) + "project=" + "x".repeat(290), known).ok, false);
  assert.equal(parseHash("#/work/inbox?project=drydock" + "&".repeat(300), known).ok, false);
  assert.equal(buildHash({group: "work", view: "mission", id: "cycle:" + "a".repeat(190), project: "x".repeat(40)}).length <= MAX_HASH, true);
  assert.equal(buildHash({group: "work", view: "inbox", project: "p".repeat(400)}), "#/home/overview", "a state too long to write gives Home");
});
ok("buildHash never throws on a hostile state", () => {
  for (const s of [undefined, null, 5, "x", {}, {group: 5, view: {}}, {group: "work"}, {view: "inbox"}, {group: "work", view: "inbox", project: {toString() { throw new Error("x"); }}}, {group: "work", view: "mission", id: Symbol("x")},
    {place: 7}, {place: "a b/c", view: "d?e"}, {group: "work", view: "mission", id: "\ud800"}]) {
    let h; assert.doesNotThrow(() => { h = buildHash(s); });
    assert.ok(typeof h === "string" && h.startsWith("#/") && h.length <= MAX_HASH);
    const r = parseHash(h, known);
    assert.deepEqual(r.ok ? fields(parseHash(buildHash(r), known)) : fields(r), r.ok ? fields(r) : fields(HOME), h);   // what parses rebuilds to itself, the rest is Home
  }
  assert.equal(buildHash({group: "work", view: "inbox", project: "a b"}), "#/work/inbox?project=a%20b");
});
ok("fuzz: random text and random states never throw, and what parses always rebuilds to a route that parses the same", () => {
  let seed = 12345; const rnd = m => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) % m;
  const alphabet = "#/?&=%:abcxyz-_.~ 09ABCDEF<>\"'`\\\u0000é\ud800";
  for (let i = 0; i < 4000; i++) {
    let h = rnd(3) ? "#/" : "#";
    for (let j = rnd(40); j > 0; j--) h += alphabet[rnd(alphabet.length)];
    if (rnd(4) === 0) h = "#/work/mission/" + encodeURIComponent(h.replace(/[\ud800-\udfff]/g, "?")) + (rnd(2) ? "?project=drydock" : "");
    const r = parseHash(h, known);
    if (r.ok) { const again = parseHash(buildHash(r), known); assert.deepEqual(fields(again), fields(r), h); }
  }
});
ok("the pairing link is recognised and is never a route", () => {
  assert.equal(isPairHash("#pair=" + "A".repeat(32)), true);
  assert.equal(isPairHash("#/work/inbox"), false);
  assert.equal(parseHash("#pair=" + "A".repeat(32), known).ok, false);
  for (const id of goodIds) assert.ok(!buildHash({group: "work", view: "mission", id}).includes("pair="));
});
ok("the module is pure: no DOM, no globals, no network, no storage, and no dash characters in it", () => {
  const src = fs.readFileSync(fileURLToPath(new URL("../dashboard/assets/route.js", import.meta.url)), "utf8");
  assert.ok(!/\b(document|window|localStorage|sessionStorage|history|location|fetch|XMLHttpRequest|eval|innerHTML|import\()/.test(src.replace(/\/\/.*$/gm, "")), "no host object");
  assert.ok(!/[–—]/.test(src));
});
console.log("  ok    route: " + n + " groups of checks (the table, the round trip over every page, project and add-on, hostile ids, bad addresses, the 300 character cap, fuzz)");
