// scene(t, L): the hero's single scene model, verbatim from the prototype.
// A pure function of time and layout. It returns node positions, colours and
// shapes, particles, the gate, and label anchors in world units; both
// renderers draw exactly this, so they cannot disagree.

import { K } from './constants.js';

export function scene(t, L) {
  const io = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2, oq = x => 1 - Math.pow(1 - x, 4);
  const cl = v => Math.min(1, Math.max(0, v)), sg = (a, b) => cl((t - a) / (b - a)), mx = (a, b, p) => a + (b - a) * p;
  const Ln = L.lanes, hit = i => 0.8 + i * 0.08, N = {};
  const hx = c => { if (c[0] === 'r') return c.match(/\d+/g).map(Number); const v = parseInt(c.slice(1), 16); return [v >> 16, (v >> 8) & 255, v & 255]; };
  const mc = (a, b, p) => { if (p <= 0) return a; if (p >= 1) return b; const A = hx(a), B = hx(b); return 'rgb(' + A.map((v, i) => Math.round(v + (B[i] - v) * p)).join(',') + ')'; };
  const base = (id, x, y, z) => ({ id, x, y, z: z || 0, fill: K.bg, ring: K.ring, sq: false, letter: K.ink, tag: '', tagc: K.muted, halo: 0 });
  const reached = (n, i) => { if (t >= hit(i)) { n.ring = mc(K.ring, K.ink, sg(hit(i), hit(i) + 0.25)); n.tag = 'REACHED'; n.tagc = K.ink; } };
  const lane = (n, c, tag, sq, t0) => { const p = io(sg(t0, t0 + 0.35)); n.fill = mc(K.bg, c, p); n.ring = mc(n.ring, c, p); n.letter = p > 0.5 ? K.dark : K.ink; n.tag = tag; n.tagc = c; n.sq = !!sq && p > 0.5; n.morph = sq ? p : 0; };
  const done = (n, at) => { const p = io(sg(at, at + 0.35)); n.fill = mc(n.fill, K.done, p); n.ring = mc(n.ring, K.done, p); n.letter = K.dark; n.tag = 'RECOVERED ✓'; n.tagc = K.done; n.sq = false; const q = sg(at, at + 1.1); n.halo = Math.sin(q * Math.PI) * 0.55; };
  { const p1 = io(sg(1.25, 2.15)), p2 = oq(sg(2.3, 2.8)), c = L.cl.A; const n = base('A', mx(mx(c[0], L.x0, p1), L.done, p2), mx(c[1], Ln.AUTO, p1));
    reached(n, 0); if (t >= 1.25) lane(n, K.auto, 'AUTO', false, 1.25); if (t >= 2.8) done(n, 2.8); N.A = n; }
  { const p1 = io(sg(1.32, 2.22)), p2 = io(sg(4.9, 5.4)), p3 = io(sg(6.15, 6.7)), c = L.cl.B;
    let x = mx(c[0], L.x0, p1); x = mx(x, L.gate - (L.m ? 0.75 : 0.95), p2); x = mx(x, L.done, p3);
    const n = base('B', x, mx(c[1], Ln.ASK, p1)); reached(n, 1);
    if (t >= 1.32) lane(n, K.ask, 'ASK', false, 1.32);
    if (t >= 2.5 && t < 3.9) n.tag = 'ASKING';
    if (t >= 3.9 && t < 4.9) n.tag = 'YES · HELD';
    if (t >= 4.9 && t < 6.1) n.tag = 'REVALIDATING';
    if (t >= 6.1 && t < 6.7) n.tag = 'PROCEED';
    if (t >= 6.7) done(n, 6.7); N.B = n; }
  { const p1 = io(sg(1.38, 2.28)), p2 = io(sg(2.5, 3.1)), c = L.cl.C; const n = base('C', mx(mx(c[0], L.x0, p1), L.owner[0], p2), mx(c[1], Ln.BLOCKED, p1));
    reached(n, 2); if (t >= 1.38) lane(n, K.owner, 'BLOCKED', true, 1.38); if (t >= 3.1) n.tag = 'OWNER'; N.C = n; }
  { const p1 = io(sg(1.44, 2.34)), p2 = io(sg(2.56, 3.16)), c = L.cl.D; const n = base('D', mx(mx(c[0], L.x1, p1), L.owner[1], p2), mx(c[1], Ln.BLOCKED, p1));
    reached(n, 3); if (t >= 1.44) lane(n, K.owner, 'BLOCKED', true, 1.44); if (t >= 3.16) n.tag = 'OWNER'; N.D = n; }
  ['E', 'F'].forEach((id, i) => { const n = base(id, i ? L.x1 : L.x0, Ln.UN, -0.9); n.letter = K.muted; if (t >= 1.25) { n.tag = 'UNTOUCHED'; n.tagc = K.muted; } N[id] = n; });

  const src = { x: L.srcR[0], y: L.srcR[1] };
  const eop = t < 0.35 ? 0.22 : t < 2.2 ? 0.62 : Math.max(0, 0.62 - (t - 2.2) * 0.9);
  const edges = ['A', 'B', 'C', 'D'].map(id => ({ a: src, b: N[id], op: eop }));
  const parts = [];
  ['A', 'B', 'C', 'D'].forEach((id, i) => { const p = sg(0.35 + i * 0.08, hit(i)); if (p > 0 && p < 1) parts.push({ x: mx(src.x, N[id].x, p), y: mx(src.y, N[id].y, p), z: 0, c: K.ink, s: 1 }); });
  const cust = { x: L.cust[0], y: L.cust[1] }, custOp = sg(2.3, 2.6) * (1 - 0.45 * sg(6.7, 7.4)), custLink = sg(2.3, 2.6) * (1 - sg(6.2, 6.8)) * 0.45;
  { const p = sg(2.5, 3.0); if (p > 0 && p < 1) parts.push({ x: mx(N.B.x, cust.x, p), y: mx(N.B.y, cust.y, p), z: 0, c: K.muted, s: 0.8 }); }
  { const p = io(sg(3.3, 3.9)); if (p > 0 && p < 1) for (let k = 0; k < 4; k++) { const q = Math.max(0, p - k * 0.035); parts.push({ x: mx(cust.x, N.B.x, q), y: mx(cust.y, N.B.y, q), z: 0, c: K.ask, s: 1.35 - k * 0.3, o: 1 - k * 0.26 }); } }
  const gOp = sg(4.4, 4.9) * (1 - 0.4 * sg(7.3, 7.9)), gN = Math.floor(cl((t - 5.45) / 0.65) * 10), gOpen = io(sg(6.1, 6.35)) * (1 - io(sg(6.85, 7.35)));
  const srcHalo = t < 1.2 ? Math.sin(cl(t / 1.2) * Math.PI) : 0;
  const clock = { op: sg(3.9, 4.1) * (1 - sg(4.8, 4.95)), x: N.B.x, y: N.B.y };
  const laneOp = sg(1.05, 1.5);

  const lab = {};
  const m = L.m;
  lab.src = m ? { x: src.x + 0.42, y: src.y, op: 1, ax: 'l' } : { x: src.x, y: src.y + 0.5, op: 1, ax: 'b' };
  lab.srcS = { x: L.srcS[0], y: L.srcS[1] + 0.5, op: m ? 0 : 0.95 };
  const lk = ['AUTO', 'ASK', 'BLOCKED', 'UN'];
  lk.forEach((k, i) => { lab['l' + i] = m ? { x: L.lx, y: Ln[k] + 0.62, op: laneOp, ax: 'tl' } : { x: L.lx, y: Ln[k], op: laneOp, ax: 'r', z: k === 'UN' ? -0.9 : 0 }; });
  lab.done = m ? { x: L.done + 0.42, y: Ln.AUTO + 0.62, op: sg(2.6, 3.0), ax: 'r' } : { x: L.done, y: Ln.AUTO + 0.72, op: sg(2.6, 3.0), ax: 'b' };
  lab.cust = m ? { x: cust.x + 0.38, y: cust.y, op: custOp, ax: 'l' } : { x: cust.x - 0.36, y: cust.y, op: custOp, ax: 'r' };
  lab.gate = { x: L.gate, y: Ln.ASK + 1.02, op: gOp, text: t >= 6.1 ? (m ? '10/10 ✓' : '10/10 · still valid') : gN + '/10 checks' };
  for (const id in N) { const n = N[id]; lab['n' + id] = { x: n.x, y: n.y, z: n.z, op: 1, color: n.letter }; lab['t' + id] = { x: n.x, y: n.y - 0.42, z: n.z, op: n.tag ? 1 : 0, text: n.tag, color: n.tagc }; }
  return { N, edges, parts, cust, custOp, custLink, gate: { x: L.gate, y: Ln.ASK, op: gOp, n: gN, open: gOpen, passed: t >= 6.1 }, src, srcHalo, clock, laneOp, lab, t };
}

/** The phase a time belongs to: 0–5 are the six steps, 6 is the settled end. */
export function phaseOf(t, PH) {
  if (t >= PH[6]) return 6;
  for (let i = 5; i >= 0; i--) if (t >= PH[i]) return i;
  return 0;
}
