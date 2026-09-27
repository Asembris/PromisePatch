// DET, verbatim from the approved prototype. `lane` maps to the CSS lane
// class; the prototype's hex colour lives in tokens.css as that lane's colour.

export const DET = {
  A: { lane: 'AUTO', glyph: '●', why: 'A substitution the customer’s recorded preference already allows.', who: 'A recorded constraint and a pre-authored recipe version. No new permission is needed.', out: 'Amended in the order system, v1 → v2, under CONSTRAINT.', fx: '1 order amendment' },
  B: { lane: 'ASK', glyph: '◆', why: 'A substitution the customer must approve.', who: 'The customer, with a literal YES on a signed web link.', out: 'One Telegram message; YES on the signed link; revalidated against a fresh snapshot; amended v1 → v2 under HUMAN_APPROVAL.', fx: '1 customer message · 1 order amendment' },
  C: { lane: 'BLOCKED', glyph: '■', why: 'The customer’s constraint forbids substitution.', who: 'The owner.', out: 'Escalated to the owner; scheduled kitchen work held.', fx: '1 task hold · 0 amendments' },
  D: { lane: 'BLOCKED', glyph: '■', why: 'No pre-authored recipe version exists.', who: 'The owner. Nothing invents a substitute at runtime.', out: 'Escalated to the owner; scheduled kitchen work held.', fx: '1 task hold · 0 amendments' },
  E: { lane: 'UNAFFECTED', glyph: '○', why: 'No raspberries in it.', who: 'Nobody. The failure does not reach it.', out: 'Untouched. Still v1 ACCEPTED in the mirror and in the order system’s store.', fx: '0 messages · 0 writes · 0 reservation changes · 0 task holds · 0 audit events' },
  F: { lane: 'UNAFFECTED', glyph: '○', why: 'No raspberries in it.', who: 'Nobody. The failure does not reach it.', out: 'Untouched. Still v1 ACCEPTED in the mirror and in the order system’s store.', fx: '0 messages · 0 writes · 0 reservation changes · 0 task holds · 0 audit events' },
};

/** Lane → CSS modifier (lane--auto etc.). */
export const LANE_CLASS = { AUTO: 'auto', ASK: 'ask', BLOCKED: 'blocked', UNAFFECTED: 'unaffected' };
