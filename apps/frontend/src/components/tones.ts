/**
 * Colour for a state name.
 *
 * Presentation and nothing else: it does not reclassify anything, it does not invent a state,
 * and a name it has never seen is shown neutrally rather than guessed at. Kept in its own
 * module so the component file exports components only.
 */
export type BadgeTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

export const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200',
  good: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  warn: 'bg-amber-50 text-amber-900 ring-amber-200',
  bad: 'bg-red-50 text-red-800 ring-red-200',
  info: 'bg-sky-50 text-sky-800 ring-sky-200',
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
