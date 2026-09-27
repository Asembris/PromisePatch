// The architecture, verbatim from the approved prototype: ARCH (the stacked
// chain shown below 1080px) and the 1200 × 570 diagram's edges, edge labels
// and nodes (shown from 1080px). No node or flow is added here.

export const ARCH = [
  ['Worker / agent client', 'OUTSIDE', 'MCP bearer token, or a signed-in session'],
  ['MCP server', 'OUTSIDE', 'Streamable HTTP · 2025-11-25 · no DB access'],
  ['Intent API', 'AUTHORITY', 'actor and clock are server-derived'],
  ['Semantic boundary', 'UNDERSTANDING', 'proposes a reading, never authority'],
  ['promise_graph engine', 'AUTHORITY', 'reach · partition · revalidate'],
  ['Durable workflow · PostgreSQL', 'AUTHORITY', 'governed amendment, after revalidation'],
  ['External order system', 'OUTSIDE', 'system of record · signed events back'],
  ['Telegram, outbound', 'OUTSIDE', 'one message'],
  ['Signed approval link', 'OUTSIDE', 'literal YES or NO'],
  ['Fresh revalidation', 'AUTHORITY', 'ten checks against a fresh snapshot'],
  ['Governed effect', 'AUTHORITY', ''],
];

export const ARCH_LABEL = 'Architecture: worker browser and MCP clients reach the Intent API; the durable workflow consults the deterministic promise_graph engine, sends words to a dashed semantic boundary that returns a candidate reading only, pushes governed amendments to the external order system, and sends one Telegram message whose signed-link answer returns for revalidation.';

/** [id, path, dashed, both ends] */
export const EDGES = [
  ['e1', 'M200 102 C 340 102 340 190 480 190', false, false],
  ['e2', 'M200 292 L 250 292', false, false],
  ['e3', 'M430 292 C 456 292 456 222 480 222', false, false],
  ['e4', 'M660 202 L 720 202', false, false],
  ['e5a', 'M790 160 L 790 96', true, false],
  ['e5b', 'M850 96 L 850 160', true, false],
  ['e6', 'M760 246 C 760 330 710 382 662 382', false, true],
  ['e7', 'M900 186 L 998 186', false, false],
  ['e8', 'M1000 220 L 902 220', false, false],
  ['e9', 'M880 246 C 880 330 930 372 998 372', false, false],
  ['e10', 'M1090 414 L 1090 468', false, false],
  ['e11', 'M1000 512 L 902 512', false, false],
  ['e12', 'M810 470 L 810 248', false, false],
];

/** [x, y, text, anchor] — mono 11px #AEB6C8 */
export const EDGE_LABELS = [
  [258, 94, 'session: the only place a plan approval is written'],
  [206, 318, 'bearer'],
  [444, 240, 'service token', 'end'],
  [782, 130, 'the words', 'end'],
  [858, 130, 'candidate reading, never authority'],
  [704, 318, 'reach · partition', 'end'],
  [704, 332, '· revalidate', 'end'],
  [950, 178, 'amendment', 'middle'],
  [950, 238, 'signed events', 'middle'],
  [946, 330, '1 message'],
  [951, 530, 'YES / NO', 'middle'],
  [818, 420, 'answer → revalidate'],
];

/**
 * kind: outside | authority | understanding.
 * title: [x, y, text, anchor?]; lines: [x, y, text, fontSize].
 */
export const NODES = [
  { x: 20, y: 60, w: 180, h: 84, rx: 12, kind: 'outside', title: [38, 94, 'Bakery worker'], lines: [[38, 118, 'voice or text', 11.5]] },
  { x: 20, y: 250, w: 180, h: 84, rx: 12, kind: 'outside', title: [38, 284, 'Alexa+-style agent'], lines: [[38, 308, 'any MCP client', 12]] },
  { x: 250, y: 250, w: 180, h: 84, rx: 12, kind: 'outside', title: [268, 280, 'MCP server'], lines: [[268, 302, 'Streamable HTTP', 11.5], [268, 319, '2025-11-25 · no DB', 11.5]] },
  { x: 480, y: 160, w: 180, h: 84, rx: 12, kind: 'authority', title: [498, 194, 'Intent API'], lines: [[498, 212, 'actor + clock are', 11.5], [498, 229, 'server-derived', 11.5]] },
  { x: 720, y: 12, w: 180, h: 84, rx: 12, kind: 'understanding', title: [738, 42, 'Semantic boundary'], lines: [[738, 64, 'Amazon Bedrock', 11.5], [738, 81, 'proposes a reading', 11.5]] },
  { x: 720, y: 160, w: 180, h: 86, rx: 12, kind: 'authority', title: [738, 190, 'Durable workflow'], lines: [[738, 212, 'state machine + ledger', 11.5], [738, 229, 'PostgreSQL', 11.5]] },
  { x: 480, y: 340, w: 180, h: 84, rx: 12, kind: 'authority', title: [498, 370, 'promise_graph'], lines: [[498, 392, 'deterministic engine', 11.5], [498, 409, 'no I/O · no clock', 11.5]] },
  { x: 1000, y: 160, w: 180, h: 84, rx: 12, kind: 'outside', title: [1018, 194, 'Order system'], lines: [[1018, 218, 'system of record', 11.5]] },
  { x: 1000, y: 330, w: 180, h: 84, rx: 12, kind: 'outside', title: [1018, 364, 'Telegram'], lines: [[1018, 388, 'outbound only', 11.5]] },
  { x: 1000, y: 470, w: 180, h: 84, rx: 42, kind: 'outside', title: [1090, 518, 'Customer', 'middle'], lines: [] },
  { x: 720, y: 470, w: 180, h: 84, rx: 12, kind: 'outside', title: [738, 504, 'Signed web link'], lines: [[738, 528, 'literal YES or NO', 11.5]] },
];

/** Node styling per kind, from the prototype's rect attributes. */
export const NODE_STYLE = {
  outside: { fill: '#111A2B', stroke: '#76819A', width: null, dash: null },
  authority: { fill: '#1B2644', stroke: '#8390F2', width: 2, dash: null },
  understanding: { fill: '#0B1221', stroke: '#AEB6C8', width: 1.5, dash: '6 5' },
};

/** Edge styling, lit vs dim, from the prototype. */
export const EDGE_STYLE = {
  lit: { stroke: '#8390F2', width: 2.25, marker: 'url(#aL)' },
  dim: { stroke: '#3A4666', width: 1.25, marker: 'url(#aD)' },
};
