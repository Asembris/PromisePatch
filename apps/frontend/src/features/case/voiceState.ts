/**
 * Which of the case-shaped voice states a case is in, in one closed mapping.
 *
 * The P7.1 voice contract fixes nine states. Five of them are postures of *capture* — idle,
 * listening, captured, correcting, unavailable-microphone — and belong to the composer, which
 * knows nothing about a case. The four here are postures of a *case*, and each one is read off a
 * field the backend already published rather than worked out from anything on the screen.
 *
 * It decides nothing. It chooses which of the panel's own already-written labels to show, and
 * every sentence a worker actually reads under any of them is still `speech`, byte for byte. A
 * function here that composed a sentence about a promise would be the screen deciding what a
 * state means, which is the one thing this surface may never do.
 *
 * Separated from the panel so it can be checked directly, state by state, without mounting a
 * workspace to find out what a case with an open question looks like.
 */
import type { CaseWorkspaceResponse } from '../../api/types'

export type CaseVoiceState =
  | 'processing'
  | 'clarifying'
  | 'confirming'
  | 'waiting'
  | 'unavailable'

/** Whether a turn is in flight, and whether the last one was refused. Both the panel's own. */
export interface TurnPosture {
  pending: boolean
  refused: boolean
}

export function caseVoiceState(
  view: CaseWorkspaceResponse,
  turn: TurnPosture,
): CaseVoiceState {
  // A refusal first, because it is the one state that is about the *turn* rather than the case:
  // the case is exactly as it was, and saying anything else about it here would overstate what
  // just happened.
  if (turn.refused) return 'unavailable'
  if (turn.pending) return 'processing'
  if (view.question !== null) return 'clarifying'
  if (view.awaiting_confirmation) return 'confirming'
  if (view.headline === 'UNDERSTANDING' || view.headline === 'WORKING') return 'processing'
  return 'waiting'
}

/**
 * The state, in words, so it is never carried by a colour alone.
 *
 * About the conversation — whose turn it is, and whether one is in flight — and never about an
 * outcome. What happened to a promise is band 3's to say, from the backend's own phrase.
 */
export const CASE_VOICE_LABEL: Record<CaseVoiceState, string> = {
  processing: 'working it out',
  clarifying: 'one question is open',
  confirming: 'waiting for your yes',
  waiting: 'nothing is yours right now',
  unavailable: 'that turn did not happen',
}
