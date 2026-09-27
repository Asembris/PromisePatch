// The revalidation gate: scenario toggle, ten checks, outcome. `n` is how many
// checks have run; 10 is the settled (and no-JS) state.

import { CHECKS, GATE_MODES, GATE_PENDING_SUB } from '../data/checks.js';
import { LINKS } from '../data/links.js';
import { attrs, esc } from './html.js';

export const TOTAL = CHECKS.length;

/** @param {number} i @param {'live' | 'hypo'} mode @param {number} n */
export function checkView(i, mode, n) {
  const m = GATE_MODES[mode];
  const [name, desc, value] = CHECKS[i];
  const ran = i < n;
  const fail = ran && i === m.failIndex;
  const state = !ran ? 'pending' : fail ? 'fail' : 'pass';
  return {
    name,
    desc,
    state,
    value: fail ? m.failValue : value,
    mark: !ran ? String(i + 1) : fail ? '✕' : '✓',
    spoken: state === 'pass' ? ' Passed.' : state === 'fail' ? ' Failed.' : ' Not yet run.',
  };
}

/** @param {'live' | 'hypo'} mode @param {number} n */
export function outcomeView(mode, n) {
  const m = GATE_MODES[mode];
  if (n < TOTAL) return { state: 'pending', verdict: `Checking ${n}/${TOTAL}`, sub: GATE_PENDING_SUB };
  return { state: mode === 'hypo' ? 'stale' : 'proceed', verdict: m.verdict, sub: m.sub };
}

/** @param {ReturnType<typeof checkView>} v */
const renderCheck = (v) =>
  `<li class="check is-${v.state}"><span class="check__mark" aria-hidden="true">${esc(v.mark)}</span>`
  + `<span class="check__text"><strong>${esc(v.name)}.</strong> <span>${esc(v.desc)}</span><span class="visually-hidden">${v.spoken}</span></span>`
  + `<code class="check__value">${esc(v.value)}</code></li>`;

/** @param {'live' | 'hypo'} mode @param {number} n */
export const renderChecks = (mode, n) => CHECKS.map((_, i) => renderCheck(checkView(i, mode, n))).join('');

/** Hidden until the enhancement script wires it. */
export function renderGateToggle(mode = 'live') {
  const btn = (key) =>
    `<button type="button" class="gate__mode gate__mode--${key}"${attrs({ 'data-mode': key, 'aria-pressed': String(mode === key) })}>${esc(GATE_MODES[key].button)}</button>`;
  return `<div class="gate__toggle" role="group" aria-label="Scenario" hidden>${btn('live')}${btn('hypo')}</div>`;
}

/** Spoken once the checks finish. */
export function gateAnnouncement(mode) {
  return mode === 'hypo'
    ? 'Illustration, not a recorded run. Check 5, substitute: no longer available. Outcome STALE.'
    : 'Deployed rehearsal R3. 10 of 10 checks passed. Outcome PROCEED.';
}

/** @param {{ mode?: 'live' | 'hypo', n?: number }} [state] */
export function renderGate({ mode = 'live', n = TOTAL } = {}) {
  const m = GATE_MODES[mode];
  const out = outcomeView(mode, n);
  return `<div class="gate" data-gate data-mode="${mode}">`
    + '<div class="gate__checks">'
    + '<div class="gate__bar">'
    + `<h3 class="gate__scenario" data-gate-scenario>${esc(m.button)}</h3>`
    + renderGateToggle(mode)
    + `<span class="gate__header" data-gate-header>${esc(m.header)}</span>`
    + '</div>'
    + `<ol class="checks" aria-label="Ten revalidation checks">${renderChecks(mode, n)}</ol>`
    + '</div>'
    + '<div class="gate__side">'
    + `<div class="outcome is-${out.state}" data-outcome><p class="label">OUTCOME</p><p class="outcome__verdict">${esc(out.verdict)}</p><p class="outcome__sub">${esc(out.sub)}</p></div>`
    + `<p class="gate__note" data-gate-note>${esc(m.note)}</p>`
    + `<a class="text-link" href="${LINKS.r3Record}">Read the R3 record →</a>`
    + '<p class="visually-hidden" role="status" data-gate-status></p>'
    + '</div>'
    + '</div>';
}
