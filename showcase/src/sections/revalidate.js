// The revalidation gate: the recorded R3 run by default, or the labelled
// illustration. Checks light one per 120 ms when 35% of the gate is in view,
// and again on every scenario change; under reduced motion all ten show at once.

import { CHECK_STEP_MS, GATE_MODES, GATE_THRESHOLD } from '../data/checks.js';
import { TOTAL, checkView, gateAnnouncement, outcomeView } from '../render/gate.js';

/** @param {import('../lib/motion.js').Motion} motion */
export function initRevalidate(motion) {
  const section = document.getElementById('revalidate');
  const gate = section?.querySelector('[data-gate]');
  if (!section || !gate) return;

  const toggle = gate.querySelector('.gate__toggle');
  const modeButtons = [...gate.querySelectorAll('[data-mode]')].filter((el) => el.tagName === 'BUTTON');
  const checks = [...gate.querySelectorAll('.check')];
  const outcome = gate.querySelector('[data-outcome]');
  const verdict = outcome.querySelector('.outcome__verdict');
  const sub = outcome.querySelector('.outcome__sub');
  const header = gate.querySelector('[data-gate-header]');
  const note = gate.querySelector('[data-gate-note]');
  const scenario = gate.querySelector('[data-gate-scenario]');
  const status = gate.querySelector('[data-gate-status]');

  const state = { mode: /** @type {'live' | 'hypo'} */ ('live'), n: TOTAL, timer: 0 };

  function paint() {
    const { mode, n } = state;
    const m = GATE_MODES[mode];
    gate.dataset.mode = mode;
    modeButtons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    scenario.textContent = m.button;
    header.textContent = m.header;
    note.textContent = m.note;
    checks.forEach((li, i) => {
      const v = checkView(i, mode, n);
      li.className = `check is-${v.state}`;
      li.querySelector('.check__mark').textContent = v.mark;
      li.querySelector('.check__value').textContent = v.value;
      li.querySelector('.check__text .visually-hidden').textContent = v.spoken;
    });
    const out = outcomeView(mode, n);
    outcome.className = `outcome is-${out.state}`;
    verdict.textContent = out.verdict;
    sub.textContent = out.sub;
  }

  function announce() {
    status.textContent = '';
    setTimeout(() => {
      status.textContent = gateAnnouncement(state.mode);
    }, 60);
  }

  function run() {
    clearInterval(state.timer);
    if (motion.reduced) {
      state.n = TOTAL;
      paint();
      announce();
      return;
    }
    state.n = 0;
    paint();
    const t0 = performance.now();
    state.timer = setInterval(() => {
      const n = Math.min(TOTAL, Math.floor((performance.now() - t0) / CHECK_STEP_MS));
      if (n !== state.n) {
        state.n = n;
        paint();
      }
      if (n >= TOTAL) {
        clearInterval(state.timer);
        announce();
      }
    }, 40);
  }

  modeButtons.forEach((b) =>
    b.addEventListener('click', () => {
      state.mode = /** @type {'live' | 'hypo'} */ (b.dataset.mode);
      run();
    }),
  );

  if (!motion.reduced && 'IntersectionObserver' in window) {
    // Wait for the gate to come into view, then run the checks once.
    state.n = 0;
    paint();
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect();
          run();
        }
      },
      { threshold: GATE_THRESHOLD },
    );
    io.observe(gate);
  }

  motion.onChange((reduced) => {
    if (reduced && state.n < TOTAL) {
      clearInterval(state.timer);
      state.n = TOTAL;
      paint();
    }
  });

  toggle.hidden = false;
  section.classList.add('is-enhanced');
}
