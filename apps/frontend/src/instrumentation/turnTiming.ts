/**
 * When each part of a turn happened, recorded and never interpreted.
 *
 * **This measures nothing.** It writes down clock readings at four places a turn passes through
 * and stops there: it computes no duration, compares nothing against a threshold, and holds no
 * opinion about whether a turn was fast. The G7 gate — ten predeclared turns, at least nine
 * starting a truthful spoken response within four seconds of speech ending — is a later slice's
 * to run, and it cannot be run at all against a surface that never wrote the instants down. So
 * this is the half that has to exist first, and the half that must be careful to claim nothing.
 *
 * **Speech end is recorded twice, on purpose.** A browser recogniser offers two candidate
 * instants for "the worker stopped speaking": the last final result it reports, and `onend`,
 * which arrives afterwards when it has closed the microphone. Which of the two G7's "speech
 * ending" means is not declared in the frozen contract, and choosing one here would be this
 * module quietly deciding the denominator of a published number. Both are recorded under their
 * own names; whoever measures picks, in the open, and can see how far apart they were.
 *
 * **First audio is the utterance's, not the call's.** `speechSynthesis.speak` returns as soon as
 * the utterance is queued, which on a cold voice list can be well before any sound exists. The
 * only honest anchor for "a spoken response started" is `SpeechSynthesisUtterance.onstart`, and
 * that is the only thing written here. Each utterance is recorded with its own kind, because a
 * short acknowledgement and the backend's actual answer are different events and a later slice
 * must be able to count them separately rather than discover they were merged.
 *
 * Readings are `performance.now()` — monotonic milliseconds since the page loaded, unaffected by
 * a clock correction mid-turn — and each record additionally carries one wall-clock stamp so a
 * session can be placed in time. Durations, if anybody ever wants one, are a subtraction
 * somebody else performs deliberately.
 *
 * It imports nothing. A record here is inert data: no case, no promise, no worker, no sentence.
 */

/** Which of the recogniser's two candidate instants a reading is. Neither is privileged. */
export type SpeechEndAnchor = 'final_result' | 'recogniser_end'

/** Which utterance began, so an acknowledgement is never counted as an answer. */
export type SpokenKind = 'acknowledgement' | 'reply' | 'refusal' | 'replay'

export type TurnVerb = 'report' | 'clarify' | 'confirm' | 'withdraw'

/** Whether the words came from the microphone, the keyboard, or no turn at all. */
export type TurnOrigin = 'spoken' | 'typed' | 'none'

export interface SpokenAudio {
  utterance: SpokenKind
  /** `SpeechSynthesisUtterance.onstart`, never the return of `speak`. */
  at: number
}

export interface TurnTiming {
  id: string
  verb: TurnVerb | null
  origin: TurnOrigin
  /** Wall clock, once, so a monotonic record can be placed in a real session. */
  opened: string
  /** The last final result the recogniser reported before this turn was sent. */
  speech_end_final_result: number | null
  /** The recogniser's `onend`, which follows the last final result. */
  speech_end_recogniser_end: number | null
  sent: number | null
  /** When the backend's answer arrived, refusal included — a refusal is a response. */
  received: number | null
  outcome: 'accepted' | 'refused' | null
  audio: SpokenAudio[]
}

/**
 * How many turns are kept. A session that ran all morning keeps its most recent turns rather
 * than growing without bound; ten is the number anybody will ever read out of it.
 */
const KEPT = 200

interface PendingCapture {
  finalResult: number | null
  recogniserEnd: number | null
}

const records: TurnTiming[] = []
let pending: PendingCapture = { finalResult: null, recogniserEnd: null }
let current: TurnTiming | null = null

function now(): number {
  return performance.now()
}

/** A new capture began, so any anchors left over from an abandoned one are not this turn's. */
export function captureStarted(): void {
  pending = { finalResult: null, recogniserEnd: null }
}

/**
 * One candidate speech-end instant.
 *
 * `final_result` is written every time the recogniser reports a final result, so what survives
 * is the last one — which is what "speech ended" would mean if it is the anchor that counts.
 */
export function speechEnded(anchor: SpeechEndAnchor): void {
  if (anchor === 'final_result') pending.finalResult = now()
  else pending.recogniserEnd = now()
}

/**
 * The turn left the browser.
 *
 * Called immediately before the request is issued rather than after it resolves, and it consumes
 * whatever capture anchors are pending — so a turn that was typed carries none and says so,
 * rather than borrowing the anchors of some earlier spoken turn.
 */
export function turnSent(verb: TurnVerb): void {
  const spoken = pending.finalResult !== null || pending.recogniserEnd !== null
  const record: TurnTiming = {
    id: crypto.randomUUID(),
    verb,
    origin: spoken ? 'spoken' : 'typed',
    opened: new Date().toISOString(),
    speech_end_final_result: pending.finalResult,
    speech_end_recogniser_end: pending.recogniserEnd,
    sent: now(),
    received: null,
    outcome: null,
    audio: [],
  }
  pending = { finalResult: null, recogniserEnd: null }
  push(record)
}

/** The backend answered, one way or the other. A refusal is a response and is timed like one. */
export function responseReceived(outcome: 'accepted' | 'refused'): void {
  if (current === null) return
  current.received = now()
  current.outcome = outcome
}

/**
 * Sound actually began.
 *
 * A replay pressed when no turn has been taken opens a record of its own rather than attaching
 * itself to whatever turn happens to be last: an utterance nobody's turn produced must not end
 * up inside somebody's turn.
 */
export function audioStarted(utterance: SpokenKind): void {
  if (current === null) {
    push({
      id: crypto.randomUUID(),
      verb: null,
      origin: 'none',
      opened: new Date().toISOString(),
      speech_end_final_result: null,
      speech_end_recogniser_end: null,
      sent: null,
      received: null,
      outcome: null,
      audio: [],
    })
  }
  current?.audio.push({ utterance, at: now() })
}

function push(record: TurnTiming): void {
  records.push(record)
  while (records.length > KEPT) records.shift()
  current = record
}

/** Every record kept, copied, so a reader cannot edit the session's own history by holding it. */
export function turnTimings(): TurnTiming[] {
  return records.map((record) => ({ ...record, audio: record.audio.map((one) => ({ ...one })) }))
}

/** Start again. For tests; nothing in the product calls it. */
export function resetTurnTimings(): void {
  records.length = 0
  current = null
  pending = { finalResult: null, recogniserEnd: null }
}

/**
 * Make the records reachable from a real browser session.
 *
 * The whole point of the instrumentation is that somebody can run ten turns in an actual browser
 * and read the instants back afterwards, so there is a named handle on `window` and a JSON
 * rendering beside it for pasting into a file. It exposes readers and nothing that writes.
 */
export function publishTurnTimings(): void {
  const scope = window as unknown as {
    promisepatchVoiceTimings?: { records: () => TurnTiming[]; json: () => string }
  }
  scope.promisepatchVoiceTimings = {
    records: turnTimings,
    json: () => JSON.stringify(turnTimings(), null, 2),
  }
}
