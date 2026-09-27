// Every string the page can show only after an interaction (another stage,
// another order, the illustration, another trace). The content gate checks
// these beside the no-JS page, so a runtime-only sentence is gated too.

import { STAGES } from '../src/data/stages.js';
import { ROWS } from '../src/data/rows.js';
import { DET } from '../src/data/detail.js';
import { CHECKS, GATE_MODES, GATE_PENDING_SUB } from '../src/data/checks.js';
import { TRACES } from '../src/data/traces.js';
import { ARCH } from '../src/data/arch.js';
import { PROOFS } from '../src/data/proofs.js';
import { gateAnnouncement } from '../src/render/gate.js';
import { stageAnnouncement } from '../src/render/matrix.js';

export function strings() {
  const out = [];
  STAGES.forEach((s, i) => out.push(s.name, s.note, stageAnnouncement(i)));
  Object.values(ROWS).forEach((row) => row.forEach(([, text]) => out.push(text)));
  Object.values(DET).forEach((d) => out.push(d.why, d.who, d.out, d.fx));
  CHECKS.forEach((c) => out.push(...c));
  Object.entries(GATE_MODES).forEach(([key, m]) => {
    out.push(m.button, m.header, m.verdict, m.sub, m.note, gateAnnouncement(key));
    if (m.failValue) out.push(m.failValue);
  });
  out.push(GATE_PENDING_SUB);
  Object.values(TRACES).forEach((t) => out.push(t.label, t.text));
  ARCH.forEach((a) => out.push(...a.filter(Boolean)));
  PROOFS.forEach((p) => out.push(p[0], p[1]));
  return out;
}
