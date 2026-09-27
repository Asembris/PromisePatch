// The hero controller: the prototype's initHero, layout, frame, place and
// heroGo, with React state replaced by direct DOM writes (caption, step
// buttons' aria-pressed, renderer label).
//
// Progressive order: the stage already shows the settled
// `assets/hero-fallback.svg` from the HTML, so first paint is meaningful with
// or without JavaScript. After first paint, once the stage is within one
// viewport, three.js is imported as its own chunk. If WebGL is unavailable,
// the import fails, renderer creation throws, or nothing has started within
// THREE_TIMEOUT_MS, the SVG renderer draws the same scene instead. The
// fallback image is removed only when a renderer has drawn its first frame,
// and the controls are revealed only then, so the stage is never blank and a
// control is never dead.

import { CAPTIONS, END, LABELS, LD, LM, MOBILE_STAGE_MAX, PH, RENDERER_LABELS, STAGE_LABEL, THREE_TIMEOUT_MS } from './constants.js';
import { phaseOf, scene } from './scene.js';
import { makeSvg } from './svg-renderer.js';

function glOK() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch {
    return false;
  }
}

function buildOverlay(ov) {
  ov.innerHTML = LABELS.map((l) => {
    let inner;
    if (l.lines) {
      inner = `<div data-a class="hl__a hl__a--${l.a}">${l.lines
        .map(([cls, text]) => `<span class="${cls.replace(/ t$/, '')}"${/ t$/.test(cls) ? ' data-t' : ''}>${text}</span>`)
        .join('')}</div>`;
    } else if (l.text) {
      inner = `<div data-a class="hl__a hl__a--${l.a} ${l.text}">${l.value}</div>`;
    } else {
      inner = `<div data-a data-t class="hl__a hl__a--${l.a}">${l.value}</div>`;
    }
    return `<div class="hl" data-k="${l.k}">${inner}</div>`;
  }).join('');
  const labels = {};
  ov.querySelectorAll('[data-k]').forEach((el) => {
    labels[el.dataset.k] = { el, a: el.querySelector('[data-a]'), t: el.querySelector('[data-t]') };
  });
  return labels;
}

/** @param {import('../lib/motion.js').Motion} motion */
export function initHero(motion) {
  const figure = document.querySelector('.hero__figure');
  const st = figure?.querySelector('.hero__stage');
  const fallback = st?.querySelector('.hero__fallback');
  const caption = figure?.querySelector('[data-hero-caption]');
  const controls = figure?.querySelector('[data-hero-controls]');
  const label = st?.querySelector('[data-hero-label]');
  if (!figure || !st || !caption || !controls || !label) return;

  const steps = [...controls.querySelectorAll('[data-hero-step]')];
  const replay = controls.querySelector('[data-hero-replay]');
  const pause = controls.querySelector('[data-hero-pause]');

  const gl = document.createElement('div');
  gl.className = 'hero__gl';
  gl.setAttribute('aria-hidden', 'true');
  const ov = document.createElement('div');
  ov.className = 'hero__overlay';
  ov.setAttribute('aria-hidden', 'true');
  st.insertBefore(ov, label);
  st.insertBefore(gl, ov);

  const want = motion.qa.renderer === 'svg' ? 'svg' : 'auto';
  const h = {
    R: null, L: null, W: 0, H: 0, isM: false,
    t: motion.reduced ? END : 0, playing: !motion.reduced, paused: false,
    mx: 0, my: 0, cx: 0, cy: 0, last: 0, lastRaf: 0, raf: 0, wd: 0,
    vis: true, hp: -1, dirty: true, labels: buildOverlay(ov), settled: false,
  };

  const running = () => h.vis && document.visibilityState !== 'hidden';
  // Under reduced motion nothing moves by itself, so the loop only draws
  // when something changed; otherwise parallax and dust keep it running.
  const needsLoop = () => running() && (!motion.reduced || h.dirty);

  function layout(force) {
    if (!h.R) return;
    const W = st.clientWidth, H = st.clientHeight, m = W < MOBILE_STAGE_MAX;
    if (!force && W === h.W && H === h.H) return;
    const rebuild = force || m !== h.isM;
    h.isM = m; h.W = W; h.H = H; h.L = m ? LM : LD;
    h.R.resize(W, H, h.L, rebuild);
    h.dirty = true;
    wake();
  }

  function place(sc) {
    for (const k in sc.lab) {
      const L = h.labels[k]; if (!L) continue; const l = sc.lab[k];
      const p = h.R.project(l.x, l.y, l.z || 0);
      L.el.style.transform = `translate3d(${p.x.toFixed(1)}px,${p.y.toFixed(1)}px,0)`;
      L.el.style.opacity = l.op;
      if (l.ax && L.a && L.ax !== l.ax) { L.a.style.transform = l.ax === 'r' ? 'translate(-100%,-50%)' : l.ax === 'l' ? 'translate(0,-50%)' : l.ax === 'tl' ? 'translate(0,-100%)' : 'translate(-50%,-100%)'; L.a.style.textAlign = l.ax === 'r' ? 'right' : ''; L.a.style.alignItems = l.ax === 'r' ? 'flex-end' : l.ax === 'b' ? 'center' : 'flex-start'; L.ax = l.ax; }
      if (l.text != null && L.t && L._t !== l.text) { L.t.textContent = l.text; L._t = l.text; }
      if (l.color && L.a && L._c !== l.color) { L.a.style.color = l.color; L._c = l.color; }
    }
  }

  function setPhase(hp) {
    if (hp === h.hp) return;
    h.hp = hp;
    caption.textContent = CAPTIONS[hp];
    steps.forEach((b, i) => b.setAttribute('aria-pressed', String(hp === i)));
  }

  function frame(now) {
    const dt = Math.min(0.2, (now - h.last) / 1000); h.last = now;
    if (!h.vis || !h.L) return;
    if (h.playing && !h.paused) { h.t = Math.min(END, h.t + dt); if (h.t >= END) h.playing = false; }
    const k = motion.reduced ? 0 : 0.05; h.cx += (h.mx - h.cx) * k; h.cy += (h.my - h.cy) * k;
    const sc = scene(h.t, h.L);
    h.R.draw(sc, h.cx, h.cy, motion.reduced ? 0 : now / 1000);
    place(sc);
    h.dirty = false;
    setPhase(phaseOf(h.t, PH));
  }

  function loop(now) {
    h.raf = 0;
    h.lastRaf = performance.now();
    frame(now);
    if (needsLoop()) h.raf = requestAnimationFrame(loop);
  }

  // Restart the loop after a pause (off-screen, hidden tab, reduced motion).
  function wake() {
    if (!h.R || h.raf || !needsLoop()) return;
    h.last = performance.now();
    h.raf = requestAnimationFrame(loop);
  }

  function sleep() {
    if (h.raf) cancelAnimationFrame(h.raf);
    h.raf = 0;
  }

  function go(i) {
    if (motion.reduced) { h.t = i >= 5 ? END : PH[i + 1] - 0.001; } else { h.t = PH[i]; h.playing = true; }
    if (h.paused) setPaused(false);
    h.dirty = true;
    wake();
  }

  function setPaused(p) {
    h.paused = p;
    pause.querySelector('[data-label]').textContent = p ? 'Play' : 'Pause';
    pause.querySelector('[data-glyph]').textContent = p ? '▶' : '❚❚';
  }

  function start(R, kind) {
    if (h.settled) { R.dispose(); return; }
    h.settled = true;
    h.R = R;
    label.textContent = STAGE_LABEL + RENDERER_LABELS[kind];
    label.hidden = false;
    st.dataset.renderer = kind;
    layout(true);
    new ResizeObserver(() => layout(false)).observe(st);
    h.last = performance.now();
    frame(h.last);
    fallback?.remove();
    // A browser that throttles rAF while the page is visible still gets
    // frames; a hidden or off-screen stage gets none.
    h.wd = setInterval(() => {
      const n = performance.now();
      if (running() && (!motion.reduced || h.dirty) && n - h.lastRaf > 300) frame(n);
    }, 120);
    wake();

    steps.forEach((b, i) => b.addEventListener('click', () => go(i)));
    replay.addEventListener('click', () => go(0));
    pause.addEventListener('click', () => { setPaused(!h.paused); wake(); });
    pause.hidden = motion.reduced;
    controls.hidden = false;
    figure.classList.add('is-enhanced');
  }

  function svg() {
    if (h.settled) return;
    try {
      start(makeSvg(gl), 'svg');
    } catch (error) {
      // The settled fallback image stays; nothing is left half-drawn.
      console.error('showcase: hero SVG renderer failed; the settled image stays', error);
      gl.textContent = '';
    }
  }

  function boot() {
    if (want === 'svg' || !glOK()) { svg(); return; }
    const timer = setTimeout(svg, THREE_TIMEOUT_MS);
    import('./three-renderer.js')
      .then((mod) => {
        clearTimeout(timer);
        if (h.settled) return;
        let R;
        try {
          R = mod.makeThree(gl);
        } catch {
          gl.textContent = '';
          svg();
          return;
        }
        start(R, 'webgl');
      })
      .catch(() => {
        clearTimeout(timer);
        svg();
      });
  }

  // Pointer parallax, off under reduced motion.
  st.addEventListener('pointermove', (e) => {
    if (motion.reduced) return;
    const r = st.getBoundingClientRect();
    h.mx = (e.clientX - r.left) / r.width * 2 - 1; h.my = (e.clientY - r.top) / r.height * 2 - 1;
  });
  st.addEventListener('pointerleave', () => { h.mx = 0; h.my = 0; });

  // Rendering pauses off-screen and in hidden tabs; the timeline does not
  // advance while paused (dt is capped on resume).
  let booted = false;
  new IntersectionObserver((es) => {
    h.vis = es[0].isIntersecting;
    if (h.vis) wake(); else sleep();
  }, { threshold: 0 }).observe(st);
  // Lazy boot: after first paint, once the stage is within a viewport.
  const near = new IntersectionObserver((es) => {
    if (booted || !es.some((e) => e.isIntersecting)) return;
    booted = true;
    near.disconnect();
    requestAnimationFrame(() => setTimeout(boot, 0));
  }, { rootMargin: '100% 0px' });
  near.observe(st);
  document.addEventListener('visibilitychange', () => (running() ? wake() : sleep()));

  // A change of the system preference while the page is open: reduced jumps
  // to the settled end and stops; full motion keeps the settled end and
  // resumes parallax and drift. Never a half-played state.
  motion.onChange((reduced) => {
    h.t = END; h.playing = false; h.mx = h.my = 0;
    if (reduced) { h.cx = 0; h.cy = 0; }
    if (h.paused) setPaused(false);
    pause.hidden = reduced;
    h.dirty = true;
    wake();
  });

  // Deterministic capture for the reference comparison, as in the prototype.
  window.__ppHero = {
    seek: (t) => {
      if (!h.R) return -1;
      layout(false); h.t = t; h.playing = false; h.vis = true; h.last = performance.now(); frame(h.last);
      return phaseOf(t, PH);
    },
    get renderer() { return st.dataset.renderer || 'none'; },
  };
}
