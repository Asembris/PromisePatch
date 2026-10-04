// The content rules, in one place. tools/verify-content.mjs runs them over the
// built no-JS page (plus every runtime string), and the Playwright suite runs
// the same rules over the live, JavaScript-rendered DOM after each interaction.
// Pure: no file system, no process; returns a list of failures.
//
//  - every frozen fact in src/data/facts.js appears byte-exact, with its
//    caveats nearby;
//  - 11/16 and 16/16 may each appear wherever they are labelled as their own
//    result, but nothing may join them as a progression: no arrow between the
//    two scores, no "improved", "now", "from … to", before/after framing, and
//    no "benchmark scored 16/16". A link arrow ("First scored run →") is not a
//    progression and is allowed;
//  - product boundaries: Telegram is outbound only, the signed web link is the
//    consent entry, the order system is labelled simulated, Alexa+ is not
//    native, a live refusal is claimed only as the one STALE at check 2 on
//    740a062838e0, the illustration is labelled;
//  - claim scope: consent is a literal YES or NO (no option code); a plan
//    approval comes from a signed-in session or the operator console; MCP
//    intake is a trusted reporting channel; revalidation guards the commit,
//    not external execution; no unqualified "exactly once"; the recorded R3
//    press was the owner's; the illustration is never a recorded refusal;
//    STALE is not one universal re-plan; timeline intervals and deadline
//    dates read true (checkClaims, checkTimeline);
//  - forbidden phrases, case-insensitive, unless inside an explicit negation;
//  - the demo video and Devpost are links to their listed URLs, and no
//    deferred placeholder is left on the page.

import { FACTS, BOUNDARIES } from '../src/data/facts.js';
import { GATE_MODES } from '../src/data/checks.js';
import { renderGate } from '../src/render/gate.js';
import { LINKS } from '../src/data/links.js';

const ENTITIES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&nbsp;': ' ' };

/** Visible text of an HTML string: inline tags vanish, block tags break words. */
export function textOf(html) {
  return html
    .replace(/<(script|style|head)\b[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<\/?(span|strong|em|code|a|b|i|abbr)\b[^>]*>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&(amp|lt|gt|quot|#39|nbsp);/g, (m) => ENTITIES[m])
    .replace(/\s+/g, ' ')
    .trim();
}

const NEAR = 1200;
const LABEL_NEAR = 220;
const ILLUSTRATION = 'ILLUSTRATION · NOT A RECORDED RUN';

function occurrences(text, needle) {
  const out = [];
  for (let i = text.indexOf(needle); i >= 0; i = text.indexOf(needle, i + 1)) out.push(i);
  return out;
}

const ARROW = '(?:→|->|⟶|➔|➜|⇒|=>|—>|\\bto\\b)';
const PROGRESSION = [
  [new RegExp(`11/16\\s*${ARROW}\\s*16/16`, 'i'), 'an arrow or "to" joins 11/16 and 16/16'],
  [/from\s+11\/16\s+to\s+16\/16/i, '"from 11/16 to 16/16"'],
  [/\bimprov\w*\b[^.]{0,60}\b1[16]\/16/i, '"improved" next to a score'],
  [/\b1[16]\/16\b[^.]{0,60}\bimprov\w*/i, 'a score next to "improved"'],
  [/\bnow\s+(?:at\s+|scores?\s+|reads?\s+)?16\/16/i, '"now 16/16"'],
  [/\b(?:went|goes|go|rose|rises|jumped|climbed|moved|increased)\s+(?:up\s+)?to\s+16\/16/i, '"went up to 16/16"'],
  [/\bbenchmark\s+(?:now\s+)?(?:scored|scores|reached|reaches|achieved|achieves|hit|hits)\s+16\/16/i, '"benchmark scored 16/16"'],
  [/\b(?:became|becomes)\s+16\/16/i, '"became 16/16"'],
  [/\bbefore\b[^.]{0,60}11\/16[\s\S]{0,120}?\bafter\b[^.]{0,60}16\/16/i, 'before/after framing of 11/16 and 16/16'],
  [/11\/16[^.]{0,40}\bbefore\b[\s\S]{0,120}?16\/16[^.]{0,40}\bafter\b/i, 'before/after framing of 11/16 and 16/16'],
];

const TELEGRAM_INBOUND = [
  /\b(?:reply|replies|replied|answer|answers|answered|respond|responds|YES|approve|approves|approved|consent)\s+(?:on|in|via|through|over|by)\s+(?:the\s+)?Telegram\b/i,
  /\bTelegram\s+(?:reply|replies|inbound)\b(?!\s+is\s+deliberately\s+not\s+built)/i,
  /\bconsent\s+(?:via|through|over|by|on|in)\s+(?:the\s+)?Telegram\b/i,
];

const FORBIDDEN = [
  'production-ready',
  'production ready',
  'production proven',
  'production-proven',
  'formally safe',
  'guaranteed safe',
  'enterprise proven',
  'enterprise-proven',
  'zero risk',
  '100% reliable',
  'benchmark improved',
  'native Alexa+ integration',
];
const NEGATION = /\b(?:not|no|never|isn't|is not)\s+(?:a\s+|an\s+)?$/i;

const sentencesOf = (text) => text.split(/(?<=[.;!?])\s+/);

// ---------- claim scope: say exactly what the implementation does ----------
// Each rule is [pattern, why]; a sentence matching `pattern` fails. They are
// semantic shapes, not one sentence each, so a reworded overclaim still fails.
const SCOPED = [
  // Consent: domain/consent.py accepts a normalized YES or NO and nothing else.
  [(s) => /\boption[\s-]+codes?\b/i.test(s) && !/\b(?:no|not|never|without)\b[^.]{0,30}\boption[\s-]+codes?\b/i.test(s),
    'customer consent claimed to accept an option code (the parser reads a literal YES or NO only)'],
  // Plan approval: ApprovalChannel is BROWSER_SESSION or OPERATOR_CONSOLE.
  [(s) => /\bplan[- ]approvals?\b|\bapproves? (?:the|a) plan\b|\bapproval a (?:human|person)\b/i.test(s)
    && /\b(?:signed-in|session)\b/i.test(s)
    && (/\bonly\b[^.]{0,20}\b(?:signed-in|session|place)\b|\bthe only place\b|\b(?:solely|exclusively|sole)\b/i.test(s) || !/\bconsole\b|\bone of (?:two|the)\b/i.test(s)),
    'a plan approval described as coming only from a signed-in session (the operator console is the other channel)'],
  // Delivery: at-least-once under a stable key; Telegram has no idempotency key.
  [(s) => /\bexactly[- ]once\b/i.test(s), '"exactly once" (scope it to a recorded result or to idempotent internal application)'],
  [(s) => /\b(?:no|never|zero|without)\b[^.]{0,20}\bduplicate\s+(?:messages?|deliver\w*|sends?)\b/i.test(s)
    || /\b(?:guarantee\w*|always)\b[^.]{0,40}\bdeliver\w*\s+once\b/i.test(s),
    'duplicate messages ruled out (Telegram exposes no idempotency key)'],
  // MCP: a trusted reporting channel under the configured worker, not a no-authority surface.
  [(s) => /\b(?:MCP|agents?|AI|callers?)\b[^.]{0,60}\b(?:has|have|holds?|carr(?:y|ies))\s+no\s+authority\b/i.test(s)
    || /\bno authority\b[^.]{0,40}\b(?:MCP|agents?|AI)\b/i.test(s),
    'MCP or AI callers claimed to hold no authority at all (MCP intake is a trusted reporting channel)'],
  [(s) => /\b(?:model|AI|MCP|agents?|LLM)\b[^.]{0,50}\b(?:cannot|can't|can never|never|may not)\s+(?:\w+\s+){0,2}attest\w*/i.test(s)
    || /\b(?:model|AI|MCP|agents?|LLM)\b[^.]{0,40}\bno\s+(?:\w+\s+)?attestation\b/i.test(s)
    || /\b(?:cannot|can't|CANNOT)\b[^.]{0,80}\battest\w*\s+(?:a\s+|the\s+)?physical\b/i.test(s),
    'model or MCP claimed categorically unable to attest (a report it reads is recorded under the reporting worker)'],
  // Revalidation guards the commit; after it only the production start is re-judged (ADR-0024, ADR-0026).
  [(s) => /\batomic\w*\b/i.test(s) && /\brevalidat\w*|\bten checks\b|\bfresh snapshot\b/i.test(s),
    'revalidation described as atomic (the ten checks guard the commit, not the order system\'s acceptance)'],
  [(s) => /\brevalidat\w*|\bten checks\b|\bfresh snapshot\b/i.test(s)
    && /\b(?:immediately|right|just)\s+before\b|\bbefore\s+(?:(?:it|that change|the change)\s+(?:runs|executes|is sent)|acting|executing|execution|(?:each|every|the)\s+(?:dispatch|send|delivery)|the order system (?:is amended|accepts)|external)\b|\b(?:at|on)\s+(?:each|every)\s+(?:dispatch|send|delivery)\b/i.test(s),
    'revalidation placed at external execution (the ten checks guard the commit; after it only the production start is judged again)'],
  // R3: the owner pressed APPROVE as the demo customer.
  [(s) => /\bpress(?:es|ed)?\s+APPROVE\b/i.test(s) && !/\bowner\b/i.test(s),
    'the recorded APPROVE press attributed to a customer (in R3 the owner acted as the demo customer)'],
  // No recorded run showed the world moving while an answer waited.
  [(s) => /\bworld\s+(?:keeps|kept)\s+moving\b|\bworld\s+(?:moved|changed)\s+while\b/i.test(s),
    'the recorded case described as a world that moved while it waited'],
  // STALE is not one universal re-plan: EXPIRED escalates, apply-time staleness escalates.
  [(s) => /\b(?:every|any|all|always)\b[^.]{0,60}\bSTALE\b[^.]{0,60}\bre-?plan/i.test(s)
    || /\bSTALE\b[^.]{0,40}\balways\b[^.]{0,30}\bre-?plan/i.test(s),
    'every stale finding claimed to re-plan (some escalate to the owner instead)'],
  // STALE was refused live once, at check 2, on 740a062838e0 (docs/revalidation-proof.md):
  // it is no longer tests-only. The earlier local reproduction
  // (docs/evidence-hardening-stale-refusal-2026-09-28.md) is never a live one.
  [(s) => /\bSTALE\b[^.;]{0,80}\bproved (?:only )?by (?:their )?tests\b/i.test(s) && !/\blive\b|\bcheck 2\b/i.test(s),
    'STALE listed as proved by tests only (it was refused live once, at check 2, on 740a062838e0)'],
  [(s) => /\bSTALE\b[^.;]{0,60}\breproduced\b/i.test(s) && /\blive\b|\bdeploy\w*|\bproduction\b/i.test(s)
    && !/\b(?:not|no|none|never)\b/i.test(s),
    'the local STALE reproduction presented as live or on the deployment'],
  // The illustration is never a recorded or rehearsed refusal.
  [(s) => /\b(?:STALE|refus\w*)\b/i.test(s) && /\bR[1-5]\b|\brehears\w*|\brecorded\b/i.test(s)
    && !/\b(?:no|none|not|never)\b|illustrat/i.test(s),
    'a refusal presented as recorded in a rehearsal'],
];

/**
 * The claim-scope rules alone, over plain text (the page, runtime strings, or
 * the root README). Pure. @param {string} text @returns {string[]} failures
 */
export function checkClaims(text) {
  const failures = [];
  for (const sentence of sentencesOf(text)) {
    for (const [test, why] of SCOPED) {
      if (test(sentence)) failures.push(`claim scope: ${why}: "${sentence.slice(0, 180)}"`);
    }
  }
  // The general STALE rule must not stand alone: where the page says a stale
  // change is re-planned outside the illustration, the owner path is said too.
  for (const m of text.matchAll(/\bSTALE\b[^.]{0,80}\bre-?plann\w*/g)) {
    const before = text.slice(Math.max(0, m.index - NEAR), m.index);
    const after = text.slice(m.index, m.index + 400);
    if (!before.includes(ILLUSTRATION) && !/illustrat/i.test(before.slice(-300)) && !/\bowner\b|\bescalat\w*/i.test(after)) {
      failures.push(`claim scope: "${m[0]}" stated without the owner path (EXPIRED and apply-time staleness escalate)`);
    }
  }
  // A time comparison that crosses midnight carries both dates.
  for (const m of text.matchAll(/(\b\d{1,2} [A-Z][a-z]{2} |\b\d{4}-\d\d-\d\d[T ])?(\d\d):(\d\d):(\d\d)Z?\s*≤\s*(\b\d{1,2} [A-Z][a-z]{2} |\b\d{4}-\d\d-\d\d[T ])?(\d\d):(\d\d):(\d\d)Z?/g)) {
    const secs = (h, mi, s) => Number(h) * 3600 + Number(mi) * 60 + Number(s);
    if (secs(m[2], m[3], m[4]) > secs(m[6], m[7], m[8]) && !(m[1] && m[5])) {
      failures.push(`claim scope: "${m[0]}" crosses midnight without both dates, so it reads as false`);
    }
  }
  return failures;
}

const TIME = /^(\d\d):(\d\d):(\d\d)$/;
const toSeconds = (t) => { const [, h, m, s] = t.match(TIME); return Number(h) * 3600 + Number(m) * 60 + Number(s); };

/**
 * The R3 timeline: every "N min S s" in a row is measured back from that
 * row's own timestamp to another row's (within a second of display rounding),
 * so a row can never pair its time with some other interval.
 * @param {string} html @returns {string[]} failures
 */
export function checkTimeline(html) {
  const failures = [];
  const list = html.match(/<ol\b[^>]*class="(?:[^"]*\s)?timeline(?:\s[^"]*)?"[^>]*>([\s\S]*?)<\/ol>/);
  if (!list) return ['the R3 timeline is missing'];
  const rows = [...list[1].matchAll(/<li\b[^>]*>([\s\S]*?)<\/li>/g)].map(([, li]) => {
    const time = (li.match(/timeline__time">([^<]+)</) || [])[1];
    return { time, text: textOf(li) };
  });
  const times = rows.map((r) => r.time).filter((t) => t && TIME.test(t)).map(toSeconds);
  for (const row of rows) {
    if (!row.time || !TIME.test(row.time)) { failures.push(`timeline row without a time: "${row.text}"`); continue; }
    for (const m of row.text.matchAll(/(\d+)\s*min\s*(\d+)\s*s\b/g)) {
      const from = toSeconds(row.time) - (Number(m[1]) * 60 + Number(m[2]));
      if (!times.some((t) => Math.abs(t - from) <= 1)) {
        failures.push(`timeline row ${row.time}: "${m[0]}" does not reach back to any other row's time`);
      }
    }
  }
  return failures;
}

/**
 * @param {{ html: string, extra?: string[], state?: 'default' | 'live' }} input
 *   `html` is the page (built file or live `outerHTML`); `extra` are strings a
 *   reader can meet elsewhere (the runtime strings); `state` is `default` for
 *   the settled, no-JS page and `live` for any state reached by interaction,
 *   where the default-only rules (R3 shown, illustration absent) do not apply.
 * @returns {string[]} failures
 */
export function checkContent({ html, extra = [], state = 'default' }) {
  const failures = [];
  const fail = (msg) => failures.push(msg);
  const page = textOf(html);
  // Everything a reader can meet: the page plus every extra string.
  const corpus = [page, ...extra].join(' \n ');

  // ---------- facts and caveats ----------
  for (const [key, fact] of Object.entries(FACTS)) {
    const at = occurrences(page, fact.value);
    if (!at.length) {
      fail(`fact ${key}: "${fact.value}" does not appear on the page`);
      continue;
    }
    if (fact.caveat) {
      const ok = at.some((i) => {
        const window = page.slice(Math.max(0, i - NEAR), i + fact.value.length + NEAR);
        return fact.caveat.every((c) => window.includes(c));
      });
      if (!ok) fail(`fact ${key}: no occurrence of "${fact.value}" has all its caveats nearby: ${fact.caveat.join(' | ')}`);
    }
  }
  for (const [key, b] of Object.entries(BOUNDARIES)) {
    if (!page.includes(b.value)) fail(`boundary ${key}: "${b.value}" is not on the page`);
  }

  // ---------- 11/16 and 16/16: two results, never a progression ----------
  for (const [re, why] of PROGRESSION) {
    const m = corpus.match(re);
    if (m) fail(`progression: ${why}: "${m[0]}"`);
  }
  for (const [score, label, name] of [
    ['11/16', /permanent headline|immutable headline|\bv1\b/i, 'the v1 headline'],
    ['16/16', /separate release condition|\bv2\b/i, 'the separate v2 release condition'],
  ]) {
    for (const i of occurrences(page, score)) {
      const window = page.slice(Math.max(0, i - LABEL_NEAR), i + score.length + LABEL_NEAR);
      if (!label.test(window)) fail(`${score} at offset ${i} is not labelled as ${name}`);
    }
  }
  if (!/PERMANENT HEADLINE/.test(page) || !/SEPARATE RELEASE CONDITION/.test(page)) {
    fail('the effect-set badges PERMANENT HEADLINE and SEPARATE RELEASE CONDITION must both be present');
  }

  // ---------- product boundaries ----------
  for (const re of TELEGRAM_INBOUND) {
    const m = corpus.match(re);
    if (m) fail(`Telegram inbound consent implied: "${m[0]}"`);
  }
  if (!/Telegram inbound is deliberately not built/.test(page)) fail('the page must say Telegram inbound is deliberately not built');
  if (!/signed web link/.test(page)) fail('the signed web link must be named as the consent entry');
  if (!/labelled fixtures and a simulator/.test(page)) fail('the order system must be labelled as a simulator');
  if (!/not a native Alexa\+ integration/i.test(page)) fail('"not a native Alexa+ integration" must be present');
  if (!/Alexa\+-style experience is simulated/.test(page)) fail('the Alexa+-style experience must be labelled simulated');

  // A refusal (or refusal state) and "live"/"deployment" in one sentence needs a
  // negation, unless it is the one live refusal, scoped as such: STALE (or "one
  // refusal kind") with "once", "check 2" or the release, and no other state.
  for (const sentence of corpus.split(/(?<=[.;!?])\s+/)) {
    if (/\b(?:refus\w*|STALE|EXPIRED|UNAUTHORIZED|NOOP)\b/i.test(sentence)
      && /\b(?:live|deploy\w*)\b/i.test(sentence)
      && !/\b(?:no|none|not|never)\b|illustrat/i.test(sentence)
      && !(/\bstale\b|\bone refusal kind\b/i.test(sentence) && /\bonce\b|\bcheck 2\b|740a062838e0/i.test(sentence)
        && !/\b(?:EXPIRED|UNAUTHORIZED|NOOP)\b/.test(sentence))) {
      fail(`refusal claimed live or on the deployment: "${sentence.slice(0, 160)}"`);
    }
  }

  // The illustration: labelled in the data and in the rendered gate.
  const hypo = renderGate({ mode: 'hypo' });
  if (GATE_MODES.hypo.header !== ILLUSTRATION || !hypo.includes(ILLUSTRATION)) {
    fail(`the illustrative gate must be headed "${ILLUSTRATION}"`);
  }
  if (!/proved by tests only/.test(GATE_MODES.hypo.note) || !/illustrative, not a recorded run/.test(GATE_MODES.hypo.note)
    || !/one live STALE[^.;]*check 2[^.;]*not this check/.test(GATE_MODES.hypo.note)) {
    fail('the illustrative gate must carry the not-a-recorded-run, live-STALE-at-check-2, tests-only note');
  }
  // Wherever the illustrated refusal shows, its label and note show with it.
  if (/Refused as STALE and re-planned|\bno longer available\b/.test(page)
    && (!page.includes(ILLUSTRATION) || !page.includes(GATE_MODES.hypo.note))) {
    fail('the illustrated STALE outcome is shown without its label and tests-only note');
  }
  if (state === 'default') {
    if (page.includes(ILLUSTRATION) || /STALE and re-planned\. Nothing/.test(page)) {
      fail('the no-JS page must show the recorded R3 run, not the illustration');
    }
    if (!page.includes('AUDIT 503–512 · SNAPSHOT 20:31:01.207Z') || !/\bPROCEED\b/.test(page)) {
      fail('the no-JS gate must show R3 at 10/10 PROCEED');
    }
  }
  if (!/One refusal kind has been exercised live, once\./.test(page)) fail('the limitations panel must say one refusal kind was exercised live, once');

  // ---------- claim scope ----------
  for (const f of checkClaims(corpus)) fail(f);
  for (const f of checkTimeline(html)) fail(f);
  for (const [re, what] of [
    [/\boperator console\b/, 'the operator console as a plan-approval channel'],
    [/\bMCP intake is a trusted reporting channel\b/, 'MCP intake as a trusted reporting channel'],
    [/\bno idempotency key\b/, 'that Telegram exposes no idempotency key'],
    [/\bowner, as the demo customer, presses APPROVE\b/, 'the owner, as the demo customer, pressing APPROVE in R3'],
    [/\bfirst dispatch\b/, 'where revalidation stops: only the production start is judged again at the first dispatch'],
    [/\bSTALE\b[^.;]*\bthrough check 2, on 740a062838e0\b/, 'that the one live STALE went through check 2, on 740a062838e0'],
  ]) if (!re.test(page)) fail(`the page must state ${what}`);

  // ---------- forbidden phrases ----------
  for (const phrase of FORBIDDEN) {
    const re = new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    for (const m of corpus.matchAll(re)) {
      const before = corpus.slice(Math.max(0, m.index - 16), m.index);
      if (!NEGATION.test(before)) fail(`forbidden phrase "${m[0]}" (…${before}${m[0]}…)`);
    }
  }

  // ---------- submission links ----------
  const hrefs = new Set([...html.matchAll(/<a\b[^>]*\shref="([^"]*)"/gi)].map((m) => m[1]));
  for (const [name, url] of [['demo video', LINKS.demoVideo], ['Devpost', LINKS.devpost]]) {
    if (!hrefs.has(url)) fail(`the ${name} link to ${url} is missing`);
  }
  if (/·\s*deferred\b/i.test(html)) fail('a deferred placeholder is still on the page');

  return failures;
}
