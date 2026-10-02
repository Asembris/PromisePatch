// The proof index: one row per PROOFS entry, claim · what it proves · file.

import { PROOFS } from '../data/proofs.js';
import { doc } from '../data/links.js';
import { esc } from './html.js';

export function renderProofs() {
  const rows = PROOFS.map(([claim, proves, file, href], i) =>
    `<li><a class="proof-row" href="${esc(href || doc(file))}">`
    + `<span class="proof-row__claim"><span class="proof-row__n">${String(i + 1).padStart(2, '0')}</span><span>${esc(claim)}</span></span>`
    + `<span class="proof-row__proves">${esc(proves)}</span>`
    + `<span class="proof-row__file">${esc(file)} <span aria-hidden="true">↗</span></span>`
    + '</a></li>');
  return `<ul class="proofs">${rows.join('')}</ul>`;
}
