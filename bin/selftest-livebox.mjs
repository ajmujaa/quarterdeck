// The live box's own logic under node (dashboard/assets/livebox.js): folding answers into lines, the clock, markup that never carries output as markup,
// and a polling run against a stand-in fetch. Prints "ok <label>" / "FAIL <label>" lines; the caller (selftest-prove-live.sh) counts them.
import {liveFold, liveClock, liveWords, liveBoxHtml, liveStart, liveStop, liveRunning, liveLines, LIVE_KEEP} from "../dashboard/assets/livebox.js";

const chk = (label, cond, extra) => console.log((cond ? "ok " : "FAIL ") + label + (cond || extra === undefined ? "" : "  | " + String(extra).slice(0, 300)));
const sleep = ms => new Promise(r => setTimeout(r, ms));

chk("liveFold appends new lines, replaces them when the run has ended, and keeps at most the last 200",
  liveFold(["a"], {lines: ["b"]}).join() === "a,b" && liveFold(["a"], {replace: true, lines: ["x", "y"]}).join() === "x,y"
  && liveFold([], {lines: Array.from({length: 450}, (_, i) => "l" + i)}).length === LIVE_KEEP && liveFold(null, null).length === 0);
chk("liveClock says seconds under a minute and minutes after", liveClock(7) === "7 s" && liveClock(65) === "1 min 05 s" && liveClock(-3) === "0 s" && liveClock("x") === "0 s");
chk("liveWords has a plain word for each state", ["running", "passed", "failed", "stopped", "done", "idle"].every(s => liveWords(s).length > 3));

const html = liveBoxHtml("prove", {title: "Running <b>x</b>", stopHtml: '<button id="s">Stop</button>'});
chk("the box has a polite log (aria-live off on the log itself, role log), a labelled progress strip with no percentage, and the page's Stop button",
  /role="log"/.test(html) && /aria-live="off"/.test(html) && /role="progressbar"/.test(html) && !/aria-valuenow/.test(html) && html.includes('id="s"') && !/<b>x<\/b>/.test(html), html);

let calls = [], n = 0;
globalThis.fetch = async url => {
  calls.push(String(url));
  n++;
  const body = n === 1 ? {state: "running", seconds: 1, lines: ["step 1", "<script>alert(1)</script>"], next: 2, total: 2, replace: false}
    : n === 2 ? {state: "running", seconds: 2, lines: ["step 2"], next: 3, total: 3, replace: false}
    : {state: "passed", seconds: 3, lines: ["step 1", "<script>alert(1)</script>", "step 2", "ok done"], next: 4, total: 4, replace: true};
  return {ok: true, json: async () => body};
};
let ended = null;
liveStart("prove", "prove:relay", {onEnd: r => { ended = r; }});
chk("a started box is running", liveRunning("prove"));
for (let i = 0; i < 60 && !ended; i++) await sleep(100);
chk("polling asks with since=0, then since=2, then since=3, and stops when the state is not running",
  ended && ended.state === "passed" && /key=prove%3Arelay&since=0$/.test(calls[0]) && /since=2$/.test(calls[1]) && /since=3$/.test(calls[2]) && calls.length === 3, calls.join(" "));
chk("the final answer replaces the lines with the kept tail, and the box is no longer running", liveLines("prove").join("|") === "step 1|<script>alert(1)</script>|step 2|ok done" && !liveRunning("prove"));
const after = liveBoxHtml("prove", {});
chk("output is only ever escaped text in the markup, and a finished box has no progress strip", !after.includes("<script>") && after.includes("&lt;script&gt;") && !/role="progressbar"/.test(after), after);

n = 0; calls = [];
liveStart("attach", "attach", {follow: true});
await sleep(1500);
chk("a followed box keeps running past a finished answer until it is stopped, and stopping ends the asking", liveRunning("attach"));
liveStop("attach");
const seen = calls.length;
await sleep(1300);
chk("  no more questions after liveStop", calls.length === seen && !liveRunning("attach"), calls.length + " vs " + seen);
