// "My rhythm": one screen for two sources. In Demo mode it draws the concept preview that bin/demo.py invents. In real mode it draws the
// owner's own counts (commits, notes, pull requests, runs started by hand, calendar blocks) from state/attention.json through
// bin/attention/rhythm_feed.py, labelled as an estimate. All the working-out is in rhythm.js. Flat solid colours, nothing moves.
import * as R from "./rhythm.js";

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
let data = null, wk = [], wi = -1, day = null, shown = false, note = null, root = null, loading = false, failed = false, slotEl = null, mode = "", openBlk = "", proj = "", drawn = "";

const CSS = `
.rh{border:1px solid var(--line);border-radius:10px;background:var(--card);padding:14px 16px;margin-bottom:10px}
.rh[hidden]{display:none}
.rh-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px}.rh-head h2{margin:0;font-size:22px}
.rh-badge{font-size:12px;color:var(--await);background:var(--await-bg);border:1px solid var(--await);border-radius:999px;padding:3px 10px}
.rh-pick{display:flex;align-items:center;gap:8px;margin:12px 0}.rh-pick sl-range{flex:1;min-width:80px}.rh-pick b{min-width:120px;text-align:right;font-size:15px}
.rh-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:12px}
@media (max-width:760px){.rh-grid{grid-template-columns:minmax(0,1fr)}}
.rh-card{border:1px solid var(--line);border-radius:8px;background:var(--card2);padding:12px}
.rh-card h3{margin:0 0 8px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--dim);font-weight:600}
.rh-wide{grid-column:1/-1}
.rh-heat{display:grid;grid-template-columns:22px repeat(35,minmax(0,1fr));gap:2px;align-items:center}
.rh-heat .lab{font-size:10px;color:var(--dim);text-align:right;padding-right:3px}.rh-heat .mon{font-size:10px;color:var(--dim);grid-column:span 1;overflow:visible;white-space:nowrap;height:12px}
.rh-cell{display:block;width:100%;aspect-ratio:1/1;min-height:7px;padding:0;border:0;border-radius:2px;cursor:pointer}
.rh-cell.sel{outline:1px solid var(--dim);outline-offset:-1px}
.rh-l0{background:var(--heat-0)}.rh-l1{background:var(--heat-1)}.rh-l2{background:var(--heat-2)}.rh-l3{background:var(--heat-3)}.rh-l4{background:var(--heat-4)}
.rh-key{display:flex;gap:6px;align-items:center;margin-top:8px;font-size:12px;color:var(--dim)}.rh-key i{display:inline-block;width:14px;height:14px;border-radius:2px}
.rh-strip{display:flex;height:44px;gap:2px}.rh-seg{display:block;border:0;padding:0;border-radius:4px;min-width:3px;cursor:pointer;color:var(--accent-ink);font-size:12px;font-weight:600;overflow:hidden;white-space:nowrap}
.rh-seg.focus{background:var(--accent)}.rh-seg.meeting{background:var(--await)}.rh-seg.gap{background:var(--line-2);color:var(--ink)}
.rh-axis{display:flex;justify-content:space-between;font-size:12px;color:var(--dim);margin-top:4px}
.rh-days{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.rh-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.rh-stat{display:block;width:100%;text-align:left;border:1px solid var(--line);border-radius:8px;background:var(--card2);padding:10px 12px;cursor:pointer;color:var(--ink)}
.rh-stat b{display:block;font-size:30px;line-height:1.15}.rh-stat span{display:block;font-size:13px;color:var(--dim);margin-top:2px}.rh-stat small{display:block;font-size:11px;color:var(--accent);margin-top:6px}
.rh-obs{list-style:none;margin:0;padding:0}.rh-obs li{margin:0}.rh-obs button{display:block;width:100%;text-align:left;border:0;border-top:1px solid var(--line);background:none;color:var(--ink);padding:10px 2px;font-size:16px;cursor:pointer}
.rh-obs li:first-child button{border-top:0}
.rh-chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.rh-chip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line-2);border-radius:999px;background:var(--card);color:var(--ink);padding:6px 12px;font-size:14px;cursor:pointer}
.rh-chip i,.rh-proj i{display:inline-block;width:10px;height:10px;border-radius:2px}
.rh-block{border-top:1px solid var(--line)}.rh-block:first-child{border-top:0}
.rh-bhead{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px;width:100%;text-align:left;border:0;background:none;color:var(--ink);padding:9px 2px;font-size:15px;cursor:pointer}
.rh-time{font-weight:700;min-width:110px}.rh-proj{display:inline-flex;align-items:center;gap:6px;color:var(--dim);min-width:130px}.rh-label{flex:1 1 220px}
.rh-ev{margin:0 0 8px 12px;padding:0 0 0 16px;font-size:14px;color:var(--dim)}.rh-ev li{margin:3px 0}.rh-ev b{color:var(--ink)}
.rh-store{font-size:12px;color:var(--dim);margin:10px 0 0}
.rh-explain{margin-top:10px;border:1px solid var(--accent-edge);background:var(--accent-bg);border-radius:8px;padding:10px 12px;font-size:14px;line-height:1.5}
.rh-explain b{display:block;margin-bottom:2px}.rh-explain sl-icon-button{float:right;margin-left:10px}
.rh button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
`;

function addStyle(){
  if(document.getElementById("rh-style")) return;
  const s = document.createElement("style"); s.id = "rh-style"; s.textContent = CSS; document.head.append(s);
}

// mode: "demo" (the invented preview) or "real" (the owner's own counts). A change of mode starts from nothing.
// The Brain toolbar owns the Map | Rhythm switch and the project choice; this module only draws the screen. `on` says whether it is showing.
export function sync(modeNow, slot, on, project){
  if(modeNow !== "demo" && modeNow !== "real"){ remove(); return; }
  if(modeNow !== mode){ data = null; wk = []; wi = -1; day = null; note = null; failed = false; mode = modeNow; }
  if(!slot) return;
  addStyle();
  proj = project || "";
  if(!root || !root.isConnected){
    root = document.createElement("section"); root.className = "rh"; root.setAttribute("aria-label", "My rhythm"); root.hidden = !on; drawn = "";
    root.addEventListener("click", onClick); root.addEventListener("input", onInput); root.addEventListener("sl-input", onInput);
    slot.before(root);
  }
  const was = shown; shown = !!on; root.hidden = !shown;
  slotEl = slot; slot.hidden = shown;
  if(shown !== was) window.dispatchEvent(new Event("resize"));
  if(!shown) return;
  const key = mode + "|" + proj + "|" + !!data;      // repaint only when something changed, so a toolbar refresh never resets the scroll
  if(shown !== was || key !== drawn){ drawn = key; paint(); }
  if(!data && !loading) load().then(() => { drawn = ""; if(shown) { drawn = mode + "|" + proj + "|" + !!data; paint(); } });
}

function remove(){
  if(root) root.remove();
  if(slotEl) slotEl.hidden = false;
  root = slotEl = null; drawn = ""; data = null; wk = []; wi = -1; day = null; shown = false; note = null; failed = false; mode = "";
}

async function load(){
  if(loading) return;
  loading = true; failed = false;
  try{
    const r = await fetch("/api/rhythm");
    if(!r.ok) throw new Error("status " + r.status);
    data = await r.json();
    wk = R.weeks(data, data.today); wi = wk.length - 1; day = wk[wi].end;
  }catch(e){ failed = true; }
  loading = false;
}

const cur = () => wk[wi];
const EX = () => R.explainFor(data);
function pickDay(d){ day = d; }

// ---- drawing ----
function paint(){
  if(!root || !shown) return;
  if(failed){ root.innerHTML = `<div class="rh-head"><h2>My rhythm</h2></div><p>My rhythm could not be loaded.</p>`; return; }
  if(!data){ root.innerHTML = `<div class="rh-head"><h2>My rhythm</h2></div><p>Loading.</p>`; return; }
  if(data.on === false){ root.innerHTML = `<div class="rh-head"><h2>My rhythm</h2><span class="rh-badge">${esc(data.badge || R.BADGE)}</span></div><p>Collection is switched off (QUARTERDECK_ATTENTION=off), so there is nothing to show.</p>`; return; }
  if(!R.enough(data, data.today)){
    root.innerHTML = `<div class="rh-head"><h2>My rhythm</h2><span class="rh-badge">${esc(data.badge || R.BADGE)}</span></div>
      <div class="rh-card"><h3>Not enough yet</h3><p style="font-size:16px;margin:0">My rhythm needs a few days of your commits, notes and calendar before it can say anything honest. ${data.events.length} event${data.events.length === 1 ? "" : "s"} so far. It reads them every 30 minutes and keeps only counts per hour.</p></div>`;
    return;
  }
  root.innerHTML = `<div class="rh-head"><h2>My rhythm</h2><span class="rh-badge">${esc(data.badge || R.BADGE)}</span></div>
    <div class="rh-pick"><sl-button size="small" data-act="prev" aria-label="Earlier week"><sl-icon name="chevron-left"></sl-icon></sl-button>
      <sl-range id="rh-range" min="0" max="${wk.length - 1}" value="${wi}" label="Week to show"></sl-range>
      <sl-button size="small" data-act="next" aria-label="Later week"><sl-icon name="chevron-right"></sl-icon></sl-button><b id="rh-week">${esc(cur().label)}</b></div>
    <div id="rh-body">${body()}</div>`;
}

function repaintBody(){
  const b = root && root.querySelector("#rh-body"); if(b) b.innerHTML = body();
  const l = root && root.querySelector("#rh-week"); if(l) l.textContent = cur().label;
  const r = root && root.querySelector("#rh-range"); if(r) r.value = wi;
}

function body(){
  const end = cur().end, st = R.weekStats(data, end, data.today);
  return `<div class="rh-grid">
    <div class="rh-card">${heat(end)}</div>
    <div class="rh-card">${strip()}</div>
    <div class="rh-card rh-wide">${tasksCard()}</div>
    <div class="rh-wide"><div class="rh-stats">${stats(st, end)}</div></div>
    <div class="rh-card rh-wide"><h3>Three quiet observations</h3><ul class="rh-obs">${R.observations(data, end).map((t, i) => `<li><button data-act="why" data-k="observation" data-v="${esc(t)}">${esc(t)}</button></li>`).join("")}</ul></div>
  </div>${explainBox()}`;
}

function heat(end){
  const h = R.heatmap(data, end), cells = [];
  cells.push(`<span></span>` + h.days.map(d => `<span class="mon">${R.weekday(d) === 1 ? esc(R.shortDate(d)) : ""}</span>`).join(""));
  h.hours.forEach((hr, r) => {
    cells.push(`<span class="lab">${hr % 3 === 0 ? hr : ""}</span>` + h.days.map((d, c) => {
      const n = h.counts[r][c], sel = d === day;
      return `<button class="rh-cell rh-l${h.levels[r][c]}${sel ? " sel" : ""}" data-act="cell" data-day="${d}" data-n="${n}" data-hr="${hr}" aria-label="${esc(R.dayLabel(d))}, ${hr} o'clock: ${n} action${n === 1 ? "" : "s"}"></button>`;
    }).join(""));
  });
  return `<h3>Active hours, last 5 weeks</h3><div class="rh-heat">${cells.join("")}</div>
    <div class="rh-key"><span>Fewer</span>${[0, 1, 2, 3, 4].map(l => `<i class="rh-l${l}"></i>`).join("")}<span>More</span></div>`;
}

function strip(){
  const s = R.dayStrip(data, day), today = day === data.today, nm = today ? "Today" : R.dayLabel(day);
  const sw = R.switches(data, day), us = R.usualSwitches(data, day);
  const segs = s.segments.map(x => {
    const nm2 = {focus: "Focus block", meeting: "Meeting", gap: "Gap"}[x.type], w = (x.mins / s.total * 100).toFixed(2);
    return `<button class="rh-seg ${x.type}" style="flex:${w} 1 0" data-act="seg" data-t="${x.type}" data-m="${x.mins}" data-l="${esc(x.label)}" aria-label="${nm2} ${esc(x.label)}, ${esc(R.hoursText(x.mins))}">${x.mins >= 70 ? esc(R.hoursText(x.mins)) : ""}</button>`;
  }).join("");
  const days = R.weekDays(cur().end).map(d => `<sl-button size="small"${d === day ? ' variant="primary"' : ""} data-act="day" data-day="${d}" aria-pressed="${d === day}">${esc(R.dayLabel(d))}</sl-button>`).join("");
  const starts = s.meetingStarts && s.meetingStarts.length ? `<button class="rh-stat" style="margin-top:8px;width:100%" data-act="why" data-k="strip" data-v="Calendar blocks started at ${esc(s.meetingStarts.map(m => Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0")).join(", "))}"><span style="margin:0">Calendar blocks started at ${esc(s.meetingStarts.map(m => Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0")).join(", "))}</span></button>` : "";
  return `<h3>${esc(nm)}: focus, meetings and gaps</h3>
    ${s.segments.length ? `<div class="rh-strip">${segs}</div><div class="rh-axis"><span>${s.from / 60}:00</span><span>${s.to / 60}:00</span></div>
      <div class="rh-key"><i class="rh-seg focus"></i>Focus${s.segments.some(x => x.type === "meeting") ? '<i class="rh-seg meeting"></i>Meeting' : ""}<i class="rh-seg gap"></i>Gap</div>` : `<p>Nothing on this day.</p>`}${starts}
    <div class="rh-days">${days}</div>
    <button class="rh-stat" style="margin-top:10px;width:100%" data-act="why" data-k="switches" data-v="${esc(R.switchNote(sw, us, today ? "today" : "on " + R.dayLabel(day)))}"><b>${sw}</b><span>${esc(R.switchNote(sw, us, today ? "today" : "on this day"))}</span><small>How is this worked out?</small></button>`;
}

const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)", "var(--series-6)", "var(--series-7)"];
const colorOf = name => COLORS[[...String(name)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % COLORS.length];
const KIND = {commit: "Commit", branch: "Branch", pr: "Pull request", note: "Note", run: "Run started by hand", meeting: "Calendar"};
const STORE = () => (R.isReal(data) ? `Task titles (commit subject lines, branch names, pull request titles, note text, run objectives and calendar titles) are kept in ${esc((data.tasks && data.tasks.file) || "state/rhythm-tasks.json")} on this Mac, readable by you only, for 400 days, and never sent anywhere. Delete them with: rm -f state/rhythm-tasks.json`
  : "These tasks are invented. Nothing is stored.");
function tasksCard(){
  const title = `What I worked on, ${day === data.today ? "today" : R.dayLabel(day)}${proj ? ", " + proj : ""}`;
  if(!R.tasksOn(data)) return `<h3>${esc(title)}</h3><p>Task titles are switched off (QUARTERDECK_RHYTHM_TASKS=off), so only counts are shown.</p>`;
  const bl = R.taskBlocks(data, day).filter(b => !proj || b.project === proj), sm = R.projectSummary(bl);
  if(!bl.length) return `<h3>${esc(title)}</h3><p>Nothing recorded on this day. Only commits, branches, pull requests, notes, hand-started runs and calendar blocks can show up here.</p><p class="rh-store">${STORE()}</p>`;
  const chips = sm.map(x => `<button class="rh-chip" data-act="why" data-k="tasks" data-v="${esc(R.summaryLine(x))}"><i style="background:${colorOf(x.project)}"></i>${esc(R.summaryLine(x))}</button>`).join("");
  const rows = bl.map((b, i) => {
    const key = day + ":" + i, open = openBlk === key;
    const head = b.kind === "meeting" ? `${R.clock(b.from)}` : `${R.clock(b.from)} to ${R.clock(b.to)}`;
    return `<div class="rh-block"><button class="rh-bhead" data-act="blk" data-k="${key}" aria-expanded="${open}"><span class="rh-time">${esc(head)}</span>
      <span class="rh-proj"><i style="background:${b.kind === "meeting" ? "var(--await)" : colorOf(b.project)}"></i>${esc(b.kind === "meeting" ? "Meeting" : b.project || "No project")}</span><span class="rh-label">${esc(b.label)}</span></button>
      ${open ? `<ul class="rh-ev">${b.evidence.map(x => `<li><b>${R.clock(x.m)}</b> ${esc(KIND[x.kind] || x.kind)}${x.outside ? " (checked out earlier)" : ""}: ${esc(x.label || "no label")}</li>`).join("")}</ul>` : ""}</div>`;
  }).join("");
  return `<h3>${esc(title)}</h3><div class="rh-chips">${chips}</div><div class="rh-blocks">${rows}</div>
    <button class="rh-stat" style="margin-top:8px;width:100%" data-act="why" data-k="tasks" data-v="How the blocks and labels are worked out"><span style="margin:0">How are these blocks worked out?</span></button>
    <p class="rh-store">${STORE()}</p>`;
}

function stats(st, end){
  const L = st.longest, M = st.meetings;
  const card = (k, val, sub, v) => `<button class="rh-stat" data-act="why" data-k="${k}" data-v="${esc(v)}"><b>${esc(val)}</b><span>${esc(sub)}</span><small>How is this worked out?</small></button>`;
  return card("longest", L ? R.hoursText(L.mins) : "None", L ? `Longest focus block, ${R.dayLabel(L.day)}` : "Longest focus block this week", L ? `${R.dayLabel(L.day)}, ${Math.floor(L.from / 60)}:${String(L.from % 60).padStart(2, "0")} to ${Math.floor(L.to / 60)}:${String(L.to % 60).padStart(2, "0")}.` : "No block of 30 minutes or more in this week.")
    + card("streak", `${st.streak} day${st.streak === 1 ? "" : "s"}`, "In a row with a block of 90 minutes or more", `${st.streak} working day${st.streak === 1 ? "" : "s"} in a row, ending ${R.dayLabel(end)}.`)
    + (M.mins === null ? card("meetings", `${M.count} meeting${M.count === 1 ? "" : "s"}`, `Calendar blocks, ${M.word}`, `${M.count} this week and ${M.prevCount} the week before.`)
      : card("meetings", R.hoursText(M.mins), `Meetings, ${M.word}`, `${R.hoursText(M.mins)} this week and ${R.hoursText(M.prev)} the week before.`));
}

function explainBox(){
  if(!note) return "";
  return `<div class="rh-explain" role="status" aria-live="polite"><sl-icon-button class="x" name="x-lg" label="Close this note" data-act="close" style="float:right;margin:-8px -8px 0 8px"></sl-icon-button><b>${esc(note.title)}</b>${esc(note.text)}</div>`;
}

// ---- events ----
function onClick(e){
  const t = e.target.closest("[data-act]"); if(!t || !data) return;
  const a = t.dataset.act;
  if(a === "close"){ note = null; return repaintBody(); }
  if(a === "blk"){ openBlk = openBlk === t.dataset.k ? "" : t.dataset.k; return repaintBody(); }
  if(a === "prev" || a === "next"){ wi = Math.max(0, Math.min(wk.length - 1, wi + (a === "next" ? 1 : -1))); day = cur().end; note = null; return repaintBody(); }
  if(a === "day"){ pickDay(t.dataset.day); note = null; return repaintBody(); }
  if(a === "cell"){
    pickDay(t.dataset.day);
    const n = +t.dataset.n;
    note = {title: `${R.dayLabel(t.dataset.day)}, ${t.dataset.hr} to ${+t.dataset.hr + 1} o'clock: ${n} action${n === 1 ? "" : "s"}`, text: EX().heat};
    return repaintBody();
  }
  if(a === "seg"){
    const nm = {focus: "Focus block", meeting: "Meeting", gap: "Gap"}[t.dataset.t];
    note = {title: `${nm}, ${t.dataset.l}, ${R.hoursText(+t.dataset.m)}`, text: t.dataset.t === "focus" ? EX().block : EX().strip};
    return repaintBody();
  }
  if(a === "why"){
    note = {title: t.dataset.v, text: EX()[t.dataset.k] || EX().heat};
    return repaintBody();
  }
}
function onInput(e){
  if(e.target.id !== "rh-range" || !data) return;
  wi = +e.target.value; day = cur().end; note = null; repaintBody();
}
