// The hero's constants, verbatim from the approved prototype's logic class:
// colours (K), phase starts (PH), the end of the timeline (END), the desktop
// (LD) and mobile (LM) layout tables in world units, the step labels, the
// captions, and the HTML label overlay. Nothing here is re-authored except
// two captions, corrected toward the repository record (CONTENT_SOURCES.md).

export const K = { bg: '#162038', ring: '#76819A', ink: '#F7F8FC', brand: '#8390F2', auto: '#42BCD3', ask: '#F2C374', owner: '#F18A76', done: '#F7F8FC', dark: '#0B1221', edge: '#26324D', muted: '#AEB6C8' };
export const PH = [0, 0.35, 1.25, 2.3, 3.25, 4.9, 6.9];
export const END = 8.2;
export const LD = { w: 13.2, h: 7.6, srcR: [-5.3, 1.0], srcS: [-5.3, -2.3], cl: { A: [-3.1, 2.1], B: [-2.0, 1.4], C: [-3.35, 0.3], D: [-2.2, -0.2] }, lanes: { AUTO: 2.3, ASK: 0.8, BLOCKED: -0.75, UN: -2.3 }, x0: 0.5, x1: 1.95, done: 5.3, gate: 3.4, cust: [1.65, 1.5], owner: [4.05, 5.3], lx: -0.2, m: false };
export const LM = { w: 7.0, h: 10.8, srcR: [-2.6, 4.45], srcS: [2.2, 4.7], cl: { A: [-1.6, 3.3], B: [0.0, 3.65], C: [-0.7, 2.75], D: [0.9, 3.0] }, lanes: { AUTO: 2.0, ASK: 0.3, BLOCKED: -2.2, UN: -4.0 }, x0: -2.3, x1: -0.7, done: 2.6, gate: 0.65, cust: [-1.25, -0.8], owner: [1.4, 2.6], lx: -3.3, m: true };

/** The stage switches to the mobile scene below this width (the stage's, not the viewport's). */
export const MOBILE_STAGE_MAX = 640;

/** Seconds the three.js chunk and renderer have to start before the SVG renderer takes over. */
export const THREE_TIMEOUT_MS = 4000;

export const PHASE_LABELS = ['Disruption', 'Reach', 'Partition', 'Act', 'Ask', 'Revalidate'];

export const CAPTIONS = [
  'A worker reports: “today’s raspberry delivery didn’t arrive.”',
  'The deterministic engine finds the four promises that failure reaches. Two orders without raspberries are never reached.',
  'Each reached promise lands in exactly one authority lane.',
  'The pre-authorized swap runs. Two orders go to the owner, with scheduled work held.',
  'One customer is asked and answers YES on a signed link. Conditions can change while an answer waits.',
  'Before the change is committed, the YES is checked again: ten checks against a fresh snapshot. Authority is still valid, so it proceeds.',
  '6 promises → 1 auto-recovered · 1 customer-approved · 2 owner-escalated · 2 untouched.',
];

export const RENDERER_LABELS = { webgl: 'WEBGL', svg: 'SVG FALLBACK' };
export const STAGE_LABEL = 'HOLLOW OAK BAKERY · CANONICAL CASE · ';

// The label overlay, one entry per prototype `data-k` element. `lines` are
// [class, text] pairs; a line with class containing `t` is the `data-t`
// target whose text the scene rewrites. `node`/`tag` entries carry `data-t`
// on the anchor itself.
export const LABELS = [
  { k: 'src', a: 'b', lines: [['hl__kicker hl--owner', 'NOT RECEIVED'], ['hl__name', 'Raspberry delivery']] },
  { k: 'srcS', a: 'b', lines: [['hl__kicker', 'RECEIVED'], ['hl__name hl__name--quiet', 'Strawberries']] },
  { k: 'l0', a: 'lane', lines: [['hl__lane hl--auto', '● AUTO'], ['hl__sub', 'existing permission']] },
  { k: 'l1', a: 'lane', lines: [['hl__lane hl--ask', '◆ ASK'], ['hl__sub', 'customer decides']] },
  { k: 'l2', a: 'lane', lines: [['hl__lane hl--owner', '■ BLOCKED'], ['hl__sub', 'owner decides']] },
  { k: 'l3', a: 'lane', lines: [['hl__lane hl--muted', '○ UNAFFECTED'], ['hl__sub', 'not reached']] },
  { k: 'done', a: 'b', text: 'hl__kicker', value: 'ORDER SYSTEM' },
  { k: 'cust', a: 'l', lines: [['hl__name hl__name--sm', 'Customer'], ['hl__sub', 'signed link']] },
  { k: 'gate', a: 'b', lines: [['hl__gate', 'REVALIDATE'], ['hl__gate-n t', '0/10 checks']] },
  ...['A', 'B', 'C', 'D', 'E', 'F'].map((id) => ({ k: 'n' + id, a: 'node', value: id })),
  ...['A', 'B', 'C', 'D', 'E', 'F'].map((id) => ({ k: 't' + id, a: 'tag', value: '' })),
];

/** Every string the hero can show, for the content gate. */
export const HERO_STRINGS = [
  ...CAPTIONS,
  ...PHASE_LABELS,
  STAGE_LABEL + RENDERER_LABELS.webgl,
  STAGE_LABEL + RENDERER_LABELS.svg,
  ...LABELS.flatMap((l) => (l.lines ? l.lines.map(([, text]) => text) : [l.value])).filter(Boolean),
  'REACHED', 'AUTO', 'ASK', 'BLOCKED', 'OWNER', 'UNTOUCHED', 'ASKING', 'YES · HELD', 'REVALIDATING', 'PROCEED', 'RECOVERED ✓',
  '10/10 ✓', '10/10 · still valid',
];
