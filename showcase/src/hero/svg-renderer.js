// makeSvg(): the prototype's SVG renderer, unchanged. It draws the same scene
// model as the three.js renderer with a flat world-to-pixel fit, and costs no
// dependency. It runs when WebGL is unavailable, three.js does not load or
// start in time, or `?renderer=svg` asks for it.

import { K } from './constants.js';

/** @param {HTMLElement} host */
export function makeSvg(host) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg'); Object.assign(svg.style, { position: 'absolute', inset: '0', width: '100%', height: '100%' }); host.appendChild(svg);
  let L, s = 1, ox = 0, oy = 0; const O = {};
  const X = x => ox + (x + L.w / 2) * s, Y = y => oy + (L.h / 2 - y) * s;
  const el = (tag, at, p) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); (p || svg).appendChild(e); return e; };
  const R = {};
  const build = () => {
    svg.innerHTML = '';
    O.lanes = Object.keys(L.lanes).map(k => el('line', { x1: X(L.x0 - 0.5), x2: X(L.done + 0.5), y1: Y(L.lanes[k]), y2: Y(L.lanes[k]), stroke: '#33405F', 'stroke-width': 1, opacity: 0 }));
    if (!L.m) [L.x0 - 0.5].forEach(x => el('line', { x1: X(L.srcS[0] + 0.22), y1: Y(L.srcS[1]), x2: X(x), y2: Y(L.lanes.UN), stroke: K.ring, 'stroke-dasharray': '4 5', opacity: .35 }));
    O.edges = [0, 1, 2, 3].map(() => el('line', { stroke: K.ink, 'stroke-width': 1 }));
    el('circle', { cx: X(L.srcR[0]), cy: Y(L.srcR[1]), r: .23 * s, fill: 'none', stroke: K.owner, 'stroke-width': .06 * s });
    el('circle', { cx: X(L.srcR[0]), cy: Y(L.srcR[1]), r: .1 * s, fill: K.owner });
    if (!L.m) el('circle', { cx: X(L.srcS[0]), cy: Y(L.srcS[1]), r: .18 * s, fill: 'none', stroke: K.ring, 'stroke-width': .04 * s });
    O.custLine = el('line', { stroke: K.muted, 'stroke-dasharray': '3 4', opacity: 0 });
    O.cust = el('circle', { r: .22 * s, fill: K.bg, stroke: K.muted, 'stroke-width': .035 * s, opacity: 0 });
    O.gate = el('g', {}); O.gTop = el('g', {}, O.gate); O.gBot = el('g', {}, O.gate); O.ticks = [];
    for (let i = 0; i < 10; i++) { const y = -0.52 + i * 0.116; O.ticks.push(el('rect', { x: X(L.gate - 0.18), y: Y(L.lanes.ASK + y + 0.027), width: .36 * s, height: .055 * s, fill: '#33405F' }, i < 5 ? O.gBot : O.gTop)); }
    el('rect', { x: X(L.gate - 0.25), y: Y(L.lanes.ASK + 0.64), width: .5 * s, height: .035 * s, fill: K.brand }, O.gTop);
    el('rect', { x: X(L.gate - 0.25), y: Y(L.lanes.ASK - 0.6), width: .5 * s, height: .035 * s, fill: K.brand }, O.gBot);
    O.nodes = {};
    ['A', 'B', 'C', 'D', 'E', 'F'].forEach(id => { const g = el('g', {}); O.nodes[id] = { g, halo: el('circle', { r: .62 * s, fill: K.done, opacity: 0 }, g), c: el('circle', { r: .3 * s, 'stroke-width': .045 * s }, g), q: el('rect', { x: -.34 * s, y: -.34 * s, width: .68 * s, height: .68 * s, rx: .04 * s }, g) }; });
    O.clock = el('circle', { r: .47 * s, fill: 'none', stroke: K.ask, 'stroke-width': .03 * s, 'stroke-dasharray': `${.47 * s * 4.2} ${.47 * s * 2.1}`, opacity: 0 });
    O.parts = Array.from({ length: 10 }, () => el('circle', { r: .075 * s, opacity: 0 }));
  };
  R.resize = (w, h, l) => { L = l; s = Math.min(w / L.w, h / L.h); ox = (w - L.w * s) / 2; oy = (h - L.h * s) / 2; build(); };
  R.draw = (sc, px, py, time) => {
    O.lanes.forEach(l => l.setAttribute('opacity', sc.laneOp));
    sc.edges.forEach((e, i) => { const x = O.edges[i]; x.setAttribute('x1', X(e.a.x)); x.setAttribute('y1', Y(e.a.y)); x.setAttribute('x2', X(e.b.x)); x.setAttribute('y2', Y(e.b.y)); x.setAttribute('opacity', e.op); });
    for (const id in sc.N) { const n = sc.N[id], o = O.nodes[id]; o.g.setAttribute('transform', `translate(${X(n.x)},${Y(n.y)})`); o.c.style.display = n.sq ? 'none' : ''; o.q.style.display = n.sq ? '' : 'none'; o.c.setAttribute('fill', n.fill); o.c.setAttribute('stroke', n.ring); o.q.setAttribute('fill', n.fill); o.halo.setAttribute('opacity', n.halo * 0.3); }
    O.cust.setAttribute('cx', X(sc.cust.x)); O.cust.setAttribute('cy', Y(sc.cust.y)); O.cust.setAttribute('opacity', sc.custOp);
    O.custLine.setAttribute('x1', X(sc.N.B.x)); O.custLine.setAttribute('y1', Y(sc.N.B.y)); O.custLine.setAttribute('x2', X(sc.cust.x)); O.custLine.setAttribute('y2', Y(sc.cust.y)); O.custLine.setAttribute('opacity', sc.custLink);
    O.parts.forEach((p, i) => { const q = sc.parts[i]; if (!q) { p.setAttribute('opacity', 0); return; } p.setAttribute('cx', X(q.x)); p.setAttribute('cy', Y(q.y)); p.setAttribute('fill', q.c); p.setAttribute('r', .075 * s * q.s); p.setAttribute('opacity', q.o == null ? 1 : q.o); });
    O.clock.setAttribute('cx', X(sc.clock.x)); O.clock.setAttribute('cy', Y(sc.clock.y)); O.clock.setAttribute('opacity', sc.clock.op); O.clock.style.transformOrigin = `${X(sc.clock.x)}px ${Y(sc.clock.y)}px`; O.clock.style.transform = `rotate(${time * 140}deg)`;
    O.gate.setAttribute('opacity', sc.gate.op);
    O.ticks.forEach((tk, i) => tk.setAttribute('fill', sc.gate.passed ? K.done : i < sc.gate.n ? K.brand : '#33405F'));
    O.gTop.setAttribute('transform', `translate(0,${-sc.gate.open * 0.3 * s})`); O.gBot.setAttribute('transform', `translate(0,${sc.gate.open * 0.3 * s})`);
  };
  R.project = (x, y) => ({ x: X(x), y: Y(y) });
  R.dispose = () => { svg.remove(); };
  return R;
}
