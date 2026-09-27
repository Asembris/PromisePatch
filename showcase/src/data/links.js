// Every outbound href on the page. tools/verify-links.mjs refuses any <a href>
// that is neither an in-page anchor nor listed here, and checks that every
// `blob/main/<path>` target exists in the working tree. Deferred items have no
// URL and are never rendered as links.

export const REPO = 'https://github.com/Asembris/PromisePatch';
export const DOCS = `${REPO}/blob/main/docs/`;
export const LIVE_APP = 'https://184.194.40.87.sslip.io';
export const PAGES_URL = 'https://asembris.github.io/PromisePatch/';

/** @param {string} file a path under docs/ */
export const doc = (file) => DOCS + file;

export const LINKS = {
  liveApp: LIVE_APP,
  repo: REPO,
  honestLimitations: `${REPO}#honest-limitations`,
  ciRun: `${REPO}/actions/runs/36310794944`,
  caseDefinition: doc('seeded-demo-case.md'),
  r3Record: doc('g8-rehearsal-r3.md'),
  demoFunnel: doc('g8-demo-funnel.md'),
  r1: doc('g8-rehearsal-r1.md'),
  r2: doc('g8-rehearsal-r2.md'),
  r3: doc('g8-rehearsal-r3.md'),
  r4: doc('g8-rehearsal-r4.md'),
  r5: doc('g8-rehearsal-r5.md'),
  firstScoredRun: doc('effect-set-first-scored-run.md'),
  releaseCondition: doc('g8-effect-set-release-condition.md'),
  voice: doc('g7-ten-turn-voice-measurement.md'),
  mcpTransport: doc('p5.1-mcp-transport-spine.md'),
  g8Closeout: doc('g8-closeout.md'),
  customerChannel: doc('deployed-customer-channel.md'),
  claimsAudit: doc('claims-audit.md'),
  contractRunner: doc('g8-demo-contract-runner.md'),
};

/** Non-navigation URLs the page names (canonical, social preview). */
export const META_URLS = [PAGES_URL, `${PAGES_URL}assets/og-preview-1200x630.png`];

/** Deferred: shown, if at all, as aria-disabled placeholders with no href. */
export const DEFERRED = {
  demoVideo: { label: 'Demo video · deferred', url: null },
  watchDemo: { label: 'Watch demo · deferred', url: null },
  devpost: { label: 'Devpost', url: null, shown: false },
};

export const ALLOWED_URLS = new Set([...Object.values(LINKS), ...META_URLS]);
