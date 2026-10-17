// The Crew page's table under node: every duty has a group, the Run dialog builds the request /api/run has always taken, an agent with nothing
// required starts at once. argv[2]: JSON list of the demo's duty names. The real duties are read from duties/*.sh.
import assert from "node:assert/strict";
import fs from "node:fs";
import {fileURLToPath} from "node:url";
import * as C from "../dashboard/assets/crew.js";

const real = fs.readdirSync(fileURLToPath(new URL("../duties/", import.meta.url))).filter(f => f.endsWith(".sh") && !f.startsWith("_")).map(f => f.slice(0, -3));
const demo = JSON.parse(process.argv[2] || "[]");
for (const [label, names] of [["real", real], ["demo", demo], ["an unknown one", [...real, "newduty"]]]) {
  const g = C.groupDuties(names), got = g.flatMap(x => x.duties).sort();
  assert.deepEqual(got, [...names].sort(), `${label}: every duty is in exactly one group`);
}
assert.ok(C.groupDuties(["newduty"]).some(g => g.id === "other" && g.duties.includes("newduty")), "an unlisted duty lands in Other");
assert.deepEqual(real.filter(d => !C.GROUPS.some(g => g.duties.includes(d))), [], "every real duty is named in the table (so none relies on the fallback)");
for (const d of real) assert.ok(C.INFO[d] && C.sentence(d, "x").length > 20 && !/\n/.test(C.sentence(d, "")), "a plain sentence for " + d);
assert.equal(C.sentence("zzz", "Does a thing. And then more."), "Does a thing.");
// the request each agent's dialog builds (the same args the old inline form sent)
assert.deepEqual(C.buildRun("surveyor", {"--pr": "42"}, false), {args: ["--pr", "42"], apply: false});
assert.deepEqual(C.buildRun("surveyor", {"--pr": " "}, false), {args: [], apply: false});
assert.deepEqual(C.buildRun("inspector", {"--pr": "7", "--issue": "3"}, true), {args: ["--pr", "7", "--issue", "3"], apply: true});
assert.deepEqual(C.buildRun("shipwright", {"--issue": "17"}, false), {args: ["--issue", "17"], apply: false});
assert.deepEqual(C.buildRun("panel", {"--panel": "decision", "--question": "tabs or spaces"}, false, "--target src").args, ["--panel", "decision", "--question", "tabs or spaces", "--target", "src"]);
assert.deepEqual(C.buildRun("panel", {"--panel": "design", "--target": "ui", "--issue": "9", "--question": "q"}, false).args, ["--panel", "design", "--target", "ui", "--issue", "9", "--question", "q"]);
assert.deepEqual(C.buildRun("harbourmaster", {"--sync-only": true}, false), {args: ["--sync-only"], apply: false});
assert.deepEqual(C.buildRun("bosun", {}, false, "--stale 30"), {args: ["--stale", "30"], apply: false});
// two clicks: an agent with nothing required has nothing to fill in; one that needs an input says which
for (const d of ["surveyor", "marshal", "harbourmaster", "bosun", "mockup", "joiner", "purser", "planner", "quartermaster", "infra"]) assert.equal(C.missing(d, {}), null, d + " starts at once");
assert.match(C.missing("inspector", {}), /pull request number/);
assert.equal(C.missing("inspector", {"--pr": "5"}), null);
assert.match(C.missing("shipwright", {}), /issue number/);
assert.equal(C.missing("shipwright", {"--plan": "p.md"}), null);
// at most three plain fields per agent, each with a label and an example
for (const [d, i] of Object.entries(C.INFO)) { assert.ok(i.main.length <= 3, d); for (const f of i.main) assert.ok(f.label && (f.ph || f.opts), d + " " + f.flag); }
// state
assert.equal(C.stateOf({status: "running"}), "running");
assert.equal(C.stateOf({status: "idle", last_at: "x", last_verdict: "CLEAN"}), "idle");
assert.equal(C.stateOf({status: "idle", last_at: "x", last_verdict: "ERROR"}), "attention");
assert.equal(C.stateOf({status: "idle", last_at: "x", last_verdict: "FINDINGS 3"}), "attention");
assert.equal(C.stateOf({status: "idle"}), "never");
assert.equal(C.stateOf({status: "unbuilt"}), "unbuilt");
console.log("crew ok");
