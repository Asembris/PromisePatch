// The R1–R5 table, verbatim from the approved prototype
// (docs/g8-demo-funnel.md §2), as taken again on the current release
// (docs/bridge-release.md §R1–R5 on 740a062838e0).

export const REHEARSALS_CAPTION = '5/5 REHEARSALS ON 740a062838e0';

/** [run, link key in LINKS, where the worker was restarted, untouched, verdict] */
export const REHEARSALS = [
  ['R1', 'r1', 'waiting for consent', '0/2', '✓ PASS'],
  ['R2', 'r2', 'across the plan confirmation', '0/2', '✓ PASS'],
  ['R3', 'r3', 'across the customer’s answer', '0/2', '✓ PASS'],
  ['R4', 'r4', 'after the case resolved', '0/2', '✓ PASS'],
  ['R5', 'r5', 'waiting for consent, again', '0/2', '✓ PASS'],
];
