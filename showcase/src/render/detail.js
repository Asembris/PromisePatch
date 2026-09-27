// The order detail panel's changing part: title, lane chip and the four facts.

import { DET, LANE_CLASS } from '../data/detail.js';
import { DEFAULT_ORDER } from '../data/rows.js';
import { esc } from './html.js';

export function renderDetail(id = DEFAULT_ORDER) {
  const d = DET[id];
  return `<div class="detail__head"><h3 id="detail-title" class="detail__title">Order ${esc(id)}</h3><span class="chip chip--lane lane--${LANE_CLASS[d.lane]}">${d.glyph} ${esc(d.lane)}</span></div>`
    + '<dl class="detail__list">'
    + `<div><dt>WHY</dt><dd>${esc(d.why)}</dd></div>`
    + `<div><dt>WHO DECIDES</dt><dd>${esc(d.who)}</dd></div>`
    + `<div><dt>SETTLED OUTCOME</dt><dd>${esc(d.out)}</dd></div>`
    + `<div><dt>EFFECTS, PER REHEARSAL</dt><dd class="mono detail__fx">${esc(d.fx)}</dd></div>`
    + '</dl>';
}
