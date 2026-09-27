// Architecture: trace buttons, trace text, the ≥1080px diagram and the
// stacked chain below it. Only edge styling changes with the trace.

import { ARCH, ARCH_LABEL, EDGES, EDGE_LABELS, NODES, NODE_STYLE, EDGE_STYLE } from '../data/arch.js';
import { TRACES, DEFAULT_TRACE, TRACE_STAGGER_S } from '../data/traces.js';
import { attrs, esc } from './html.js';

/**
 * @param {string} edge edge id
 * @param {string} trace trace key
 * @param {boolean} [reduced] no stagger under reduced motion
 */
export function edgeView(edge, trace, reduced = false) {
  const idx = TRACES[trace].e.indexOf(edge);
  const lit = idx >= 0;
  const s = lit ? EDGE_STYLE.lit : EDGE_STYLE.dim;
  return { lit, stroke: s.stroke, width: s.width, marker: s.marker, delay: lit && !reduced ? `${+(idx * TRACE_STAGGER_S).toFixed(2)}s` : '0s' };
}

export function renderEdges(trace = DEFAULT_TRACE) {
  return EDGES.map(([id, d, dashed, both]) => {
    const v = edgeView(id, trace, true);
    return `<path${attrs({
      'data-edge': id,
      d,
      stroke: v.stroke,
      'stroke-width': v.width,
      'stroke-dasharray': dashed ? '5 5' : null,
      'marker-end': v.marker,
      'marker-start': both ? v.marker : null,
    })}></path>`;
  }).join('');
}

function renderNode(n) {
  const st = NODE_STYLE[n.kind];
  const rect = `<rect${attrs({ x: n.x, y: n.y, width: n.w, height: n.h, rx: n.rx, fill: st.fill, stroke: st.stroke, 'stroke-width': st.width, 'stroke-dasharray': st.dash })}></rect>`;
  const [tx, ty, title, anchor] = n.title;
  const t = `<text${attrs({ x: tx, y: ty, fill: '#F7F8FC', 'font-size': 16, 'font-weight': 600, 'text-anchor': anchor || null })}>${esc(title)}</text>`;
  const lines = n.lines.map(([x, y, text, size]) =>
    `<text class="arch-diagram__mono"${attrs({ x, y, fill: '#AEB6C8', 'font-size': size })}>${esc(text)}</text>`).join('');
  return rect + t + lines;
}

export function renderArchSvg(trace = DEFAULT_TRACE) {
  const labels = EDGE_LABELS.map(([x, y, text, anchor]) =>
    `<text${attrs({ x, y, 'text-anchor': anchor || null })}>${esc(text)}</text>`).join('');
  return `<svg viewBox="0 0 1200 570" width="1200" height="570" role="img" aria-label="${esc(ARCH_LABEL)}">`
    + '<defs>'
    + '<marker id="aD" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#3A4666"></path></marker>'
    + '<marker id="aL" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#8390F2"></path></marker>'
    + '</defs>'
    + `<g class="arch-diagram__edges" fill="none" stroke-linecap="round">${renderEdges(trace)}</g>`
    + `<g class="arch-diagram__mono" font-size="11" fill="#AEB6C8">${labels}</g>`
    + `<g class="arch-diagram__sans">${NODES.map(renderNode).join('')}</g>`
    + '</svg>';
}

const CHAIN_KIND = { AUTHORITY: 'authority', UNDERSTANDING: 'understanding', OUTSIDE: 'outside' };

export function renderChain() {
  const items = ARCH.map(([name, kind, edge]) =>
    `<li class="chain__item"><div class="chain__node chain__node--${CHAIN_KIND[kind]}"><span class="chain__name">${esc(name)}</span><span class="chain__kind">${kind}</span></div>`
    + (edge ? `<div class="chain__edge">↓ ${esc(edge)}</div>` : '')
    + '</li>');
  return `<ol class="chain" aria-label="Architecture, as a chain">${items.join('')}</ol>`;
}

/** Hidden until the enhancement script wires it. */
export function renderTraceButtons(trace = DEFAULT_TRACE) {
  const buttons = Object.entries(TRACES).map(([key, t]) =>
    `<button type="button" class="trace-btn"${attrs({ 'data-trace': key, 'aria-pressed': String(key === trace) })}>${esc(t.label)}</button>`);
  return `<div class="traces" role="group" aria-label="Trace a path" hidden>${buttons.join('')}</div>`;
}

/** The name is the no-JS stand-in for the pressed button; CSS hides it once enhanced. */
export function renderTraceText(trace = DEFAULT_TRACE) {
  return `<h3 class="trace-name label" data-trace-name>${esc(TRACES[trace].label)}</h3>`
    + `<p class="trace-text" aria-live="polite" data-trace-text>${esc(TRACES[trace].text)}</p>`;
}
