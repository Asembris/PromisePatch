// PROOFS, verbatim from the approved prototype: [claim, what it proves, file,
// href?]. Without an href, the file is a document under docs/ on main.
// Claim-hardening corrections (CONTENT_SOURCES.md) depart from the prototype
// only where the repository record required it.

export const PROOFS = [
  ['The current release, revalidated', '740a062, image 740a062838e0: pr 13 of 13, the Alexa+ bridge verified live, v2 16/16, R1–R5 PASS, demo contract 47.', 'bridge-release.md'],
  ['Exact release SHA passes CI', '13 of 13 jobs on 740a062, the whole-stack browser job included.', 'actions/runs/36925136266', 'https://github.com/Asembris/PromisePatch/actions/runs/36925136266'],
  ['A stale yes is refused live, once', 'On 740a062838e0, a customer’s v1 yes was refused as STALE at check 2 after the order moved to v2, and no amendment reached that order; a control run applied.', 'revalidation-proof.md'],
  ['MCP spends, never creates, a human approval', 'On 740a062838e0, a browser approval, then “Yes, go ahead.” in the simulated Alexa+ panel, Bedrock CONFIRM and a real MCP confirm: still one approval, no customer consent created.', 'alexa-mcp-confirm-proof.md'],
  ['Restart-safe on the deployment', 'R1–R5: five worker restarts at four points on 740a062838e0, each PASS, every effect recorded once and delivered on attempt 1.', 'bridge-release.md', 'https://github.com/Asembris/PromisePatch/blob/main/docs/bridge-release.md#r1r5-on-740a062838e0'],
  ['Untouched means untouched', 'The funnel 6 → 1/1/2 + 2, and 0/2 untouched orders affected, in all five rehearsals.', 'g8-demo-funnel.md'],
  ['The storyboard is executable', '49 assertions through the intent API and the signed link, with no direct consent insert, or 47 when confirmed on the console.', 'g8-demo-contract-runner.md'],
  ['The immutable headline', '11/16 against frozen v1, with every diff published.', 'effect-set-first-scored-run.md'],
  ['The separate release condition', '16/16 against the v2 label correction, and the fix SHA for each v1 failure.', 'g8-effect-set-release-condition.md'],
  ['The voice number', '9/10 in run 2, with void run 1 and every timing published.', 'g7-ten-turn-voice-measurement.md'],
  ['MCP transport', 'Streamable HTTP, 2025-11-25, bearer and Origin/Host refusals, tested with the official SDK.', 'p5.1-mcp-transport-spine.md'],
  ['Real customer loop', 'One Telegram delivery and a web YES, revalidated, then EXT-B amended once.', 'deployed-customer-channel.md'],
  ['Earlier releases, historical', '283f63f2845f and 4529a802e34e, each with its own CI run and five rehearsals; the G8 freeze closed 22 of 22 rows.', 'g8-closeout.md'],
];
