/**
 * The handful of display primitives the screen is built from.
 *
 * They format and they do not decide. `Unknown` is the important one: an absent value from the
 * backend means *unknown*, the engine fails closed on it, and every place that could be
 * tempted to print `0` or an empty cell instead routes through here so that the distinction
 * survives to the screen.
 */
import type { ReactNode } from 'react'
import { TONE_CLASSES, toneForState, type BadgeTone } from './tones'

/** What an absent value looks like. Never a zero, never a blank cell. */
export function Unknown(): ReactNode {
  return (
    <span className="text-muted italic" title="unknown — the backend returned no value">
      unknown
    </span>
  )
}

/** A value, or the explicit unknown marker when the backend sent `null`. */
export function Value({ children }: { children: string | null | undefined }): ReactNode {
  if (children === null || children === undefined || children === '') return <Unknown />
  return <>{children}</>
}

/**
 * A quantity, rendered as the string the backend sent.
 *
 * Deliberately not parsed. The engine's arithmetic is decimal and is serialised as a
 * fixed-point string precisely so it cannot be perturbed by a binary float on the way to a
 * display; converting it here to right-align it more prettily would reintroduce the problem
 * the representation was chosen to avoid. A negative value is a shortfall and is shown as one.
 */
export function QuantityValue({ value }: { value: string | null }): ReactNode {
  if (value === null) return <Unknown />
  const negative = value.trimStart().startsWith('-')
  return (
    <span className={`font-mono tabular-nums ${negative ? 'font-semibold text-red-700' : ''}`}>
      {value}
    </span>
  )
}

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: BadgeTone
  children: ReactNode
}): ReactNode {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] leading-4 ring-1 ring-inset ${TONE_CLASSES[tone]}`}
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

export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: ReactNode
  children: ReactNode
}): ReactNode {
  return (
    <section className="rounded-lg border border-edge bg-panel shadow-xs">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-edge px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {subtitle ? <p className="text-xs text-muted">{subtitle}</p> : null}
      </header>
      {children}
    </section>
  )
}

export function Notice({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'bad'
  children: ReactNode
}): ReactNode {
  const style =
    tone === 'bad' ? 'border-red-200 bg-red-50 text-red-800' : 'border-edge bg-surface text-muted'
  return <p className={`m-4 rounded border px-3 py-2 text-sm ${style}`}>{children}</p>
}
