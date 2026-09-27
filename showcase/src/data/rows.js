// ROWS, verbatim from the approved prototype: for each order, one
// [cell kind, text] pair per stage.

export const ORDER_IDS = ['A', 'B', 'C', 'D', 'E', 'F'];

export const DEFAULT_ORDER = 'B';

export const ROWS = {
  A: [['i', 'accepted'], ['r', 'has raspberry'], ['auto', '● AUTO'], ['done', '✓ amended v1→v2'], ['done', '✓ recovered'], ['done', '✓ recovered'], ['done', '✓ RECOVERED']],
  B: [['i', 'accepted'], ['r', 'has raspberry'], ['ask', '◆ ASK'], ['wait', '◆ 1 message sent'], ['ask', '◆ YES'], ['ask', '◆ 10/10 PROCEED'], ['done', '✓ RECOVERED']],
  C: [['i', 'accepted'], ['r', 'has raspberry'], ['blk', '■ BLOCKED'], ['blk', '■ owner · held'], ['blk', '■ owner · held'], ['blk', '■ owner · held'], ['blk', '■ ESCALATED']],
  D: [['i', 'accepted'], ['r', 'has raspberry'], ['blk', '■ BLOCKED'], ['blk', '■ owner · held'], ['blk', '■ owner · held'], ['blk', '■ owner · held'], ['blk', '■ ESCALATED']],
  E: [['i', 'accepted'], ['un', 'no raspberry'], ['un', '○ UNAFFECTED'], ['un', '○ 0 effects'], ['un', '○ 0 effects'], ['un', '○ 0 effects'], ['un', '○ UNTOUCHED']],
  F: [['i', 'accepted'], ['un', 'no raspberry'], ['un', '○ UNAFFECTED'], ['un', '○ 0 effects'], ['un', '○ 0 effects'], ['un', '○ 0 effects'], ['un', '○ UNTOUCHED']],
};
