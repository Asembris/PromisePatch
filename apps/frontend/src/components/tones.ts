/**
 * Colour for a state name.
 *
 * Presentation and nothing else: it does not reclassify anything, it does not invent a state,
 * and a name it has never seen is shown neutrally rather than guessed at. Kept in its own
 * module so the component file exports components only.
 */
export type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

export const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-panel text-muted ring-edge',
  good: 'bg-done/12 text-done ring-done/30',
  warn: 'bg-ask/12 text-ask ring-ask/35',
  bad: 'bg-owner/12 text-owner ring-owner/35',
  info: 'bg-auto/12 text-auto ring-auto/35',
}

export function toneForState(state: string): BadgeTone {
  const upper = state.toUpperCase()
  if (upper.includes('BLOCKED') || upper.includes('ESCALATED') || upper.includes('OUT_OF_SERVICE')) {
    return 'bad'
  }
  if (upper.includes('APPROVAL') || upper.includes('WAITING') || upper.includes('HELD')) {
    return 'warn'
  }
  if (upper.includes('RECOVERED') || upper.includes('IN_SERVICE') || upper.includes('UNAFFECTED')) {
    return 'good'
  }
  if (upper.includes('AUTO')) return 'info'
  return 'neutral'
}
