// Reduced motion: the system preference, or the prototype's QA switch
// (`?motion=reduced`, or `localStorage['pp-qa'] = '{"motion":"reduced"}'`).
// Read at start and again whenever the system preference changes.

function qaSwitches() {
  let qa = {};
  try {
    qa = JSON.parse(localStorage.getItem('pp-qa') || '{}') || {};
  } catch {
    qa = {};
  }
  try {
    Object.assign(qa, Object.fromEntries(new URLSearchParams(location.search)));
  } catch {
    // no query string to read
  }
  return qa;
}

export function createMotion() {
  const qa = qaSwitches();
  const forced = qa.motion === 'reduced';
  const mq = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  const listeners = new Set();
  const motion = {
    reduced: forced || Boolean(mq && mq.matches),
    /** @param {(reduced: boolean) => void} fn */
    onChange(fn) {
      listeners.add(fn);
    },
  };
  if (forced) document.documentElement.classList.add('motion-reduced');
  if (mq && !forced) {
    mq.addEventListener('change', () => {
      motion.reduced = mq.matches;
      listeners.forEach((fn) => fn(motion.reduced));
    });
  }
  return motion;
}

/** @typedef {ReturnType<typeof createMotion>} Motion */
