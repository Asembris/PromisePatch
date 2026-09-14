/**
 * The three things a worker may hear, and the hard rule about which is which.
 *
 * P7.1 §7 gives five of the nine voice states an audible column. Four of them — clarifying,
 * confirming, waiting, and every answer in between — are **the backend's sentence**, read out
 * byte for byte by `speakTurnReply`. There is no summary step here, no truncation and no wording
 * of this module's own for any of them, because a spoken paraphrase of "planned" is one word
 * away from "done" and nobody can hear a footnote.
 *
 * The remaining two states are audible statements about the **turn**, and they are the only
 * strings in this file: a short acknowledgement while a turn is in flight, and a statement that
 * a refused turn did not happen. Both are fixed, both are about the conversation rather than
 * about a case, and neither may contain a digit or any of the thirty-nine outcome words the
 * orchestrator's own glue gate bans (`semantic/jobs.py`, `CLAIM_WORDS`) — held to the same bar
 * as the model's glue, because a sentence a screen composed is no more trustworthy than one a
 * model composed. `voice.test.tsx` asserts both properties against that list rather than
 * trusting the wording to stay careful.
 *
 * The acknowledgement is deliberately spoken *before* there is anything to report. That is the
 * honest-progress reply the contract asks for: it says a turn is being worked on and stops, and
 * the moment a real answer exists it is cancelled mid-word and replaced by the backend's.
 *
 * Nothing here decides anything. Where a browser has no voice, every one of these is silent and
 * the same sentence is on the screen, which is the same product rather than a degraded one.
 */
import { audioStarted } from '../../instrumentation/turnTiming'
import { speakAloud } from './speech'

/**
 * What a worker hears the instant a turn is sent.
 *
 * About the turn and nothing else. It names no case, no promise, no customer and no outcome,
 * and it is the same five words whatever the turn was — a fixed phrase cannot accidentally
 * report a result, and a phrase composed per turn eventually would.
 */
export const TURN_ACKNOWLEDGEMENT = 'Working on that turn now.'

/**
 * What a worker hears when a turn was refused.
 *
 * Two facts, both of them true by construction: the turn did not happen, and the case is
 * therefore exactly what it was before anybody spoke. The backend's own refusal message stays
 * on the screen beside it; this is the statement the contract requires be *audible*, and it
 * deliberately does not read that message aloud, because a refusal message explains why one
 * turn was declined and is not a description of the case.
 */
export const TURN_DID_NOT_HAPPEN = 'That turn did not happen. The case is exactly as it was.'

/** A turn has left the browser. Honest progress, never a result. */
export function announceTurnSent(): void {
  speakAloud(TURN_ACKNOWLEDGEMENT, { onStart: () => { audioStarted('acknowledgement') } })
}

/** A turn was refused. The case is unchanged, and this says exactly that and no more. */
export function announceTurnRefused(): void {
  speakAloud(TURN_DID_NOT_HAPPEN, { onStart: () => { audioStarted('refusal') } })
}

/**
 * The backend's sentence, out loud, unchanged.
 *
 * `text` is whatever the backend returned for this turn — `status_view`'s rendering or the
 * receipt for the statement just accepted — and this function has no ability to alter it.
 */
export function speakTurnReply(text: string): void {
  speakAloud(text, { onStart: () => { audioStarted('reply') } })
}
