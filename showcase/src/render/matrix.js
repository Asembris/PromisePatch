// Six promises: stepper, stage note and matrix. The view functions are the
// single model of a state; the string renderers and the runtime DOM updates
// both read them, so build output and interaction cannot drift.

import { STAGES, SETTLED } from '../data/stages.js';
import { ORDER_IDS, ROWS, DEFAULT_ORDER } from '../data/rows.js';
import { FUTURE_TEXT } from '../data/cells.js';
import { attrs, esc } from './html.js';

/**
 * @param {string} id order id
 * @param {number} i stage column
 * @param {number} stage current stage
 */
export function cellView(id, i, stage) {
  const [kind, text] = ROWS[id][i];
  const when = i > stage ? 'future' : i === stage ? 'current' : 'past';
  return {
    kind,
    when,
    text: when === 'future' ? FUTURE_TEXT : text,
    className: `cell cell--${kind} is-${when}`,
  };
}

/** @param {ReturnType<typeof cellView>} v */
const renderCell = (v) => `<span class="${v.className}">${esc(v.text)}</span>`;

/** @param {string} id @param {number} stage */
export const renderCells = (id, stage) => STAGES.map((_, i) => renderCell(cellView(id, i, stage))).join('');

/**
 * @param {{ stage?: number, sel?: string, interactive?: boolean }} [state]
 * Without `interactive`, order ids are plain text: a no-JS reader never meets
 * a button that does nothing.
 */
export function renderMatrix({ stage = SETTLED, sel = DEFAULT_ORDER, interactive = false } = {}) {
  const rows = ORDER_IDS.map((id) => {
    const on = id === sel;
    const idEl = interactive
      ? `<button type="button" class="matrix__id"${attrs({ 'data-order': id, 'aria-pressed': String(on), 'aria-label': `Order ${id}, show details` })}>${id}</button>`
      : `<span class="matrix__id"><span class="visually-hidden">Order </span>${id}</span>`;
    return `<li class="matrix__row${on ? ' is-selected' : ''}" data-row="${id}">${idEl}<span class="matrix__cells">${renderCells(id, stage)}</span></li>`;
  });
  return `<ul class="matrix" aria-label="Orders at this stage">${rows.join('')}</ul>`;
}

/** @param {number} stage */
export const stageLabel = (stage) => `${stage + 1} ${STAGES[stage].name}`;

/** The chip is the no-JS stand-in for the stepper; CSS hides it once enhanced. */
export const renderStageNote = (stage = SETTLED) =>
  `<span class="stage-note__stage">${esc(stageLabel(stage))}</span><span data-stage-note>${esc(STAGES[stage].note)}</span>`;

/** Rendered hidden; the enhancement script reveals it once it is wired. */
export function renderStepper(stage = SETTLED) {
  const buttons = STAGES.map((st, i) =>
    `<button type="button" class="stepper__stage"${attrs({ 'data-stage': i, 'aria-pressed': String(i === stage) })}><span class="stepper__n">${i + 1}</span>${esc(st.name)}</button>`,
  );
  return `<div class="stepper" role="group" aria-label="Case stage" hidden><button type="button" class="stepper__play" data-play>${playLabel(false)}</button>${buttons.join('')}</div>`;
}

/** @param {boolean} playing */
export const playLabel = (playing) => (playing ? '❚❚ Pause' : '▶ Play case');

/** @param {number} stage */
export const stageAnnouncement = (stage) => `Stage ${stage + 1} of ${STAGES.length}, ${STAGES[stage].name}. ${STAGES[stage].note}`;
