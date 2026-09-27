// The R1–R5 rehearsal table: a real table with caption and scope.

import { REHEARSALS, REHEARSALS_CAPTION } from '../data/rehearsals.js';
import { LINKS } from '../data/links.js';
import { esc } from './html.js';

export function renderRehearsals() {
  const rows = REHEARSALS.map(([run, key, where, untouched, verdict]) =>
    `<tr><th scope="row"><a href="${LINKS[key]}">${run}</a></th><td>${esc(where)}</td><td class="mono">${esc(untouched)}</td><td class="rehearsals__verdict">${esc(verdict)}</td></tr>`);
  return '<table class="rehearsals">'
    + `<caption>${esc(REHEARSALS_CAPTION)}</caption>`
    + '<thead><tr><th scope="col">run</th><th scope="col">worker restarted</th><th scope="col">untouched</th><th scope="col" class="rehearsals__verdict">verdict</th></tr></thead>'
    + `<tbody>${rows.join('')}</tbody>`
    + '</table>';
}
