// The settled defaults the build injects at `<!-- @render:<name> -->` markers.
// These are the no-JS states: stage 7 Settled with order B, R3 at 10/10
// PROCEED, the Customer consent trace, and every proof row.

import { renderMatrix, renderStageNote, renderStepper } from './matrix.js';
import { renderDetail } from './detail.js';
import { renderGate } from './gate.js';
import { renderArchSvg, renderChain, renderTraceButtons, renderTraceText } from './arch.js';
import { renderProofs } from './proofs.js';
import { renderRehearsals } from './rehearsals.js';

export const SECTIONS = {
  'story-stepper': () => renderStepper(),
  'story-note': () => renderStageNote(),
  'story-matrix': () => renderMatrix(),
  'story-detail': () => renderDetail(),
  gate: () => renderGate(),
  'arch-traces': () => renderTraceButtons(),
  'arch-trace-text': () => renderTraceText(),
  'arch-svg': () => renderArchSvg(),
  'arch-chain': () => renderChain(),
  rehearsals: () => renderRehearsals(),
  proofs: () => renderProofs(),
};
