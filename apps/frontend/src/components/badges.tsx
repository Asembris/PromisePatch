/**
 * The small text carriers: a badge, and a state shown as a state.
 *
 * `StateBadge` prints the backend's state name verbatim and never a synonym. That is the whole
 * point of it: a paraphrase of "planned" is one word away from "done", so the vocabulary the
 * product is allowed to use lives in the domain and reaches the screen as a string.
 */
import type { ReactNode } from 'react'
import { TONE_CLASSES, toneForState, type BadgeTone } from './tones'
import { Unknown } from './values'

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: BadgeTone
  children: ReactNode
}): ReactNode {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-state leading-4 ring-1 ring-inset ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}

/** A state string from the backend, shown verbatim with a tone chosen only for legibility. */
export function StateBadge({ state }: { state: string | null }): ReactNode {
  if (state === null) return <Unknown />
  return <Badge tone={toneForState(state)}>{state}</Badge>
}
