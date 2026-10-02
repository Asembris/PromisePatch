// The frozen facts the page states, each typed once, each with the committed
// repository record it comes from. Values are DO_NOT_CHANGE.md's exact forms.
// If a later repository document changes one, the page follows the repository
// and `source` changes with it; frozen evidence is never edited to match.
//
// `{{fact.<key>}}` in index.html is replaced with `value` at build time, and
// tools/verify-content.mjs checks every value appears in the built page with
// its `caveat` text nearby.

/** @typedef {{ value: string, source: string[], caveat?: string[] }} Fact */

/** @type {Record<string, Fact>} */
export const FACTS = {
  releaseSha: {
    value: '740a062838e0ea2620499abed27d653c42fc05f7',
    source: ['docs/bridge-release.md', 'README.md §The release that runs now'],
    caveat: ['Earlier releases are historical'],
  },
  releaseShort: {
    value: '740a062',
    source: ['docs/bridge-release.md §Release and CI', 'README.md §License'],
  },
  deployedSha: {
    value: '740a062838e0',
    source: ['docs/bridge-release.md §Deployment', 'README.md §The release that runs now'],
    caveat: ['Reported by'],
  },
  v1Headline: {
    value: '11/16',
    source: ['docs/effect-set-first-scored-run.md', 'docs/g8-effect-set-release-condition.md §1', 'README.md §Measured evidence', 'docs/effect-set-manifest.md'],
    caveat: ['PERMANENT HEADLINE', 'hand-labelled before the runner existed', 'Five failed', 'never replaced'],
  },
  v2Condition: {
    value: '16/16',
    source: ['docs/g8-effect-set-release-condition.md §5–7', 'docs/bridge-release.md §Release checks', 'docs/adr/0017-a-blocked-promise-does-not-hold-a-started-task.md'],
    caveat: ['SEPARATE RELEASE CONDITION', 'separately versioned label correction', 'The original benchmark did not become 16/16.'],
  },
  effectSetScope: {
    value: 'developer-authored, finite and public, not an independent benchmark',
    source: ['README.md §Measured evidence'],
  },
  rehearsals: {
    value: '5/5',
    source: ['docs/bridge-release.md §R1–R5', 'docs/g8-demo-funnel.md §2'],
    caveat: ['not a reliability rate'],
  },
  untouched: {
    value: '0/2',
    source: ['docs/g8-demo-funnel.md', 'docs/bridge-release.md §R1–R5', 'README.md §Measured results'],
    caveat: ['each of five', 'One fixture measured five times'],
  },
  perRehearsal: {
    value: '2 amendments · 1 customer message · 2 task holds · 3 outbox rows',
    source: ['docs/g8-demo-funnel.md (effect counts)'],
  },
  funnel: {
    value: '6 promises → 1 auto-recovered · 1 customer-approved · 2 owner-escalated · 2 untouched',
    source: ['docs/g8-demo-funnel.md §1'],
  },
  voice: {
    value: '9/10',
    source: ['docs/g7-ten-turn-voice-measurement.md', 'README.md §Measured evidence', 'docs/claims-audit.md'],
    caveat: ['Run 1 (1/10) was voided', 'best-of-two', 'Local stack', 'Not a latency SLA'],
  },
  ci: {
    value: '13/13',
    source: ['docs/bridge-release.md §Release and CI', 'https://github.com/Asembris/PromisePatch/actions/runs/36925136266'],
    caveat: ['whole-stack browser job'],
  },
  ciRun: {
    value: '36925136266',
    source: ['docs/bridge-release.md §Release and CI'],
  },
  mcpRevision: {
    value: '2025-11-25',
    source: ['docs/p5.1-mcp-transport-spine.md', 'docs/alexa-mcp-confirm-proof.md', 'README.md §Alexa+, Bedrock and MCP'],
    caveat: ['not a native Alexa+ integration'],
  },
  freezeDate: {
    value: '2026-10-02',
    source: ['docs/bridge-release.md §Verdict', 'README.md §License'],
  },
};

/** Product boundaries the page must state; checked as phrases by verify-content. */
export const BOUNDARIES = {
  telegramOutbound: {
    value: 'Telegram outbound is live',
    source: ['docs/deployed-customer-channel.md', 'README.md §AWS deployment'],
  },
  signedLinkConsent: {
    value: 'customers answer through the signed web link',
    source: ['docs/customer-approval-link.md', 'docs/adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md'],
  },
  telegramInboundUnbuilt: {
    value: 'Telegram inbound is deliberately not built',
    source: ['docs/customer-message-transport.md', 'README.md §Honest limitations'],
  },
  alexaSimulated: {
    value: 'This is not a native Alexa+ integration.',
    source: ['README.md §Alexa+, Bedrock and MCP', 'docs/adr/0028-a-simulated-alexa-turn-is-a-case-scoped-mcp-client-on-the-server.md'],
  },
  orderSystemSimulated: {
    value: 'a simulated order system',
    source: ['README.md §Honest limitations', 'docs/order-system.md'],
  },
  oneLiveRefusal: {
    value: 'One refusal kind has been exercised live, once.',
    source: ['README.md §Honest limitations', 'docs/revalidation-proof.md'],
  },
};

/** Public SHAs the page offers to copy. Nothing else is ever copied. */
export const COPYABLE = {
  prod: FACTS.deployedSha.value,
  rel: FACTS.releaseSha.value,
};
