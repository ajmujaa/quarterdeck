// The page's handler plumbing under node: data goes into a control only as JSON in a data attribute and comes back out only through
// JSON.parse, so no text from a run, a file or a model is ever read as code. The helpers are cut out of dashboard/index.html itself.
import assert from "node:assert/strict";
import fs from "node:fs";
import {fileURLToPath} from "node:url";

const html = fs.readFileSync(fileURLToPath(new URL("../dashboard/index.html", import.meta.url)), "utf8");
const between = (a, b) => { const i = html.indexOf(a), j = html.indexOf(b, i); assert.ok(i > 0 && j > i, a); return html.slice(i, j); };
const src = between("const esc = s =>", "let ACT_EV = null") + between("let ACT_EV = null", "// click, keydown, submit");
const ACTIONS = {seq: true, got: (...a) => { calls.push(a); }, preventDefault: () => false};
const calls = [];
const {esc, actOn, act, T, runAction} = new Function("ACTIONS", src + "; return {esc, actOn, act, T, runAction};")(ACTIONS);

// what an HTML parser does to a double-quoted attribute value
const attrs = s => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2].replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&")]));

const evil = ["x');window.__pwn=1;//", "<img src=x onerror=window.__pwn=1>", 'a"b\'c`d</script><script>window.__pwn=1</script>&#39;&quot;', "  ${window.__pwn=1}", "\\\"); alert(1); (\"", "</textarea><svg onload=1>"];
for (const t of evil) {
  const out = act("got", t, {ok: t}, 3);
  assert.ok(!/[<>]/.test(out) && !out.includes('"' + t), "the markup holds no raw tag characters and no quote opened by the data: " + t);
  const a = attrs(out);
  assert.deepEqual(Object.keys(a).sort(), ["data-a-click", "data-on-click"], "only two attributes, however hostile the data");
  assert.equal(a["data-on-click"], "got");
  assert.deepEqual(JSON.parse(a["data-a-click"]), [t, {ok: t}, 3], "the data comes back exactly, as data");
}
// the name is a name from the table or nothing: no lookup walks the prototype, nothing is evaluated
for (const bad of ["constructor", "__proto__", "toString", "hasOwnProperty", "x');alert(1);//", "window.__pwn=1"]) { calls.length = 0; assert.equal(runAction(bad, [], {}, {}), undefined); assert.equal(calls.length, 0); }
// tokens stand for the control and the event, read when it fires; a data string that looks like a token is only a string
calls.length = 0;
runAction("got", [T.value, T.checked, T.sel, "$value", {$: "nope"}], {value: "v", checked: true}, {});
assert.deepEqual(calls[0], ["v", true, "v", "$value", undefined]);
// a sequence runs each named action in order and one that says false makes the whole say false
calls.length = 0;
assert.equal(runAction("seq", [["got", 1], ["preventDefault"], ["got", 2]], {}, {}), false);
assert.deepEqual(calls, [[1], [2]]);
assert.equal(runAction("seq", [["nope", 1], ["got", 3]], {}, {}), undefined);
console.log("  ok    handlers: hostile data survives a round trip through the attributes as data, and only table names run");
