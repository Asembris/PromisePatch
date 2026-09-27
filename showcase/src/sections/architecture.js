// Architecture traces. A trace button lights only its path, edge by edge,
// 140 ms apart; under reduced motion it lights at once. The narrow chain is
// static and shows every node; only the trace text changes there.

import { TRACES, DEFAULT_TRACE } from '../data/traces.js';
import { edgeView } from '../render/arch.js';

/** @param {import('../lib/motion.js').Motion} motion */
export function initArchitecture(motion) {
  const section = document.getElementById('architecture');
  const group = section?.querySelector('.traces');
  const text = section?.querySelector('[data-trace-text]');
  const name = section?.querySelector('[data-trace-name]');
  if (!section || !group || !text || !name) return;

  const buttons = [...group.querySelectorAll('[data-trace]')];
  const edges = [...section.querySelectorAll('.arch-diagram [data-edge]')];

  function setTrace(trace) {
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.trace === trace)));
    name.textContent = TRACES[trace].label;
    text.textContent = TRACES[trace].text;
    for (const path of edges) {
      const v = edgeView(path.dataset.edge, trace, motion.reduced);
      path.style.transitionDelay = v.delay;
      path.setAttribute('stroke', v.stroke);
      path.setAttribute('stroke-width', String(v.width));
      path.setAttribute('marker-end', v.marker);
      if (path.hasAttribute('marker-start')) path.setAttribute('marker-start', v.marker);
    }
  }

  buttons.forEach((b) => b.addEventListener('click', () => setTrace(b.dataset.trace)));
  setTrace(DEFAULT_TRACE);

  group.hidden = false;
  section.classList.add('is-enhanced');
}
