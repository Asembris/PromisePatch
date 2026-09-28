// CHECKS and the gate's two scenarios, verbatim from the approved prototype.
// Values are as `pp case-status` printed them in rehearsal R3
// (docs/g8-rehearsal-r3.md §9); the deadline carries both dates, as the
// record does, because it crosses midnight.
// Claim-hardening corrections (CONTENT_SOURCES.md) depart from the prototype
// only where the repository record required it.

export const CHECKS = [
  ['Waiting', 'The track and case are waiting.', 'WAITING'],
  ['Order', 'Order state and version unchanged.', 'ACCEPTED @ v1'],
  ['Pinned version', 'Pinned recipe version unchanged.', 'rv-raspberry-rose-2'],
  ['Constraints', 'Constraint snapshot unchanged.', 'ee9962aa… = ee9962aa…'],
  ['Substitute', 'The substitute is still available.', '3.200 ≥ 2.200'],
  ['Production task', 'Not started; its start is ahead.', 'SCHEDULED'],
  ['Deadline', 'Approval deadline not passed, judged at processing time.', '24 Sep 20:31:01Z ≤ 25 Sep 01:26:54Z'],
  ['Sender', 'The sender is the order’s approval channel.', 'masked'],
  ['Parser', 'The decision came from the literal parser.', 'LITERAL'],
  ['Decision', 'One unspent decision, bound to this plan.', '1 decision'],
];

/** One check per 120 ms, started when 35% of the gate is in view (MOTION_SPEC). */
export const CHECK_STEP_MS = 120;
export const GATE_THRESHOLD = 0.35;

/**
 * `live` is the recorded R3 run and the default. `hypo` is an illustration,
 * never a recorded run: the substitute check (index 4) fails.
 */
export const GATE_MODES = {
  live: {
    button: 'Deployed rehearsal R3',
    header: 'AUDIT 503–512 · SNAPSHOT 20:31:01.207Z',
    verdict: 'PROCEED',
    sub: 'EXT-B amended once, v1 → v2, under HUMAN_APPROVAL. Case RESOLVED at 20:31:03Z.',
    note: 'Values as pp case-status printed them in rehearsal R3, on the frozen deployment 4529a802e34e.',
    failIndex: -1,
  },
  hypo: {
    button: 'If the substitute had run out',
    header: 'ILLUSTRATION · NOT A RECORDED RUN',
    verdict: 'STALE',
    sub: 'Refused as STALE and re-planned. Nothing is written to the order system.',
    note: 'This scenario is illustrative, not a recorded run. STALE was reproduced locally on the frozen code, and EXPIRED, UNAUTHORIZED and NOOP are proved by tests only; none was exercised live.',
    failIndex: 4,
    failValue: 'no longer available',
  },
};

export const GATE_PENDING_SUB = 'Every check runs against the snapshot taken after the answer arrived.';
