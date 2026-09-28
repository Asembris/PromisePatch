// PROOFS, verbatim from the approved prototype: [claim, what it proves, file,
// href?]. Without an href, the file is a document under docs/ on main.
// Claim-hardening corrections (CONTENT_SOURCES.md) depart from the prototype
// only where the repository record required it.

export const PROOFS = [
  ['Release proof, closed', '22 of 22 G8 rows closed, the two SHAs reconciled, and the feature freeze.', 'g8-closeout.md'],
  ['Exact release SHA passes CI', '13 of 13 jobs on 56c3023, the whole-stack browser job included.', 'actions/runs/36310794944', 'https://github.com/Asembris/PromisePatch/actions/runs/36310794944'],
  ['Restart-safe on the deployment', 'R1–R5: five worker restarts at four points on 4529a802e34e, each PASS, every effect recorded once and delivered on attempt 1.', 'g8-rehearsal-r1.md … r5.md', 'https://github.com/Asembris/PromisePatch/blob/main/docs/g8-rehearsal-r1.md'],
  ['Untouched means untouched', 'The funnel 6 → 1/1/2 + 2, and 0/2 untouched orders affected, in all five rehearsals.', 'g8-demo-funnel.md'],
  ['The storyboard is executable', '49 assertions through the intent API and the signed link, with no direct consent insert.', 'g8-demo-contract-runner.md'],
  ['The immutable headline', '11/16 against frozen v1, with every diff published.', 'effect-set-first-scored-run.md'],
  ['The separate release condition', '16/16 against the v2 label correction, and the fix SHA for each v1 failure.', 'g8-effect-set-release-condition.md'],
  ['The voice number', '9/10 in run 2, with void run 1 and every timing published.', 'g7-ten-turn-voice-measurement.md'],
  ['MCP transport', 'Streamable HTTP, 2025-11-25, bearer and Origin/Host refusals, tested with the official SDK.', 'p5.1-mcp-transport-spine.md'],
  ['Real customer loop', 'One Telegram delivery and a web YES, revalidated, then EXT-B amended once.', 'deployed-customer-channel.md'],
];
