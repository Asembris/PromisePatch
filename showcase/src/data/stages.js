// STAGES, verbatim from the approved prototype. Index 6 (Settled) is the
// default and the no-JS state.

export const STAGES = [
  { name: 'Report', note: 'A worker reports: “today’s raspberry delivery didn’t arrive.”' },
  { name: 'Clarify', note: 'One clarifying question. “Just raspberries — the strawberries came.”' },
  { name: 'Partition', note: 'PLANNED · the engine partitions the six orders 1 / 1 / 2 + 2.' },
  { name: 'Worker confirms', note: 'CONFIRMED · a worker approves the plan that was read out, in a signed-in session.' },
  { name: 'Customer answers', note: 'One Telegram message. The customer answers YES on the signed link.' },
  { name: 'Revalidate', note: 'Ten checks against a fresh snapshot. All ten pass: PROCEED.' },
  { name: 'Settled', note: 'RESOLVED · the order system’s own store holds both amendments.' },
];

export const SETTLED = STAGES.length - 1;

/** Play case timing (MOTION_SPEC): one stage per 1150 ms; 400 ms under reduced motion. */
export const PLAY_STEP_MS = 1150;
export const PLAY_STEP_REDUCED_MS = 400;
