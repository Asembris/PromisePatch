// One-shot section reveal (700 ms, `ui` easing, rootMargin −8%). Only blocks
// below the fold at load are armed, so nothing already on screen blinks, and
// nothing is armed under reduced motion.

/** @param {import('../lib/motion.js').Motion} motion */
export function initReveal(motion) {
  if (motion.reduced || !('IntersectionObserver' in window)) return;
  const els = [...document.querySelectorAll('[data-reveal]')].filter(
    (el) => el.getBoundingClientRect().top > window.innerHeight,
  );
  if (!els.length) return;

  const show = (el) => el.classList.remove('reveal-pending');
  const io = new IntersectionObserver(
    (entries) =>
      entries.forEach((e) => {
        if (e.isIntersecting) {
          show(e.target);
          io.unobserve(e.target);
        }
      }),
    { rootMargin: '0px 0px -8% 0px' },
  );
  els.forEach((el) => {
    el.classList.add('reveal-armed', 'reveal-pending');
    io.observe(el);
  });

  motion.onChange((reduced) => {
    if (!reduced) return;
    io.disconnect();
    els.forEach(show);
  });
}
