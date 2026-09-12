/**
 * The four closed vocabularies the backend speaks, and what each value is allowed to look like.
 *
 * This module replaces a function that chose a colour by looking for substrings in a state
 * name. That function was the screen **deriving a meaning** rather than being handed one, and
 * it had a specific hazard in it: `UNAFFECTED` contains no negative fragment, so it matched the
 * success branch — one rename away from drawing "left alone" as an achievement.
 *
 * Everything here is an exhaustive `Record` over a closed union taken from
 * `promisepatch.domain.status_view`. That is the whole design: a state the backend adds is a
 * **compile error** in this file rather than a silent neutral badge on a worker's screen.
 *
 * Three rules the tables keep, and `tests/vocabulary.test.ts` holds each one to it.
 *
 * 1. **Nothing is carried by colour alone.** Every promise is shown with its phrase, its state
 *    name as text, and a marker whose *shape* differs — and no two states share both a tone and
 *    a marker shape, so a greyscale frame still separates them.
 * 2. **`done` belongs to `RECOVERED` and to nothing else.** It is the only reading that means
 *    the external order system's own state agreed, so it is the only value that may look
 *    finished. No case headline reaches it either: a settled case is not a recovered order.
 * 3. **Authority and execution are different channels.** `AUTHORITY_TONE` says whose permission
 *    a change needs; `PROMISE_STATE_TREATMENT` says what has actually happened. A lane's colour
 *    never claims progress, and a state's tone never claims permission.
 */

// ------------------------------------------------------------------------------------ tones

/**
 * A colour channel. These are palette names, not meanings — a tone is chosen by a table in this
 * file or by a call site that knows what it is saying, and it never carries a claim on its own.
 */
export type Tone = 'neutral' | 'auto' | 'ask' | 'owner' | 'done' | 'brand'

/** A filled pill's classes. */
export const TONE_PILL: Record<Tone, string> = {
  neutral: 'bg-panel text-ink ring-edge',
  auto: 'bg-auto/12 text-auto ring-auto/35',
  ask: 'bg-ask/12 text-ask ring-ask/35',
  owner: 'bg-owner/12 text-owner ring-owner/35',
  // The one near-white fill on the page, so it cannot be reached by accident.
  done: 'bg-done text-surface ring-done',
  brand: 'bg-brand/15 text-brand ring-brand/40',
}

/** A tone as foreground only, for a marker or an inline word. */
export const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-muted',
  auto: 'text-auto',
  ask: 'text-ask',
  owner: 'text-owner',
  done: 'text-done',
  brand: 'text-brand',
}

// ----------------------------------------------------------------------------------- markers

/**
 * The shape channel.
 *
 * A marker's *fill pattern* is what survives a monochrome video frame and a reader who cannot
 * separate the tones, so it is a first-class carrier rather than decoration.
 */
export type Marker =
  | 'hollow-circle'
  | 'hollow-square'
  | 'ring'
  | 'dashed'
  | 'half'
  | 'filled'
  | 'bar'

export const MARKER_CLASSES: Record<Marker, string> = {
  'hollow-circle': 'size-2.5 rounded-full border border-current',
  'hollow-square': 'size-2.5 rounded-[2px] border border-current',
  ring: 'size-2.5 rounded-full border-2 border-current',
  dashed: 'size-2.5 rounded-full border border-dashed border-current',
  half: 'size-2.5 rounded-full border border-current bg-[linear-gradient(90deg,currentColor_50%,transparent_50%)]',
  filled: 'size-2.5 rounded-full bg-current',
  // A terminal stop: this promise ends here, and it ends somewhere other than this case.
  bar: 'h-0.5 w-2.5 rounded-full bg-current',
}

// --------------------------------------------------------------------------- promise states

/** Every value `promisepatch.domain.status_view.PromiseState` can take. */
export const PROMISE_STATES = [
  'UNTOUCHED',
  'PLANNED',
  'AUTHORIZED',
  'REQUESTED',
  'CONSENTED',
  'DECLINED',
  'APPLYING',
  'RECOVERED',
  'ESCALATED',
  'STALE',
  'EXPIRED',
  'LINKED',
  'WITHDRAWN',
  'AWAITING_PLAN',
] as const

export type PromiseState = (typeof PROMISE_STATES)[number]

export interface StateTreatment {
  tone: Tone
  marker: Marker
  /**
   * May this state read as finished?
   *
   * True for exactly one value. Permission is not an act and an acknowledgement is not an
   * outcome, so `AUTHORIZED`, `CONSENTED`, `APPLYING` and `REQUESTED` are all false — each of
   * them is a real thing that has happened, and none of them is the change being made.
   */
  finished: boolean
}

export const PROMISE_STATE_TREATMENT: Record<PromiseState, StateTreatment> = {
  // Quiet ground, no success tone, and never omitted. "Left alone" is the absence of an
  // effect, not an achievement.
  UNTOUCHED: { tone: 'neutral', marker: 'ring', finished: false },
  // Nothing has been done. No tick, no completion tone, no past tense.
  PLANNED: { tone: 'neutral', marker: 'hollow-square', finished: false },
  // Permission granted and work queued — deliberately not sharing a look with RECOVERED.
  AUTHORIZED: { tone: 'auto', marker: 'hollow-circle', finished: false },
  // A provider acknowledged delivery. Nobody has replied.
  REQUESTED: { tone: 'ask', marker: 'hollow-circle', finished: false },
  // The customer's own literal decision, and work queued behind it.
  CONSENTED: { tone: 'ask', marker: 'filled', finished: false },
  // A settled answer the owner takes from here. Not a failure, not an error state.
  DECLINED: { tone: 'owner', marker: 'hollow-circle', finished: false },
  // In-flight work, shown honestly as in flight.
  APPLYING: { tone: 'auto', marker: 'half', finished: false },
  // The one finished reading, and only once the order system's own state agreed.
  RECOVERED: { tone: 'done', marker: 'filled', finished: true },
  // Work on somebody's desk. Prominent, and never styled as a crash.
  ESCALATED: { tone: 'owner', marker: 'half', finished: false },
  // Revalidation refused and the track was re-planned. Not a retry in progress.
  STALE: { tone: 'owner', marker: 'hollow-square', finished: false },
  // The timer fired with no decision. Never drawn as a decline — nobody said no.
  EXPIRED: { tone: 'owner', marker: 'dashed', finished: false },
  // Left to somebody else rather than left alone, so it sits outside the untouched set.
  LINKED: { tone: 'neutral', marker: 'bar', finished: false },
  WITHDRAWN: { tone: 'neutral', marker: 'hollow-circle', finished: false },
  // The fail-closed default: the case has not finished deciding, and that is all it says.
  AWAITING_PLAN: { tone: 'neutral', marker: 'dashed', finished: false },
}

const PROMISE_STATE_SET: ReadonlySet<string> = new Set<string>(PROMISE_STATES)

export function isPromiseState(value: string): value is PromiseState {
  return PROMISE_STATE_SET.has(value)
}

/**
 * The treatment for a state string off the wire.
 *
 * A value this build has never heard of gets `AWAITING_PLAN`'s treatment — the domain's own
 * fail-closed default — so an unforeseen posture understates rather than lies. It can never
 * land on a finished reading, and the state name itself is still printed verbatim beside it.
 */
export function promiseStateTreatment(state: string): StateTreatment {
  return isPromiseState(state)
    ? PROMISE_STATE_TREATMENT[state]
    : PROMISE_STATE_TREATMENT.AWAITING_PLAN
}

// ---------------------------------------------------------------------------- case headlines

/** Every value `promisepatch.domain.status_view.CaseHeadline` can take. */
export const CASE_HEADLINES = [
  'UNDERSTANDING',
  'CLARIFYING',
  'NEEDS_HUMAN',
  'ANALYSED',
  'PLANNED',
  'WORKING',
  'WAITING',
  'SETTLED',
  'CANCELLED',
] as const

export type CaseHeadline = (typeof CASE_HEADLINES)[number]

/**
 * The frame a case sits in.
 *
 * `SETTLED` is deliberately neutral. A settled case is a case that has stopped, which is not
 * the same claim as an order that changed — and giving it the `done` tone would let a terminal
 * case with an escalation still open read as a success at a glance.
 */
export const CASE_HEADLINE_TONE: Record<CaseHeadline, Tone> = {
  UNDERSTANDING: 'neutral',
  CLARIFYING: 'ask',
  // A person is asked to read the report. A normal posture, not an error.
  NEEDS_HUMAN: 'brand',
  ANALYSED: 'neutral',
  // The only headline under which a confirm affordance may exist, so it takes the
  // worker-interaction colour rather than a state colour.
  PLANNED: 'brand',
  WORKING: 'auto',
  WAITING: 'ask',
  SETTLED: 'neutral',
  CANCELLED: 'neutral',
}

const CASE_HEADLINE_SET: ReadonlySet<string> = new Set<string>(CASE_HEADLINES)

export function caseHeadlineTone(headline: string): Tone {
  return CASE_HEADLINE_SET.has(headline)
    ? CASE_HEADLINE_TONE[headline as CaseHeadline]
    : 'neutral'
}

// ------------------------------------------------------------------- owners and authorities

/** Every value `promisepatch.domain.status_view.ActionOwner` can take. */
export const ACTION_OWNERS = ['YOU', 'OWNER', 'CUSTOMER', 'SYSTEM', 'NOBODY'] as const
export type ActionOwner = (typeof ACTION_OWNERS)[number]

/**
 * Whose move it is.
 *
 * `YOU` takes the interaction colour because the worker's own move is the only one a control on
 * this surface could ever belong to. `NOBODY` is a real answer and is shown as one.
 */
export const ACTION_OWNER_TONE: Record<ActionOwner, Tone> = {
  YOU: 'brand',
  OWNER: 'owner',
  CUSTOMER: 'ask',
  SYSTEM: 'auto',
  NOBODY: 'neutral',
}

const ACTION_OWNER_SET: ReadonlySet<string> = new Set<string>(ACTION_OWNERS)

export function actionOwnerTone(owner: string): Tone {
  return ACTION_OWNER_SET.has(owner) ? ACTION_OWNER_TONE[owner as ActionOwner] : 'neutral'
}

/** Every value `promisepatch.domain.status_view.Authority` can take. */
export const AUTHORITIES = [
  'NONE',
  'STANDING_PREFERENCE',
  'CUSTOMER',
  'OWNER',
  'UNDECIDED',
] as const
export type Authority = (typeof AUTHORITIES)[number]

/** Whose permission a group of changes needs. Says nothing about whether anything happened. */
export const AUTHORITY_TONE: Record<Authority, Tone> = {
  NONE: 'neutral',
  STANDING_PREFERENCE: 'auto',
  CUSTOMER: 'ask',
  OWNER: 'owner',
  UNDECIDED: 'neutral',
}

const AUTHORITY_SET: ReadonlySet<string> = new Set<string>(AUTHORITIES)

export function authorityTone(authority: string): Tone {
  return AUTHORITY_SET.has(authority) ? AUTHORITY_TONE[authority as Authority] : 'neutral'
}
