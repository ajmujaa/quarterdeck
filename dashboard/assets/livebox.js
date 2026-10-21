// The live box: what a long action prints while it runs. One reusable piece (Prove on the Ready card, the scan when a folder is attached).
// It asks one small JSON, GET /api/live?key=&since=N, once a second: {state, seconds, lines, next, total, replace}. No stream and no websocket.
// Text only: every line is put on the page with textContent, never as markup, so output can only ever be read. The progress strip is a moving
// indicator, never a percentage, because the page cannot know how long a command will take.
// Pure helpers are exported so node can test them (bin/selftest-livebox.mjs); the DOM parts look an element up by id and do nothing if it is gone.

export const LIVE_KEEP = 200;                       // lines held in the page, the same as the server sends at most
const BOXES = {};                                   // id -> {key, lines, next, state, seconds, timer, stop}

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const safeId = id => String(id).replace(/[^A-Za-z0-9_-]/g, "-");

export function liveFold(prev, resp) {                // the lines held after one answer: appended, or replaced by the kept tail when the run has ended
  const lines = resp && resp.replace ? (resp.lines || []).slice() : (prev || []).concat((resp && resp.lines) || []);
  return lines.slice(-LIVE_KEEP);
}
export function liveClock(seconds) {                  // "12 s" under a minute, then "1 min 05 s"
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  return s < 60 ? s + " s" : Math.floor(s / 60) + " min " + String(s % 60).padStart(2, "0") + " s";
}
export const liveWords = state => ({running: "Running", passed: "Finished", failed: "Stopped with a failure", stopped: "Stopped by you", done: "Finished", idle: "Not running"})[state] || "Running";

// The markup of one box. title: what is running. stopHtml: the page's own Stop button (or ""). The log is the only part with text from outside.
export function liveBoxHtml(id, o = {}) {
  const k = safeId(id), b = BOXES[k] || {lines: [], seconds: 0, state: "running"};
  const running = b.state === "running";
  return `<div class="lv" id="lv-${k}" data-state="${esc(b.state)}">
    <div class="lv-head"><span class="lv-title">${esc(o.title || "Working")}</span> <span class="sub lv-clock" id="lv-${k}-clock">${esc(liveWords(b.state))} · ${esc(liveClock(b.seconds))}</span>${o.stopHtml || ""}</div>
    ${running ? `<div class="lv-bar" role="progressbar" aria-label="${esc(o.title || "Working")}, no percentage: it is not known how long this takes" id="lv-${k}-bar"><span></span></div>` : ""}
    <pre class="lv-log" id="lv-${k}-log" tabindex="0" role="log" aria-live="off" aria-label="${esc(o.logLabel || "Output so far")}">${esc(b.lines.join("\n"))}</pre>
  </div>`;
}

function paint(k) {                                    // update the pieces in place; the page is not redrawn for a new line
  const b = BOXES[k], doc = typeof document === "undefined" ? null : document;
  if (!b || !doc) return;
  const log = doc.getElementById("lv-" + k + "-log"), clock = doc.getElementById("lv-" + k + "-clock"), box = doc.getElementById("lv-" + k);
  if (log) {
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
    log.textContent = b.lines.join("\n");
    if (atEnd) log.scrollTop = log.scrollHeight;       // follow the output unless the reader scrolled up to read
  }
  if (clock) clock.textContent = liveWords(b.state) + " · " + liveClock(b.seconds);
  if (box) {
    box.setAttribute("data-state", b.state);
    const bar = doc.getElementById("lv-" + k + "-bar");
    if (bar && b.state !== "running") bar.remove();
  }
}

// liveStart(id, key, {follow, onEnd}): ask every second until the server says the run is over (or, with follow, until liveStop(id)).
export function liveStart(id, key, o = {}) {
  const k = safeId(id);
  liveStop(k, true);
  BOXES[k] = {key, lines: [], next: 0, state: "running", seconds: 0, timer: 0, follow: !!o.follow, onEnd: o.onEnd || null};
  const mine = BOXES[k];
  const tick = async () => {
    if (BOXES[k] !== mine) return;
    let r = null;
    try {
      const res = await fetch("/api/live?key=" + encodeURIComponent(key) + "&since=" + mine.next);
      r = res.ok ? await res.json() : null;
    } catch (e) { r = null; }                          // the next tick asks again
    if (BOXES[k] !== mine) return;
    if (r) {
      mine.lines = liveFold(mine.lines, r); mine.next = r.next || 0; mine.seconds = r.seconds || 0;
      const over = r.state !== "running" && r.state !== "idle";
      mine.state = mine.follow ? "running" : (r.state === "idle" ? "running" : r.state);        // a followed box ends when the caller says so
      paint(k);
      if (over && !mine.follow) { if (mine.onEnd) mine.onEnd(r); return; }
    }
    mine.timer = setTimeout(tick, 1000);
  };
  mine.timer = setTimeout(tick, 250);
  return k;
}
// liveStop(id): end the watching. The lines stay held, so the box can still be drawn; a box that was still running is marked finished.
export function liveStop(id, quiet) {
  const k = safeId(id), b = BOXES[k];
  if (!b) return;
  clearTimeout(b.timer); b.timer = 0;
  if (!quiet && b.state === "running") { b.state = "done"; paint(k); }
}
export const liveRunning = id => { const b = BOXES[safeId(id)]; return !!b && b.state === "running" && !!b.timer; };
export const liveLines = id => { const b = BOXES[safeId(id)]; return b ? b.lines.slice() : []; };
