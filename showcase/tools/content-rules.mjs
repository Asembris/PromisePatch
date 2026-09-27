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
//    native, no refusal is claimed live, the illustration is labelled;
//  - forbidden phrases, case-insensitive, unless inside an explicit negation;
//  - deferred items carry aria-disabled and no href; Devpost is absent.

import { FACTS, BOUNDARIES } from '../src/data/facts.js';
import { GATE_MODES } from '../src/data/checks.js';
import { renderGate } from '../src/render/gate.js';

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

  // A refusal (or refusal state) and "live"/"deployment" in one sentence needs a negation.
  for (const sentence of corpus.split(/(?<=[.;!?])\s+/)) {
    if (/\b(?:refus\w*|STALE|EXPIRED|UNAUTHORIZED|NOOP)\b/i.test(sentence)
      && /\b(?:live|deploy\w*)\b/i.test(sentence)
      && !/\b(?:no|none|not|never)\b|illustrat/i.test(sentence)) {
      fail(`refusal claimed live or on the deployment: "${sentence.slice(0, 160)}"`);
    }
  }

  // The illustration: labelled in the data and in the rendered gate.
  const hypo = renderGate({ mode: 'hypo' });
  if (GATE_MODES.hypo.header !== ILLUSTRATION || !hypo.includes(ILLUSTRATION)) {
    fail(`the illustrative gate must be headed "${ILLUSTRATION}"`);
  }
  if (!/proved by tests only/.test(GATE_MODES.hypo.note) || !/none was exercised live/.test(GATE_MODES.hypo.note)) {
    fail('the illustrative gate must carry the tests-only, not-live note');
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
  if (!/No refusal path has been exercised live/.test(page)) fail('the limitations panel must say no refusal path was exercised live');

  // ---------- forbidden phrases ----------
  for (const phrase of FORBIDDEN) {
    const re = new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    for (const m of corpus.matchAll(re)) {
      const before = corpus.slice(Math.max(0, m.index - 16), m.index);
      if (!NEGATION.test(before)) fail(`forbidden phrase "${m[0]}" (…${before}${m[0]}…)`);
    }
  }

  // ---------- deferred items ----------
  for (const label of ['Demo video · deferred', 'Watch demo · deferred']) {
    // The element whose own text is the label (after an optional decorative glyph).
    const tag = html.match(new RegExp(`<([a-z]+)\\b([^>]*)>\\s*(?:<span aria-hidden="true">[^<]*</span>)?\\s*${label}`, 'i'));
    if (!tag) fail(`deferred placeholder "${label}" not found`);
    else if (tag[1].toLowerCase() === 'a' || /\bhref\s*=/.test(tag[2]) || !/aria-disabled="true"/.test(tag[2])) {
      fail(`deferred placeholder "${label}" must be aria-disabled with no href`);
    }
  }
  if (/devpost/i.test(html)) fail('Devpost is deferred and must not appear');

  return failures;
}
