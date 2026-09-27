// CELL, verbatim from the approved prototype. The same values are the
// `.cell--<kind>` rules in sections.css; this table is the reference the CSS
// was written from, and the renderer uses only its keys.

export const CELL = {
  i: { bg: 'transparent', bd: '#26324D', fg: '#AEB6C8', bs: 'solid' },
  r: { bg: 'transparent', bd: '#F7F8FC', fg: '#F7F8FC', bs: 'solid' },
  auto: { bg: 'rgba(66,188,211,.13)', bd: '#42BCD3', fg: '#7FD6E6', bs: 'solid' },
  ask: { bg: 'rgba(242,195,116,.12)', bd: '#F2C374', fg: '#F2C374', bs: 'solid' },
  wait: { bg: 'rgba(242,195,116,.06)', bd: '#F2C374', fg: '#F2C374', bs: 'dashed' },
  blk: { bg: 'rgba(241,138,118,.12)', bd: '#F18A76', fg: '#F6A897', bs: 'solid' },
  un: { bg: 'transparent', bd: '#3A4666', fg: '#AEB6C8', bs: 'dashed' },
  done: { bg: '#F7F8FC', bd: '#F7F8FC', fg: '#0B1221', bs: 'solid' },
};

/** A cell whose stage has not happened yet (prototype: '·', #1C2640 border, 50%). */
export const FUTURE_TEXT = '·';
