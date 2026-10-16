// The brain view: a 3D brain whose regions are the areas of the work, whose dots
// are the live things inside them, and whose lines are what connects one to
// another. It draws what it is handed and owns no data: index.html builds the
// graph from the dashboard's state and hands it to setGraph().
//
// Every string in a graph can come from outside (a PR title, an email subject),
// so nothing here ever goes through innerHTML: text is set as text.
import * as THREE from "three";
import {OrbitControls} from "./vendor/OrbitControls.js";
import {buildHead} from "./head.js";

// Colours are handed to the shaders as written, so they must not be converted.
THREE.ColorManagement.enabled = false;

export const REGIONS = {
  code:     {name: "Code",       color: "#38b6ff"},
  ops:      {name: "Operations", color: "#35d07f"},
  agents:   {name: "Agents",     color: "#f5c451"},
  world:    {name: "The world",  color: "#ff8f6b"},
  thinking: {name: "Thinking",   color: "#5eead4"},
  system:   {name: "System",     color: "#9fb0c4"},
};
const STATE = {idle: 0, live: 1, attn: 2, off: 3, new: 4};

// ---- seeded randomness: the same id always lands in the same place ----------
function hash(str){
  let h = 1779033703 ^ str.length;
  for(let i = 0; i < str.length; i++){ h = Math.imul(h ^ str.charCodeAt(i), 3432918353); h = h << 13 | h >>> 19; }
  return () => { h = Math.imul(h ^ h >>> 16, 2246822507); h = Math.imul(h ^ h >>> 13, 3266489909); return (h ^= h >>> 16) >>> 0; };
}
function rng(seed){
  let a = hash(String(seed))();
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

// ---- the shape ---------------------------------------------------------------
// x is left-right, y up, z toward the face. A brain is two hemispheres, a temporal
// lobe low on each side, a cerebellum behind and below, and a stem.
const HEMI = [-0.5, 0.5].map(x => ({c: [x, 0.08, 0], r: [0.62, 0.72, 1.12], part: "hemi"}));
const TEMP = [-0.74, 0.74].map(x => ({c: [x, -0.4, 0.3], r: [0.36, 0.3, 0.6], part: "temporal"}));
const CEREB = {c: [0, -0.6, -0.85], r: [0.62, 0.34, 0.42], part: "cerebellum"};
const BODIES = [...HEMI, ...TEMP, CEREB];
const inside = (b, p) => Math.hypot((p[0]-b.c[0])/b.r[0], (p[1]-b.c[1])/b.r[1], (p[2]-b.c[2])/b.r[2]);

function regionOf(part, p){
  if(part === "stem") return "system";
  if(part === "cerebellum") return "thinking";
  if(part === "temporal") return "agents";
  return p[2] > 0.4 ? "code" : p[2] < -0.45 ? "world" : "ops";
}

const unitOn = rand => { const z = rand()*2-1, t = rand()*Math.PI*2, r = Math.sqrt(1-z*z); return [r*Math.cos(t), z, r*Math.sin(t)]; };

function buildShell(){
  const rand = rng("shell");
  const pts = [];                      // {p, c, region}
  const unit = () => unitOn(rand);
  for(const b of BODIES){
    const want = b.part === "hemi" ? 2600 : b.part === "temporal" ? 700 : 900;
    let got = 0;
    for(let n = 0; got < want && n < want*6; n++){
      const d = unit(), p = [b.c[0]+d[0]*b.r[0], b.c[1]+d[1]*b.r[1], b.c[2]+d[2]*b.r[2]];
      if(BODIES.some(o => o !== b && inside(o, p) < 0.985)) continue;
      // folds: a shallow ridge pattern along the surface, so it reads as cortex
      const f = 1 + 0.045*Math.sin(7.3*p[0]+3.1*p[1]) * Math.sin(6.1*p[2]-2.0*p[0]) + 0.02*Math.sin(17*p[1]+9*p[2]);
      pts.push({p: [b.c[0]+d[0]*b.r[0]*f, b.c[1]+d[1]*b.r[1]*f, b.c[2]+d[2]*b.r[2]*f], c: b.c, region: regionOf(b.part, p)});
      got++;
    }
  }
  for(let n = 0; n < 500; n++){        // the stem
    const y = -0.45 - rand()*0.85, t = rand()*Math.PI*2, r = 0.2 - (-0.45 - y)*0.06;
    const p = [Math.cos(t)*r, y, -0.4 + Math.sin(t)*r];
    if(BODIES.some(o => inside(o, p) < 0.985)) continue;
    pts.push({p, c: [0, y, -0.4], region: "system"});
  }
  return pts;
}

// ---- the module's one instance ----------------------------------------------
let host, stage, canvas, renderer, scene, camera, controls, overlay, tip, panel, legend, stats, focusBar, clockEl, lblEl;
let shellPts, headPts, nodePts, linkLines, shell, showHead = true;
let graph = {nodes: [], links: []}, sig = "";
let nodes = [], byId = new Map(), placed = new Map(), hidden = new Set();
let hoverId = null, selId = null, running = false, opts = {}, ro, t0 = performance.now();
let regionLabels = {}, hubLabels = new Map(), ready = false;
const CAM0 = [5.5, 0.6, 3.2], TARGET0 = [0, -0.9, 0];

// A focus is one or two areas (a hub and everything hanging off it) and a clock. Everything
// else dims. It is a personal convenience, so it lives in this browser only.
const FOCUS_KEY = "quarterdeck.focus";
let focus = null;
try{
  const f = JSON.parse(localStorage.getItem(FOCUS_KEY) || "null");
  if(f && Array.isArray(f.ids) && f.ids.length && f.ids.length <= 2 && f.ids.every(i => typeof i === "string") && Number.isFinite(f.endsAt)) focus = f;
}catch(e){}
const saveFocus = () => {
  try{ focus ? localStorage.setItem(FOCUS_KEY, JSON.stringify(focus)) : localStorage.removeItem(FOCUS_KEY); }catch(e){}
  window.dispatchEvent(new Event("quarterdeck-focus"));
};
const groupOf = n => n.parent || n.id;
const dimmed = n => !!focus && focus.ids.some(i => byId.has(i)) && !focus.ids.includes(groupOf(n));

// A close control is Shoelace's own icon button, top right of its panel, with a label for assistive technology.
const xBtn = label => { const b = document.createElement("sl-icon-button"); b.className = "x"; b.setAttribute("name", "x-lg"); b.setAttribute("label", label); return b; };
// A small button from the page's component set (Shoelace), for the side panels and the focus bar. Text only; a link opens in a new tab.
const sbtn = (text, href) => { const b = document.createElement("sl-button"); b.setAttribute("size", "small"); b.textContent = text; if(href){ b.setAttribute("href", href); b.setAttribute("target", "_blank"); b.setAttribute("rel", "noopener"); } return b; };
const el = (tag, cls, text) => { const e = document.createElement(tag); if(cls) e.className = cls; if(text !== undefined) e.textContent = text; return e; };

function init(){
  // The host is a row: the scene (stage) and, when something is open, the side panel beside it (below it on a phone). The panel never
  // covers the scene, so the canvas simply takes the room that is left.
  host = el("div", "brain-host");
  stage = el("div", "brain-stage");
  canvas = el("canvas", "brain-canvas");
  overlay = el("div", "brain-overlay");
  tip = el("div", "brain-tip"); tip.hidden = true;
  panel = el("div", "brain-panel"); panel.hidden = true;
  panel.setAttribute("role", "region"); panel.setAttribute("aria-label", "Brain details");
  legend = el("div", "brain-legend");
  legend.setAttribute("role", "group"); legend.setAttribute("aria-label", "Areas of the map");
  stats = el("div", "brain-stats");
  stats.setAttribute("role", "group"); stats.setAttribute("aria-label", "Counts by state");
  focusBar = el("div", "brain-focus"); focusBar.hidden = true;
  const hud = el("div", "brain-hud"); hud.append(stats, focusBar);
  stage.append(canvas, overlay, tip, hud, legend);
  host.append(stage, panel);

  renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: false});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  renderer.setClearColor(0x070a10, 1);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 50);
  camera.position.set(...CAM0);
  controls = new OrbitControls(camera, canvas);
  controls.target.set(...TARGET0);
  Object.assign(controls, {enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 2.2, maxDistance: 11,
                           autoRotate: true, autoRotateSpeed: 0.25});

  shell = buildShell();
  const pos = new Float32Array(shell.length*3), col = new Float32Array(shell.length*3), bg = new THREE.Color(0x070a10);
  shell.forEach((s, i) => {
    pos.set(s.p, i*3);
    new THREE.Color(REGIONS[s.region].color).lerp(bg, 0.62).toArray(col, i*3);
  });
  const sg = new THREE.BufferGeometry();
  sg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  sg.setAttribute("color", new THREE.BufferAttribute(col, 3));
  shellPts = new THREE.Points(sg, new THREE.ShaderMaterial({
    uniforms: {uScale: {value: 1}, uCam: {value: 5}},
    vertexShader: `attribute vec3 color; varying vec3 vC; varying float vD; uniform float uScale, uCam;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); gl_Position = projectionMatrix*mv;
        gl_PointSize = 0.011*uScale/(-mv.z); vC = color;
        vD = 1.0 - 0.7*clamp((-mv.z-(uCam-1.4))/2.8, 0.0, 1.0); }`,
    fragmentShader: `varying vec3 vC; varying float vD;
      void main(){ vec2 c = gl_PointCoord-0.5; if(length(c) > 0.5) discard; gl_FragColor = vec4(vC*vD, 1.0); }`,
  }));
  scene.add(shellPts);

  const hg = new THREE.BufferGeometry();
  hg.setAttribute("position", new THREE.BufferAttribute(buildHead(rng("head")), 3));
  headPts = new THREE.Points(hg, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, uniforms: {uScale: {value: 1}, uCam: {value: 5}},
    vertexShader: `varying float vD; uniform float uScale, uCam;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); gl_Position = projectionMatrix*mv;
        gl_PointSize = 0.010*uScale/(-mv.z);
        vD = (1.0 - 0.6*clamp((-mv.z-(uCam-1.9))/3.6, 0.0, 1.0)) * smoothstep(-3.9, -2.4, position.y); }`,
    fragmentShader: `varying float vD;
      void main(){ if(length(gl_PointCoord-0.5) > 0.5) discard; gl_FragColor = vec4(vec3(0.42, 0.5, 0.62)*vD, 0.5*vD); }`,
  }));
  scene.add(headPts);

  for(const [k, r] of Object.entries(REGIONS)){
    const mine = shell.filter(s => s.region === k);
    const c = mine.reduce((a, s) => [a[0]+s.p[0], a[1]+s.p[1], a[2]+s.p[2]], [0, 0, 0]).map(v => v/mine.length);
    const l = el("div", "brain-region", r.name.toUpperCase()); l.style.color = r.color;
    overlay.append(l); regionLabels[k] = {el: l, at: new THREE.Vector3(...c).multiplyScalar(1.28)};
  }

  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", () => { hoverId = null; tip.hidden = true; paintNodes(); });
  let down = null;
  canvas.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", e => {
    if(!down || Math.hypot(e.clientX-down[0], e.clientY-down[1]) > 5) return;
    down = null; select(pick(e));
  });
  canvas.addEventListener("dblclick", e => { const n = pick(e); if(n && opts.onOpen) opts.onOpen(n); });
  canvas.addEventListener("contextmenu", e => { e.preventDefault(); camera.position.set(...CAM0); controls.target.set(...TARGET0); });
  ro = new ResizeObserver(resize); ro.observe(stage);
  buildLegend(); paintFocus();
  setInterval(tickFocus, 1000);
  ready = true;
}

function resize(){
  const w = stage.clientWidth, h = stage.clientHeight;
  if(!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w/h; camera.updateProjectionMatrix();
  shellPts.material.uniforms.uScale.value = headPts.material.uniforms.uScale.value = h * renderer.getPixelRatio() * 1.452;
  if(nodePts) nodePts.material.uniforms.uScale.value = h * renderer.getPixelRatio() * 1.452;
}

// ---- placing nodes -----------------------------------------------------------
const byRegion = k => shell.filter(s => s.region === k);
function nearest(p){ let d = 1e9; for(const q of placed.values()) d = Math.min(d, Math.hypot(p[0]-q[0], p[1]-q[1], p[2]-q[2])); return d; }

function place(n){
  if(placed.has(n.id)) return;
  const r = rng(n.id);
  const near = n.near && placed.get(n.near);          // pull towards a related dot, but stay inside the own region
  const parent = !near && n.parent && placed.get(n.parent);
  let pool = parent ? null : byRegion(n.region);
  if(near) pool = pool.map(s => [Math.hypot(s.p[0]-near[0], s.p[1]-near[1], s.p[2]-near[2]), s]).sort((a, b) => a[0] - b[0]).slice(0, 80).map(x => x[1]);
  let best = null;
  for(let i = 0; i < 40; i++){
    let p;
    if(parent){
      const z = r()*2-1, t = r()*Math.PI*2, k = Math.sqrt(1-z*z), rad = 0.17 + r()*0.2;
      p = [parent[0]+k*Math.cos(t)*rad, parent[1]+z*rad, parent[2]+k*Math.sin(t)*rad];
    }else{
      const s = pool[Math.floor(r()*pool.length)];
      p = [s.c[0]+(s.p[0]-s.c[0])*0.8, s.c[1]+(s.p[1]-s.c[1])*0.8, s.c[2]+(s.p[2]-s.c[2])*0.8];
    }
    const gap = nearest(p);
    if(!best || gap > best.gap) best = {p, gap};
    if(gap > (parent ? 0.11 : 0.34)) break;
  }
  placed.set(n.id, best.p);
}

// ---- drawing the graph -------------------------------------------------------
const shown = () => nodes.filter(n => !hidden.has(n.region));

function rebuild(){
  if(nodePts){ scene.remove(nodePts); nodePts.geometry.dispose(); }
  if(linkLines){ scene.remove(linkLines); linkLines.geometry.dispose(); }
  for(const l of hubLabels.values()) l.el.remove();
  hubLabels = new Map();
  const vis = shown(), idx = new Map(vis.map((n, i) => [n.id, i]));

  const pos = new Float32Array(vis.length*3), colr = new Float32Array(vis.length*3);
  vis.forEach((n, i) => { pos.set(placed.get(n.id), i*3); new THREE.Color(REGIONS[n.region].color).toArray(colr, i*3); });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(colr, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(vis.length), 1));
  g.setAttribute("aState", new THREE.BufferAttribute(new Float32Array(vis.length), 1));
  g.setAttribute("aDim", new THREE.BufferAttribute(new Float32Array(vis.length).fill(1), 1));
  nodePts = new THREE.Points(g, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: {uScale: {value: canvas.clientHeight * renderer.getPixelRatio() * 1.452}, uTime: {value: 0}, uCam: {value: 5}},
    vertexShader: `attribute vec3 aColor; attribute float aSize, aState, aDim; varying vec3 vC; varying float vS, vD, vA;
      uniform float uScale, uTime, uCam;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); gl_Position = projectionMatrix*mv;
        float pulse = aState > 0.5 && aState < 1.5 ? 1.0 + 0.18*sin(uTime*1.6) : 1.0;
        gl_PointSize = aSize*pulse*uScale/(-mv.z); vC = aColor; vS = aState; vA = aDim;
        vD = 1.0 - 0.55*clamp((-mv.z-(uCam-1.4))/2.8, 0.0, 1.0); }`,
    fragmentShader: `varying vec3 vC; varying float vS, vD, vA;
      void main(){ float d = length(gl_PointCoord-0.5)*2.0; if(d > 1.0) discard;
        vec3 col = vC; float a = 1.0 - smoothstep(0.9, 1.0, d);
        if(vS > 2.5 && vS < 3.5){ if(d < 0.55) discard; }                 // not connected: a ring, nothing inside
        else if(vS > 1.5 && vS < 2.5){ if(d > 0.7) col = vec3(1.0, 0.42, 0.42); }   // needs you: red rim
        else if(vS > 3.5){ if(d > 0.7) col = vec3(1.0); }                 // something new: white rim
        else if(vS > 0.5){ if(d > 0.78) col = vec3(1.0); }                // working now: pale rim
        gl_FragColor = vec4(col*vD, a*vA); }`,
  }));
  scene.add(nodePts);

  const lp = [], lc = [], bg = new THREE.Color(0x070a10);
  for(const [a, b] of graph.links){
    if(!idx.has(a) || !idx.has(b)) continue;
    const A = byId.get(a), B = byId.get(b);
    lp.push(...placed.get(a), ...placed.get(b));
    const ca = new THREE.Color(REGIONS[A.region].color).lerp(bg, 0.55), cb = new THREE.Color(REGIONS[B.region].color).lerp(bg, 0.55);
    lc.push(ca.r, ca.g, ca.b, cb.r, cb.g, cb.b);
  }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.Float32BufferAttribute(lp, 3));
  lg.setAttribute("color", new THREE.Float32BufferAttribute(lc, 3));
  linkLines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({vertexColors: true}));
  scene.add(linkLines);

  for(const n of vis) if(n.hub){
    const l = el("div", "brain-hub", n.label);
    const kids = nodes.filter(k => k.parent === n.id), bad = kids.filter(k => k.state === "attn").length + (n.state === "attn" ? 1 : 0);
    const cnt = kids.length || n.count;
    const open = (txt, cls, label, sel) => { const b = el("button", cls, txt); b.type = "button"; b.setAttribute("aria-label", label); b.onclick = () => openList(sel); return b; };
    if(kids.length) l.append(" ", open(String(cnt), "n", `${cnt} things under ${n.label}, list them`, {kind: "hub", key: n.id}));
    else if(cnt) l.append(el("span", "n", " " + cnt));
    if(bad) l.append(" ", open(`${bad} need you`, "bad", `${bad} under ${n.label} need you, list them`, {kind: "hub", key: n.id, only: "attn"}));
    overlay.append(l); hubLabels.set(n.id, {el: l, v: new THREE.Vector3(...placed.get(n.id)), n});
  }
  paintNodes();
}

function paintNodes(){
  if(!nodePts) return;
  const vis = shown(), size = nodePts.geometry.attributes.aSize, st = nodePts.geometry.attributes.aState, dm = nodePts.geometry.attributes.aDim;
  vis.forEach((n, i) => {
    let s = n.hub ? 0.075 : 0.045;
    if(n.count) s *= 0.75 + Math.min(n.count, 40)/40;
    if(typeof n.weight === "number") s *= 0.55 + 1.45 * Math.min(1, Math.max(0, n.weight));     // size by my attention: the page sets weight 0 to 1
    if(n.id === hoverId || n.id === selId) s *= 1.4;
    size.setX(i, s); st.setX(i, STATE[n.state] ?? 0); dm.setX(i, dimmed(n) ? 0.14 : 1);
  });
  size.needsUpdate = st.needsUpdate = dm.needsUpdate = true;
}

function buildLegend(){
  legend.replaceChildren();
  for(const [k, r] of Object.entries(REGIONS)){
    const count = nodes.filter(n => n.region === k).length, on = !hidden.has(k);
    const seg = el("span", "brain-seg" + (on ? "" : " off"));
    const b = el("button", "brain-chip");
    const sw = el("span", "sw"); sw.style.background = r.color;
    b.append(sw, el("span", "", r.name));
    b.type = "button"; b.setAttribute("aria-pressed", String(on)); b.title = (on ? "Hide " : "Show ") + r.name + " on the map";
    b.onclick = () => { hidden.has(k) ? hidden.delete(k) : hidden.add(k); buildLegend(); rebuild(); };
    const c = el("button", "brain-count", String(count)); c.type = "button"; c.disabled = !count;
    c.setAttribute("aria-label", `${count} in ${r.name}, list them`); c.onclick = () => openList({kind: "region", key: k});
    seg.append(b, c); legend.append(seg);
  }
  const hb = el("button", "brain-chip lone" + (showHead ? "" : " off"), "Head");
  hb.type = "button"; hb.setAttribute("aria-pressed", String(showHead)); hb.title = "Show or hide the outline of the head";
  hb.onclick = () => { showHead = !showHead; headPts.visible = showHead; buildLegend(); };
  legend.append(hb);
}

function buildStats(){
  const c = {attn: 0, live: 0, new: 0, off: 0};
  for(const n of nodes) if(n.state in c) c[n.state]++;
  stats.replaceChildren(...[["attn", "Need you"], ["live", "Working"], ["new", "New"], ["off", "Not connected"]].map(([k, w]) => {
    const s = el("button", "st" + (k === "attn" && c.attn ? " bad" : "")); s.type = "button"; s.disabled = !c[k];
    s.setAttribute("aria-label", `${c[k]} ${w.toLowerCase()}, list them`); s.append(el("b", "", String(c[k])), el("span", "", w));
    s.onclick = () => openList({kind: "state", key: k}); return s;
  }));
}

// ---- focus -------------------------------------------------------------------
const pad = v => String(v).padStart(2, "0");
function startFocus(n){
  const g = groupOf(n), name = (byId.get(g) || n).label;
  if(!focus) focus = {ids: [g], names: [name], endsAt: Date.now() + 25*60000};
  else if(!focus.ids.includes(g)){ focus.ids = [...focus.ids, g].slice(-2); focus.names = [...(focus.names || []), name].slice(-2); }
  saveFocus(); paintNodes(); paintFocus(); showPanel();
}
function stopFocus(){ focus = null; saveFocus(); paintNodes(); paintFocus(); showPanel(); }
function paintFocus(){
  focusBar.hidden = !focus;
  if(!focus) return;
  const names = focus.ids.map((i, k) => byId.get(i)?.label || (focus.names || [])[k] || i.replace(/^\w+:/, "")).join(" + ");
  const more = sbtn("+5 min"), stop = sbtn("Stop");
  more.onclick = () => { focus.endsAt = Math.max(focus.endsAt, Date.now()) + 5*60000; saveFocus(); tickFocus(); };
  stop.onclick = stopFocus;
  lblEl = el("span", "lbl", "Focus"); clockEl = el("span", "clock", "");
  focusBar.replaceChildren(lblEl, el("b", "", names), clockEl, more, stop);
  tickFocus();
}
function tickFocus(){
  if(!focus || !clockEl) return;
  const left = focus.endsAt - Date.now(), a = Math.abs(left);
  clockEl.textContent = (left < 0 ? "+" : "") + pad(Math.floor(a/60000)) + ":" + pad(Math.floor(a/1000) % 60);
  lblEl.textContent = left < 0 ? "Time is up" : "Focus";
  focusBar.classList.toggle("done", left < 0);
}

// ---- picking and the detail panel -------------------------------------------
function screenOf(n){
  const v = new THREE.Vector3(...placed.get(n.id)).project(camera);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  return {x: (v.x+1)/2*w, y: (1-v.y)/2*h, z: v.z};
}
function pick(e){
  const r = canvas.getBoundingClientRect(), mx = e.clientX-r.left, my = e.clientY-r.top;
  let best = null;
  for(const n of shown()){
    const s = screenOf(n), d = Math.hypot(s.x-mx, s.y-my), reach = n.hub ? 16 : 11;
    if(d < reach && (!best || s.z < best.z)) best = {n, z: s.z};
  }
  return best && best.n;
}
function onMove(e){
  const n = pick(e), id = n ? n.id : null;
  if(id !== hoverId){ hoverId = id; paintNodes(); }
  canvas.style.cursor = n ? "pointer" : "grab";
  if(!n){ tip.hidden = true; return; }
  tip.replaceChildren(el("b", "", n.label), ...(n.sub ? [el("span", "", n.sub)] : []));
  const r = canvas.getBoundingClientRect();
  tip.style.left = Math.min(e.clientX-r.left+14, r.width-260) + "px"; tip.style.top = (e.clientY-r.top+14) + "px";
  tip.hidden = false;
}
function select(n){
  selId = n ? n.id : null; paintNodes(); showPanel();
}
// ---- the side panel: a node's card, or the list behind a count --------------------------------------------------
// The page decides what is in a list (index.html builds it with assets/brainlists.js); this only shows it, in the dashboard's own
// parts: a mono kicker, a heading, pills, sl-details sections and .li rows. Opening one never moves the camera.
let listSel = null, listSpec = null, landOnPanel = false;
const STATE_PILL = {attn: ["bad", "Needs you"], live: ["running", "Working"], new: ["blue", "New"], off: ["", "Not connected"], idle: ["", "Quiet"]};
const pillOf = state => { const [cls, label] = STATE_PILL[state] || STATE_PILL.idle; return el("span", "pill " + cls, label); };
const section = (title, open = true) => { const d = document.createElement("sl-details"); d.setAttribute("summary", title); if(open) d.setAttribute("open", ""); return d; };
const panelHead = (kicker, title, closeLabel, onClose, extra) => {
  const close = xBtn(closeLabel); close.onclick = onClose;
  const top = el("div", "pk"); top.append(el("span", "kicker", kicker), close);
  const h = el("h2", "pt", title); h.tabIndex = -1;
  const head = el("header", "hd"); head.append(top, h, ...(extra || []));
  return {head, h};
};
function openList(sel){ listSel = sel; selId = null; landOnPanel = true; paintNodes(); if(opts.onList) opts.onList(sel); }
export function showList(spec){ listSpec = spec; if(!selId) renderList(); }
export function closePanel(){
  if(panel.hidden) return false;
  if(selId){ select(null); return true; }
  listSel = listSpec = null; panel.hidden = true; return true;
}
function listRow(r){
  const row = el("div", "lrow"), main = el("div", "lmain");
  const t = el("div", "lt"); t.append(el("b", "", r.label));
  if(r.state && r.state !== "idle") t.append(pillOf(r.state));
  main.append(t);
  if(r.sub) main.append(el("p", "", r.sub));
  if(r.source) main.append(el("span", "src", r.source));
  if(r.doc) main.append(el("p", "doc", r.doc));
  if(typeof r.bar === "number"){ const bar = el("div", "lbar"), fill = el("i"); fill.style.width = Math.round(Math.min(1, Math.max(0, r.bar)) * 100) + "%"; bar.append(fill); main.append(bar); }   // flat, no animation
  const acts = el("div", "acts");
  for(const a of r.actions || []){
    if(a.url && /^https:\/\//.test(a.url)) acts.append(sbtn(a.label, a.url));
    else{ const b = sbtn(a.label); b.onclick = () => a.run && a.run(); acts.append(b); }
  }
  if(byId.has(r.id)){ const show = sbtn("Show on map"); show.onclick = () => select(byId.get(r.id)); acts.append(show); }
  row.append(main, ...(acts.childElementCount ? [acts] : []));
  return row;
}
function renderList(){
  if(!listSpec){ panel.hidden = true; return; }
  const keep = panel.scrollTop, n = listSpec.rows.filter(r => !r.head).length;
  const {head, h} = panelHead("List", listSpec.title, "Close the list", () => { listSel = listSpec = null; panel.hidden = true; },
    listSpec.nocount ? [] : [el("span", "pill", `${n} ${n === 1 ? "item" : "items"}`)]);
  const body = el("div", "lists");
  if(!listSpec.rows.length) body.append(el("p", "lempty", listSpec.empty || "Nothing here."));
  // rows come in sections ({head: true, label}); each section is a collapsible sl-details, rows before the first one stand alone
  let into = body;
  for(const r of listSpec.rows){
    if(r.head){ into = section(r.label); body.append(into); continue; }
    into.append(listRow(r));
  }
  const foot = el("div", "acts");
  for(const a of listSpec.foot || []){ const b = sbtn(a.label); b.onclick = () => a.run && a.run(); foot.append(b); }
  panel.replaceChildren(head, body, ...(listSpec.foot && listSpec.foot.length ? [foot] : []));
  panel.hidden = false; panel.scrollTop = keep;
  if(landOnPanel){ landOnPanel = false; h.focus({preventScroll: true}); }
}
function showPanel(){
  const n = byId.get(selId);
  if(!n){ if(listSpec) renderList(); else panel.hidden = true; return; }
  const reg = REGIONS[n.region], inFocus = !!(focus && focus.ids.includes(groupOf(n)));
  const pills = el("div", "pills"); pills.append(pillOf(n.state));
  if(inFocus) pills.append(el("span", "pill blue", "In focus"));
  const {head} = panelHead(`${reg.name} / ${n.kind}`, n.label, "Close the details", () => select(null), [pills]);
  const body = el("div", "lists");
  if(n.sub) body.append(el("p", "psub", n.sub));
  if((n.lines || []).length){ const d = section("Details"); n.lines.forEach(l => d.append(el("p", "dl", l))); body.append(d); }
  const kids = nodes.filter(k => k.parent === n.id), up = n.parent && byId.get(n.parent);
  if(up || kids.length){
    const d = section(kids.length ? `Inside this (${kids.length})` : "Part of", !!up && !kids.length);
    const link = k => {
      const b = el("button", "lk", k.label); b.type = "button"; b.onclick = () => select(k);
      const main = el("div", "lmain"); main.append(b, ...(k.state !== "idle" ? [pillOf(k.state)] : []));
      const r = el("div", "lrow tight"); r.append(main); return r;
    };
    if(up) d.append(link(up));
    kids.slice(0, 12).forEach(k => d.append(link(k)));
    if(kids.length > 12) d.append(el("p", "dl", `and ${kids.length - 12} more`));
    body.append(d);
  }
  const acts = el("div", "acts");
  for(const a of n.actions || []){
    if(a.url && /^https:\/\//.test(a.url)){ acts.append(sbtn(a.label, a.url)); }
    else{ const b = sbtn(a.label); b.onclick = () => opts.onAction && opts.onAction(a); acts.append(b); }
  }
  if(!inFocus){
    const f = sbtn(!focus ? "Focus 25 min" : focus.ids.length < 2 ? "Add to focus" : "Swap focus");
    f.onclick = () => startFocus(n); acts.append(f);
  }
  if(listSpec){ const back = sbtn("Back to the list"); back.onclick = () => { selId = null; paintNodes(); renderList(); }; acts.prepend(back); }
  panel.replaceChildren(head, body, acts);
  panel.hidden = false; panel.scrollTop = 0;
}

// ---- the frame loop ----------------------------------------------------------
function frame(){
  if(!host.isConnected){ running = false; return; }
  requestAnimationFrame(frame);
  if(document.hidden) return;
  const t = (performance.now()-t0)/1000, dist = camera.position.length();
  const calm = document.documentElement.classList.contains("calm");
  controls.autoRotate = !hoverId && !selId && !calm;
  controls.update();
  shellPts.material.uniforms.uCam.value = headPts.material.uniforms.uCam.value = dist;
  if(nodePts){ nodePts.material.uniforms.uTime.value = calm ? 0 : t; nodePts.material.uniforms.uCam.value = dist; }
  const w = canvas.clientWidth, h = canvas.clientHeight, v = new THREE.Vector3();
  const place2 = (label, at, dx, dy, k = 1) => {
    v.copy(at).project(camera);
    const depth = 1 - 0.65*Math.min(1, Math.max(0, (camera.position.distanceTo(at) - (dist-1.4)) / 2.8));
    label.style.transform = `translate(${(v.x+1)/2*w+dx}px,${(1-v.y)/2*h+dy}px)`;
    label.style.opacity = (depth*k).toFixed(2);
  };
  for(const r of Object.values(regionLabels)) place2(r.el, r.at, -30, -8);
  for(const l of hubLabels.values()) place2(l.el, l.v, 18, -8, dimmed(l.n) ? 0.25 : 1);
  renderer.render(scene, camera);
}

// ---- what index.html calls ---------------------------------------------------
export function attach(slot, options){
  if(!ready) init();
  opts = options || {};
  slot.replaceChildren(host);
  resize();
  if(!running){ running = true; requestAnimationFrame(frame); }
}

export function setGraph(g){
  if(!ready) return;
  const next = JSON.stringify(g);
  if(next === sig) return;
  sig = next; graph = g;
  nodes = g.nodes; byId = new Map(nodes.map(n => [n.id, n]));
  for(const n of nodes.filter(n => !n.parent)) place(n);
  for(const n of nodes.filter(n => n.parent)) place(n);
  if(selId && !byId.has(selId)) selId = null;
  buildLegend(); buildStats(); rebuild(); paintFocus(); showPanel();
  if(listSel && opts.onList) opts.onList(listSel);       // an open list follows the data
}

export function focusNode(id){
  const n = byId.get(id), at = placed.get(id);
  if(!n || !at) return false;
  if(hidden.has(n.region)){ hidden.delete(n.region); buildLegend(); rebuild(); }
  select(n);
  controls.target.set(...at);
  return true;
}

export default {attach, setGraph, focusNode, showList, closePanel};
