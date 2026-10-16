// The human bust around the brain: a head in profile (brow, nose, lips, jaw), a strong neck and
// shoulders, drawn as contour rings of points like a body scan. x left-right, y up, z toward the face.
// Pure geometry: no three.js, so it can be drawn and checked on its own (bin/selftest.py runs it).

// [y, halfWidth, front, back] down the head; the cranium above y = 0.5 is a dome.
const HEAD = [
  [0.5, 1.30, 1.30, -1.40], [0.25, 1.31, 1.36, -1.44], [0.0, 1.30, 1.40, -1.46], [-0.15, 1.28, 1.47, -1.47],
  [-0.3, 1.24, 1.36, -1.48], [-0.45, 1.20, 1.34, -1.48], [-0.65, 1.15, 1.36, -1.44], [-0.85, 1.08, 1.38, -1.34],
  [-1.0, 1.00, 1.42, -1.24], [-1.1, 0.95, 1.47, -1.16], [-1.2, 0.90, 1.42, -1.08], [-1.3, 0.85, 1.46, -1.00],
  [-1.42, 0.82, 1.38, -0.90], [-1.6, 0.74, 1.36, -0.76], [-1.8, 0.56, 1.28, -0.60], [-1.95, 0.38, 1.05, -0.48],
  [-2.1, 0.20, 0.60, -0.38],
];
// Neck and shoulders: [y, halfWidth, halfDepth]. Centre z is NECK_Z.
const NECK_Z = -0.3;
const BODY = [
  [-1.3, 0.58, 0.55], [-2.2, 0.60, 0.55], [-2.6, 0.78, 0.60], [-2.95, 1.35, 0.72], [-3.25, 2.10, 0.80],
  [-3.6, 2.55, 0.85], [-4.0, 2.60, 0.85],
];
// The nose, added to the front of the face: [y, how far it stands out, half width].
const NOSE = [[-0.3, 0.0, 0.10], [-0.45, 0.12, 0.10], [-0.65, 0.32, 0.13], [-0.85, 0.52, 0.17], [-1.0, 0.48, 0.25], [-1.1, 0.16, 0.23], [-1.17, 0.0, 0.1]];

// Catmull-Rom through table rows, sampled at y (rows run downward). col picks the column.
function at(tbl, y, col){
  let i = 0;
  while(i < tbl.length - 2 && y < tbl[i + 1][0]) i++;
  const t = Math.max(0, Math.min(1, (y - tbl[i][0]) / (tbl[i + 1][0] - tbl[i][0])));
  const p = k => tbl[Math.max(0, Math.min(tbl.length - 1, k))][col];
  const [a, b, c, d] = [p(i - 1), p(i), p(i + 1), p(i + 2)];
  return b + 0.5*t*(c - a + t*(2*a - 5*b + 4*c - d + t*(3*(b - c) + d - a)));
}
const spow = (v, e) => Math.sign(v) * Math.abs(v) ** e;

// The cross-section of the head at height y: half width, front z, back z. Null outside the head.
export function headSlice(y){
  if(y > 1.18 || y < -2.1) return null;
  if(y >= 0.5){
    const s = Math.sqrt(1 - ((y - 0.5) / 0.68) ** 2);
    return {w: 1.30*s, front: 1.30*s, back: -1.40*s};
  }
  return {w: at(HEAD, y, 1), front: at(HEAD, y, 2), back: at(HEAD, y, 3)};
}

export function buildHead(rand){
  const out = [];
  const ring = (y, w, front, back, nose = 0, noseW = 1) => {
    const zc = (front + back) / 2, df = front - zc, db = zc - back, n = 2 / (y > 0 ? 2.0 : 2.3);
    const steps = Math.max(24, Math.round(6.28 * Math.max(w, 0.2) / 0.05));
    const row = [];
    for(let k = 0; k < steps; k++){
      const t = (k + rand()*0.6) / steps * Math.PI * 2, c = spow(Math.cos(t), n), s = spow(Math.sin(t), n);
      const x = w * c;
      row.push([x, y, zc + (s >= 0 ? df + nose * Math.exp(-((x / noseW) ** 2)) : db) * s]);
    }
    return row;
  };
  const inNeck = p => (p[0] / 0.6) ** 2 + ((p[2] - NECK_Z) / 0.56) ** 2 < 1;
  const keep = (p, half) => {                                    // a few points between the rings, so it reads as a surface
    out.push(...p);
    if(rand() < 0.5) out.push(p[0] + (rand() - 0.5)*0.03, p[1] + (rand() - 0.5)*half, p[2] + (rand() - 0.5)*0.03);
  };
  for(let y = 1.17; y > -2.1; y -= 0.055){                        // the head
    const h = headSlice(y);
    let nose = 0, noseW = 1;
    if(y < -0.3 && y > -1.17){ nose = at(NOSE, y, 1); noseW = Math.max(0.05, at(NOSE, y, 2)); }
    for(const p of ring(y, h.w, h.front, h.back, nose, noseW)) if(y > -1.3 || !inNeck(p)) keep(p, 0.055);
  }
  for(let y = -1.3; y > -4.0; y -= 0.07){                        // neck and shoulders
    const w = at(BODY, y, 1), d = at(BODY, y, 2);
    for(const p of ring(y, w, NECK_Z + d, NECK_Z - d)) keep(p, 0.07);
  }
  for(const sx of [-1, 1]){                                      // ears: two nested outlines at each side
    const w = headSlice(-0.5).w;
    for(const sc of [1, 0.62]) for(let k = 0; k < 40; k++){
      const t = k / 40 * Math.PI * 2;
      out.push(sx*(w + 0.04 + rand()*0.05), -0.5 + Math.sin(t)*0.34*sc, -0.22 + Math.cos(t)*0.2*sc);
    }
  }
  return new Float32Array(out);
}
