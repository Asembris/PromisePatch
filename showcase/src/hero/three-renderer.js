// makeThree(): the prototype's three.js renderer, ported with named imports
// so Vite can tree-shake it into its own lazy chunk. Pinned to three r149,
// the release the prototype ran, whose default colour handling (no colour
// management) is what the approved frames were captured with.
// Changes from the prototype: `preserveDrawingBuffer` is dropped (it was for
// design-tool screenshots), and `dispose()` also removes the canvas.

import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Mesh, CircleGeometry, RingGeometry, PlaneGeometry,
  BufferGeometry, BufferAttribute, Line, LineBasicMaterial, LineDashedMaterial, Points, PointsMaterial,
  MeshBasicMaterial, Color, Vector3,
} from 'three';
import { K } from './constants.js';

/** @param {HTMLElement} host */
export function makeThree(host) {
  const r = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); r.setClearColor(0x000000, 0);
  host.appendChild(r.domElement); Object.assign(r.domElement.style, { position: 'absolute', inset: '0', width: '100%', height: '100%' });
  const scene = new Scene(), cam = new PerspectiveCamera(28, 1, 0.1, 200), v = new Vector3();
  const M = (c, o = 1) => new MeshBasicMaterial({ color: new Color(c), transparent: true, opacity: o, depthWrite: false });
  const mesh = (g, c, o, parent) => { const x = new Mesh(g, M(c, o)); (parent || root).add(x); return x; };
  const line = (pts, mat) => { const g = new BufferGeometry().setFromPoints(pts.map(p => new Vector3(p[0], p[1], p[2] || 0))); const l = new Line(g, mat); root.add(l); return l; };
  let root = null, W = 1, H = 1, dist = 16; const R = {}; const O = {};
  const build = (L) => {
    if (root) { scene.remove(root); root.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); }); }
    root = new Group(); scene.add(root);
    const n = L.m ? 70 : 170, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { pos[i * 3] = (Math.random() - .5) * L.w * 1.7; pos[i * 3 + 1] = (Math.random() - .5) * L.h * 1.5; pos[i * 3 + 2] = -2.5 - Math.random() * 7; }
    const dg = new BufferGeometry(); dg.setAttribute('position', new BufferAttribute(pos, 3));
    O.dust = new Points(dg, new PointsMaterial({ color: new Color(K.brand), size: 0.04, transparent: true, opacity: .32, depthWrite: false })); root.add(O.dust);
    O.lanes = Object.keys(L.lanes).map(k => { const z = (k === 'UN' ? -0.9 : 0) - 0.06; return line([[L.x0 - 0.5, L.lanes[k], z], [L.done + 0.5, L.lanes[k], z]], new LineBasicMaterial({ color: new Color('#33405F'), transparent: true, opacity: 0 })); });
    if (!L.m) [L.x0 - 0.5].forEach(x => { const l = line([[L.srcS[0] + 0.24, L.srcS[1], 0], [x, L.lanes.UN, -0.96]], new LineDashedMaterial({ color: new Color(K.ring), dashSize: .1, gapSize: .12, transparent: true, opacity: .32 })); l.computeLineDistances(); });
    O.edges = [0, 1, 2, 3].map(() => { const g = new BufferGeometry(); g.setAttribute('position', new BufferAttribute(new Float32Array(6), 3)); const l = new Line(g, new LineBasicMaterial({ color: new Color(K.ink), transparent: true, opacity: .2 })); root.add(l); return l; });
    O.srcHalo = mesh(new CircleGeometry(.7, 48), K.owner, 0); O.srcHalo.position.set(L.srcR[0], L.srcR[1], -0.01);
    O.src = mesh(new RingGeometry(.2, .26, 48), K.owner, 1); O.src.position.set(L.srcR[0], L.srcR[1], 0);
    O.srcDot = mesh(new CircleGeometry(.1, 24), K.owner, 1); O.srcDot.position.set(L.srcR[0], L.srcR[1], 0);
    if (!L.m) { const s = mesh(new RingGeometry(.16, .2, 48), K.ring, .7); s.position.set(L.srcS[0], L.srcS[1], 0); }
    O.nodes = {};
    ['A', 'B', 'C', 'D', 'E', 'F'].forEach(id => {
      const g = new Group(); root.add(g);
      O.nodes[id] = { g, halo: mesh(new CircleGeometry(.62, 48), K.done, 0, g), c: mesh(new CircleGeometry(.27, 48), K.bg, 1, g), r: mesh(new RingGeometry(.29, .335, 48), K.ring, 1, g), s: mesh(new CircleGeometry(.36, 4, Math.PI / 4), K.owner, 1, g), sr: mesh(new RingGeometry(.39, .44, 4, 1, Math.PI / 4), K.owner, 1, g) };
    });
    O.cust = new Group(); root.add(O.cust); mesh(new CircleGeometry(.2, 40), K.bg, 1, O.cust); mesh(new RingGeometry(.21, .245, 40), K.muted, 1, O.cust);
    O.custLine = line([[0, 0, 0], [0, 0, 0]], new LineDashedMaterial({ color: new Color(K.muted), dashSize: .06, gapSize: .08, transparent: true, opacity: 0 }));
    O.parts = Array.from({ length: 10 }, () => { const x = mesh(new CircleGeometry(.075, 20), K.ink, 1); x.visible = false; return x; });
    O.clock = mesh(new RingGeometry(.46, .49, 48, 1, 0, Math.PI * 1.35), K.ask, 0);
    O.gate = new Group(); root.add(O.gate); O.gate.position.set(L.gate, L.lanes.ASK, 0);
    O.gTop = new Group(); O.gBot = new Group(); O.gate.add(O.gTop); O.gate.add(O.gBot);
    O.ticks = [];
    for (let i = 0; i < 10; i++) { const y = -0.52 + i * 0.116; const grp = i < 5 ? O.gBot : O.gTop; const tk = mesh(new PlaneGeometry(.36, .055), '#33405F', 1, grp); tk.position.set(0, y, 0); O.ticks.push(tk); }
    O.capT = mesh(new PlaneGeometry(.5, .035), K.brand, 1, O.gTop); O.capT.position.set(0, 0.62, 0);
    O.capB = mesh(new PlaneGeometry(.5, .035), K.brand, 1, O.gBot); O.capB.position.set(0, -0.62, 0);
    O.post = mesh(new PlaneGeometry(.025, 1.24), K.brand, .5, O.gate); O.post.position.set(-0.2, 0, -0.01);
    R.L = L;
  };
  R.resize = (w, h, L, rebuild) => { W = w; H = h; r.setSize(w, h, false); cam.aspect = w / h; const f = Math.tan(14 * Math.PI / 180); dist = Math.max((L.h / 2) / f, (L.w / 2) / (f * cam.aspect)) * 1.03; cam.updateProjectionMatrix(); if (rebuild) build(L); };
  R.draw = (sc, px, py, time) => {
    cam.position.set(px * 0.9, -py * 0.55, dist); cam.lookAt(0, 0, 0);
    O.dust.position.x = Math.sin(time * 0.05) * 0.25; O.dust.position.y = Math.cos(time * 0.04) * 0.15;
    O.lanes.forEach(l => l.material.opacity = sc.laneOp * 0.9);
    O.srcHalo.material.opacity = sc.srcHalo * 0.22; O.srcHalo.scale.setScalar(0.6 + sc.srcHalo * 0.6);
    sc.edges.forEach((e, i) => { const a = O.edges[i].geometry.attributes.position.array; a[0] = e.a.x; a[1] = e.a.y; a[2] = -0.04; a[3] = e.b.x; a[4] = e.b.y; a[5] = e.b.z - 0.04; O.edges[i].visible = e.op > 0.005; O.edges[i].geometry.attributes.position.needsUpdate = true; O.edges[i].material.opacity = e.op; });
    for (const id in sc.N) { const n = sc.N[id], o = O.nodes[id]; o.g.position.set(n.x, n.y, n.z); const mo = n.morph || 0; o.c.visible = o.r.visible = mo < 1; o.s.visible = mo > 0; o.sr.visible = false; o.c.material.color.set(n.fill); o.r.material.color.set(n.ring); o.s.material.color.set(n.fill); o.c.material.opacity = o.r.material.opacity = 1 - mo; o.s.material.opacity = mo; o.s.scale.setScalar(0.72 + 0.28 * mo); o.c.scale.setScalar(1 - 0.15 * mo); o.r.scale.setScalar(1 - 0.15 * mo); o.halo.material.opacity = n.halo * 0.45; o.halo.scale.setScalar(0.8 + n.halo * 0.5); }
    O.cust.position.set(sc.cust.x, sc.cust.y, 0); O.cust.children.forEach(c => c.material.opacity = sc.custOp);
    const cla = O.custLine.geometry.attributes.position.array; cla[0] = sc.N.B.x; cla[1] = sc.N.B.y; cla[3] = sc.cust.x; cla[4] = sc.cust.y; O.custLine.geometry.attributes.position.needsUpdate = true; O.custLine.computeLineDistances(); O.custLine.material.opacity = sc.custLink; O.custLine.visible = sc.custLink > 0.005;
    O.parts.forEach((p, i) => { const q = sc.parts[i]; p.visible = !!q; if (q) { p.position.set(q.x, q.y, 0.02); p.material.color.set(q.c); p.material.opacity = q.o == null ? 1 : q.o; p.scale.setScalar(q.s); } });
    O.clock.position.set(sc.clock.x, sc.clock.y, 0.01); O.clock.rotation.z = -time * 2.4; O.clock.material.opacity = sc.clock.op;
    [O.capT, O.capB, O.post].forEach(x => x.material.opacity = sc.gate.op * (x === O.post ? 0.5 : 1));
    O.ticks.forEach((tk, i) => { tk.material.color.set(sc.gate.passed ? K.done : i < sc.gate.n ? K.brand : '#33405F'); tk.material.opacity = sc.gate.op; });
    O.gTop.position.y = sc.gate.open * 0.3; O.gBot.position.y = -sc.gate.open * 0.3;
    r.render(scene, cam);
  };
  R.project = (x, y, z) => { v.set(x, y, z).project(cam); return { x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H }; };
  R.dispose = () => { root && root.traverse(o => { o.geometry && o.geometry.dispose(); o.material && o.material.dispose(); }); r.dispose(); r.domElement.remove(); };
  return R;
}
