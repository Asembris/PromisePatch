/**
 * The small carriers: a badge, a marker, and a promise state shown as three things at once.
 *
 * Every one of these prints a backend string verbatim and never a synonym. That is the whole
 * point of them: a paraphrase of "planned" is one word away from "done", so the vocabulary the
 * product is allowed to use lives in the domain and reaches the screen as text.
 */
import type { ReactNode } from 'react'
import {
  MARKER_CLASSES,
  TONE_PILL,
  TONE_TEXT,
  caseHeadlineTone,
  promiseStateTreatment,
  type Marker,
  type Tone,
} from './vocabulary'
import { Unknown } from './values'

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }): ReactNode {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-state leading-4 ring-1 ring-inset ${TONE_PILL[tone]}`}
    >
      {children}
    </span>
  )
}

/**
 * A shape. Decorative to a reader; load-bearing to a greyscale frame.
 *
 * With no `tone` it takes the surrounding `currentColor`, which is what a marker inside a
 * filled pill has to do — the `done` pill is near-white, and a marker painted in the `done`
 * token on top of it would be an invisible carrier.
 */
export function StateMarker({ marker, tone }: { marker: Marker; tone?: Tone }): ReactNode {
  return (
    <span
      aria-hidden="true"
      data-testid="state-marker"
      data-marker={marker}
      className={`inline-block shrink-0 ${tone === undefined ? '' : TONE_TEXT[tone]} ${MARKER_CLASSES[marker]}`}
    />
  )
}

/**
 * An engine string, printed as itself.
 *
 * This is used for the vocabularies the screen has no table for — an order state, a track
 * state, an engine classification. It is **always neutral**, deliberately: a badge that guessed
 * a tone from the shape of a word would be the screen inferring a meaning it was not given, and
 * that is exactly the function this replaced.
 */
export function StateBadge({ state }: { state: string | null }): ReactNode {
  if (state === null) return <Unknown />
  return <Badge>{state}</Badge>
}

/** A case headline, in the frame it sets. The name itself is always printed. */
export function CaseHeadlineBadge({ headline }: { headline: string }): ReactNode {
  return (
    <span data-testid="case-headline" data-headline={headline}>
      <Badge tone={caseHeadlineTone(headline)}>{headline}</Badge>
    </span>
  )
}

/**
 * One promise's status, carried three ways at once.
 *
 * The phrase is the reading, the state name is the same thing in the product's own vocabulary,
 * and the marker's shape is the third carrier — so the row separates from its neighbours in a
 * monochrome frame, and a reader who takes no colour from the screen at all loses nothing.
 *
 * Both strings are the backend's. Neither is shortened, re-cased or reworded here.
 */
export function PromiseStatePill({
  state,
  phrase,
}: {
  state: string
  phrase: string
}): ReactNode {
  const treatment = promiseStateTreatment(state)
  return (
    <span
      className="inline-flex items-center gap-2"
      data-testid="promise-status"
      data-state={state}
      data-tone={treatment.tone}
      data-finished={treatment.finished}
    >
      {/* `key` on the state, so the pill is a new element whenever the **server** reports a
          different one and the one-shot mark plays exactly then. It cannot play early: this
          component has no idea a turn is in flight, and the value it keys on is the backend's.
          With motion removed the pill is identical, because the animation adds no glyph, no
          colour and no word. */}
      <span
        key={state}
        data-motion="restate"
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-phrase font-medium ring-1 ring-inset ${TONE_PILL[treatment.tone]}`}
      >
        <StateMarker marker={treatment.marker} />
        {phrase}
      </span>
      <span className="font-mono text-state text-muted">{state}</span>
    </span>
  )
}
