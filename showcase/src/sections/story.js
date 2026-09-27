// Six promises: stepper, Play case, selectable orders, detail panel. Starts
// from the settled markup the build rendered and changes it in place, so a
// focused button keeps focus and cell colours can transition.

import { STAGES, SETTLED, PLAY_STEP_MS, PLAY_STEP_REDUCED_MS } from '../data/stages.js';
import { ORDER_IDS, DEFAULT_ORDER } from '../data/rows.js';
import { cellView, playLabel, renderMatrix, stageAnnouncement, stageLabel } from '../render/matrix.js';
import { renderDetail } from '../render/detail.js';

/** @param {import('../lib/motion.js').Motion} motion */
export function initStory(motion) {
  const section = document.getElementById('story');
  const stepper = section?.querySelector('.stepper');
  const staticMatrix = section?.querySelector('.matrix');
  const detail = section?.querySelector('[data-detail]');
  const status = section?.querySelector('[data-story-status]');
  if (!section || !stepper || !staticMatrix || !detail || !status) return;

  const state = { stage: SETTLED, sel: DEFAULT_ORDER, timer: 0 };

  // The same renderer, now with order buttons instead of plain letters.
  staticMatrix.outerHTML = renderMatrix({ stage: state.stage, sel: state.sel, interactive: true });
  const matrix = section.querySelector('.matrix');
  const play = stepper.querySelector('[data-play]');
  const stageButtons = [...stepper.querySelectorAll('[data-stage]')];
  const chip = section.querySelector('.stage-note__stage');
  const note = section.querySelector('[data-stage-note]');

  function setStage(stage) {
    state.stage = stage;
    stageButtons.forEach((b, i) => b.setAttribute('aria-pressed', String(i === stage)));
    for (const id of ORDER_IDS) {
      const cells = matrix.querySelectorAll(`[data-row="${id}"] .cell`);
      cells.forEach((el, i) => {
        const v = cellView(id, i, stage);
        el.className = v.className;
        el.textContent = v.text;
      });
    }
    chip.textContent = stageLabel(stage);
    note.textContent = STAGES[stage].note;
    status.textContent = stageAnnouncement(stage);
  }

  function select(id) {
    state.sel = id;
    matrix.querySelectorAll('[data-row]').forEach((row) => {
      const on = row.dataset.row === id;
      row.classList.toggle('is-selected', on);
      row.querySelector('[data-order]').setAttribute('aria-pressed', String(on));
    });
    detail.innerHTML = renderDetail(id);
  }

  function stop() {
    clearInterval(state.timer);
    state.timer = 0;
    play.textContent = playLabel(false);
  }

  function start() {
    setStage(0);
    play.textContent = playLabel(true);
    state.timer = setInterval(() => {
      setStage(state.stage + 1);
      if (state.stage >= SETTLED) stop();
    }, motion.reduced ? PLAY_STEP_REDUCED_MS : PLAY_STEP_MS);
  }

  play.addEventListener('click', () => (state.timer ? stop() : start()));
  stageButtons.forEach((b) =>
    b.addEventListener('click', () => {
      stop();
      setStage(Number(b.dataset.stage));
    }),
  );
  matrix.addEventListener('click', (e) => {
    const btn = e.target instanceof Element ? e.target.closest('[data-order]') : null;
    if (btn) select(btn.dataset.order);
  });

  stepper.hidden = false;
  section.classList.add('is-enhanced');
}
