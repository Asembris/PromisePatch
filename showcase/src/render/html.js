// Tiny helpers shared by the pure renderers. No DOM, no I/O: every renderer
// runs in Node at build time and in the browser at runtime.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };

/** @param {unknown} value */
export const esc = (value) => String(value).replace(/[&<>"]/g, (c) => ESC[c]);

/** @param {Record<string, string | number | boolean | null | undefined>} attrs */
export function attrs(attrs) {
  return Object.entries(attrs)
    .filter(([, v]) => v !== false && v !== null && v !== undefined)
    .map(([k, v]) => (v === true ? ` ${k}` : ` ${k}="${esc(v)}"`))
    .join('');
}
